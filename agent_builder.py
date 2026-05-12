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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import shutil
from datetime import datetime, timezone

from agent_search import (
    AUTOBUILD_AGENTS_REL,
    USER_AGENTS_REL,
    AgentDoc,
    discover_indexable_agents,
    invalidate_cache,
)


# Directory layout for versioning + approval:
#   .open-code/autobuild-agents/
#     <name>.md                  -- the live agent
#     .history/<name>/<ts>.md    -- archived prior versions
#     .pending/<name>.md         -- waiting for user approval (when
#                                   autobuild.auto_approve is False)
HISTORY_SUBDIR = ".history"
PENDING_SUBDIR = ".pending"


def _history_dir(cwd: Path, name: str) -> Path:
    return cwd / AUTOBUILD_AGENTS_REL / HISTORY_SUBDIR / name


def _pending_dir(cwd: Path) -> Path:
    return cwd / AUTOBUILD_AGENTS_REL / PENDING_SUBDIR


def _archive_existing(cwd: Path, name: str, current_path: Path) -> Path | None:
    """If `current_path` exists, copy it to .history/<name>/<iso-ts>.md.
    Returns the archive path (or None if there was nothing to archive).

    Microsecond resolution in the filename prevents collision when
    two archives happen in quick succession (e.g. a revert that
    immediately re-archives the outgoing version).
    """
    if not current_path.is_file():
        return None
    hist = _history_dir(cwd, name)
    hist.mkdir(parents=True, exist_ok=True)
    # %f gives microseconds; we keep them in the filename so the
    # alphabetic sort (newest first via reverse=True) is also
    # chronologically correct.
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    archive = hist / f"{ts}.md"
    # Belt + braces: if a collision somehow still occurs (clock skew
    # on a clearly-broken system), tack on an incrementing suffix.
    n = 2
    while archive.exists():
        archive = hist / f"{ts}-{n}.md"
        n += 1
    try:
        shutil.copy2(current_path, archive)
        return archive
    except OSError:
        return None


def list_versions(cwd: Path, name: str) -> list[Path]:
    """Returns archived versions of `name`, newest first."""
    hist = _history_dir(cwd, name)
    if not hist.is_dir():
        return []
    return sorted(hist.glob("*.md"), key=lambda p: p.name, reverse=True)


def revert_to_version(
    cwd: Path, name: str, version_ts: str | None = None,
) -> tuple[bool, str]:
    """Restore an agent from history.

    If `version_ts` is None, restores the most recent archived version.
    Otherwise restores the version whose filename starts with
    `version_ts` (so prefix match on "2026-05-12" works).

    Returns (ok, message).
    """
    versions = list_versions(cwd, name)
    if not versions:
        return False, f"no archived versions for {name!r}"
    if version_ts is None:
        target = versions[0]
    else:
        match = [v for v in versions if v.name.startswith(version_ts)]
        if not match:
            return False, (
                f"no version matching {version_ts!r}; "
                f"have {[v.name for v in versions[:5]]}"
            )
        target = match[0]
    live = cwd / AUTOBUILD_AGENTS_REL / f"{name}.md"
    # Archive the current live version BEFORE overwriting it, so
    # revert is itself reversible.
    _archive_existing(cwd, name, live)
    try:
        shutil.copy2(target, live)
    except OSError as exc:
        return False, f"failed to restore: {exc}"
    invalidate_cache(cwd)
    return True, f"restored {name} from {target.name}"


def list_pending(cwd: Path) -> list[Path]:
    """Returns pending agent specs awaiting user approval."""
    d = _pending_dir(cwd)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.md"))


def approve_pending(cwd: Path, name: str) -> tuple[bool, str, Path | None]:
    """Move a pending spec to live + archive any prior version.

    Returns (ok, message, live_path).
    """
    pending = _pending_dir(cwd) / f"{name}.md"
    if not pending.is_file():
        return False, f"no pending spec named {name!r}", None
    live = cwd / AUTOBUILD_AGENTS_REL / f"{name}.md"
    _archive_existing(cwd, name, live)
    try:
        shutil.copy2(pending, live)
        pending.unlink()
    except OSError as exc:
        return False, f"approve failed: {exc}", None
    invalidate_cache(cwd)
    return True, f"approved {name}", live


