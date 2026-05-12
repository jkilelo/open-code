"""LLMClient Protocol -- the structural type every adapter implements."""
from __future__ import annotations

from typing import Any, Iterator, Protocol

from .types import AskResult, Message, StreamChunk, ToolDecl


class LLMClient(Protocol):
    """Provider-agnostic interface. Three core methods plus a
    `provider` tag.

    Structural typing: any class with these methods is an LLMClient.
    BaseLLMClient in base.py is an optional ABC that gives you the
    bookkeeping (error translation, stop-reason normalization) for
    free if you want to inherit.

    Parameter philosophy: every method accepts the full neutral kwarg
    surface. Adapters silently drop the ones their SDK doesn't
    support rather than raising. Provider-specific knobs go through
    `extra={}` (escape hatch on the call) or `Part.extra={}` (per-part
    opaque metadata that round-trips through history).
    """

    provider: str

    def ask(
        self,
        *,
        model: str,
        messages: list[Message],
        system_instruction: str = "",
        tools: list[ToolDecl] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        seed: int | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
        candidate_count: int | None = None,
        metadata: dict[str, str] | None = None,
        user: str | None = None,
        thinking_effort: str | None = None,
        thinking_budget: int | None = None,
        include_thinking: bool = False,
        response_schema: dict[str, Any] | type | None = None,
        response_mime_type: str = "",
        extra: dict[str, Any] | None = None,
    ) -> AskResult:
        """Generate a single completion (non-streaming)."""
        ...

    def ask_stream(
        self,
        *,
        model: str,
        messages: list[Message],
        system_instruction: str = "",
        tools: list[ToolDecl] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        parallel_tool_calls: bool | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        seed: int | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
        candidate_count: int | None = None,
        metadata: dict[str, str] | None = None,
        user: str | None = None,
        thinking_effort: str | None = None,
        thinking_budget: int | None = None,
        include_thinking: bool = False,
        response_schema: dict[str, Any] | type | None = None,
        response_mime_type: str = "",
        extra: dict[str, Any] | None = None,
    ) -> Iterator[StreamChunk]:
        """Streaming variant of ask. Yields chunks until done. The
        last chunk has is_final=True and carries the final Usage."""
        ...

    def embed(
        self, *, model: str, texts: list[str],
        task_type: str = "", output_dimensionality: int | None = None,
    ) -> list[list[float]]:
        """One embedding per input text. Empty inner list means the
        provider couldn't embed that text. Anthropic raises
        LLMConfigError -- it has no embeddings API."""
        ...


__all__ = ["LLMClient"]
