"""Probe: a streaming chunk with BOTH text AND a tool_call -- both end up in history?

After the LLM decoupling, this probe constructs a fake LLMClient that
yields a StreamChunk carrying text_delta + a tool_call Part in one event.
The neutral _stream_iter_response should split them into separate Parts
in the assembled message.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as oc
import sessions as sx
from llm import Message, Part, StreamChunk


class FakeInterleavedClient:
    provider = "fake"

    def ask(self, **kw):
        raise NotImplementedError

    def ask_stream(self, **kw):
        # One chunk carrying BOTH a text delta AND a tool_call Part.
        # This is the interleaved shape we want to verify round-trips.
        yield StreamChunk(
            text_delta="I'm going to list the dir first.\n",
            tool_calls=[Part.make_tool_call("list_dir", {"path": "."})],
            usage=None,
        )

    def embed(self, **kw):
        return []


parts, usage = oc._stream_iter_response(
    FakeInterleavedClient(), model="fake",
    history=[Message(role="user", parts=[Part.make_text("list")])],
    system_instruction="",
    tools=None,
    thinking_budget=None,
    verbose=False,
)
print(f"parts collected: {len(parts)}")
for p in parts:
    if p.is_tool_call():
        print(f"  tool_call: {p.tool_name}({dict(p.tool_args)})")
    elif p.is_text():
        print(f"  text: {p.text!r}")
    else:
        print(f"  other: kind={p.kind}")

# Round-trip through content_to_dict / dict_to_content (storage layer).
c = Message(role="model", parts=parts)
d = sx.content_to_dict(c)
print(f"serialized parts: {len(d['parts'])}")
for p in d["parts"]:
    print(f"  {p}")
c2 = sx.dict_to_content(d)
print(f"deserialized parts: {len(c2.parts)}")