def reject_pending(cwd: Path, name: str) -> tuple[bool, str]:
    """Delete a pending spec without promoting it."""
    pending = _pending_dir(cwd) / f"{name}.md"
    if not pending.is_file():
        return False, f"no pending spec named {name!r}"
    try:
        pending.unlink()
    except OSError as exc:
        return False, f"reject failed: {exc}"
    return True, f"rejected {name}"


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
allowed-tools: [<subset of read_file, list_dir>]
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
- allowed-tools is a subset of [read_file, list_dir]. The build
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
    # Y2 fix: signal to the caller (and downstream to the LLM) that
    # the LLM-proposed tool list was narrowed during validation.
    # Without this, an autobuilt agent ostensibly granted run_shell
    # silently runs read-only; the model would issue shell tasks and
    # be confused by repeated tool denials.
    tools_adjusted: bool = False
    dropped_tools: list[str] = field(default_factory=list)
    final_tools: list[str] = field(default_factory=list)


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

    # Read both forms defensively: meta-prompt now says "allowed-tools"
    # (matching subagents.py since v0.4) but an LLM trained on older
    # versions of this codebase may still emit underscore.
    allowed_tools_raw = (
        fm.get("allowed-tools") or fm.get("allowed_tools") or ""
    )
    allowed_tools_pre_filter = _parse_list_field(allowed_tools_raw)
    allowed_tools = [
        t for t in allowed_tools_pre_filter if t in DEFAULT_ALLOWED_TOOLS
    ]
    # Y2 fix: track whether the allowlist filter dropped anything OR
    # we defaulted to read-only. The caller surfaces this to the model
    # so it doesn't mistakenly believe the specialist has write/shell
    # capability.
    tools_adjusted = (
        set(allowed_tools) != set(allowed_tools_pre_filter)
    )
    dropped_tools = [
        t for t in allowed_tools_pre_filter if t not in DEFAULT_ALLOWED_TOOLS
    ]
    if not allowed_tools:
        # Default to read-only inspection capability.
        allowed_tools = list(DEFAULT_ALLOWED_TOOLS)
        tools_adjusted = True

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
        "tools_adjusted": tools_adjusted,
        "dropped_tools": dropped_tools,
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
    # B1 fix: emit `allowed-tools` (hyphen) -- the canonical key the
    # subagents loader reads. The previous underscore form silently
    # made every autobuild agent run unrestricted (privilege escalation).
    fm = (
        "---\n"
        f"name: {meta['name']}\n"
        f"description: {meta['description']}\n"
        f"domain: {meta['domain']}\n"
        f"capabilities: [{caps_inline}]\n"
        f"allowed-tools: [{tools_inline}]\n"
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
    auto_approve: bool = True,
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
            tools_adjusted=meta.get("tools_adjusted", False),
            dropped_tools=list(meta.get("dropped_tools", [])),
            final_tools=list(meta.get("allowed_tools", [])),
        )

    # Resolve target location. auto_approve=False routes to the
    # .pending/ subdir; the user must run /autobuild approve <name>
    # to promote.
    autobuild_root = cwd / AUTOBUILD_AGENTS_REL
    autobuild_root.mkdir(parents=True, exist_ok=True)
    if auto_approve:
        target_dir = autobuild_root
    else:
        target_dir = autobuild_root / PENDING_SUBDIR
        target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{meta['name']}.md"
    # B1 + Path safety: re-resolve and confirm the path lives strictly
    # inside the autobuild directory before writing. The name regex
    # ^[a-z][a-z0-9-]*$ already prevents traversal, but a layered
    # check here is cheap and means a future regex regression can't
    # let `..` reach disk.
    try:
        resolved = target_path.resolve(strict=False)
        root_resolved = autobuild_root.resolve(strict=False)
        if not str(resolved).startswith(str(root_resolved)):
            return BuildResult(
                ok=False,
                error=(
                    f"refusing to write outside autobuild dir: "
                    f"{resolved} not under {root_resolved}"
                ),
                raw_response=raw,
            )
    except OSError as exc:
        return BuildResult(
            ok=False, error=f"path resolution failed: {exc}",
            raw_response=raw,
        )
    # Versioning: when overwriting an existing LIVE agent (auto_approve
    # path, name collided through validator's dedup), archive the
    # outgoing copy before writing. Validator's _unique_name suffixes
    # collisions, so the LIVE path is fresh by name; this still
    # protects against future edits that re-build under the same name.
    if auto_approve and target_path.is_file():
        _archive_existing(cwd, meta["name"], target_path)
    try:
        target_path.write_text(_serialize(meta), encoding="utf-8")
    except OSError as exc:
        return BuildResult(
            ok=False,
            error=f"failed to write {target_path}: {exc}",
            raw_response=raw,
        )
    if auto_approve:
        invalidate_cache(cwd)
    return BuildResult(
        ok=True,
        name=meta["name"],
        path=target_path,
        domain=meta["domain"],
        tools_adjusted=meta.get("tools_adjusted", False),
        dropped_tools=list(meta.get("dropped_tools", [])),
        final_tools=list(meta.get("allowed_tools", [])),
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
        "tools_adjusted": result.tools_adjusted,
        "dropped_tools": list(result.dropped_tools),
        "final_tools": list(result.final_tools),
        "domain": result.domain,
        "description": result.description,
        "error": result.error,
    }
