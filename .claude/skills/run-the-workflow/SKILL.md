---
name: run-the-workflow
description: Adopt the primary persona and run their workflow against the current build. Save honest report to runs/. Use after build sessions, before brutal review, or when the user asks "did you run it?"
allowed-tools: Read, Glob, Grep, Bash, Write
when_to_use: Use after a build session that ships a workflow step; before invoking brutal-honest-review; when the user asks "did it work?" / "did you run it?"
---

# Run the workflow as the persona

Stop being the developer. Become the persona. Open the tools they'd
use. Type what they'd type. Read the output the way they would --
distracted, before their morning meeting, with two minutes of
attention.

## Pre-flight

```!
echo "=== Workflow verification protocol ==="
echo "Reading mvp-spec.md Sec. 'How v0.1 is verified'..."
test -f mvp-spec.md && grep -A 20 "How v0.1 is verified" mvp-spec.md || echo "MISSING -- no verification protocol; spec invalid"
echo ""
echo "Real systems available?"
test -f .env && echo "[OK] .env present" || echo "(no .env -- real LLM key required)"
```

If `mvp-spec.md Sec. "How v0.1 is verified"` is missing, the spec is
invalid. Return to `/mvp-spec` to add that section before proceeding.

## What "real" means

The build you run must use:

- **Real LLM API key** from `.env` (not mocked)
- **Real input** the persona will actually use (real URLs, real PDFs,
  real article text -- not toy fixtures)
- **Real time pressure** (start a stopwatch if the spec mentions
  latency)
- **Real environment** (the persona's browser, terminal, phone)

If you don't have real input, ask the user before declaring the
workflow done.

## Execute, capture verbatim

Run the verification protocol from `mvp-spec.md`. Capture:

- Every command typed
- Every output (verbatim)
- Wall-clock time per step
- Screenshots if a UI is involved

Save to `runs/YYYY-MM-DD-vX.Y.Z.md`. Create the `runs/` directory if
absent.

## The five-question report

After running, write this in the `runs/` file:

### 1. Did the workflow complete without you intervening?
If you fixed paths, edited config, restarted services, or manually
deserialized JSON -- the persona would not have completed it. Note this.

### 2. Does the output meet the spec criterion?
Quote the criterion verbatim. Then quote the output that satisfies (or
violates) it.

### 3. What's faked / mocked / hardcoded that the persona would notice?
Be specific. The user trusts your report; if you fudge it, they ship
broken code.

### 4. What gaps did you observe but not fix?
One line per gap. These go to `gap-log.md`.

### 5. Would the persona use this tomorrow morning in their actual
context, instead of their current workflow?
Yes/no + 2-4 sentence explanation.

## Three-times rule

Run the workflow at least three times:

- **Run 1:** happy path -- input you designed for
- **Run 2:** real input -- what the persona actually pastes
- **Run 3:** tired-persona input -- typos, partial input, distracted

Different runs surface different gaps.

## When the workflow doesn't run

Don't bandage. Don't catch the exception. Delegate to
`root-cause-tracer` subagent (or invoke `/trace-root-cause`).

## When it runs but feels off

Trust the feeling. List the off-feeling items in the run file. They
are gap-log candidates.

## Then invoke brutal review

After saving `runs/...md`, invoke `/brutal-honest-review` (or
delegate to `brutal-reviewer` subagent) for the verdict.

## Reference

Methodology: `@methodology/04-RUN-THE-WORKFLOW.md`.
