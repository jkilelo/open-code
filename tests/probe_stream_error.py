"""Probe: what gets saved to JSONL when stream raises mid-way?

With v0.3's append-only JSONL + per-event flush, partial output before
the error should be on disk. This was a v0.2 carried gap.
"""
from __future__ import annotations
import sys, tempfile, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as oc
from sessions import SessionStore
from google.genai import types
from unittest.mock import MagicMock

def _mk_chunk(text):
    p = types.Part.from_text(text=text)
    cand = MagicMock()
    cand.content = types.Content(role="model", parts=[p])
    chunk = MagicMock()
    chunk.candidates = [cand]
    chunk.usage_metadata = None
    return chunk

def fake_stream():
    yield _mk_chunk("hello ")
    yield _mk_chunk("world ")
    raise ConnectionError("simulated network drop mid-stream")

fake_client = MagicMock()
fake_client.models.generate_content_stream = lambda **kw: fake_stream()

orig = oc.genai.Client
oc.genai.Client = lambda **kw: fake_client

store_root = Path(tempfile.mkdtemp(prefix="ocstream-"))
store = SessionStore(store_root)
session = store.create("/tmp/x", "fake", "test")

try:
    code, metrics = oc.run_loop(
        task="say hi",
        model="fake",
        api_key="fake",
        max_iterations=3,
        store=store,
        session=session,
        initial_history=[],
        verbose=False,
        stream=True,
    )
    print(f"\nexit_code={code} metrics_iters={metrics['iterations']}")
except Exception as e:
    print(f"loop raised: {type(e).__name__}: {e}")
finally:
    oc.genai.Client = orig

# Inspect what's actually on disk
print(f"\nEvents written to JSONL ({session.path.name}):")
with session.path.open() as f:
    for line in f:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = ev.get("kind")
        if kind == "session":
            print(f"  [session] task={ev.get('task')!r}")
        elif kind == "msg":
            parts = ev.get("parts", [])
            preview = parts[0].get("text", "") if parts else ""
            print(f"  [msg seq={ev.get('seq')} role={ev.get('role')}] {preview!r}")
        elif kind == "end":
            print(f"  [end] exit_code={ev.get('exit_code')} iters={ev.get('iters')}")
        else:
            print(f"  [{kind}] {ev}")
