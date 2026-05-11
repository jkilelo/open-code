"""Probe: permission modes (plan / acceptEdits / bypassPermissions)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings as S


# ---- Test 1: VALID_MODES tuple is correct ----
assert S.VALID_MODES == ("default", "acceptEdits", "plan", "auto", "bypassPermissions")
print("[PASS] VALID_MODES tuple")


# ---- Test 2: default mode = "default" ----
s = S.Settings()
assert s.mode == "default", f"got {s.mode!r}"
print("[PASS] Settings() defaults to mode='default'")


# ---- Test 3: settings.json with mode roundtrips ----
import json
import tempfile
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / ".open-code").mkdir()
    (base / ".open-code" / "settings.json").write_text(
        json.dumps({"mode": "plan"}), encoding="utf-8"
    )
    loaded = S.load_layered_settings(base)
    assert loaded.mode == "plan", f"got {loaded.mode!r}"
print("[PASS] settings.json mode round-trips")


# ---- Test 4: invalid mode falls back to default ----
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    (base / ".open-code").mkdir()
    (base / ".open-code" / "settings.json").write_text(
        json.dumps({"mode": "bogus-mode-xyz"}), encoding="utf-8"
    )
    loaded = S.load_layered_settings(base)
    assert loaded.mode == "default", f"invalid mode should fall back; got {loaded.mode!r}"
print("[PASS] invalid mode -> default fallback")


# ---- Test 5: Now exercise the run_loop mode-gating logic via a mock ----
# Import run_loop's mode logic by importing what we need
from open_code import run_loop, SYSTEM_INSTRUCTION
from sessions import SessionStore
from tools import CONFIG
from unittest.mock import MagicMock
from google.genai import types

# Build a fake client that always asks to call write_file once then stops
class _FakeStream:
    def __init__(self, parts):
        self._parts = parts
    def __iter__(self):
        chunk = MagicMock()
        cand = MagicMock()
        cand.content = types.Content(role="model", parts=self._parts)
        chunk.candidates = [cand]
        chunk.usage_metadata = None
        yield chunk

def _fake_client_factory(*, parts):
    client = MagicMock()
    def stream(**kw):
        return _FakeStream(parts)
    client.models.generate_content_stream = stream
    return client

def _patch_client(parts):
    import open_code
    client = _fake_client_factory(parts=parts)
    open_code.genai.Client = lambda **kw: client


# Plan mode: write_file call is denied
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    CONFIG.cwd = base
    store_root = base / "sessroot"
    store = SessionStore(store_root)
    session = store.create(str(base), "fake", "test plan mode")

    # First model turn: try to write a file
    write_part = types.Part(
        function_call=types.FunctionCall(
            name="write_file", args={"path": "x.txt", "content": "hi"}
        )
    )
    text_done = types.Part.from_text(text="(plan-mode iter)")

    # Cycle: first iter wants write_file; second iter no tools (model "concludes")
    call_count = {"n": 0}
    import open_code
    class _CyclingClient:
        class models:
            @staticmethod
            def generate_content_stream(**kw):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return _FakeStream([write_part])
                return _FakeStream([text_done])
    open_code.genai.Client = lambda **kw: _CyclingClient()

    s_plan = S.Settings(mode="plan")
    code, metrics = run_loop(
        task="please write x.txt",
        model="fake", api_key="fake", max_iterations=5,
        store=store, session=session,
        initial_history=[], verbose=False, stream=True,
        system_instruction=SYSTEM_INSTRUCTION, settings=s_plan,
        is_repl=False, fire_session_start=False,
    )
    assert metrics["tool_errors"] >= 1, f"plan mode should deny write_file; metrics={metrics}"
    assert not (base / "x.txt").exists(), "plan mode should NOT have written the file"
print("[PASS] plan mode denies write_file; file not created")


# Test 6: bypassPermissions actually bypasses an explicit ask rule
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    CONFIG.cwd = base
    CONFIG.allow_outside_cwd = False
    store = SessionStore(base / "sessroot")
    session = store.create(str(base), "fake", "test bypass")

    write_part = types.Part(
        function_call=types.FunctionCall(
            name="write_file", args={"path": "y.txt", "content": "hi"}
        )
    )
    text_done = types.Part.from_text(text="(bypass-mode iter)")
    call_count = {"n": 0}
    import open_code
    class _CyclingClient2:
        class models:
            @staticmethod
            def generate_content_stream(**kw):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return _FakeStream([write_part])
                return _FakeStream([text_done])
    open_code.genai.Client = lambda **kw: _CyclingClient2()

    s_bypass = S.Settings(
        mode="bypassPermissions",
        permissions=S.PermissionRules(ask=["write_file(*)"]),
    )
    code, metrics = run_loop(
        task="please write y.txt",
        model="fake", api_key="fake", max_iterations=5,
        store=store, session=session,
        initial_history=[], verbose=False, stream=True,
        system_instruction=SYSTEM_INSTRUCTION, settings=s_bypass,
        is_repl=False, fire_session_start=False,
    )
    assert metrics["tool_errors"] == 0, f"bypass should allow; metrics={metrics}"
    assert (base / "y.txt").exists(), "bypass mode should allow write"
print("[PASS] bypassPermissions skips ask rule; file written")


# Test 7: acceptEdits turns ask into allow for write_file
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    CONFIG.cwd = base
    CONFIG.allow_outside_cwd = False
    store = SessionStore(base / "sessroot")
    session = store.create(str(base), "fake", "test acceptEdits")

    write_part = types.Part(
        function_call=types.FunctionCall(
            name="write_file", args={"path": "z.txt", "content": "hi"}
        )
    )
    text_done = types.Part.from_text(text="(acceptEdits iter)")
    call_count = {"n": 0}
    import open_code
    class _CyclingClient3:
        class models:
            @staticmethod
            def generate_content_stream(**kw):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return _FakeStream([write_part])
                return _FakeStream([text_done])
    open_code.genai.Client = lambda **kw: _CyclingClient3()

    s_accept = S.Settings(
        mode="acceptEdits",
        permissions=S.PermissionRules(ask=["write_file(*)"]),
    )
    code, metrics = run_loop(
        task="write z.txt",
        model="fake", api_key="fake", max_iterations=5,
        store=store, session=session,
        initial_history=[], verbose=False, stream=True,
        system_instruction=SYSTEM_INSTRUCTION, settings=s_accept,
        is_repl=False, fire_session_start=False,
    )
    assert metrics["tool_errors"] == 0, f"acceptEdits should allow; metrics={metrics}"
    assert (base / "z.txt").exists(), "acceptEdits should write"
print("[PASS] acceptEdits turns ask -> allow for write_file")


print("\nOK -- 7 modes probes passed.")
