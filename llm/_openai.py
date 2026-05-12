"""OpenAI adapter via the Responses API (modern path).

The Responses API (launched 2025-03) is OpenAI's primary surface for
new agent code: first-class agents, server-side conversation state,
built-in tools (web_search, file_search, code_interpreter,
computer_use, mcp, image_generation), persistent reasoning across
turns via previous_response_id.

For OSS-compat providers that only speak Chat Completions (Groq,
vLLM, Anthropic-OpenAI shim, etc.), use _openai_chat.OpenAIChatClient
instead via provider="openai_chat".

SDK reference: openai 2.36.0 (verified 2026-05-12).
"""
from __future__ import annotations

import base64
import json
from typing import Any, Iterator

import openai

from .base import BaseLLMClient, StreamAccumulator
from .errors import (
    LLMAuthenticationError, LLMBadRequestError, LLMCallError,
    LLMConnectionError, LLMNotFoundError, LLMPermissionError,
    LLMRateLimitError, LLMSafetyError, LLMServerError, LLMTimeoutError,
)
from .types import AskResult, Message, Part, StreamChunk, ToolDecl, Usage


# thinking_effort -> Responses reasoning.effort
# (`xhigh` is the highest tier; "off" maps to "none" which disables
# reasoning entirely on reasoning-capable models)
_EFFORT_MAP = {
    "off": "none", "minimal": "minimal", "low": "low",
    "medium": "medium", "high": "high", "max": "xhigh",
}


