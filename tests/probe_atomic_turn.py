"""Probe: atomic-commit per turn (Tier 2 #12).

Tests:
  - run_loop emits BOTH turn-start AND turn-end checkpoint events
    when settings.auto_checkpoint is True (no live API call).
  - turn-end snapshot survives KeyboardInterrupt mid-loop.
  - SessionStore.recent_checkpoints(phase="turn-start") returns
    events newest-first for /undo lookup.
"""
from __future__ import annotations
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import checkpoints as CK
import sessions as SX
import open_code as OC
from settings import Settings


_HAVE_GIT = shutil.which("git") is not None


# ===========================================================================
# Test 1: SessionStore.recent_checkpoints filters by phase + sorts newest-first
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    store = SX.SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "ckpt sort test")
    store.append_checkpoint(s, sha="a" * 40, label="t1 start",
                            phase="turn-start")
    store.append_checkpoint(s, sha="b" * 40, label="t1 end",
                            phase="turn-end")
    store.append_checkpoint(s, sha="c" * 40, label="t2 start",
                            phase="turn-start")
    store.append_checkpoint(s, sha="d" * 40, label="t2 end",
                            phase="turn-end")
    starts = store.recent_checkpoints(s, phase="turn-start")
    assert len(starts) == 2, f"got {len(starts)} turn-starts"
    assert starts[0]["sha"] == "c" * 40, "newest-first ordering broken"
    assert starts[1]["sha"] == "a" * 40
    ends = store.recent_checkpoints(s, phase="turn-end")
    assert len(ends) == 2 and ends[0]["sha"] == "d" * 40
    all_ = store.recent_checkpoints(s)
    assert len(all_) == 4
print("[PASS] recent_checkpoints filters by phase, newest first")


# ===========================================================================
# Test 2: run_loop emits BOTH turn-start AND turn-end checkpoints
# ===========================================================================
if not _HAVE_GIT:
    print("[SKIP] run_loop turn-start+turn-end: git missing")
else:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d).resolve()
        store_root = base / "store"
        store_root.mkdir()
        store = SX.SessionStore(store_root)
        s = store.create(str(base), "fake", "atomic-turn test")

        # Stub Gemini client so we never call the live API.
        class _StubChunk:
            def __init__(self, parts=None, usage=None):
                self.candidates = []
                self.usage_metadata = usage

        class _StubResp:
            candidates = []
            usage_metadata = None
            def __init__(self):
                from google.genai import types as _t
                self.candidates = [type("C", (), {
                    "content": _t.Content(role="model",
                                          parts=[_t.Part.from_text(text="ok done")])
                })()]

        class _StubModels:
            def generate_content(self, **kwargs):
                return _StubResp()
            def generate_content_stream(self, **kwargs):
                return iter([])  # streaming off path

        class _StubClient:
            def __init__(self, **kwargs):
                self.models = _StubModels()

        st = Settings(auto_checkpoint=True)
        # Point CONFIG.cwd at our test dir
        prior_cwd = OC.CONFIG.cwd
        OC.CONFIG.cwd = base
        try:
            with patch("open_code.genai.Client", _StubClient):
                OC.run_loop(
                    task="hello atomic",
                    model="fake", api_key="x",
                    max_iterations=2, store=store, session=s,
                    verbose=False, stream=False,
                    fire_session_start=False,
                    settings=st, is_repl=False,
                )
        finally:
            OC.CONFIG.cwd = prior_cwd

        ts = store.recent_checkpoints(s, phase="turn-start")
        te = store.recent_checkpoints(s, phase="turn-end")
        assert len(ts) == 1, f"expected 1 turn-start, got {len(ts)}"
        assert len(te) == 1, f"expected 1 turn-end, got {len(te)}"
        assert ts[0]["sha"] != te[0]["sha"], \
            "turn-start and turn-end should be distinct commits"
        # Both should be resolvable in the shadow repo
        assert CK.resolve_ref(base, ts[0]["sha"]) is not None
        assert CK.resolve_ref(base, te[0]["sha"]) is not None
    print("[PASS] run_loop emits both turn-start AND turn-end checkpoints")


# ===========================================================================
# Test 3: turn-end snapshot survives mid-loop exception
# ===========================================================================
if not _HAVE_GIT:
    print("[SKIP] turn-end after exception: git missing")
else:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d).resolve()
        store_root = base / "store"
        store_root.mkdir()
        store = SX.SessionStore(store_root)
        s = store.create(str(base), "fake", "exception-during-turn")

        class _BoomModels:
            def generate_content(self, **kwargs):
                raise KeyboardInterrupt("simulated Ctrl-C")
            def generate_content_stream(self, **kwargs):
                raise KeyboardInterrupt("simulated Ctrl-C")

        class _BoomClient:
            def __init__(self, **kwargs):
                self.models = _BoomModels()

        st = Settings(auto_checkpoint=True)
        prior_cwd = OC.CONFIG.cwd
        OC.CONFIG.cwd = base
        try:
            with patch("open_code.genai.Client", _BoomClient):
                raised = False
                try:
                    OC.run_loop(
                        task="boom", model="fake", api_key="x",
                        max_iterations=2, store=store, session=s,
                        verbose=False, stream=False,
                        fire_session_start=False,
                        settings=st, is_repl=False,
                    )
                except KeyboardInterrupt:
                    raised = True
                assert raised, "expected the simulated Ctrl-C to propagate"
        finally:
            OC.CONFIG.cwd = prior_cwd

        # turn-end should STILL have been written via the `finally` block
        te = store.recent_checkpoints(s, phase="turn-end")
        ts = store.recent_checkpoints(s, phase="turn-start")
        assert len(ts) == 1, "turn-start should still have been written"
        assert len(te) == 1, \
            f"turn-end should have fired in finally; got {len(te)} events"
    print("[PASS] turn-end checkpoint fires in finally after KeyboardInterrupt")


# ===========================================================================
# Test 4: auto_checkpoint=False emits no checkpoint events
# ===========================================================================
if not _HAVE_GIT:
    print("[SKIP] no-checkpoint mode: git missing")
else:
    with tempfile.TemporaryDirectory() as d:
        base = Path(d).resolve()
        store_root = base / "store"
        store_root.mkdir()
        store = SX.SessionStore(store_root)
        s = store.create(str(base), "fake", "no-ckpt run")

        class _StubResp:
            usage_metadata = None
            def __init__(self):
                from google.genai import types as _t
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

        st = Settings(auto_checkpoint=False)  # explicitly off
        prior_cwd = OC.CONFIG.cwd
        OC.CONFIG.cwd = base
        try:
            with patch("open_code.genai.Client", _StubClient):
                OC.run_loop(
                    task="quiet", model="fake", api_key="x",
                    max_iterations=2, store=store, session=s,
                    verbose=False, stream=False,
                    fire_session_start=False,
                    settings=st, is_repl=False,
                )
        finally:
            OC.CONFIG.cwd = prior_cwd

        # No checkpoint events at all
        all_ck = store.recent_checkpoints(s)
        assert len(all_ck) == 0, \
            f"auto_checkpoint=False should emit zero events; got {len(all_ck)}"
        # And shadow repo should not have been initialized either
        assert not CK.is_initialized(base), \
            "shadow repo init should not have happened when auto_checkpoint=False"
    print("[PASS] auto_checkpoint=False emits zero checkpoint events")


print("\nOK -- atomic-turn probes passed.")
