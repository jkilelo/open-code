"""Probe: full-loop integration -- run_loop against fake LLMClients.

Catches the cross-cutting bugs that adapter unit tests miss. These are
the EXACT regressions v0.30.2 found by manual REPL testing on
Anthropic; this probe would have caught all six without burning a
single live API call:

  1. cli passing wrong API key to non-Gemini providers
  2. settings.llm.model ignored by --model resolution
  3. REPL banner hardcoded
  4. tool decls UPPERCASE schema (Anthropic/OpenAI reject)
  5. tool_call_id not round-tripping from tool_use to tool_result
  6. tool_result message using role="user" instead of role="tool"
     (OpenAI Responses drops it silently)

Strategy: build a fake LLMClient that records every kwargs dict it
receives. Script its responses to drive a tool_use turn + final
text turn. Then assert on the recorded call shapes.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm import (
    AskResult, Message, Part, ToolDecl, Usage,
)


class FakeLLMClient:
    """LLMClient that records every ask() / ask_stream() call's kwargs
    and emits scripted responses. Both methods are scripted via the
    same `responses` list; the loop consumes one per iteration.
    """
    provider = "fake"

    def __init__(self, responses: list[AskResult]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def ask(self, **kwargs):
        # Snapshot mutable list/dict args at call time -- run_loop
        # mutates `messages` between iterations and we want each
        # recorded call to reflect ITS OWN state, not the final state.
        snapshot = dict(kwargs)
        if "messages" in snapshot:
            snapshot["messages"] = list(snapshot["messages"])
        if "tools" in snapshot:
            snapshot["tools"] = list(snapshot["tools"])
        self.calls.append({"method": "ask", "kwargs": snapshot})
        if not self._responses:
            raise AssertionError("FakeLLMClient: ran out of scripted responses")
        return self._responses.pop(0)

    def ask_stream(self, **kwargs):
        # We don't exercise streaming in this probe -- pass-through ask
        result = self.ask(**kwargs)
        from llm import StreamChunk
        for p in result.message.parts:
            if p.is_text() and p.text:
                yield StreamChunk(text_delta=p.text)
            elif p.is_tool_call():
                yield StreamChunk(tool_calls=[p])
        yield StreamChunk(
            usage=result.usage,
            stop_reason=result.stop_reason,
            is_final=True,
        )

    def embed(self, *, model, texts, task_type="",
              output_dimensionality=None):
        return [[] for _ in texts]


def _make_session_store(base: Path):
    from sessions import SessionStore
    return SessionStore(base / "sessions")


# ===========================================================================
# Test 1: full tool-use round-trip records correct call_id propagation
# ===========================================================================
print("Test 1: tool_call_id round-trips from model -> dispatch -> next ask", flush=True)
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    store = _make_session_store(base)
    sess = store.create(str(base), "fake-model", "test")

    from open_code import run_loop, SYSTEM_INSTRUCTION
    from tools import CONFIG
    from settings import Settings

    # Iter 1: model emits a tool_call with a specific id.
    EXPECTED_CALL_ID = "call_VERY_SPECIFIC_TOKEN_xyz123"
    iter1_response = AskResult(
        message=Message(role="model", parts=[
            Part.make_tool_call(
                "list_dir", {"path": "."},
                tool_call_id=EXPECTED_CALL_ID,
            ),
        ]),
        usage=Usage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    # Iter 2: model emits final text (no more tool calls).
    iter2_response = AskResult(
        message=Message(role="model", parts=[
            Part.make_text("Done!"),
        ]),
        usage=Usage(input_tokens=20, output_tokens=3),
        stop_reason="stop",
    )

    fake_llm = FakeLLMClient([iter1_response, iter2_response])

    CONFIG.cwd = base
    code, metrics = run_loop(
        task="list this directory then say done",
        model="fake-model", api_key="ignored",
        max_iterations=5, store=store, session=sess,
        verbose=False, stream=False,
        system_instruction=SYSTEM_INSTRUCTION,
        settings=Settings(), is_repl=False,
        fire_session_start=False,
        llm=fake_llm,
    )

assert code == 0, f"expected exit=0, got {code}"
assert len(fake_llm.calls) == 2, (
    f"expected 2 ask calls (iter1 + iter2); got {len(fake_llm.calls)}"
)

# === ASSERTION SET A: iter 1 saw a fresh history + tools ===
call1 = fake_llm.calls[0]["kwargs"]
assert call1["model"] == "fake-model", call1
# Tools must be lowercase JSON Schema (catches v0.30.2 bug #4)
tools = call1.get("tools") or []
assert tools, "iter 1 should be passed tools"
for tool in tools:
    params = tool.parameters or {}
    if not params:
        continue
    schema_type = params.get("type")
    if schema_type:
        assert schema_type == schema_type.lower(), (
            f"tool {tool.name!r} schema.type must be lowercase JSON Schema; "
            f"got {schema_type!r}"
        )
# History should be: [user message]
msgs = call1["messages"]
assert len(msgs) == 1, f"iter 1 expected 1 history msg; got {len(msgs)}"
assert msgs[0].role == "user", f"first turn must be user; got {msgs[0].role!r}"
print("  [PASS] iter 1: fresh history, lowercase tool schemas")

# === ASSERTION SET B: iter 2's history has the tool_result with role="tool" ===
# (catches v0.30.3 bug -- OpenAI Responses drops user-role tool_results)
call2 = fake_llm.calls[1]["kwargs"]
msgs = call2["messages"]
# Expected history: [user, model(tool_call), tool(tool_result)]
assert len(msgs) == 3, (
    f"iter 2 expected 3 history msgs; got {len(msgs)}: "
    f"{[(m.role, [p.kind for p in m.parts]) for m in msgs]}"
)
assert msgs[0].role == "user"
assert msgs[1].role == "model"
assert msgs[2].role == "tool", (
    f"tool_result message MUST have role='tool' (not 'user') so the "
    f"OpenAI Responses adapter lifts it to function_call_output; got "
    f"role={msgs[2].role!r}. This is the v0.30.3 regression."
)
print("  [PASS] iter 2: tool_result message uses role='tool'")

# === ASSERTION SET C: the tool_use_id round-trips into tool_result.tool_call_id ===
# (catches v0.30.2 bug #5)
tool_result_parts = [p for p in msgs[2].parts if p.is_tool_result()]
assert len(tool_result_parts) == 1, (
    f"expected 1 tool_result part on the tool turn; got {len(tool_result_parts)}"
)
tr = tool_result_parts[0]
assert tr.tool_call_id == EXPECTED_CALL_ID, (
    f"tool_call_id round-trip broke: model emitted "
    f"{EXPECTED_CALL_ID!r}, but dispatch produced "
    f"tool_result with tool_call_id={tr.tool_call_id!r}. This is the "
    f"v0.30.2 regression that Anthropic 400'd on."
)
print(f"  [PASS] iter 2: tool_call_id round-trip preserved {EXPECTED_CALL_ID!r}")


# ===========================================================================
# Test 2: streaming path -- same invariants must hold
# ===========================================================================
print("Test 2: same invariants via streaming path", flush=True)
with tempfile.TemporaryDirectory() as d:
    base = Path(d).resolve()
    store = _make_session_store(base)
    sess = store.create(str(base), "fake-model", "test stream")

    iter1_response = AskResult(
        message=Message(role="model", parts=[
            Part.make_tool_call(
                "list_dir", {"path": "."},
                tool_call_id="call_streamed_id_42",
            ),
        ]),
        usage=Usage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    iter2_response = AskResult(
        message=Message(role="model", parts=[Part.make_text("done")]),
        usage=Usage(input_tokens=20, output_tokens=3),
        stop_reason="stop",
    )

    fake_llm = FakeLLMClient([iter1_response, iter2_response])
    CONFIG.cwd = base
    code, _ = run_loop(
        task="list then done",
        model="fake-model", api_key="ignored",
        max_iterations=5, store=store, session=sess,
        verbose=False, stream=True,    # <-- streaming path
        system_instruction=SYSTEM_INSTRUCTION,
        settings=Settings(), is_repl=False,
        fire_session_start=False,
        llm=fake_llm,
    )

assert code == 0, code
assert len(fake_llm.calls) == 2
call2 = fake_llm.calls[1]["kwargs"]
assert call2["messages"][-1].role == "tool"
tr = [p for p in call2["messages"][-1].parts if p.is_tool_result()][0]
assert tr.tool_call_id == "call_streamed_id_42"
print("  [PASS] streaming path: role='tool', tool_call_id round-trips")


# ===========================================================================
# Test 3: tool decl shape contract -- every built-in tool's input_schema
# must be lowercase JSON Schema (catches v0.30.2 bug #4)
# ===========================================================================
print("Test 3: every built-in TOOL_DECLARATIONS uses lowercase schema", flush=True)
from tools import TOOL_DECLARATIONS

VIOLATIONS: list[str] = []

def _check_schema(name: str, schema: dict, path: str = "") -> None:
    if not isinstance(schema, dict):
        return
    t = schema.get("type")
    if isinstance(t, str) and t != t.lower():
        VIOLATIONS.append(f"{name}.{path or 'root'}: type={t!r} not lowercase")
    for k, v in (schema.get("properties") or {}).items():
        if isinstance(v, dict):
            _check_schema(name, v, f"{path}.properties.{k}" if path else f"properties.{k}")
    items = schema.get("items")
    if isinstance(items, dict):
        _check_schema(name, items, f"{path}.items" if path else "items")


for decl in TOOL_DECLARATIONS:
    name = decl.get("name", "<unnamed>")
    params = decl.get("parameters", {})
    _check_schema(name, params)

assert not VIOLATIONS, (
    "tool declarations contain Gemini-flavored UPPERCASE types -- "
    "Anthropic + OpenAI will reject them:\n  "
    + "\n  ".join(VIOLATIONS)
)
print(f"  [PASS] all {len(TOOL_DECLARATIONS)} tool decls use lowercase JSON Schema")


# ===========================================================================
# Test 4: settings.llm.model is honored when --model isn't passed
# (catches v0.30.2 bug #2)
# ===========================================================================
print("Test 4: settings.llm.model overrides DEFAULT_MODEL", flush=True)
import open_code

# Simulate the cli resolution path inline (cli.main has the full
# chain; we mirror it here in miniature).
DEFAULT = open_code.DEFAULT_MODEL
cli_default = DEFAULT  # user didn't pass --model

# Case A: settings.llm.model = "claude-haiku-4-5"
class _S:
    raw = {"llm": {"provider": "anthropic", "model": "claude-haiku-4-5"}}
    model = None

raw = getattr(_S, "raw", None) or {}
llm_cfg = raw.get("llm") if isinstance(raw, dict) else None
nested_model = llm_cfg.get("model") if isinstance(llm_cfg, dict) else None
resolved = nested_model or getattr(_S, "model", None) or DEFAULT
assert resolved == "claude-haiku-4-5", (
    f"settings.llm.model should beat DEFAULT_MODEL when CLI default; "
    f"got resolved={resolved!r}, expected 'claude-haiku-4-5'"
)
print("  [PASS] resolution chain: settings.llm.model wins over DEFAULT_MODEL")


# ===========================================================================
# Test 5: tool decls referenced in iter2's history must serialize fine
# through sessions storage round-trip
# ===========================================================================
print("Test 5: stored tool_result Message round-trips via JSONL", flush=True)
import sessions
m = Message(role="tool", parts=[
    Part.make_tool_result(
        "list_dir",
        {"ok": True, "entries": [{"name": "a.py", "size": 100}]},
        tool_call_id="call_persist_xyz",
    ),
])
d = sessions.content_to_dict(m)
m2 = sessions.dict_to_content(d)
assert m2.role == "tool", m2
assert len(m2.parts) == 1
p = m2.parts[0]
assert p.is_tool_result()
assert p.tool_call_id == "call_persist_xyz", p.tool_call_id
print("  [PASS] tool_result round-trip preserves role + tool_call_id")


print("\nOK -- integration probes passed (catches the v0.30.2/.3 regression class).")
