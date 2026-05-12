# LLM-agnostic layer redesign -- 3-provider comparison (2026-05-12)

Source SDKs (latest verified today):
- **google-genai 2.1.0** (Python 3.10+) -- uses `client.models.generate_content`
- **anthropic 0.101.0** (Python 3.9+) -- uses `client.messages.create`
- **openai 2.36.0** (Python 3.9+) -- uses `client.responses.create` (modern) or `client.chat.completions.create` (legacy)

OpenAI's Responses API is the primary path for new code (launched 2025-03; first-class
agents, server-side state, built-in tools, persistent reasoning). Chat Completions stays
as a fallback for OSS-compat providers and Azure.

---

## 1. Parameter overlap matrix

Legend: [OK] native, ? maps via adapter, [NO] unsupported (ignored).

| Neutral kwarg                | Gemini                                 | Anthropic                                | OpenAI Responses             | OpenAI Chat                       |
|------------------------------|----------------------------------------|------------------------------------------|------------------------------|-----------------------------------|
| `model`                      | [OK]                                      | [OK]                                        | [OK]                            | [OK]                                 |
| `messages` (neutral)         | ? -> `contents`                         | ? -> `messages`                           | ? -> `input`                  | ? -> `messages`                    |
| `system_instruction`         | [OK] `system_instruction`                 | [OK] `system`                               | [OK] `instructions`             | ? role=system in messages         |
| `max_output_tokens`          | [OK]                                      | [OK] `max_tokens` (REQUIRED)                | [OK]                            | [OK] `max_completion_tokens`         |
| `temperature`                | [OK] (0..2)                               | [OK] (0..1) -- clamp                         | [OK] (0..2)                     | [OK] (0..2)                          |
| `top_p`                      | [OK]                                      | [OK]                                        | [OK]                            | [OK]                                 |
| `top_k`                      | [OK]                                      | [OK]                                        | [NO]                            | [NO]                                 |
| `stop_sequences`             | [OK]                                      | [OK]                                        | [NO]                            | [OK] `stop`                          |
| `seed`                       | [OK]                                      | [NO]                                        | [NO]                            | [OK]                                 |
| `presence_penalty`           | [OK]                                      | [NO]                                        | [NO]                            | [OK]                                 |
| `frequency_penalty`          | [OK]                                      | [NO]                                        | [NO]                            | [OK]                                 |
| `candidate_count` (`n`)      | [OK]                                      | [NO]                                        | [NO]                            | [OK] `n`                             |
| `metadata`                   | [NO]                                      | ? `{user_id}` only                       | [OK]                            | [OK]                                 |
| `user` / `safety_identifier` | [NO]                                      | metadata.user_id                          | [OK] both                       | [OK] both                            |
| `tools`                      | [OK]                                      | [OK]                                        | [OK]                            | [OK]                                 |
| `tool_choice`                | [OK] via `ToolConfig.mode`                | [OK]                                        | [OK]                            | [OK]                                 |
| `parallel_tool_calls`        | implicit                                | [OK] `disable_parallel_tool_use` (inverse)  | [OK]                            | [OK]                                 |
| `response_schema`            | [OK] `response_schema` + mime json        | [OK] `output_config.format.json_schema`     | [OK] `text.format.json_schema`  | [OK] `response_format.json_schema`   |
| `thinking_effort`            | ? `thinking_level` (3.x) / budget (2.5)| ? `thinking.budget_tokens` / `adaptive`  | [OK] `reasoning.effort`         | [OK] `reasoning_effort`              |
| `thinking_budget` (int)      | [OK] (2.5 only)                           | [OK] (when type=enabled)                    | [NO] (effort string only)       | [NO]                                 |
| `include_thinking`           | [OK] `include_thoughts`                   | [OK] `display="summarized"`                 | [OK] `reasoning.summary`        | hidden                             |

### Sampling-param coverage by provider

- **Universal (all 4 endpoints):** `temperature`, `top_p`, `max_output_tokens`, `tools`, `tool_choice`, `response_schema`, `system_instruction` (in some shape).
- **3-of-4:** `stop_sequences` (no Responses), `top_k` (no OpenAI either way).
- **Gemini+Chat only:** `seed`, `presence_penalty`, `frequency_penalty`, `candidate_count`/`n`.

**Design call:** keep all in the protocol. Adapters silently drop the unsupported ones rather than raising -- the user expects "pass whatever you want, the adapter does its best." A `strict_params=True` mode could opt into raising; default lenient.

---

## 2. Message / content-block shape

Every provider has roughly the same shape but different names.

