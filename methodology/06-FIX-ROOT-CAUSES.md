# 06 -- Fix root causes

> When the brutal review found a gap, your next move decides whether
> you're shipping software or papering over rot.

## The trap: symptom-fixing

When the workflow doesn't work, the natural instinct is to make the
specific failure go away. That's a trap. Examples:

- The brief returns 0 bullets -> cap min_bullets to 1 with a default
  "no facts available" placeholder. **No.** The 0 bullets is a
  symptom; trace why no facts came back.

- The latency exceeds 30s -> add a UI spinner that distracts from the
  wait. **No.** The 30s is a symptom; trace which call dominates and
  fix that.

- The query returns empty results when it shouldn't -> catch + return
  a hardcoded fallback. **No.** Empty result is a symptom; trace
  what's filtering everything out.

- A test fails intermittently -> mark it `@pytest.mark.flaky` and
  retry 3 times. **No.** Flakiness is a symptom; the test is detecting
  a real concurrency or state issue. Find it.

Each of these "fixes" makes the immediate complaint quiet but leaves
the original failure in place, ready to surface in a different shape.
The user will hit it tomorrow, with less context to diagnose it.

## The trace-three-deep rule

When the workflow surfaces a gap, ask **why** three times before you
start fixing.

Worked example from the agentGraph build (autoresearch was always
returning `accepted=0`):

> **Gap:** Liu's autoresearch loop accepts 0 mutations on every run,
> regardless of mutator config or budget.
>
> **Why 1:** Because `accepted = (post_fitness < pre_fitness)` is
> always false. So `pre == post` for every iteration.
>
> **Why 2:** Because `pre == post` means the fitness function is
> returning the same value before and after the mutation. So the
> mutation isn't affecting what fitness measures.
>
> **Why 3:** Because `retrieval_cost(store, suite)` was implemented
> as `sum(span.text length) / len(suite)` -- a property of the store,
> not of how queries are answered. Mutations don't change the store.

Stopping at "why 1" leads to: "make the comparison `<=`." Symptom
fixed; bug intact.

Stopping at "why 2" leads to: "force the fitness function to return
different values somehow." Hacky; bug still intact.

Going to "why 3" exposes the actual cause: the fitness function was
the wrong shape. Rewrite it to actually run queries through the
executor with the live config. Now mutations change what queries
return, fitness changes, the loop accepts good mutations, ratchet
engages.

## When fixes stack

Sometimes one fix reveals another. In the autoresearch case, after
fixing fitness:

> **Why 4 (next layer):** Now fitness runs queries, but RRF weight
> changes still don't affect output. Why? Because the executor
> derives `hybrid_node_ids` from a SET of fused span_ids. Set
> membership is order-independent. Without a top-K cap, the same
> set comes out regardless of order.
>
> **Why 5:** Even with a cap, the executor sorts results
> alphabetically before returning, destroying RRF order.

Three independent bugs stacked. Each one had to be fixed before the
loop could demonstrate value. Patching only the surface bug would
have left the user with a "fixed" loop that still didn't work.

The discipline: after each fix, re-run the workflow as the persona.
If the original gap recurs in a different shape, you have another
layer to fix.

## Refusal patterns

When tempted by these, refuse:

- **"Let me catch this exception and return a default."** The
  exception is signaling a bug. Returning a default hides it.
  Find the bug.

- **"Let me feature-flag this off until I figure it out."** Feature
  flags belong to A/B tests in production, not to active development.
  If the feature is broken, fix it; don't toggle it.

- **"Let me retry the LLM call up to 3 times."** Retries hide
  intermittent failures. The persona will hit them with no diagnostic
  info. If the LLM is unreliable for your use, log every failure
  loudly so the user can see the failure mode. Add retries only
  after you understand WHY the failures happen.

- **"Let me add `if x is None` defensive checks everywhere."** If a
  value can be `None` and the code wasn't designed for it, the bug
  is upstream -- find why None arrived. Adding `is None` guards
  scatters the upstream bug across many call sites.

- **"This edge case probably won't happen in practice."** If you
  thought of it, the persona will hit it. Either handle it or
  document it loudly in `gap-log.md`.

## Fix locality

A root-cause fix usually touches **fewer** lines than a symptom fix,
because it changes ONE thing in ONE place. If your fix touches 12
files and adds defensive code in each, you're symptom-fixing.

Counter-example from the agentGraph build:

- **Symptom fix would have been:** add `if not facts: return [a
  placeholder bullet]` to `generate_brief()`. 3 lines, 1 file. Hides
  the bug forever.

- **Root-cause fix was:** discover that `_resolve_seed()` picked the
  first label-matching node (often the orphaned one) when the LLM
  produced two same-label nodes with different `entity_type`. Replace
  with `_resolve_seeds()` returning all matches sorted by edge count,
  union their neighborhoods. ~50 lines, 1 file. Bug actually gone.

The root-cause fix is bigger because it understands the problem. The
symptom fix is smaller because it suppresses a side-effect.

## Don't bandage by adding tests around the bug

A common tempting pattern: write a test that asserts the buggy
behavior, then move on. This pins the bug and makes it harder to
fix later. Don't.

Tests should pin the **persona-correct** behavior, not whatever the
code does today.

## When you can't fix the root cause

Sometimes the root cause is structural and out of v0.1 scope. In that
case:

1. Document the gap in `gap-log.md` with the trace-three-deep analysis.
2. Document the SHALLOW workaround you applied as a temporary measure.
3. Mark the workaround with a `# WORKAROUND(persona-mvp-kit):` comment
   citing the gap-log entry.
4. Tell the user explicitly in your final response.

Don't apply a workaround silently. The user must know.

## The fix-and-rerun loop

After every root-cause fix:

1. Run the workflow as the persona.
2. Verify the original gap is gone.
3. Verify no new gap appeared (regression).
4. Update `gap-log.md`: mark the fixed gap as [OK] with the commit SHA.
5. Commit. See `07-SHIPPING.md`.

If you can't get to step 4 with a clear conscience, you haven't
finished the fix.

## Read next

- [`07-SHIPPING.md`](07-SHIPPING.md) -- commit discipline + release
- [`templates/commit-message.md`](../templates/commit-message.md) --
  how the message should look
