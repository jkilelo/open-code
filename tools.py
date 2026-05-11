"""Tools available to the open-code agent + the security guards around them.

Four tools mirror Claude Code's primary file/shell surface:
  read_file, write_file, list_dir, run_shell

Plus the v0.2 security guards:
  - write_file refuses paths outside CWD unless --allow-outside-cwd
  - run_shell refuses destructive patterns unless --allow-dangerous
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_TIMEOUT_PER_SHELL = 60
MAX_SHELL_OUTPUT = 8000


# ---------------------------------------------------------------------------
# Runtime config (mutated from CLI in open_code.main)
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """Runtime config set from CLI flags; read by tool functions."""

    allow_outside_cwd: bool = False
    allow_dangerous: bool = False
    cwd: Path = field(default_factory=Path.cwd)
    # Tier 2 #14: status-line toggle (off by default)
    statusline_on: bool = False
    # Tier 2 #20: --print mode emits structured JSON events to stdout
    # instead of human-readable text. Set by cli.main when --print is
    # passed; read by open_code._emit_json in run_loop.
    print_json: bool = False


CONFIG = Config()


# ---------------------------------------------------------------------------
# Destructive-command denylist
# ---------------------------------------------------------------------------


DANGEROUS_PATTERNS = [
    # Filesystem-level destruction
    re.compile(r"\bmkfs(?:\.|\s)", re.I),
    re.compile(r"\bdd\s+[^|]*\bof=/dev/", re.I),
    re.compile(r">\s*/dev/sd[a-z]"),
    # Redirect into critical config files
    re.compile(r">>?\s*/etc/(?:passwd|shadow|sudoers|hosts|fstab)\b", re.I),
    # Fork bomb
    re.compile(r":\s*\(\s*\)\s*\{\s*:\|:&\s*\};:"),
    # chmod -R 777 of system roots
    re.compile(r"\bchmod\s+-[a-zA-Z]*R[a-zA-Z]*\s+(?:777|666|000)\s+[/~]", re.I),
    # Windows native recursive deletes
    re.compile(r"\brd\s+/s\b", re.I),
    re.compile(r"\brmdir\s+/s\b", re.I),
    re.compile(r"\bdel\s+/[a-zA-Z]+\s+[a-zA-Z]:\\", re.I),
    re.compile(r"\bformat\s+[a-zA-Z]:", re.I),
    # System power control
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\b(?:reboot|halt|poweroff)(?:\s|$)", re.I),
    re.compile(r"\binit\s+0\b"),
    # Network -> execution
    re.compile(r"\b(?:curl|wget)\b[^|;]*\|\s*(?:sh|bash|zsh|ksh|fish)\b", re.I),
    re.compile(r"\beval\s+[\"']?\$\([^)]*\b(?:curl|wget)\b", re.I),
    # find / -delete (broad deletion via find on root or home)
    re.compile(r"\bfind\s+[/~][^;|]*\s-delete\b", re.I),
    # Git destruction (force-push, hard reset, clean -fd)
    re.compile(r"\bgit\s+push\b[^;|]*\s(?:--force\b|--force-with-lease\b|-f\b)", re.I),
    re.compile(r"\bgit\s+reset\s+--hard\b", re.I),
    re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f[a-zA-Z]*d[a-zA-Z]*", re.I),
    # Container/cluster destruction
    re.compile(r"\bdocker\s+system\s+prune\b[^;|]*\s-[a-zA-Z]*[af]", re.I),
    re.compile(r"\bdocker\s+system\s+prune\b[^;|]*\s--(?:all|force)\b", re.I),
    re.compile(r"\bkubectl\s+delete\s+(?:namespace|ns|--all\b)", re.I),
    # Package publish (irreversible release)
    re.compile(r"\bnpm\s+publish\b", re.I),
    # Firewall disable
    re.compile(r"\bnetsh\s+advfirewall\s+set\s+[^;|]*\sstate\s+off\b", re.I),
]


def _rm_has_recurse_and_force(command: str) -> bool:
    """rm with BOTH -r and -f flags, in any form.

    Combined (-rf, -fr, -Rf, -rfv), separated (-r -f, -f -r), long
    (--recursive --force), full-path (/usr/bin/rm), uppercase RM,
    sudo prefix, sh -c '...' wrappers, pipelines (ls | xargs rm -rf).
    """
    for m in re.finditer(r"(?:^|[^a-zA-Z0-9_/-])(?:[/\w]+/)?rm\b(.*)", command, re.I):
        rest = m.group(1)
        rest = re.split(r"[;|&]|>", rest, maxsplit=1)[0]
        has_r = False
        has_f = False
        for tok in rest.split():
            if not tok.startswith("-"):
                break
            low = tok.lower()
            if low.startswith("--recursive"):
                has_r = True
            elif low.startswith("--force"):
                has_f = True
            elif tok.startswith("--"):
                continue
            else:
                letters = tok[1:].lower()
                if "r" in letters:
                    has_r = True
                if "f" in letters:
                    has_f = True
        if not (has_r and has_f):
            attached = re.search(r"\brm\s+-([a-zA-Z]+)(?:[/~])", command, re.I)
            if attached:
                letters = attached.group(1).lower()
                if "r" in letters and "f" in letters:
                    has_r = has_f = True
        if has_r and has_f:
            return True
    return False


def _ps_remove_has_recurse_and_force(command: str) -> bool:
    """PowerShell: Remove-Item / ri / rmdir with -Recurse AND -Force."""
    if not re.search(r"\b(?:Remove-Item|rmdir)\b", command, re.I) \
            and not re.search(r"(?:^|[^a-zA-Z0-9_])ri\b", command):
        return False
    has_r = False
    has_f = False
    for tok in re.findall(r"-[A-Za-z]+", command):
        low = tok.lower()
        if low == "-recurse" or low == "-r":
            has_r = True
            continue
        if low == "-force" or low == "-f":
            has_f = True
            continue
        letters = low[1:]
        if "r" in letters:
            has_r = True
        if "f" in letters:
            has_f = True
    return has_r and has_f


def _dangerous_match(command: str) -> str | None:
    """Return the matched-pattern description if `command` is destructive."""
    if _rm_has_recurse_and_force(command):
        return "rm with both recursive and force flags"
    if _ps_remove_has_recurse_and_force(command):
        return "Remove-Item / rmdir / ri with -Recurse and -Force"
    for pat in DANGEROUS_PATTERNS:
        if pat.search(command):
            return pat.pattern
    return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def tool_read_file(path: str) -> dict[str, Any]:
    """Read a UTF-8 text file and return its contents (truncated if huge)."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"file not found: {path}"}
        if p.is_dir():
            return {"ok": False, "error": f"path is a directory, not a file: {path}"}
        size = p.stat().st_size
        if size > 200_000:
            return {
                "ok": False,
                "error": (
                    f"file too large ({size} bytes; cap 200KB). "
                    "Use run_shell with head/tail/grep to inspect."
                ),
            }
        text = p.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "content": text, "size": size}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def tool_write_file(path: str, content: str) -> dict[str, Any]:
    """Write a file. Refuses paths outside CWD unless allow_outside_cwd."""
    try:
        p = Path(path).expanduser()
        if not CONFIG.allow_outside_cwd:
            target = (CONFIG.cwd / p).resolve() if not p.is_absolute() else p.resolve()
            if not _is_under(target, CONFIG.cwd):
                return {
                    "ok": False,
                    "error": (
                        f"refusing to write outside CWD: {target} is not under "
                        f"{CONFIG.cwd}. Re-run open-code with --allow-outside-cwd "
                        "if this write is intended."
                    ),
                }
            p = target
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {
            "ok": True,
            "bytes_written": len(content.encode("utf-8")),
            "path": str(p),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def tool_list_dir(path: str = ".") -> dict[str, Any]:
    """List files + dirs in a directory (non-recursive)."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"path not found: {path}"}
        if not p.is_dir():
            return {"ok": False, "error": f"not a directory: {path}"}
        entries = []
        for child in sorted(p.iterdir()):
            kind = "dir" if child.is_dir() else "file"
            size = child.stat().st_size if child.is_file() else None
            entries.append({"name": child.name, "kind": kind, "size": size})
        return {"ok": True, "path": str(p), "entries": entries}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def tool_run_shell(command: str, timeout: int = DEFAULT_TIMEOUT_PER_SHELL) -> dict[str, Any]:
    """Run a shell command. Refuses obviously-destructive commands."""
    if not CONFIG.allow_dangerous:
        hit = _dangerous_match(command)
        if hit:
            return {
                "ok": False,
                "error": (
                    f"refusing dangerous command (matched pattern {hit!r}). "
                    "Re-run open-code with --allow-dangerous if this is intended."
                ),
            }
    try:
        proc = subprocess.run(  # noqa: S602 -- intentional shell=True
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if len(stdout) > MAX_SHELL_OUTPUT:
            stdout = stdout[:MAX_SHELL_OUTPUT] + f"\n[truncated, total {len(proc.stdout)} chars]"
        if len(stderr) > MAX_SHELL_OUTPUT:
            stderr = stderr[:MAX_SHELL_OUTPUT] + f"\n[truncated, total {len(proc.stderr)} chars]"
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"command timed out after {timeout}s: {command}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


TOOL_DECLARATIONS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file and return its contents.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"path": {"type": "STRING", "description": "Path to the file."}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write a file with the given content. Creates parent directories. "
            "Overwrites if the file exists. Refuses paths outside the working "
            "directory unless the user invoked open-code with --allow-outside-cwd."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Path to write."},
                "content": {"type": "STRING", "description": "File content."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List the entries in a directory (non-recursive).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Directory path. Defaults to '.'."}
            },
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Run a shell command in the current working directory. Returns "
            "stdout, stderr, and exit code. Cross-platform (cmd on Windows, "
            "sh on POSIX). Refuses obviously-destructive commands unless the "
            "user invoked open-code with --allow-dangerous."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {"type": "STRING", "description": "Shell command."},
                "timeout": {
                    "type": "INTEGER",
                    "description": f"Seconds before kill. Default {DEFAULT_TIMEOUT_PER_SHELL}.",
                },
            },
            "required": ["command"],
        },
    },
]


def tool_apply_patch(patch: str) -> dict[str, Any]:
    """Apply a V4A patch envelope. Body lives in patches.py to keep
    this module's surface small.

    Late import: tools.py is imported by patches.py for CONFIG / _is_under,
    so we can't import patches at module load.
    """
    from patches import apply_patch as _apply_patch
    return _apply_patch(patch)


# Static V4A apply_patch tool declaration — kept here to avoid a load-time
# cycle with patches.py. The runtime body lives in patches.py.
APPLY_PATCH_TOOL_DECLARATION = {
    "name": "apply_patch",
    "description": (
        "Apply a V4A patch envelope to the working directory in one shot. "
        "Use for multi-file edits, anchored hunks, and renames. The "
        "envelope must begin with `*** Begin Patch` and end with "
        "`*** End Patch`. Inside, use `*** Add File: <path>`, "
        "`*** Update File: <path>` (with `@@ anchor` lines and `+`/`-` "
        "diff lines), `*** Delete File: <path>`, or `*** Move to: <new>` "
        "(after an Update block). Hunks are anchored by surrounding "
        "code, NOT line numbers — if the anchor is ambiguous the patch "
        "fails clean. Honors --allow-outside-cwd."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "patch": {
                "type": "STRING",
                "description": "The full V4A envelope, beginning with "
                               "'*** Begin Patch' and ending with "
                               "'*** End Patch'.",
            },
        },
        "required": ["patch"],
    },
}

TOOL_DECLARATIONS.append(APPLY_PATCH_TOOL_DECLARATION)


TOOL_FUNCTIONS = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_dir": tool_list_dir,
    "run_shell": tool_run_shell,
    "apply_patch": tool_apply_patch,
}
