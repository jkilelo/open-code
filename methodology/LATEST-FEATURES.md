# Latest Claude Code features the kit uses

Snapshot as of 2026-05-10 (Claude Code v2.1.136). The kit is wired
to use everything below. If you're on an older version, some features
may need a `claude --version` check + upgrade.

## v2.1.128+ (Week 19, May 4-8 2026)

- **`autoMode.hard_deny`**: unconditional block in auto mode,
  regardless of allow rules. The kit uses this for destructive
  commands (`rm -rf`, `sudo`, `curl|sh`).
  See `.claude/settings.json Sec. "autoMode.hard_deny"`.

- **Hooks receive `effort.level`**: hooks see the current effort
  setting via JSON input + `$CLAUDE_EFFORT` env var. The kit's
  hooks don't currently use this but could (e.g., skip
  expensive checks at `low` effort).

- **`--plugin-url`**: load a plugin from a remote .zip URL for one
  session. Useful for trying a plugin before adding to a
  marketplace.

- **Worktree `baseRef`**: `fresh` (remote default) or `head` (local
  HEAD). Default `fresh`.

## v2.1.120+ (Week 18, Apr 27-May 1 2026)

- **`PostToolUse.updatedToolOutput`**: hooks can replace tool
  output. The kit doesn't currently use this but could (e.g.,
  inject persona-language framing on tool results).

- **`/skills` type-to-filter**: search box in the skill picker.
  No kit config change; just easier to find skills in a long list.

- **`claude ultrareview`**: non-interactive `/ultrareview` for CI.
  Mention in the kit's CI section if you add one.

- **`--dangerously-skip-permissions`**: bypasses prompts for
  `.claude/`, `.git/`, shell configs, etc. The kit's hooks still
  fire -- exit 2 from `require-personas.sh` still blocks.

- **MCP servers `alwaysLoad: true`**: opt out of tool-search
  deferral. The kit's MCP examples don't need this.

## v2.1.114+ (Week 17, Apr 20-24 2026)

- **`/ultrareview`** (research preview): cloud-based fleet of
  bug-hunting agents. Run before merging critical PRs. The kit's
  brutal-reviewer subagent is the local equivalent; for high-stakes
  branches, run both.

- **`/recap`**: one-line session recap when you switch back to a
  terminal. Useful when running parallel kit sessions.

- **Hooks `type: "mcp_tool"`**: hooks can call MCP server tools
  directly without spawning a process. The kit's hooks are shell
  scripts; switching to mcp_tool is a future option for
  cross-platform robustness.

- **`/cost` and `/stats` -> `/usage`**: merged. Same info, one
  command.

- **`autoMode.allow/soft_deny/environment` with `"$defaults"` token**:
  compose with built-in classifier rules. The kit uses
  `["$defaults"]` in `allow` and `soft_deny`.

- **`CLAUDE_CODE_FORK_SUBAGENT=1`** (external builds): forked
  subagents inherit full conversation context. The kit's
  brutal-reviewer benefits from this -- set the env var if your
  build needs full context for the review.

- **Default effort `high` for Opus/Sonnet 4.6 (Pro/Max)**: was
  `medium`. Affects how much thinking Claude does per turn.

## Custom statusline (long-established, now used by the kit)

The kit ships `.claude/hooks/statusline.sh` which renders:

```
[persona-mvp-kit] P:[OK] S:[OK] R:3 | gap: 2[FAIL] 5[OK] | main
```

- P = personas.md present
- S = mvp-spec.md present
- R = count of runs/ files
- gap = open / closed gap counts
- branch = current git branch

Always visible at the bottom of Claude Code. The kit's enforcement
state is now a HUD, not a black box.

## Auto-memory (`MEMORY.md`)

Per-project, machine-local at `~/.claude/projects/<project>/memory/`.
First 200 lines load every session. Claude writes to it organically
as it discovers project patterns.

The kit doesn't seed `MEMORY.md` (it would be wrong; the file is
machine-local). Instead:

- Use `/memory` to view what auto-memory has learned
- If a recurring kit-related pattern emerges (e.g., "Sarah always
  wants briefs in markdown, never JSON"), let auto-memory keep it
- For project-wide patterns the team needs to see, add to
  `personas.md` or a `.claude/rules/<topic>.md` instead

## MCP Memory server (cross-project learning)

For knowledge that spans MANY projects (e.g., "this org always uses
pnpm"), add the MCP Memory server (see `.mcp.json.example`). It
maintains an entity-relation graph Claude can query across projects.

## Cross-tool compat: AGENTS.md

If your repo also has `AGENTS.md` (Cursor, Windsurf, others use it),
the kit's CLAUDE.md has a commented `@AGENTS.md` line. Uncomment it
to import AGENTS.md alongside the kit's rules, so both tools see
the same instructions.

## What's NOT in the kit (deliberately)

These features exist but the kit doesn't ship config for them.
Adopt per project if relevant:

- **`agent` setting** (activate a custom agent as the main thread):
  too aggressive for a default -- would prevent normal sessions
  from working outside the kit's loop. Add to your project's
  `settings.local.json` if you want it.

- **Sandboxing**: OS-level isolation. Project-specific. The kit's
  permission allowlist + hooks are usually enough.

- **Voice dictation**: not relevant to MVP development.

- **Agent teams**: multi-session coordination. Out of scope for a
  single-developer kit.

- **GitHub Actions integration**: enable when you have CI and want
  Claude reviewing PRs.

- **Computer use**: not relevant.

## Upgrading

```bash
# Check version
claude --version

# Update (varies by install method)
# Homebrew:
brew upgrade claude-code
# npm:
npm install -g @anthropic-ai/claude-code@latest
# Direct install: re-run the install script
```

After upgrade, run `/init` to see if the kit's CLAUDE.md needs any
refinements based on new features.
