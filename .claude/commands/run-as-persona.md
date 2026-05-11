---
description: Adopt the primary persona and run their workflow against the current build. Save honest report to runs/.
---

You are switching from developer mode to persona mode under the
persona-mvp-kit standard.

Pre-conditions:
- `personas.md` and `mvp-spec.md` exist and are confirmed.
- A build is in place (the slice runs, even if rough).

Steps:

1. Read `mvp-spec.md` § "How v0.1 is verified." That's your script.

2. Read `personas.md` § Primary. Quote the success criterion verbatim.

3. Execute the script. Real systems only:
   - Real LLM API key (load `.env`)
   - Real input format the persona will use
   - Real time pressure (start a stopwatch if latency is in the spec)
   - Real environment (their browser, their terminal)

4. Save the run output to `runs/YYYY-MM-DD-vX.Y.Z.md`. Include:
   - Persona name + criterion (verbatim from spec)
   - Every command + verbatim output
   - Wall-clock time per step
   - Screenshots if a UI is involved

5. Answer the **five questions** in the run file:

   1. Did the workflow complete without developer intervention?
   2. Does the output meet the spec criterion? (Quote criterion and
      relevant output verbatim.)
   3. What's faked / mocked / hardcoded that the persona would
      notice? Be specific.
   4. What gaps did you observe but not fix? (List for `gap-log.md`.)
   5. Would the persona use this tomorrow morning, in their actual
      context, instead of their current workflow? Yes/no + 2-4
      sentence explanation.

6. Color-code each criterion in `mvp-spec.md`:
   - 🟢 met (quote the satisfying output)
   - 🟡 partial (specify the gap)
   - 🔴 failed (name what's broken)
   - ⚫ N/A (confirm still OUT)

7. Tell the user the verdict and the next step:
   - All 🟢 + ⚫ → "v0.1.0 is shippable. Want me to tag?"
   - Any 🟡 or 🔴 → "Not shippable. Top blocker: [...]. Want me to fix?"

If you can't run the workflow without developer intervention, that's
a 🔴. Don't fudge.

If the workflow runs but the output is "good enough but not actually
better than the persona's current workflow," that's a 🟡.
"Outperforms human" is the bar.

Reference: `methodology/04-RUN-THE-WORKFLOW.md` and
`methodology/05-BRUTAL-REVIEW.md`.
