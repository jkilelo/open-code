# Personas

> Fill out this file before writing any code. The first persona is
> "primary" -- v0.1 ships their workflow. Additional personas are
> backlog (v0.2+).
>
> A useful persona is a CONSTRAINT, not a wish. Specific name, specific
> daily pain, specific success criterion -- see methodology/01-PERSONAS.md.

---

## Primary persona -- v0.1 ships this workflow

### [Name] -- [Job title], [Organization]

**Daily pain (current workflow):**

> Describe what this person does today, in 3-6 sentences. Be specific:
> how often (daily/weekly), how long (X minutes per day), what failure
> rate (Y% of cases produce errors), what does the failure cost them
> (missed work / re-work / embarrassment with their boss).
>
> Example: "Reads ~200 fintech news articles 7-9am every weekday,
> manually cross-references claims across Reuters / FT / SEC filings,
> types notes into Word, updates Excel counterparty tracker, emails
> brief to credit committee by 9:30. Takes 90-120 minutes. Misses
> ~15% of cross-source contradictions because she can't hold 4
> articles in working memory."

**Primary workflow (v0.1 ships this one thing):**

> The single workflow this persona cares most about. Daily, high-pain,
> self-contained.
>
> Example: "Given 4-10 articles about a single counterparty, produce
> a 5-bullet brief with citations and an explicit list of
> contradictions across the sources."

**Success criterion (the "outperforms human" bar):**

> Concrete, measurable, statable in the persona's own language. This
> is the acceptance test for v0.1.
>
> Example: "Brief is produced in <30 seconds (vs 30-45 min manual).
> Catches at least one cross-source contradiction the human would
> have missed. Every claim has a span citation traceable to source
> URL. Briefs are ready before her 9:30am committee email."

**What "no" looks like (anti-success):**

> Outputs that would make this persona NOT use the tool. The mirror of
> the criterion.
>
> Example: "If it ever fabricates a citation. If the brief misses a
> contradiction that's literally in the source text. If it takes
> longer than her current manual process. If she can't trace any
> claim back to a verifiable source URL."

---

## Secondary persona -- v0.2 candidate

### [Name] -- [Job title], [Organization]

[Same fields as above. Will not be served by v0.1; add to v0.2 only
when primary persona's criterion is concretely [OK].]

---

## Tertiary persona -- v0.3+ backlog

### [Name] -- [Job title], [Organization]

[Same fields. Backlog.]

---

## Notes

- If two personas have the same workflow, MERGE them -- one persona is
  enough.
- If two personas have different workflows, only ONE workflow ships in
  v0.1. The other waits.
- If you can't tell whether the persona would say "yes" or "no" to a
  given output, the success criterion is too vague. Sharpen it.
- Personas don't change because the code is hard. Personas change
  because the user discovered the workflow was wrong, or the user
  explicitly approves the change.
