"""Probe: 4 concurrent JSONL writers, file-per-session (no contention)."""
from __future__ import annotations
import sys, threading, tempfile, time, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sessions import SessionStore
from llm import Message, Part

store_root = Path(tempfile.mkdtemp(prefix="occonc-"))
errors = []

def worker(idx: int):
    try:
        store = SessionStore(store_root)
        session = store.create("/tmp/concurrent", "gemini-x", f"task {idx}")
        for i in range(20):
            msg = Message(role="user", parts=[Part.make_text(f"w{idx} m{i}")])
            store.append_message(session, msg)
    except Exception as e:
        errors.append((idx, type(e).__name__, str(e)))

threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
t0 = time.perf_counter()
for t in threads: t.start()
for t in threads: t.join()
elapsed = time.perf_counter() - t0
print(f"4 concurrent writers, 20 msgs each. Elapsed {elapsed:.2f}s.")
print(f"Errors: {len(errors)}")
for e in errors: print("  ", e)

# Count files + total msgs across all sessions
store = SessionStore(store_root)
sessions = store.list_for_cwd("/tmp/concurrent")
total_msgs = 0
for s in sessions:
    with s.path.open() as f:
        for line in f:
            try:
                if json.loads(line).get("kind") == "msg":
                    total_msgs += 1
            except json.JSONDecodeError:
                pass
print(f"Final: {len(sessions)} sessions, {total_msgs} messages (expected 4 sessions, 80 messages)")
