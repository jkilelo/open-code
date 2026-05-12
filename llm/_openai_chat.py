"""OpenAI Chat Completions adapter (legacy / OSS-compat).

For native OpenAI, prefer the Responses API (`_openai.py`). This
adapter exists for:
  (a) OSS-compat providers exposing only Chat Completions (Groq,
      vLLM, Anthropic-OpenAI shim, etc.) -- point `base_url` at them
      via extra={"base_url": "..."}.
  (b) Azure OpenAI deployments on Chat-only models.

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


_EFFORT_MAP = {
    "off": "none", "minimal": "minimal", "low": "low",
    "medium": "medium", "high": "high", "max": "xhigh",
}


class OpenAIChatClient(BaseLLMClient):
    """Adapter implementing LLMClient against openai 2.x Chat Completions."""

    provider: str = "openai_chat"

    def __init__(
        self, *, api_key: str, extra: dict[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._extra = dict(extra) if extra else {}
        # Allow base_url override for OSS-compat backends
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if "base_url" in self._extra:
            client_kwargs["base_url"] = self._extra["base_url"]
        self._client = openai.OpenAI(**client_kwargs)

    # ---- adapter hooks ----

    def _ask_impl(self, **kwargs: Any) -> AskResult:
        params = self._coerce_params(**kwargs)
        resp = self._client.chat.completions.create(**params)
        return self._to_ask_result(resp)

    def _ask_stream_impl(self, **kwargs: Any) -> Iterator[StreamChunk]:
        params = self._coerce_params(**kwargs)
        params["stream"] = True
        # Without this, Chat Completions doesn't emit usage in stream.
        params["stream_options"] = {"include_usage": True}
        acc = StreamAccumulator()
        # Map native delta.tool_calls[i].index -> our internal slot
        tool_idx_map: dict[int, int] = {}

        for chunk in self._client.chat.completions.create(**params):
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                acc.set_usage(self._usage_from_meta(usage))
            for choice in (getattr(chunk, "choices", None) or []):
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                text = getattr(delta, "content", None)
                if text:
                    yield acc.add_text(text)
                for tc in (getattr(delta, "tool_calls", None) or []):
                    nat_idx = getattr(tc, "index", 0)
                    our_idx = tool_idx_map.get(nat_idx)
                    if our_idx is None:
                        our_idx = len(tool_idx_map)
                        tool_idx_map[nat_idx] = our_idx
                        acc.start_tool_call(our_idx)
                    if getattr(tc, "id", None):
                        acc.start_tool_call(our_idx, call_id=tc.id)
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            acc.start_tool_call(our_idx, name=fn.name)
                        if getattr(fn, "arguments", None):
                            acc.add_tool_call_args(our_idx, fn.arguments)
                fr = getattr(choice, "finish_reason", None)
                if fr:
                    acc.set_stop_reason(fr)
                    if fr == "content_filter":
                        raise LLMSafetyError(
                            "openai chat: content_filter",
                            reason="content_filter",
                        )

        yield acc.final_chunk()

    def _embed_impl(
        self, *, model: str, texts: list[str],
        task_type: str = "", output_dimensionality: int | None = None,
    ) -> list[list[float]]:
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
            "messages": self._messages_to_native(
                kw["messages"], kw.get("system_instruction") or "",
            ),
        }
        if kw.get("max_output_tokens") is not None:
            params["max_completion_tokens"] = kw["max_output_tokens"]
        for src, dst in (
            ("temperature", "temperature"),
            ("top_p", "top_p"),
            ("seed", "seed"),
            ("presence_penalty", "presence_penalty"),
            ("frequency_penalty", "frequency_penalty"),
            ("candidate_count", "n"),
        ):
            v = kw.get(src)
            if v is not None:
                params[dst] = v
        if kw.get("stop_sequences"):
            params["stop"] = list(kw["stop_sequences"])

        # Tools
        tools = kw.get("tools") or []
        if tools:
            params["tools"] = self._tools_to_native(tools)
        tc = kw.get("tool_choice")
        if tc is not None:
            params["tool_choice"] = self._tool_choice_to_native(tc)
        if kw.get("parallel_tool_calls") is not None:
            params["parallel_tool_calls"] = bool(kw["parallel_tool_calls"])

        # Reasoning effort (o-series / gpt-5+ models)
        effort = kw.get("thinking_effort")
        if effort:
            params["reasoning_effort"] = _EFFORT_MAP.get(effort, "medium")

        # Structured output
        schema = kw.get("response_schema")
        if schema is not None:
            schema_dict = (
                schema if isinstance(schema, dict)
                else self._pydantic_schema(schema)
            )
            params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response", "strict": True, "schema": schema_dict,
                },
            }

        if kw.get("metadata"):
            params["metadata"] = dict(kw["metadata"])
        if kw.get("user"):
            params["safety_identifier"] = kw["user"]

        # Provider-specific via extra={}
        extra = dict(kw.get("extra") or {})
        # base_url was consumed at __init__; drop if present
        extra.pop("base_url", None)
        for k in (
            "store", "service_tier", "logprobs", "top_logprobs",
            "logit_bias", "web_search_options", "verbosity",
            "extra_headers", "extra_query", "timeout",
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
        self, msgs: list[Message], system: str = "",
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in msgs:
            role = m.role
            if role == "model":
                role = "assistant"

            if role == "tool":
                # Each tool_result becomes its own {"role":"tool"} message
                for p in m.parts:
                    if p.is_tool_result():
                        out.append({
                            "role": "tool",
                            "tool_call_id": p.tool_call_id or "",
                            "content": (
                                json.dumps(p.tool_result)
                                if p.tool_result else ""
                            ),
                        })
                continue

            # Build one message with content + optional tool_calls
            text_parts: list[dict[str, Any]] = []
            tool_calls: list[dict[str, Any]] = []
            for p in m.parts:
                if p.is_text() and p.text:
                    text_parts.append({"type": "text", "text": p.text})
                elif p.is_tool_call():
                    tool_calls.append({
                        "id": p.tool_call_id or "",
                        "type": "function",
                        "function": {
                            "name": p.tool_name,
                            "arguments": (
                                json.dumps(p.tool_args)
                                if p.tool_args else "{}"
                            ),
                        },
                    })
                elif p.is_image() and role == "user":
                    url = ""
                    if p.image_url:
                        url = p.image_url
                    elif p.image_data:
                        b64 = base64.b64encode(p.image_data).decode("ascii")
                        url = (
                            f"data:{p.image_mime or 'image/png'};base64,{b64}"
                        )
                    if url:
                        text_parts.append({
                            "type": "image_url",
                            "image_url": {"url": url},
                        })

            msg_obj: dict[str, Any] = {"role": role}
            if text_parts:
                # Chat accepts either str or list[content_part]; pass str
                # if only one text block (smaller payload).
                if (
                    len(text_parts) == 1
                    and text_parts[0].get("type") == "text"
                ):
                    msg_obj["content"] = text_parts[0]["text"]
                else:
                    msg_obj["content"] = text_parts
            elif tool_calls:
                msg_obj["content"] = None
            else:
                continue  # empty message; skip
            if tool_calls:
                msg_obj["tool_calls"] = tool_calls
            out.append(msg_obj)
        return out

    @staticmethod
    def _tools_to_native(tools: list[ToolDecl]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in tools:
            if t.builtin:
                # Chat doesn't have a flexible built-in tool surface --
                # web_search rides via web_search_options instead.
                continue
            td: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": (
                        dict(t.parameters) if t.parameters
                        else {"type": "object", "properties": {}}
                    ),
                },
            }
            if t.strict:
                td["function"]["strict"] = True
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
                return {
                    "type": "function",
                    "function": {"name": tc["name"]},
                }
            return dict(tc)
        return "auto"

    # ---- native -> neutral coercion ----

    def _to_ask_result(self, resp: Any) -> AskResult:
        choices = getattr(resp, "choices", None) or []
        if not choices:
            raise LLMCallError("openai chat returned no choices")
        choice = choices[0]
        msg_obj = getattr(choice, "message", None)
        if msg_obj is None:
            raise LLMCallError("openai chat choice has no message")

        if getattr(msg_obj, "refusal", None):
            raise LLMSafetyError(
                f"openai chat refused: {msg_obj.refusal}",
                reason="refusal",
            )

        parts: list[Part] = []
        text = getattr(msg_obj, "content", None)
        if text:
            parts.append(Part.make_text(text))
        for tc in getattr(msg_obj, "tool_calls", None) or []:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            args_str = getattr(fn, "arguments", "") or "{}"
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {"_raw": args_str}
            parts.append(Part.make_tool_call(
                fn.name, args, tool_call_id=getattr(tc, "id", "") or "",
            ))

        msg = Message(role="model", parts=parts)
        usage = self._usage_from_meta(getattr(resp, "usage", None))
        stop_native = getattr(choice, "finish_reason", "") or ""
        if stop_native == "content_filter":
            raise LLMSafetyError(
                "openai chat: content_filter", reason="content_filter",
            )
        stop = self.normalize_stop_reason(stop_native)
        return AskResult(message=msg, usage=usage, stop_reason=stop, raw=resp)

    @staticmethod
    def _usage_from_meta(meta: Any) -> Usage:
        if meta is None:
            return Usage()
        prompt_details = getattr(meta, "prompt_tokens_details", None)
        completion_details = getattr(meta, "completion_tokens_details", None)
        cached = (
            getattr(prompt_details, "cached_tokens", 0)
            if prompt_details else 0
        )
        reasoning = (
            getattr(completion_details, "reasoning_tokens", 0)
            if completion_details else 0
        )
        return Usage(
            input_tokens=getattr(meta, "prompt_tokens", 0) or 0,
            output_tokens=getattr(meta, "completion_tokens", 0) or 0,
            reasoning_tokens=reasoning or 0,
            cached_input_tokens=cached or 0,
        )

    # ---- error translation ----

    def _translate_error(self, exc: Exception) -> Exception:
        if isinstance(exc, openai.AuthenticationError):
            return LLMAuthenticationError(f"openai chat: {exc}")
        if isinstance(exc, openai.PermissionDeniedError):
            return LLMPermissionError(f"openai chat: {exc}")
        if isinstance(exc, openai.NotFoundError):
            return LLMNotFoundError(f"openai chat: {exc}")
        if isinstance(exc, openai.RateLimitError):
            return LLMRateLimitError(f"openai chat: {exc}")
        if isinstance(exc, openai.BadRequestError):
            return LLMBadRequestError(f"openai chat: {exc}")
        if isinstance(exc, openai.InternalServerError):
            return LLMServerError(f"openai chat: {exc}")
        if isinstance(exc, openai.APITimeoutError):
            return LLMTimeoutError(f"openai chat: {exc}")
        if isinstance(exc, openai.APIConnectionError):
            return LLMConnectionError(f"openai chat: {exc}")
        return super()._translate_error(exc)

    @property
    def raw_client(self) -> Any:
        return self._client
