"""Tests for the v0.2 security guards (path sandbox + shell denylist).

Run with the project venv:
    .venv/Scripts/python.exe tests/test_security.py

Exit code 0 = all pass, non-zero = failure (with details printed).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_code import (  # noqa: E402
    CONFIG,
    _dangerous_match,
    tool_run_shell,
    tool_write_file,
)


def _check(label: str, ok: bool, detail: str = "") -> bool:
    glyph = "PASS" if ok else "FAIL"
    print(f"[{glyph}] {label}" + (f"  ({detail})" if detail else ""))
    return ok


def main() -> int:
    failures = 0
    passes = 0

    # --- Denylist pattern matching ---
    dangerous = [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf *",
        "sudo rm -rf /tmp",
        "shutdown -h now",
        "reboot",
        "halt",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "chmod -R 777 /",
        "format C:",
        "Remove-Item -Recurse -Force C:",
        ":(){ :|:& };:",
    ]
    safe = [
        "ls -la",
        "python --version",
        "echo hello world",
        "git status",
        "cat README.md",
        "pytest tests/",
        "rm temp.txt",  # rm without -rf on a relative non-root path
    ]

    for cmd in dangerous:
        if _check(
            f"denylist HIT for {cmd!r}",
            _dangerous_match(cmd) is not None,
        ):
            passes += 1
        else:
            failures += 1

    for cmd in safe:
        if _check(
            f"denylist PASSES safe cmd {cmd!r}",
            _dangerous_match(cmd) is None,
            f"matched={_dangerous_match(cmd)}",
        ):
            passes += 1
        else:
            failures += 1

    # --- Path sandbox via tool_write_file ---
    sandbox = Path(tempfile.mkdtemp(prefix="open-code-test-sandbox-"))
    outside = Path(tempfile.mkdtemp(prefix="open-code-test-outside-"))
    try:
        CONFIG.cwd = sandbox
        CONFIG.allow_outside_cwd = False

        # Inside CWD — allowed
        r = tool_write_file(str(sandbox / "inside.txt"), "ok")
        if _check("write inside CWD allowed", r.get("ok") is True, str(r)):
            passes += 1
        else:
            failures += 1

        # Outside CWD via absolute path — refused
        escape = outside / "escaped.txt"
        r = tool_write_file(str(escape), "should not exist")
        refused = r.get("ok") is False and "outside CWD" in (r.get("error") or "")
        not_written = not escape.exists()
        if _check("write outside CWD refused", refused and not_written, str(r)):
            passes += 1
        else:
            failures += 1

        # ../ relative escape — refused
        r = tool_write_file("../escaped.txt", "should not exist either")
        if _check("write via ../ refused", r.get("ok") is False, str(r)):
            passes += 1
        else:
            failures += 1

        # With override — allowed
        CONFIG.allow_outside_cwd = True
        r = tool_write_file(str(escape), "now allowed")
        if _check(
            "write outside CWD allowed when --allow-outside-cwd",
            r.get("ok") is True and escape.exists(),
            str(r),
        ):
            passes += 1
        else:
            failures += 1
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)
        CONFIG.allow_outside_cwd = False
        CONFIG.cwd = Path.cwd()

    # --- tool_run_shell behaviour with denylist ---
    CONFIG.allow_dangerous = False
    r = tool_run_shell("shutdown -h now")
    if _check(
        "tool_run_shell refuses denylisted (shutdown)",
        r.get("ok") is False and "dangerous" in (r.get("error") or "").lower(),
        str(r),
    ):
        passes += 1
    else:
        failures += 1

    r = tool_run_shell("echo hello")
    if _check(
        "tool_run_shell runs safe command",
        r.get("ok") is True and "hello" in (r.get("stdout") or ""),
        str(r),
    ):
        passes += 1
    else:
        failures += 1

    print()
    print(f"=== {passes} passed, {failures} failed ===")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
