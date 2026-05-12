"""Probe: ui.py rendering across rich / plain / json modes."""
from __future__ import annotations
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ui as UI_MOD


# ===========================================================================
# Test 1: detect_mode honors precedence (json > plain > NO_COLOR > tty)
# ===========================================================================
class _FakeStream:
    def __init__(self, is_tty: bool) -> None:
        self._is_tty = is_tty
    def isatty(self) -> bool:
        return self._is_tty


tty = _FakeStream(True)
non_tty = _FakeStream(False)

# json wins everything
assert UI_MOD.detect_mode(json_override=True, stream=tty) == "json"
assert UI_MOD.detect_mode(json_override=True, plain_override=True,
                          stream=tty) == "json"
# plain wins over TTY
assert UI_MOD.detect_mode(plain_override=True, stream=tty) == "plain"
# Non-TTY -> plain
assert UI_MOD.detect_mode(stream=non_tty) == "plain"
# TTY + no overrides + no env -> rich
saved = {k: os.environ.pop(k, None) for k in
         ("NO_COLOR", "OPEN_CODE_PLAIN")}
try:
    assert UI_MOD.detect_mode(stream=tty) == "rich"
    # NO_COLOR forces plain
    os.environ["NO_COLOR"] = "1"
    assert UI_MOD.detect_mode(stream=tty) == "plain"
    del os.environ["NO_COLOR"]
    # OPEN_CODE_PLAIN forces plain
    os.environ["OPEN_CODE_PLAIN"] = "1"
    assert UI_MOD.detect_mode(stream=tty) == "plain"
    del os.environ["OPEN_CODE_PLAIN"]
finally:
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
print("[PASS] detect_mode honors json > plain > NO_COLOR/env > TTY")


# ===========================================================================
# Test 2: plain mode output is pure ASCII + has no ANSI escapes
# ===========================================================================
buf = io.StringIO()
with redirect_stderr(buf):
    u = UI_MOD.UI(mode="plain", quiet=False, stderr=True)
    u.tool_call("run_shell", {"command": "echo hi"})
    u.tool_result("run_shell", {"ok": True, "stdout": "hi", "exit_code": 0})
    u.tool_result("run_shell", {"ok": False, "error": "denied"})
    u.status_line(model="m", iter=1, in_tok=5, out_tok=3, tool_errs=0)
    u.info("trace")
    u.warn("oops")
    u.error("nope")
    u.banner(session_id="abc-123", cwd="/tmp/x", model="fake")
    u.table(title="Things", columns=["a", "b"],
            rows=[["1", "2"], ["3", "4"]])

out = buf.getvalue()
# Pure ASCII
assert all(ord(c) < 128 for c in out), \
    f"plain mode produced non-ASCII chars; sample: {out[:200]!r}"
# No ANSI escape codes
assert "\x1b[" not in out, \
    f"plain mode emitted ANSI escapes; sample: {out[:200]!r}"
# Expected substrings
assert "  -> run_shell" in out
assert "  [OK] run_shell" in out
assert "  [X] run_shell" in out
assert "[error] nope" in out
print("[PASS] plain mode is pure ASCII, no ANSI escapes")


# ===========================================================================
# Test 3: rich mode produces ANSI escapes when forced
# ===========================================================================
# We can't force a TTY but we can force_terminal via the Console's
# constructor. Easiest path: construct a UI in rich mode and have it
# write to a StringIO. Rich won't auto-color unless the file looks
# like a TTY, so we'll patch the lazy-built console with one that
# forces terminal mode.
buf = io.StringIO()
u = UI_MOD.UI(mode="rich", quiet=False, stderr=True)
from rich.console import Console
u._console = Console(file=buf, force_terminal=True,
                     color_system="truecolor",
                     highlight=False, soft_wrap=True)
u.tool_call("run_shell", {"command": "ls"})
u.tool_result("run_shell", {"ok": True, "stdout": "x", "exit_code": 0})
u.tool_result("run_shell", {"ok": False, "error": "denied"})
u.status_line(model="m", iter=1)
out = buf.getvalue()
assert "\x1b[" in out, "rich mode should emit ANSI escapes when force_terminal=True"
# Content still present despite the ANSI wrapping
assert "run_shell" in out
assert "[OK]" in out or "[X]" in out
print("[PASS] rich mode emits ANSI escapes when forced")


# ===========================================================================
# Test 4: json mode renders nothing through UI (all methods are no-ops)
# ===========================================================================
buf_err = io.StringIO()
buf_out = io.StringIO()
with redirect_stderr(buf_err), redirect_stdout(buf_out):
    u = UI_MOD.UI(mode="json", quiet=False, stderr=True)
    u.tool_call("x", {})
    u.tool_result("x", {"ok": True})
    u.status_line(a=1)
    u.info("info")
    u.warn("warn")
    u.error("error")
    u.banner(session_id="s", cwd="/t")
    u.table(title="t", columns=["a"], rows=[["1"]])
    u.line("hello")
    u.model_text("text")
# stderr stays empty; stdout stays empty (model_text is also gated)
assert buf_err.getvalue() == "", \
    f"json mode wrote to stderr: {buf_err.getvalue()!r}"
assert buf_out.getvalue() == "", \
    f"json mode wrote to stdout: {buf_out.getvalue()!r}"
print("[PASS] json mode: all UI methods are no-ops")


# ===========================================================================
# Test 5: quiet=True suppresses info/tool_call/tool_result but NOT error
# ===========================================================================
buf = io.StringIO()
with redirect_stderr(buf):
    u = UI_MOD.UI(mode="plain", quiet=True, stderr=True)
    u.info("should be suppressed")
    u.tool_call("hidden", {})
    u.tool_result("hidden", {"ok": True})
    u.status_line(a=1)
    u.error("must show")
