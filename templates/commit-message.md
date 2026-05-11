# Commit message template

Every commit closes one gap. The message has four sections:

```
<persona-name>: <one-sentence description in the persona's terms>

Persona pain (what was broken from their view):
[2-4 sentences. Specific. Use their language.]

Root cause:
[The trace-three-deep result. NOT the symptom; the underlying cause.]

Fix:
[What you changed. Specific files / functions / lines, but explain
WHY each change addresses the root cause, not what each change does
syntactically.]

Verification (against criterion in mvp-spec.md):
[Quote the criterion verbatim. Then quote the run output that
satisfies it. Cite the runs/YYYY-MM-DD file.]
```

## Worked example

```
Sarah: brief now catches multi-source numerical contradictions

Persona pain: 4 finance articles report different funding amounts
($80M / $100M / $120M) for the same Series B round. Previous brief
silently agreed on "secured Series B funding" -- Sarah would have
written that into the credit committee email and been wrong.

Root cause: the LLM brief prompt only saw abstracted edge tuples
(src --type--> dst), not the verbatim source spans. With no source
text in the prompt, no number-disagreement was visible to the model
at composition time.

Fix: include the verbatim source snippet (max 280 chars per fact)
in the FACTS block of the prompt at brief.py:_BRIEF_PROMPT_TEMPLATE.
Add explicit instruction in the prompt to detect numerical /
leadership disagreements across snippets and return them as a
`contradictions` list referencing fact_ids.

Verification (against criterion: "Catches at least one cross-source
contradiction the human would have missed"): brief on p07 corpus
returned

  Contradictions:
  - Funding amount: $80M (fact 3, 4, 5, 8, 9, 18) vs $100M (fact
    6, 10) vs $120M (fact 1, 7, 13)

See runs/2026-05-10-v0.1.0.md Sec. "Sarah's brief".
```

## Anti-pattern: vague messages

```
fix bug                                # [FAIL] no persona, no context
refactor brief module                  # [FAIL] no user value
add feature                            # [FAIL] which persona benefits?
WIP                                    # [FAIL] never commit WIP
update some files                      # [FAIL] commit body should explain
```

If you can't write a real persona-language message, the commit isn't
ready. Either you don't know what user value you produced, or you
mixed multiple gaps into one commit. Either way, fix it before
committing.

## Co-author tag (optional, useful when AI-assisted)

If the user wants AI-assist attribution, append:

```
Co-Authored-By: Claude <noreply@anthropic.com>
```

If they don't, skip it.
