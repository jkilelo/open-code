"""Probe: Vertex AI corporate mode wiring (no network).

Verifies that extra={"vertex": {...}} on the Gemini adapter:

  1. Routes through genai.Client(vertexai=True, project=..., location=...).
  2. Builds HttpOptions(base_url=...) when a corporate gateway is given.
  3. _CommandCredentials runs the shell command and exposes the
     stdout as .token, sets a future expiry, and re-runs on refresh().
  4. Errors helpfully when project is missing or the credentials
     command exits non-zero.
  5. Strips the `vertex` block out of _extra so per-call coercion
     never sees it.

The probe monkeypatches `genai.Client` and `subprocess.check_output`
so it never makes a network call or runs `helix`.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import _smoke_setup  # noqa: F401  -- UTF-8 stdout/stderr on Windows

import llm._gemini as gx
from llm import LLMConfigError, make_llm_client


# ===========================================================================
# Fake genai.Client recorder
# ===========================================================================
class FakeGenaiClient:
    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        FakeGenaiClient.last_kwargs = kwargs


# Patch the SDK Client constructor; restored at script end.
_real_genai_client = gx.genai.Client
gx.genai.Client = FakeGenaiClient  # type: ignore[assignment]


# ===========================================================================
# Test 1: vertex.enabled=True with credentials_command builds the right
# Client kwargs (vertexai=True, project, location, credentials, http_options)
# ===========================================================================
fake_subprocess_calls: list[str] = []


def fake_check_output(cmd: str, **_: Any) -> str:
    fake_subprocess_calls.append(cmd)
    return "fake-access-token-abc123\n"


real_check_output = gx.subprocess.check_output
gx.subprocess.check_output = fake_check_output  # type: ignore[assignment]

try:
    client = make_llm_client(
        provider="gemini",
        api_key=None,
        extra={
            "vertex": {
                "enabled": True,
                "project": "my-corp-project",
                "location": "global",
                "base_url": "https://corp-gateway.example.com",
                "api_version": "v1",
                "credentials_command": "helix auth access-token print -a",
            },
        },
    )
finally:
    pass

kw = FakeGenaiClient.last_kwargs
assert kw.get("vertexai") is True, kw
assert kw.get("project") == "my-corp-project", kw
assert kw.get("location") == "global", kw
assert "credentials" in kw, "credentials must be passed when command given"
creds = kw["credentials"]
assert getattr(creds, "token", None) == "fake-access-token-abc123", creds.token
http_opts = kw.get("http_options")
assert http_opts is not None and getattr(http_opts, "base_url", "") == \
    "https://corp-gateway.example.com", http_opts
assert getattr(http_opts, "api_version", "") == "v1", http_opts
assert fake_subprocess_calls == ["helix auth access-token print -a"], \
    fake_subprocess_calls
print("[PASS] vertex+command wired Client(vertexai=True, ..., http_options=...)")


# ===========================================================================
# Test 2: _CommandCredentials.refresh() re-runs the command
# ===========================================================================
fake_subprocess_calls.clear()
fake_subprocess_calls_seq = iter([
    "token-v1\n",
    "token-v2\n",
])


def fake_check_output_seq(cmd: str, **_: Any) -> str:
    fake_subprocess_calls.append(cmd)
    return next(fake_subprocess_calls_seq)


gx.subprocess.check_output = fake_check_output_seq  # type: ignore[assignment]

cc = gx._CommandCredentials("dummy-cmd")
assert cc.token == "token-v1", cc.token
cc.refresh(None)
assert cc.token == "token-v2", cc.token
assert fake_subprocess_calls == ["dummy-cmd", "dummy-cmd"], fake_subprocess_calls
# Expiry should be in the future (TTL ~50 minutes)
import datetime as _dt
assert cc.expiry is not None
delta = cc.expiry - _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
assert _dt.timedelta(minutes=40) < delta <= _dt.timedelta(minutes=50), delta
print("[PASS] _CommandCredentials refresh() re-runs command + sets expiry")


# ===========================================================================
# Test 3: vertex.enabled but missing project -> LLMConfigError
# ===========================================================================
raised = False
try:
    make_llm_client(
        provider="gemini",
        api_key=None,
        extra={"vertex": {"enabled": True, "location": "us-central1"}},
    )
except LLMConfigError as exc:
    raised = True
    assert "project" in str(exc).lower(), exc
assert raised, "missing project should raise LLMConfigError"
print("[PASS] missing vertex.project raises LLMConfigError")


# ===========================================================================
# Test 4: credentials_command + credentials_file together -> LLMConfigError
# ===========================================================================
raised = False
try:
    make_llm_client(
        provider="gemini",
        api_key=None,
        extra={
            "vertex": {
                "enabled": True,
                "project": "p",
                "location": "us-central1",
                "credentials_command": "x",
                "credentials_file": "/tmp/sa.json",
            },
        },
    )
except LLMConfigError as exc:
    raised = True
    assert "command" in str(exc).lower() and "file" in str(exc).lower()
assert raised, "command+file together should raise"
print("[PASS] credentials_command + credentials_file together -> error")


# ===========================================================================
# Test 5: empty credentials_command stdout -> LLMConfigError
# ===========================================================================
gx.subprocess.check_output = (
    lambda *a, **k: ""  # type: ignore[assignment]
)
raised = False
try:
    make_llm_client(
        provider="gemini",
        api_key=None,
        extra={
            "vertex": {
                "enabled": True,
                "project": "p",
                "location": "us-central1",
                "credentials_command": "echo nothing",
            },
        },
    )
except LLMConfigError as exc:
    raised = True
    assert "empty" in str(exc).lower(), exc
assert raised, "empty stdout should raise"
print("[PASS] empty credentials_command stdout raises LLMConfigError")


# ===========================================================================
# Test 6: factory.py loosens GEMINI_API_KEY check when vertex enabled
# ===========================================================================
import os as _os
_saved = _os.environ.pop("GEMINI_API_KEY", None)
gx.subprocess.check_output = fake_check_output  # type: ignore[assignment]
try:
    c = make_llm_client(
        provider="gemini",
        api_key=None,
        extra={
            "vertex": {
                "enabled": True,
                "project": "p",
                "location": "us-central1",
                "credentials_command": "x",
            },
        },
    )
    assert c.provider == "gemini"
finally:
    if _saved is not None:
        _os.environ["GEMINI_API_KEY"] = _saved
print("[PASS] factory skips GEMINI_API_KEY when vertex.enabled")


# ===========================================================================
# Test 7: vertex key is consumed -- doesn't leak into self._extra
# ===========================================================================
c = make_llm_client(
    provider="gemini",
    api_key=None,
    extra={
        "vertex": {
            "enabled": True,
            "project": "p",
            "location": "us-central1",
            "credentials_command": "x",
        },
        "safety_settings": [{"category": "X", "threshold": "Y"}],
    },
)
# _extra is private; reach in for the probe assertion only.
extra = getattr(c, "_extra", {})
assert "vertex" not in extra, f"vertex should be popped; got {extra}"
assert "safety_settings" in extra, f"other extras must remain; got {extra}"
print("[PASS] vertex key popped; other extras preserved")


# ===========================================================================
# Test 8: vertex.enabled=false -> normal API-key path (api_key still required)
# ===========================================================================
raised = False
try:
    make_llm_client(
        provider="gemini",
        api_key=None,
        extra={"vertex": {"enabled": False}},
    )
except LLMConfigError as exc:
    raised = True
    assert "GEMINI_API_KEY" in str(exc), exc
assert raised, "vertex.enabled=False should still require api_key"
print("[PASS] vertex.enabled=False falls back to API-key requirement")


# Restore real SDK Client + subprocess.
gx.genai.Client = _real_genai_client  # type: ignore[assignment]
gx.subprocess.check_output = real_check_output  # type: ignore[assignment]

print("\nOK -- Vertex corporate mode wiring verified.")
