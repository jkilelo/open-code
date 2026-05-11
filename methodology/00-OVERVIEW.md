# 00 -- Overview

The persona-driven MVP method, end to end.

## The core insight

Most LLM-assisted coding fails the same way: the LLM produces code that
**runs** but doesn't **help**. The unit tests pass. The architecture
reads cleanly. The README looks plausible. But no specific human is
better off tomorrow than they were yesterday.

This happens because the bar is wrong. "It compiles," "tests pass,"
"the architecture is clean" -- all true, all irrelevant. The right bar
is: **does a named human pick this over their current workflow?**

The persona is the bar. The workflow is the test. The slice is what
you ship.

## The seven steps

```
1. Extract personas       -> personas.md
2. Define the MVP bar     -> mvp-spec.md
3. Pick smallest stack    -> tech choices justified per-persona
4. Build the slice        -> smallest end-to-end, real systems
5. Run as the persona     -> not "test passes", workflow runs
6. Brutal honest review   -> would they actually use this?
7. Ship per-gap commits   -> root cause fixed, persona quoted
                          (loop) loop to step 5 until persona success
                          (loop) then add the next persona
```

Each step has a dedicated methodology file (`01-` through `07-`).

## Why this works in practice

We built `agentGraph` (a knowledge-graph layer for AI agents) using this
method. Five fictional personas -- Sarah the Citi risk analyst, Maya the
clinical pharmacist, Alex the OSS maintainer, Jamie the investigative
journalist, Liu the ML researcher -- each described with a real daily
pain. Every commit either built or fixed something a named persona was
blocked on.

Concrete results from running this method:

- **Sarah's workflow**: cross-reference 4 overnight news articles for
  the same event, catch contradictions a tired analyst misses. The
  brief generator we built catches `$80M / $100M / $120M` as three
  reported funding amounts across 4 sources, in 5 seconds, with full
  citations. A human takes 30-45 minutes.

- **Maya's workflow**: look up n-ary drug-drug-population interactions
  (`warfarin + aspirin + elderly -> bleeding risk`) before patient
  discharge. The hyperedge-aware brief surfaces `(anticoagulant=Warfarin,
  antiplatelet=Aspirin, physiologic_process=Hemostasis) --
  drug_drug_interaction` from raw papers, with `--min-confidence 0.9`
  for clinical safety.

- **Liu's workflow**: tune retrieval policy via auto-research loop. We
  found and fixed three stacked bugs that were silently making the
  loop a no-op. After the fix: 30 iterations, 3 accepted, retrieval
  cost 2052 -> 1926.2 (6.1% improvement).

What made this work, more than any technical decision: **at every step
we asked "would Sarah/Maya/Liu use this tomorrow?" and answered
honestly.** When the answer was no, we fixed the gap. When the answer
was yes, we shipped and added the next persona.

## What this method is NOT

- **Not waterfall-with-personas.** You don't write all personas, then
  all specs, then all code. You write ONE persona, ONE spec slice,
  ONE end-to-end build, then iterate.

- **Not "design thinking" or UX research.** Personas here are
  engineering constraints, not market research. They tell you what to
  build and how to test, not how to position.

- **Not test-driven development.** TDD pins technical contracts; this
  pins user-value contracts. They compose well -- write tests for the
  workflow steps as you build them -- but tests passing is not the
  acceptance signal.

- **Not "agile" or "lean."** Those methods give you process. This
  gives you a single bright-line bar: would this named person use
  this tomorrow.

## The ratchet

After v0.1 ships, every subsequent commit is a ratchet step:

1. Run the workflow. Find the place it falls short of the persona's
   success criterion.
2. Trace the cause to its root.
3. Fix the root cause in one commit.
4. Re-run. Verify the persona-language success criterion is closer to
   met.

Each commit's message names the persona and quotes their criterion. If
you can't write that commit message honestly, you haven't actually
fixed a gap.

## When to add the next persona

Add a second persona only when the first one's primary workflow is
**concretely outperforming** their current alternative. Not "code is
clean enough to extend." Not "I'm bored." When Sarah would actually
use the brief generator tomorrow morning, then Maya gets attention.

This sequencing matters because adding personas before the first one
ships dilutes the bar. Each persona has tradeoffs; making the first
slice work for two personas at once usually means it works for
neither.

## Read next

- [`01-PERSONAS.md`](01-PERSONAS.md) -- how to write a useful persona
- [`02-MVP-BAR.md`](02-MVP-BAR.md) -- defining the bar concretely
- [`VERIFICATION-FIRST.md`](VERIFICATION-FIRST.md) -- the #1 official
  recommendation: give Claude a way to verify its work
- [`CONTEXT-MANAGEMENT.md`](CONTEXT-MANAGEMENT.md) -- `/clear`,
  `/compact`, `/rewind`, the 200k window, auto-compaction
- [`ANTI-PATTERNS.md`](ANTI-PATTERNS.md) -- what to never do
