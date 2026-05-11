---
paths:
  - "src/**/*"
  - "lib/**/*"
---

# Root-cause fixes, not symptom bandages

You are editing build code. If you're about to add error handling,
catch a specific exception, or wrap something in a fallback —
**stop and trace 3-deep first**.

## The trace-three-deep rule

For every bug or unexpected failure, ask "why" three times:

> **Why 1:** [immediate behavior + file:line]
> **Why 2:** [layer below + file:line]
> **Why 3:** [structural layer + file:line]

Stop when the deepest answer points to a structural change that, if
made, makes the whole CLASS of "this kind of failure" go away.

## Refuse these bandages

- **`try: ... except: return default`** — hides the upstream bug
- **Feature flags hiding broken behavior** — defers without solving
- **Retries with no understanding of why failures happen** — masks
  intermittent bugs from the user
- **`if x is None: x = default` scattered through call sites** —
  the upstream bug is somewhere else; find it
- **Writing a test that pins the buggy behavior** — locks the bug in

## When to fix at layer N vs N+1

A symptom fix usually touches MORE lines than a root-cause fix
because it scatters defensive code. A root-cause fix usually touches
fewer lines but in fewer files because it changes ONE thing in ONE
place.

Counter-check: if your fix is in 5+ files, you're probably
symptom-fixing.

## Delegate to the root-cause-tracer subagent

For meaningful gaps, delegate to the `root-cause-tracer` subagent
(`.claude/agents/root-cause-tracer.md`). It works in an isolated
context, reads the failure + surrounding code, and returns the
deepest layer that must change.

Invoke via:
- `/trace-root-cause` slash command (recommended), or
- `Use the root-cause-tracer subagent to trace why X fails`

## When you can't fix the root cause now

Sometimes the root cause is out of v0.1 scope. In that case:

1. Document the gap in `gap-log.md` with the trace-three-deep
2. Apply the SHALLOWEST possible workaround
3. Mark with `# WORKAROUND(persona-mvp-kit): see gap-log #N` comment
4. Tell the user explicitly in your response

Don't apply a workaround silently. The user must know.

See `@methodology/06-FIX-ROOT-CAUSES.md`.
