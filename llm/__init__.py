"""open-code LLM-agnostic layer.

Three first-class providers (verified against latest SDKs 2026-05-12):

  - google-genai 2.1.0  (Gemini)        via `._gemini.GeminiClient`
  - anthropic 0.101.0   (Claude)        via `._anthropic.AnthropicClient`
  - openai 2.36.0       (GPT Responses) via `._openai.OpenAIResponsesClient`
                        (Chat fallback) via `._openai_chat.OpenAIChatClient`

Public API:

    from llm import (
        LLMClient, LLMError, LLMConfigError, LLMCallError, ...,
        Part, Message, ToolDecl, Usage, AskResult, StreamChunk,
        make_llm_client, default_model_for,
    )

Adapters live in private modules (`._gemini`, `._anthropic`,
`._openai`, `._openai_chat`); instantiate them via
`make_llm_client(provider=...)`. The factory lazy-imports each
adapter module so users on one provider never pay the cost of the
others' SDKs at startup.

Design constraints:

  1. Neutral types only. open-code never imports a provider SDK
     directly. Adapters do that, inside their own modules.

  2. The protocol is small. Three methods on LLMClient -- ask,
     ask_stream, embed -- plus a `provider` tag.

  3. Tool calls + tool results are first-class in the neutral
     Part type. The session JSONL on disk uses the same shape, so
     storage was always provider-agnostic; only the in-memory
     boundary needed translation.

  4. Streaming chunks carry text_delta, tool_calls (list of Part),
     thinking_delta, usage (only on the final chunk for some
     providers). The caller assembles.

  5. Failure modes are exceptions. LLMConfigError for setup
     issues, LLMCallError + subclasses for runtime API failures.
     LLMSafetyError when the provider blocks output.

  6. Provider-specific knobs go through:
       - `extra={}` on ask/ask_stream for call-level params
       - `Part.extra={}` for opaque per-part round-trip state
         (signatures, encrypted reasoning, cache markers).
"""
from __future__ import annotations

from .errors import (
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMCallError,
    LLMConfigError,
    LLMConnectionError,
    LLMError,
    LLMNotFoundError,
    LLMPermissionError,
    LLMRateLimitError,
    LLMSafetyError,
    LLMServerError,
    LLMTimeoutError,
)
from .factory import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_MODELS,
    default_model_for,
    make_llm_client,
)
from .protocol import LLMClient
from .types import (
    AskResult,
    KIND_IMAGE,
    KIND_TEXT,
    KIND_THINKING,
    KIND_TOOL_CALL,
    KIND_TOOL_RESULT,
    Message,
    Part,
    ROLE_MODEL,
    ROLE_SYSTEM,
    ROLE_TOOL,
    ROLE_USER,
    STOP_REASONS,
    StreamChunk,
    ToolDecl,
    Usage,
)


__all__ = [
    # Types
    "Part", "Message", "ToolDecl", "Usage", "AskResult", "StreamChunk",
    # Constants
    "ROLE_USER", "ROLE_MODEL", "ROLE_SYSTEM", "ROLE_TOOL",
    "KIND_TEXT", "KIND_TOOL_CALL", "KIND_TOOL_RESULT",
    "KIND_THINKING", "KIND_IMAGE",
    "STOP_REASONS",
    # Errors
    "LLMError", "LLMConfigError", "LLMCallError",
    "LLMAuthenticationError", "LLMTimeoutError", "LLMConnectionError",
    "LLMRateLimitError", "LLMBadRequestError", "LLMPermissionError",
    "LLMNotFoundError", "LLMServerError", "LLMSafetyError",
    # Protocol + factory
    "LLMClient",
    "make_llm_client", "default_model_for",
    "DEFAULT_MODELS", "DEFAULT_API_KEY_ENV",
]
