"""Dynamic specialist-agent builder.

Goal: when the user asks something domain-specific (SQL, ML, web-scraping,
infra, security, ...), the system either finds an existing specialist
or builds a high-quality one and saves it. Subsequent questions in the
same domain hit the cache.

What "high quality" means here:
- A specialist isn't just a one-line system prompt. It's a structured
  agent file with: role, domain expert knowledge (best practices),
  workflow (numbered steps), output format, worked examples, edge
  cases, refusal cases. This structure is enforced by the meta-prompt
  AND by post-generation validation.
- The meta-prompt is a one-shot LLM call against a strict template.
  Outputs that don't parse cleanly are rejected; the caller can retry.
- Names are kebab-case + suffixed `-agent`, deduplicated against the
  existing library.
- Saved under `.open-code/autobuild-agents/<name>.md`. Doesn't touch
  `.open-code/agents/` (user-curated agents are sacred).

Failure modes handled:
- Meta-prompt produces malformed frontmatter -> validate, return error
- Generated name collides with existing -> suffix `-2`, `-3`, ...
- Empty or trivial body -> reject
- Disallowed tools -> filter against TOOL_FUNCTIONS allowlist

Honest trade-off:
- This is one LLM call per specialist built. ~1k input tokens + ~2k
  output. The infrastructure caches aggressively so users pay this
  once per domain encountered, not once per question.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_search import (
    AUTOBUILD_AGENTS_REL,
    USER_AGENTS_REL,
    AgentDoc,
    discover_indexable_agents,
    invalidate_cache,
)


# Tools we permit auto-built specialists to use. Conservative on
# purpose: a fresh agent shouldn't get run_shell + write_file by
# default unless the user explicitly allows it.
DEFAULT_ALLOWED_TOOLS = ("read_file", "list_dir")
TOOLS_OPT_IN = ("write_file", "run_shell", "apply_patch")


# The agent-architect meta-prompt. This is the most important string
# in this module -- specialist quality is bounded by this template.
META_PROMPT_TEMPLATE = """\
You are an expert agent designer. The user has hit a task that needs
a specialist their open-code library doesn't yet have. Your job is
to author a high-quality, reusable specialist agent.

Output MUST be a complete markdown file in EXACTLY this shape (no
explanation outside, no triple-backtick fence around it):

---
name: <kebab-case-name>
description: <one sentence, BM25-searchable; concrete keywords>
domain: <single lowercase word: sql | data | web | ml | infra | security | docs | testing | other>
capabilities: [<list>, <of>, <searchable>, <keywords>]
allowed_tools: [<subset of read_file, list_dir>]
model: null
---

# <Title>

## Role
<One paragraph: what THIS specialist does and the rigorous discipline
it follows. Use the second person addressing the agent itself.>

## Expert knowledge
- <First key best practice for this domain (concrete, not generic)>
- <Second>
- <Third>
- <Fourth>
- <Fifth>

## Workflow
1. <First numbered step the specialist takes>
2. <Second>
3. <Third>
4. <Fourth>

## Output format
<Specification of what the user receives. If code: language + style.
If analysis: structure. Be specific.>

## Examples

### Example 1
**Input:** <example user prompt in this domain>
**Approach:** <one or two sentences of reasoning>
**Output:**
```
<expected high-quality output, properly formatted>
```

### Example 2
**Input:** <another example, ideally edge-case-y>
**Approach:** <reasoning>
**Output:**
```
<expected output>
```

## Edge cases
- <First edge case the specialist must handle>
- <Second>
- <Third>

## Refusal cases
- <Tasks the specialist should refuse and how to phrase the refusal>

---

Context for THIS specialist build:

Domain hint:        {domain}
Example user task:  {task_example}
Additional notes:   {notes}

Existing specialists (do NOT duplicate; pick a name distinct from
these):
{existing_names}

Rules you MUST follow:
- The name must be kebab-case (lowercase, hyphens). Suffix with `-agent`
  if not already.
- description must be ONE sentence, under 140 characters, packed
  with concrete keywords that will help BM25 retrieval.
