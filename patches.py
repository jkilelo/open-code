"""V4A patch envelope for open-code (OpenAI Codex CLI compatible).

A single `apply_patch` tool that accepts an envelope describing
multiple file operations:

    *** Begin Patch
    *** Add File: path/new.py
    +line one
    +line two
    *** Update File: src/existing.py
    @@ def some_anchor
    -    return old
    +    return new
    *** Delete File: tmp/old.txt
    *** End Patch

Supported actions:
  Add File           -- collect `+`-prefixed lines; create file (refuse if exists)
  Delete File        -- rm the path
  Update File        -- apply one or more hunks; each hunk is anchor + diff lines
  Update + Move to   -- same as Update, but rename target to a new path at the end

Hunk format:
  Optional `@@ context` line(s) that uniquely locate the change site.
  Then a mix of:
    space-prefix    -- context line (must match the file exactly)
    `-` prefix      -- line being removed (must match the file)
    `+` prefix      -- line being added

Hunks are anchored by surrounding text, not line numbers. If an
anchor appears multiple times in the file (and the wider context
in the hunk also doesn't disambiguate), the patch fails clean.

Sandbox: all path operations honor `tools.CONFIG.allow_outside_cwd`
the same way `tool_write_file` does.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools import CONFIG, _is_under


# ---------------------------------------------------------------------------
# Parsed patch structures
# ---------------------------------------------------------------------------


@dataclass
class Hunk:
    """One change-site within an Update File action."""
    anchors: list[str] = field(default_factory=list)  # @@ context lines
    lines: list[tuple[str, str]] = field(default_factory=list)
    # Each `lines` entry is (kind, text) where kind in {"ctx", "del", "add"}.


@dataclass
class PatchAction:
    op: str             # "add" | "delete" | "update"
    path: str
    move_to: str | None = None  # only meaningful with op == "update"
    content: str | None = None  # only for "add" -- assembled body
    hunks: list[Hunk] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class PatchParseError(Exception):
    pass


_BEGIN = "*** Begin Patch"
_END = "*** End Patch"


def parse_patch(text: str) -> list[PatchAction]:
    """Parse a V4A envelope. Returns a list of actions, in order.

    Raises PatchParseError on malformed input.
    """
    lines = text.splitlines()
    # Locate Begin/End markers; tolerate leading/trailing junk.
    try:
        start = next(i for i, L in enumerate(lines) if L.strip() == _BEGIN)
    except StopIteration:
        raise PatchParseError("missing '*** Begin Patch' marker")
    try:
        stop = next(i for i, L in enumerate(lines) if L.strip() == _END and i > start)
    except StopIteration:
        raise PatchParseError("missing '*** End Patch' marker")

    body = lines[start + 1: stop]
    actions: list[PatchAction] = []
    current: PatchAction | None = None
    current_hunk: Hunk | None = None
    add_buf: list[str] = []

    def flush_action():
        nonlocal current, current_hunk, add_buf
        if current is None:
            return
        if current.op == "add":
            current.content = "\n".join(add_buf) + ("\n" if add_buf else "")
        if current_hunk is not None and current.op == "update":
            current.hunks.append(current_hunk)
        actions.append(current)
        current = None
        current_hunk = None
        add_buf = []

    for raw in body:
        stripped = raw.rstrip("\r")
        if stripped.startswith("*** Add File:"):
            flush_action()
            current = PatchAction(op="add", path=stripped.split(":", 1)[1].strip())
            add_buf = []
            continue
        if stripped.startswith("*** Delete File:"):
            flush_action()
            actions.append(PatchAction(
                op="delete", path=stripped.split(":", 1)[1].strip()
            ))
            current = None
            continue
        if stripped.startswith("*** Update File:"):
            flush_action()
            current = PatchAction(
                op="update", path=stripped.split(":", 1)[1].strip()
            )
            current_hunk = None
            continue
        if stripped.startswith("*** Move to:"):
            if current is None or current.op != "update":
                raise PatchParseError("'*** Move to:' outside of an Update block")
            current.move_to = stripped.split(":", 1)[1].strip()
            continue
        # Within an Add File block -- collect +-prefixed lines as body
        if current is not None and current.op == "add":
            if stripped.startswith("+"):
                add_buf.append(stripped[1:])
            elif stripped == "":
                add_buf.append("")
            else:
                # Tolerate unexpected lines (e.g. blank context) by ignoring
                add_buf.append(stripped)
            continue
        # Within an Update File block -- hunks
        if current is not None and current.op == "update":
            if stripped.startswith("@@"):
                # New hunk if this is the first @@; otherwise stack anchors
                if current_hunk is None or current_hunk.lines:
                    if current_hunk is not None:
                        current.hunks.append(current_hunk)
                    current_hunk = Hunk()
                anchor = stripped[2:].lstrip()
                current_hunk.anchors.append(anchor)
                continue
            if current_hunk is None:
                # No anchor yet -- start an implicit hunk with no anchor
                current_hunk = Hunk()
            if stripped.startswith("-"):
                current_hunk.lines.append(("del", stripped[1:]))
            elif stripped.startswith("+"):
                current_hunk.lines.append(("add", stripped[1:]))
            elif stripped.startswith(" "):
                current_hunk.lines.append(("ctx", stripped[1:]))
            elif stripped == "":
                # Blank line between hunks -- flush and reset
                if current_hunk is not None and current_hunk.lines:
                    current.hunks.append(current_hunk)
                    current_hunk = None
            # Other lines silently ignored to be forgiving.
    flush_action()
    return actions


# ---------------------------------------------------------------------------
# Applier
# ---------------------------------------------------------------------------


def _resolve_target(path_str: str) -> tuple[Path | None, str | None]:
    """Apply path sandbox to a target path. Return (resolved, err)."""
    try:
        p = Path(path_str).expanduser()
        if not CONFIG.allow_outside_cwd:
            target = (CONFIG.cwd / p).resolve() if not p.is_absolute() else p.resolve()
            if not _is_under(target, CONFIG.cwd):
                return None, (
                    f"refusing path outside CWD: {target} is not under "
                    f"{CONFIG.cwd}. Re-run with --allow-outside-cwd if "
                    "intended."
                )
            return target, None
        return p.resolve() if p.is_absolute() else (CONFIG.cwd / p).resolve(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _apply_hunk(file_lines: list[str], hunk: Hunk) -> tuple[list[str], str | None]:
    """Apply one hunk to the file's line list. Returns (new_lines, err)."""
    # Strategy: build the "before" pattern (anchors + ctx + del lines, in
    # order) and the "after" replacement (anchors + ctx + add lines).
    # Find the unique location matching `before` in file_lines, splice.

    # Build the search and replacement sequences.
    before: list[str] = []
    after: list[str] = []
    for kind, text in hunk.lines:
        if kind == "ctx":
            before.append(text)
            after.append(text)
        elif kind == "del":
            before.append(text)
        elif kind == "add":
            after.append(text)

    if not before:
        return file_lines, "hunk had no `-` or context lines to anchor on"

    # Anchors narrow the search window. Each anchor must match EXACTLY
    # ONE line (after stripping leading indentation) -- the line either
    # equals the anchor, or starts with the anchor followed by a
    # word-boundary character (so `def foo` matches `def foo(...):`
    # but NOT `def foo_helper(...):`).
    start_idx = 0
    for anchor in hunk.anchors:
        anchor_stripped = anchor.strip()
        if not anchor_stripped:
            continue
        anchor_re = re.compile(
            r"^" + re.escape(anchor_stripped) + r"(?:\b|$)"
        )
        positions: list[int] = []
        for i in range(start_idx, len(file_lines)):
            line_lstripped = file_lines[i].lstrip()
            if (line_lstripped == anchor_stripped
                    or anchor_re.search(line_lstripped)):
                positions.append(i)
        if not positions:
            return file_lines, f"anchor not found: {anchor!r}"
        if len(positions) > 1:
            return file_lines, (
                f"anchor {anchor!r} matches {len(positions)} lines "
                "(ambiguous). Add more @@ context to disambiguate, or "
                "extend the anchor to include the full line."
            )
        start_idx = positions[0]

    # Locate `before` as a contiguous block from `start_idx`. Collect
    # ALL strict matches (don't short-circuit on the first) so we can
    # detect ambiguity.
    matches: list[int] = []
    if before:
        for i in range(start_idx, len(file_lines) - len(before) + 1):
            if all(file_lines[i + j] == before[j] for j in range(len(before))):
                matches.append(i)
    if not matches:
        # Forgiving fallback: rstrip both sides (tolerates trailing
        # whitespace differences). Collect ALL matches -- the original
        # code broke on the first, hiding ambiguity.
        for i in range(start_idx, len(file_lines) - len(before) + 1):
            if all(
                file_lines[i + j].rstrip() == before[j].rstrip()
                for j in range(len(before))
            ):
                matches.append(i)
    if not matches:
        return file_lines, (
            f"hunk pattern not found in file (after anchors). "
            f"First line of pattern: {before[0]!r}"
        )
    if len(matches) > 1:
        return file_lines, (
            f"hunk pattern is ambiguous -- matches {len(matches)} locations "
            "(add more @@ context or surrounding ctx lines to disambiguate)"
        )

    idx = matches[0]
    new_lines = file_lines[:idx] + after + file_lines[idx + len(before):]
    return new_lines, None


