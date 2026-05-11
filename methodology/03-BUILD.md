# 03 -- Build the slice

Personas are confirmed. `mvp-spec.md` is signed off. Now you build.

## Build the smallest end-to-end first, not the deepest layer first

The instinct is to build the data model fully, then the API fully, then
the UI fully. That instinct is wrong here. It produces N-1 layers of
"complete" code that don't do the workflow because the Nth layer isn't
done yet.

Build the **thinnest vertical slice** through every layer first:

```
v0.1.0:  one input -> one transform -> one output
                       v
v0.1.1:  + persistence so the output isn't lost
                       v
v0.1.2:  + the second-most-important workflow detail
                       v
v0.1.x:  + persona's stated criterion is met
```

Each step ends with a runnable workflow. Not a runnable test. A runnable
workflow that the persona could trigger.

## Real systems, real data, real wiring

Tests can stub at boundaries -- that's fine. The build itself must:

- Hit the real LLM (use the user's actual API key from `.env`).
- Read the real database (real SQLite file, real schema).
- Process the real input format the persona will send.
- Produce real output the persona consumes.

If any layer is stubbed, that's a known incomplete in `gap-log.md` --
not "done" code with a stub hidden inside it. The user must be able to
look at your output and trust that what they see is what runs.

## Wiring discipline

End-to-end wiring is where most slices fail. The persona's input
arrives in the form they actually have it; your slice handles that
form; the output goes where they actually consume it.

Common wiring failures to refuse:

- **Frontend "demo mode" that uses mock data while the backend is built
  separately.** Wire them in the same session. If the backend isn't
  ready, write the smallest backend that returns real data first.

- **Backend that returns rich JSON the frontend never displays.** The
  schema of the response should match what the UI shows; if the UI
  shows 3 fields, the response has 3 fields.

- **"Run this CLI command, then paste the output into the web form."**
  Two unwired halves are worse than one half that works alone. Pick
  one entry point and ship it end-to-end.

- **Auth/login pages that block the workflow during development.** If
  the persona is the only user, no auth in v0.1.

## Stack selection: cheapest tool that works

For a given task, the smallest stack is usually:

| Need | First-choice tool | When to step up |
|---|---|---|
| Sync HTTP backend | FastAPI / Flask / Hono | When you need WebSockets, scale beyond one box |
| Persistence | SQLite | When you need concurrent writers / multi-host |
| Frontend | one React/Vue page, no router | When persona needs N pages |
| Styling | Tailwind defaults | When persona is design-sensitive |
| LLM | one SDK with one model | When persona's success requires multi-model |
| Background work | inline async | When work takes >30s OR persona reloads page |
| Search | LIKE / FTS5 | When you measure recall < persona threshold |
| Vector search | sqlite-vec / pgvector | When non-vector recall fails persona test |
| Auth | none (single user) | When persona needs multi-user |
| Observability | print/log to stdout | When persona reads the logs |
| Deployment | "run python && npm dev" | When persona consumes hosted URL |
| CI | none | When team grows beyond 1 |

These aren't rules -- they're defaults. Override when the persona's
workflow plainly demands more. A persona using the system from a
phone needs the frontend hosted; a persona at Citi needs auth even
in v0.1 because of compliance.

## File-and-directory discipline

The smallest slice has the smallest file tree. Single-file servers,
single-file clients, single-file data access are all valid in v0.1.
Split when files exceed ~300 lines AND splitting makes the workflow
clearer to the next reader.

Common over-organization to refuse in v0.1:

- `src/api/v1/`, `src/api/v2/` -- there is no v2 yet
- `services/`, `repositories/`, `dto/` -- three layers of abstraction
  for one workflow is theatre
- `config/development.json`, `config/production.json` -- there is no
  production yet
- `tests/unit/`, `tests/integration/`, `tests/e2e/` -- flat `tests/`
  is fine until you have >50 tests

Earned organization is fine. Speculative organization is rot.

## Errors and edge cases in v0.1

For input you control (your own internal calls), trust it. No defensive
parameter validation. No "in case the dict is None." Internal types
are types -- let Python tell you when they're wrong.

For input you don't control (user input, LLM responses, external APIs),
validate at the boundary, fail loudly on bad input. Don't:

- Catch generic `Exception` and log + return default.
- Wrap LLM calls in try/except that returns empty string on failure.
- Silently coerce missing fields to empty string.

These patterns hide bugs the persona will hit but you won't see in
testing.

For edge cases the persona will encounter rarely:

- If the persona's primary workflow doesn't depend on it, don't handle
  it in v0.1. Add a `# TODO(persona): edge case X surfaces when ...`
  comment and move on. Document in `gap-log.md`.
- If the persona's primary workflow ALWAYS triggers it, handle it.
  This is just the workflow.

## Tests in v0.1

Tests pin behavior the persona depends on. Add them as you build:

- For each step of the workflow, one happy-path test.
- For each known failure mode (parse errors, network errors, bad
  input), one failure-mode test that asserts the loud error message.

Don't:

- Write tests for behaviors you haven't decided yet.
- Write parameterized tests for every combination of inputs.
- Write integration tests that mock the thing being integrated.

Run the test suite once per build session. Don't let red tests
accumulate.

## When to commit

Commit when:

- A step of the workflow runs end-to-end.
- A test for that step passes.
- The slice is `git push`-able to your team without embarrassment.

Don't:

- Commit unfinished half-states.
- Squash everything into one big "first slice" commit.
- Delay commits until the slice is "done" -- incremental commits help
  the user see the slice take shape.

Commit messages: see `templates/commit-message.md`.

## When to stop building and run

Stop building and run the workflow as the persona when:

- The smallest end-to-end slice runs without crashing on the persona's
  real input.
- You can show the persona a result they would consume.

This is when you switch from `03-BUILD.md` to `04-RUN-THE-WORKFLOW.md`.
Do this BEFORE polishing the build, BEFORE adding the next feature,
BEFORE writing more tests. Running as the persona surfaces gaps that
no amount of additional code can find.

## Read next

- [`04-RUN-THE-WORKFLOW.md`](04-RUN-THE-WORKFLOW.md) -- adopt the
  persona to test
- [`ANTI-PATTERNS.md`](ANTI-PATTERNS.md) -- what to avoid during build
