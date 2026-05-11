# 05 -- Brutal honest review

After running the workflow as the persona, you produce a critique that
**is not optimistic by default**. The user has copied this kit because
they want truth, not encouragement. Honest "no, not yet" is more
valuable than glossy "yes, shipped."

## The brutal honesty test

Before claiming v0.1 is shippable, answer this question in writing:

> If the persona's boss showed them this tool and said "use this
> tomorrow morning instead of your current workflow, and I'll review
> the output you produce," would the persona be **glad** their boss
> made that switch?

Three failure modes:

- **No, they'd be angry.** The tool is worse than the current workflow.
  Common cause: criterion not met, or fakes the persona will hit on
  day one.
- **No, they'd be neutral.** The tool is no better or worse. Common
  cause: criterion was vague -- even success doesn't move the needle.
- **No, they'd be quietly worried.** The tool produces output that
  LOOKS right but the persona doesn't trust it. Common cause:
  fabricated citations, hidden mocks, no traceability.

If the answer isn't "yes, glad," fix it before claiming done.

## What "honest" actually means

Honesty here isn't about modesty. It's about specificity.

> [FAIL] "It mostly works but there are some rough edges."
> [OK] "The brief generation works end-to-end with real Gemini on the
>     4-source p07 corpus. The citation [^N] markers are wired and
>     the contradiction detector catches the $80M/$100M/$120M
>     disagreement. BUT: (a) latency is 22s on warm cache, 45s on
>     cold -- Sarah's spec said <30s, so cold-cache fails. (b) The
>     'history' tab is hardcoded to a JSON file, not reading from
>     SQLite -- Sarah won't see her past briefs. (c) On a 10-source
>     corpus, brief truncates at 7 facts because we hardcoded
>     max_facts=7; Sarah's actual workflow tops out at 6 sources, so
>     this is fine for v0.1."

The honest version names the persona, names the criterion, names
the gap with measured numbers, and tells the user which gaps are
deal-breakers vs acceptable for v0.1.

## Bias to find gaps, not justify completeness

The build effort biases you toward "it's done." The persona's daily
work biases them toward "this needs to do my job, not yours." When
those biases conflict, the persona's wins.

Habits that counter the build bias:

- **Run the workflow at least three times.** First run is "happy
  path I expected." Second run is "real input I didn't anticipate."
  Third run is "what would the persona type if they were tired."
  Different runs surface different gaps.

- **Read the output as the persona's adversary.** What would a
  skeptical reviewer challenge in this output? "Where did this
  number come from? Why this conclusion? What's missing?"

- **Compare side-by-side with the current workflow.** If the persona's
  current workflow takes 25 minutes and produces a 5-bullet brief,
  put your output next to that brief. Is yours actually better, or
  just different?

## The four colors of "done"

When reviewing, every claim about the slice falls into one of four
categories. Color-code your honesty:

- [OK] **Met:** the criterion is concretely satisfied, you ran it, you
  can quote the output. Ship.
- [WARN] **Partial:** the slice does most of what the criterion asks but
  has a documented gap (cited specifically). Work in progress.
- [FAIL] **Failed:** the criterion is not met. Don't ship until fixed.
- [X] **Not applicable for v0.1:** explicitly OUT of scope per
  `mvp-spec.md`. Confirm it's still out.

A v0.1 ships when ALL primary-persona criteria are [OK] and remaining
items are [X]. [WARN] and [FAIL] must move to [OK] (or be deferred to v0.2 with
user approval) before claiming done.

## Reviewing for the persona's ergonomics

Beyond the criterion, the persona has implicit expectations the spec
won't capture:

- **Speed:** every interaction has an expected latency. Type-paste-
  read-copy is sub-second. If your slice has a 5-second pause where
  the persona expects instant, they won't use it.

- **Wording:** the output language matches the persona's domain. A
  clinical pharmacist needs `mg/kg` and ICD codes, not generic JSON.

- **Errors:** when something goes wrong, the persona needs to know
  why and what to do. "Internal Server Error" is not acceptable;
  "Could not parse article 3 -- try copy-pasting the body text" is.

- **Trust:** the persona must be able to verify the output. Citations,
  source URLs, computed scores -- any output that can't be traced
  back to ground truth is suspicious.

Each implicit expectation is a gap candidate. List them in the review.

## The "what I'd be embarrassed to show them" list

Make this list. It's the most useful artifact you'll produce in any
review session. Every item should be a one-line gap:

```
What I'd be embarrassed for [persona] to see right now:
- The brief truncates the last bullet at 200 chars without saying so.
- The history page shows briefs from yesterday in random order.
- The "share" button doesn't actually copy to clipboard on Safari.
- The citation [^N] markers in the brief don't link anywhere.
- The page doesn't have a loading state during the 22s LLM call.
```

Then prioritize. The first 1-3 are immediate fixes. The rest go to
`gap-log.md`.

## When the review says "not yet"

Tell the user clearly:

> v0.1 is **not** shippable yet. Two blocking gaps:
>
> 1. Latency on cold cache (45s) exceeds Sarah's <30s criterion.
>    Root cause: we re-embed every span on every query. Fix:
>    cache embeddings on first read.
>
> 2. History page hardcoded -- Sarah won't see her past briefs.
>    Root cause: I built the list page with a TODO before wiring
>    the SQLite read. Fix: 20 lines of repository code + one
>    SELECT.
>
> Want me to fix both, then re-run the workflow?

Then wait for confirmation. Don't unilaterally start fixing. The user
might decide to ship v0.1 with the gaps documented, or push for the
fixes, or change scope. Their call.

## When the review says "ship it"

Tell the user clearly, with proof:

> v0.1 is shippable. Verified against Sarah's spec criterion:
>
> - [OK] Brief produced in 18s on warm cache, 28s on cold (criterion
>   <30s).
> - [OK] Catches the $80M/$100M/$120M contradiction across 4 sources.
> - [OK] Each bullet has [^N] citation traceable to source URL.
> - [OK] History page reads from SQLite; Sarah sees her last 50
>   briefs sorted by created_at desc.
> - [X] No auth (Sarah is the only user; runs locally) -- out per
>   spec.
>
> Run output: runs/2026-05-10-v0.1.0.md

Then wait. The user may want to ship as-is or refine.

## Read next

- [`06-FIX-ROOT-CAUSES.md`](06-FIX-ROOT-CAUSES.md) -- when the review
  found gaps, fixing them right
- [`07-SHIPPING.md`](07-SHIPPING.md) -- commit + release discipline
