"""make_llm_client(...) -- lazy-import factory dispatching by provider."""
from __future__ import annotations

import os
from typing import Any

from .errors import LLMConfigError
from .protocol import LLMClient


# Default model per provider when settings.llm.model is unset.
# Fast, cheap defaults; callers override for quality.
DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-3.1-flash-lite",
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-5.5-mini",
    "openai_chat": "gpt-5.5-mini",
    "ollama": "llama3.2",
}


# Each provider's default env var for the API key (Ollama uses no key).
DEFAULT_API_KEY_ENV: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openai_chat": "OPENAI_API_KEY",
    "ollama": "",
}


def make_llm_client(
    *,
    provider: str = "gemini",
    api_key: str | None = None,
    api_key_env: str | None = None,
    extra: dict[str, Any] | None = None,
) -> LLMClient:
    """Build an LLMClient for the named provider.

    Lazy-imports the adapter module so users on a single provider
    don't pay the cost of every SDK at startup.

    API key resolution (in order):
      1. `api_key` arg (explicit)
      2. `os.environ[api_key_env]` if api_key_env given
      3. `os.environ[DEFAULT_API_KEY_ENV[provider]]` (the conventional name)

    Raises `LLMConfigError` on:
      - missing api key (when required)
      - unknown provider
      - SDK not installed
    """
    provider = (provider or "gemini").lower().strip()
    extra = dict(extra) if extra else {}

    # Resolve api_key
    if api_key is None:
        env_name = api_key_env or DEFAULT_API_KEY_ENV.get(provider, "")
        if env_name:
            api_key = os.environ.get(env_name, "").strip() or None

    if provider == "gemini":
        if not api_key:
            raise LLMConfigError(
                "GEMINI_API_KEY not set. Put it in a .env file in your "
                "project, or export it. Get one at "
                "https://aistudio.google.com/app/apikey"
            )
        try:
            from ._gemini import GeminiClient
        except ImportError as exc:
            raise LLMConfigError(
                f"Gemini provider unavailable -- install google-genai. "
                f"({exc})"
            ) from exc
        return GeminiClient(api_key=api_key, extra=extra)

    if provider == "anthropic":
        if not api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY not set. Export it or add to .env. "
                "Get one at https://console.anthropic.com/"
            )
        try:
            from ._anthropic import AnthropicClient
        except ImportError as exc:
            raise LLMConfigError(
                f"Anthropic provider unavailable -- install anthropic. "
                f"({exc})"
            ) from exc
        return AnthropicClient(api_key=api_key, extra=extra)

    if provider == "openai":
        if not api_key:
            raise LLMConfigError(
                "OPENAI_API_KEY not set. Export it or add to .env. "
                "Get one at https://platform.openai.com/api-keys"
            )
        try:
            from ._openai import OpenAIResponsesClient
        except ImportError as exc:
            raise LLMConfigError(
                f"OpenAI provider unavailable -- install openai. "
                f"({exc})"
            ) from exc
        return OpenAIResponsesClient(api_key=api_key, extra=extra)

    if provider == "openai_chat":
        if not api_key:
            raise LLMConfigError(
                "OPENAI_API_KEY not set. Export it or add to .env."
            )
        try:
            from ._openai_chat import OpenAIChatClient
        except ImportError as exc:
            raise LLMConfigError(
                f"OpenAI provider unavailable -- install openai. "
                f"({exc})"
            ) from exc
        return OpenAIChatClient(api_key=api_key, extra=extra)

    raise LLMConfigError(
        f"Unknown LLM provider: {provider!r}. "
        f"Supported: {sorted(DEFAULT_MODELS)}"
    )


def default_model_for(provider: str) -> str:
    """Fallback when settings.llm.model is unset."""
    return DEFAULT_MODELS.get(
        (provider or "gemini").lower(), DEFAULT_MODELS["gemini"],
    )


__all__ = [
    "make_llm_client", "default_model_for",
    "DEFAULT_MODELS", "DEFAULT_API_KEY_ENV",
]
