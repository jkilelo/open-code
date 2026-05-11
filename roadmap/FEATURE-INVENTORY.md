# open-code feature inventory & roadmap

> Merged from research into Claude Code's design surface (May 2026) and
> 8 adjacent CLI coding agents (Aider, Cline, Codex CLI, Continue,
> Cursor, Gemini CLI, Crush, Sourcegraph Amp, Windsurf).
>
> Goal: a complete inventory of features that an open-code "full Claude
> Code clone" eventually wants, with explicit have/missing markers
> against today's v0.4.0 build (`open_code.py` 970 + `sessions.py` 479
> + `tools.py` 344 = 1793 LOC).
>
> The companion `PROMPT-PACK.md` ships a copy-paste kit prompt for
> every "missing" entry. Combined, these two documents are the v0.5+
> roadmap.

---

## Current state (v0.4.0) — features already in open-code

These are 🟢 done. They're listed here so the gap analysis is honest
and to define the baseline that each new feature builds on.

| Area | Current | Source pattern |
|------|---------|----------------|
| 4 tools (read_file, write_file, list_dir, run_shell) | 🟢 | Claude Code core |
| File-per-session JSONL storage at `~/.open-code/projects/<encoded-cwd>/<uuid>.jsonl` | 🟢 | Claude Code transcripts |
| Append-only event log (`session`/`msg`/`metrics`/`fallback`/`refusal`/`end`) | 🟢 | Claude Code |
| UUID session IDs | 🟢 | Claude Code |
| Encoded-CWD directory layout | 🟢 | Claude Code |
| `--resume` (most recent in CWD), `--resume-id <uuid>` | 🟢 | Claude Code `--continue` / `--resume` |
| `--list-sessions`, `--list-sessions-all` | 🟢 | Claude Code |
| Resume cap (`--resume-max-messages`, default 80) | 🟢 | open-code-original |
| Cumulative metrics across resume chains | 🟢 | open-code-original |
| Model fallback chain (preview → GA → older GA) | 🟢 | open-code-original |
| Migration from older session storage | 🟢 | open-code-original (v0.2→v0.3) |
| Streaming output via `generate_content_stream` | 🟢 | Claude Code |
| Path sandbox (refuses writes outside CWD) + `--allow-outside-cwd` | 🟡 partial | Claude Code permissions (lighter) |
| Destructive-command denylist (30 patterns, token-aware) + `--allow-dangerous` | 🟡 partial | Claude Code Bash guards |
| `OPEN_CODE.md` project context (walks up ancestors, capped 50KB) | 🟡 partial | Claude Code `CLAUDE.md` |
| `@-file` references in prompts (dedup, trailing punct, subdirs, 200KB cap) | 🟡 partial | Claude Code `@file` |
| REPL mode with 8 slash commands (`/help /exit /clear /sessions /switch /cost /model /dump`) | 🟡 partial | Claude Code REPL |
| Audit trail (tool refusals + model fallbacks as JSONL events) | 🟢 | open-code-original |
| Cross-platform (Windows, WSL Linux verified) | 🟢 | open-code-original |
| OS-LF normalization via `.gitattributes` | 🟢 | open-code-original |
| Test suite: 54-assertion security test + 10 regression probes | 🟢 | open-code-original |

---

## Missing features — prioritized roadmap

Each entry is one row in the roadmap. The PROMPT-PACK.md has a
copy-paste prompt per row, indexed by the same number.

Legend:
- **Impact:** how much this changes Jeff's daily workflow.
- **Complexity:** S (≤100 LOC), M (100-300 LOC), L (>300 LOC).
- **Tier:** T1 (next 3-5 releases), T2 (mid-priority), T3 (advanced/polish).
- **Source:** which tool/project the pattern comes from.

### Tier 1 — Foundation extensibility (ship before T2)

| # | Feature | Source | Impact | Complexity | One-line summary |
|---|---------|--------|--------|------------|------------------|
| 1 | **Hooks system** | Claude Code | high | M | Register PreToolUse / PostToolUse / Stop / SessionStart / UserPromptSubmit handlers via `.open-code/hooks/`; JSON I/O over stdin; exit-code conventions (0=allow, 2=block). |
| 2 | **Settings hierarchy + permission rules** | Claude Code | high | M | 3-tier settings (user / project / local) merging into one `Settings` object; `permissions.{allow,ask,deny}` rules with `Tool` / `Tool(specifier)` matchers. |
| 3 | **Skills system** | Claude Code | high | M | `.open-code/skills/<name>/SKILL.md` with YAML frontmatter; `$ARGUMENTS` interpolation; dynamic context via `` !`cmd` `` ; lazy-load on invocation. |
| 4 | **Subagents / Task tool** | Claude Code | high | L | Spawn isolated-context agents with custom system prompt + tool allowlist; return summary to parent loop. |
| 5 | **Permission modes** | Claude Code | high | S | `default` / `acceptEdits` / `plan` / `auto` / `bypassPermissions` flag controlling tool auto-approval and edit gating. |
| 6 | **Plan/Act mode separation** | Cline | high | S | Plan mode: read-only, produces a structured plan artifact. Act mode: executes the plan. Different models per mode. |
| 7 | **Repo-map (tree-sitter + PageRank symbol skeleton)** | Aider | high | M | Parse every tracked file with tree-sitter, build a definitions/refs graph, PageRank-rank for the active task, inject ~1k tokens of symbol skeleton into the system prompt. |
| 8 | **V4A `apply_patch` envelope** | OpenAI Codex CLI | high | M | Single tool replacing read/write/edit: `*** Begin Patch / *** Add File / *** Update File / *** End Patch` with `@@` hunks anchored by surrounding code (not line numbers). |
| 9 | **Architect/editor model split** | Aider | high | S | A reasoning model writes a plan; a cheap "editor" model converts it to actual edits. Pair Gemini 3 Pro + Flash for ~5x cost reduction with no quality drop. |
| 10 | **MCP server support (stdio transport)** | Claude Code / industry | high | L | Connect to Model Context Protocol servers; auto-discover their tools; multiplex into the agent's TOOL_DECLARATIONS. |

