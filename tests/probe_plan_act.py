"""Probe: append_plan / latest_plan in sessions.py."""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sessions import SessionStore


# ---- Test 1: no plan event yet -> latest_plan returns None ----
with tempfile.TemporaryDirectory() as d:
    store = SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake-model", "test session")
    assert store.latest_plan(s) is None
print("[PASS] empty session -> latest_plan() is None")


# ---- Test 2: append_plan + latest_plan round-trip ----
with tempfile.TemporaryDirectory() as d:
    store = SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake-model", "test session")
    store.append_plan(s, plan_id="abc12345",
                      content="Step 1: do X\nStep 2: do Y",
                      model="gemini-x")
    plan = store.latest_plan(s)
    assert plan is not None
    assert plan["plan_id"] == "abc12345"
    assert "Step 1" in plan["content"]
    assert plan["model"] == "gemini-x"
print("[PASS] append_plan + latest_plan round-trip")


# ---- Test 3: latest_plan returns the LAST one ----
with tempfile.TemporaryDirectory() as d:
    store = SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "t")
    store.append_plan(s, plan_id="aaaa1111", content="old", model="x")
    store.append_plan(s, plan_id="bbbb2222", content="new", model="x")
    plan = store.latest_plan(s)
    assert plan["plan_id"] == "bbbb2222", f"got {plan['plan_id']!r}"
print("[PASS] latest_plan returns most recent")


# ---- Test 4: aggregate_metrics doesn't count plans as iters ----
with tempfile.TemporaryDirectory() as d:
    store = SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "t")
    store.append_plan(s, plan_id="p1", content="plan body", model="x")
    agg = store.aggregate_metrics(s)
    # plan events are not iter/fallback/refusal -- should be zero
    assert agg["n_iters"] == 0, f"plan should not count as iter; got {agg}"
print("[PASS] plan events don't pollute aggregate_metrics counters")


# ---- Test 5: plan content survives newlines + code blocks ----
with tempfile.TemporaryDirectory() as d:
    store = SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "t")
    body = "Step 1\n\n```python\nprint('hi')\n```\n\nStep 2"
    store.append_plan(s, plan_id="p1", content=body, model="x")
    plan = store.latest_plan(s)
    assert plan["content"] == body
    assert "```python" in plan["content"]
print("[PASS] plan content preserves multi-line + code blocks")


print("\nOK -- 5 plan/act probes passed.")
