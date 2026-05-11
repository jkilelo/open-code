# persona-mvp-kit

A drop-in kit for **persona-driven minimum-viable-product development**
with [Claude Code](https://code.claude.com).

## What this is

A methodology + a portable set of guidelines + Claude Code mechanics
(skills, subagents, hooks, slash commands, settings) that make Claude:

1. **Refuse to write code** until concrete personas are documented (a
   `PreToolUse` hook enforces this — not advisory text)
2. Build the **smallest possible slice that ships an actual user
   workflow end-to-end** before adding anything else
3. **Run the workflow as the persona** against real systems (real
   APIs, real data — never toy fixtures)
4. **Brutally critique** whether the persona would actually use it
   tomorrow, in an isolated subagent context that doesn't bloat the
   main conversation
5. **Fix root causes** — not symptoms — when gaps surface, via a
   trace-three-deep subagent
6. Ship in **tight commits** whose messages quote the persona's
   success criterion

## What it isn't

- Not a code generator. Not a project scaffold. Not a template engine.
- Not a methodology that produces "complete" software in one pass. It
  produces a working slice plus a ratchet of improvements.

## Why personas, not user stories or features

A user story (`As a user, I want X so that Y`) describes a wish. A
feature (`upload form`) describes a thing.

A persona is a **constraint**: a named human with a real job, a real
daily pain, a real workflow they're already doing the slow way. The
persona's daily workflow IS the acceptance test. If your slice doesn't
help that named person tomorrow morning, it doesn't ship — no matter
how good the code looks.

This is the same shift that turned `agentGraph` from "a knowledge
graph library" into a tool that catches multi-source contradictions
($80M / $100M / $120M reported by 4 finance outlets) in 5 seconds
with full citations. Without the Sarah-Chen persona, the same code is
just a graph database.

## How to use

1. **Drop the kit into your project root.** Keep the `.claude/`
   structure intact:

   ```bash
   cp -r persona-mvp-kit/. /path/to/your/project/
   chmod +x /path/to/your/project/.claude/hooks/*.sh
   ```

   See [`INSTALL.md`](INSTALL.md) for full details.

2. **Write your initial prompt.** See
   [`prompts/starter-prompt.md`](prompts/starter-prompt.md). A typical
   example:

   > Build a full-stack FastAPI + SQLite + Tailwind + React app that
   > hosts AI agents. Follow the persona-mvp-kit standard.

3. **Claude reads `CLAUDE.md` first.** That file binds Claude to the 8
   bright lines and the master loop. The `PreToolUse` hook on
   `Edit|Write` deterministically blocks code edits when
   `personas.md` doesn't exist.

4. **Iterate.** Each session adds one ratchet step: another persona,
   another workflow, another root-cause fix.

## Contents

| Path | Purpose |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Auto-loaded master rules. 8 bright lines + `@path` imports. ~130 lines (under the 200-line ceiling). |
| [`CLAUDE.local.md.example`](CLAUDE.local.md.example) | Template for personal gitignored overrides (sandbox URLs, preferences). |
| [`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) | Plugin manifest. Lets the kit install as a Claude Code plugin. |
| [`.claude/settings.json`](.claude/settings.json) | Permissions + 5 hooks + `autoMode.hard_deny`. |
| [`.claude/skills/`](.claude/skills/) | Four skills with modern frontmatter (`allowed-tools`, `context: fork`, dynamic context injection). |
| [`.claude/agents/`](.claude/agents/) | Three subagents (persona-validator, brutal-reviewer, root-cause-tracer). |
| [`.claude/hooks/`](.claude/hooks/) | Five hook scripts: require-personas (PreToolUse), remind-gap-log (PostToolUse), enforce-verification (Stop), session-start-context (SessionStart, dynamic), check-prompt-bypass (UserPromptSubmit). |
| [`.claude/rules/`](.claude/rules/) | Five path-scoped rules. Load only when matching files are edited — kit guidance "near" Claude without bloating CLAUDE.md. |
| [`.claude/commands/`](.claude/commands/) | Four slash commands: /persona-extract, /mvp-spec, /run-as-persona, /trace-root-cause. |
| [`.claude/output-styles/`](.claude/output-styles/) | `persona-driven.md` — system-prompt-level framing in persona language. |
| [`.mcp.json.example`](.mcp.json.example) | MCP server template. Rename to `.mcp.json`. |
| [`methodology/`](methodology/) | 11 docs Claude reads on demand. Includes `CLAUDE-CODE-MECHANICS.md` cataloging the kit's 10-layer enforcement stack. |
| [`templates/`](templates/) | Fill-in templates for personas, spec, gap-log, commit messages. |
| [`examples/`](examples/) | Two worked examples (agentGraph retro + FastAPI/React walkthrough). |
| [`prompts/`](prompts/) | Initial prompt shapes. |

## Quick start

```bash
# 1. Install the kit
cp -r persona-mvp-kit/. my-new-app/
chmod +x my-new-app/.claude/hooks/*.sh
cd my-new-app/

# 2. Initialize git so commits work
git init && git add . && git commit -m "Adopt persona-mvp-kit"

# 3. Open Claude Code and prompt:
#    "Build a [...] app. Follow the persona-mvp-kit standard."
```

## What you should expect

**Session 1:** Claude won't write code. The `PreToolUse` hook blocks
any source-file edit. Claude asks 2-4 extraction questions, drafts
`personas.md` + `mvp-spec.md`, and waits for your confirmation.

**Session 2:** Claude builds the smallest end-to-end slice. Real
systems, real wiring. Runs the workflow as the persona, saves output
to `runs/`. Brutal-reviewer subagent reports honestly: 🟢/🟡/🔴/⚫.

**Session 3+:** One root-cause fix per session, one ratchet
improvement per commit, until the persona's success criterion is
concretely 🟢. Then add the next persona.

## Aligned with official Claude Code best practices

The kit uses every documented Claude Code mechanic that helps its
purpose. See [`methodology/CLAUDE-CODE-MECHANICS.md`](methodology/CLAUDE-CODE-MECHANICS.md)
for the full 10-layer enforcement stack. Highlights:

- **CLAUDE.md under 200 lines** with `@path` imports — long files
  get half-ignored per official guidance
- **`.claude/rules/`** with `paths:` frontmatter — rules load only
  when matching files are edited, keeping always-on context tiny
- **Skills with progressive disclosure** — descriptions cost ~100
  tokens; full bodies load on demand; dynamic context injection
  via `` !`shell command` `` syntax
- **Skills with `context: fork`** — heavy work runs in subagent
  context, keeping main conversation clean
- **Three subagents** for isolated reading (persona-validator,
  brutal-reviewer, root-cause-tracer)
- **Five hooks** for deterministic enforcement:
  - `PreToolUse` blocks code edits without personas (exit 2)
  - `PostToolUse` reminds gap-log updates
  - `Stop` soft-blocks turn-end without verification
  - `SessionStart` injects dynamic project state
  - `UserPromptSubmit` detects bypass patterns
- **Permissions** with conservative allow/ask/deny + `autoMode.hard_deny`
- **`AGENTS.md` compatibility** via `@AGENTS.md` import (cross-tool)
- **`/init` and `CLAUDE_CODE_NEW_INIT=1`** interactive setup (see
  INSTALL.md)
- **Plugin manifest** (`.claude-plugin/plugin.json`) for marketplace
  distribution
- **Output style** for system-prompt-level persona framing (optional)
- **Verification-first** — see
  [`methodology/VERIFICATION-FIRST.md`](methodology/VERIFICATION-FIRST.md)

References: [Best practices](https://code.claude.com/docs/en/best-practices) ·
[Skills](https://code.claude.com/docs/en/skills) ·
[Hooks](https://code.claude.com/docs/en/hooks) ·
[Subagents](https://code.claude.com/docs/en/sub-agents) ·
[Memory](https://code.claude.com/docs/en/memory) ·
[Plugins](https://code.claude.com/docs/en/plugins).

## License

Use this freely. Adapt it freely. If you make it better, send a PR.