- domain must be one of: sql, data, web, ml, infra, security, docs,
  testing, other.
- capabilities must be 3-8 specific keywords (NOT generic words like
  "general" or "tasks").
- allowed_tools is a subset of [read_file, list_dir]. The build
  process will reject anything else.
- Expert knowledge bullets must be concrete domain rules, NOT
  motherhood-and-apple-pie statements.
- Examples must be substantive: actual queries, actual code, actual
  output structures.
- Output ONLY the markdown file. No preamble, no postscript, no
  triple-backtick fence around the whole thing.
"""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


VALID_DOMAINS = (
    "sql", "data", "web", "ml", "infra",
    "security", "docs", "testing", "other",
)


@dataclass
class BuildResult:
    """Outcome of a build_agent call."""
    ok: bool
    name: str = ""
    path: Path | None = None
    domain: str = ""
    description: str = ""
    error: str = ""
    raw_response: str = ""


_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str]:
    """Return (frontmatter_dict, body_text, error_if_any)."""
    if not text.startswith("---"):
        return {}, "", "missing leading `---` frontmatter fence"
    end = text.find("\n---", 3)
    if end < 0:
        return {}, "", "missing closing `---` fence"
    raw = text[3:end].lstrip("\n").rstrip()
    body = text[end + 4:].lstrip("\n")
    fm: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm, body, ""


def _parse_list_field(value: str) -> list[str]:
    if not value:
        return []
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [p.strip().strip("'\"") for p in v.split(",") if p.strip()]


def _unique_name(base: str, existing: set[str]) -> str:
    """Suffix -2, -3, ... until unique. Idempotent if base is already unique."""
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def validate_generated_agent(
    text: str,
    existing_names: set[str],
) -> tuple[bool, dict[str, Any], str]:
    """Parse + validate. Returns (ok, parsed_meta, error)."""
    text = text.strip()
    # Strip a possible outer ``` fence the model sometimes adds despite
    # the explicit instruction not to.
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl > 0:
            text = text[first_nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip().rstrip("`").rstrip()
    fm, body, err = _parse_frontmatter(text)
    if err:
        return False, {}, err

    name = (fm.get("name") or "").strip()
    if not name:
        return False, {}, "frontmatter missing `name`"
    if not _NAME_RE.match(name):
        return False, {}, (
            f"name {name!r} is not kebab-case; expected ^[a-z][a-z0-9-]*$"
        )
    if not name.endswith("-agent"):
        # Soft-fix: suffix `-agent` if missing.
        name = f"{name}-agent"
    name = _unique_name(name, existing_names)

    desc = (fm.get("description") or "").strip()
    if len(desc) < 8:
        return False, {}, "description too short or missing"
    if len(desc) > 200:
        desc = desc[:200].rstrip()

    domain = (fm.get("domain") or "other").strip().lower()
    if domain not in VALID_DOMAINS:
        domain = "other"

    capabilities = _parse_list_field(fm.get("capabilities", ""))
    if len(capabilities) < 2:
        return False, {}, "capabilities must list at least 2 keywords"

    allowed_tools = _parse_list_field(fm.get("allowed_tools", ""))
    # Filter against the allowlist.
    allowed_tools = [t for t in allowed_tools if t in DEFAULT_ALLOWED_TOOLS]
    if not allowed_tools:
        # Default to read-only inspection capability.
        allowed_tools = list(DEFAULT_ALLOWED_TOOLS)

    # Body sanity: must contain the structural section headers.
    REQUIRED_SECTIONS = (
        "## Role", "## Expert knowledge", "## Workflow",
        "## Output format", "## Examples",
    )
    missing = [s for s in REQUIRED_SECTIONS if s not in body]
    if missing:
        return False, {}, (
            f"body missing required sections: {', '.join(missing)}"
        )

    return True, {
        "name": name,
        "description": desc,
        "domain": domain,
        "capabilities": capabilities,
        "allowed_tools": allowed_tools,
        "body": body.strip() + "\n",
    }, ""


def _serialize(meta: dict[str, Any]) -> str:
    """Render the validated meta back to a clean markdown file.

    Frontmatter is regenerated rather than passed through verbatim so
    we know the on-disk format always parses with our own readers
    (skills.py, subagents.py, agent_search.py).
    """
    caps_inline = ", ".join(meta["capabilities"])
    tools_inline = ", ".join(meta["allowed_tools"])
    fm = (
        "---\n"
        f"name: {meta['name']}\n"
        f"description: {meta['description']}\n"
        f"domain: {meta['domain']}\n"
        f"capabilities: [{caps_inline}]\n"
        f"allowed_tools: [{tools_inline}]\n"
        "model: null\n"
        "---\n\n"
    )
    return fm + meta["body"]


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------


# A `LLMCallable` is any function that takes a prompt string and
# returns the model's response. Decoupling the meta-prompt invocation
# from the genai client lets tests inject a deterministic stub and
# lets the caller pick the model (typically the same one driving the
# REPL, but could be a different "architect" model).
LLMCallable = Callable[[str], str]


def render_meta_prompt(
    *,
    domain_hint: str,
    task_example: str,
    notes: str,
    existing: list[AgentDoc],
) -> str:
    existing_lines = "\n".join(
        f"- {a.name}: {a.description}" for a in existing[:30]
    ) or "(none yet)"
    return META_PROMPT_TEMPLATE.format(
        domain=domain_hint or "(unspecified)",
        task_example=task_example or "(unspecified)",
        notes=notes or "(none)",
        existing_names=existing_lines,
    )


def build_agent(
    cwd: Path,
    *,
    llm: LLMCallable,
    domain_hint: str = "",
    task_example: str = "",
    notes: str = "",
    dry_run: bool = False,
) -> BuildResult:
    """End-to-end: generate, validate, save, refresh index.

    `llm(prompt) -> response` is the only external dependency.
    Callers wire it to their genai client.

    `dry_run=True` returns the parsed meta WITHOUT writing to disk
    (useful for previewing in a REPL approval flow).
    """
    existing = discover_indexable_agents(cwd)
    existing_names = {a.name for a in existing}
    prompt = render_meta_prompt(
        domain_hint=domain_hint,
        task_example=task_example,
        notes=notes,
        existing=existing,
    )
    try:
        raw = llm(prompt)
    except Exception as exc:
        return BuildResult(
            ok=False,
            error=f"meta-prompt LLM call failed: {type(exc).__name__}: {exc}",
            raw_response="",
        )
    ok, meta, err = validate_generated_agent(raw, existing_names)
    if not ok:
        return BuildResult(
            ok=False,
            error=f"validation failed: {err}",
            raw_response=raw,
        )

    if dry_run:
        return BuildResult(
            ok=True,
            name=meta["name"],
            path=None,
            domain=meta["domain"],
            description=meta["description"],
            raw_response=raw,
        )

    # Write to .open-code/autobuild-agents/<name>.md
    target_dir = cwd / AUTOBUILD_AGENTS_REL
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{meta['name']}.md"
    try:
        target_path.write_text(_serialize(meta), encoding="utf-8")
    except OSError as exc:
        return BuildResult(
            ok=False,
            error=f"failed to write {target_path}: {exc}",
            raw_response=raw,
        )
    invalidate_cache(cwd)
    return BuildResult(
        ok=True,
        name=meta["name"],
        path=target_path,
        domain=meta["domain"],
        description=meta["description"],
        raw_response=raw,
    )


# ---------------------------------------------------------------------------
# A simple JSON event for telemetry / --print integration
# ---------------------------------------------------------------------------


def build_event_payload(result: BuildResult) -> dict[str, Any]:
    """Shape used by `_emit_json` when --print mode reports a build."""
    return {
        "type": "agent_built" if result.ok else "agent_build_failed",
        "name": result.name,
        "path": str(result.path) if result.path else "",
        "domain": result.domain,
        "description": result.description,
        "error": result.error,
    }