| Concept          | Gemini                        | Anthropic                                       | OpenAI Responses                          | OpenAI Chat                                |
|------------------|-------------------------------|-------------------------------------------------|-------------------------------------------|--------------------------------------------|
| Container        | `Content(role, parts=[Part])` | `{"role", "content": [Block]}`                  | input items list (incl. `message` items)  | `{"role", "content"}`                      |
| Roles            | `user` / `model`              | `user` / `assistant`                            | `user`/`assistant`/`system`/`developer`   | `user`/`assistant`/`system`/`developer`/`tool` |
| Text             | `Part(text="...")`            | `{"type":"text","text":...}`                    | `{"type":"input_text","text":...}` (user) / `{"type":"output_text",...}` (assistant) | `{"type":"text","text":...}` or plain str  |
| Image            | `Part.from_bytes(b, mime)`    | `{"type":"image","source":{...}}`               | `{"type":"input_image","image_url":...}`  | `{"type":"image_url","image_url":{url,detail}}` |
| Tool call        | `Part(function_call=FC(id,name,args))` | `{"type":"tool_use","id","name","input"}` | `{"type":"function_call","call_id","name","arguments"}` | `tool_calls[i]={"id","type","function":{name,arguments(JSON str)}}` |
| Tool result      | `Part.from_function_response(id,name,response)` | `{"type":"tool_result","tool_use_id","content","is_error?"}` | `{"type":"function_call_output","call_id","output"}` | `{"role":"tool","tool_call_id","content"}` |
| Reasoning/thinking | `Part(thought=True, text=...)`+`thought_signature` (bytes) on every part | `{"type":"thinking","thinking","signature"}` or `{"type":"redacted_thinking","data"}` | reasoning items (encrypted_content) | hidden |
| Document/PDF     | inline / Files API            | `{"type":"document","source":{...}}`            | `{"type":"input_file","file_id"}`         | `{"type":"file","file":{file_id}}`         |

### Neutral `Part` design

A flat dataclass with a `kind` discriminator. Adds vs the current shape:
- `tool_call_id` (unified -- replaces ad-hoc storage in `extra`)
- `kind="image"` with `image_data`/`image_mime`/`image_url`/`image_file_id`
- `kind="thinking"` with `text` (the summary) and `extra["signature"]` (bytes/str)
- `is_error: bool` for tool_result

Tool-call IDs: **Anthropic and OpenAI always carry one; Gemini only needs one for parallel calls but the SDK accepts it always.** Adapters always emit + always echo back -- uniform behavior.

---

## 3. Streaming

Wildly different at the SDK level, identical conceptually.

| Aspect                  | Gemini                                       | Anthropic                                          | OpenAI Responses                                   | OpenAI Chat                                          |
|-------------------------|----------------------------------------------|----------------------------------------------------|----------------------------------------------------|------------------------------------------------------|
| Entry                   | `generate_content_stream(...)` (iterator)    | `messages.stream(...)` (ctx) or `create(stream=)`  | `responses.stream(...)` (ctx) or `create(stream=)` | `chat.completions.create(stream=True)` or `.stream()` |
| Event model             | Same `GenerateContentResponse` chunks        | Typed events (`message_start`, `content_block_*`, `message_delta`, `message_stop`, `ping`) | Typed events (`response.created`, `response.output_text.delta`, `response.function_call_arguments.delta`, ...) | Chunks with `choices[0].delta` |
| Text delta              | `chunk.candidates[0].content.parts[i].text`  | `text_delta` events                                | `response.output_text.delta`                       | `delta.content`                                      |
| Tool-call args streaming| Whole-arg parts arrive in chunks             | `input_json_delta.partial_json` -> parse on `content_block_stop` | `response.function_call_arguments.delta` -> parse on `done` | `delta.tool_calls[i].function.arguments` partials   |
| Thinking deltas         | `part.thought=True` text                     | `thinking_delta` + `signature_delta`               | `response.reasoning_text.delta`                    | hidden                                               |
| Usage delivery          | Final chunk reliably populated               | `message_delta.usage` (cumulative, gotcha)         | `response.completed` carries full usage            | Only with `stream_options.include_usage`             |
| Stop reason             | `candidate.finish_reason` enum               | `message_delta.stop_reason`                        | `response.completed.status` / item.status         | `choices[0].finish_reason` on last chunk             |

**Shared base machinery:** a `StreamAccumulator` helper class that adapters call with normalized hooks -- `add_text_delta(s)`, `start_tool_call(idx,id,name)`, `add_tool_arg_delta(idx,partial)`, `end_tool_call(idx)`, `add_thinking_delta(s)`, `set_signature(sig)`, `set_usage(u)`, `set_stop_reason(r)`. The accumulator emits neutral `StreamChunk`s as deltas arrive and synthesizes the final `Message`. Eliminates ~150 lines of duplicated assembly code per adapter.

