---
name: minimal-stack-selection
description: Pick technology for the v0.1 build under the persona-mvp-kit standard. Each dependency must trace to a specific persona workflow; no speculative tech. Use when drafting mvp-spec.md Sec. "Tech stack", when the user proposes adding a library mid-build, or when `npm install` / `pip install` / `uv add` is about to run.
allowed-tools: Read, Grep, Glob
when_to_use: Use when mvp-spec.md Sec. "Tech stack" is being drafted; when a new dependency is proposed; before pip install / npm install / uv add commands.
---

# Minimal stack selection

Each dependency in v0.1 must trace to a persona need, written in
`mvp-spec.md` Sec. "Tech stack" with a one-paragraph justification.

## Default ladder

For each common need, pick the smallest viable choice; step up only
when the persona's stated criterion demands it.

| Need | First choice | Step up when |
|---|---|---|
| Sync HTTP backend | FastAPI / Flask / Hono | WebSockets, multi-host scale |
| Persistence | SQLite (one file, one process) | concurrent writers OR multi-host |
| ORM | none -- raw SQL via stdlib | schema large enough that hand-SQL is error-prone |
| Schema migrations | none (edit schema in place) | persona's data is in production |
| Frontend | one React/Vue/Svelte page, no router | persona needs N pages |
| Frontend state | local `useState` | shared state across >=3 pages |
| Styling | Tailwind defaults | persona is design-sensitive |
| LLM | one SDK + one model | persona requires multi-model |
| Embeddings | hashing-based or local model | persona needs production-grade recall |
| Search | LIKE / FTS5 | recall < persona threshold |
| Vector DB | sqlite-vec / pgvector | non-vector recall fails persona test |
| Background jobs | inline async | work > 30s OR persona reloads page |
| Auth | none (single user) | persona is multi-user |
| Sessions | none / cookies | server-side state needed |
| API docs | FastAPI auto OpenAPI | none for non-FastAPI |
| Validation | Pydantic at API boundary | hand-rolled `dict.get` for trivial |
| Logging | `print()` to stdout | persona reads logs |
| Observability | nothing | persona/ops has dashboards |
| Deployment | "run python && npm dev" | persona consumes hosted URL |
| Containerization | none | ops requires Docker |
| CI | none | team grows beyond 1 |

These are defaults. Override when the persona's workflow plainly
demands more.

## Rejected by default

- Multi-database support (one DB until two personas demand different)
- Multi-LLM support (one provider until persona demands choice)
- Multi-tenancy (single tenant until N tenants exist)
- Plugin systems (no plugin until N plugins demanded)
- Generic configuration files (hardcoded constants until v0.2)
- Internationalization (English until persona speaks other language)
- Theming (defaults until designer joins)
- Rate limiting (none until persona is rate-limited externally)
- Background workers / queues (synchronous until UX demands async)
- Service mesh / microservices (one service until N services exist)

## Justification template

Each dependency in `mvp-spec.md` looks like this:

```markdown
- **FastAPI** -- Sarah's workflow is "POST 4 URLs, get markdown brief
  back." She needs a long-lived service her team can hit. FastAPI's
  async is irrelevant here, but the auto-OpenAPI gives her a "try it"
  UI for free without me writing a frontend in v0.1.
```

If you can't write that paragraph, the dependency is speculative.
Cut it.

## When the user names a tech you wouldn't pick

User: "Use FastAPI + Postgres + Redis + Celery + React + Tailwind."
You'd default to SQLite + sync + smaller frontend.

Don't silently override. Ask:

> Given the v0.1 spec (single-user, <100MB data, sync workflow), my
> default would be SQLite + inline async + no queue. Want me to:
> (a) Use your stack as named (longer setup, more moving parts),
> (b) Use my smaller stack (faster to v0.1, easy to migrate later),
> (c) Hybrid (e.g., SQLite for v0.1, migrate to Postgres when
>     persona X is added)?

Make the tradeoff visible.

## Anti-pattern

"We might need it later." Every "might need" is speculation. Real
persona needs are observable. Defer until observable.

If the user prompts a feature "for the future," ask: "which persona's
workflow needs that, and when in our roadmap?" If there's no answer,
it's out of v0.1.

## Reference

Methodology: `@methodology/03-BUILD.md` Sec. "Stack selection."
