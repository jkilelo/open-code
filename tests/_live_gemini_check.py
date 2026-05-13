"""One-off live Gemini smoke covering protocol surfaces the CLI
doesn't exercise: response_schema (structured output) and embeddings."""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _smoke_setup  # noqa: F401  -- UTF-8 stdout/stderr on Windows

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

api_key = os.environ.get("GEMINI_API_KEY", "").strip()
assert api_key, "GEMINI_API_KEY missing"

from llm import make_llm_client, Message, Part

llm = make_llm_client(provider="gemini", api_key=api_key)

# ---- 1. Structured output via response_schema ----
schema = {
    "type": "object",
    "properties": {
        "color": {"type": "string"},
        "is_warm": {"type": "boolean"},
    },
    "required": ["color", "is_warm"],
}
res = llm.ask(
    model="gemini-3.1-flash-lite-preview",
    messages=[Message(role="user", parts=[Part.make_text(
        "Tell me about the color 'crimson' as JSON."
    )])],
    response_schema=schema,
)
print("[structured]", res.message.text())
import json
parsed = json.loads(res.message.text())
assert "color" in parsed and "is_warm" in parsed
print("[PASS] response_schema -> valid JSON matching schema")

# ---- 2. Embedding ----
vecs = llm.embed(
    model="gemini-embedding-001",
    texts=["the quick brown fox", "lorem ipsum dolor sit amet"],
    task_type="SEMANTIC_SIMILARITY",
    output_dimensionality=768,
)
assert len(vecs) == 2
assert len(vecs[0]) == 768 and len(vecs[1]) == 768
print(f"[PASS] embed -> 2 vectors x 768 dims (first 3: {vecs[0][:3]})")

# ---- 3. Streaming returns chunks then final ----
stream = llm.ask_stream(
    model="gemini-3.1-flash-lite-preview",
    messages=[Message(role="user", parts=[Part.make_text("count to 3, one per line")])],
)
text_buf = []
n_chunks = 0
final = None
for chunk in stream:
    n_chunks += 1
    if chunk.text_delta:
        text_buf.append(chunk.text_delta)
    if chunk.is_final:
        final = chunk
assert final is not None, "stream must end with a final chunk"
assert "".join(text_buf).strip(), "stream must produce text"
print(f"[PASS] ask_stream -> {n_chunks} chunks, final usage in={final.usage.input_tokens if final.usage else 0}")

print("\nOK -- live Gemini protocol surfaces verified.")
