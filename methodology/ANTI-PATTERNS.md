# Anti-patterns

Things this kit explicitly forbids. When you feel the urge to do any
of these, refuse -- or ask the user before proceeding.

## Process anti-patterns

### "Let me set up the project structure first"

Before personas are confirmed, project structure is speculation. Fight
the instinct to scaffold `src/`, `tests/`, `docs/`, `Dockerfile`,
`.github/workflows/`, `pyproject.toml`, `tsconfig.json`, etc.

**Allowed before personas:** `personas.md`, `mvp-spec.md`, the
persona-mvp-kit folder itself.

**Forbidden:** anything else.

### "Let me write the database schema first"

Schemas serve workflows. Workflows serve personas. Build the workflow
end-to-end first; the schema emerges from what the workflow needs.

If you write `CREATE TABLE` before you've run a workflow that
demands it, you're guessing.

### "Let me build the entire frontend, then wire the backend"

Or vice versa. Two unwired halves are worse than one wired half.
Build a vertical slice through every layer, then thicken.

### "Let me write tests first" (without first defining what runs)

TDD has its place but it's not "write tests for everything before
you have a workflow that runs." The right shape is:
1. Write the smallest e2e workflow that runs.
2. As you build each step, add a test pinning that step's behavior.
3. Run the workflow as the persona.
4. Add tests for any failure mode the persona hit.

If you're 200 lines into pytest before the workflow has run once,
you're TDD-LARPing.

### "Let me refactor before adding the next feature"

Refactor when files exceed 300 lines AND clarity demands it. Don't
refactor speculative architecture into existence.

### "Let me add a config system"

Config systems are infrastructure that supports many environments.
Until v0.1 has more than one environment, hardcode constants. When
v0.1 ships, add config IF an actual user is asking to vary something.

### "Let me write a CLI AND a REST API AND a Python library"

Pick one entry point per persona. Sarah uses CLI? Build CLI. The
others come when a different persona's workflow demands them.

## Code anti-patterns

### Defensive programming for cases that can't happen

```python
# [FAIL] This pattern hides bugs
def add_node(node):
    if node is None:
        return
    if not hasattr(node, 'id'):
        return
    if node.id is None:
        return
    ...
```

Trust your types. If `node` shouldn't be None at this call site,
let `AttributeError` blow up loudly when it is. The exception is
the diagnostic.

### Try-except returning defaults

```python
# [FAIL] Silently swallows the real failure
def get_brief(entity):
    try:
        return generate_brief(entity)
    except Exception as exc:
        log.error(f"Brief failed: {exc}")
        return {"summary": "", "bullets": []}
```

This pattern returns empty briefs when the brief generator throws.
The persona sees "no facts available" and assumes the entity has
no info. Don't do this. Let exceptions propagate to a single
top-level handler that shows the error to the persona with a clear
diagnostic message.

### Mocking what should be real

If the build claims "ingestion works" but the LLM call is mocked
to return a hardcoded response, ingestion DOESN'T work. The user
will discover this when they hand it to the persona.

Acceptable: tests that mock at boundaries.
Unacceptable: a "running" build that has mocks behind the curtain.

### Writing wrappers around stable libraries "for flexibility"

```python
# [FAIL] Wrapping httpx because "what if we change HTTP libraries?"
class HttpClient:
    def __init__(self): self._inner = httpx.Client()
    def get(self, url): return self._inner.get(url)
    def post(self, url, json): return self._inner.post(url, json=json)
```

You will not change HTTP libraries. The wrapper adds friction and
hides httpx's actual capabilities. Use httpx directly.

### Creating abstractions for one implementation

```python
# [FAIL] One backend wrapped behind a Protocol
class StorageBackend(Protocol):
    def save(self, key: str, value: str) -> None: ...
    def load(self, key: str) -> str | None: ...

class SqliteStorage(StorageBackend):  # only impl
    ...
```

Protocols and ABCs are earned by the SECOND implementation. Until
then, just have `SqliteStorage`. When the second backend lands,
extract the Protocol from the two concrete classes -- not the other
way around.

