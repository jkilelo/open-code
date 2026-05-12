"""Neutral exception hierarchy. Adapters translate provider-native
exceptions to these via BaseLLMClient._translate_error().

Hierarchy:

    LLMError
    +-- LLMConfigError              # setup-time (key missing, sdk not installed)
    |   +-- LLMAuthenticationError  # 401 (sometimes ConfigError-y)
    +-- LLMCallError                # runtime call failed
        +-- LLMTimeoutError
        +-- LLMConnectionError
        +-- LLMRateLimitError       # 429
        +-- LLMBadRequestError      # 400 / 422
        +-- LLMPermissionError      # 403
        +-- LLMNotFoundError        # 404
        +-- LLMServerError          # 5xx
        +-- LLMSafetyError          # content policy block (not always 4xx)
"""
from __future__ import annotations


class LLMError(Exception):
    """Base for every LLM-layer exception."""


class LLMConfigError(LLMError):
    """Setup-time failures: missing api key, unknown provider, SDK
    not installed, malformed settings. Generally not retryable."""


class LLMAuthenticationError(LLMConfigError):
    """Provider rejected the credential (HTTP 401). Treated as a
    config error -- user must fix it before any call can succeed."""


class LLMCallError(LLMError):
    """A specific API call failed at runtime."""


class LLMTimeoutError(LLMCallError):
    """Network or server-side timeout. Retryable."""


class LLMConnectionError(LLMCallError):
    """Network-level failure (DNS, TLS, broken pipe). Retryable."""


class LLMRateLimitError(LLMCallError):
    """429. Often retryable after backoff. Carries .retry_after if
    the provider returned one."""

    def __init__(
        self, message: str, retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMBadRequestError(LLMCallError):
    """400 / 422 -- the request is malformed. Not retryable as-is."""


class LLMPermissionError(LLMCallError):
    """403 -- credential is valid but lacks access to this resource."""


class LLMNotFoundError(LLMCallError):
    """404 -- model or resource not found."""


class LLMServerError(LLMCallError):
    """5xx -- provider-side failure. Retryable with backoff."""


class LLMSafetyError(LLMCallError):
    """Content-policy block. Provider-specific:

      Gemini: finish_reason in (SAFETY, RECITATION, PROHIBITED_CONTENT,
              SPII, IMAGE_SAFETY, BLOCKLIST), OR
              prompt_feedback.block_reason
      Anthropic: stop_reason="refusal", or refusal block in content
      OpenAI: refusal output item, or finish_reason="content_filter"
    """

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


__all__ = [
    "LLMError",
    "LLMConfigError",
    "LLMAuthenticationError",
    "LLMCallError",
    "LLMTimeoutError",
    "LLMConnectionError",
    "LLMRateLimitError",
    "LLMBadRequestError",
    "LLMPermissionError",
    "LLMNotFoundError",
    "LLMServerError",
    "LLMSafetyError",
]
