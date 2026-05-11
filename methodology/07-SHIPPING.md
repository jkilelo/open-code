# 07 -- Shipping

## One commit per gap

Every commit closes exactly one gap from `gap-log.md`. Not two; not
half. One.

Why: when the persona's experience changes -- for better or worse -- the
user must be able to point at the commit that caused it. A commit that
mixes a feature, a refactor, and a bug-fix is impossible to bisect.

## Commit message anatomy

Use `templates/commit-message.md` as the base. Every commit message:

1. **Title (first line, <=72 chars):** `<persona-name>: <one-sentence
   description of what the commit ships, in the persona's terms>`.

2. **Body:** explain (a) what was broken from the persona's
   perspective, (b) the root cause you traced, (c) what you changed,
   (d) the verification you did against the persona's criterion.

Examples:

```
Sarah: brief now catches multi-source numerical contradictions

Persona pain: 4 finance articles report different funding amounts
($80M / $100M / $120M) for the same Series B round. Previous brief
silently agreed on "secured Series B funding" -- Sarah would have
written that into the credit committee email and been wrong.

Root cause: the LLM brief prompt only saw abstracted edge tuples
(src --type--> dst), not the verbatim source spans. With no source
text in the prompt, no number-disagreement was visible to the model.

Fix: include the verbatim source snippet (max 280 chars per fact)
in the FACTS block of the prompt, plus an explicit instruction to
detect numerical/leadership disagreements across snippets and return
them as a `contradictions` list referencing fact_ids.

Verified against Sarah's spec criterion ("Catches at least one
cross-source contradiction"): brief on p07 (4 articles) returned

  Contradictions:
  - Funding amount: $80M (fact 3, 4, 5, 8, 9, 18) vs $100M (fact
    6, 10) vs $120M (fact 1, 7, 13)

Sarah's 9:30am email is now correct.
```

```
Maya: --min-confidence floor blocks low-confidence facts from clinical brief

Persona pain: clinical pharmacist running brief on Warfarin
pre-discharge cannot afford to see a 0.6-confidence drug
interaction in the output. Wrong-call cost is asymmetric: a missed
warning is inconvenient; a fabricated interaction is malpractice
exposure.

Fix: new --min-confidence C flag on `agent-graph brief`. Facts whose
grounding citation has confidence < C are dropped before the LLM
sees them; LLM cannot cite them; they cannot reach the final
markdown.

Default 0.0 (no filter), so existing Sarah/Alex workflows are
unchanged. Maya can call:

    agent-graph brief --entity "Warfarin" --min-confidence 0.9

and only see facts the extractor was confident about.

Verified: a 0.6-confidence test fact survives at floor=0.0 but is
dropped at floor=0.9. Real-Gemini run on Maya's p04 corpus shows
the n-ary `(anticoagulant=Warfarin, antiplatelet=Aspirin) --
drug_drug_interaction` fact passes the 0.9 floor as expected.
```

Note: each message names the persona, names the criterion, names
the cause, names the verification. No commit is just "fix bug" or
"refactor X".

## Gap-log discipline

`gap-log.md` is the running record of what's blocking each persona.
Update it AT EVERY STEP:

- When you find a gap during run-the-workflow -> add it as [FAIL].
- When you start fixing it -> mark [WARN] in-progress.
- When you commit the fix -> mark [OK] with SHA + verification quote.
- When you decide to defer -> mark [X] with reason ("deferred to v0.2
  per Maya's decision date 2026-05-10").

The user reads `gap-log.md` to know what's done and what's outstanding.
A stale log makes the kit useless.

## Versioning the slice

Each shippable state of the slice gets a tag. Use semantic versioning
inside-the-persona scope:

- `v0.1.0` -- first shippable slice for primary persona
- `v0.1.1` -- bug fix or small ratchet improvement, primary persona
  still primary
- `v0.2.0` -- second persona's primary workflow added
- `v1.0.0` -- the user explicitly declares "this is the product"

Don't ship `v0.1.0` until the primary persona's success criterion is
[OK]. Don't ship `v0.2.0` until the secondary persona's primary
workflow is [OK].

## Branching strategy

For solo dev with this kit: commit straight to `main`. Each commit
is small and persona-justified, so a noisy main is fine.

For multi-dev: feature branches per gap, one commit per branch, PR
title = commit title. Reviewer's only question: "is this gap closed
according to the persona's criterion?"

Don't run multi-week feature branches. Each commit closes one gap;
each gap has a small commit. Long-running branches violate the
"one commit per gap" discipline.

## Pre-commit checklist

Before `git commit`, run through:

- [ ] The workflow ran end-to-end as the persona, with output saved
      to `runs/`.
- [ ] The persona's criterion is concretely closer to met (or fully
      met) after this change. Quote the new state.
- [ ] `gap-log.md` is updated to reflect what changed.
- [ ] Tests for the changed behavior pass (and ideally a new test
      pins the persona-correct outcome).
- [ ] No new tech dependency was added without a persona-justification
      line in `mvp-spec.md`.
- [ ] No mocks, fakes, or hardcoded fallbacks were added that the
      user would discover later.
- [ ] The commit message names the persona and quotes the criterion.

If any item is unchecked, the commit isn't ready.

## Pre-push / pre-PR

If you're about to push or open a PR:

- [ ] All commits since the last push pass the pre-commit checklist.
- [ ] The latest `runs/` file shows the workflow currently passes.
- [ ] `gap-log.md` reflects the current state.
- [ ] The PR description (or push message) summarizes which personas
      are now [OK], [WARN], [FAIL] against their primary criteria.

## "Done" for v0.1.0

A v0.1.0 ships when:

- The primary persona's `mvp-spec.md` success criterion is [OK].
- Every "OUT of v0.1" item in the spec is verified still out (no
  scope creep).
- The latest `runs/` file demonstrates the criterion met.
- `gap-log.md` either has all primary-persona gaps [OK] or has them
  marked [X] "deferred per user decision."

Tag with `git tag v0.1.0`. Push the tag.

## Read next

- [`templates/commit-message.md`](../templates/commit-message.md) --
  the commit-message template
- [`templates/gap-log.md`](../templates/gap-log.md) -- the gap-log
  template
- [`ANTI-PATTERNS.md`](ANTI-PATTERNS.md) -- the things that violate
  this discipline
