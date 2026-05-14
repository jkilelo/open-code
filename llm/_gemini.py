"""Google Gemini adapter (google-genai SDK).

Translates between open-code's neutral types and google.genai.types
on every call. The only file in the package that imports
`from google import genai`. The factory keeps it lazy so users on
other providers don't need google-genai installed.

Two auth modes, picked at construction time:

  1. Gemini Developer API (default): api_key from AI Studio.
  2. Vertex AI (corporate): extra={"vertex": {...}}. Lets you run
     against a corporate gateway with OAuth2 access tokens fetched
     from a shell command (e.g. `helix auth access-token print -a`),
     a service-account JSON file, or Application Default Credentials.

SDK reference: google-genai 2.1.0 (verified 2026-05-12).
"""
from __future__ import annotations

import datetime
import json
import subprocess
from typing import Any, Iterator

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as _gt

from .base import BaseLLMClient, StreamAccumulator
from .errors import (
    LLMAuthenticationError, LLMBadRequestError, LLMCallError, LLMConfigError,
    LLMNotFoundError, LLMPermissionError, LLMRateLimitError,
    LLMSafetyError, LLMServerError,
)
from .types import AskResult, Message, Part, StreamChunk, ToolDecl, Usage


# Default OAuth2 scope when Vertex mode is enabled. Corporate setups
# almost always want cloud-platform; surface the override anyway.
_DEFAULT_VERTEX_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/cloud-platform",
)

# How long a Vertex access token from a shell command is presumed to
# last. Google access tokens are 1h by default; we expire ours a bit
# earlier so google-auth refreshes proactively before a 401.
_COMMAND_TOKEN_TTL = datetime.timedelta(minutes=50)


# thinking_effort -> Gemini 3.x ThinkingLevel enum
_EFFORT_LEVEL_MAP = {
    "off": "MINIMAL", "minimal": "MINIMAL", "low": "LOW",
    "medium": "MEDIUM", "high": "HIGH", "max": "HIGH",
}

# thinking_effort -> Gemini 2.5 thinking_budget (Flash variants)
_EFFORT_BUDGETS_2_5_FLASH = {
    "off": 0, "minimal": 256, "low": 2048,
    "medium": 8192, "high": 16384, "max": 24576,
}

# thinking_effort -> Gemini 2.5 thinking_budget (Pro: can't disable)
_EFFORT_BUDGETS_2_5_PRO = {
    "off": 128, "minimal": 256, "low": 2048,
    "medium": 8192, "high": 16384, "max": 32768,
}


# Safety-block finish reasons -- adapter raises LLMSafetyError when
# the model emits any of these.
_SAFETY_FINISH = frozenset({
    "SAFETY", "RECITATION", "PROHIBITED_CONTENT",
    "SPII", "IMAGE_SAFETY", "BLOCKLIST",
})


def _resolve_vertex_credentials(
    cfg: dict[str, Any], scopes: list[str] | tuple[str, ...],
) -> Any:
    """Pick the right google.auth.credentials.Credentials for Vertex mode.

    Returns None to let google-auth fall back to Application Default
    Credentials (ADC). Raises LLMConfigError on misconfiguration.
    """
    cmd = cfg.get("credentials_command")
    sa_file = cfg.get("credentials_file")

    if cmd and sa_file:
        raise LLMConfigError(
            'vertex config: choose either "credentials_command" or '
            '"credentials_file", not both.'
        )

    scope_list = list(scopes)
    if cmd:
        if not isinstance(cmd, str) or not cmd.strip():
            raise LLMConfigError(
                'vertex.credentials_command must be a non-empty shell '
                'command string (e.g. "helix auth access-token print -a").'
            )
        return _CommandCredentials(cmd.strip(), scopes=scope_list)

    if sa_file:
        try:
            from google.oauth2 import service_account
        except ImportError as exc:
            raise LLMConfigError(
                "vertex.credentials_file requires google-auth's "
                "service_account module; install google-auth."
            ) from exc
        return service_account.Credentials.from_service_account_file(
            sa_file, scopes=scope_list,
        )

    # ADC: returning None tells genai.Client to call google.auth.default().
    return None


