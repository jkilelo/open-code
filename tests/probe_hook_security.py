"""Probe: hook trust gate (v0.14.2).

Before v0.14.2: hooks fired automatically from any project's
.open-code/hooks/. Cloning a hostile repo and running open-code in it
would execute attacker code. This was logged as a brutal-review [FAIL].

v0.14.2 introduces a trust gate:
  - `hooks.ensure_hooks_trusted(cwd, interactive=..., trust_override=...)`
    is called by cli.main once at session start.
  - In interactive mode, the user is prompted with the inventory of
    hook scripts and chooses allow-once / trust-always / deny.
  - In non-interactive mode (one-shot pipe), the answer is "deny"
    unless `--trust-hooks` was passed.
  - `hooks.fire()` now refuses to invoke any script unless the project
    has been marked trusted in this session.

This probe asserts the FIX:
  1. By default (untrusted), a malicious hook does NOT run -- no marker.
  2. After explicit trust, the hook runs.
"""
from __future__ import annotations
import sys, pathlib, tempfile, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import hooks

td = pathlib.Path(tempfile.mkdtemp(prefix="oc-pwn-")).resolve()
hooks_dir = td / ".open-code" / "hooks" / "PreToolUse"
hooks_dir.mkdir(parents=True)
script = hooks_dir / "000-pwn.py"

marker = td / "PWNED.txt"
script.write_text(
    f"import sys, os, pathlib\n"
    f"pathlib.Path({str(marker)!r}).write_text('hello from your hooks')\n"
    f"sys.exit(0)\n",
    encoding="utf-8",
)
if os.name != "nt":
    script.chmod(0o755)

# Reset session trust to simulate a fresh process.
hooks.clear_session_trust()

# ---- Case 1: UNTRUSTED -- hooks must NOT fire ----
result = hooks.fire("PreToolUse", td, session_id="x",
                    payload={"tool": "read_file", "args": {"path": "anywhere"}})
assert result.invoked == [], (
    f"REGRESSION: untrusted hook fired anyway. invoked={result.invoked}"
)
assert not marker.exists(), (
    f"REGRESSION: hook wrote {marker} despite trust gate"
)
print(f"[PASS] untrusted project: hook refused; marker NOT written")

# ---- Case 2: EXPLICITLY TRUSTED -- hooks fire normally ----
hooks.mark_project_trusted(td, "allow", persist=False)
result = hooks.fire("PreToolUse", td, session_id="x",
                    payload={"tool": "read_file", "args": {"path": "anywhere"}})
assert "000-pwn.py" in result.invoked, (
    f"after trust, hook should have fired; invoked={result.invoked}"
)
assert marker.exists(), "after trust, hook should have written marker"
print(f"[PASS] trusted project: hook fires; marker written: {marker.read_text()!r}")

# ---- Case 3: ensure_hooks_trusted in non-interactive mode auto-denies ----
hooks.clear_session_trust()
# (Pretend non-tty: explicit interactive=False)
allowed = hooks.ensure_hooks_trusted(td, interactive=False, trust_override=False)
assert not allowed, "non-interactive without --trust-hooks should auto-deny"
print(f"[PASS] non-interactive mode auto-denies untrusted project")

# ---- Case 4: --trust-hooks override bypasses prompt ----
hooks.clear_session_trust()
allowed = hooks.ensure_hooks_trusted(td, interactive=False, trust_override=True)
assert allowed, "--trust-hooks should allow despite non-interactive mode"
result = hooks.fire("PreToolUse", td, session_id="x",
                    payload={"tool": "read_file", "args": {}})
assert "000-pwn.py" in result.invoked
print(f"[PASS] trust_override (--trust-hooks) bypasses non-interactive auto-deny")

# Cleanup: reset session trust so other tests in the suite aren't affected.
hooks.clear_session_trust()

print("\nOK -- hook trust gate works end-to-end. RCE-by-cd-into-hostile-repo blocked.")
