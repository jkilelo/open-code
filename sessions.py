"""Session storage for open-code (v0.3+).

Replaces v0.2's SQLite layer with file-per-session JSONL — one append-only
event log per session, organized by CWD. Patterns borrowed from Claude
Code's transcript layout:

  ~/.open-code/projects/<encoded-cwd>/<uuid>.jsonl

Each line is one JSON event. Event `kind`s:
- "session": opening record (one per file, line 1)
- "msg":     a conversational message (user / model / tool result)
- "metrics": per-iteration usage from the model
- "fallback":the agent dropped to a fallback model
- "end":     closing record (one per file, on clean exit)

Append-only + per-event flush means partial output survives crashes or
Ctrl-C — what Jeff wrote up to that point is on disk. The filesystem
is the index: `--list-sessions` is a directory scan, no DB to corrupt.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from google.genai import types

JSONL_VERSION = "0.3.0"


# ---------------------------------------------------------------------------
# CWD encoding (Claude Code-style: replace separators with dashes)
# ---------------------------------------------------------------------------


def encode_cwd(cwd: str | Path) -> str:
    """Encode an absolute path as a filesystem-safe single-component name.

    `C:\\Users\\jeff\\foo`  -> `C-Users-jeff-foo`
    `/home/jeff/foo`        -> `home-jeff-foo`

    Collisions are theoretically possible across paths that differ only
    by separator characters; in practice this never happens for actual
    CWDs because real path components don't contain `-`-substitutable
    chars in weird combinations.
    """
    s = str(Path(cwd).resolve())
    s = s.replace("\\", "-").replace("/", "-").replace(":", "")
    s = re.sub(r"-+", "-", s).strip("-")
    return s


# ---------------------------------------------------------------------------
# Content <-> dict serialization
# ---------------------------------------------------------------------------


def content_to_dict(content: types.Content) -> dict[str, Any]:
    """Serialize a types.Content to a JSON-friendly dict.

    Each Part becomes one of: text / function_call / function_response.
    The format is stable across SDK versions because we only store the
    data fields, not the SDK's internal object identity.
    """
    parts_out: list[dict[str, Any]] = []
    for p in content.parts or []:
        text = getattr(p, "text", None)
        fc = getattr(p, "function_call", None)
        fr = getattr(p, "function_response", None)
        if fc is not None and getattr(fc, "name", None):
            args_d = dict(fc.args) if fc.args else {}
            parts_out.append({"type": "function_call", "name": fc.name, "args": args_d})
        elif fr is not None and getattr(fr, "name", None):
            resp_d = dict(fr.response) if fr.response else {}
            parts_out.append({"type": "function_response", "name": fr.name, "response": resp_d})
        elif text:
            parts_out.append({"type": "text", "text": text})
    return {"role": content.role or "", "parts": parts_out}


def dict_to_content(d: dict[str, Any]) -> types.Content:
    parts: list[types.Part] = []
    for pd in d.get("parts", []):
        t = pd.get("type")
        if t == "text":
            parts.append(types.Part.from_text(text=pd.get("text", "")))
        elif t == "function_call":
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(
                        name=pd["name"], args=pd.get("args", {})
                    )
                )
            )
        elif t == "function_response":
            parts.append(
                types.Part.from_function_response(
                    name=pd["name"], response=pd.get("response", {})
                )
            )
    return types.Content(role=d.get("role") or "user", parts=parts)


# ---------------------------------------------------------------------------
# Session record
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """In-memory handle to a session's JSONL file.

    `path` is the source of truth; `id`, `cwd`, `model`, `task`, and
    `started_at` are convenience fields populated from the session
    header line. `last_active_at` is the mtime of the file.
    """
    id: str
    cwd: str
    model: str
    task: str
    started_at: str
    path: Path

    @property
    def last_active_at(self) -> str:
        try:
            ts = self.path.stat().st_mtime
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
        except OSError:
            return self.started_at


# ---------------------------------------------------------------------------
# Storage layer
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_first_line(path: Path) -> dict[str, Any] | None:
    """Read the session header from a JSONL file (line 1). None if malformed."""
    try:
        with path.open("r", encoding="utf-8") as f:
            first = f.readline().strip()
        if not first:
            return None
        return json.loads(first)
    except (OSError, json.JSONDecodeError):
        return None


class SessionStore:
    """File-per-session JSONL store under `~/.open-code/projects/`.

    Thread-safety: each session is its own file. Two processes writing
    to the same session concurrently is undefined — but that's a
    user-error case (you'd have to explicitly --resume the same session
    in two terminals). Different sessions = different files = no race.
    """

    def __init__(self, root: Path):
        self.root = root
        self.projects_dir = root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        # Brutal-review H4: cache message counts per session so
        # append_message doesn't do an O(N) file scan every turn.
        # Keyed by session.id. Lazily populated on first lookup.
        self._msg_counts: dict[str, int] = {}

    # ---- path helpers ----

    def _project_dir_for(self, cwd: str) -> Path:
        d = self.projects_dir / encode_cwd(cwd)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _session_path(self, cwd: str, session_id: str) -> Path:
        return self._project_dir_for(cwd) / f"{session_id}.jsonl"

    # ---- creation + I/O ----

    def create(self, cwd: str, model: str, task: str) -> Session:
        sid = str(uuid.uuid4())
        path = self._session_path(cwd, sid)
        started = _now()
        header = {
            "kind": "session",
            "v": JSONL_VERSION,
            "id": sid,
            "cwd": cwd,
            "model": model,
            "task": task,
            "started_at": started,
        }
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")
            f.flush()
        # Prime the H4 message-count cache. A freshly-created session
        # has zero messages, so future append_message calls can skip
        # the cold-scan entirely.
        self._msg_counts[sid] = 0
        return Session(
            id=sid, cwd=cwd, model=model, task=task, started_at=started, path=path
        )

    def _append(self, session: Session, event: dict[str, Any]) -> None:
        """Append one event line. Flush every write so partial output
        survives interrupts / crashes / Ctrl-C."""
        with session.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
            f.flush()

    def append_message(self, session: Session, content: types.Content) -> None:
        # seq lets us reconstruct ordering without trusting file position.
        # H4 fix: in-memory counter avoids the O(N) scan per turn that
        # accumulated to O(N²) over a long /loop or REPL session.
        seq = self._count_messages(session)
        self._msg_counts[session.id] = seq + 1
        self._append(
            session,
            {
                "kind": "msg",
                "seq": seq,
                "role": content.role or "",
                "parts": content_to_dict(content)["parts"],
                "ts": _now(),
            },
        )

    def append_metrics(self, session: Session, *, iteration: int, model: str,
                       input_tok: int, output_tok: int) -> None:
        self._append(
            session,
            {
                "kind": "metrics",
                "iter": iteration,
                "model": model,
                "input_tok": input_tok,
                "output_tok": output_tok,
                "ts": _now(),
            },
        )

    def append_fallback(self, session: Session, *, from_model: str,
                        to_model: str, reason: str) -> None:
        self._append(
            session,
            {
                "kind": "fallback",
                "from": from_model,
                "to": to_model,
                "reason": reason,
                "ts": _now(),
            },
        )

    def append_end(self, session: Session, *, exit_code: int, iters: int,
                   wall_seconds: float) -> None:
        self._append(
            session,
            {
                "kind": "end",
                "exit_code": exit_code,
                "iters": iters,
                "wall_seconds": round(wall_seconds, 3),
                "ts": _now(),
            },
        )

    def append_compact(self, session: Session, *, summary: str,
                       kept_recent: int, dropped: int, model: str) -> None:
        """Record a `/compact` event: summary of older history.

        `kept_recent` = number of recent messages preserved verbatim;
        `dropped` = number of old messages condensed into `summary`.
        Subsequent --resume sees this event and replaces the dropped
        history with the summary as a single synthetic user message.
        """
        self._append(
            session,
            {
                "kind": "compact",
                "summary": summary,
                "kept_recent": kept_recent,
                "dropped": dropped,
                "model": model,
                "ts": _now(),
            },
        )

    def append_checkpoint(self, session: Session, *, sha: str, label: str,
                          phase: str) -> None:
        """Record a shadow-git checkpoint event (Tier 2 #11).

        `sha` is the full shadow-repo commit sha. `label` is a short
        human-readable description. `phase` is "turn-start" (before
        the user turn runs) or "turn-end" (after) or "manual" (REPL
        `/checkpoint` command).
        """
        self._append(
            session,
            {
                "kind": "checkpoint",
                "sha": sha,
                "short_sha": sha[:10],
                "label": label,
                "phase": phase,
                "ts": _now(),
            },
        )

    def recent_checkpoints(self, session: Session,
                           phase: str | None = None,
                           limit: int = 20) -> list[dict[str, Any]]:
        """Return recent `checkpoint` events from this session (newest first).

        Optional `phase` filter ∈ {"turn-start", "turn-end", "manual"}.
        Used by `/undo` to find the most-recent turn-start sha to
        restore the workspace to.
        """
        out: list[dict[str, Any]] = []
        try:
            with session.path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("kind") != "checkpoint":
                        continue
                    if phase is not None and ev.get("phase") != phase:
                        continue
                    out.append(ev)
        except OSError:
            return []
        out.reverse()  # newest first
        return out[:limit]

    def append_plan(self, session: Session, *, plan_id: str,
                    content: str, model: str) -> None:
        """Record a Plan/Act 'plan' artifact in the session JSONL.

        Written after a `/plan <task>` turn finishes; later read by
        `/act` to inject as context under `<plan id=...>` tags.
        """
        self._append(
            session,
            {
                "kind": "plan",
                "plan_id": plan_id,
                "model": model,
                "content": content,
                "ts": _now(),
            },
        )

    def latest_plan(self, session: Session) -> dict[str, Any] | None:
        """Return the most recent `plan` event payload (id, content, ts)
        in the session's JSONL, or None if no plans recorded."""
        latest: dict[str, Any] | None = None
        try:
            with session.path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("kind") == "plan":
                        latest = ev
        except OSError:
            return None
        return latest

    def append_tool_refusal(self, session: Session, *, tool: str,
                            reason: str, args_snippet: str) -> None:
        """Audit-trail entry: a tool call was refused by the security guards."""
        self._append(
            session,
            {
                "kind": "refusal",
                "tool": tool,
                "reason": reason,
                "args": args_snippet,
                "ts": _now(),
            },
        )

    # ---- discovery ----

    def _count_messages(self, session: Session) -> int:
        """Return the current message count for `session`, caching the result.

        First call for a session does the O(N) file scan (catches the
        --resume case where messages exist on disk before this process
        started writing). Subsequent calls in the same process return
        the cached count, kept fresh by `append_message`.
        """
        cached = self._msg_counts.get(session.id)
        if cached is not None:
            return cached
        n = 0
        try:
            with session.path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("kind") == "msg":
                        n += 1
        except OSError:
            pass
        self._msg_counts[session.id] = n
        return n

    def _session_from_path(self, path: Path) -> Session | None:
        header = _read_first_line(path)
        if not header or header.get("kind") != "session":
            return None
        return Session(
            id=header.get("id", path.stem),
            cwd=header.get("cwd", ""),
            model=header.get("model", ""),
            task=header.get("task", ""),
            started_at=header.get("started_at", ""),
            path=path,
        )

    def find_latest_for_cwd(self, cwd: str) -> Session | None:
        d = self._project_dir_for(cwd)
        candidates = [p for p in d.glob("*.jsonl") if p.is_file()]
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            s = self._session_from_path(path)
            if s is not None:
                return s
        return None

    def find_by_id(self, session_id: str) -> Session | None:
        """Walk every project dir; sessions are uniquely named by UUID.
        Typical project counts are dozens, so a scan is cheap."""
        for d in self.projects_dir.iterdir():
            if not d.is_dir():
                continue
            candidate = d / f"{session_id}.jsonl"
            if candidate.exists():
                return self._session_from_path(candidate)
        return None

    def list_for_cwd(self, cwd: str, limit: int = 20) -> list[Session]:
        d = self._project_dir_for(cwd)
        return self._sorted_sessions(d.glob("*.jsonl"), limit)

    def list_all(self, limit: int = 20) -> list[Session]:
        return self._sorted_sessions(self.projects_dir.glob("*/*.jsonl"), limit)

    def _sorted_sessions(self, paths: Iterable[Path], limit: int) -> list[Session]:
        out: list[Session] = []
        for p in sorted(paths, key=lambda x: x.stat().st_mtime, reverse=True):
            s = self._session_from_path(p)
            if s is not None:
                out.append(s)
            if len(out) >= limit:
                break
        return out

    # ---- history reconstruction ----

    def load_history(
        self, session: Session, max_messages: int = 80
    ) -> tuple[list[types.Content], int]:
        """Read the JSONL file, return (history, dropped_count).

        max_messages <= 0 means uncapped. The returned history is
        trimmed to start on a user-role turn (Gemini API requirement).

        If the JSONL contains a `compact` event, the most recent one
        replaces all msg events before it with a single synthetic
        user-role summary message. Subsequent `msg` events (those
        AFTER the compact) load verbatim.
        """
        all_msgs: list[types.Content] = []
        msg_count_at_compact = 0  # how many msgs preceded the latest compact
        compact_summary: str | None = None
        try:
            with session.path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = ev.get("kind")
                    if kind == "msg":
                        all_msgs.append(
                            dict_to_content({"role": ev.get("role", ""),
                                             "parts": ev.get("parts", [])})
                        )
                    elif kind == "compact":
                        compact_summary = ev.get("summary") or ""
                        msg_count_at_compact = len(all_msgs)
        except OSError:
            return [], 0
        if compact_summary is not None:
            # Replace the first `msg_count_at_compact` messages with the
            # single summary, prepended as a synthetic user message.
            summary_msg = dict_to_content({
                "role": "user",
                "parts": [{"type": "text",
                           "text": f"[compacted earlier history summary]\n{compact_summary}"}],
            })
            all_msgs = [summary_msg] + all_msgs[msg_count_at_compact:]
        if max_messages <= 0 or len(all_msgs) <= max_messages:
            return all_msgs, 0
        trimmed = all_msgs[-max_messages:]
        while trimmed and (trimmed[0].role or "") != "user":
            trimmed = trimmed[1:]
        return trimmed, len(all_msgs) - len(trimmed)

    def aggregate_metrics(self, session: Session) -> dict[str, Any]:
        """Sum input/output tokens across all 'metrics' events in this session
        file. Used to report cumulative cost across --resume chains."""
        agg = {"input_tok": 0, "output_tok": 0, "n_iters": 0,
               "n_fallbacks": 0, "n_refusals": 0}
        try:
            with session.path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    k = ev.get("kind")
                    if k == "metrics":
                        agg["input_tok"] += int(ev.get("input_tok") or 0)
                        agg["output_tok"] += int(ev.get("output_tok") or 0)
                        agg["n_iters"] += 1
                    elif k == "fallback":
                        agg["n_fallbacks"] += 1
                    elif k == "refusal":
                        agg["n_refusals"] += 1
        except OSError:
            pass
        return agg


# ---------------------------------------------------------------------------
# Migration from v0.2.x SQLite
# ---------------------------------------------------------------------------


def migrate_from_sqlite(sqlite_path: Path, store: SessionStore) -> int:
    """One-shot migration: read every session out of `sqlite_path`, write
    each as a JSONL file under the store. Returns count migrated.

    After success, renames the SQLite file to `<name>.migrated` so future
    runs skip migration and the user can recover if anything went wrong.
    """
    if not sqlite_path.exists():
        return 0
    conn = sqlite3.connect(str(sqlite_path))
    try:
        rows = conn.execute(
            "SELECT id, cwd, model, task, started_at FROM sessions ORDER BY id ASC"
        ).fetchall()
    except sqlite3.DatabaseError:
        conn.close()
        return 0

    count = 0
    for old_sid, cwd, model, task, started in rows:
        session = store.create(cwd, model or "", task or "")
        _backdate_session_start(session, started)
        msgs = conn.execute(
            "SELECT role, parts_json FROM messages WHERE session_id = ? ORDER BY seq ASC",
            (old_sid,),
        ).fetchall()
        for role, pj in msgs:
            try:
                d = json.loads(pj)
            except json.JSONDecodeError:
                continue
            content = dict_to_content({"role": role, "parts": d.get("parts", [])})
            store.append_message(session, content)
        try:
            mtime = datetime.fromisoformat(started).timestamp()
            os.utime(session.path, (mtime, mtime))
        except (ValueError, OSError):
            pass
        count += 1
    conn.close()
    try:
        sqlite_path.rename(sqlite_path.with_suffix(".db.migrated"))
    except OSError:
        pass
    return count


def _backdate_session_start(session: Session, started_at: str) -> None:
    """Rewrite line 1 of the JSONL with the original started_at. Atomic via
    temp file + rename."""
    if not started_at:
        return
    try:
        with session.path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if not lines:
            return
        header = json.loads(lines[0])
        header["started_at"] = started_at
        lines[0] = json.dumps(header) + "\n"
        tmp = session.path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        tmp.replace(session.path)
    except (OSError, json.JSONDecodeError, KeyError):
        pass
