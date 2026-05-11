# 01 — Personas

A useful persona is **a constraint, not a wish**.

## What a persona MUST contain

Use `templates/persona.md`. Every persona has these five fields, all
filled with concrete specifics:

### 1. Name + role + organization

A real-sounding name (so you stop calling them "the user"), a specific
job title, and the type of organization. Specificity matters — a "data
scientist" is different from a "data scientist at Citi Risk Analytics"
because the latter constraints what data they touch and what their
boss expects.

> ❌ "Power user who runs reports"
> ✅ "Sarah Chen, Senior Data Scientist, Citi Risk Analytics, NYC office"

### 2. Daily pain (current workflow)

What does this person do RIGHT NOW that's painful? Be precise: how
many minutes/hours per day, how often does it fail, what does the
failure cost them?

> ❌ "Spends a lot of time on research"
> ✅ "Reads ~200 fintech news articles between 7am-9am every weekday,
>     manually cross-references claims across Reuters / FT / SEC
>     filings, types notes into Word, updates Excel counterparty
>     tracker, emails brief to credit committee by 9:30. Takes
>     90-120 minutes. Misses ~15% of cross-source contradictions
>     because she can't hold 4 articles in working memory."

### 3. Primary workflow (the ONE thing this slice does)

The single workflow the v0.1 ships. Pick the workflow that:
- Happens most often (daily > weekly > monthly)
- Has the highest pain (most time / most errors / most stakes)
- Is most self-contained (doesn't require 5 other systems to work
  first)

If you can't pick one, your persona is fuzzy. Sharpen it.

> ❌ "Build risk reports"
> ✅ "Given 4-10 articles about a single counterparty, produce a
>     5-bullet brief with citations and an explicit list of
>     contradictions across the sources."

### 4. Success criterion (the "outperforms human" bar)

Concrete, measurable, **statable in the persona's own language**.
Not "the test passes" — what does the persona consider winning?

> ❌ "Better recall"
> ✅ "Brief is produced in <30 seconds (vs 30-45 min manual). Catches
>     at least one cross-source contradiction the human would have
>     missed. Every claim has a span citation traceable to source
>     URL. Briefs are ready before her 9:30am committee email goes
>     out."

The success criterion is the **acceptance test**. If you can't tell
whether the persona would say "yes" or "no" to a session's output,
the criterion is too vague.

### 5. What "no" looks like

The mirror of the criterion. What outputs would make this persona
NOT use your tool?

> ❌ "If it's broken"
> ✅ "If it ever fabricates a citation. If the brief misses a
>     contradiction that's literally in the source text. If it takes
>     longer than her current manual process. If she can't trace any
>     claim back to a verifiable source URL."

## How to extract personas from a vague request

When a user prompts something like:

> Build a full-stack FastAPI + React + SQLite + Tailwind app for
> hosting AI agents.

You DON'T have personas. You have a tech stack and a domain. You need
to ask up to 4 questions before writing code:

1. **Who's running the agents?** Marketing analyst? Internal devops?
   End customers? Different answers ⇒ totally different apps.

2. **What does ONE agent do, in their words?** "Summarize 10 articles"
   is different from "draft a sales email" is different from "scan
   logs for anomalies."

3. **What does the persona do today instead?** This anchors the
   "outperforms" bar.

4. **What does a successful Tuesday morning with this tool look like?**
   Concrete time, concrete output, concrete reduction in their current
   workflow.

If the user gave any of these in the prompt, don't ask them again.
If they gave none, ask all four. If they gave 2, ask the missing 2.

## Two to five personas, ordered

For a project of any meaningful scope, write 2-5 personas. Order them
by **which one's workflow you ship first**. The first persona's
success criterion is the v0.1 acceptance test. The others are
backlog.

```markdown
# Personas

## Primary (v0.1 ships their workflow)

### 1. Sarah Chen — Senior Data Scientist, Citi Risk Analytics
[full template]

## Secondary (v0.2+)

### 2. Maya Patel — Clinical Pharmacist, Mass General
[full template]

## Tertiary (later)

### 3. Alex Rivera — OSS Maintainer (PyPA)
[full template]
```

If two personas have similar workflows, MERGE them — you don't need
both. If they have different workflows, the slice for one will not
serve the other; pick one and ship it before adding the other.

## Personas are honest, not aspirational

A persona that's "anyone who uses our app" is the same as having no
persona. A persona that's "a busy executive" is so vague that any
output passes its bar.

The persona must be:
- **Specific enough that you can imagine their Tuesday morning calendar.**
- **Constrained enough that some features are obviously OUT of scope** (e.g., a clinical pharmacist persona excludes building social-media features).
- **Sharp enough that if you said "ship it" the user could either nod or push back with a concrete reason.**

## When personas change

Personas change when:

- The user tells you they got the workflow wrong and corrects it.
- The first slice ships and reveals that a related-but-different
  workflow is the real value.
- A second persona's needs surface conflicts with the first that
  must be resolved at the spec level.

When personas change, update `personas.md` AND `mvp-spec.md` BEFORE
writing any new code. Then commit those updates with a message that
explains why the bar shifted.

Personas don't change because:

- The code is hard to write the persona-correct way.
- A new tech is shiny.
- "It would be more elegant if..."

If you find yourself wanting to change a persona to make code easier,
stop. Ask the user.

## Read next

- [`02-MVP-BAR.md`](02-MVP-BAR.md) — how to translate a persona's
  success criterion into a build bar
- [`templates/persona.md`](../templates/persona.md) — fill-in template
