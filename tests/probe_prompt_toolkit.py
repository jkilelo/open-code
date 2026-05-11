"""Probe: ui.prompt() input-side integration.

prompt_toolkit needs an interactive TTY for its real behavior, so
this probe focuses on:
  1. The fallback chain when PT is unavailable / stdin isn't a TTY.
  2. The plumbing: ui.prompt receives the right args and returns
     whatever the underlying input source returned.
  3. Exception propagation (EOFError, KeyboardInterrupt).
  4. The cached PromptSession is reused across calls in rich mode.
  5. _try_pt's tri-state cache works.
"""
from __future__ import annotations
import builtins
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ui as UI_MOD


# ===========================================================================
# Test 1: plain mode -> falls back to input() always
# ===========================================================================
u = UI_MOD.UI(mode="plain")
inputs = ["hello world"]
with patch.object(builtins, "input", lambda prompt="": inputs.pop(0)):
    result = u.prompt(">> ")
assert result == "hello world"
assert u._pt_available is False, "plain mode must short-circuit _try_pt"
print("[PASS] plain mode falls back to input() and never tries PT")


# ===========================================================================
# Test 2: rich mode + non-TTY stdin -> falls back to input()
# ===========================================================================
# In the test environment stdin is usually not a TTY. _try_pt should
# detect this and disable PT.
u = UI_MOD.UI(mode="rich")
# stdin.isatty() is what _try_pt checks. In a test runner this is False.
inputs = ["fallback works"]
with patch.object(builtins, "input", lambda prompt="": inputs.pop(0)):
    result = u.prompt("> ")
assert result == "fallback works"
assert u._pt_available is False, (
    "rich mode + non-TTY stdin must disable PT"
)
print("[PASS] rich mode + non-TTY stdin falls back to input()")


# ===========================================================================
# Test 3: _try_pt result is cached (tri-state -> bool)
# ===========================================================================
u = UI_MOD.UI(mode="plain")
assert u._pt_available is None  # tri-state: unknown
first = u._try_pt()
assert u._pt_available is False
second = u._try_pt()
assert first == second
print("[PASS] _try_pt caches its result after first call")


# ===========================================================================
# Test 4: prompt_toolkit ImportError -> graceful fallback
# ===========================================================================
# Simulate "not installed" using the documented sys.modules[name]=None
# sentinel which causes future `import prompt_toolkit` to raise
# ImportError. Save + restore so other tests are unaffected.
_pt_saved: dict[str, object] = {}
for _k in list(sys.modules):
    if _k == "prompt_toolkit" or _k.startswith("prompt_toolkit."):
        _pt_saved[_k] = sys.modules.pop(_k)
sys.modules["prompt_toolkit"] = None  # type: ignore[assignment]
try:
    u = UI_MOD.UI(mode="rich")
    with patch.object(sys.stdin, "isatty", lambda: True):
        inputs = ["import-fallback"]
        with patch.object(builtins, "input",
                          lambda prompt="": inputs.pop(0)):
            result = u.prompt("> ")
    assert result == "import-fallback", f"got {result!r}"
    assert u._pt_available is False
finally:
    sys.modules.pop("prompt_toolkit", None)
    for _k, _v in _pt_saved.items():
        sys.modules[_k] = _v  # type: ignore[assignment]
print("[PASS] prompt_toolkit ImportError falls back to input() cleanly")


# ===========================================================================
# Test 5: completions list is accepted; passing it doesn't crash even
# when PT is unavailable (fallback ignores it -- builtin input() doesn't
# do completions but the API is stable).
# ===========================================================================
u = UI_MOD.UI(mode="plain")
inputs = ["/sk"]
with patch.object(builtins, "input", lambda prompt="": inputs.pop(0)):
    result = u.prompt(
        "> ",
        completions=["/skill", "/skills", "/style", "/sessions"],
    )
assert result == "/sk"
print("[PASS] completions arg accepted in fallback path without crashing")


# ===========================================================================
# Test 6: EOFError + KeyboardInterrupt propagate (so REPL can handle them)
# ===========================================================================
u = UI_MOD.UI(mode="plain")
def _raise_eof(prompt=""):
    raise EOFError()
def _raise_kbi(prompt=""):
    raise KeyboardInterrupt()

with patch.object(builtins, "input", _raise_eof):
    raised = False
    try:
        u.prompt(">> ")
    except EOFError:
        raised = True
    assert raised, "EOFError must propagate"

with patch.object(builtins, "input", _raise_kbi):
    raised = False
    try:
        u.prompt(">> ")
    except KeyboardInterrupt:
        raised = True
    assert raised, "KeyboardInterrupt must propagate"
print("[PASS] EOFError + KeyboardInterrupt propagate to caller")


# ===========================================================================
# Test 7: reset_input() drops the cached PromptSession
# ===========================================================================
u = UI_MOD.UI(mode="rich")
u._pt_session = "fake-session-marker"
u.reset_input()
assert u._pt_session is None
print("[PASS] reset_input() drops cached PromptSession")


# ===========================================================================
# Test 8: history_file path with non-existent parent is handled
# (in PT path it would mkdir; in fallback it's just ignored).
# ===========================================================================
u = UI_MOD.UI(mode="plain")
fake_path = Path("/nonexistent/dir/history.txt")
inputs = ["ok"]
with patch.object(builtins, "input", lambda prompt="": inputs.pop(0)):
    # Should not raise even though the path doesn't exist; fallback
    # path doesn't touch the filesystem at all.
    result = u.prompt("> ", history_file=fake_path)
assert result == "ok"
print("[PASS] history_file with non-existent dir handled in fallback")


print("\nOK -- prompt_toolkit probes passed.")