---

## 4. Thinking / reasoning -- three model families, one knob

| Provider     | Native shape                                                                                  | Neutral mapping                                                                            |
|--------------|-----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| Gemini 3.x   | `thinking_config.thinking_level ? {MINIMAL,LOW,MEDIUM,HIGH}`                                  | `thinking_effort` str -> enum                                                               |
| Gemini 2.5   | `thinking_config.thinking_budget` int 0..32768 (`-1` dynamic; `0` disables on Flash)          | `thinking_budget` int -> field, OR `thinking_effort` mapped (off->0, low->2k, med->8k, high->24k)|
| Anthropic    | `thinking={"type":"enabled","budget_tokens":N}` (Sonnet 3.7/4.5/Opus 4.5) or `"adaptive"` (Opus 4.6+/Sonnet 4.6/Haiku 4.5/Opus 4.7) | `thinking_effort="off"` -> omit; `thinking_budget>0` -> enabled+budget; otherwise -> adaptive |
| OpenAI       | `reasoning.effort ? {none,minimal,low,medium,high,xhigh}`                                     | `thinking_effort` -> effort                                                                 |

**Neutral knob:** `thinking_effort: "off"|"minimal"|"low"|"medium"|"high"|"max"` AND `thinking_budget: int | None`. Adapter picks the one its model supports. The `max` level maps to `xhigh` on OpenAI / `HIGH` on Gemini 3.x / largest budget on Gemini 2.5 / adaptive on Anthropic.

**Signatures** are mandatory to round-trip on all three. My existing `Part.extra["signature"]` pattern works; Gemini 3 needs it on text parts too (not just tool_calls -- extending capture).

---

## 5. Errors -- neutralize the hierarchy

All three SDKs converge on roughly the same shape; my `LLMError` tree should mirror:

| Neutral                       | Gemini source                  | Anthropic source              | OpenAI source              |
|-------------------------------|--------------------------------|-------------------------------|----------------------------|
| `LLMConfigError`              | (factory-level)                | (factory-level)               | (factory-level)            |
| `LLMAuthenticationError`      | `ClientError` 401              | `AuthenticationError` 401     | `AuthenticationError` 401  |
| `LLMPermissionError`          | `ClientError` 403              | `PermissionDeniedError` 403   | `PermissionDeniedError` 403|
| `LLMNotFoundError`            | `ClientError` 404              | `NotFoundError` 404           | `NotFoundError` 404        |
| `LLMBadRequestError`          | `ClientError` 400              | `BadRequestError` 400         | `BadRequestError` 400      |
| `LLMRateLimitError`           | `ClientError` 429              | `RateLimitError` 429          | `RateLimitError` 429       |
| `LLMTimeoutError`             | (httpx timeout)                | `APITimeoutError`             | `APITimeoutError`          |
| `LLMConnectionError`          | (httpx ConnectError)           | `APIConnectionError`          | `APIConnectionError`       |
| `LLMServerError`              | `ServerError` 5xx              | `InternalServerError`/`OverloadedError` 5xx/529 | `InternalServerError` 5xx |
| `LLMSafetyError`              | `finish_reason==SAFETY` etc.   | `stop_reason==refusal`        | refusal output             |
| `LLMCallError` (catch-all)    | (anything else)                | (anything else)               | (anything else)            |

Safety blocks on Gemini are not exceptions -- they're `finish_reason`. Adapter checks and raises `LLMSafetyError` to keep behavior uniform across providers.

---

## 6. Embeddings

| Provider  | Method                              | Models                                   |
|-----------|-------------------------------------|------------------------------------------|
| Gemini    | `embed_content(model, contents, config={task_type, output_dimensionality})` | `gemini-embedding-001` 3072d Matryoshka (was `text-embedding-004`, deprecated) |
| Anthropic | **NONE** -- use Voyage/etc.          | n/a                                      |
| OpenAI    | `embeddings.create(model, input, dimensions, encoding_format)` | `text-embedding-3-small` 1536d, `text-embedding-3-large` 3072d |

**Anthropic adapter raises `LLMConfigError`** on `embed()` with a hint.

---

## 7. Package layout

Move from flat (`llm.py` + `llm_gemini.py`) to a package -- easier to grow.

