"""Subagents (Task tool) for open-code.

A subagent is a named preset under `.open-code/agents/<name>.md`:

    ---
    name: explorer
    description: Read-only investigator. Map the repo, summarize.
    allowed-tools: read_file, list_dir
    model: gemini-3.1-flash-lite-preview
    ---
    You are an exploration subagent. Your job is to read the repo
    and produce a 5-bullet summary of what each top-level dir does.
    Do NOT write files or run shell commands. Just read.

When the main agent calls `delegate(agent="explorer", task="...")`:

  1. We load the matching agent definition.
  2. We open a fresh JSONL transcript at
     `<parent>.subagent.<idx>.jsonl` and add a session header that
     links back to the parent session.
  3. We invoke `run_loop` with the subagent's system prompt and a
     restricted TOOL_DECLARATIONS subset (filtered by allowed-tools).
  4. We read the subagent's final model text and return it as the
     `summary` of the tool result. We also write a `delegate` event
     into the parent's JSONL pointing at the subagent transcript.

The subagent has NO access to the `delegate` tool itself -- no
recursion.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sessions import JSONL_VERSION, Session


AGENTS_REL = ".open-code/agents"
DEFAULT_SUBAGENT_MAX_ITERATIONS = 10


@dataclass
class Agent:
    """In-memory representation of an agent definition."""
    name: str
    description: str
    system_prompt: str  # the body of the agent .md
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    path: Path | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Same minimal YAML subset as skills.py -- keep them in sync."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    raw = text[3:end].lstrip("\n").rstrip()
    body = text[end + 4:].lstrip("\n")
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm, body


def _parse_list(value: str) -> list[str]:
    if not value:
        return []
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    parts = [p.strip().strip("'\"") for p in v.split(",")]
    return [p for p in parts if p]


def load_agent_file(path: Path) -> Agent | None:
    """Parse an agent .md path into an Agent object, or None if malformed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _parse_frontmatter(text)
    name = fm.get("name", "").strip() or path.stem
    return Agent(
        name=name,
        description=fm.get("description", "").strip(),
        system_prompt=body.strip(),
        allowed_tools=_parse_list(fm.get("allowed-tools", "")),
        model=(fm.get("model", "").strip() or None),
        path=path,
    )


def discover_agents(cwd: Path) -> list[Agent]:
    """Find every `*.md` under both `.open-code/agents/` and
    `.open-code/autobuild-agents/` (Tier 3 -- dynamic agent library).

    Hand-written agents take precedence on name collision: a user
    deliberately curated agent can't be shadowed by an autobuild.
    """
    by_name: dict[str, Agent] = {}
    # Autobuild first; hand-written overrides below.
    autobuild = cwd / ".open-code/autobuild-agents"
    if autobuild.exists() and autobuild.is_dir():
        for p in sorted(autobuild.iterdir()):
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            a = load_agent_file(p)
            if a is not None:
                by_name[a.name] = a
    root = cwd / AGENTS_REL
    if root.exists() and root.is_dir():
        for p in sorted(root.iterdir()):
            if not p.is_file() or p.suffix.lower() != ".md":
                continue
            a = load_agent_file(p)
            if a is not None:
                by_name[a.name] = a  # user shadows autobuild
    return list(by_name.values())


def find_agent_by_name(cwd: Path, name: str) -> Agent | None:
    for a in discover_agents(cwd):
        if a.name == name:
            return a
    return None


def render_agent_listing(agents: list[Agent]) -> str:
    if not agents:
        return "(no agents defined; create .open-code/agents/<name>.md)"
    lines = [f"{'NAME':<18}  {'MODEL':<35}  DESCRIPTION"]
    lines.append("-" * 100)
    for a in agents:
        m = a.model or "(default)"
        desc = a.description or ""
        if len(desc) > 40:
            desc = desc[:37] + "..."
        lines.append(f"{a.name:<18}  {m:<35}  {desc}")
    return "\n".join(lines)


def open_subagent_transcript(
    parent_session: Session,
    *,
    agent_name: str,
    task: str,
    model: str,
) -> Session:
    """Create a sibling JSONL for a subagent run.

    Path: `<parent.path>.subagent.<idx>.jsonl` where <idx> is the next
    free integer. Writes a session header that includes
    `parent_session` (UUID) and `agent_name` so the file is self-
    describing.

    Returns a synthetic Session pointing at the new file. The same
    SessionStore methods (append_message, append_metrics, etc.) work
    on it because they only need `session.path`.
    """
    parent_dir = parent_session.path.parent
    base_stem = parent_session.path.stem
    idx = 0
    while True:
        candidate = parent_dir / f"{base_stem}.subagent.{idx}.jsonl"
        if not candidate.exists():
            break
        idx += 1
    sid = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    header = {
        "kind": "session",
        "v": JSONL_VERSION,
        "id": sid,
        "cwd": parent_session.cwd,
        "model": model,
        "task": task,
        "started_at": started,
        "parent_session": parent_session.id,
        "agent_name": agent_name,
    }
    with candidate.open("w", encoding="utf-8") as f:
        f.write(json.dumps(header) + "\n")
        f.flush()
    return Session(
        id=sid,
        cwd=parent_session.cwd,
        model=model,
        task=task,
        started_at=started,
        path=candidate,
    )


def append_delegate_event(
    parent_session: Session,
    *,
    agent_name: str,
    task: str,
    subagent_session_id: str,
    transcript_path: Path,
    summary: str,
    exit_code: int,
) -> None:
    """Write a `delegate` event into the PARENT JSONL summarizing the
    subagent's run. The full subagent transcript lives in its own file."""
    ev = {
        "kind": "delegate",
        "agent": agent_name,
        "task": task,
        "subagent_session_id": subagent_session_id,
        "transcript_path": str(transcript_path),
        "summary": summary,
        "exit_code": exit_code,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with parent_session.path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev) + "\n")
        f.flush()


DELEGATE_TOOL_DECLARATION = {
    "name": "delegate",
    "description": (
        "Delegate a focused subtask to a named subagent (defined under "
        ".open-code/agents/). The subagent runs in isolated context with "
        "a restricted tool allowlist; you receive only its final summary "
        "text. Use this for research-heavy or specialized tasks where you "
        "want to keep your own context clean."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "agent": {
                "type": "STRING",
                "description": "Subagent name (see /agents for the list).",
            },
            "task": {
                "type": "STRING",
                "description": "What the subagent should investigate or produce.",
            },
        },
        "required": ["agent", "task"],
    },
}
