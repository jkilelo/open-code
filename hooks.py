"""Hooks system for open-code (Claude Code-style).

Five event types fire shell scripts under `.open-code/hooks/<event>/`:

- PreToolUse       fires before each tool call; exit 2 blocks the call
- PostToolUse      fires after each tool call (observe-only)
- Stop             fires at end-of-turn; exit 2 forces the model to
                   produce another response
- SessionStart     fires when a session is created / resumed; stdout
                   JSON {"additionalContext": "..."} is injected into
                   the system instruction
- UserPromptSubmit fires per REPL turn before the prompt reaches the
                   model; stdout JSON {"transformedPrompt": "..."} or
                   {"block": true, "reason": "..."} are honored

Each script receives a JSON document on stdin:
  {event, session_id, cwd, ...event-specific keys}

Env vars when invoked:
  OPEN_CODE_PROJECT_DIR  path to the `.open-code/` parent
  OPEN_CODE_SESSION_ID   the UUID of the active session
  OPEN_CODE_CWD          the absolute CWD

Exit-code conventions:
  0   allow / proceed
  2   block (with reason on stderr OR in stdout JSON.reason)
  any other  log to stderr; treat as if exit 0 (never crash the session
            because of a misbehaving hook)
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SessionStart",
    "UserPromptSubmit",
)

# Per-hook execution timeout (seconds). Anything slower is misbehavior.
HOOK_TIMEOUT_SECS = 30


@dataclass
class HookResult:
    """Aggregated outcome from firing all hooks for one event."""
    block: bool = False
    reason: str = ""
    additional_context: str | None = None
    transformed_prompt: str | None = None
    modified_args: dict[str, Any] | None = None
    errored: bool = False
    # Names of scripts that fired (for traceability)
    invoked: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.invoked is None:
            self.invoked = []


def find_hooks_dir(cwd: Path) -> Path | None:
    """Walk up from cwd looking for `.open-code/hooks/`. None if absent."""
    current = cwd.resolve()
    while True:
        candidate = current / ".open-code" / "hooks"
        if candidate.exists() and candidate.is_dir():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _executable_scripts(d: Path) -> list[Path]:
    """List the scripts in an event directory, sorted by name.

    On POSIX requires +x; on Windows accepts known script suffixes.
    Allows `.py` / `.sh` everywhere even without +x for convenience.
    """
    if not d.exists() or not d.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(d.iterdir()):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if os.name == "nt":
            if suffix in (".py", ".sh", ".ps1", ".bat", ".cmd", ".exe"):
                out.append(p)
        else:
            mode = p.stat().st_mode
            if mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                out.append(p)
            elif suffix in (".py", ".sh"):
                out.append(p)
    return out


def _cmd_for(script: Path) -> list[str]:
    """Pick an interpreter for the script based on extension."""
    suffix = script.suffix.lower()
    if suffix == ".py":
        return [sys.executable, str(script)]
    if suffix == ".sh":
        return ["bash", str(script)]
    if suffix == ".ps1":
        return ["pwsh", "-File", str(script)]
    return [str(script)]


def _invoke_one(script: Path, stdin_obj: dict[str, Any],
                env_extras: dict[str, str]) -> dict[str, Any]:
    """Run a single hook. Returns {exit_code, stdout, stderr, payload}."""
    env = os.environ.copy()
    env.update(env_extras)
    try:
        proc = subprocess.run(
            _cmd_for(script),
            input=json.dumps(stdin_obj),
            capture_output=True,
            text=True,
            timeout=HOOK_TIMEOUT_SECS,
            env=env,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        payload: dict[str, Any] = {}
        # Try to parse stdout as JSON; non-JSON output is fine (text hook)
        try:
            parsed = json.loads(stdout) if stdout.strip() else {}
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
        return {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "payload": payload,
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "",
                "stderr": f"hook timeout after {HOOK_TIMEOUT_SECS}s", "payload": {}}
    except Exception as exc:
        return {"exit_code": -1, "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}", "payload": {}}


def fire(event: str, cwd: Path, *, session_id: str,
         payload: dict[str, Any]) -> HookResult:
    """Fire all hooks for `event`. Returns aggregated HookResult.

    Short-circuits on the first hook that returns exit 2 (block).
    Other non-zero exits are logged but don't propagate.
    Stdout JSON payloads are merged (later hooks can override earlier).
    """
    result = HookResult()
    if event not in HOOK_EVENTS:
        return result
    hooks_root = find_hooks_dir(cwd)
    if hooks_root is None:
        return result
    event_dir = hooks_root / event
    scripts = _executable_scripts(event_dir)
    if not scripts:
        return result
    stdin_obj: dict[str, Any] = {
        "event": event,
        "session_id": session_id,
        "cwd": str(cwd),
        **payload,
    }
    env_extras = {
        "OPEN_CODE_PROJECT_DIR": str(hooks_root.parent.parent),
        "OPEN_CODE_SESSION_ID": session_id,
        "OPEN_CODE_CWD": str(cwd),
    }
    for script in scripts:
        outcome = _invoke_one(script, stdin_obj, env_extras)
        result.invoked.append(script.name)
        if outcome["exit_code"] == 2:
            result.block = True
            pld_reason = (outcome["payload"].get("reason")
                          if isinstance(outcome["payload"], dict) else None)
            result.reason = (pld_reason or outcome["stderr"] or "blocked").strip()
            return result  # short-circuit
        if outcome["exit_code"] not in (0, 2):
            sys.stderr.write(
                f"open-code: hook {script.name!r} returned exit="
                f"{outcome['exit_code']}; ignoring "
                f"(stderr: {outcome['stderr'][:160].strip()!r})\n"
            )
            result.errored = True
            continue
        pld = outcome.get("payload", {}) or {}
        if not isinstance(pld, dict):
            continue
        ac = pld.get("additionalContext")
        if isinstance(ac, str) and ac:
            result.additional_context = (
                ac if result.additional_context is None
                else f"{result.additional_context}\n\n{ac}"
            )
        tp = pld.get("transformedPrompt")
        if isinstance(tp, str):
            result.transformed_prompt = tp
        ma = pld.get("modifiedArgs")
        if isinstance(ma, dict):
            result.modified_args = ma
    return result
