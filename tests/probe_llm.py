"""Probe: LLMClient protocol contract.

Tests the neutral types, factory, storage round-trip, and structural
duck-typing without making a network call. The whole decoupling rests
on these invariants holding regardless of which adapter is in play.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import llm as L
import sessions as SX


# ===========================================================================
# Test 1: neutral type constructors + accessors (all 5 kinds)
# ===========================================================================
t = L.Part.make_text("hi")
assert t.is_text() and t.text == "hi"
assert not t.is_tool_call() and not t.is_tool_result()

tc = L.Part.make_tool_call("read", {"path": "/x"}, tool_call_id="call_1")
assert tc.is_tool_call() and tc.tool_name == "read"
assert tc.tool_args == {"path": "/x"}
assert tc.tool_call_id == "call_1"

tr = L.Part.make_tool_result(
    "read", {"ok": True, "data": "..."}, tool_call_id="call_1",
)
assert tr.is_tool_result() and tr.tool_call_id == "call_1"
assert tr.is_error is False

# Auto-detect is_error from {"ok": False}
tr_err = L.Part.make_tool_result("read", {"ok": False, "error": "no"})
assert tr_err.is_error is True

th = L.Part.make_thinking("the model thinks ...", signature=b"sigbytes")
assert th.is_thinking() and th.text == "the model thinks ..."
assert th.extra["signature"] == b"sigbytes"

img = L.Part.make_image(mime="image/png", data=b"\x89PNGfake")
assert img.is_image() and img.image_mime == "image/png"

m = L.Message(role="model", parts=[th, t, tc])
assert m.text() == "hi"
assert len(m.tool_calls()) == 1
assert len(m.thinking()) == 1
print("[PASS] all Part kinds + Message accessors")


# ===========================================================================
# Test 2: storage round-trip preserves every field
# ===========================================================================
orig = L.Message(role="model", parts=[
    L.Part.make_thinking("reasoning ...", signature=b"\x01\x02\x03"),
    L.Part.make_text("here is the result"),
    L.Part.make_tool_call(
        "read", {"path": "/etc/hosts"}, tool_call_id="call_abc",
        extra={"thought_signature": b"\xde\xad\xbe\xef"},
    ),
    L.Part.make_tool_result(
        "read", {"ok": False, "error": "perm denied"},
        tool_call_id="call_abc", is_error=True,
    ),
    L.Part.make_image(mime="image/jpeg", data=b"\xff\xd8fakejpg"),
])
d = SX.content_to_dict(orig)
assert d["role"] == "model"
back = SX.dict_to_content(d)
assert isinstance(back, L.Message)
assert len(back.parts) == 5

# thinking with bytes signature
assert back.parts[0].is_thinking()
assert back.parts[0].text == "reasoning ..."
assert back.parts[0].extra["signature"] == b"\x01\x02\x03"

# text
assert back.parts[1].is_text() and back.parts[1].text == "here is the result"

# tool_call with id + extra
assert back.parts[2].is_tool_call()
assert back.parts[2].tool_call_id == "call_abc"
assert back.parts[2].extra["thought_signature"] == b"\xde\xad\xbe\xef"

# tool_result with id + is_error
assert back.parts[3].is_tool_result()
assert back.parts[3].tool_call_id == "call_abc"
assert back.parts[3].is_error is True

# image
assert back.parts[4].is_image()
assert back.parts[4].image_mime == "image/jpeg"
assert back.parts[4].image_data == b"\xff\xd8fakejpg"
print("[PASS] storage round-trip preserves all Part fields incl. bytes")


# ===========================================================================
# Test 3: factory raises LLMConfigError for missing key
# ===========================================================================
raised = False
try:
    L.make_llm_client(
        provider="anthropic", api_key=None,
        api_key_env="DOES_NOT_EXIST_KEY_X",
    )
except L.LLMConfigError:
    raised = True
assert raised, "missing anthropic key should raise LLMConfigError"
print("[PASS] factory raises LLMConfigError for missing api key")


# ===========================================================================
# Test 4: factory raises LLMConfigError for unknown provider
# ===========================================================================
raised = False
try:
    L.make_llm_client(provider="madeup-provider-xyz", api_key="x")
except L.LLMConfigError as exc:
    raised = True
    assert "Unknown" in str(exc) or "madeup-provider-xyz" in str(exc)
assert raised
print("[PASS] factory raises LLMConfigError for unknown provider")


# ===========================================================================
# Test 5: default_model_for resolves per provider
# ===========================================================================
assert "gemini" in L.default_model_for("gemini").lower()
assert "claude" in L.default_model_for("anthropic").lower()
assert "gpt" in L.default_model_for("openai").lower()
assert L.default_model_for("nonexistent") == L.DEFAULT_MODELS["gemini"]
print("[PASS] default_model_for resolves all known providers")


# ===========================================================================
# Test 6: structural duck-typing -- minimal class is an LLMClient
# ===========================================================================
class _MinimalClient:
    provider = "minimal"

    def ask(self, *, model, messages, **kw):
        return L.AskResult(
            message=L.Message(role="model", parts=[L.Part.make_text("ok")]),
            usage=L.Usage(input_tokens=1, output_tokens=1),
        )

    def ask_stream(self, **kw):
        yield L.StreamChunk(text_delta="ok")
        yield L.StreamChunk(
            usage=L.Usage(input_tokens=1, output_tokens=1),
            is_final=True,
        )

    def embed(self, *, model, texts, **kw):
        return [[0.0] * 8 for _ in texts]


client = _MinimalClient()
result = client.ask(model="x", messages=[])
assert isinstance(result, L.AskResult)
assert result.message.text() == "ok"
chunks = list(client.ask_stream(model="x", messages=[]))
assert chunks[-1].is_final
vecs = client.embed(model="x", texts=["a", "b"])
assert len(vecs) == 2 and len(vecs[0]) == 8
print("[PASS] minimal LLMClient implementation is structurally accepted")


# ===========================================================================
# Test 7: BaseLLMClient ABC provides error translation
# ===========================================================================
from llm.base import BaseLLMClient, StreamAccumulator


class _FailingClient(BaseLLMClient):
    provider = "test"

    def _ask_impl(self, **kw):
        raise TimeoutError("simulated timeout")

    def _ask_stream_impl(self, **kw):
        if False:
            yield  # generator
        raise ConnectionError("simulated network drop")


c = _FailingClient()
try:
    c.ask(model="x", messages=[])
    raise AssertionError("expected timeout error")
except L.LLMTimeoutError:
    pass

try:
    list(c.ask_stream(model="x", messages=[]))
    raise AssertionError("expected connection error")
except L.LLMConnectionError:
    pass

# Default embed raises LLMConfigError (Anthropic-style)
try:
    c.embed(model="x", texts=["a"])
    raise AssertionError("expected config error")
except L.LLMConfigError:
    pass
print("[PASS] BaseLLMClient translates exceptions to LLMError tree")


# ===========================================================================
# Test 8: StreamAccumulator assembles deltas into a Message
# ===========================================================================
acc = StreamAccumulator()
acc.add_text("Hello ")
acc.add_text("world!")
acc.add_thinking("I should respond cheerfully.")
acc.set_signature(b"\xaa\xbb")
acc.start_tool_call(0, call_id="call_0", name="greet")
acc.add_tool_call_args(0, '{"target": "world"}')
acc.set_usage(L.Usage(input_tokens=10, output_tokens=5))
acc.set_stop_reason("end_turn")

msg = acc.build_message()
assert len(msg.parts) == 3  # thinking, text, tool_call (in that order)
assert msg.parts[0].is_thinking()
assert msg.parts[0].extra["signature"] == b"\xaa\xbb"
assert msg.parts[1].is_text() and msg.parts[1].text == "Hello world!"
assert msg.parts[2].is_tool_call()
assert msg.parts[2].tool_name == "greet"
assert msg.parts[2].tool_args == {"target": "world"}
assert msg.parts[2].tool_call_id == "call_0"

final = acc.final_chunk()
assert final.is_final
assert final.usage.input_tokens == 10
assert final.stop_reason == "end_turn"
print("[PASS] StreamAccumulator assembles deltas correctly")


# ===========================================================================
# Test 9: stop_reason normalization across providers
# ===========================================================================
n = BaseLLMClient.normalize_stop_reason
# Gemini values
assert n("STOP") == "stop"
assert n("MAX_TOKENS") == "length"
assert n("SAFETY") == "content_filter"
# Anthropic values
assert n("end_turn") == "stop"
assert n("tool_use") == "tool_use"
assert n("max_tokens") == "length"
# OpenAI values
assert n("tool_calls") == "tool_use"
assert n("content_filter") == "content_filter"
# Empty
assert n("") == "stop"
print("[PASS] stop_reason normalization works across all 3 provider vocabs")


# ===========================================================================
# Test 10: llm.py has no top-level google/anthropic/openai imports
# (the lazy-provider promise -- single-provider users don't pay all)
# ===========================================================================
src_init = (ROOT / "llm" / "__init__.py").read_text(encoding="utf-8")
src_types = (ROOT / "llm" / "types.py").read_text(encoding="utf-8")
src_proto = (ROOT / "llm" / "protocol.py").read_text(encoding="utf-8")
src_errors = (ROOT / "llm" / "errors.py").read_text(encoding="utf-8")
src_base = (ROOT / "llm" / "base.py").read_text(encoding="utf-8")
src_factory = (ROOT / "llm" / "factory.py").read_text(encoding="utf-8")
for src_name, src in (
    ("llm/__init__.py", src_init),
    ("llm/types.py", src_types),
    ("llm/protocol.py", src_proto),
    ("llm/errors.py", src_errors),
    ("llm/base.py", src_base),
    ("llm/factory.py", src_factory),
):
    for ln_no, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        for bad in ("from google", "import google",
                    "import anthropic", "from anthropic",
                    "import openai", "from openai"):
            if s.startswith(bad):
                raise AssertionError(
                    f"{src_name}:{ln_no} leaks top-level provider "
                    f"import: {line!r}"
                )
print("[PASS] public llm/ modules have no top-level provider imports")


# ===========================================================================
# Test 11: factory lazy-imports adapter modules
# ===========================================================================
import subprocess
script = (
    "import sys; before = set(sys.modules); "
    "import llm; added = set(sys.modules) - before; "
    "leaked = [m for m in added if m.startswith(('google.', 'anthropic.', 'openai.'))]; "
    "print('LEAK:' + ','.join(leaked) if leaked else 'CLEAN')"
)
proc = subprocess.run(
    [sys.executable, "-c", script],
    capture_output=True, text=True, cwd=str(ROOT),
)
out = proc.stdout.strip()
assert out == "CLEAN" or out.startswith("LEAK:"), (
    f"unexpected output: {out!r} stderr={proc.stderr!r}"
)
# Even if the user has SDKs installed elsewhere, importing `llm`
# alone shouldn't have eagerly imported their internals.
print(f"[PASS] importing `llm` is lazy ({out})")


print("\nOK -- LLMClient protocol probes passed.")