### Tier 2 — Robustness + UX power-ups

| # | Feature | Source | Impact | Complexity | One-line summary |
|---|---------|--------|--------|------------|------------------|
| 11 | **Shadow-git checkpointing** | Cline / Gemini CLI | high | M | Per-tool-call filesystem snapshots in a separate shadow repo (`~/.open-code/checkpoints/<session>/`); `/restore <id>` reverts files + conversation pointer. |
| 12 | **Atomic-commit-per-turn** | Aider | medium | S | Optional: every accepted change committed to the user's real git with an LLM-written message. Real git history becomes the audit log. |
| 13 | **`/compact` slash command** | Claude Code | medium | S | Summarize older history into a single condensed `msg` event; keep the last N turns verbatim; the cumulative metrics record the compaction. |
| 14 | **Status line** | Claude Code | medium | S | Persistent footer (or stderr widget) showing model, effort, context-token usage, cumulative cost; updated each turn. |
| 15 | **Effort levels** | Claude Code | medium | S | `/effort low|medium|high|xhigh` slider that maps to model + thinking-budget params; per-turn override. |
| 16 | **Extended thinking / `ultrathink`** | Claude Code | medium | S | A flag or in-prompt token that bumps the model's thinking-budget for one turn. Gemini 3 supports an explicit `thinking_config`. |
| 17 | **Sticky session permissions** | OpenAI Codex CLI | medium | S | Permissions chosen in one invocation persist across `--resume`; written to a `permissions` event in the JSONL. |
| 18 | **Four-tier memory** | Gemini CLI | medium | S | `~/.open-code/OPEN_CODE.md` (global) → `./OPEN_CODE.md` (project, committed) → `./<subdir>/OPEN_CODE.md` (subdir override) → `./.open-code/MEMORY.md` (private/uncommitted), concatenated in order. |
| 19 | **Extended @-mention context providers** | Continue | medium | S each | `@diff`, `@terminal`, `@problems`, `@folder`, `@tree`, `@open`, `@docs` — each yields tokens via a small adapter. |
| 20 | **Non-interactive `--print` + JSON stream output** | Codex CLI / Claude Code `--output-format stream-json` | medium | M | Headless mode: emit one JSON object per event (`tool_call`, `assistant_message`, `apply_patch`, `cost`) to stdout. Pipe-friendly. |
| 21 | **Skill prompt caching (1h)** | Claude Code | medium | S | If the model supports prompt caching, mark the SYSTEM_INSTRUCTION + skills + OPEN_CODE.md as a cacheable prefix to cut latency/cost on repeated turns. |
| 22 | **Plugin system + marketplace** | Claude Code | medium | L | `.open-code-plugin/plugin.json` manifest bundling skills, agents, hooks, MCP configs, denylist patches. Namespaced (`plugin:skill`). `--plugin-dir` / `--plugin-url`. |
| 23 | **Output styles / theming** | Claude Code | low-med | S | User-pickable color scheme + glyph set for the tool-call trace; defined in `~/.open-code/themes/<name>.json`. |
| 24 | **`/loop` and `/schedule`** | Claude Code | medium | M | `/loop` re-runs a task on an interval; `/schedule` registers a cron-style background agent that fires later. Output goes to the session's JSONL. |
| 25 | **Managed settings enforcement** | Claude Code | low-med | M | Org-level policy file at a fixed path that locks down hooks/MCP/permissions and cannot be overridden by user settings. |

### Tier 3 — Advanced / polish