### Catching `Exception` at the top of the workflow

```python
# [FAIL] Hides every bug under one diagnostic
try:
    result = run_workflow(input)
except Exception as exc:
    return {"error": "Something went wrong"}
```

The persona deserves a real diagnostic. Either:
- Let the exception propagate to the framework's default error page
  (which will show the traceback in dev), or
- Catch specific exceptions you've defined for the workflow
  (`InputParseError`, `LLMUnavailableError`, etc.) and show the
  persona a useful message per type.

### Speculative concurrency / async / streaming

Building async + streaming + queue-backed background jobs because
"the persona MIGHT have lots of traffic later" is over-engineering.
Synchronous code is shorter, simpler, and easier to debug. Switch
to async/streaming when the persona's stated criterion plainly
demands it.

### Adding observability before there's anyone to observe

Datadog, OpenTelemetry, structured logs, dashboards -- all earn their
place when the persona (or operations team) is reading them. Until
then, `print()` to stdout is fine.

## Documentation anti-patterns

### Writing READMEs before the slice runs

A README describes what the software does. If the slice doesn't
run, the README is fiction. Write the README AFTER the workflow
runs end-to-end as the persona.

### Long architecture docs for v0.1

`mvp-spec.md` is the architecture for v0.1. If you find yourself
writing `docs/architecture/00-overview.md`, `docs/architecture/01-
data-flow.md`, etc., for a slice that doesn't yet ship -- stop.
Architecture docs are an output of v1.0, not v0.1.

### Inline comments explaining what code does

```python
# [FAIL] Reads what's already obvious
# Increment counter by 1
counter += 1
```

Code explains what. Comments explain WHY. Reserve comments for
non-obvious WHYs: business rules, hidden constraints, workarounds
for specific bugs, pointers to gap-log entries.

## Persona anti-patterns

### Inventing personas to justify pre-decided architecture

If you found yourself writing a persona that conveniently needs the
exact technology you wanted to use, you've corrupted the process.
Stop. The persona drives the architecture, not the other way.

### Vague personas

> [FAIL] "Power user who needs analytics."
> [FAIL] "Anyone who wants to track their projects."
> [FAIL] "A developer."

If the persona could be anyone, it constrains nothing. Re-do the
extraction with the questions in `01-PERSONAS.md`.

### Multiple primary personas in v0.1

Only one persona's workflow ships first. Listing 3 primary personas
means none of them gets a slice that actually serves them -- every
build choice is a compromise.

### Persona drift mid-build

Mid-build, you realize the persona's workflow is harder than expected,
and you start "adjusting" the persona to make the build easier.
Stop. Fix the workflow or talk to the user about scope. Don't fudge
the persona.

## Shipping anti-patterns

### Big-bang commits

A single 50-file 5000-line "first slice" commit is unreviewable and
unbisectable. Even for v0.1, ship in commits of one workflow-step
each.

### Commit messages that don't name the persona

If your commit message says "fix bug" or "refactor module" without
naming who benefits from the change, you've lost the through-line
that makes this method work.

### Saying "done" when it isn't

The brutal review tells you when v0.1 is done. If the latest `runs/`
file has [FAIL] against the persona's criterion, the slice is not done.
Don't claim it is.

### Squashing diagnostic info out of commits

Verbose commit bodies (with persona-context, root-cause traces,
verification quotes) are an asset, not noise. Don't squash them
into one-liners during PR cleanup. Keep the audit trail.

## When the user asks you to do an anti-pattern

Tell them. Quote the anti-pattern from this file. Ask if they want
to override.

> The user asked me to add an authentication system. The MVP spec has
> auth listed as OUT for v0.1 because the only persona is a single
> local user. Adding auth now would be a scope-creep anti-pattern.
> Want me to:
> (a) Skip auth as the spec says,
> (b) Update the spec to include auth (which adds N hours and pulls
>     the build sideways), or
> (c) Add a second persona to `personas.md` that explicitly needs
>     auth, then re-spec?

The user can choose. But the kit's defaults forbid silent override.
