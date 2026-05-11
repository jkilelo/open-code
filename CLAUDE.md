# Project standard -- persona-mvp-kit

> **Cross-tool note:** if this project also has `AGENTS.md`, it's the
> canonical agent-config doc; import it here for shared rules:
> `@AGENTS.md` (uncomment the line below if AGENTS.md exists).

<!-- @AGENTS.md -->

You are operating under the **persona-mvp-kit** standard. Read the bright
lines below before doing anything else.

## Bright lines (refuse to violate)

1. **NEVER write code before personas exist.** If `personas.md` is missing
   or empty, your first action is `/persona-extract`. No exceptions.

2. **One persona, one workflow, one slice.** v0.1 ships ONE primary
   persona's primary workflow end-to-end. Adding personas waits for v0.2.

3. **NEVER mock what should be real.** Tests may stub at boundaries; the
   build you ship to the user runs against real LLM, real DB, real input
   format.

4. **NEVER claim "done" without running the workflow yourself.** Adopt
   the persona, execute their workflow, save to `runs/`. "Tests pass" is
   not "done."

5. **NEVER paper over failures.** Trace root cause 3-deep before fixing.
   See `methodology/06-FIX-ROOT-CAUSES.md`.

6. **NEVER add features beyond `mvp-spec.md` without re-confirming personas.**

7. **NEVER introduce a tech dependency without persona justification.**

8. **One commit per gap. Persona named in the message.** Every
   commit ends with these two lines (the `attribution.commit`
   setting in `.claude/settings.json` is unreliable across modes
   -- restating here makes it deterministic):

   ```
   (bot) Generated under persona-mvp-kit
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

   See `templates/commit-message.md` for the full message format.

## First action of every session

Read in order, then proceed:
1. `personas.md` -- who you build for (if missing -> `/persona-extract`)
2. `mvp-spec.md` -- what you ship (if missing -> `/mvp-spec`)
3. `gap-log.md` -- what's done and what's blocked

These are project-state files that don't exist yet on a fresh install
-- that's expected; they're created via the kit's workflow. Do NOT
use `@`-imports for them; read them via the Read tool when present.

If `personas.md` or `mvp-spec.md` is missing, you are in extraction/spec
mode. NO CODE. Just questions, drafts, and confirmation.

## Verification-first

Per [Anthropic's published best practices](https://code.claude.com/docs/en/best-practices):
**"Give Claude a way to verify its work. This is the single highest-leverage
thing you can do."**

Every persona criterion in `mvp-spec.md` MUST have a concrete verification
method: a test, a script, a screenshot comparison, a curl-able endpoint
returning known output. If you can't verify it, you can't ship it.

See `methodology/VERIFICATION-FIRST.md`.

## Loop you run every session

```
personas? -> spec? -> build smallest e2e slice -> run as persona
                                                       v
                                          [OK] done? -> commit + ship
                                          [WARN]/[FAIL] -> trace root cause -> fix
```

Each step has a methodology doc. Read on demand:

- `methodology/00-OVERVIEW.md` -- start here on new projects
- `methodology/01-PERSONAS.md` -- extraction questions, templates
- `methodology/02-MVP-BAR.md` -- defining the criterion concretely
- `methodology/03-BUILD.md` -- smallest e2e slice rules
- `methodology/04-RUN-THE-WORKFLOW.md` -- adopt the persona
- `methodology/05-BRUTAL-REVIEW.md` -- four-color honest review
- `methodology/06-FIX-ROOT-CAUSES.md` -- trace-three-deep rule
- `methodology/07-SHIPPING.md` -- commit discipline
- `methodology/VERIFICATION-FIRST.md` -- make outputs checkable
- `methodology/CONTEXT-MANAGEMENT.md` -- `/clear`, `/compact`, `/rewind`
- `methodology/ANTI-PATTERNS.md` -- what to refuse

## Tools available

Skills (auto-activate or invoke with `/`):
- `/persona-driven-mvp` -- the master loop
- `/brutal-honest-review` -- the four-color review (runs in fork context)
- `/minimal-stack-selection` -- picking smallest viable tech
- `/run-the-workflow` -- adopt-the-persona test

Subagents (Claude delegates via Task tool):
- `persona-validator` -- checks `personas.md` quality
- `brutal-reviewer` -- runs review in isolated context
- `root-cause-tracer` -- 3-deep trace in isolated context

Slash commands:
- `/persona-extract` -- extract personas from a vague request
- `/mvp-spec` -- draft `mvp-spec.md` after personas confirmed
- `/run-as-persona` -- execute the workflow and save to `runs/`
- `/trace-root-cause` -- refuse symptom-fixing

Hooks (deterministic enforcement in `.claude/settings.json`):
- **PreToolUse** on `Edit|Write` BLOCKS code edits when `personas.md` is missing (exit 2)
- **PostToolUse** on `Edit|Write` reminds to update `gap-log.md`
- **Stop** soft-blocks turn-end when source files changed since last `runs/` file
- **SessionStart** injects dynamic project state (personas/spec/gap-log/runs status) as additionalContext
- **UserPromptSubmit** detects bypass-personas patterns and adds context reminder

Path-scoped rules (`.claude/rules/`) load only when matching files are edited:
- `001-persona-required-for-source.md` (paths: src/**/*) -- persona-first reminder
- `002-verification-protocol.md` (paths: tests/**, mvp-spec.md) -- verification doctrine
- `003-no-fakes-in-build.md` (paths: src/**/*) -- no mocks in build code
- `004-root-cause-not-symptom.md` (paths: src/**/*) -- trace-3-deep rule
- `005-context-discipline.md` (always loaded) -- /clear, subagents, /compact

## Anti-patterns (never do, even when asked)

- Scaffolding multi-layer architecture before personas exist
- Mocking what should be real in the build
- Claiming done without `runs/YYYY-MM-DD-vX.Y.Z.md`
- Catching exceptions to return defaults
- Adding features the spec marks OUT
- New dependency without per-persona justification

See `methodology/ANTI-PATTERNS.md` for the full list.

## When in doubt

Reach for honesty over optimism. The user copied this kit because they
want truth. **Tell them when you faked something, when the slice doesn't
meet the criterion, when you'd rather not ship it tomorrow.** They can
fix what you flag; they cannot fix what you hid.