def apply_patch(patch_text: str) -> dict[str, Any]:
    """Apply a V4A patch envelope. Returns the tool-result dict."""
    try:
        actions = parse_patch(patch_text)
    except PatchParseError as exc:
        return {"ok": False, "error": f"patch parse: {exc}"}

    applied: list[str] = []
    failed: list[dict[str, str]] = []

    for action in actions:
        target, err = _resolve_target(action.path)
        if err:
            failed.append({"path": action.path, "error": err})
            continue
        assert target is not None

        if action.op == "add":
            if target.exists():
                failed.append({
                    "path": action.path,
                    "error": "Add File: target already exists "
                             "(use Update File instead)",
                })
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(action.content or "", encoding="utf-8")
                applied.append(str(target))
            except OSError as exc:
                failed.append({"path": action.path,
                               "error": f"OS error on add: {exc}"})
            continue

        if action.op == "delete":
            if not target.exists():
                failed.append({"path": action.path,
                               "error": "Delete File: target doesn't exist"})
                continue
            try:
                target.unlink()
                applied.append(str(target))
            except OSError as exc:
                failed.append({"path": action.path,
                               "error": f"OS error on delete: {exc}"})
            continue

        if action.op == "update":
            if not target.exists():
                failed.append({"path": action.path,
                               "error": "Update File: target doesn't exist"})
                continue
            try:
                original = target.read_text(encoding="utf-8")
            except OSError as exc:
                failed.append({"path": action.path,
                               "error": f"read failed: {exc}"})
                continue
            file_lines = original.splitlines()
            error_for_action: str | None = None
            for hi, hunk in enumerate(action.hunks):
                file_lines, hunk_err = _apply_hunk(file_lines, hunk)
                if hunk_err:
                    error_for_action = f"hunk {hi}: {hunk_err}"
                    break
            if error_for_action:
                failed.append({"path": action.path, "error": error_for_action})
                continue
            new_content = "\n".join(file_lines)
            if original.endswith("\n"):
                new_content += "\n"
            try:
                target.write_text(new_content, encoding="utf-8")
            except OSError as exc:
                failed.append({"path": action.path,
                               "error": f"write failed: {exc}"})
                continue
            if action.move_to:
                new_target, mv_err = _resolve_target(action.move_to)
                if mv_err:
                    failed.append({"path": action.path,
                                   "error": f"move sandbox: {mv_err}"})
                    continue
                assert new_target is not None
                try:
                    new_target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(target), str(new_target))
                    applied.append(f"{target} -> {new_target}")
                except OSError as exc:
                    failed.append({"path": action.path,
                                   "error": f"move failed: {exc}"})
                    continue
            else:
                applied.append(str(target))
            continue

    result: dict[str, Any] = {
        "ok": len(failed) == 0,
        "applied": applied,
        "count": len(applied),
    }
    if failed:
        result["failed"] = failed
        result["error"] = (
            f"{len(failed)} action(s) failed; "
            f"first error: {failed[0].get('error', '?')}"
        )
    return result


# NOTE: the tool declaration constant lives in tools.py
# (to avoid a load-time circular import). This module just holds the
# parser + applier.
