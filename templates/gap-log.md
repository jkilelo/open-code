# Gap log

> Running record of what blocks each persona. Update at every step:
> when a gap is found, when fixing starts, when committed.
>
> Status legend:
> - 🔴 OPEN — gap exists, not yet started
> - 🟡 IN PROGRESS — actively being closed; partial code shipped
> - 🟢 CLOSED — verified by `runs/` file; commit SHA recorded
> - ⚫ DEFERRED — out of v0.1, deferred to v0.X.Y by user decision

---

## Primary persona — [Name]

| # | Gap | Status | Closed at | Verification |
|---|---|---|---|---|
| 1 | [One-line description of what's broken from persona's view] | 🔴 | — | — |
| 2 | [...] | 🟡 | — | partial — fix WIP |
| 3 | [...] | 🟢 | abc1234 | runs/2026-05-10-v0.1.0.md § "criterion 3" |

---

## Closure log

> One entry per closed gap. Quote the persona's criterion + the
> verification output that satisfied it. This is the audit trail.

- **2026-05-10 — gap #3 closed by abc1234.** Sarah's criterion
  ("brief catches multi-source numerical contradictions") verified:
  brief on p07 corpus returned `Contradictions: Funding amount: $80M
  (fact 3, 4, 5) vs $100M (fact 6) vs $120M (fact 1, 7)`.

- **2026-05-10 — gap #1 closed by def5678.** ...

---

## Deferred items (not in v0.1)

| # | Gap | Deferred to | Reason |
|---|---|---|---|
| D1 | Multi-tenant database support | v0.3 | Sarah is sole user in v0.1 |
| D2 | Email export of briefs | v0.2 | Sarah pastes to Slack manually |
