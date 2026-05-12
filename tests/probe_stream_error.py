"""Probe: what gets saved to JSONL when stream raises mid-way?

With v0.3's append-only JSONL + per-event flush, partial output before
the error should be on disk. This was a v0.2 carried gap.

Provider-agnostic: injects a fake LLMClient instead of mocking
google.genai. The neutral protocol means we only need to fake
ask_stream() yielding StreamChunks; the loop is unchanged.
"""
from __future__ import annotations
import sys, tempfile, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as oc
from sessions import SessionStore
from llm import Part, StreamChunk, Usage


class FakeStreamErrorClient:
    """LLMClient that streams two chunks then raises. Used to probe
    the partial-write-then-error path in the agent loop."""
    provider = "fake"

    def ask(self, **kw):  # not used in this probe
        raise NotImplementedError

    def ask_stream(self, **kw):
        yield StreamChunk(text_delta="hello ", tool_calls=[])
        yield StreamChunk(text_delta="world ", tool_calls=[])
        raise ConnectionError("simulated network drop mid-stream")

    def embed(self, **kw):
        return []


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
        llm=FakeStreamErrorClient(),
    )
    print(f"\nexit_code={code} metrics_iters={metrics['iterations']}")
except Exception as e:
    print(f"loop raised: {type(e).__name__}: {e}")

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
