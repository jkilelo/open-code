---
description: Draft mvp-spec.md from the confirmed personas before any code is written.
---

You are translating confirmed personas into a concrete MVP bar under
the persona-mvp-kit standard.

Pre-conditions:
- `personas.md` exists and the user has confirmed it.

If `personas.md` doesn't exist or isn't confirmed, run `/persona-extract`
first.

Steps:

1. Read `personas.md`. Identify the **primary persona** (the one v0.1
   ships their workflow).

2. Draft `mvp-spec.md` from `templates/mvp-spec.md`. The four sections:
   - **Persona shipped** — name the primary persona
   - **Success criterion** — concrete, measurable, in their language;
     quote verbatim from `personas.md` and add specifics (time bounds,
     output format, failure modes)
   - **Smallest tech stack** — each dependency justified per-persona
     in one paragraph each. Use `skills/minimal-stack-selection/` as
     the default ladder
   - **OUT of v0.1** — explicit list, each item with a one-line reason

3. Add two operational sections:
   - **How v0.1 ships** — the exact entry point the persona uses
   - **How v0.1 is verified** — the run sequence + criterion check

4. Show the file to the user. Ask:
   "Does this match the bar you want for v0.1? Anything to add to
   the OUT-of-scope list? Confirm before I start building."

Do NOT write code. Do NOT install dependencies. Do NOT create the
project skeleton. The output is `mvp-spec.md` only.

If the user previously told you a stack ("use FastAPI + Postgres +
Redis") and your minimal-stack default would pick smaller (e.g.
SQLite, no queue), surface the tradeoff before drafting:

> You named [their stack]; my default for this v0.1 spec would be
> [smaller stack]. Want me to use yours, mine, or hybrid?

Reference: `methodology/02-MVP-BAR.md`.