def _build_http_options(cfg: dict[str, Any]) -> "_gt.HttpOptions | None":
    """Translate vertex.* HTTP knobs into a types.HttpOptions, or None.

    Recognized keys (all optional):
      base_url, api_version, headers, timeout, base_url_resource_scope
    """
    keys = (
        "base_url", "api_version", "headers", "timeout",
        "base_url_resource_scope",
    )
    opts = {k: cfg[k] for k in keys if cfg.get(k) is not None}
    if not opts:
        return None
    try:
        return _gt.HttpOptions(**opts)
    except TypeError as exc:
        # SDK may not know one of these on older versions -- drop the
        # unknown key and retry once with a clear hint to the user.
        raise LLMConfigError(
            f"vertex http_options rejected by google-genai: {exc}. "
            f"Keys passed: {sorted(opts)}. Upgrade google-genai or "
            f"remove the unsupported key."
        ) from exc


class _CommandCredentials:
    """OAuth2 credentials backed by a shell command.

    Mirrors the corporate pattern:
        Credentials(subprocess.check_output("helix auth access-token "
                                            "print -a", shell=True)
                    .decode().strip())

    Subclasses `google.oauth2.credentials.Credentials` so the
    google-auth transport treats it like any other refreshable
    credential. We override refresh() to re-run the shell command
    when google-auth detects the token is near expiry, so long
    REPL sessions don't 401 after the initial 1h.
    """

    def __new__(
        cls, command: str, *, scopes: list[str] | None = None,
    ) -> "_CommandCredentials":
        # Lazy-import + dynamic subclass so importing this module
        # never requires google-auth-oauthlib for the Developer-API
        # path. Cache the resolved subclass on the class for reuse.
        impl = getattr(cls, "_impl_cls", None)
        if impl is None:
            try:
                from google.oauth2.credentials import Credentials
            except ImportError as exc:
                raise LLMConfigError(
                    "vertex.credentials_command requires google-auth "
                    "(google.oauth2.credentials.Credentials)."
                ) from exc

            class _Impl(Credentials):
                def __init__(
                    self, command: str, *, scopes: list[str] | None = None,
                ) -> None:
                    super().__init__(token=None, scopes=scopes)
                    self._command = command
                    self._fetch()  # initial fetch so .token is set

                def _fetch(self) -> None:
                    try:
                        out = subprocess.check_output(
                            self._command, shell=True, text=True,
                            stderr=subprocess.PIPE,
                        )
                    except subprocess.CalledProcessError as exc:
                        stderr = (exc.stderr or "").strip()[:400]
                        raise LLMConfigError(
                            f"vertex.credentials_command exited "
                            f"{exc.returncode}: {self._command!r}. "
                            f"stderr: {stderr!r}"
                        ) from exc
                    except FileNotFoundError as exc:
                        raise LLMConfigError(
                            f"vertex.credentials_command not found: "
                            f"{self._command!r} ({exc})"
                        ) from exc
                    token = (out or "").strip()
                    if not token:
                        raise LLMConfigError(
                            f"vertex.credentials_command produced empty "
                            f"output: {self._command!r}"
                        )
                    self.token = token
                    # google-auth compares expiry to a naive UTC clock,
                    # so we strip tzinfo after computing on aware now().
                    self.expiry = (
                        datetime.datetime.now(datetime.timezone.utc)
                        .replace(tzinfo=None) + _COMMAND_TOKEN_TTL
                    )

                def refresh(self, request: Any) -> None:  # noqa: ARG002
                    self._fetch()

            cls._impl_cls = _Impl  # type: ignore[attr-defined]
            impl = _Impl
        return impl(command, scopes=scopes)  # type: ignore[return-value]


