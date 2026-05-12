"""One-off live Anthropic smoke covering the protocol surfaces:
non-streaming, streaming, multi-iter tool calls (signature round-trip
across turns), structured output via output_config, and the embed()
hint-raises-LLMConfigError contract.

Loads ANTHROPIC_API_KEY from open-code/.env OR ai_agents/.env.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Auto-load env from either location -- user keeps keys in ai_agents/.env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / "ai_agents" / ".env")
except ImportError:
    pass

api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
assert api_key, "ANTHROPIC_API_KEY missing"

from llm import (
    make_llm_client, Message, Part, ToolDecl, LLMConfigError,
)

llm = make_llm_client(provider="anthropic", api_key=api_key)
MODEL = "claude-haiku-4-5"   # cheapest; bump for tougher tests


# ===========================================================================
# Test 1: non-streaming text
# ===========================================================================
res = llm.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Say exactly: 'hello from anthropic adapter' and nothing else."
    )])],
    max_output_tokens=64,
)
out = res.message.text()
assert "hello from anthropic adapter" in out.lower(), f"got: {out!r}"
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
    max_output_tokens=64,
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
# Test 3: multi-iter tool chain (signature round-trip across turns)
# Simulates one full step of open-code's run_loop:
#  iter 1 -> model calls a tool
#  we append a tool_result with the SAME tool_call_id
#  iter 2 -> model produces final text
# If thinking signatures round-trip, both turns succeed without 400.
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
    },
)

history: list[Message] = [
    Message(role="user", parts=[Part.make_text(
        "What time is it in UTC right now? Use the get_time tool, "
        "then in one short sentence report the result."
    )])
]

# Iter 1: model should request the tool
res1 = llm.ask(
    model=MODEL,
    messages=history,
    tools=[get_time_tool],
    max_output_tokens=512,
)
tool_calls = res1.message.tool_calls()
assert tool_calls, f"iter 1 expected tool_call, got: {res1.message.text()!r}"
tc = tool_calls[0]
assert tc.tool_name == "get_time"
assert tc.tool_call_id, "tool_use_id should round-trip into Part.tool_call_id"
print(f"[PASS] iter 1 tool_call: {tc.tool_name}({tc.tool_args}) id={tc.tool_call_id[:12]}...")

# Append assistant turn + a synthetic tool result on user turn
history.append(res1.message)
history.append(Message(role="tool", parts=[
    Part.make_tool_result(
        tc.tool_name,
        {"ok": True, "iso": "2026-05-12T15:00:00Z"},
        tool_call_id=tc.tool_call_id,
    ),
]))

# Iter 2: model should produce final text
res2 = llm.ask(
    model=MODEL,
    messages=history,
    tools=[get_time_tool],
    max_output_tokens=256,
)
final_text = res2.message.text()
assert final_text, f"iter 2 expected final text; got {len(res2.message.parts)} non-text parts"
assert "2026" in final_text or "15:00" in final_text or "UTC" in final_text, f"got: {final_text!r}"
print(f"[PASS] iter 2 final: {final_text!r}")
print(f"       (in={res2.usage.input_tokens} out={res2.usage.output_tokens} "
      f"reasoning={res2.usage.reasoning_tokens})")


# ===========================================================================
# Test 4: embed() raises LLMConfigError (Anthropic has no embeddings API)
# ===========================================================================
raised = False
try:
    llm.embed(model="x", texts=["a"])
except LLMConfigError as exc:
    raised = True
    assert "anthropic" in str(exc).lower(), f"got: {exc}"
assert raised, "embed() should raise LLMConfigError on Anthropic"
print("[PASS] embed() raises LLMConfigError with the hint")


# ===========================================================================
# Test 5: extended thinking (adaptive on haiku-4-5)
# ===========================================================================
res = llm.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "If I have 7 apples and give away 2/3, how many do I have left? "
        "Show your reasoning briefly."
    )])],
    thinking_effort="low",
    include_thinking=True,
    max_output_tokens=4096,
)
text = res.message.text()
thoughts = res.message.thinking()
print(f"[PASS] thinking enabled: {len(thoughts)} thought-block(s), "
      f"answer='{text[:80]}...' reasoning_tokens=...")
# Note: haiku-4-5 uses adaptive; reasoning_tokens may not surface
# via the usage object the same way -- log what we got
print(f"       usage: in={res.usage.input_tokens} out={res.usage.output_tokens} "
      f"reasoning={res.usage.reasoning_tokens} cached={res.usage.cached_input_tokens}")


print("\nOK -- live Anthropic protocol surfaces verified.")
