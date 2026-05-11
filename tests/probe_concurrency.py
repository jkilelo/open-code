"""Probe: two concurrent SQLite writers in the same CWD."""
from __future__ import annotations
import sys, threading, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from open_code import db_connect, session_create, message_save
from google.genai import types

dbp = Path(tempfile.mkdtemp(prefix="occonc-")) / "sessions.db"
errors = []

def worker(idx: int):
    try:
        c = db_connect(dbp)
        sid = session_create(c, "/tmp/concurrent", "gemini-x", f"task {idx}")
        for i in range(20):
            msg = types.Content(role="user", parts=[types.Part.from_text(text=f"w{idx} m{i}")])
            message_save(c, sid, msg)
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
c = db_connect(dbp)
n = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
s = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
print(f"Final: {s} sessions, {n} messages (expected 4 sessions, 80 messages)")