class GeminiClient(BaseLLMClient):
    """Adapter implementing LLMClient against google-genai 2.x.

    Construction has two paths:

      - API-key (default):
            GeminiClient(api_key="AI...", extra={...})
        Hits generativelanguage.googleapis.com via the Developer API.

      - Vertex AI (corporate):
            GeminiClient(api_key=None, extra={"vertex": {
                "enabled": True,
                "project": "my-gcp-project",
                "location": "us-central1",            # or "global"
                "base_url": "https://corp-gw...",     # optional, gateway
                "api_version": "v1",                   # optional
                "headers": {"X-Tenant": "..."},       # optional
                "credentials_command": "helix auth access-token print -a",
                # OR: "credentials_file": "/path/to/service-account.json"
                # OR: omit both -> fall back to Application Default Credentials
                "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
            }})
        Mirrors the corporate snippet:
          Client(vertexai=True, project=..., location=..., credentials=...,
                 http_options=types.HttpOptions(base_url=...))
        The `vertex` block is consumed at construction and removed
        from `_extra` so it never leaks into per-call coercion.
    """

    provider: str = "gemini"

    def __init__(
        self, *, api_key: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._extra = dict(extra) if extra else {}
        vertex_cfg = self._extra.pop("vertex", None)
        if isinstance(vertex_cfg, dict) and vertex_cfg.get("enabled"):
            self._client = self._build_vertex_client(vertex_cfg)
        else:
            if not api_key:
                raise LLMConfigError(
                    "GeminiClient: api_key required for the Developer API "
                    "path. For corporate Vertex AI, pass "
                    'extra={"vertex": {"enabled": True, ...}}.'
                )
            self._client = genai.Client(api_key=api_key)

    @staticmethod
    def _build_vertex_client(cfg: dict[str, Any]) -> "genai.Client":
        """Construct a Vertex-mode genai.Client from a vertex.* config dict.

        Required: project, location.
        Credentials precedence (most explicit first):
          1. credentials_command  -- run shell command, use stdout as
             access token (subclass refresh() re-runs it as token ages)
          2. credentials_file     -- service account JSON, scoped
          3. neither              -- google.auth.default() (ADC)
        """
        project = cfg.get("project")
        location = cfg.get("location") or "us-central1"
        if not project:
            raise LLMConfigError(
                'vertex config requires "project" '
                "(your GCP project ID for quota)."
            )

        scopes: list[str] = [
            str(s) for s in (cfg.get("scopes") or _DEFAULT_VERTEX_SCOPES)
        ]
        credentials = _resolve_vertex_credentials(cfg, scopes)

        client_kwargs: dict[str, Any] = {
            "vertexai": True,
            "project": project,
            "location": location,
        }
        if credentials is not None:
            client_kwargs["credentials"] = credentials

        http_opts = _build_http_options(cfg)
        if http_opts is not None:
            client_kwargs["http_options"] = http_opts

        return genai.Client(**client_kwargs)

    # ---- adapter hooks ----

    def _ask_impl(self, **kwargs: Any) -> AskResult:
        params = self._coerce_params(**kwargs)
        resp = self._client.models.generate_content(
            model=params["model"],
            contents=params["contents"],
            config=params["config"],
        )
        return self._to_ask_result(resp)

    def _ask_stream_impl(self, **kwargs: Any) -> Iterator[StreamChunk]:
        params = self._coerce_params(**kwargs)
        acc = StreamAccumulator()
        safety_block = ""

        stream = self._client.models.generate_content_stream(
            model=params["model"],
            contents=params["contents"],
            config=params["config"],
        )

        for chunk in stream:
            cands = getattr(chunk, "candidates", None) or []
            for cand in cands:
                content = getattr(cand, "content", None)
                if content is not None:
                    for gp in (content.parts or []):
                        yield from self._stream_part(gp, acc)

                fr = getattr(cand, "finish_reason", None)
                if fr is not None:
                    fr_name = getattr(fr, "name", str(fr))
                    if fr_name in _SAFETY_FINISH:
                        safety_block = fr_name
                    acc.set_stop_reason(fr_name)

            meta = getattr(chunk, "usage_metadata", None)
            if meta is not None:
                acc.set_usage(self._usage_from_meta(meta))

        if safety_block:
            raise LLMSafetyError(
                f"gemini blocked output ({safety_block})",
                reason=safety_block,
            )
        yield acc.final_chunk()

    def _embed_impl(
        self, *, model: str, texts: list[str],
        task_type: str = "", output_dimensionality: int | None = None,
    ) -> list[list[float]]:
        cfg_kwargs: dict[str, Any] = {}
        if task_type:
            cfg_kwargs["task_type"] = task_type
        if output_dimensionality is not None:
            cfg_kwargs["output_dimensionality"] = output_dimensionality
        cfg = _gt.EmbedContentConfig(**cfg_kwargs) if cfg_kwargs else None

        out: list[list[float]] = []
        for t in texts:
            kwargs: dict[str, Any] = {"model": model, "contents": t}
            if cfg is not None:
                kwargs["config"] = cfg
            try:
                resp = self._client.models.embed_content(**kwargs)
            except Exception:
                out.append([])
                continue
            out.append(self._extract_embedding(resp))
        return out

    # ---- neutral -> native coercion ----

    def _coerce_params(self, **kwargs: Any) -> dict[str, Any]:
        contents = [self._to_content(m) for m in kwargs["messages"]]
        return {
            "model": kwargs["model"],
            "contents": contents,
            "config": self._build_config(kwargs),
        }

    def _build_config(self, kw: dict[str, Any]) -> "_gt.GenerateContentConfig":
        cfg: dict[str, Any] = {}
        if kw.get("system_instruction"):
            cfg["system_instruction"] = kw["system_instruction"]
        for k_src, k_dst in (
            ("temperature", "temperature"),
            ("top_p", "top_p"),
            ("top_k", "top_k"),
            ("max_output_tokens", "max_output_tokens"),
            ("seed", "seed"),
            ("presence_penalty", "presence_penalty"),
            ("frequency_penalty", "frequency_penalty"),
            ("candidate_count", "candidate_count"),
        ):
            v = kw.get(k_src)
            if v is not None:
                cfg[k_dst] = v
        if kw.get("stop_sequences"):
            cfg["stop_sequences"] = list(kw["stop_sequences"])

        # Tools
        tools = kw.get("tools") or []
        if tools:
            cfg["tools"] = self._tools_to_native(tools)
        tc = kw.get("tool_choice")
        if tc is not None:
            cfg["tool_config"] = self._tool_choice_to_native(tc)
        # AFC: always disable -- open-code dispatches tools itself.
        cfg["automatic_function_calling"] = _gt.AutomaticFunctionCallingConfig(
            disable=True,
        )

        # Thinking
        thinking_cfg = self._thinking_to_native(
            kw["model"], kw.get("thinking_effort"),
            kw.get("thinking_budget"), bool(kw.get("include_thinking")),
        )
        if thinking_cfg is not None:
            cfg["thinking_config"] = thinking_cfg

        # Structured output
        if kw.get("response_mime_type"):
            cfg["response_mime_type"] = kw["response_mime_type"]
        if kw.get("response_schema") is not None:
            cfg["response_schema"] = kw["response_schema"]
            if not cfg.get("response_mime_type"):
                cfg["response_mime_type"] = "application/json"

        # Metadata -> Vertex `labels` (only place Gemini has for this)
        if kw.get("metadata") and "labels" not in cfg:
            cfg["labels"] = {
                str(k): str(v) for k, v in (kw["metadata"] or {}).items()
            }

        # Provider-specific knobs through extra={}
        extra = dict(kw.get("extra") or {})
        for k in (
            "safety_settings", "cached_content", "routing_config",
            "media_resolution", "service_tier", "speech_config",
            "response_logprobs", "logprobs", "audio_timestamp",
            "labels", "http_options",
        ):
            if k in extra:
                cfg[k] = extra.pop(k)

        return _gt.GenerateContentConfig(**cfg)

    def _to_content(self, msg: Message) -> "_gt.Content":
        parts: list[_gt.Part] = []
        for p in msg.parts:
            if p.is_text() and p.text:
                gp = _gt.Part.from_text(text=p.text)
                self._restore_signature(gp, p)
                parts.append(gp)
            elif p.is_tool_call():
                gp = _gt.Part(
                    function_call=_gt.FunctionCall(
                        id=p.tool_call_id or None,
                        name=p.tool_name,
                        args=dict(p.tool_args) if p.tool_args else {},
                    ),
                )
                self._restore_signature(gp, p)
                parts.append(gp)
            elif p.is_tool_result():
                # function_response parts don't carry thought_signature
                parts.append(_gt.Part.from_function_response(
                    name=p.tool_name,
                    response=dict(p.tool_result) if p.tool_result else {},
                ))
            elif p.is_thinking():
                # Echo thinking summary back so Gemini reconstructs
                # the reasoning chain on the followup turn.
                if p.text:
                    gp = _gt.Part.from_text(text=p.text)
                    try:
                        gp.thought = True
                    except AttributeError:
                        pass
                    self._restore_signature(gp, p)
                    parts.append(gp)
            elif p.is_image():
                if p.image_data:
                    parts.append(_gt.Part.from_bytes(
                        data=p.image_data,
                        mime_type=p.image_mime or "image/png",
                    ))
                elif p.image_url:
                    parts.append(_gt.Part.from_uri(
                        file_uri=p.image_url,
                        mime_type=p.image_mime or "image/png",
                    ))
                elif p.image_file_id:
                    parts.append(_gt.Part.from_uri(
                        file_uri=p.image_file_id,
                        mime_type=p.image_mime or "image/png",
                    ))

        # Map "model" stays "model"; "tool" -> "user" (Gemini sends
        # tool results back via the user role).
        role = "user" if msg.role == "tool" else msg.role
        return _gt.Content(role=role, parts=parts)

    @staticmethod
    def _restore_signature(gp: "_gt.Part", p: Part) -> None:
        sig = p.extra.get("thought_signature")
        if sig is None:
            return
        try:
            gp.thought_signature = sig
        except AttributeError:
            pass  # older SDK

    @staticmethod
    def _tools_to_native(tools: list[ToolDecl]) -> list:
        out_custom: list[dict[str, Any]] = []
        out_builtin: list = []
        for t in tools:
            if t.builtin:
                if t.builtin == "google_search":
                    out_builtin.append(_gt.Tool(google_search=_gt.GoogleSearch()))
                elif t.builtin == "code_execution":
                    try:
                        out_builtin.append(_gt.Tool(
                            code_execution=_gt.ToolCodeExecution(),
                        ))
                    except AttributeError:
                        pass
                elif t.builtin == "url_context":
                    try:
                        out_builtin.append(_gt.Tool(url_context=_gt.UrlContext()))
                    except AttributeError:
                        pass
                # else: silently ignore unknown built-in
                continue
            out_custom.append({
                "name": t.name,
                "description": t.description,
                "parameters": dict(t.parameters) if t.parameters else {},
            })
        result: list = []
        if out_custom:
            result.append(_gt.Tool(function_declarations=out_custom))
        result.extend(out_builtin)
        return result

    @staticmethod
    def _tool_choice_to_native(tc: Any) -> "_gt.ToolConfig":
        if isinstance(tc, str):
            mode = {
                "auto": "AUTO", "any": "ANY", "required": "ANY",
                "none": "NONE",
            }.get(tc.lower(), "AUTO")
            return _gt.ToolConfig(
                function_calling_config=_gt.FunctionCallingConfig(mode=mode),
            )
        if isinstance(tc, dict):
            if tc.get("type") == "tool" and tc.get("name"):
                return _gt.ToolConfig(
                    function_calling_config=_gt.FunctionCallingConfig(
                        mode="ANY",
                        allowed_function_names=[tc["name"]],
                    ),
                )
        return _gt.ToolConfig(
            function_calling_config=_gt.FunctionCallingConfig(mode="AUTO"),
        )

    @staticmethod
    def _thinking_to_native(
        model: str, effort: str | None, budget: int | None, include: bool,
    ) -> "_gt.ThinkingConfig | None":
        if effort is None and budget is None and not include:
            return None
        kwargs: dict[str, Any] = {}
        if include:
            kwargs["include_thoughts"] = True

        ml = (model or "").lower()
        is_gemini_3 = "gemini-3" in ml
        if is_gemini_3:
            lvl = _EFFORT_LEVEL_MAP.get(effort or "medium", "MEDIUM")
            kwargs["thinking_level"] = lvl
        else:
            is_pro = "pro" in ml
            table = _EFFORT_BUDGETS_2_5_PRO if is_pro else _EFFORT_BUDGETS_2_5_FLASH
            b = budget
            if b is None and effort is not None:
                b = table.get(effort, table["medium"])
            if b is not None:
                kwargs["thinking_budget"] = b
        try:
            return _gt.ThinkingConfig(**kwargs)
        except (TypeError, AttributeError):
            return None

    # ---- native -> neutral coercion ----

    def _to_ask_result(self, resp: Any) -> AskResult:
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            pf = getattr(resp, "prompt_feedback", None)
            block = getattr(pf, "block_reason", None) if pf else None
            if block:
                raise LLMSafetyError(
                    f"gemini blocked prompt ({block})", reason=str(block),
                )
            raise LLMCallError("gemini returned no candidates")
        cand = cands[0]
        content = getattr(cand, "content", None)
        if content is None:
            raise LLMCallError("gemini candidate has no content")

        fr = getattr(cand, "finish_reason", None)
        fr_name = getattr(fr, "name", str(fr)) if fr is not None else ""
        if fr_name in _SAFETY_FINISH:
            raise LLMSafetyError(
                f"gemini blocked output ({fr_name})", reason=fr_name,
            )

        message = self._from_content(content)
        usage = self._usage_from_meta(getattr(resp, "usage_metadata", None))
        stop = self.normalize_stop_reason(fr_name) if fr_name else "stop"
        return AskResult(message=message, usage=usage, stop_reason=stop, raw=resp)

    @staticmethod
    def _from_content(content: Any) -> Message:
        parts: list[Part] = []
        for gp in content.parts or []:
            fc = getattr(gp, "function_call", None)
            fr = getattr(gp, "function_response", None)
            text = getattr(gp, "text", None) or ""
            thought = bool(getattr(gp, "thought", False))
            sig = getattr(gp, "thought_signature", None)
            extra = {"thought_signature": sig} if sig is not None else None

            if fc is not None and getattr(fc, "name", None):
                parts.append(Part.make_tool_call(
                    fc.name,
                    dict(fc.args) if fc.args else {},
                    tool_call_id=getattr(fc, "id", "") or "",
                    extra=extra,
                ))
            elif fr is not None and getattr(fr, "name", None):
                parts.append(Part.make_tool_result(
                    fr.name,
                    dict(fr.response) if fr.response else {},
                    tool_call_id=getattr(fr, "id", "") or "",
                ))
            elif thought and text:
                parts.append(Part.make_thinking(text, signature=sig))
            elif text:
                p = Part.make_text(text)
                if sig is not None:
                    # Gemini 3 puts signatures on text parts -- stash
                    p.extra["thought_signature"] = sig
                parts.append(p)
        return Message(role="model", parts=parts)

    @staticmethod
    def _usage_from_meta(meta: Any) -> Usage:
        if meta is None:
            return Usage()
        cached = (
            getattr(meta, "cached_content_input_token_count", 0)
            or getattr(meta, "cached_content_token_count", 0)
            or 0
        )
        return Usage(
            input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
            output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
            reasoning_tokens=getattr(meta, "thoughts_token_count", 0) or 0,
            cached_input_tokens=cached,
        )

    @staticmethod
    def _extract_embedding(resp: Any) -> list[float]:
        embs = getattr(resp, "embeddings", None)
        if embs:
            values = getattr(embs[0], "values", None)
            if values:
                return list(values)
        emb = getattr(resp, "embedding", None)
        if emb is not None:
            values = getattr(emb, "values", None)
            if values:
                return list(values)
        return []

    def _stream_part(
        self, gp: Any, acc: StreamAccumulator,
    ) -> Iterator[StreamChunk]:
        """Convert one streamed Gemini Part into 0+ StreamChunks
        and feed the accumulator."""
        fc = getattr(gp, "function_call", None)
        text = getattr(gp, "text", None) or ""
        thought = bool(getattr(gp, "thought", False))
        sig = getattr(gp, "thought_signature", None)
        if sig is not None:
            acc.set_signature(sig)

        if fc is not None and getattr(fc, "name", None):
            # Gemini streams complete function_call parts in one shot,
            # not as JSON-arg deltas. Pre-serialize args; accumulator
            # parses on build.
            idx = acc.tool_call_count
            acc.start_tool_call(
                idx,
                call_id=getattr(fc, "id", "") or "",
                name=fc.name,
            )
            args_str = json.dumps(dict(fc.args) if fc.args else {})
            acc.add_tool_call_args(idx, args_str)
            if sig is not None:
                acc.set_tool_call_extra(idx, {"thought_signature": sig})
            return
        if text:
            if thought:
                yield acc.add_thinking(text)
            else:
                yield acc.add_text(text)

    # ---- error translation ----

    def _translate_error(self, exc: Exception) -> Exception:
        if isinstance(exc, genai_errors.ClientError):
            code = getattr(exc, "code", None) or 0
            msg = f"gemini: {exc}"
            if code == 401:
                return LLMAuthenticationError(msg)
            if code == 403:
                return LLMPermissionError(msg)
            if code == 404:
                return LLMNotFoundError(msg)
            if code == 429:
                return LLMRateLimitError(msg)
            return LLMBadRequestError(msg)
        if isinstance(exc, genai_errors.ServerError):
            return LLMServerError(f"gemini: {exc}")
        return super()._translate_error(exc)

    # ---- escape hatch ----

    @property
    def raw_client(self) -> Any:
        """Power users who need direct SDK access (unsupported features
        like Live API, batch API, custom endpoints) can reach the
        underlying genai.Client. Most code should NOT touch this --
        if a feature can be expressed through the protocol, do that."""
        return self._client
