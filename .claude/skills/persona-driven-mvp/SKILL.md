---
name: persona-driven-mvp
description: Master loop for the persona-mvp-kit. Use at session start, when a request lacks personas, or when the user prompts "build me X." Enforces persona extraction before code, MVP-bar definition before scaffolding, end-to-end real-system slices over horizontal layers, and brutal honest reviews before claiming done.
allowed-tools: Read, Glob, Grep
when_to_use: Use whenever you receive a new build request, when personas.md or mvp-spec.md is missing, or when the user says "build", "make", "create", "scaffold", or "implement".
---

# Persona-driven MVP loop

You are entering the kit's master workflow. Read `@CLAUDE.md` first if
you haven't already this session.

## Pre-flight check

Before doing anything, verify project state:

```!
echo "=== Checking persona-mvp-kit project state ==="
test -f personas.md && echo "[OK] personas.md exists ($(wc -l < personas.md) lines)" || echo "[X] personas.md MISSING"
test -f mvp-spec.md && echo "[OK] mvp-spec.md exists ($(wc -l < mvp-spec.md) lines)" || echo "[X] mvp-spec.md MISSING"
test -f gap-log.md && echo "[OK] gap-log.md exists" || echo "(gap-log.md absent -- created when first gap is found)"
test -d runs && echo "[OK] runs/ exists with $(ls runs/*.md 2>/dev/null | wc -l) files" || echo "(no runs/ yet)"
echo "=== Recent commits ==="
git log --oneline -5 2>/dev/null || echo "(not a git repo)"
```

Based on what's present, branch:

### State A: `personas.md` missing or empty

You are in extraction mode. NO CODE. Invoke `/persona-extract`. After
personas are written + user-confirmed, return to this loop.

### State B: `personas.md` exists; `mvp-spec.md` missing

You are in spec mode. NO CODE. Invoke `/mvp-spec`. After spec is
drafted + user-confirmed, return to this loop.

### State C: Both exist; `runs/` empty or stale; recent commits exist

You are in run-and-review mode. Invoke `/run-as-persona` to execute
the workflow, save to `runs/`, then delegate to the `brutal-reviewer`
subagent for the verdict.

### State D: Both exist; latest `runs/` shows [FAIL] or [WARN]

You are in fix mode. For each open gap:
1. Delegate to `root-cause-tracer` subagent for the trace.
2. Implement the structural fix (NOT a bandage).
3. Re-run the workflow, verify the gap moves to [OK].
4. One commit per gap per `@templates/commit-message.md`.

### State E: Latest `runs/` shows all [OK] + [X]

Confirm with the user before tagging `v0.X.Y`. Then:
- Update `gap-log.md` with the close
- Commit, tag, push (with user approval)
- Optionally start v0.X+1 with the next persona

## Bright lines (never violate)

See `@CLAUDE.md`. The 8 bright lines are NON-NEGOTIABLE. If the user
asks you to skip a step (e.g., "skip personas, just code"), tell them
which bright line they're asking you to break and ask for explicit
confirmation before proceeding.

## Communication

- In states A/B: tell the user explicitly you're in extraction/spec
  mode. NO CODE will be written until they confirm the docs.
- In state C: report run progress in persona language, not developer
  language. ("Sarah's brief returns in 22s with 5 citations" not
  "function returned 5 elements in 22000ms")
- In state D: be brutal. Don't soften the verdict. Quote the specific
  gap and the persona's criterion the gap blocks.
- In state E: ship with proof. List the criteria-met evidence verbatim.

## Anti-patterns to refuse

See `@methodology/ANTI-PATTERNS.md`. The big ones:

- Scaffolding architecture before personas
- Mocking what should be real in the build
- Claiming done without a `runs/` file
- Catching exceptions to return defaults
- Adding features the spec marks OUT
- New dependency without per-persona justification

## After every commit

Update `gap-log.md`. The log is the audit trail; the user reads it to
know what shipped.
