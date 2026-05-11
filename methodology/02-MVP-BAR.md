# 02 -- Defining the MVP bar

> "Minimum viable" is two words. Most builds get the first wrong by
> adding things; this method gets the second wrong by accepting things
> that don't help anyone. Hold both.

## The MVP spec is one document

`mvp-spec.md` at project root, written from `templates/mvp-spec.md`.
It answers four questions:

1. **Which persona's workflow does v0.1 ship?** (Single name from
   `personas.md`.)
2. **What's the success criterion, in their language?** (Concrete,
   measurable, dated.)
3. **What's the smallest tech stack that achieves it?**
4. **What's explicitly OUT of v0.1?**

That's the whole document. If you find yourself adding more sections,
stop -- you're scoping creep.

## The success criterion must be measurable

A vague criterion produces a vague slice. A concrete criterion forces
a concrete slice.

> [FAIL] "Brief is good and helpful"
> [OK] "Given 4 input articles about one event, output a markdown brief
>     with 4-7 bullets, each grounded by a `[^N]` citation to a
>     verbatim source span. If two sources report different numbers
>     for the same fact (e.g. funding amount), brief includes a
>     `Contradictions:` section listing them with fact_id refs.
>     End-to-end runtime <30s on 4 sources of <2KB each."

The criterion should pass the **screenshot test**: if you can't
imagine a screenshot or terminal output that obviously satisfies the
criterion, it's not concrete enough.

## The smallest end-to-end slice

The phrase "end-to-end" is doing real work here. Slice means
**vertical**: from the user's input through every layer to the
output the persona consumes. Not horizontal: not "first build the
schema, then the API, then the UI."

For a fullstack app, the smallest e2e slice is typically:

- One input form (or one CLI command)
- One backend endpoint that does the work
- One persistence write (so the work isn't lost)
- One output the persona reads

Not 4 endpoints. Not "the whole CRUD." One workflow, end to end.

## Stack selection: each piece justified per-persona

Every dependency in the v0.1 build must trace to a specific persona
need. Write the justification in `mvp-spec.md`:

```markdown
## Tech stack

- **FastAPI** -- Sarah needs a workflow that runs as a long-lived
  service her team can hit; FastAPI's async + auto-OpenAPI matches
  this and is the smallest framework that handles it.
- **SQLite** -- Sarah's data is <100MB of news articles. Single
  process. No need for Postgres in v0.1.
- **OpenAI SDK** -- needed for summary generation; persona criterion
  requires citation-grounded output.

## Out of v0.1

- Auth (Sarah is the only user; she runs it locally)
- Frontend (CLI is sufficient; she pastes briefs into email)
- Background workers (synchronous request is fast enough at her scale)
- Multi-tenant DB design
- Deployment / Docker / CI
```

If a piece can't be justified per-persona, it's out. "We'll need it
later" is not a justification -- it's deferred-design rot.

## What goes OUT of v0.1

Be explicit about what you're NOT building. The Out-of-Scope list is
as important as the in-scope list because it's a permission slip to
say "no" later when scope creep arrives.

Examples of common things that go OUT of v0.1:

- Authentication / authorization (unless persona requires multi-user)
- Database migrations (unless schema will provably change pre-v0.1)
- Production deployment / Docker / CI (unless persona uses production)
- Logging / observability infrastructure (unless persona reads the logs)
- Configuration management (use hardcoded constants until persona
  needs to vary them)
- Multi-LLM / multi-backend / multi-X support
- Graceful degradation paths for situations that can't happen yet
- Admin UI
- Email / Slack notifications (unless persona's success criterion
  mentions them)

For each of these you decide to skip, write "OUT: [thing] because
[reason]" in `mvp-spec.md`. Reasons that work: "Sarah is the only
user," "we have <100 records," "deferred until persona X is added."

## When to expand the bar

Expand the bar when:

- The first persona's success criterion is concretely met AND
- A second persona is in `personas.md` with their own criterion AND
- The user explicitly approves moving to v0.2.

Don't expand because:

- "We have time."
- "It would be cleaner."
- "Other apps have this feature."
- "I might forget later."

## Worked example: the user's FastAPI + React prompt

Imagine the user wrote:

> Build a full-stack FastAPI + SQLite + Tailwind + React app for
> hosting AI agents.

Wrong response: scaffold all four pieces and write boilerplate.

Right response: the prompt has a stack but no persona. You ask:

1. Who runs the agents? (e.g., "internal team of marketing analysts")
2. What does ONE agent do? (e.g., "summarize 10 competitor news
   articles into a 5-bullet brief")
3. Current workflow? (e.g., "they manually skim articles in browser
   and type notes")
4. Success criterion? (e.g., "produce brief in <60s with citations
   they can paste into Slack")

Then `mvp-spec.md` becomes:

```markdown
# MVP spec -- v0.1

## Persona shipped
Marketing analyst (Sam) -- see personas.md.

## Success criterion
Sam pastes 10 article URLs into a single web form, clicks "summarize."
Within 60 seconds, the page shows a 5-bullet brief, each bullet ending
with a `[^N]` citation linking back to the source URL. Sam copies the
markdown to Slack. End-to-end on a typical Tuesday: <90 seconds vs
his current ~25 minutes.

## Smallest tech stack
- FastAPI -- single endpoint POST /briefs, takes URLs, returns markdown.
- SQLite -- store {brief_id, urls, output, created_at}. Lets Sam
  re-read past briefs.
- React + Tailwind -- one page, one form, one output area, one
  history list.
- One LLM SDK (Gemini OR OpenAI, pick whichever the user has a key
  for) -- for actual summarization.

## OUT of v0.1
- User accounts / auth (Sam is the only user; runs locally)
- Multi-LLM support (one LLM, hardcoded model id)
- Streaming (synchronous is fine at <60s)
- Article scraping infrastructure (assume URLs return readable text;
  use a single library, fail loudly on JS-heavy sites -- Sam can
  paste the article body if scraping fails)
- Deployment / Docker / Tests-as-CI (Sam runs `python -m server` +
  `npm run dev`)
- Tailwind theming / design system (default Tailwind, no custom)
- Sources beyond URL (no PDF, no upload, no email forwarding)
- Multiple agents (one workflow only -- summarization)
- Rate limiting, retries, observability
```

That's the whole spec. Now build that. Resist adding to it during the
build.

## Read next

- [`03-BUILD.md`](03-BUILD.md) -- actually building the slice
- [`templates/mvp-spec.md`](../templates/mvp-spec.md) -- fill-in template
