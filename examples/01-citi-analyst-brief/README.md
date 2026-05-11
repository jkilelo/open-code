# Worked example 01 — Citi analyst brief generator (agentGraph)

This is the build that produced the persona-mvp-kit. Reading it
end-to-end shows what the methodology looks like in practice when the
domain is non-trivial (LLM-driven knowledge graph) and the persona
gap is concrete (cross-source contradictions in finance news).

The actual code that came out of this lives in
`src/ai_agents/agent_graph/` in the host repo; this README is the
persona-and-process retrospective.

---

## The opening prompt

> Use the same personas to stretch the app — use real use cases where
> these personas face daily issues in their day-to-day activities,
> and how our app helps. Be brutal honest. Anytime you see a gap, fix
> it. Aim for genuinely make the system outperform humans.

There is no "build me X" framing here. The user already had a system
(agentGraph). The kit's loop is identical: extract personas, define
the workflow, build the slice, run as the persona, brutally review,
fix root causes, ship.

---

## Personas (extracted from the prompt + prior context)

### Primary — Sarah Chen

- **Role:** Senior Data Scientist, Citi Risk Analytics, NYC
- **Daily pain:** reads ~200 fintech articles 7-9am every weekday,
  manually cross-references claims across Reuters / FT / SEC filings,
  types notes into Word, updates Excel counterparty tracker, emails
  brief to credit committee by 9:30. Takes 90-120 min. Misses
  ~15% of cross-source contradictions because she can't hold 4
  articles in working memory.
- **Primary workflow:** Given 4-10 articles about a single
  counterparty, produce a 5-bullet brief with citations + an
  explicit list of contradictions across the sources.
- **Success criterion:** Brief in <30s, catches a contradiction the
  human would miss, every claim cited to a source span, ready
  before her 9:30am email.

### Secondary — Maya Patel

- **Role:** Clinical Pharmacist, Mass General
- **Workflow:** n-ary drug-drug-population interaction lookups
- **Criterion:** clinical-grade citation traceback + confidence floor

### Tertiary — Alex Rivera (PyPA), Jamie Park (ProPublica), Liu Wei
(Stanford NLP). Each with their own workflow.

The full personas were in the conversation; they didn't need a
separate `personas.md` because they were established earlier.

---

## MVP bar (Sarah's slice)

The slice that ships v0.1:

> A new CLI subcommand `agent-graph brief --entity "<name>"` that
> walks the entity's neighborhood in the graph, gathers every
> grounded fact (binary edges + n-ary hyperedges + node descriptions),
> sends the facts + verbatim source snippets to Gemini with a prompt
> that requires `[fact_id=N]` citations and explicit contradiction
> detection, and emits markdown with `[^N]` footnotes pointing back
> to source spans.

OUT of this slice (deferred):
- A web UI (Sarah uses CLI)
- Email export
- Multi-LLM
- Streaming
- Auth (Sarah is sole user, runs locally)

---

## Build (the actual session log)

Real systems used:
- Real Gemini API via the user's `.env`
- Real corpus (`tests/eval/corpora/p07_news_contradictions/`) — 4
  Nimbus AI funding articles
- Real SQLite store from prior `agent-graph compile` runs

Build steps, in order:

1. **`brief.py` skeleton**: `_walk_neighborhood`, `_gather_facts`,
   `BriefResult`, `render_markdown`. ~150 lines.
2. **CLI subcommand**: `agent-graph brief --entity X --hops 2`,
   wire to `generate_brief` and `generate_brief_offline`.
3. **First run as Sarah** with `--offline` (deterministic): facts
   surface but as raw `src --[edge_type]--> dst` tuples. No prose.
   No contradiction handling.
4. **First run with real Gemini**: brief is fluent. But:
   `Contradictions: None detected` despite the cited spans clearly
   showing $80M vs $100M vs $120M.

This was the brutal-review moment.

---

## Brutal review (from `runs/2026-05-10-v0.1.0.md`)

The 5-question report:

1. ✅ Workflow ran without intervention.
2. 🔴 **Output FAILED criterion.** "Catches at least one cross-source
   contradiction" — system reported "None detected" while the spans
   themselves contained $80M/$100M/$120M.
3. Nothing faked.
4. Gaps observed:
   - LLM brief prompt only saw abstracted edge tuples, not span text
   - Citation format `[fact_id=N]` instead of `[^N]`
5. **Sarah would NOT use this tomorrow.** It's actively harmful: she'd
   write the wrong number into her credit committee email.

---

## Root-cause trace (3-deep)

> **Why 1:** Gemini said "None detected" → it didn't see the
> disagreement.
>
> **Why 2:** Gemini saw `[edge tuples]` not `[span text]` → the
> prompt didn't include verbatim spans.
>
> **Why 3:** The prompt was written generically without thinking
> about contradiction detection — the FACTS block was a list of
> abstract relations, when contradictions live in the SOURCE TEXT
> describing those relations.

Fix shape: enrich the FACTS block with verbatim span snippets (max
280 chars per fact) AND add explicit instruction to look for
numerical / leadership / date disagreements.

Touched: `brief.py:_BRIEF_PROMPT_TEMPLATE` (one prompt rewrite) and
`brief.py:generate_brief` (one line — include `s.text` in
facts_block formatter).

---

## Re-run (verification)

Same corpus (p07), same query (`brief --entity "Nimbus AI"`), real
Gemini.

Output (verbatim):

```markdown
**Contradictions:**
- Funding amount: $80M (fact 3, 4, 5, 8, 9, 18) vs $100M (fact 6, 10)
  vs $120M (fact 1, 7, 13)
```

🟢 Sarah's criterion concretely met. Workflow now beats her manual
process.

---

## Commits in this slice

```
615d0f0 Sarah: brief catches multi-source contradictions (M3.live.3)
277f48c Jamie: agent-graph conflicts shows fuzzy edge-type variance (M3.live.4)
1d09ab4 Alex: brief merges across LLM-driven label duplicates (M3.live.5)
cad0fc8 Maya: --min-confidence floor for clinical safety (M3.live.6)
3dcf1e6 Liu: autoresearch root-cause fix — accepted=0 → accepted=3 (M3.live.7)
```

Five personas. Five commits. Each commit names its persona, traces
root cause, quotes the verification output. Each commit's message
is unambiguous about what user value shipped and what didn't.

---

## What this example illustrates

- **Personas drive the spec.** Sarah's Tuesday morning is concrete;
  the spec follows from it. Without her, "build a brief generator"
  has 100 valid interpretations.
- **The first build version was wrong.** Brutal review caught it. A
  test-passes-so-done methodology would have shipped a brief that
  silently misled Sarah.
- **Root-cause discipline matters.** The fix was a prompt rewrite, not
  catching an exception or adding a fallback. After the fix, the
  whole class of "didn't see the disagreement" was gone.
- **One commit per gap.** Each persona's gap got its own commit. A
  reader of the git log can reconstruct what each persona got out
  of each session.

---

## What v0.2 would add

- **Sarah's web UI.** CLI works for her data-science setup; her PMs
  want point-and-click. Add a one-page React form.
- **Sarah's overnight delta.** "What changed about Nimbus AI since
  yesterday?" — needs incremental ingest + bi-temporal `--since` brief.
- **Maya's clinical-safety polish.** Confidence floor exists but the
  brief should also flag "fact retracted in a later source" not
  just "not in source."

These wait until v0.1 is concretely ✅ for Sarah.
