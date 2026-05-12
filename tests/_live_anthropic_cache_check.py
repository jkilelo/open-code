"""Wire-verify Anthropic prompt-caching auto-injection (v0.31.0).

Builds a system prompt large enough to clear Haiku 4.5's 4096-token
minimum (~5000 tokens worth of stable instructions), then makes two
ask() calls with the same prefix:

  Call 1: cache miss -> usage.cache_write_tokens > 0,
                        usage.cached_input_tokens == 0
  Call 2: cache hit  -> usage.cached_input_tokens > 0

Loads ANTHROPIC_API_KEY from open-code/.env OR ai_agents/.env.
"""
from __future__ import annotations
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

api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
assert api_key, "ANTHROPIC_API_KEY missing"

from llm import make_llm_client, Message, Part

# Build a 5000+ token system prompt by concatenating a long policy
# block. Each line is ~14 tokens; we need ~4096 for Haiku 4.5 to
# actually cache. 400 copies of this paragraph = ~5600 tokens of
# stable prefix.
POLICY_LINE = (
    "You are a careful, precise coding assistant. You never write "
    "code without first reading the relevant existing code. You "
    "explain reasoning briefly before tool calls. You never invent "
    "filenames or APIs you have not seen. "
)
LONG_SYSTEM = (POLICY_LINE * 400).strip()

# Make a client with cache enabled.
llm_cached = make_llm_client(
    provider="anthropic",
    api_key=api_key,
    extra={"cache": {"enabled": True}},
)

MODEL = "claude-haiku-4-5"

# Call 1: expect cache_creation_input_tokens > 0 (writing the cache).
res1 = llm_cached.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Say the word 'one' and nothing else."
    )])],
    system_instruction=LONG_SYSTEM,
    max_output_tokens=64,
)
print(f"[call 1] in={res1.usage.input_tokens} out={res1.usage.output_tokens} "
      f"cache_write={res1.usage.cache_write_tokens} "
      f"cache_read={res1.usage.cached_input_tokens}")
assert "one" in res1.message.text().lower(), f"got: {res1.message.text()!r}"

# Call 2: same prefix, different user message. Expect cached_input_tokens > 0.
res2 = llm_cached.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Say the word 'two' and nothing else."
    )])],
    system_instruction=LONG_SYSTEM,
    max_output_tokens=64,
)
print(f"[call 2] in={res2.usage.input_tokens} out={res2.usage.output_tokens} "
      f"cache_write={res2.usage.cache_write_tokens} "
      f"cache_read={res2.usage.cached_input_tokens}")
assert "two" in res2.message.text().lower(), f"got: {res2.message.text()!r}"

# Hardest assertion: call 2 hit the cache.
assert res2.usage.cached_input_tokens > 0, (
    f"expected cache hit on call 2; usage was "
    f"in={res2.usage.input_tokens} cache_read={res2.usage.cached_input_tokens} "
    f"cache_write={res2.usage.cache_write_tokens}. The system prompt may "
    f"be below the 4096-token minimum for {MODEL}, or cache_control "
    f"markers were placed incorrectly."
)
print(f"[PASS] cache hit confirmed: "
      f"{res2.usage.cached_input_tokens} tokens served from cache "
      f"(call 2 paid only for {res2.usage.input_tokens} new tokens + "
      f"{res2.usage.output_tokens} output)")

# Sanity check: call 1 should have written to cache.
if res1.usage.cache_write_tokens == 0:
    print(f"[WARN] call 1 cache_write was 0 -- the system prompt may "
          f"have been pre-cached by an earlier run, or the model's "
          f"min-cache threshold isn't being hit. Cache READ on call 2 "
          f"is the real signal and it passed.")
else:
    print(f"[PASS] call 1 wrote {res1.usage.cache_write_tokens} tokens to cache")


# ===========================================================================
# Negative test: disable cache, verify markers are absent + no cache hits
# ===========================================================================
llm_uncached = make_llm_client(provider="anthropic", api_key=api_key)
res3 = llm_uncached.ask(
    model=MODEL,
    messages=[Message(role="user", parts=[Part.make_text(
        "Say the word 'three' and nothing else."
    )])],
    system_instruction=LONG_SYSTEM,
    max_output_tokens=64,
)
print(f"[call 3 uncached] in={res3.usage.input_tokens} "
      f"cache_write={res3.usage.cache_write_tokens} "
      f"cache_read={res3.usage.cached_input_tokens}")
# Without cache_control markers, both should be 0
assert res3.usage.cache_write_tokens == 0, (
    f"unexpected cache_write on uncached client: {res3.usage.cache_write_tokens}"
)
assert res3.usage.cached_input_tokens == 0, (
    f"unexpected cache_read on uncached client: {res3.usage.cached_input_tokens}"
)
print("[PASS] cache disabled -> no cache write/read")


print("\nOK -- Anthropic prompt-caching auto-injection verified.")
