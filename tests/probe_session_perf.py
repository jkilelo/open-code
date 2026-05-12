"""Probe: brutal-review H4 fix -- message-count caching.

Before the fix, every `append_message` did a full file scan to assign
seq, making N appends cost O(N^2). After the fix, the counter is
cached in memory and incremented per-append.

Tests:
  1. Sequential appends produce monotonic seq numbers (correctness).
  2. The cache is populated lazily on first call.
  3. After many appends, the open count of file scans stays at 1
     (the initial scan), proving we don't re-scan per call.
  4. Resume case: a SessionStore that loads an existing session
     correctly counts existing messages on first lookup, then caches.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sessions as SX
from llm import Message, Part


def _new_msg(role: str, text: str) -> Message:
    return Message(role=role, parts=[Part.make_text(text)])


# ===========================================================================
# Test 1: seq numbers are monotonic and correct
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    store = SX.SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "perf test")
    for i in range(20):
        store.append_message(s, _new_msg("user", f"m{i}"))
    # Read raw JSONL and verify seq numbers
    seen_seq: list[int] = []
    with s.path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("kind") == "msg":
                seen_seq.append(ev["seq"])
    assert seen_seq == list(range(20)), f"seq not monotonic: {seen_seq}"
print("[PASS] message seq numbers monotonic (0..N-1)")


# ===========================================================================
# Test 2: cache populated lazily; subsequent appends don't re-scan
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    store = SX.SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "cache test")
    # Cache is primed to 0 at create() time so first append needs no scan
    assert store._msg_counts[s.id] == 0
    store.append_message(s, _new_msg("user", "hi"))
    assert store._msg_counts[s.id] == 1
    store.append_message(s, _new_msg("model", "ok"))
    assert store._msg_counts[s.id] == 2
print("[PASS] cache primed at create() then incremented without re-scan")


# ===========================================================================
# Test 3: heavy append batch never re-opens the file in _count_messages
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    store = SX.SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "scan-count test")
    # Wrap session.path.open to count read-mode opens (write-mode opens
    # are from _append; we only care about the scan we eliminated).
    real_open = Path.open
    read_open_count = {"n": 0}

    def _counting_open(self, mode="r", *args, **kwargs):  # noqa: ANN001
        if self == s.path and "r" in mode and "w" not in mode and "a" not in mode:
            read_open_count["n"] += 1
        return real_open(self, mode, *args, **kwargs)

    with patch.object(Path, "open", _counting_open):
        for i in range(50):
            store.append_message(s, _new_msg("user", f"m{i}"))
    assert read_open_count["n"] == 0, (
        f"expected zero read-opens of session file during 50 appends "
        f"(initial scan was avoided because seq=0 was set on first "
        f"append after create); got {read_open_count['n']}"
    )
print("[PASS] 50 appends triggered ZERO file scans of session.path")


# ===========================================================================
# Test 4: --resume case (new SessionStore reading existing session) scans
# exactly ONCE on first lookup, then caches.
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    root = Path(d).resolve()
    # Phase 1: write 5 messages with one store
    store_a = SX.SessionStore(root)
    s = store_a.create("/tmp/x", "fake", "resume-perf test")
    for i in range(5):
        store_a.append_message(s, _new_msg("user", f"m{i}"))
    sid = s.id
    spath = s.path
    # Phase 2: spin up a fresh SessionStore (simulating --resume) and
    # verify it scans exactly once.
    store_b = SX.SessionStore(root)
    # Re-create the Session handle (mimicking find_by_id)
    s2 = SX.Session(id=sid, cwd="/tmp/x", model="fake", task="...",
                     started_at="", path=spath)
    real_open = Path.open
    read_open_count = {"n": 0}

    def _counting_open(self, mode="r", *args, **kwargs):  # noqa: ANN001
        if self == spath and "r" in mode and "w" not in mode and "a" not in mode:
            read_open_count["n"] += 1
        return real_open(self, mode, *args, **kwargs)

    with patch.object(Path, "open", _counting_open):
        n1 = store_b._count_messages(s2)  # cold; should scan once
        n2 = store_b._count_messages(s2)  # warm; should not scan
        n3 = store_b._count_messages(s2)  # warm; should not scan
    assert n1 == 5
    assert n2 == 5 and n3 == 5
    assert read_open_count["n"] == 1, (
        f"expected exactly 1 cold-scan; got {read_open_count['n']}"
    )
print("[PASS] resume scans exactly once, then caches")


# ===========================================================================
# Test 5: 3rd-brutal-review probe -- post-compact seq numbers stay
# monotonic and contiguous across all msg events in the file.
# This was claimed as a bug by the reviewer; the assertion below
# verifies the claim was wrong and guards against future regressions.
# ===========================================================================
with tempfile.TemporaryDirectory() as d:
    store = SX.SessionStore(Path(d).resolve())
    s = store.create("/tmp/x", "fake", "post-compact seq test")
    # Write 5 messages, then a compact event, then 2 more messages
    for i in range(5):
        store.append_message(s, _new_msg("user", f"old {i}"))
    store.append_compact(s, summary="...", kept_recent=2, dropped=3,
                          model="fake")
    for i in range(2):
        store.append_message(s, _new_msg("user", f"new {i}"))
    # All 7 msg events on disk should have seq 0..6
    seqs: list[int] = []
    with s.path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("kind") == "msg":
                seqs.append(ev["seq"])
    assert seqs == list(range(7)), (
        f"post-compact seq must stay monotonic + contiguous; got {seqs}"
    )
print("[PASS] seq numbers stay monotonic+contiguous across a compact event")


print("\nOK -- session-perf probes passed.")
