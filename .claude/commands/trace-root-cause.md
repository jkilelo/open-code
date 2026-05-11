---
description: Apply the trace-three-deep rule to a gap before fixing it. Refuses symptom-fixing.
---

You found a gap during run-as-persona. Before fixing, apply the
trace-three-deep rule from `methodology/06-FIX-ROOT-CAUSES.md`.

Steps:

1. State the gap from the persona's view (not the developer's view):

   > The persona's workflow [does X], but it should [do Y].
   > Concrete example from the latest `runs/` file: [...]

2. Ask "why" three times. Each "why" digs one layer below the previous.

   Example (from agentGraph autoresearch):

   > **Why 1:** Liu's autoresearch loop accepts 0 mutations, so the
   > ratchet does nothing. Why?
   >
   > **Why 2:** `accepted = (post < pre)` is always false because
   > `post == pre` for every iteration. Why?
   >
   > **Why 3:** Because `retrieval_cost(store, suite)` is implemented
   > as `sum(span.text length) / len(suite)` -- a property of the
   > store. Mutations don't change the store, so the metric is
   > constant.

3. Identify the SHAPE of the fix at the deepest layer. Not a one-line
   patch -- the structural change that makes the gap go away.

4. Check for stacked bugs. After the deepest fix, what's the next
   thing that would block the persona's criterion? Sometimes 1 fix
   reveals N more.

5. Report your trace to the user before fixing:

   > Gap: [persona-language description]
   >
   > Trace:
   > - Why 1: [...]
   > - Why 2: [...]
   > - Why 3: [...]
   >
   > Fix shape: [structural change at deepest layer]
   >
   > Stacked bugs likely: [yes/no, list if yes]
   >
   > Want me to proceed with the fix?

6. After confirmation, fix the deepest cause first. Re-run the
   workflow. If a stacked bug surfaces, repeat the trace for it.

7. Once the persona's gap is concretely [OK] in a fresh `runs/` file,
   commit per `templates/commit-message.md` (persona named, root
   cause traced, verification quoted).

Refuse the following symptom fixes:

- Catching the exception that surfaces the gap and returning a
  default value
- Adding a feature flag to hide the broken behavior
- Retrying the failing operation with no understanding of why it
  fails
- Adding `if x is None` guards scattered through the codebase
- Writing a test that asserts the buggy behavior

If the user asks for a quick bandage and you've already traced the
root cause, tell them what the bandage hides and ask if they really
want to skip the proper fix.

Reference: `methodology/06-FIX-ROOT-CAUSES.md`.
