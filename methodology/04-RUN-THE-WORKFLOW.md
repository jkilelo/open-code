# 04 — Run the workflow as the persona

This is the step most LLM-assisted builds skip. Don't skip it.

## What "run as the persona" means

Stop being the developer. Become Sarah. Or Maya. Or whichever persona
the slice shipped for. Open their tools (terminal, browser, whatever
they actually use). Type what they would type. Click what they would
click. Read the output the way they would read it — before their
9:30am committee email, with two minutes' attention, while distracted.

## The five questions you answer after running

After executing the workflow, write a short report addressing these
five questions in order:

### 1. Did the workflow complete without you, the developer, intervening?

If you had to ssh in to fix a path, edit a config, restart a process,
or deserialize a JSON manually, the persona would not have completed
it. The slice fails this question.

> ❌ "It works after I added the API key to .env and restarted."
> ✅ "From cold start: she runs `npm run dev`, opens localhost:3000,
>     pastes 4 URLs, clicks summarize, sees brief in 22s."

### 2. Does the output meet the success criterion stated in `mvp-spec.md`?

Re-read the criterion. Look at the output. Quote the part that
satisfies it (or doesn't).

> ✅ "Criterion: 'brief includes a Contradictions section listing
>     numerical disagreements.' Output:
>     `Contradictions:
>      - Funding amount: $80M (fact 3, 4, 5) vs $100M (fact 6) vs
>        $120M (fact 1, 7)`. Met."

### 3. What's faked, mocked, or hardcoded that the persona would notice?

Be specific. The user trusts your report; if you fudge it, they ship
broken code.

> ❌ "Everything is real."
> ✅ "Three things are fake:
>     - The 'history' page reads from a hardcoded JSON file, not the
>       database. (Real DB write is in the workflow; the history
>       page render isn't wired yet.)
>     - The 'export to email' button shows a toast but doesn't send
>       email — Sam would notice on first click.
>     - LLM model is hardcoded to 'gpt-4o-mini'; the spec said
>       'configurable per request' but I didn't surface a UI knob."

### 4. What gaps did you observe but not fix yet?

These go into `gap-log.md`. One line per gap, naming the persona and
the criterion it blocks.

### 5. Would the persona use this tomorrow morning, in their actual
context, instead of their current workflow?

This is the only question that matters. Answer yes/no, then explain.

> ❌ "It's a great start."
> ✅ "No, not yet. Two reasons: (a) brief takes 50s in real conditions
>     because the LLM call is on a cold path with no caching; Sarah's
>     SLA is 30s before her email. (b) The contradiction detector
>     missed one obvious cross-source disagreement in our test
>     because the brief prompt didn't include verbatim source
>     snippets — only abstracted edge tuples."

## Real-world test conditions, not toy fixtures

A persona's workflow runs on real data. Your test must too:

- **Real LLM API**, real key, real latency. Don't use a mock that
  returns the canned answer your code expects.
- **Real corpus**, the actual size and shape the persona will hand
  it: not 3 spans, but 30 or 300.
- **Real time pressure.** If the persona's criterion is "<30s," start
  a stopwatch. If it's "fits on a phone screen," open a phone-sized
  viewport.
- **Real adversarial inputs.** What if the persona gives you a 0-byte
  file? A binary file mislabeled as text? An LLM that returned
  malformed JSON? These are the inputs the persona will accidentally
  send.

If you don't have real data, ask the user for some before declaring
the workflow done.

## Persona drift: the failure mode

A common failure: you adopt the persona but unconsciously soften the
criterion. You say "Sarah would use this" because the brief is "good
enough" — even though the spec said `<30s` and your build hits 50s.

Counter this by **re-reading the spec criterion verbatim** before
each run. Quote it back to yourself. Then run.

If you can't quote the criterion verbatim, the spec was too vague.
Fix the spec before fixing the code.

## When the workflow doesn't run

Don't bandage. Don't add try/except around the failure. Don't pivot
to "let me build a different feature that does work."

Trace the cause. See `06-FIX-ROOT-CAUSES.md`.

## When the workflow runs but feels off

Trust that feeling. The persona's actual user has it too. Examples
from the agentGraph build:

- "Sarah's brief catches the contradiction but the formatting is
  slightly off — the citation marker is `[fact_id=4]` instead of
  `[^4]`. She'd find that ugly." → small fix, ship it.

- "Maya's brief surfaces hyperedges but the member labels are raw
  64-char hashes when the node isn't in the binary-edge neighborhood."
  → real bug; trace and fix.

- "Liu runs autoresearch and gets `accepted=0` on every iteration
  with every program.md she writes." → silent regression; trace
  three layers deep, fix all three.

In the third example, the temptation is to write a comment explaining
why `accepted=0` is correct. Resist. The persona's success criterion
("see autoresearch improve retrieval cost") wasn't met; trace the
chain of cause until you find the layer that would have to change
for the criterion to be met.

## Running the workflow on multiple personas

If v0.1 ships for one persona but you have 4 in `personas.md`, run
the workflow for ONLY the first persona during build. Don't dilute
the bar by trying to satisfy multiple personas in v0.1.

When v0.1 satisfies persona 1, then re-read persona 2's `mvp-spec.md`
section, write what changes for them, build the increment, then
re-run as persona 2. Each persona is its own ratchet.

## Documenting the run

Save the run output to `runs/YYYY-MM-DD-vX.Y.Z.md`. Includes:

- Persona name + criterion (verbatim from spec)
- Command invocations + verbatim output
- Wall-clock time per step
- The five-question report above
- Any screenshots (if a UI is involved)

This file is the audit trail. When the user asks "is it ready?", you
point to the latest `runs/` file.

## Read next

- [`05-BRUTAL-REVIEW.md`](05-BRUTAL-REVIEW.md) — turning the run report
  into a critique
- [`06-FIX-ROOT-CAUSES.md`](06-FIX-ROOT-CAUSES.md) — when you found
  a gap, fix it correctly
