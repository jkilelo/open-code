# Verification-first

> "Give Claude a way to verify its work. This is the single highest-leverage
> thing you can do."
> -- [Anthropic, Claude Code best practices](https://code.claude.com/docs/en/best-practices)

This is the #1 published recommendation for working with Claude Code,
and it fits the persona-mvp-kit perfectly: a persona's success
criterion is a verification protocol. If you can't verify it, you
can't ship it.

## Why this dominates

LLMs hallucinate confidently. Without a verification loop, "plausible-
looking code" passes for "correct code" until a human runs it. Once
the human is the only feedback loop, every mistake costs them time.

A verification protocol -- a test, a script, a screenshot comparison,
a curl-able endpoint with known expected output -- short-circuits the
feedback loop. Claude runs it, sees if it passes, fixes if it
doesn't. The human's involvement drops to confirming the verification
protocol matches the persona's intent.

## Every persona criterion has a verification method

`mvp-spec.md Sec. "Success criterion"` is the persona's "outperforms"
bar. `mvp-spec.md Sec. "How v0.1 is verified"` is the protocol that
proves the bar is met. The latter is REQUIRED.

Examples of good verification protocols:

| Criterion | Verification protocol |
|---|---|
| "Brief in <30s" | Start a stopwatch in the spec run, fail if >30s |
| "5 bullets with citations" | grep the output for `[^N]` exactly 5 times; assert each `[^N]` matches a URL in the input |
| "Catches contradictions" | A test fixture with 4 articles disagreeing on a number; assert output's "Contradictions" section names all three values |
| "Pastes cleanly to Slack" | Render output in markdown; assert no malformed code fences or unclosed brackets |
| "Mobile-friendly" | Lighthouse audit at viewport 375x812; assert score > 90 |
| "No fabricated citations" | Every `[^N]` in the output points to a span_id that exists in the database; mechanical interval-arithmetic check on the span bytes |

If you can't write a protocol that passes/fails the criterion, the
criterion is too vague. Sharpen the criterion BEFORE writing code.

## Common verification shapes

### Test suite
- pytest / vitest / cargo test with one happy-path + one failure-mode
  test per workflow step
- Run on every build session, not just CI

### Screenshot comparison
- For UI: use Playwright/Puppeteer or Claude in Chrome to take a
  screenshot, diff against a reference
- "make the dashboard look better" without a target screenshot is
  unverifiable

### Curl-able endpoint
- "Run this curl, expect this JSON" -- works for any backend
- Document the curl command in the spec; Claude runs it

### Side-by-side
- For LLM outputs: keep a "gold" output. Compare new output to gold;
  flag drift

### Smell tests
- Output contains expected tokens (entity names, URL patterns,
  numeric values from input)
- Output is well-formed (parseable JSON, valid markdown, no error
  strings)

## Where verification lives

For a v0.1 build:

- `mvp-spec.md Sec. "How v0.1 is verified"` -- the protocol description
- `tests/` -- code that runs the protocol
- `runs/YYYY-MM-DD-vX.Y.Z.md` -- verbatim record of each run + the
  five-question report

Each `runs/` file is the audit trail. When the user asks "is it
ready?", you point to the latest `runs/` file.

## When verification is hard

Some persona criteria are inherently fuzzy:

- "The brief is well-written"
- "The output feels professional"
- "The UI is delightful"

These need *operationalization*:

> "Well-written" = <=2 grammatical errors per 100 words, run a
> grammar checker as part of verification.

> "Professional" = no all-caps, no exclamation marks except in
> direct quotes, sentence length variance > 5 words.

> "Delightful" = 5/5 people in a 5-person test cohort prefer
> v0.1 over their current workflow.

If you can't operationalize, run the workflow as the persona and let
their immediate reaction be the verification. Save the reaction
verbatim to `runs/`.

## Anti-patterns

### Verification that mocks the thing being verified

> [FAIL] "The brief generator returns >=4 bullets" + the test mocks the
> LLM to return exactly 4 bullets.

This tests that the mock returns what the mock returns. It doesn't
verify anything about the brief generator.

Verification must hit the real system at least once per build.

### Tests that pass when the workflow is broken

> [FAIL] A test that asserts `len(result.bullets) >= 0`. Always passes.
> Persona criterion ("5 bullets") not actually checked.

Tests should assert what the persona CARES about, not what's easy
to assert.

### Asserting that code didn't crash, not that output is right

> [FAIL] `assert result is not None`. Doesn't say what `result` should
> contain.

The check must be specific enough that a sneaky bug producing
wrong-but-non-null output would fail it.

### Skipping verification for "trivial" changes

> [FAIL] "It's just a config change, I'll skip the verification this
> time."

Config changes break verification routinely. Always run.

## The trust-then-verify gap

From the official docs:

> The trust-then-verify gap: Claude produces a plausible-looking
> implementation that doesn't handle edge cases.
> Fix: Always provide verification (tests, scripts, screenshots).
> If you can't verify it, don't ship it.

This is the persona-mvp-kit's bright line #4 ("Never claim done
without running the workflow yourself"), restated.

## Reference

- [Claude Code best practices Sec. Give Claude a way to verify its work](https://code.claude.com/docs/en/best-practices)
- `@methodology/04-RUN-THE-WORKFLOW.md` -- how to run as the persona
- `@methodology/05-BRUTAL-REVIEW.md` -- how to interpret the verification
- `@templates/mvp-spec.md` -- Sec. "How v0.1 is verified" template
