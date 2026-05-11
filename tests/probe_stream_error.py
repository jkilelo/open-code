"""Probe: what gets saved to sqlite when stream raises mid-way?"""
from __future__ import annotations
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as oc
from google.genai import types
from unittest.mock import MagicMock

# Build a fake stream that yields 2 text chunks then raises
def fake_stream():
    yield _mk_chunk("hello ")
    yield _mk_chunk("world ")
    raise ConnectionError("simulated network drop mid-stream")

def _mk_chunk(text):
    p = types.Part.from_text(text=text)
    cand = MagicMock()
    cand.content = types.Content(role="model", parts=[p])
    chunk = MagicMock()
    chunk.candidates = [cand]
    chunk.usage_metadata = None
    return chunk

fake_client = MagicMock()
fake_client.models.generate_content_stream = lambda **kw: fake_stream()

# Now invoke run_loop with this client by monkeypatching genai.Client
import open_code
orig = open_code.genai.Client
open_code.genai.Client = lambda **kw: fake_client

# Set up sqlite
dbp = Path(tempfile.mkdtemp(prefix="ocstream-")) / "sessions.db"
conn = oc.db_connect(dbp)
sid = oc.session_create(conn, "/tmp/x", "fake", "test")

try:
    code, metrics = oc.run_loop(
        task="say hi",
        model="fake",
        api_key="fake",
        max_iterations=3,
        db_conn=conn,
        session_id=sid,
        initial_history=[],
        verbose=False,
        stream=True,
    )
    print(f"\nexit_code={code} metrics_iters={metrics['iterations']}")
except Exception as e:
    print(f"loop raised: {type(e).__name__}: {e}")
finally:
    open_code.genai.Client = orig

# Inspect what got saved
rows = conn.execute(
    "SELECT seq, role, parts_json FROM messages WHERE session_id=? ORDER BY seq", (sid,)
).fetchall()
print(f"\nMessages saved to sqlite: {len(rows)}")
for seq, role, pj in rows:
    print(f"  seq={seq} role={role} parts_json={pj[:200]}")
