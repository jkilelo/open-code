"""Anthropic Claude adapter.

Translates between open-code neutral types and anthropic SDK content
blocks. Only file in the package that imports `anthropic`. Factory
keeps it lazy so users on Gemini/OpenAI don't need the SDK installed.

SDK reference: anthropic 0.101.0 (verified 2026-05-12).
"""
from __future__ import annotations

import base64
import json
from typing import Any, Iterator

import anthropic

from .base import BaseLLMClient, StreamAccumulator
from .errors import (
    LLMAuthenticationError, LLMBadRequestError, LLMConnectionError,
    LLMNotFoundError, LLMPermissionError, LLMRateLimitError,
    LLMSafetyError, LLMServerError, LLMTimeoutError,
)
from .types import AskResult, Message, Part, StreamChunk, ToolDecl, Usage


# Anthropic requires max_tokens. Adapter default; bump on thinking.
_DEFAULT_MAX_TOKENS = 4096
_THINKING_MIN_MAX_TOKENS = 16384


# Adaptive-thinking models: use thinking={"type":"adaptive"} -- they
# self-budget. Empirically (verified live 2026-05-12): adaptive is
# Opus/Sonnet 4.6+ only; Haiku 4.5 rejects adaptive with
# 'adaptive thinking is not supported on this model'. Older models
# (Opus 4.5, Sonnet 4.5, Sonnet 3.7) use type=enabled + budget. Haiku
# 4.5 falls through to enabled mode too.
_ADAPTIVE_THINKING_MODELS = (
    "opus-4-7", "opus-4-6", "sonnet-4-6",
)


# thinking_effort -> token budget for enabled-mode models
_EFFORT_BUDGETS = {
    "off": 0,
    "minimal": 1024,
    "low": 2048,
    "medium": 4096,
    "high": 8192,
    "max": 16000,
}