```
llm/
??? __init__.py            # re-exports public API; same `from llm import X` works
??? types.py               # Part, Message, ToolDecl, Usage, AskResult, StreamChunk
??? errors.py              # LLMError tree
??? protocol.py            # LLMClient Protocol
??? factory.py             # make_llm_client(...), DEFAULT_MODELS, DEFAULT_API_KEY_ENV
??? base.py                # BaseLLMClient ABC + StreamAccumulator + shared helpers
??? _gemini.py             # GeminiClient(BaseLLMClient)
??? _anthropic.py          # AnthropicClient(BaseLLMClient)
??? _openai.py             # OpenAIResponsesClient(BaseLLMClient)
??? _openai_chat.py        # OpenAIChatClient(BaseLLMClient) -- fallback
```

Underscored adapter files signal "not for direct import -- go through the factory." The
factory lazy-imports them so users on Gemini only never pay the cost of
`import anthropic` / `import openai`.

`from llm import X` keeps working via `__init__.py` re-exports -- no caller code changes.

---

## 8. What stays in the protocol vs lives in `extra`

**First-class protocol kwargs (every provider gets these names):**
`model`, `messages`, `system_instruction`, `tools`, `tool_choice`, `parallel_tool_calls`,
`temperature`, `top_p`, `top_k`, `max_output_tokens`, `stop_sequences`, `seed`,
`presence_penalty`, `frequency_penalty`, `candidate_count`, `metadata`, `user`,
`thinking_effort`, `thinking_budget`, `include_thinking`, `response_schema`,
`response_mime_type`.

**Provider-specific in `extra={}` escape hatch on ask/ask_stream:**
- Gemini: `safety_settings`, `cached_content`, `labels`, `routing_config`, `speech_config`, `media_resolution`, `service_tier`, `automatic_function_calling`, `response_logprobs`.
- Anthropic: `betas=[...]`, `service_tier`, `container`, `mcp_servers`, `cache_control` (on system/tools -- but per-block goes via `ToolDecl.extra` / `Part.extra`).
- OpenAI: `store`, `previous_response_id`, `conversation`, `include`, `truncation`, `text.verbosity`, `parallel_tool_calls`, `prompt_cache_key`, `prompt_cache_retention`, `safety_identifier`, `service_tier`, `background`, `prompt`, `top_logprobs`, `web_search_options`.

**Per-Part `extra` for opaque round-trip state:**
- Gemini: `thought_signature` (bytes) on every part type with Gemini 3.
- Anthropic: thinking-block `signature`, `cache_control` markers, `is_error` on tool_results, `citations`.
- OpenAI: `encrypted_content` on reasoning items (with `store=False`), `call_id` separation from item id.

---

## 9. Live SDK quirks the adapter must absorb

- **Anthropic `max_tokens` is required.** Default 4096; bump to 16384 when `thinking_effort != "off"`. Document this in the adapter, never let it raise.
- **Anthropic first message must be `user`.** My loop already does this -- kept as invariant.
- **OpenAI `tools` shape diverges between APIs:** Chat wraps `function`, Responses is flat. Two separate adapters, not one shared tool-encoder.
- **OpenAI tool-call args are JSON strings**, not dicts. Adapter `json.loads` on the way in, `json.dumps` on the way out.
- **OpenAI Responses `store=True` is the default.** For PII-sensitive deployments the adapter should accept `extra={"store": False}` and request `include=["reasoning.encrypted_content"]` automatically when reasoning is on.
- **Streaming usage:** OpenAI Chat needs `stream_options={"include_usage": True}` opt-in; the others are automatic.
- **Anthropic `usage` in `message_delta` is cumulative**, not incremental. The accumulator must take the LATEST, not sum.
- **Gemini's `response.text` raises** if any part is a function_call -- never use it, walk `candidates[0].content.parts`.
- **Gemini AFC** auto-loops if you pass raw callables -- disable via `automatic_function_calling=AutomaticFunctionCallingConfig(disable=True)`. Adapter only ever passes declarations, but pin the flag anyway.

---

## 10. Out of scope for v1

- Audio + video modalities (Gemini-only; Anthropic doesn't support input audio/video).
- Bedrock + Vertex auth variants for Anthropic (factory hook reserved; not wired).
- Anthropic prompt caching auto-injection (user can hand-set via `Part.extra["cache_control"]`).
- OpenAI Conversations server-side state (`previous_response_id` exposed via `extra=`).
- Async clients (sync only in v1; async is `ask_async` / `ask_stream_async` later).
- Token-counting endpoint (Anthropic has `count_tokens`, OpenAI doesn't, Gemini has `count_tokens`).
- Live API / batch API on any provider.

These are deferred but the protocol is shaped so adding them is additive, not breaking.
