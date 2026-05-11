"""Probe: --print JSON output mode (Tier 2 #20).

Runs run_loop with CONFIG.print_json = True and verifies the JSON
events emitted on stdout. Uses a stubbed Gemini client so the probe
is hermetic.
"""
from __future__ import annotations
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as OC
import sessions as SX
import tools as TOOLS
from settings import Settings
from google.genai import types as _t


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

    # Stub: turn 1 calls run_shell; turn 2 emits text + stop
    call_count = {"n": 0}

    class _Resp1:
        usage_metadata = type("U", (), {
            "prompt_token_count": 10, "candidates_token_count": 5,
        })()
        def __init__(self):
            self.candidates = [type("C", (), {
                "content": _t.Content(
                    role="model",
                    parts=[
                        _t.Part.from_text(text="I'll run echo."),
                        _t.Part.from_function_call(
                            name="run_shell",
                            args={"command": "echo hi"},
                        ),
                    ],
                )
            })()]

    class _Resp2:
        usage_metadata = type("U", (), {
            "prompt_token_count": 12, "candidates_token_count": 7,
        })()
        def __init__(self):
            self.candidates = [type("C", (), {
                "content": _t.Content(
                    role="model",
                    parts=[_t.Part.from_text(text="Done.")],
                )
            })()]

    class _StubModels:
        def generate_content(self, **kwargs):
            call_count["n"] += 1
            return _Resp2() if call_count["n"] >= 2 else _Resp1()
        def generate_content_stream(self, **kwargs):
            return iter([])

    class _StubClient:
        def __init__(self, **kwargs):
            self.models = _StubModels()

    TOOLS.CONFIG.print_json = True
    prior_cwd = TOOLS.CONFIG.cwd
    TOOLS.CONFIG.cwd = base

    buf = io.StringIO()
    try:
        with patch("open_code.genai.Client", _StubClient), \
             redirect_stdout(buf):
            OC.run_loop(
                task="please run echo",
                model="fake-model", api_key="x",
                max_iterations=4, store=store, session=s,
                verbose=False, stream=False,
                fire_session_start=False,
                settings=Settings(),
                is_repl=False,
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
TOOLS.CONFIG.print_json = False
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    store_root = base / "store"
    store_root.mkdir()
    store = SX.SessionStore(store_root)
    s = store.create(str(base), "fake-model", "silent test")

    class _StubResp:
        usage_metadata = None
        def __init__(self):
            self.candidates = [type("C", (), {
                "content": _t.Content(role="model",
                                      parts=[_t.Part.from_text(text="ok")])
            })()]

    class _StubModels:
        def generate_content(self, **kwargs):
            return _StubResp()
        def generate_content_stream(self, **kwargs):
            return iter([])

    class _StubClient:
        def __init__(self, **kwargs):
            self.models = _StubModels()

    prior_cwd = TOOLS.CONFIG.cwd
    TOOLS.CONFIG.cwd = base
    buf = io.StringIO()
    try:
        with patch("open_code.genai.Client", _StubClient), \
             redirect_stdout(buf):
            OC.run_loop(
                task="quiet", model="fake-model", api_key="x",
                max_iterations=2, store=store, session=s,
                verbose=False, stream=False,
                fire_session_start=False,
                settings=Settings(),
                is_repl=False,
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