class AnthropicClient(BaseLLMClient):
    """Adapter implementing LLMClient against anthropic 0.x."""

    provider: str = "anthropic"

    def __init__(
        self, *, api_key: str, extra: dict[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._extra = dict(extra) if extra else {}
        self._client = anthropic.Anthropic(api_key=api_key)

    # ---- adapter hooks ----

    def _ask_impl(self, **kwargs: Any) -> AskResult:
        params = self._coerce_params(**kwargs)
        resp = self._client.messages.create(**params)
        return self._to_ask_result(resp)

    def _ask_stream_impl(self, **kwargs: Any) -> Iterator[StreamChunk]:
        params = self._coerce_params(**kwargs)
        params.pop("stream", None)
        acc = StreamAccumulator()
        # Map Anthropic's content_block index -> our tool-call slot
        tool_block_idx: dict[int, int] = {}

        with self._client.messages.stream(**params) as stream:
            for event in stream:
                et = getattr(event, "type", "")

                if et == "content_block_start":
                    block = event.content_block
                    bt = getattr(block, "type", "")
                    if bt == "tool_use":
                        new_idx = len(tool_block_idx)
                        tool_block_idx[event.index] = new_idx
                        acc.start_tool_call(
                            new_idx,
                            call_id=getattr(block, "id", "") or "",
                            name=getattr(block, "name", "") or "",
                        )

                elif et == "content_block_delta":
                    delta = event.delta
                    dt = getattr(delta, "type", "")
                    if dt == "text_delta":
                        yield acc.add_text(delta.text)
                    elif dt == "thinking_delta":
                        yield acc.add_thinking(delta.thinking)
                    elif dt == "signature_delta":
                        acc.set_signature(delta.signature)
                    elif dt == "input_json_delta":
                        idx = tool_block_idx.get(event.index)
                        if idx is not None:
                            acc.add_tool_call_args(idx, delta.partial_json)

                elif et == "message_delta":
                    # Anthropic usage is CUMULATIVE in message_delta;
                    # set (don't add). Final stop_reason rides here.
                    u = getattr(event, "usage", None)
                    if u is not None:
                        acc.set_usage(self._usage_from_meta(u))
                    sr = getattr(event.delta, "stop_reason", None)
                    if sr:
                        acc.set_stop_reason(sr)

                elif et == "message_stop":
                    break

        if acc.stop_reason() == "refusal":
            raise LLMSafetyError(
                "anthropic refused to respond", reason="refusal",
            )
        yield acc.final_chunk()

    def _embed_impl(self, **kwargs: Any) -> list[list[float]]:
        # Anthropic has no embeddings API. Base class catches the
        # NotImplementedError and raises LLMConfigError with the
        # "use Voyage/OpenAI/Gemini" hint.
        raise NotImplementedError

    # ---- neutral -> native coercion ----

    def _coerce_params(self, **kw: Any) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": kw["model"],
            "messages": self._messages_to_native(kw["messages"]),
            "max_tokens": kw.get("max_output_tokens") or _DEFAULT_MAX_TOKENS,
        }

        if kw.get("system_instruction"):
            params["system"] = kw["system_instruction"]

        # Tools
        tools = kw.get("tools") or []
        if tools:
            params["tools"] = self._tools_to_native(tools)
        tc = kw.get("tool_choice")
        if tc is not None:
            params["tool_choice"] = self._tool_choice_to_native(tc)
        if kw.get("parallel_tool_calls") is False:
            existing_tc = params.setdefault("tool_choice", {"type": "auto"})
            if isinstance(existing_tc, dict):
                existing_tc["disable_parallel_tool_use"] = True

        # Sampling (Anthropic temperature is 0..1; clamp)
        if kw.get("temperature") is not None:
            params["temperature"] = max(0.0, min(1.0, float(kw["temperature"])))
        if kw.get("top_p") is not None:
            params["top_p"] = kw["top_p"]
        if kw.get("top_k") is not None:
            params["top_k"] = kw["top_k"]
        if kw.get("stop_sequences"):
            params["stop_sequences"] = list(kw["stop_sequences"])
        # seed, presence_penalty, frequency_penalty, candidate_count:
        # not supported by Anthropic. Silently dropped.

        # Thinking
        thinking_param = self._thinking_to_native(
            kw["model"], kw.get("thinking_effort"), kw.get("thinking_budget"),
        )
        if thinking_param is not None:
            params["thinking"] = thinking_param
            # max_tokens must exceed budget. Bump if caller didn't size it.
            cur_max = params["max_tokens"]
            min_required = max(
                _THINKING_MIN_MAX_TOKENS,
                (thinking_param.get("budget_tokens") or 0) + 1024,
            )
            if cur_max < min_required:
                params["max_tokens"] = min_required

        # Structured output (Anthropic's output_config / json_schema)
        schema = kw.get("response_schema")
        if schema is not None:
            schema_dict = (
                schema if isinstance(schema, dict)
                else self._pydantic_schema(schema)
            )
            params["output_config"] = {
                "format": {"type": "json_schema", "schema": schema_dict},
            }

        # Metadata: only user_id is honored
        md = kw.get("metadata") or {}
        if md.get("user_id"):
            params["metadata"] = {"user_id": str(md["user_id"])}
        elif kw.get("user"):
            params["metadata"] = {"user_id": str(kw["user"])}

        # Provider-specific knobs via extra={}
        extra = dict(kw.get("extra") or {})
        for k in (
            "betas", "service_tier", "container", "mcp_servers",
            "extra_headers", "extra_query", "extra_body", "timeout",
        ):
            if k in extra:
                params[k] = extra.pop(k)
        # Remaining extras go to extra_body for forward-compat
        if extra:
            params.setdefault("extra_body", {}).update(extra)

        return params

    @staticmethod
    def _pydantic_schema(model: Any) -> dict[str, Any]:
        try:
            return model.model_json_schema()
        except AttributeError:
            return {}

    def _messages_to_native(self, msgs: list[Message]) -> list[dict[str, Any]]:
        """Translate neutral messages to Anthropic shape.

        Anthropic requires alternating user/assistant; tool results
        ride as user-role messages with tool_result blocks. We
        preserve neutral Part order, which means callers building
        assistant turns should put thinking parts FIRST (before
        tool_use) -- Anthropic enforces this ordering.
        """
        out: list[dict[str, Any]] = []
        for m in msgs:
            role = m.role
            if role == "model":
                role = "assistant"
            if role == "tool":
                role = "user"
            blocks: list[dict[str, Any]] = []
            for p in m.parts:
                blk = self._part_to_block(p)
                if blk is not None:
                    blocks.append(blk)
            if not blocks:
                continue  # Anthropic disallows empty messages
            out.append({"role": role, "content": blocks})
        return out

    def _part_to_block(self, p: Part) -> dict[str, Any] | None:
        if p.is_thinking():
            sig = p.extra.get("signature")
            if sig is None:
                # No signature -> treat as redacted_thinking
                data = p.extra.get("data") or ""
                if data:
                    return {"type": "redacted_thinking", "data": data}
                return None
            return {
                "type": "thinking",
                "thinking": p.text,
                "signature": sig,
            }
        if p.is_text() and p.text:
            blk: dict[str, Any] = {"type": "text", "text": p.text}
            cc = p.extra.get("cache_control")
            if cc:
                blk["cache_control"] = cc
            return blk
        if p.is_tool_call():
            return {
                "type": "tool_use",
                "id": p.tool_call_id or f"toolu_{p.tool_name}",
                "name": p.tool_name,
                "input": dict(p.tool_args) if p.tool_args else {},
            }
        if p.is_tool_result():
            tr: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": p.tool_call_id or "",
                "content": (
                    json.dumps(p.tool_result) if p.tool_result else ""
                ),
            }
            if p.is_error:
                tr["is_error"] = True
            return tr
        if p.is_image():
            src: dict[str, Any]
            if p.image_data:
                src = {
                    "type": "base64",
                    "media_type": p.image_mime or "image/png",
                    "data": base64.b64encode(p.image_data).decode("ascii"),
                }
            elif p.image_url:
                src = {"type": "url", "url": p.image_url}
            elif p.image_file_id:
                src = {"type": "file", "file_id": p.image_file_id}
            else:
                return None
            return {"type": "image", "source": src}
        return None

    @staticmethod
    def _tools_to_native(tools: list[ToolDecl]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t in tools:
            if t.builtin:
                # Anthropic built-ins: type-versioned name (bash_20250124,
                # text_editor_20250728, etc) -- caller provides via builtin.
                td: dict[str, Any] = {"type": t.builtin, "name": t.builtin}
                if t.extra:
                    td.update(t.extra)
                out.append(td)
                continue
            td = {
                "name": t.name,
                "description": t.description,
                "input_schema": (
                    dict(t.parameters) if t.parameters
                    else {"type": "object", "properties": {}}
                ),
            }
            if t.strict:
                td["strict"] = True
            if t.extra.get("cache_control"):
                td["cache_control"] = t.extra["cache_control"]
            out.append(td)
        return out

    @staticmethod
    def _tool_choice_to_native(tc: Any) -> dict[str, Any]:
        if isinstance(tc, str):
            tcl = tc.lower()
            if tcl in ("auto", "any", "none"):
                return {"type": tcl}
            if tcl == "required":
                return {"type": "any"}
        if isinstance(tc, dict):
            if tc.get("type") == "tool" and tc.get("name"):
                return {"type": "tool", "name": tc["name"]}
            return dict(tc)
        return {"type": "auto"}

    @staticmethod
    def _thinking_to_native(
        model: str, effort: str | None, budget: int | None,
    ) -> dict[str, Any] | None:
        if not effort and budget is None:
            return None
        if effort == "off":
            return None
        ml = (model or "").lower()
        if any(m in ml for m in _ADAPTIVE_THINKING_MODELS):
            return {"type": "adaptive"}
        # Older models: enabled + explicit budget_tokens
        b = budget
        if b is None and effort:
            b = _EFFORT_BUDGETS.get(effort, _EFFORT_BUDGETS["medium"])
        if not b or b < 1024:
            return None
        return {"type": "enabled", "budget_tokens": b}

    # ---- native -> neutral coercion ----

    def _to_ask_result(self, resp: Any) -> AskResult:
        content = getattr(resp, "content", None) or []
        parts: list[Part] = []
        for blk in content:
            bt = getattr(blk, "type", "")
            if bt == "text":
                parts.append(Part.make_text(blk.text))
            elif bt == "thinking":
                parts.append(Part.make_thinking(
                    getattr(blk, "thinking", ""),
                    signature=getattr(blk, "signature", None),
                ))
            elif bt == "redacted_thinking":
                p = Part(
                    kind="thinking", text="",
                    extra={"data": getattr(blk, "data", "")},
                )
                parts.append(p)
            elif bt == "tool_use":
                parts.append(Part.make_tool_call(
                    blk.name,
                    dict(getattr(blk, "input", None) or {}),
                    tool_call_id=getattr(blk, "id", "") or "",
                ))
            # server_tool_use / web_search_tool_result: surfaced only
            # if user enables those tools; skip for default flow.

        msg = Message(role="model", parts=parts)
        usage = self._usage_from_meta(getattr(resp, "usage", None))
        stop_native = getattr(resp, "stop_reason", "") or ""
        if stop_native == "refusal":
            raise LLMSafetyError(
                "anthropic refused to respond", reason="refusal",
            )
        stop = self.normalize_stop_reason(stop_native)
        return AskResult(message=msg, usage=usage, stop_reason=stop, raw=resp)

    @staticmethod
    def _usage_from_meta(meta: Any) -> Usage:
        if meta is None:
            return Usage()
        return Usage(
            input_tokens=getattr(meta, "input_tokens", 0) or 0,
            output_tokens=getattr(meta, "output_tokens", 0) or 0,
            cached_input_tokens=getattr(meta, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(meta, "cache_creation_input_tokens", 0) or 0,
        )

    # ---- error translation ----

    def _translate_error(self, exc: Exception) -> Exception:
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMAuthenticationError(f"anthropic: {exc}")
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LLMPermissionError(f"anthropic: {exc}")
        if isinstance(exc, anthropic.NotFoundError):
            return LLMNotFoundError(f"anthropic: {exc}")
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(f"anthropic: {exc}")
        if isinstance(exc, anthropic.BadRequestError):
            return LLMBadRequestError(f"anthropic: {exc}")
        if isinstance(exc, anthropic.InternalServerError):
            return LLMServerError(f"anthropic: {exc}")
        if isinstance(exc, anthropic.APITimeoutError):
            return LLMTimeoutError(f"anthropic: {exc}")
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMConnectionError(f"anthropic: {exc}")
        return super()._translate_error(exc)

    @property
    def raw_client(self) -> Any:
        return self._client
