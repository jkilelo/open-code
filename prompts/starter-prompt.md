# Starter prompt — how to invoke the kit

The kit is most effective when your first prompt makes the standard
explicit. Pick one of the shapes below.

## Shape 1 — pure persona-driven (recommended for greenfield)

> Build [the thing], following the persona-mvp-kit standard in this
> repo. Don't write any code until you've extracted personas and I've
> confirmed the MVP spec.

Example:

> Build a tool that helps clinical pharmacists check drug interactions
> from recent literature, following the persona-mvp-kit standard in
> this repo. Don't write any code until you've extracted personas and
> I've confirmed the MVP spec.

## Shape 2 — stack-named, kit-respected

> Build a full-stack [stack] app that [does X], following the
> persona-mvp-kit standard. Use the named stack but justify each
> dependency per-persona, and ship the smallest end-to-end slice
> first.

Example:

> Build a full-stack FastAPI + SQLite + Tailwind + React app that
> hosts AI agents for multiple use cases, following the
> persona-mvp-kit standard. Use the named stack but justify each
> dependency per-persona, and ship the smallest end-to-end slice
> first.

## Shape 3 — extending an existing project

> I want to add [capability] to this project. Apply the
> persona-mvp-kit standard: identify which persona this serves
> (existing or new), define the MVP bar in `mvp-spec-v0.X.md`, and
> ship the smallest end-to-end ratchet.

Example:

> I want to add real-time streaming to this project. Apply the
> persona-mvp-kit standard: identify which persona this serves and
> define the MVP bar in `mvp-spec-v0.2.md`.

## Shape 4 — bug fix / improvement

> [Description of what's broken or missing]. Apply the
> persona-mvp-kit standard: trace root cause 3-deep, name the
> persona this blocks, fix in one commit.

Example:

> The history page sometimes shows yesterday's briefs in random
> order. Apply the persona-mvp-kit standard: trace root cause
> 3-deep, name the persona this blocks, fix in one commit.

## What you DON'T need to include in your prompt

The kit's `CLAUDE.md` is auto-loaded. You don't need to copy-paste
its rules into every prompt. If Claude tries to skip a step (write
code without personas, mock something that should be real, claim
done without a `runs/` file), it's violating the kit — push back
and reference the section it skipped.

## What to expect on session 1

If you used Shape 1 or Shape 2:

- Claude responds: "I'm operating under the persona-mvp-kit standard.
  Before I write any code, I need to extract personas. Here are 4
  questions..."
- You answer.
- Claude writes `personas.md` and `mvp-spec.md`. Shows them.
- You confirm or refine.
- THEN code is written.

If you used Shape 3 or Shape 4:

- Claude reads existing `personas.md`, `mvp-spec.md`, `gap-log.md`.
- Claude proposes the increment as a v0.X spec OR a single-commit
  fix.
- You confirm.
- Claude builds.

## When to override the kit

You can. The kit is a default, not a law. If you tell Claude
explicitly to skip a step ("just give me a quick prototype, don't
worry about personas"), it should comply — but it should also
warn you which step it's skipping and what that means for the
output.

## Common first-prompt mistakes

- **"Build me an MVP"** — too vague. Of what? For whom?
- **"Use [stack]"** without saying what for — Claude has nothing to
  reason about.
- **"It should be production-ready"** — production for whom? "Ready"
  per which persona's criterion?

Each of these will trigger the extraction questions anyway. You
might as well give Claude what it needs upfront: name the user (or
ask for help defining one), name what they do today, name what
"better" would look like.
