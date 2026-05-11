---
# No paths field — this rule loads every session.
# Context discipline is universal; it applies regardless of which file
# is being edited.
---

# Context discipline

The persona-mvp-kit's overhead is meaningful (kit + skills + your
build files). To keep performance from degrading, hold these
disciplines:

## `/clear` between unrelated tasks

If the current task is done and the next is unrelated, `/clear`.
Don't accumulate context across unrelated tasks.

## After 2 corrections on the same issue, `/clear`

Context is now polluted with failed approaches. Start fresh with a
better prompt incorporating what you learned. A clean session with
a better prompt almost always outperforms a long session with
accumulated corrections.

## Use subagents for heavy reading

Three subagents in `.claude/agents/` run in fork context:

- `persona-validator` — for persona quality checks
- `brutal-reviewer` — for the review (heavy reading of mvp-spec
  + runs + gap-log + git log)
- `root-cause-tracer` — for trace-three-deep on a gap

Delegate to them via `Use the X subagent to ...` so heavy work
happens in their isolated 200k window, not yours.

## Scope file reads narrowly

`Read` with `offset` and `limit` for known regions. Use `Grep` to
find call sites before `Read`-ing entire files. Use `Glob` for
discovery before `Read`.

## Set MAX_TOKENS / WITHIN_LATENCY_MS

For LLM-using systems, cap retrieval payloads. Reduces token cost
AND forces better ranking.

## What survives auto-compaction

- `CLAUDE.md` (re-read from disk)
- `personas.md`, `mvp-spec.md`, `gap-log.md` (referenced via
  `@path` imports in CLAUDE.md)
- Most recent invocation of each skill (first 5k tokens; combined
  budget 25k)
- The kit's `SessionStart` hook on `compact` matcher re-injects
  the critical reminder

What's lost: most conversation history (summarized), file contents
read but not recently referenced.

See `@methodology/CONTEXT-MANAGEMENT.md` for the full doctrine.
