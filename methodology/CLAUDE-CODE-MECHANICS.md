# How the kit uses Claude Code mechanics

This kit isn't advisory documentation. It's a multi-layered
enforcement system built on the mechanics Claude Code provides. Each
mechanic does one job; together they make the kit's bright lines
non-bypassable without explicit override.

## Layer 1 — Always-loaded context (the rules)

- **`CLAUDE.md`** (project root, 117 lines): the 8 bright lines +
  pointers to everything else via `@path` imports. Loaded at every
  session start; survives compaction (re-read from disk).

- **`.claude/rules/005-context-discipline.md`** (no `paths:`
  frontmatter): universal /clear / /compact / subagent guidance.
  Loaded every session.

Total always-loaded budget: ~120 lines + 5k tokens for skill
descriptions. Well under the 200-line CLAUDE.md target.

## Layer 2 — Conditional context (path-scoped rules)

`.claude/rules/00X-*.md` files load **only when Claude edits a
matching file**. Per the `paths:` frontmatter:

- `001-persona-required-for-source.md` → fires on `src/**`, `lib/**`,
  `app/**`, source-file extensions
- `002-verification-protocol.md` → fires on `tests/**`, test-file
  patterns, `mvp-spec.md`
- `003-no-fakes-in-build.md` → fires on `src/**`, `lib/**`, `app/**`,
  `server/**`, `backend/**`, `frontend/**`
- `004-root-cause-not-symptom.md` → fires on `src/**`, `lib/**`

Effect: the kit's full rule set is "near" Claude only when relevant,
not bloating CLAUDE.md.

## Layer 3 — Skills (on-demand workflows)

`.claude/skills/<name>/SKILL.md` files are auto-discovered. Skill
descriptions (~100 tokens each) are always in Claude's awareness;
full bodies load when invoked (or when Claude auto-determines
relevance).

Kit skills:
- `persona-driven-mvp` — master loop with state-detection
- `brutal-honest-review` — runs in `context: fork` (subagent
  context) to keep main conversation clean
- `minimal-stack-selection` — tech-choice ladder
- `run-the-workflow` — adopt-the-persona protocol

Each skill uses dynamic context injection (`` !`<command>` ``) to
read live project state when invoked.

## Layer 4 — Subagents (isolated contexts)

`.claude/agents/<name>.md` define specialists with their own 200k
window:

- `persona-validator` — validates personas.md quality
- `brutal-reviewer` — runs the four-color review on the build
- `root-cause-tracer` — applies trace-three-deep to a gap

When Claude delegates to a subagent (via Task tool or skill with
`context: fork`), heavy reading happens in the subagent's window.
Main conversation gets the summary, not the file dump.

## Layer 5 — Slash commands (user-invoked workflows)

`.claude/commands/<name>.md`:
- `/persona-extract` — extract personas from a vague request
- `/mvp-spec` — translate personas → spec
- `/run-as-persona` — adopt persona, run workflow, save to runs/
- `/trace-root-cause` — refuse symptom-fixing

These exist alongside skills (skills handle auto-invocation; slash
commands handle explicit user invocation).

## Layer 6 — Hooks (deterministic enforcement)

`.claude/settings.json` registers five hooks:

| Event | Purpose | Behavior |
|---|---|---|
| `PreToolUse` (Edit\|Write) | Block code edits when personas missing | Exit 2 (deny) with diagnostic stderr |
| `PostToolUse` (Edit\|Write) | Remind to update gap-log.md | Stdout note to Claude |
| `Stop` | Block turn-end when source changed since last runs/ | JSON `decision=block` with reason |
| `SessionStart` | Inject dynamic project state | `hookSpecificOutput.additionalContext` reads personas/spec/gap-log/runs |
| `UserPromptSubmit` | Detect bypass-personas patterns | `additionalContext` reminder about bright lines |

Hooks are the only LAYER that enforces deterministically. Skills,
rules, and CLAUDE.md are guidance Claude can talk itself out of;
hooks are shell scripts that don't negotiate.

## Layer 7 — Permissions (capability boundaries)

`.claude/settings.json` `permissions` field:
- `allow`: Read, Grep, Glob, git status/log/diff, ls/find/cat/test
- `ask`: Write, Edit, Bash (unspecified)
- `deny`: rm -rf, sudo, .env edits, .git edits, personas.md/spec
  edits (those go through the kit's workflow)

Plus `autoMode.hard_deny` (v2.1.128+): destructive commands
unconditionally blocked even when running with auto mode.

## Layer 8 — Output style (system-prompt-level framing)

`.claude/output-styles/persona-driven.md` modifies the system prompt
to keep Claude in persona-framing voice. Optional — activate via
`/config → Output style → Persona-driven`. Sticky for the session.

## Layer 9 — Plugin packaging (distribution)

`.claude-plugin/plugin.json` makes the kit installable as a Claude
Code plugin. When installed via marketplace:
- Skills become `/persona-mvp-kit:skill-name` (namespaced)
- All other components install in user/project scope as expected
- `claude --plugin-dir ./persona-mvp-kit` works for local dev too

## Layer 10 — Auto-memory (cross-session learning)

`~/.claude/projects/<project>/memory/MEMORY.md` accumulates what
Claude has learned about the project across sessions. Machine-local,
not committed to git. The kit doesn't seed it; let Claude write to
it organically as it discovers project patterns.

`/memory` command opens the menu to browse/edit.

## How the layers compose

A typical session under the kit:

1. **SessionStart hook** runs → injects current state of personas/
   spec/gap-log/runs as `additionalContext`. Claude knows where
   it's at in the loop.
2. **CLAUDE.md** loads → 8 bright lines + `@path` imports.
3. **`005-context-discipline.md`** rule loads → context hygiene.
4. **`MEMORY.md`** (auto-memory) loads → 200 lines of accumulated
   project lessons.
5. User prompts. **UserPromptSubmit hook** fires → if bypass
   pattern, injects reminder.
6. Claude decides which skill to invoke (auto or via `/skill-name`).
7. If skill has `context: fork`, **subagent** spawns in isolated
   window.
8. Skill invokes Read/Write/Edit tools. **PreToolUse hook** fires:
   - Source file? Check personas.md exists. Exit 2 if not.
   - Source file in src/**? **Path-scoped rules** 001/003/004
     load → persona-required + no-fakes + root-cause guidance.
9. After every tool call, **PostToolUse hook** fires → gap-log
   reminder.
10. Claude tries to end turn. **Stop hook** fires → if source files
    changed since last runs/, soft-block with "run /run-as-persona."

The user only sees Claude's responses and tool results. Behind the
scenes, ten enforcement layers cooperate to keep the kit's bright
lines unbreakable without explicit override.

## When to override

You can override any layer — but you'll do it explicitly:

- **Hook blocks**: see the diagnostic message; either fix the
  prerequisite (e.g., write personas.md) or pass `--permission-mode
  bypassPermissions` for that session
- **Bright line violation**: tell Claude "I'm explicitly overriding
  bright line #N because [reason]" — Claude will note it in
  gap-log.md
- **Disable a hook**: edit `.claude/settings.json` and remove that
  hook block; commit the change so the team sees the override
- **Disable a rule**: rename the file to `.md.disabled` or delete it

Overriding silently breaks the kit. Overriding explicitly is fine
and reversible.
