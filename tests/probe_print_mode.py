"""Probe: --print JSON output mode (Tier 2 #20).

Runs run_loop with CONFIG.print_json = True and verifies the JSON
events emitted on stdout. Uses a stubbed LLMClient so the probe is
hermetic. Post-decoupling, this stubs the neutral protocol -- no
provider-specific shapes leak into the test.
"""
from __future__ import annotations
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as OC
import sessions as SX
import tools as TOOLS
from settings import Settings
from llm import AskResult, Message, Part, Usage


def _parse_jsonl(s: str) -> list[dict]:
    out: list[dict] = []
    for line in s.splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


# ===========================================================================
# Test 1: _emit_json is a no-op when CONFIG.print_json is False
# ===========================================================================
TOOLS.CONFIG.print_json = False
buf = io.StringIO()
with redirect_stdout(buf):
    OC._emit_json("session_start", model="x")
assert buf.getvalue() == "", \
    f"_emit_json should be silent when print_json=False; got {buf.getvalue()!r}"
print("[PASS] _emit_json is a no-op when print_json=False")


# ===========================================================================
# Test 2: _emit_json writes a JSON line when CONFIG.print_json is True
# ===========================================================================
TOOLS.CONFIG.print_json = True
buf = io.StringIO()
with redirect_stdout(buf):
    OC._emit_json("session_start", model="gemini-3.1", task="hi")
TOOLS.CONFIG.print_json = False
out = buf.getvalue()
assert out.endswith("\n")
event = json.loads(out)
assert event["type"] == "session_start"
assert event["model"] == "gemini-3.1"
assert event["task"] == "hi"
print("[PASS] _emit_json writes a JSON line when print_json=True")


# ===========================================================================
# Test 3: run_loop emits the full event sequence under --print
# ===========================================================================
class TwoTurnFakeClient:
    """Turn 1: text + tool_call(run_shell). Turn 2: plain text done."""
    provider = "fake"

    def __init__(self):
        self._n = 0

    def ask(self, **kw):
        self._n += 1
        if self._n == 1:
            msg = Message(role="model", parts=[
                Part.make_text("I'll run echo."),
                Part.make_tool_call("run_shell", {"command": "echo hi"}),
            ])
            usage = Usage(input_tokens=10, output_tokens=5)
        else:
            msg = Message(role="model", parts=[Part.make_text("Done.")])
            usage = Usage(input_tokens=12, output_tokens=7)
        return AskResult(message=msg, usage=usage, stop_reason="stop")

    def ask_stream(self, **kw):
        yield from ()  # not used (stream=False)

    def embed(self, **kw):
        return []


with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    store_root = base / "store"
    store_root.mkdir()
    store = SX.SessionStore(store_root)
    s = store.create(str(base), "fake-model", "test")

    # Replace run_shell tool with a stub that doesn't depend on the OS
    orig_run = TOOLS.TOOL_FUNCTIONS.get("run_shell")
    TOOLS.TOOL_FUNCTIONS["run_shell"] = lambda **kw: {
        "ok": True, "stdout": "stub-out", "exit_code": 0,
    }

    TOOLS.CONFIG.print_json = True
    prior_cwd = TOOLS.CONFIG.cwd
    TOOLS.CONFIG.cwd = base

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            OC.run_loop(
                task="please run echo",
                model="fake-model", api_key="x",
                max_iterations=4, store=store, session=s,
                verbose=False, stream=False,
                fire_session_start=False,
                settings=Settings(),
                is_repl=False,
                llm=TwoTurnFakeClient(),
            )
    finally:
        TOOLS.CONFIG.print_json = False
        TOOLS.CONFIG.cwd = prior_cwd
        if orig_run is not None:
            TOOLS.TOOL_FUNCTIONS["run_shell"] = orig_run

    events = _parse_jsonl(buf.getvalue())
    types_seen = [e["type"] for e in events]
    # We expect: session_start, text (iter 1), tool_use, tool_result,
    # text (iter 2), session_end
    assert types_seen[0] == "session_start", f"first event: {types_seen[0]}"
    assert types_seen[-1] == "session_end", f"last event: {types_seen[-1]}"
    assert "tool_use" in types_seen
    assert "tool_result" in types_seen
    text_events = [e for e in events if e["type"] == "text"]
    assert len(text_events) == 2, f"expected 2 text events; got {len(text_events)}"
    assert "echo" in text_events[0]["text"]
    tool_use = [e for e in events if e["type"] == "tool_use"][0]
    assert tool_use["name"] == "run_shell"
    assert tool_use["args"]["command"] == "echo hi"
    tool_result = [e for e in events if e["type"] == "tool_result"][0]
    assert tool_result["ok"] is True
    assert tool_result["result"]["stdout"] == "stub-out"
    end_evt = events[-1]
    assert end_evt["exit_code"] == 0
    assert end_evt["tool_calls"] >= 1
    assert end_evt["input_tokens"] >= 10  # at least one turn's tokens

print("[PASS] run_loop emits expected JSON event sequence under --print")


# ===========================================================================
# Test 4: print_json off -> no events on stdout
# ===========================================================================
class SilentFakeClient:
    provider = "fake"

    def ask(self, **kw):
        return AskResult(
            message=Message(role="model", parts=[Part.make_text("ok")]),
            usage=Usage(), stop_reason="stop",
        )

    def ask_stream(self, **kw):
        yield from ()

    def embed(self, **kw):
        return []


TOOLS.CONFIG.print_json = False
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    store_root = base / "store"
    store_root.mkdir()
    store = SX.SessionStore(store_root)
    s = store.create(str(base), "fake-model", "silent test")

    prior_cwd = TOOLS.CONFIG.cwd
    TOOLS.CONFIG.cwd = base
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            OC.run_loop(
                task="quiet", model="fake-model", api_key="x",
                max_iterations=2, store=store, session=s,
                verbose=False, stream=False,
                fire_session_start=False,
                settings=Settings(),
                is_repl=False,
                llm=SilentFakeClient(),
            )
    finally:
        TOOLS.CONFIG.cwd = prior_cwd
    out = buf.getvalue()
    # With print_json=False, stdout may contain plain model text
    # ("ok" in this stub) but NEVER JSON envelopes for session_start /
    # tool_use / session_end / etc.
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # plain text -- expected when print_json=False
        # If we got here it parsed as JSON -- check if it's one of our
        # envelope types
        if isinstance(obj, dict) and obj.get("type") in (
            "session_start", "session_end", "tool_use", "tool_result", "text",
        ):
            raise AssertionError(
                f"print_json=False should not emit envelope events; got: {line!r}"
            )
print("[PASS] print_json=False emits no JSON envelope events on stdout")


print("\nOK -- print-mode probes passed.")
