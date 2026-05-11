"""Skills system for open-code (Claude Code-style).

A "skill" is a reusable, named prompt template that lives at:

    <project>/.open-code/skills/<name>/SKILL.md

SKILL.md format:

    ---
    name: review-pr
    description: Brutal-review a pull request against project standards
    allowed-tools: read_file, list_dir, run_shell
    disable-model-invocation: false
    ---
    You are reviewing PR $ARGUMENTS.

    Project state:
    !`git status --short`
    !`git diff main --stat | head -40`

    Walk the diff. Find: untested branches, surface-area widening, ...

Invocation (REPL):  /skill review-pr 1234

What the user types becomes `$ARGUMENTS` and `$1`, `$2`, ... `$N`
(space-split positional). The body's `` !`cmd` `` blocks are resolved
via subprocess.run before the body reaches the model — the model
sees only the resolved text.

`disable-model-invocation: true` is reserved for future auto-discovery
(v0.8+). v0.7 ships explicit `/skill` invocation only.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Reasonable cap; matches the file ref cap. Skill bodies are template
# prompts, not data dumps.
MAX_SKILL_BODY_BYTES = 50_000
SKILLS_REL = ".open-code/skills"
COMMAND_TIMEOUT_SECS = 20

# Tier 2 #21 — skill prompt caching. Skills with frontmatter
# `cache: true` get their expanded body memoized by
# (skill_path_mtime, args_string) for `_CACHE_TTL_SECS`. Default off
# at the per-skill level so prior behavior is preserved.
_CACHE_TTL_SECS = int(os.environ.get("OPEN_CODE_SKILL_CACHE_TTL", "300"))
_EXPANSION_CACHE: dict[tuple[str, float, str], tuple[float, str]] = {}


def clear_skill_cache() -> None:
    """Force-evict every cached expansion. For tests + REPL `/skill --refresh`."""
    _EXPANSION_CACHE.clear()


@dataclass
class Skill:
    """In-memory representation of a SKILL.md."""
    name: str
    description: str
    body: str
    allowed_tools: list[str] = field(default_factory=list)
    disable_model_invocation: bool = False
    # Tier 2 #21 — when True (frontmatter `cache: true`), expanded
    # body is memoized for OPEN_CODE_SKILL_CACHE_TTL seconds (default 300).
    cache: bool = False
    path: Path | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a markdown file at `---` fences. Returns (fm_dict, body).

    Frontmatter is a tiny key:value YAML subset:
      - line-oriented `key: value`
      - lists rendered as comma-separated values
      - booleans `true`/`false` (case-insensitive)
      - everything else is a string
    No nested structures. Anything we don't understand becomes a string.
    """
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
    # Strip surrounding [ ] if present, then comma-split.
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    parts = [p.strip().strip("'\"") for p in v.split(",")]
    return [p for p in parts if p]


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "1", "on")


def load_skill_file(path: Path) -> Skill | None:
    """Parse a SKILL.md path into a Skill object, or None if malformed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _parse_frontmatter(text)
    name = fm.get("name", "").strip()
    if not name:
        # Fall back to the parent directory name
        name = path.parent.name
    if len(body) > MAX_SKILL_BODY_BYTES:
        body = body[:MAX_SKILL_BODY_BYTES] + "\n[...truncated]"
    return Skill(
        name=name,
        description=fm.get("description", "").strip(),
        body=body,
        allowed_tools=_parse_list(fm.get("allowed-tools", "")),
        disable_model_invocation=_parse_bool(fm.get("disable-model-invocation", "")),
        cache=_parse_bool(fm.get("cache", "")),
        path=path,
    )


def discover_skills(cwd: Path) -> list[Skill]:
    """Find every SKILL.md under <cwd>/.open-code/skills/<name>/."""
    skills_root = cwd / SKILLS_REL
    if not skills_root.exists() or not skills_root.is_dir():
        return []
    out: list[Skill] = []
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir():
            continue
        candidate = entry / "SKILL.md"
        if not candidate.exists():
            continue
        s = load_skill_file(candidate)
        if s is not None:
            out.append(s)
    return out


def find_skill_by_name(cwd: Path, name: str) -> Skill | None:
    for s in discover_skills(cwd):
        if s.name == name:
            return s
    return None


_CMD_BLOCK_RE = re.compile(r"!`([^`\n]+)`")


def _expand_command_blocks(text: str, cwd: Path) -> str:
    """Replace `` !`<cmd>` `` markers with their stdout output."""

    def runner(match: re.Match[str]) -> str:
        cmd = match.group(1).strip()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECS,
                encoding="utf-8",
                errors="replace",
                cwd=str(cwd),
            )
            out = (proc.stdout or "").rstrip()
            if proc.returncode != 0 and proc.stderr:
                out = (out + "\n" + proc.stderr.strip()).strip()
            return out if out else "(no output)"
        except subprocess.TimeoutExpired:
            return f"[skill cmd timeout after {COMMAND_TIMEOUT_SECS}s: {cmd}]"
        except Exception as exc:
            return f"[skill cmd error: {type(exc).__name__}: {exc}]"

    return _CMD_BLOCK_RE.sub(runner, text)


def _expand_arguments(text: str, raw_args: str) -> str:
    """Replace $ARGUMENTS and $1..$9 in the body."""
    expanded = text.replace("$ARGUMENTS", raw_args)
    try:
        parts = shlex.split(raw_args) if raw_args else []
    except ValueError:
        parts = raw_args.split()
    for i in range(1, 10):
        placeholder = f"${i}"
        replacement = parts[i - 1] if i - 1 < len(parts) else ""
        expanded = expanded.replace(placeholder, replacement)
    return expanded


def expand_skill_body(skill: Skill, args: str, cwd: Path,
                      *, use_cache: bool = True) -> str:
    """Resolve $ARGUMENTS / $1..$9 / `` !`cmd` `` in the skill's body.

    Returns the final prompt text that should be sent to the model.

    Tier 2 #21: when `skill.cache` is True AND `use_cache` is True,
    the expansion is memoized by (skill_path, mtime, args) for
    `_CACHE_TTL_SECS`. Bypass with `use_cache=False` (REPL
    `/skill --refresh` or programmatic forced refresh).
    """
    key: tuple[str, float, str] | None = None
    if use_cache and skill.cache and skill.path is not None:
        try:
            mtime = skill.path.stat().st_mtime
        except OSError:
            mtime = -1.0
        key = (str(skill.path), mtime, args)
        cached = _EXPANSION_CACHE.get(key)
        if cached is not None:
            ts, body = cached
            if time.time() - ts < _CACHE_TTL_SECS:
                return body
            # expired -- fall through to re-expand
    expanded = _expand_arguments(skill.body, args)
    expanded = _expand_command_blocks(expanded, cwd)
    result = expanded.strip()
    if key is not None:
        _EXPANSION_CACHE[key] = (time.time(), result)
    return result


def render_skill_listing(skills: Iterable[Skill]) -> str:
    items = list(skills)
    if not items:
        return "(no skills defined; create .open-code/skills/<name>/SKILL.md)"
    lines = [f"{'NAME':<20}  DESCRIPTION"]
    lines.append("-" * 80)
    for s in items:
        desc = s.description or ""
        if len(desc) > 55:
            desc = desc[:52] + "..."
        lines.append(f"{s.name:<20}  {desc}")
    return "\n".join(lines)
