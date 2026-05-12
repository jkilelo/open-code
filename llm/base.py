"""Shared machinery for LLM provider adapters.

BaseLLMClient is an optional ABC that wraps adapter calls with
uniform error translation and stop-reason normalization. Subclass it
and implement _ask_impl / _ask_stream_impl / _embed_impl with the
SDK-native call.

StreamAccumulator is a helper for assembling streaming events from
text/tool/thinking deltas into a final Message and emitting neutral
StreamChunks as deltas arrive. Eliminates ~150 lines of duplicated
assembly code per adapter.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Iterator

from .errors import (
    LLMCallError, LLMConfigError, LLMConnectionError, LLMError,
    LLMRateLimitError, LLMServerError, LLMTimeoutError,
)
from .types import AskResult, Message, Part, StreamChunk, Usage


class BaseLLMClient(ABC):
    """Optional base class for provider adapters.

    Inheriting gives you:
      - Uniform error translation (provider exc -> LLMError tree)
      - Default embed() that raises LLMConfigError if _embed_impl
        isn't overridden
      - Stop-reason normalization helper
      - A consistent `provider` tag

    The LLMClient Protocol is structural -- subclasses don't have
    to inherit from this; it's just a convenience to share code.
    """
    provider: str = "base"

    # ---- protocol surface (concrete, wraps the _impl hooks) ----

    def ask(self, **kwargs: Any) -> AskResult:
        try:
            return self._ask_impl(**kwargs)
        except LLMError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from exc

    def ask_stream(self, **kwargs: Any) -> Iterator[StreamChunk]:
        try:
            for chunk in self._ask_stream_impl(**kwargs):
                yield chunk
        except LLMError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from exc

    def embed(
        self, *, model: str, texts: list[str],
        task_type: str = "", output_dimensionality: int | None = None,
    ) -> list[list[float]]:
        try:
            return self._embed_impl(
                model=model, texts=texts,
                task_type=task_type,
                output_dimensionality=output_dimensionality,
            )
        except LLMError:
            raise
        except NotImplementedError:
            raise LLMConfigError(
                f"{self.provider!r} does not support embeddings. "
                f"Use Gemini or OpenAI for embedding-backed features "
                f"(or proxy to Voyage AI for Anthropic-flavored vectors)."
            ) from None
        except Exception as exc:
            raise self._translate_error(exc) from exc

    # ---- adapter hooks (subclasses implement) ----

    @abstractmethod
    def _ask_impl(self, **kwargs: Any) -> AskResult:
        """Provider-specific non-streaming call."""

    @abstractmethod
    def _ask_stream_impl(self, **kwargs: Any) -> Iterator[StreamChunk]:
        """Provider-specific streaming call."""

    def _embed_impl(
        self, *, model: str, texts: list[str],
        task_type: str = "", output_dimensionality: int | None = None,
    ) -> list[list[float]]:
        """Override to support embeddings. Default raises."""
        raise NotImplementedError

    # ---- shared helpers ----

    def _translate_error(self, exc: Exception) -> LLMError:
        """Map provider-native exception to an LLMError subclass.

        Subclasses override for provider-specific exception
        hierarchies (the openai/anthropic SDKs have clean classes
        we can isinstance-check). Default falls back to name-based
        heuristics so even a never-seen-before exception lands
        somewhere sensible.
        """
        name = type(exc).__name__.lower()
        msg = f"{self.provider}: {type(exc).__name__}: {exc}"
        if "timeout" in name:
            return LLMTimeoutError(msg)
        if "connection" in name or "connect" in name:
            return LLMConnectionError(msg)
        if "ratelimit" in name or "rate_limit" in name:
            return LLMRateLimitError(msg)
        if (
            name.endswith("servererror")
            or "internal" in name
            or "overloaded" in name
        ):
            return LLMServerError(msg)
        return LLMCallError(msg)

    # Provider finish/stop -> neutral stop_reason. Subclasses can
    # extend the table or override entirely.
    _STOP_REASON_MAP: dict[str, str] = {
        # Gemini
        "STOP": "stop", "MAX_TOKENS": "length",
        "SAFETY": "content_filter", "RECITATION": "content_filter",
        "BLOCKLIST": "content_filter",
        "PROHIBITED_CONTENT": "content_filter",
        "SPII": "content_filter", "IMAGE_SAFETY": "content_filter",
        "MALFORMED_FUNCTION_CALL": "error",
        "UNEXPECTED_TOOL_CALL": "error",
        "LANGUAGE": "content_filter",
        "OTHER": "stop",
        # Anthropic
        "end_turn": "stop", "max_tokens": "length",
        "stop_sequence": "stop", "tool_use": "tool_use",
        "pause_turn": "pause", "refusal": "refusal",
        # OpenAI Chat
        "stop": "stop", "length": "length",
        "tool_calls": "tool_use", "content_filter": "content_filter",
        "function_call": "tool_use",
        # OpenAI Responses
        "completed": "stop", "incomplete": "length",
        "failed": "error", "cancelled": "error",
    }

    @classmethod
    def normalize_stop_reason(cls, provider_reason: str) -> str:
        if not provider_reason:
            return "stop"
        return cls._STOP_REASON_MAP.get(
            provider_reason, provider_reason.lower() or "stop",
        )


class StreamAccumulator:
    """Assemble streaming deltas into a final Message + per-chunk
    neutral StreamChunks. Adapters call add_* / set_* / start_*
    methods as native events arrive, yielding the returned chunk
    when present, then call build_message() + final_chunk() when
    the stream completes.

    Tool-call args are accumulated as partial JSON strings (this is
    how Anthropic and OpenAI deliver them) and parsed on completion.
    Malformed partial JSON falls back to {"_raw": "..."} so we don't
    crash the agent loop on a provider bug.
    """

    def __init__(self) -> None:
        self._text: list[str] = []
        self._thinking: list[str] = []
        self._signature: Any = None
        self._tool_calls: dict[int, dict[str, Any]] = {}
        self._usage: Usage | None = None
        self._stop_reason: str = ""

    # ---- delta inputs ----

    def add_text(self, s: str) -> StreamChunk:
        if s:
            self._text.append(s)
        return StreamChunk(text_delta=s)

    def add_thinking(self, s: str) -> StreamChunk:
        if s:
            self._thinking.append(s)
        return StreamChunk(thinking_delta=s)

    def set_signature(self, sig: Any) -> None:
        if sig is not None:
            self._signature = sig

    def start_tool_call(
        self, idx: int, *, call_id: str = "", name: str = "",
    ) -> None:
        tc = self._tool_calls.setdefault(idx, {
            "call_id": "", "name": "",
            "args_buf": [], "extra": {},
        })
        if call_id:
            tc["call_id"] = call_id
        if name:
            tc["name"] = name

    def add_tool_call_args(self, idx: int, partial: str) -> None:
        tc = self._tool_calls.setdefault(idx, {
            "call_id": "", "name": "",
            "args_buf": [], "extra": {},
        })
        if partial:
            tc["args_buf"].append(partial)

    def set_tool_call_extra(
        self, idx: int, extra: dict[str, Any],
    ) -> None:
        tc = self._tool_calls.setdefault(idx, {
            "call_id": "", "name": "",
            "args_buf": [], "extra": {},
        })
        tc["extra"].update(extra)

    def set_usage(self, u: Usage) -> None:
        """Replace running usage (Anthropic delivers cumulative
        usage in message_delta -- the latest value wins)."""
        self._usage = u

    def add_usage(self, u: Usage) -> None:
        """Add to running total (for providers that emit
        incremental usage)."""
        self._usage = (self._usage or Usage()).merge(u)

    def set_stop_reason(self, r: str) -> None:
        if r:
            self._stop_reason = r

    @property
    def tool_call_count(self) -> int:
        return len(self._tool_calls)

    # ---- finalize ----

    def build_message(self) -> Message:
        parts: list[Part] = []
        if self._thinking:
            parts.append(Part.make_thinking(
                "".join(self._thinking),
                signature=self._signature,
            ))
        if self._text:
            parts.append(Part.make_text("".join(self._text)))
        for idx in sorted(self._tool_calls.keys()):
            tc = self._tool_calls[idx]
            if not tc.get("name"):
                continue   # incomplete; skip
            parts.append(self._build_tool_part(tc))
        return Message(role="model", parts=parts)

    def final_chunk(self) -> StreamChunk:
        return StreamChunk(
            usage=self._usage,
            stop_reason=self._stop_reason,
            is_final=True,
        )

    def usage(self) -> Usage | None:
        return self._usage

    def stop_reason(self) -> str:
        return self._stop_reason

    # ---- internals ----

    @staticmethod
    def _build_tool_part(tc: dict[str, Any]) -> Part:
        args_str = "".join(tc.get("args_buf") or [])
        try:
            args = json.loads(args_str) if args_str.strip() else {}
        except json.JSONDecodeError:
            args = {"_raw": args_str}
        return Part.make_tool_call(
            tc["name"], args,
            tool_call_id=tc.get("call_id") or "",
            extra=dict(tc.get("extra") or {}),
        )


__all__ = ["BaseLLMClient", "StreamAccumulator"]
