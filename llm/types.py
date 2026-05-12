"""Neutral types -- the wire format between open-code and any LLM provider.

These dataclasses are the agnostic layer. Adapters translate to/from
provider-native types on every call. JSONL session storage uses the
same shape verbatim, so resume preserves provider-specific opaque
state (thought signatures, encrypted reasoning, cache markers) via
the per-Part `extra` dict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Roles. Most providers use "model" or "assistant" -- internally we
# use "model"; adapters map. "tool" is a synthetic role for tool
# results (most providers send these as a user-role message).
ROLE_USER = "user"
ROLE_MODEL = "model"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"


# Part kinds. The flat-discriminated-union shape (vs. one dataclass
# per kind) matches the JSONL on-disk schema and keeps the dispatch
# loop simple.
KIND_TEXT = "text"
KIND_TOOL_CALL = "tool_call"
KIND_TOOL_RESULT = "tool_result"
KIND_THINKING = "thinking"
KIND_IMAGE = "image"


@dataclass
class Part:
    """A piece of a message. Kind discriminates the union:

      - text:        kind="text", text=...
      - tool_call:   kind="tool_call", tool_name, tool_args, tool_call_id
      - tool_result: kind="tool_result", tool_name, tool_call_id,
                     tool_result, is_error
      - thinking:    kind="thinking", text=<summary>,
                     extra["signature"]=<bytes|str>
      - image:       kind="image", image_mime,
                     + one of {image_data, image_url, image_file_id}

    `extra` is the provider-opaque escape hatch -- the agent loop
    never inspects it. Adapters stash provider-specific state here
    (Gemini thought_signature, Anthropic cache_control, OpenAI
    encrypted_content) so it round-trips through history.
    """
    kind: str = KIND_TEXT

    # text
    text: str = ""

    # tool_call & tool_result
    tool_call_id: str = ""    # provider call ID; required for parallel matching
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)     # tool_call
    tool_result: dict[str, Any] = field(default_factory=dict)   # tool_result
    is_error: bool = False    # tool_result indicator

    # image (input only -- providers don't currently emit images)
    image_mime: str = ""      # "image/png", "image/jpeg", ...
    image_data: bytes | None = None  # inline bytes
    image_url: str = ""       # https URL or data: URL
    image_file_id: str = ""   # provider Files API id

    # opaque per-part provider stash (signature, cache_control, ...)
    extra: dict[str, Any] = field(default_factory=dict)

    # ---- constructors ----

    @classmethod
    def make_text(cls, t: str) -> "Part":
        return cls(kind=KIND_TEXT, text=t)

    @classmethod
    def make_tool_call(
        cls, name: str, args: dict[str, Any], *,
        tool_call_id: str = "", extra: dict[str, Any] | None = None,
    ) -> "Part":
        return cls(
            kind=KIND_TOOL_CALL, tool_name=name,
            tool_args=dict(args) if args else {},
            tool_call_id=tool_call_id,
            extra=dict(extra) if extra else {},
        )

    @classmethod
    def make_tool_result(
        cls, name: str, result: dict[str, Any], *,
        tool_call_id: str = "", is_error: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> "Part":
        # Auto-detect is_error from open-code's {"ok": False} tool
        # convention if the caller didn't specify.
        if is_error is None:
            is_error = bool(
                isinstance(result, dict) and result.get("ok") is False
            )
        return cls(
            kind=KIND_TOOL_RESULT, tool_name=name,
            tool_result=dict(result) if result else {},
            tool_call_id=tool_call_id, is_error=bool(is_error),
            extra=dict(extra) if extra else {},
        )

    @classmethod
    def make_thinking(
        cls, text: str, *, signature: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> "Part":
        base_extra = dict(extra) if extra else {}
        if signature is not None:
            base_extra["signature"] = signature
        return cls(kind=KIND_THINKING, text=text, extra=base_extra)

    @classmethod
    def make_image(
        cls, *, mime: str = "",
        data: bytes | None = None, url: str = "", file_id: str = "",
    ) -> "Part":
        if not (data or url or file_id):
            raise ValueError(
                "Part.make_image requires one of data, url, or file_id"
            )
        return cls(
            kind=KIND_IMAGE, image_mime=mime,
            image_data=data, image_url=url, image_file_id=file_id,
        )

    # ---- accessors ----

    def is_text(self) -> bool:
        return self.kind == KIND_TEXT

    def is_tool_call(self) -> bool:
        return self.kind == KIND_TOOL_CALL

    def is_tool_result(self) -> bool:
        return self.kind == KIND_TOOL_RESULT

    def is_thinking(self) -> bool:
        return self.kind == KIND_THINKING

    def is_image(self) -> bool:
        return self.kind == KIND_IMAGE


@dataclass
class Message:
    """One turn. Roles map across providers via the adapter:

      user   -> user (all three)
      model  -> model / assistant
      system -> system / instructions (usually promoted to a top-level
                param rather than appearing in the messages list)
      tool   -> a user-role message carrying tool_result parts
    """
    role: str = ROLE_USER
    parts: list[Part] = field(default_factory=list)

    def text(self) -> str:
        """Concatenate every text part. Empty if no text."""
        return "".join(p.text for p in self.parts if p.is_text())

    def tool_calls(self) -> list[Part]:
        return [p for p in self.parts if p.is_tool_call()]

    def tool_results(self) -> list[Part]:
        return [p for p in self.parts if p.is_tool_result()]

    def thinking(self) -> list[Part]:
        return [p for p in self.parts if p.is_thinking()]


@dataclass
class ToolDecl:
    """A function the model can call. Mirrors JSON Schema's function
    declaration shape; adapters translate to provider-native shapes
    (Gemini FunctionDeclaration, Anthropic tool def, OpenAI tool param).
    """
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    strict: bool = False     # OpenAI/Anthropic strict-mode grammar
    builtin: str = ""        # if set, names a provider built-in tool
                             # (e.g. "web_search"); parameters ignored
    extra: dict[str, Any] = field(default_factory=dict)  # cache_control etc


@dataclass
class Usage:
    """Token accounting. Most providers report these four; the rest
    are provider-specific extensions exposed for cost analytics.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0       # OpenAI/Anthropic thinking
    cached_input_tokens: int = 0    # all three (prompt cache hits)
    cache_write_tokens: int = 0     # Anthropic cache_creation_input_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def merge(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


# Neutral stop-reason codes. Adapters normalize provider values to one
# of these via BaseLLMClient.normalize_stop_reason.
STOP_REASONS = (
    "stop", "length", "tool_use", "content_filter",
    "refusal", "pause", "error",
)


@dataclass
class AskResult:
    """Non-streaming response. `message` always has role="model"."""
    message: Message
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "stop"
    raw: Any = None     # provider-native response for debug / escape hatch


@dataclass
class StreamChunk:
    """One streaming event.

    Adapters yield text/tool/thinking deltas as they arrive. The
    caller accumulates. The final chunk has is_final=True and
    carries the final Usage (some providers only deliver usage at
    the end of the stream).
    """
    text_delta: str = ""
    tool_calls: list[Part] = field(default_factory=list)
    thinking_delta: str = ""
    usage: Usage | None = None
    stop_reason: str = ""
    is_final: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "Part", "Message", "ToolDecl", "Usage", "AskResult", "StreamChunk",
    "ROLE_USER", "ROLE_MODEL", "ROLE_SYSTEM", "ROLE_TOOL",
    "KIND_TEXT", "KIND_TOOL_CALL", "KIND_TOOL_RESULT",
    "KIND_THINKING", "KIND_IMAGE",
    "STOP_REASONS",
]