class OpenAIResponsesClient(BaseLLMClient):
    """Adapter implementing LLMClient against openai 2.x Responses API."""

    provider: str = "openai"

    def __init__(
        self, *, api_key: str, extra: dict[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._extra = dict(extra) if extra else {}
        self._client = openai.OpenAI(api_key=api_key)

    # ---- adapter hooks ----

    def _ask_impl(self, **kwargs: Any) -> AskResult:
        params = self._coerce_params(**kwargs)
        resp = self._client.responses.create(**params)
        return self._to_ask_result(resp)

    def _ask_stream_impl(self, **kwargs: Any) -> Iterator[StreamChunk]:
        params = self._coerce_params(**kwargs)
        params["stream"] = True
        acc = StreamAccumulator()
        # Map OpenAI response.output_item.id -> our tool-call index
        tool_item_idx: dict[str, int] = {}

        stream = self._client.responses.create(**params)
        for event in stream:
            et = getattr(event, "type", "")

            if et == "response.output_text.delta":
                yield acc.add_text(getattr(event, "delta", "") or "")

            elif et == "response.reasoning_text.delta":
                yield acc.add_thinking(getattr(event, "delta", "") or "")

            elif et == "response.reasoning_summary_text.delta":
                # Summary reasoning is also fair game as a thinking delta
                yield acc.add_thinking(getattr(event, "delta", "") or "")

            elif et == "response.output_item.added":
                item = event.item
                it = getattr(item, "type", "")
                if it == "function_call":
                    idx = len(tool_item_idx)
                    tool_item_idx[getattr(item, "id", "")] = idx
                    acc.start_tool_call(
                        idx,
                        call_id=getattr(item, "call_id", "") or "",
                        name=getattr(item, "name", "") or "",
                    )

            elif et == "response.function_call_arguments.delta":
                item_id = getattr(event, "item_id", "")
                idx = tool_item_idx.get(item_id)
                if idx is not None:
                    acc.add_tool_call_args(
                        idx, getattr(event, "delta", "") or "",
                    )

            elif et == "response.completed":
                resp = event.response
                u = getattr(resp, "usage", None)
                if u is not None:
                    acc.set_usage(self._usage_from_meta(u))
                acc.set_stop_reason("stop")

            elif et == "response.failed":
                resp = event.response
                err = getattr(resp, "error", None)
                msg = (
                    getattr(err, "message", "openai stream failed")
                    if err else "openai stream failed"
                )
                raise LLMCallError(f"openai: {msg}")

            elif et == "response.incomplete":
                acc.set_stop_reason("length")

            elif et == "error":
                err = getattr(event, "error", None)
                msg = (
                    getattr(err, "message", "openai stream error")
                    if err else "openai stream error"
                )
                raise LLMCallError(f"openai: {msg}")

        yield acc.final_chunk()

    def _embed_impl(
        self, *, model: str, texts: list[str],
        task_type: str = "", output_dimensionality: int | None = None,
    ) -> list[list[float]]:
        # OpenAI ignores task_type. dimensions only works on -3- models.
        kwargs: dict[str, Any] = {"model": model, "input": list(texts)}
        if output_dimensionality is not None:
            kwargs["dimensions"] = output_dimensionality
        resp = self._client.embeddings.create(**kwargs)
        out: list[list[float]] = []
        for item in (resp.data or []):
            vec = getattr(item, "embedding", None)
            out.append(list(vec) if vec else [])
        return out

    # ---- neutral -> native coercion ----

    def _coerce_params(self, **kw: Any) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": kw["model"],
            "input": self._messages_to_native(kw["messages"]),
        }
        if kw.get("system_instruction"):
            params["instructions"] = kw["system_instruction"]
        if kw.get("max_output_tokens") is not None:
            params["max_output_tokens"] = kw["max_output_tokens"]
        if kw.get("temperature") is not None:
            params["temperature"] = kw["temperature"]
        if kw.get("top_p") is not None:
            params["top_p"] = kw["top_p"]
        # top_k, seed, presence_penalty, frequency_penalty,
        # stop_sequences, candidate_count: NOT supported on Responses.
        # Silently dropped.

        # Tools
        tools = kw.get("tools") or []
        if tools:
            params["tools"] = self._tools_to_native(tools)
        tc = kw.get("tool_choice")
        if tc is not None:
            params["tool_choice"] = self._tool_choice_to_native(tc)
        if kw.get("parallel_tool_calls") is not None:
            params["parallel_tool_calls"] = bool(kw["parallel_tool_calls"])

        # Reasoning
        effort = kw.get("thinking_effort")
        include = kw.get("include_thinking")
        if effort or include:
            reasoning: dict[str, Any] = {}
            if effort:
                reasoning["effort"] = _EFFORT_MAP.get(effort, "medium")
            if include:
                reasoning["summary"] = "auto"
            params["reasoning"] = reasoning

        # Structured output: text.format.json_schema
        schema = kw.get("response_schema")
        if schema is not None:
            schema_dict = (
                schema if isinstance(schema, dict)
                else self._pydantic_schema(schema)
            )
            params["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "response",
                    "strict": True,
                    "schema": schema_dict,
                },
            }

        if kw.get("metadata"):
            params["metadata"] = dict(kw["metadata"])
        if kw.get("user"):
            params["safety_identifier"] = kw["user"]

        # Provider-specific via extra={}
        extra = dict(kw.get("extra") or {})
        for k in (
            "store", "previous_response_id", "conversation",
            "include", "truncation", "service_tier", "background",
            "max_tool_calls", "prompt_cache_key", "prompt_cache_retention",
            "top_logprobs", "extra_headers", "extra_query", "timeout",
        ):
            if k in extra:
                params[k] = extra.pop(k)
        if extra:
            params.setdefault("extra_body", {}).update(extra)

        return params

    @staticmethod
    def _pydantic_schema(model: Any) -> dict[str, Any]:
        try:
            return model.model_json_schema()
        except AttributeError:
            return {}

    def _messages_to_native(
        self, msgs: list[Message],
    ) -> list[dict[str, Any]]:
        """Translate to Responses API `input` items.

        Responses uses a flat list of items. A user/assistant message
        becomes a `message` item with role+content. Tool calls become
        `function_call` items (top-level, not inside messages). Tool
        results become `function_call_output` items. Reasoning round-
        trips as `reasoning` items with encrypted_content (when
        store=False).
        """
        out: list[dict[str, Any]] = []
        for m in msgs:
            role = m.role
            if role == "model":
                role = "assistant"

            if role == "tool":
                # Each tool_result becomes a top-level function_call_output
                for p in m.parts:
                    if p.is_tool_result():
                        out.append({
                            "type": "function_call_output",
                            "call_id": p.tool_call_id or "",
                            "output": (
                                json.dumps(p.tool_result)
                                if p.tool_result else ""
                            ),
                        })
                continue

            content_parts: list[dict[str, Any]] = []
            for p in m.parts:
                if p.is_thinking() and p.extra.get("encrypted_content"):
                    # Reasoning rides as top-level item
                    out.append({
                        "type": "reasoning",
                        "encrypted_content": p.extra["encrypted_content"],
                    })
                    continue
                if p.is_tool_result():
                    # Legacy sessions stored tool_result Parts inside
                    # user-role messages (the role="tool" convention is
                    # post-v0.30.2). Lift them to top-level
                    # function_call_output items so resume keeps working.
                    out.append({
                        "type": "function_call_output",
                        "call_id": p.tool_call_id or "",
                        "output": (
                            json.dumps(p.tool_result)
                            if p.tool_result else ""
                        ),
                    })
                    continue
                if p.is_text() and p.text:
                    kind = "input_text" if role == "user" else "output_text"
                    content_parts.append({"type": kind, "text": p.text})
                elif p.is_tool_call():
                    # function_call is a top-level item, not nested
                    out.append({
                        "type": "function_call",
                        "call_id": p.tool_call_id or "",
                        "name": p.tool_name,
                        "arguments": (
                            json.dumps(p.tool_args) if p.tool_args else "{}"
                        ),
                    })
                elif p.is_image() and role == "user":
                    if p.image_url:
                        content_parts.append({
                            "type": "input_image",
                            "image_url": p.image_url,
                        })
                    elif p.image_file_id:
                        content_parts.append({
                            "type": "input_image",
                            "file_id": p.image_file_id,
                        })
                    elif p.image_data:
                        b64 = base64.b64encode(p.image_data).decode("ascii")
                        url = (
                            f"data:{p.image_mime or 'image/png'};base64,{b64}"
                        )
                        content_parts.append({
                            "type": "input_image",
                            "image_url": url,
                        })
            if content_parts:
                out.append({
                    "type": "message",
                    "role": role,
                    "content": content_parts,
                })
        return out

    @staticmethod
    def _tools_to_native(tools: list[ToolDecl]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in tools:
            if t.builtin:
                # Built-in (web_search, file_search, code_interpreter, ...)
                td: dict[str, Any] = {"type": t.builtin}
                if t.extra:
                    td.update(t.extra)
                out.append(td)
                continue
            # Responses uses FLAT tool shape (no nested "function" wrapper)
            td = {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": (
                    dict(t.parameters) if t.parameters
                    else {"type": "object", "properties": {}}
                ),
            }
            if t.strict:
                td["strict"] = True
            out.append(td)
        return out

    @staticmethod
    def _tool_choice_to_native(tc: Any) -> Any:
        if isinstance(tc, str):
            tcl = tc.lower()
            if tcl in ("none", "auto", "required"):
                return tcl
            if tcl == "any":
                return "required"
        if isinstance(tc, dict):
            if tc.get("type") == "tool" and tc.get("name"):
                return {"type": "function", "name": tc["name"]}
            return dict(tc)
        return "auto"

    # ---- native -> neutral coercion ----

    def _to_ask_result(self, resp: Any) -> AskResult:
        output = getattr(resp, "output", None) or []
        parts: list[Part] = []
        for item in output:
            it = getattr(item, "type", "")
            if it == "message":
                for c in (getattr(item, "content", None) or []):
                    ct = getattr(c, "type", "")
                    if ct == "output_text":
                        parts.append(Part.make_text(c.text))
                    elif ct == "refusal":
                        raise LLMSafetyError(
                            f"openai refused: {getattr(c, 'refusal', '')}",
                            reason="refusal",
                        )
            elif it == "reasoning":
                enc = getattr(item, "encrypted_content", None)
                summary_items = getattr(item, "summary", None) or []
                text = " ".join(
                    getattr(s, "text", "") for s in summary_items
                    if hasattr(s, "text")
                )
                extra: dict[str, Any] = {}
                if enc is not None:
                    extra["encrypted_content"] = enc
                if text or enc is not None:
                    parts.append(Part.make_thinking(text, extra=extra))
            elif it == "function_call":
                args_str = getattr(item, "arguments", "") or "{}"
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {"_raw": args_str}
                parts.append(Part.make_tool_call(
                    getattr(item, "name", ""),
                    args,
                    tool_call_id=getattr(item, "call_id", "") or "",
                ))

        msg = Message(role="model", parts=parts)
        usage = self._usage_from_meta(getattr(resp, "usage", None))
        status = getattr(resp, "status", "completed")
        stop = (
            "stop" if status == "completed"
            else self.normalize_stop_reason(status)
        )
        return AskResult(message=msg, usage=usage, stop_reason=stop, raw=resp)

    @staticmethod
    def _usage_from_meta(meta: Any) -> Usage:
        if meta is None:
            return Usage()
        input_details = getattr(meta, "input_tokens_details", None)
        output_details = getattr(meta, "output_tokens_details", None)
        cached = (
            getattr(input_details, "cached_tokens", 0)
            if input_details else 0
        )
        reasoning = (
            getattr(output_details, "reasoning_tokens", 0)
            if output_details else 0
        )
        return Usage(
            input_tokens=getattr(meta, "input_tokens", 0) or 0,
            output_tokens=getattr(meta, "output_tokens", 0) or 0,
            reasoning_tokens=reasoning or 0,
            cached_input_tokens=cached or 0,
        )

    # ---- error translation ----

    def _translate_error(self, exc: Exception) -> Exception:
        if isinstance(exc, openai.AuthenticationError):
            return LLMAuthenticationError(f"openai: {exc}")
        if isinstance(exc, openai.PermissionDeniedError):
            return LLMPermissionError(f"openai: {exc}")
        if isinstance(exc, openai.NotFoundError):
            return LLMNotFoundError(f"openai: {exc}")
        if isinstance(exc, openai.RateLimitError):
            return LLMRateLimitError(f"openai: {exc}")
        if isinstance(exc, openai.BadRequestError):
            return LLMBadRequestError(f"openai: {exc}")
        if isinstance(exc, openai.InternalServerError):
            return LLMServerError(f"openai: {exc}")
        if isinstance(exc, openai.APITimeoutError):
            return LLMTimeoutError(f"openai: {exc}")
        if isinstance(exc, openai.APIConnectionError):
            return LLMConnectionError(f"openai: {exc}")
        return super()._translate_error(exc)

    @property
    def raw_client(self) -> Any:
        return self._client
