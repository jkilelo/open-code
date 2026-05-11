---
paths:
  - "tests/**/*"
  - "**/test_*.py"
  - "**/*.test.{ts,tsx,js,jsx}"
  - "**/*.spec.{ts,tsx,js,jsx}"
  - "**/*_test.go"
  - "tests.rs"
  - "mvp-spec.md"
---

# Verification protocol rule (tests + spec)

You are editing a test file or the MVP spec. The persona-mvp-kit
treats verification as the highest-leverage activity (per Anthropic
best practices: "Give Claude a way to verify its work -- this is
the single highest-leverage thing you can do").

## Required for every persona criterion

Each entry in `mvp-spec.md Sec. "Success criterion"` MUST have a
verification method. Acceptable shapes:

- **Test code**: pytest/vitest/cargo test asserting concrete output
  shape, not just "doesn't throw"
- **Curl-able endpoint**: a shell command with expected output
  documented in the spec
- **Screenshot comparison**: Playwright/Puppeteer-based, with
  reference image
- **Numeric threshold**: timing assertion, recall threshold, score
  metric -- measurable, not subjective

## Anti-patterns to refuse

- **Tests that mock the system being tested.** A "brief generator
  works" test that mocks the LLM tests the mock, not the generator.
  Hit the real system at least once per verification.
- **Tests that always pass.** `assert len(result) >= 0` always
  passes. Tests must assert what the persona CARES about.
- **Asserting non-null.** `assert result is not None` doesn't
  verify behavior. Assert the actual expected shape.
- **Skipping verification on "trivial" changes.** Config changes
  break verification routinely. Always run.

## When verification is hard

Some criteria are inherently fuzzy ("the brief is well-written").
Operationalize:

- "Well-written" -> <=2 grammatical errors per 100 words (run a
  grammar checker)
- "Professional" -> no all-caps outside quotes, sentence length
  variance > 5 words
- "Delightful" -> 5/5 in a 5-person test cohort

If you can't operationalize, run the workflow as the persona and
save their immediate reaction verbatim to `runs/`. That reaction is
the verification.

See `@methodology/VERIFICATION-FIRST.md` for the full doctrine.
