"""Probe: permission modes (plan / acceptEdits / bypassPermissions).

After the LLM decoupling, this probe injects a fake LLMClient instead
of monkey-patching genai.Client. The streaming contract is the
LLMClient protocol; the loop is fully provider-agnostic.
"""
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


# ---- Test 5+: run_loop mode-gating via a fake LLMClient ----
from open_code import run_loop, SYSTEM_INSTRUCTION
from sessions import SessionStore
from tools import CONFIG
from llm import Part, StreamChunk


class CyclingFakeClient:
    """First call streams a tool_call Part; subsequent calls stream a
    text 'done' part. Exercises the iter-1-tool, iter-2-stop flow that
    every mode probe needs."""
    provider = "fake"

    def __init__(self, tool_call: Part, done_text: str):
        self._tool = tool_call
        self._done = done_text
        self._n = 0

    def ask(self, **kw):
        raise NotImplementedError

    def ask_stream(self, **kw):
        self._n += 1
        if self._n == 1:
            yield StreamChunk(text_delta="", tool_calls=[self._tool])
        else:
            yield StreamChunk(text_delta=self._done, tool_calls=[])

    def embed(self, **kw):
        return []


# Plan mode: write_file call is denied
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    CONFIG.cwd = base
    store_root = base / "sessroot"
    store = SessionStore(store_root)
    session = store.create(str(base), "fake", "test plan mode")

    fake_llm = CyclingFakeClient(
        tool_call=Part.make_tool_call("write_file", {"path": "x.txt", "content": "hi"}),
        done_text="(plan-mode iter)",
    )

    s_plan = S.Settings(mode="plan")
    code, metrics = run_loop(
        task="please write x.txt",
        model="fake", api_key="fake", max_iterations=5,
        store=store, session=session,
        initial_history=[], verbose=False, stream=True,
        system_instruction=SYSTEM_INSTRUCTION, settings=s_plan,
        is_repl=False, fire_session_start=False,
        llm=fake_llm,
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

    fake_llm = CyclingFakeClient(
        tool_call=Part.make_tool_call("write_file", {"path": "y.txt", "content": "hi"}),
        done_text="(bypass-mode iter)",
    )

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
        llm=fake_llm,
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

    fake_llm = CyclingFakeClient(
        tool_call=Part.make_tool_call("write_file", {"path": "z.txt", "content": "hi"}),
        done_text="(acceptEdits iter)",
    )

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
        llm=fake_llm,
    )
    assert metrics["tool_errors"] == 0, f"acceptEdits should allow; metrics={metrics}"
    assert (base / "z.txt").exists(), "acceptEdits should write"
print("[PASS] acceptEdits turns ask -> allow for write_file")


print("\nOK -- 7 modes probes passed.")
