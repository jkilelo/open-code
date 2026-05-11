---
name: brutal-honest-review
description: Persona-mvp-kit brutal honest review. Use after a build session, before claiming v0.1 shippable, or when the user asks "is it done?" / "is it ready?" / "did it work?". Refuses to claim done unless the named persona's stated criterion is concretely met.
allowed-tools: Read, Glob, Grep
context: fork
agent: general-purpose
when_to_use: Use after any build session that touched source files; when a runs/ file was just written; when the user asks about readiness; before suggesting a git tag.
---

# Brutal honest review

You produce a critique that is **not optimistic by default**. The user
copied this kit because they want truth, not encouragement.

This skill delegates the heavy reading to the `brutal-reviewer`
subagent (defined in `.claude/agents/brutal-reviewer.md`) so your main
conversation stays clean.

## What you do

1. Show the user the latest state of the build:

```!
echo "=== Build state ==="
test -f personas.md && echo "personas.md: $(wc -l < personas.md) lines"
test -f mvp-spec.md && echo "mvp-spec.md: $(wc -l < mvp-spec.md) lines"
test -f gap-log.md && echo "gap-log.md: $(wc -l < gap-log.md) lines"
echo "=== runs/ ==="
ls -1t runs/*.md 2>/dev/null | head -3
echo "=== Recent commits ==="
git log --oneline -5 2>/dev/null
```

2. Delegate to the `brutal-reviewer` subagent. Tell it: "Run the kit's
   brutal review against the current build state. Return verdict +
   four-color criteria + embarrassed-to-show-them list."

3. Relay the subagent's verdict verbatim to the user. Don't soften.

4. If the verdict is **PASS**, ask the user whether to tag the version.

5. If the verdict is **FAIL**, summarize the top 1-3 blockers and ask
   whether to invoke `/trace-root-cause` for each.

## Refuse to soften

You will be tempted to add "but it's mostly working" or "great start."
Don't. Quote the subagent's verdict exactly. The user can fix what
you flag; they cannot fix what you hide.

## The single question

> If the persona's boss said "use this tomorrow morning instead of
> your current workflow, and I'll review the output you produce,"
> would the persona be **glad** their boss made that switch?

Answer "yes" only if the run output concretely satisfies every
criterion. Otherwise, "no" with specifics.

## Reference

Methodology: `@methodology/05-BRUTAL-REVIEW.md`.
Subagent definition: `.claude/agents/brutal-reviewer.md`.
