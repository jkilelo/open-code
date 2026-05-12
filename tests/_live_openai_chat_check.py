"""One-off live OpenAI Chat Completions smoke (the legacy / OSS-compat
adapter; `provider="openai_chat"`). Mirrors _live_openai_check.py but
hits chat.completions.create() instead of responses.create() so we
exercise the nested-function-wrapper tool shape and the per-result
role="tool" message path.

Useful for: validating OSS-compat backends (Groq, vLLM, Anthropic's
OpenAI shim, Azure) that only speak Chat Completions. Point at them
via `extra={"base_url": "..."}`.

Loads OPENAI_API_KEY from open-code/.env OR ai_agents/.env.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / "ai_agents" / ".env")
except ImportError:
    pass

api_key = os.environ.get("OPENAI_API_KEY", "").strip()
assert api_key, "OPENAI_API_KEY missing"

from llm import make_llm_client, Message, Part, ToolDecl

llm = make_llm_client(provider="openai_chat", api_key=api_key)
MODEL = "gpt-5-mini"   # works through chat.completions too


# ===========================================================================
# Test 1: non-streaming text
# ===========================================================================
res = llm.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Say exactly: 'hello from openai_chat adapter' and nothing else."
    )])],
    # gpt-5-mini reasoning eats budget by default -- minimal keeps it small.
    thinking_effort="minimal",
    max_output_tokens=256,
)
out = res.message.text()
assert "hello from openai_chat adapter" in out.lower(), f"got: {out!r}"
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
# Test 3: multi-iter tool chain (call_id round-trip via role="tool")
# ===========================================================================
get_time_tool = ToolDecl(
    name="get_time",
    description="Returns the current time as an ISO 8601 string.",
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone, e.g. 'UTC'.",
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
# Use the neutral ROLE_TOOL convention -- the adapter maps to
# {"role":"tool", "tool_call_id":..., "content":...} messages.
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
assert "2026" in final_text or "15:00" in final_text or "3:00" in final_text or "UTC" in final_text, f"got: {final_text!r}"
print(f"[PASS] iter 2 final: {final_text!r}")
print(f"       (in={res2.usage.input_tokens} out={res2.usage.output_tokens} "
      f"reasoning={res2.usage.reasoning_tokens})")


# ===========================================================================
# Test 4: structured output via response_format.json_schema (strict mode)
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
    thinking_effort="minimal",
    max_output_tokens=1024,
)
parsed = json.loads(res.message.text())
assert "color" in parsed and "is_warm" in parsed, f"got: {parsed!r}"
print(f"[PASS] structured output: {parsed}")


# ===========================================================================
# Test 5: embeddings (same client.embeddings endpoint as Responses adapter)
# ===========================================================================
vecs = llm.embed(
    model="text-embedding-3-small",
    texts=["the quick brown fox", "lorem ipsum dolor sit amet"],
)
assert len(vecs) == 2
assert len(vecs[0]) == 1536, f"unexpected dim: {len(vecs[0])}"
print(f"[PASS] embed -> 2 vectors x {len(vecs[0])} dims")


# ===========================================================================
# Test 6: reasoning_effort knob (Chat passes via top-level reasoning_effort)
# ===========================================================================
res = llm.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "If I have 7 apples and give away 2/3, how many do I have left? "
        "One line."
    )])],
    thinking_effort="low",
    max_output_tokens=1024,
)
print(f"[PASS] reasoning_effort=low: {res.message.text()!r}")
print(f"       usage: in={res.usage.input_tokens} out={res.usage.output_tokens} "
      f"reasoning={res.usage.reasoning_tokens} cached={res.usage.cached_input_tokens}")


print("\nOK -- live OpenAI Chat Completions surfaces verified.")