out = buf.getvalue()
assert "should be suppressed" not in out
assert "hidden" not in out
assert "must show" in out
print("[PASS] quiet=True suppresses chatter but errors still surface")


# ===========================================================================
# Test 6: UI.auto picks the right mode given args + stream tty-ness
# ===========================================================================
u1 = UI_MOD.UI.auto(plain=True, stderr=True)
assert u1.mode == "plain"
u2 = UI_MOD.UI.auto(json_mode=True, stderr=True)
assert u2.mode == "json"
# When stderr isn't a tty (which is the case in this probe run), auto
# should pick plain even without --plain.
u3 = UI_MOD.UI.auto(stderr=True)
assert u3.mode in ("plain", "rich"), f"unexpected mode {u3.mode}"
# In test environments, stderr is usually NOT a TTY, so mode is plain.
# This assertion is contextual; just verify the call succeeds.
print(f"[PASS] UI.auto returns valid mode (got {u3.mode!r} in this env)")


# ===========================================================================
# Test 7 (closes brutal-review Y2): empty_listing emits visible output
# in EVERY mode, including json. Before the fix, ui.line() was used for
# empty-state messages and silently dropped them under --print.
# ===========================================================================

# plain mode -> plain text on stderr
buf = io.StringIO()
with redirect_stderr(buf):
    u = UI_MOD.UI(mode="plain", stderr=True)
    u.empty_listing("(no sessions)", kind="sessions")
assert "(no sessions)" in buf.getvalue()
assert all(ord(c) < 128 for c in buf.getvalue())

# json mode -> JSON event on stdout (not stderr)
buf_out = io.StringIO()
buf_err = io.StringIO()
with redirect_stdout(buf_out), redirect_stderr(buf_err):
    u = UI_MOD.UI(mode="json", stderr=True)
    u.empty_listing("(no sessions)", kind="sessions")
assert buf_err.getvalue() == "", \
    f"json empty_listing should NOT write to stderr; got {buf_err.getvalue()!r}"
out = buf_out.getvalue().strip()
assert out, "json empty_listing should produce stdout"
event = json.loads(out)
assert event == {"type": "listing_empty", "kind": "sessions",
                 "message": "(no sessions)"}, f"got {event}"
print("[PASS] empty_listing: visible in plain mode AND json mode (Y2 fix)")


# ===========================================================================
# Test 8: LiveStatusPanel - construction + no-op fallback
# ===========================================================================

# plain mode -> NoOpPanel
u = UI_MOD.UI(mode="plain")
p = u.live_panel(model="x", max_iters=10)
assert isinstance(p, UI_MOD.NoOpPanel), f"plain mode must return NoOpPanel; got {type(p)}"
p.start()
p.update(iter=1, in_tok=100)
p.set_action("doing thing")
p.stop()
# Context-manager form
with u.live_panel(model="x", max_iters=10) as p2:
    p2.update(iter=2)
print("[PASS] LiveStatusPanel: plain mode returns NoOpPanel; ctx-mgr works")


# json mode -> NoOpPanel
u = UI_MOD.UI(mode="json")
p = u.live_panel(model="x", max_iters=10)
assert isinstance(p, UI_MOD.NoOpPanel)
print("[PASS] LiveStatusPanel: json mode returns NoOpPanel")


# rich mode but env disable -> NoOpPanel
os.environ["OPEN_CODE_NO_PANEL"] = "1"
try:
    u = UI_MOD.UI(mode="rich")
    p = u.live_panel(model="x", max_iters=10)
    assert isinstance(p, UI_MOD.NoOpPanel), (
        "OPEN_CODE_NO_PANEL=1 must force NoOpPanel even in rich mode"
    )
finally:
    os.environ.pop("OPEN_CODE_NO_PANEL", None)
print("[PASS] LiveStatusPanel: OPEN_CODE_NO_PANEL=1 forces NoOpPanel")


# rich mode + non-TTY console -> NoOpPanel (auto-detected via is_terminal)
u = UI_MOD.UI(mode="rich")
p = u.live_panel(model="x", max_iters=10)
# In a typical test runner, stderr is NOT a TTY, so the panel
# detects this and returns NoOpPanel. We can't reliably force a TTY
# without a pseudo-terminal harness, so this is the assertion.
assert isinstance(p, UI_MOD.NoOpPanel), (
    f"non-TTY stderr should yield NoOpPanel; got {type(p)}"
)
print("[PASS] LiveStatusPanel: non-TTY auto-degrades to NoOpPanel")


# LiveStatusPanel redirect-flag regression (real-terminal bug from
# v0.27.1: panel rendered first row, then model response was eaten
# because redirect_stdout=False meant streamed writes hit the cursor
# Live was managing). Source-level assertion: don't ship redirect=False.
import inspect
panel_src = inspect.getsource(UI_MOD.LiveStatusPanel.start)
assert "redirect_stdout=False" not in panel_src, (
    "v0.27.1 regression: Live(redirect_stdout=False) eats streamed "
    "model text + tool prints. Defaults must be used (True)."
)
assert "redirect_stderr=False" not in panel_src
print("[PASS] LiveStatusPanel: stdout/stderr redirect not disabled")


# token formatter
assert UI_MOD._fmt_tokens(0) == "0"
assert UI_MOD._fmt_tokens(999) == "999"
assert UI_MOD._fmt_tokens(1000) == "1.0K"
assert UI_MOD._fmt_tokens(12345) == "12.3K"
assert UI_MOD._fmt_tokens(1234567) == "1.2M"
print("[PASS] _fmt_tokens: 0/999/1.0K/12.3K/1.2M")


print("\nOK -- ui probes passed.")
