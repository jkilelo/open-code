"""Probe: a chunk containing BOTH text AND a function_call — do both end up in history?"""
from __future__ import annotations
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import open_code as oc
import sessions as sx
from google.genai import types
from unittest.mock import MagicMock

def fake_stream():
    # One chunk, two parts: a text reply AND a function call
    text_part = types.Part.from_text(text="I'm going to list the dir first.\n")
    fc_part = types.Part(function_call=types.FunctionCall(name="list_dir", args={"path": "."}))
    cand = MagicMock()
    cand.content = types.Content(role="model", parts=[text_part, fc_part])
    chunk = MagicMock()
    chunk.candidates = [cand]
    chunk.usage_metadata = None
    yield chunk

fake_client = MagicMock()
fake_client.models.generate_content_stream = lambda **kw: fake_stream()

parts, fcs, usage = oc._stream_iter_response(
    fake_client, model="fake",
    history=[types.Content(role="user", parts=[types.Part.from_text(text="list")])],
    config=types.GenerateContentConfig(system_instruction=""),
    verbose=False,
)
print(f"parts collected: {len(parts)}")
for p in parts:
    txt = getattr(p, "text", None)
    fc = getattr(p, "function_call", None)
    if fc and getattr(fc, "name", None):
        print(f"  function_call: {fc.name}({dict(fc.args) if fc.args else {}})")
    elif txt:
        print(f"  text: {txt!r}")
    else:
        print(f"  other: {p}")
print(f"function_calls extracted: {len(fcs)}")
# Now confirm both round-trip through content_to_dict / dict_to_content
c = types.Content(role="model", parts=parts)
d = sx.content_to_dict(c)
print(f"serialized parts: {len(d['parts'])}")
for p in d["parts"]:
    print(f"  {p}")
c2 = sx.dict_to_content(d)
print(f"deserialized parts: {len(c2.parts or [])}")
