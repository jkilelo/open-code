"""One-off live OpenAI smoke covering the Responses-API protocol
surfaces: non-streaming, streaming, multi-iter tool calls
(tool_call_id round-trip across turns), structured output via
text.format.json_schema, embeddings, and the reasoning_effort knob.

Loads OPENAI_API_KEY from open-code/.env OR ai_agents/.env.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _smoke_setup  # noqa: F401  -- UTF-8 stdout/stderr on Windows

# Auto-load env from either location -- user keeps keys in ai_agents/.env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / "ai_agents" / ".env")
except ImportError:
    pass

api_key = os.environ.get("OPENAI_API_KEY", "").strip()
assert api_key, "OPENAI_API_KEY missing"

from llm import make_llm_client, Message, Part, ToolDecl

llm = make_llm_client(provider="openai", api_key=api_key)
MODEL = "gpt-5-mini"   # cheap reasoning-capable; verified live 2026-05-12


# ===========================================================================
# Test 1: non-streaming text
# ===========================================================================
res = llm.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Say exactly: 'hello from openai adapter' and nothing else."
    )])],
    # gpt-5-mini eats reasoning tokens by default -- minimal effort
    # keeps the test deterministic at a small budget. See README gotcha.
    thinking_effort="minimal",
    max_output_tokens=256,
)
out = res.message.text()
assert "hello from openai adapter" in out.lower(), f"got: {out!r}"
print(f"[PASS] non-streaming: {out!r}  (in={res.usage.input_tokens} out={res.usage.output_tokens})")


# ===========================================================================
# Test 2: streaming text
# ===========================================================================
chunks_seen = 0
text_buf: list[str] = []
final = None
for chunk in llm.ask_stream(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Count from 1 to 5, one number per line, nothing else."
    )])],
    thinking_effort="minimal",
    max_output_tokens=256,
):
    chunks_seen += 1
    if chunk.text_delta:
        text_buf.append(chunk.text_delta)
    if chunk.is_final:
        final = chunk
assert final is not None, "stream must end with is_final"
text = "".join(text_buf)
assert "1" in text and "5" in text, f"got: {text!r}"
print(f"[PASS] streaming: {chunks_seen} chunks, final usage in={final.usage.input_tokens if final.usage else 0}")


# ===========================================================================
# Test 3: multi-iter tool chain (call_id round-trip across turns)
# Simulates one full step of open-code's run_loop.
# ===========================================================================
get_time_tool = ToolDecl(
    name="get_time",
    description="Returns the current time as an ISO 8601 string.",
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone, e.g. 'UTC' or 'America/New_York'.",
            },
        },
        "required": ["timezone"],
        "additionalProperties": False,
    },
    strict=True,
)

history: list[Message] = [
    Message(role="user", parts=[Part.make_text(
        "What time is it in UTC right now? Use the get_time tool, "
        "then in one short sentence report the result."
    )])
]

res1 = llm.ask(
    model=MODEL,
    messages=history,
    tools=[get_time_tool],
    max_output_tokens=512,
)
tool_calls = res1.message.tool_calls()
assert tool_calls, f"iter 1 expected tool_call, got text: {res1.message.text()!r}"
tc = tool_calls[0]
assert tc.tool_name == "get_time"
assert tc.tool_call_id, "call_id should round-trip into Part.tool_call_id"
print(f"[PASS] iter 1 tool_call: {tc.tool_name}({tc.tool_args}) id={tc.tool_call_id[:12]}...")

history.append(res1.message)
history.append(Message(role="tool", parts=[
    Part.make_tool_result(
        tc.tool_name,
        {"ok": True, "iso": "2026-05-12T15:00:00Z"},
        tool_call_id=tc.tool_call_id,
    ),
]))

res2 = llm.ask(
    model=MODEL,
    messages=history,
    tools=[get_time_tool],
    max_output_tokens=256,
)
final_text = res2.message.text()
assert final_text, f"iter 2 expected final text; got {len(res2.message.parts)} non-text parts"
assert "2026" in final_text or "15:00" in final_text or "3:00 PM" in final_text or "UTC" in final_text, f"got: {final_text!r}"
print(f"[PASS] iter 2 final: {final_text!r}")
print(f"       (in={res2.usage.input_tokens} out={res2.usage.output_tokens} "
      f"reasoning={res2.usage.reasoning_tokens})")


# ===========================================================================
# Test 4: structured output via text.format.json_schema
# ===========================================================================
color_schema = {
    "type": "object",
    "properties": {
        "color": {"type": "string"},
        "is_warm": {"type": "boolean"},
    },
    "required": ["color", "is_warm"],
    "additionalProperties": False,
}
res = llm.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Tell me about the color 'crimson' as JSON."
    )])],
    response_schema=color_schema,
    thinking_effort="minimal",     # avoid reasoning eating the token budget
    max_output_tokens=1024,
)
text = res.message.text()
if not text:
    # Diagnostic dump if the adapter missed something
    print(f"  DEBUG: stop_reason={res.stop_reason!r}")
    print(f"  DEBUG: parts={[(p.kind, p.text[:50]) for p in res.message.parts]}")
    print(f"  DEBUG: usage={res.usage}")
    raw_output = getattr(res.raw, "output", None) or []
    for item in raw_output:
        print(f"  DEBUG raw item: type={getattr(item, 'type', '?')!r}")
    raise AssertionError("structured-output response.text() was empty")
parsed = json.loads(text)
assert "color" in parsed and "is_warm" in parsed, f"got: {parsed!r}"
print(f"[PASS] structured output: {parsed}")


# ===========================================================================
# Test 5: embeddings via text-embedding-3-small
# ===========================================================================
vecs = llm.embed(
    model="text-embedding-3-small",
    texts=["the quick brown fox", "lorem ipsum dolor sit amet"],
)
assert len(vecs) == 2
assert len(vecs[0]) == 1536, f"unexpected dim: {len(vecs[0])}"  # default for 3-small
print(f"[PASS] embed -> 2 vectors x {len(vecs[0])} dims (first 3: {vecs[0][:3]})")

# With dimensions truncation
vecs_short = llm.embed(
    model="text-embedding-3-small",
    texts=["hi"],
    output_dimensionality=256,
)
assert len(vecs_short[0]) == 256
print(f"[PASS] embed with dims=256 -> 1 vec x 256")


# ===========================================================================
# Test 6: reasoning_effort knob (low effort to keep tokens cheap)
# ===========================================================================
res = llm.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "If I have 7 apples and give away 2/3, how many do I have left? "
        "Show the calculation in one line."
    )])],
    thinking_effort="low",
    max_output_tokens=1024,
)
text = res.message.text()
print(f"[PASS] reasoning_effort=low: {text!r}")
print(f"       usage: in={res.usage.input_tokens} out={res.usage.output_tokens} "
      f"reasoning={res.usage.reasoning_tokens} cached={res.usage.cached_input_tokens}")


print("\nOK -- live OpenAI protocol surfaces verified.")