| # | Feature | Source | Impact | Complexity | One-line summary |
|---|---------|--------|--------|------------|------------------|
| 26 | **Codemaps** | Windsurf / Cognition | med | M | Persistent, viewable AI-annotated map of the repo, generated once with a strong model and `@codemap`-referenced afterward. Caches what repo-map computes per-turn. |
| 27 | **OS-native sandbox** | Codex CLI | med | M | Two-layer security: kernel sandbox (Landlock on Linux, sandbox-exec on macOS) is session-fixed; an orthogonal approval policy is hot-swappable. |
| 28 | **LSP context injection** | Crush | med | L | Run language servers (gopls, pyright, rust-analyzer) as subprocesses; expose diagnostics/hover/refs/defs as tools. Refactor with O(1) symbol queries. |
| 29 | **Oracle subagent pattern** | Sourcegraph Amp | med | S | A specialized subagent exposed as a tool: `oracle(question)` calls a stronger/slower model with isolated context; main session stays cheap. |
| 30 | **Browser-use tool** | Cline | med | L | Puppeteer-controlled Chromium (or CDP attach) with `navigate / click / type / screenshot`; vision model reads screenshots. |
| 31 | **Watch-mode AI comments** | Aider | med | S | Filesystem watcher; user types `# ai: rename foo` in any file in their editor, saves, open-code reads the marker, makes the change, clears the marker. |
| 32 | **Parallel subagent dispatch** | Cursor SDK | med | L | Main agent identifies independent subtasks and fans them out to async subagents; results merged on return. |
| 33 | **Cloud provider routing** | Claude Code | low | M | `--gateway <url>` and adapters for Vertex AI / Bedrock / custom HTTP endpoints. Already structurally enabled by our fallback chain. |
| 34 | **IDE integrations (VS Code, JetBrains)** | Claude Code | low-med (for CLI) | XL | Native extensions that share session state with the terminal and add diff preview, button bars, inline accept/reject. |
| 35 | **Auto-select edit format per model** | Aider | low-med | M | Benchmark each supported model's "laziness" with `whole` / `diff` / `udiff` / `apply_patch` formats; pick the least-lazy one per session. |
| 36 | **Vim visual modes in REPL** | Claude Code | low | S | `v` and `V` modes inside the REPL prompt for bulk selection of past turns / sections. |
| 37 | **PowerShell tool on Windows** | Claude Code | low | S | When `OPEN_CODE_USE_POWERSHELL=1`, route `run_shell` through `pwsh` instead of `cmd`. |
| 38 | **Native CLI binary** | Claude Code | low | L | PyInstaller / Nuitka build that ships a single executable; faster cold start than `python …`. |

---

## Summary by tier

- **Tier 1:** 10 features. The "core clone" — hooks, settings, skills,
  subagents, permission modes, plan/act, repo-map, apply_patch,
  architect/editor split, MCP. ~3-4 releases of work.
- **Tier 2:** 15 features. Robustness + ergonomics. ~3-5 releases.
- **Tier 3:** 13 features. Advanced surface area. As-needed.

Total: 38 missing features. Adding them all probably produces a
~5000-7000 LOC codebase across 8-12 modules — comparable to Aider's
size, smaller than Claude Code's runtime.

---

## Implementation order — recommended

If forced to pick 5 to ship first across both tiers for maximum
impact-per-LOC:

1. **#1 Hooks** — unlocks 80% of extensibility surface in one feature
2. **#7 Repo-map** — single biggest "agent makes less wrong-file edits" win
3. **#3 Skills** — every team has a workflow they'd codify
4. **#6 Plan/Act** — paired with #9 below, halves cost on multi-file tasks
5. **#8 V4A apply_patch** — replaces the awkward read/write/edit triad

Honest framing: shipping just these five takes open-code from
"Claude-Code-flavored REPL with cost reporting" to "credible Claude
Code competitor for indie devs on Gemini."

---

## Sources

### Claude Code (May 2026 research)
- https://code.claude.com/docs/en/changelog
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/mcp
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/plugins
- https://code.claude.com/docs/en/permission-modes
- https://code.claude.com/docs/en/security
- https://code.claude.com/docs/en/memory
- https://code.claude.com/docs/en/ide-integrations
- https://code.claude.com/docs/en/whats-new

### Variants
- Aider: https://aider.chat/docs/repomap.html · https://aider.chat/2024/09/26/architect.html · https://aider.chat/docs/more/edit-formats.html · https://aider.chat/docs/usage/modes.html
- Codex CLI: https://github.com/openai/codex/blob/main/codex-rs/apply-patch/apply_patch_tool_instructions.md · https://developers.openai.com/codex/concepts/sandboxing · https://developers.openai.com/codex/cli/reference
- Cline: https://docs.cline.bot/features/checkpoints · https://cline.bot/blog/plan-smarter-code-faster-clines-plan-act-is-the-paradigm-for-agentic-coding · https://docs.cline.bot/exploring-clines-tools/remote-browser-support
- Gemini CLI: https://geminicli.com/docs/cli/checkpointing/ · https://github.com/google-gemini/gemini-cli/discussions/26216
- Continue: https://docs.continue.dev/customize/deep-dives/custom-providers
- Cursor: https://cursor.com/changelog/2-4 · https://cursor.com/docs/subagents · https://cursor.com/changelog/sdk-release
- Windsurf: https://cognition.ai/blog/codemaps
- Crush: https://github.com/charmbracelet/crush
- Sourcegraph Amp: https://sourcegraph.com/amp
- Comparison: https://www.tembo.io/blog/coding-cli-tools-comparison
