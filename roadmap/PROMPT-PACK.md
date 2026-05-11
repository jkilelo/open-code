# open-code prompt pack

> One self-contained kit-style prompt per missing feature from
> `FEATURE-INVENTORY.md`. Paste any one into a fresh Claude session
> opened against the open-code repo (the kit hooks at
> `.claude/settings.json` enforce persona-mvp-kit discipline).
>
> Each prompt is designed to land **one tightly-scoped commit** that
> ships the feature with: spec update + probe + gap-log entry + a
> runs/ doc per the kit's standard.
>
> Numbers match `FEATURE-INVENTORY.md`. Tier 1 first.

---

## Reusable preamble (every prompt assumes this context)

The fresh Claude session needs to know the project shape. The
preamble below is repeated implicitly via `CLAUDE.md` in the repo, but
including the key facts in each prompt keeps the prompt portable.

> **Project:** open-code, a Gemini-backed terminal coding agent.
> Persona is Jeff (indie dev, cost-sensitive, Python 3.13).
> Layout: `open_code.py` (CLI + REPL + loop, 970 LOC), `sessions.py`
> (JSONL store, 479), `tools.py` (4 tools + denylist, 344).
> Tests: `tests/test_security.py` + 10 probes.
> Discipline: persona-mvp-kit (see `CLAUDE.md` for bright lines).
> Every commit: one feature, spec update + probe + runs/ + gap-log.

---

# Tier 1 — Foundation extensibility

## #1 Hooks system

**Tier 1 · Impact: high · Complexity: M · Source: Claude Code**

```
Add a hooks system to open-code modeled on Claude Code's. Goal: let
users intercept agent behavior with shell scripts under
`.open-code/hooks/` without modifying the Python source.

Support five events at minimum:
- PreToolUse  (fires before each tool call; exit 2 = block)
- PostToolUse (fires after each tool call; observe only)
- Stop        (fires at end-of-turn; exit 2 = soft-block, model must
              produce additional output)
- SessionStart(fires when a session is created or resumed; can emit
              JSON to `additionalContext` injected into the system
              instruction)
- UserPromptSubmit (fires per REPL turn; can transform the prompt)

Protocol:
- Hook scripts are any executable under `.open-code/hooks/<event>/`
  named `*.sh` / `*.py` / etc.
- Each fires with JSON on stdin: { event, tool, args, cwd, session_id }
- Exit code 0 = allow, exit 2 = block (with message read from stderr).
- A hook may emit JSON on stdout with keys `additionalContext`,
  `transformedPrompt`, etc.
- env: `$OPEN_CODE_PROJECT_DIR`, `$OPEN_CODE_SESSION_ID`,
  `$OPEN_CODE_CWD` set when invoked.

Implementation hints:
- New module `hooks.py` (~150 LOC); imported by `run_loop` and the
  REPL turn-runner.
- Hooks discovered at session start; cached in-memory; refreshed on
  /reload-hooks slash command.
- Settings can disable hooks via `permissions.hooks.disabled: true`.

Acceptance (mvp-spec assertions to add):
- A12 Round-trip: a PreToolUse hook that blocks `write_file` causes
  the agent loop to receive a tool-call error, surface to user.
- A13 PostToolUse fires AFTER the tool result is appended to history;
  receives `{tool, args, result, exit_code}`.
- A14 Stop hook returning exit 2 with a message causes the model to
  see "you must continue" and emit another iter.

Conventions:
- Add `tests/probe_hooks.py` with synthetic hook scripts under a
  temp dir; assert pre-tool blocks, post-tool fires, stop loops.
- Update `mvp-spec.md` with the three assertions above.
- Append a v0.5.0 row to `gap-log.md`.
- Write `runs/<date>-v0.5.0.md` with verbatim live runs.
- One commit with kit attribution.
```

---

## #2 Settings hierarchy + permission rules

**Tier 1 · Impact: high · Complexity: M · Source: Claude Code**

```
Add layered settings + per-tool permission rules to open-code.

Layout (lowest precedence first):
1. `~/.open-code/settings.json` (user defaults)
2. `<project>/.open-code/settings.json` (project, committed)
3. `<project>/.open-code/settings.local.json` (gitignored, per-machine)

Schema (subset of Claude Code's settings.json):
{
  "model": "gemini-3.1-flash-lite-preview",
  "max_iterations": 25,
  "permissions": {
    "allow": ["read_file(*)", "list_dir(*)"],
    "ask":   ["write_file(*)"],
    "deny":  ["run_shell(rm -rf *)", "run_shell(sudo *)"]
  },
  "hooks": { "enabled": true },
  "spinnerTipsOverride": "thinking..."
}

Matcher syntax: `Tool` matches any args; `Tool(specifier)` uses fnmatch
on the args' string form; `Tool(/regex/)` uses regex.

Implementation hints:
- New module `settings.py` (~150 LOC) with `load_layered_settings(cwd)`.
- CLI flags + env vars override file settings (highest precedence).
- The four `allow/ask/deny` lists evaluated PreToolUse:
  deny wins → ask prompts user (REPL only; one-shot defaults to deny)
  → allow proceeds. Default policy: allow read/list, ask on
  write/shell.
- Path sandbox + denylist remain as a separate hard layer underneath.

Acceptance:
- A15 Project settings.json overrides user settings.json.
- A16 `deny: run_shell(rm -rf *)` rejects matching commands even
  with `--allow-dangerous`.
- A17 `ask: write_file(*)` prompts in REPL; auto-deny in one-shot.

Conventions:
- `tests/probe_settings.py` with synthetic settings hierarchy.
- Update mvp-spec, gap-log, runs/. Single commit.
```

---

## #3 Skills system

**Tier 1 · Impact: high · Complexity: M · Source: Claude Code**

```
Add a skills system modeled on Claude Code's `.claude/skills/`.

Layout: `.open-code/skills/<name>/SKILL.md` (one dir per skill).

SKILL.md frontmatter:
---
name: review-pr
description: Brutal-review a pull request against project standards
arguments:
  - name: pr_number
    description: GitHub PR number
allowed-tools: [read_file, list_dir, run_shell]
context: fork  # optional; if set, run in a Task subagent
disable-model-invocation: false
---

Body: prose instructions. Supports `$ARGUMENTS` interpolation and
dynamic context blocks like `` !`git diff main` `` which run before
the model sees the body.

Invocation:
- In REPL: `/skill review-pr 123` runs the skill body as the
  user prompt for the next turn.
- Auto-discovered: when the model emits text matching a skill
  description AND `disable-model-invocation: false`, the skill body
  is injected as additional context.

Implementation hints:
- New module `skills.py` (~200 LOC). Frontmatter via `yaml` (stdlib
  isn't enough; add PyYAML if not present, or hand-roll a minimal
  parser since we own the format).
- `$ARGUMENTS` is a simple str.format-style substitution.
- `` !`cmd` `` blocks resolved via `subprocess.run` with the same
  shell config as tool_run_shell; output replaces the placeholder.
- Skills register a new slash command `/skill <name> [args]`.

Acceptance:
- A18 A skill with $ARGUMENTS substitutes correctly.
- A19 A `` !`echo hello` `` block resolves before the model sees it.
- A20 `disable-model-invocation: true` prevents auto-invocation.

Conventions:
- `tests/probe_skills.py` with a fake skill directory.
- spec/gap-log/runs/commit per kit.
```

---

## #4 Subagents / Task tool

**Tier 1 · Impact: high · Complexity: L · Source: Claude Code**

```
Add subagent delegation modeled on Claude Code's Task tool.

Behavior: the main agent can call a `delegate` tool that runs a
sub-loop with:
- A different system prompt (provided in the tool call)
- A restricted tool allowlist
- A different model (optional override)
- Isolated context (no leak of the main loop's history)
- Returns: a short summary text from the sub-loop's final turn

UX: in REPL, `/agents` lists available agent presets defined under
`.open-code/agents/<name>.md` (frontmatter + prompt body, like skills
but with `kind: agent`). The main loop sees these as tool options.

Implementation hints:
- New module `subagents.py` (~250 LOC).
- The `delegate` tool's TOOL_DECLARATIONS entry exposes:
  name, system_prompt, task_description, model (optional),
  tool_allowlist (optional), max_iterations (default 10).
- Reuse `run_loop` itself with `store=None` (don't write subagent
  turns to the main JSONL; instead write a single `delegate` event
  capturing inputs + summary).
- Subagent's own transcript stored under
  `~/.open-code/projects/<encoded-cwd>/<parent_uuid>.subagent.<n>.jsonl`
  for debugging.

Acceptance:
- A21 Main agent calling `delegate(name='explorer', ...)` returns a
  string and never sees the subagent's intermediate turns.
- A22 Subagent's tool allowlist is enforced (calling a disallowed
  tool returns an error to the subagent's model).
- A23 Subagent transcript saved as a separate JSONL with a
  `parent_session` pointer.

Conventions:
- `tests/probe_subagents.py` with a mock subagent and assertions.
- spec/gap-log/runs/commit.
```

---

## #5 Permission modes

**Tier 1 · Impact: high · Complexity: S · Source: Claude Code**

```
Add a `--mode` flag with these values mirroring Claude Code:

- `default`        — current behavior (ask in REPL, deny in one-shot)
- `acceptEdits`    — auto-allow all write_file calls (within sandbox)
- `plan`           — read-only: write_file and run_shell are denied
                    at the permissions layer; agent narrates what it
                    *would* do; output is the "plan" artifact
- `auto`           — model-controlled; the model can request the user
                    elevate, otherwise it sticks to read-only
- `bypassPermissions` — disables ALL permission checks (the existing
                       --allow-outside-cwd + --allow-dangerous are
                       a subset of this)

Implementation hints:
- Add `mode` field to settings + CLI flag + REPL slash command
  (`/mode plan`).
- Permission check function gates each tool call: returns
  (allow|ask|deny, reason). Plan mode denies write_file/run_shell
  with reason "plan mode — narrate only."
- Plan-mode session ends by writing a `plan` event to JSONL with the
  full model text; `--apply-plan <session-id>` can later replay it
  in acceptEdits mode.

Acceptance:
- A24 In plan mode, write_file calls return a `plan mode` error to
  the model; the model adapts and describes the change instead.
- A25 In acceptEdits mode, REPL doesn't prompt for write_file even
  on first use.
- A26 `--mode bypassPermissions` implies both --allow-outside-cwd and
  --allow-dangerous.

Conventions:
- `tests/probe_modes.py`. spec/gap-log/runs/commit.
```

---

## #6 Plan/Act mode separation

**Tier 1 · Impact: high · Complexity: S · Source: Cline**

```
Build on #5 (permission modes) by adding the Cline-style Plan/Act
loop as a first-class REPL workflow:

- `/plan` enters plan mode; the next prompt produces a structured
  plan artifact (text-only output, no tool side effects)
- The plan is saved as a `plan` event in the JSONL with a stable id
- `/act <plan-id>` switches to acceptEdits mode, prepends the plan to
  the context as `<plan id="X">...</plan>`, and runs the task

Optional model routing: plan-mode uses a configured "architect"
model (set via settings.json `models.architect`); act-mode uses
"editor" model. Default architect = gemini-3.1-pro-preview; default
editor = gemini-3.1-flash-lite-preview.

Implementation hints:
- Reuse #5's plan mode under the hood.
- The `/plan` REPL command flips mode and tags the next turn's JSONL
  event kind as `plan`.
- `/act` looks up the most recent `plan` event in the current
  session (or by id), flips mode to acceptEdits, and continues.

Acceptance:
- A27 `/plan "refactor sessions.py to use SQLAlchemy"` -> the model
  produces a plan with no write_file/run_shell side effects.
- A28 `/act` continues with the plan injected; produces actual
  edits.
- A29 If `models.architect` is set, plan-mode uses that model;
  cumulative metrics show the mix.

Conventions:
- Reuses probe_modes.py with new plan/act cases.
- spec/gap-log/runs/commit.
```

---

## #7 Repo-map (Aider-style symbol skeleton)

**Tier 1 · Impact: high · Complexity: M · Source: Aider**

```
Add an Aider-style repo-map: a compact "symbol skeleton" of the
repo automatically prepended to the system instruction.

Algorithm (faithfully ported from Aider):
1. Discover all tracked files (`git ls-files`).
2. For each file, parse with tree-sitter to extract definitions
   (functions, classes, methods) and references.
3. Build a directed graph: file -> file edges where source defines
   a symbol referenced by target.
4. Run PageRank, personalized on files mentioned in the current
   conversation. Result: ranked list of files.
5. From the top-ranked files, render a textual "symbol map":
     # src/foo.py
       class Foo:
         def bar(self, x: int) -> str: ...
       def helper(s: str) -> None: ...
6. Truncate at ~1000 tokens. Inject as a `<repo-map>...</repo-map>`
   block in the system instruction.

Implementation hints:
- New module `repomap.py` (~250 LOC).
- Deps: `tree-sitter`, `tree-sitter-languages` (covers ~30 languages),
  `networkx`.
- Aider's `tags.scm` queries are MIT — port directly per-language.
- Cache the graph on disk under
  `~/.open-code/cache/<encoded-cwd>/repomap.json`; invalidate on
  file mtime change.
- New flag `--no-repomap` disables; setting `repomap.enabled: false`
  in settings.json disables globally.

Acceptance:
- A30 On a repo with 50+ Python files, the system prompt includes a
  `<repo-map>` block under 1500 tokens.
- A31 The skeleton lists top-3 files in PageRank order and shows
  function signatures without bodies.
- A32 Edit-then-query: after a file's symbol set changes, the cache
  invalidates and the next turn sees the new skeleton.

Conventions:
- `tests/probe_repomap.py` against the open-code repo itself.
- New deps in requirements.txt: `tree-sitter`, `tree-sitter-languages`,
  `networkx`. Document the dep budget growth in runs/.
- spec/gap-log/runs/commit.
```

---

## #8 V4A apply_patch envelope

**Tier 1 · Impact: high · Complexity: M · Source: OpenAI Codex CLI**

```
Replace the write_file/edit dance with a single `apply_patch` tool
using OpenAI's V4A diff envelope.

Tool surface:
- One new tool: `apply_patch(patch: str) -> {ok, applied: [paths]}`
- Format:
    *** Begin Patch
    *** Update File: src/foo.py
    @@ def bar
    -    return x
    +    return x + 1
    *** End Patch
- Supports: Add File, Update File, Delete File, Move to <newpath>.
- Hunks anchored by surrounding code (the `@@ context` line), not
  line numbers. If the anchor doesn't match uniquely, error.

Implementation hints:
- New module `patches.py` (~250 LOC).
- Parser: stateful walk over the patch lines.
- Applier: for each Update hunk, find the unique anchor in the
  target file, splice in the new content. If ambiguous, fail.
- Inherits the path sandbox from #2 / current tool_write_file.
- Keep tool_write_file around for the "create a fresh file" case;
  remove the edit-via-rewrite footgun.

Acceptance:
- A33 An apply_patch with a Move + Update succeeds atomically.
- A34 Ambiguous anchor returns error mentioning all matches.
- A35 Path sandbox refuses out-of-CWD updates without
  --allow-outside-cwd.

Conventions:
- `tests/probe_apply_patch.py` with the format's edge cases.
- Update SYSTEM_INSTRUCTION to teach the model the new envelope.
- spec/gap-log/runs/commit.
```

---

## #9 Architect/editor model split

**Tier 1 · Impact: high · Complexity: S · Source: Aider**

```
Allow open-code to use two models in a single turn: an "architect"
that writes a plan and an "editor" that produces actual edits.

UX:
- New settings.json fields:
    models:
      architect: gemini-3.1-pro-preview
      editor:    gemini-3.1-flash-lite-preview
- Or per-invocation flags: `--architect gemini-3.1-pro-preview
  --editor gemini-3.1-flash-lite-preview`.
- Default: both unset means single-model mode (current behavior).

Loop (when both are set):
1. Architect turn: model = architect, system prompt nudges toward
   "produce a plan; do not call tools." Plan text is captured.
2. Editor turn: model = editor, history includes the plan as a
   `<plan>` block. Tool calls expected here.
3. Append `metrics` events distinguishing architect vs. editor.

Implementation hints:
- ~100 LOC of routing in run_loop or a wrapper.
- Reuse #6's plan/act if shipped — this is essentially "auto plan +
  auto act with different models."
- If editor mid-turn needs more reasoning, it can `delegate` to the
  architect (depends on #4 subagents).

Acceptance:
- A36 With architect=Pro + editor=Flash, a multi-file refactor
  produces metrics events tagged with each model.
- A37 Without the split, single-model mode behaves exactly as v0.4.
- A38 Cumulative cost shows the split.

Conventions:
- `tests/probe_architect_editor.py` with mock clients per role.
- spec/gap-log/runs/commit.
```

---

## #10 MCP server support

**Tier 1 · Impact: high · Complexity: L · Source: Claude Code / industry standard**

```
Add Model Context Protocol (MCP) client support so open-code can
connect to external tool servers.

Scope (v0.5 — stdio transport only):
- Read `mcpServers` section of settings.json (Claude Code format):
    mcpServers:
      filesystem:
        command: npx
        args: [-y, "@modelcontextprotocol/server-filesystem", /tmp]
      github:
        command: github-mcp-server
        env: { GITHUB_TOKEN: $GITHUB_TOKEN }
- Spawn each server as a subprocess at session start; speak the
  MCP JSON-RPC protocol over stdin/stdout.
- Discover the server's tools (`tools/list`).
- Merge them into `TOOL_DECLARATIONS` with a namespace prefix:
  `mcp__filesystem__read_file`.
- Route calls to the right server.
- On session end, terminate subprocesses.

Implementation hints:
- New module `mcp.py` (~400 LOC). The official `mcp` Python package
  exists and works; use it (add to requirements.txt).
- Errors during startup: 3-retry with backoff; if all fail, log to
  stderr and skip that server (don't kill the session).
- New slash command `/mcp` lists connected servers + their tools.
- Permission rules from #2 apply to MCP tools too.

Acceptance:
- A39 With a filesystem MCP server configured, the model can call
  `mcp__filesystem__list_directory` and receive results.
- A40 A failed server (bad command) logs a warning but the rest of
  the session works.
- A41 `/mcp` shows connected servers and their tool counts.

Conventions:
- `tests/probe_mcp.py` against a tiny in-process mock MCP server.
- New runtime dep: `mcp` Python SDK. Document.
- spec/gap-log/runs/commit.
```

---

# Tier 2 — Robustness + UX power-ups

## #11 Shadow-git checkpointing

**Tier 2 · Impact: high · Complexity: M · Source: Cline / Gemini CLI**

```
Add per-tool-call filesystem snapshots so the agent can be reverted
without touching the user's real git.

Mechanism:
- For each session, maintain a shadow git repo at
  `~/.open-code/checkpoints/<session-id>.git` (bare or with a sep
  working tree under the same dir).
- Before each tool call that writes to disk (write_file, apply_patch,
  run_shell when it touches files), commit the current CWD state to
  the shadow repo with the tool call as the commit message.
- New slash command `/checkpoint list` shows recent checkpoints.
- `/restore <ckpt-id>` reverts files in CWD to that checkpoint AND
  marks the agent's JSONL history with a `restore` event so resume
  picks up the right context.

Implementation hints:
- Use `git` via subprocess (cross-platform; cheaper than a libgit2
  binding). Hide the shadow repo from user's git.
- Skip checkpointing for read-only tools.
- New module `checkpoints.py` (~200 LOC).
- Settings: `checkpoints.enabled: true` (default), `checkpoints.gc_days: 30`.

Acceptance:
- A42 After a write_file followed by /restore, the file on disk
  reverts to its prior content.
- A43 The shadow repo never appears in `git status` of the user's CWD.
- A44 `--no-checkpoint` flag disables for a single invocation.

Conventions:
- `tests/probe_checkpoints.py` exercising write -> restore -> write.
- Doc the disk-usage trade-off (one shadow repo per session).
- spec/gap-log/runs/commit.
```

---

## #12 Atomic-commit per turn

**Tier 2 · Impact: medium · Complexity: S · Source: Aider**

```
Add an opt-in mode where every successful turn's file changes are
committed to the user's real git with an LLM-written message.

UX:
- Settings: `auto_commit: true` (default false).
- After a turn that wrote files, check `git diff --quiet`; if non-zero,
  ask the model to produce a one-line conventional-commit-style
  message describing the change.
- Commit with that message + a kit-style attribution footer:
    🤖 Authored by open-code (session <uuid>)

Implementation hints:
- ~80 LOC near the end of run_loop.
- Skip if not in a git repo.
- Honors permission modes: skipped in plan mode; behaves normally
  otherwise.
- The commit message goes to the JSONL as a `git_commit` event with
  the SHA.

Acceptance:
- A45 With auto_commit=true and a successful write_file turn,
  `git log -1` shows the open-code commit.
- A46 No git repo -> the flag is a no-op (warning to stderr).
- A47 In plan mode, auto_commit is skipped.

Conventions:
- `tests/probe_atomic_commit.py` against a temp git repo.
- spec/gap-log/runs/commit.
```

---

## #13 `/compact` slash command

**Tier 2 · Impact: medium · Complexity: S · Source: Claude Code**

```
Add a `/compact` slash command that summarizes older session history
into a single condensed `msg` event, dropping the verbose middle
turns to save tokens on subsequent --resume.

UX:
- In REPL: `/compact` triggers an LLM call that summarizes the first
  N-K turns of history (N = current message count, K = last 10 to
  keep verbatim) into a single user-role message.
- The original messages are NOT deleted from disk; a `compact` event
  is appended pointing at the summary.
- On next `--resume`, load_history detects the most recent `compact`
  event and uses its summary plus the K most recent msgs.

Implementation hints:
- ~120 LOC in open_code.py + sessions.py.
- Summary prompt: "Summarize the prior N turns of this coding session
  in 200 words, focused on what files exist, what was decided, and
  what's still TODO."
- Settings: `compact.keep_recent: 10`, `compact.summary_target_tokens: 200`.

Acceptance:
- A48 After /compact, --show-metrics on the next --resume shows
  reduced input_tok.
- A49 The compact event preserves the original message count for
  audit.
- A50 The model's summary is appended as a real `msg` event so all
  metrics still work.

Conventions:
- `tests/probe_compact.py` with mocked summary client.
- spec/gap-log/runs/commit.
```

---

## #14 Status line

**Tier 2 · Impact: medium · Complexity: S · Source: Claude Code**

```
Add a persistent status line at the bottom of the REPL (and below
the per-iter trace in one-shot mode) showing:

    [model: gemini-3.1-flash-lite-preview | iter 3 | tok 1.4k/4.2k |
     cost $0.0008 | session abc... | mode default]

Implementation hints:
- ~80 LOC: a `render_status` function called every render tick.
- Use ANSI cursor controls to redraw a single line at the bottom of
  stderr (POSIX) or just print before each prompt (Windows fallback).
- Configurable via settings: `statusLine.template` (Python format
  string), `statusLine.enabled: true`.
- Cost estimation: maintain a price-per-token table per model;
  multiply by cumulative tokens; default $0 if unknown model.

Acceptance:
- A51 During a multi-iter turn, the status line updates each iter.
- A52 In REPL between prompts, the status line is visible and shows
  the latest cumulative cost.
- A53 `statusLine.enabled: false` disables it.

Conventions:
- `tests/probe_statusline.py` mocking stdout/stderr.
- spec/gap-log/runs/commit.
```

---

## #15 Effort levels

**Tier 2 · Impact: medium · Complexity: S · Source: Claude Code**

```
Add `--effort <low|medium|high|xhigh>` and `/effort` REPL command
that adjusts the model's reasoning budget.

Mapping (initial; revisit when Gemini exposes a richer
thinking-budget API):
- low:   thinking_config.thinking_budget = 0
- medium: thinking_config.thinking_budget = 512
- high:  thinking_config.thinking_budget = 4096
- xhigh: thinking_config.thinking_budget = 16384

Implementation hints:
- ~60 LOC. Pass through `thinking_config` in the
  GenerateContentConfig.
- Settings: `effort.default: medium`.
- The JSONL `metrics` event captures the effort used per iter.

Acceptance:
- A54 `--effort high` makes a measurable latency + output_tok bump on
  a complex task vs `--effort low`.
- A55 `/effort xhigh` mid-REPL applies from the next turn.
- A56 The metrics event records the effort level.

Conventions:
- `tests/probe_effort.py` (may need a live call or mock the config).
- spec/gap-log/runs/commit.
```

---

## #16 Extended thinking / `ultrathink`

**Tier 2 · Impact: medium · Complexity: S · Source: Claude Code**

```
Add an in-prompt marker `ultrathink` that bumps the next turn's
thinking-budget to its maximum WITHOUT changing the session's effort
setting. One-off escape hatch for hard turns.

Mechanism:
- Before sending the prompt to the model, scan for the literal
  token `ultrathink`. If present, override the upcoming generation
  config's thinking_budget to the maximum supported (or 32768).
- Strip `ultrathink` from the visible prompt (so the model focuses
  on the task).
- Emit a `metrics` event annotation `ultrathink: true`.

Implementation hints:
- ~30 LOC in main() and the REPL prompt handler.
- Independent of #15 (compose: effort=low + ultrathink = high once).

Acceptance:
- A57 A prompt containing "ultrathink, why does foo break?" runs
  with max thinking budget; the next turn doesn't.
- A58 The `ultrathink` literal does NOT appear in the JSONL `msg`
  parts.

Conventions:
- `tests/probe_ultrathink.py`. spec/gap-log/runs/commit.
```

---

## #17 Sticky session permissions

**Tier 2 · Impact: medium · Complexity: S · Source: OpenAI Codex CLI**

```
Persist per-tool permission decisions across --resume.

UX:
- When the user answers an `ask:` prompt in REPL (allow / deny /
  always-allow / always-deny), write a `permission_grant` event to
  the JSONL with the matcher and decision.
- On --resume, load_history scans for permission_grant events and
  applies them to the in-memory permission rules BEFORE the loop
  starts.

Implementation hints:
- ~80 LOC; mostly in run_loop's permission check + REPL prompt.
- "Always-allow" only persists within the session by default;
  settings.json `permissions.persist_grants: true` makes them
  cross-session for that CWD.

Acceptance:
- A59 After granting "always-allow write_file in this session",
  subsequent --resume invocations don't re-ask.
- A60 The grant decays at session end unless persist_grants is set.

Conventions:
- `tests/probe_permission_grants.py`. spec/gap-log/runs/commit.
```

---

## #18 Four-tier project memory

**Tier 2 · Impact: medium · Complexity: S · Source: Gemini CLI**

```
Extend OPEN_CODE.md loading from "first match wins" to four-tier
concatenation:

1. `~/.open-code/OPEN_CODE.md`           (global personal defaults)
2. Walk-up from CWD: each ancestor's `OPEN_CODE.md`, top-down
3. `<CWD>/OPEN_CODE.md`                  (project, committed)
4. `<CWD>/.open-code/MEMORY.md`          (private, gitignored)

All four are concatenated in order under section headers. Total
capped at MAX_PROJECT_CONTEXT_BYTES (raise default to 100KB now
that we have multiple sources).

Implementation hints:
- ~80 LOC; modify load_project_context to return a list of
  (path, content) tuples; build_system_instruction concatenates.
- Each section gets a `## Project context from <path>` header so
  the model can tell where guidance came from.

Acceptance:
- A61 With global + project + private MEMORY files all present,
  the system instruction contains all four under labeled headers.
- A62 Order: global first, then ancestors top-down, then project,
  then private.
- A63 If any one is missing, the others still load.

Conventions:
- `tests/probe_four_tier_memory.py`. spec/gap-log/runs/commit.
```

---

## #19 Extended @-mention context providers

**Tier 2 · Impact: medium · Complexity: S each · Source: Continue**

```
Extend @-file refs (#19 in v0.4) with typed providers Continue-style.

Add these tokens beyond `@<path>`:
- `@diff`         -> `git diff` output
- `@diff:staged`  -> `git diff --staged`
- `@terminal`     -> last 200 lines of the user's shell history if
                    available (`HISTFILE` / fc -l)
- `@problems`     -> if a `make check` / `ruff check` / `mypy`
                    config is detected, run it and inject output
- `@tree`         -> `tree -L 2` of CWD (truncated)
- `@open`         -> list of files opened in the last hour
                    (from JSONL msg events)
- `@cwd`          -> the encoded CWD + recent session ids

Implementation hints:
- ~30 LOC per provider. Implement as a registry:
    PROVIDERS = {"diff": fn, "terminal": fn, ...}
- Each provider returns a string blob; expand_file_refs prepends
  `<context kind="diff">...</context>` blocks.
- A missing/empty provider silently no-ops.

Acceptance:
- A64 `@diff` in a prompt run inside a git repo injects the diff.
- A65 `@tree` injects a depth-2 tree; truncates above 10 KB.
- A66 `@nonexistent` is left as a literal (existing behavior).

Conventions:
- `tests/probe_at_providers.py`. spec/gap-log/runs/commit.
```

---

## #20 Non-interactive `--print` + JSON stream output

**Tier 2 · Impact: medium · Complexity: M · Source: Codex CLI / Claude Code**

```
Add `--print` (alias `-p`) flag that switches output to JSON-line
events on stdout, suitable for piping or scripting.

Event types (one JSON object per line):
- {"kind":"session","id":"<uuid>","model":"...","cwd":"..."}
- {"kind":"iter_start","iter":1,"model":"..."}
- {"kind":"tool_call","tool":"write_file","args":{...}}
- {"kind":"tool_result","tool":"...","result":{...}}
- {"kind":"assistant_message","text":"..."}
- {"kind":"fallback","from":"...","to":"...","reason":"..."}
- {"kind":"refusal","tool":"...","reason":"..."}
- {"kind":"end","exit_code":0,"iters":3,"wall_seconds":2.5,
   "input_tok":1234,"output_tok":56}

Implementation hints:
- ~150 LOC; mostly emitter functions called from the same hot paths
  that already write to JSONL.
- Suppress the human-friendly stderr trace when `--print` is set.
- Streaming output: assistant_message events emit token chunks with
  `"streaming":true` until a final `"streaming":false` event.

Acceptance:
- A67 `open_code --print "task"` emits valid JSON lines; each
  parseable; ends with an `end` event.
- A68 `open_code --print --resume "..."` works the same.
- A69 No human-friendly stderr trace in --print mode.

Conventions:
- `tests/probe_print_mode.py` runs subprocess and parses JSON-lines.
- Document the schema in roadmap/PRINT-SCHEMA.md (one new file).
- spec/gap-log/runs/commit.
```

---

## #21 Prompt caching (1-hour TTL)

**Tier 2 · Impact: medium · Complexity: S · Source: Claude Code**

```
When the underlying model supports prompt caching (Gemini 3.x does
via `cached_content`), mark the cacheable prefix and use it.

Cacheable prefix = SYSTEM_INSTRUCTION + project context + repo-map
(if shipped from #7) + skill bodies (if shipped from #3). The
per-turn user message stays outside the cache.

Implementation hints:
- ~100 LOC.
- New module function `build_cached_content(...)` that builds the
  cache once per session and returns a handle.
- Pass the handle into each `generate_content` / `generate_content_stream`
  call.
- Settings: `cache.enabled: true`, `cache.ttl_seconds: 3600`.

Acceptance:
- A70 Second turn in a session shows reduced input_tok in metrics
  vs first turn (because cached prefix isn't billed).
- A71 Disable via settings -> no caching.

Conventions:
- `tests/probe_cache.py` may need a live call to verify token deltas.
- spec/gap-log/runs/commit.
```

---

## #22 Plugin system + marketplace

**Tier 2 · Impact: medium · Complexity: L · Source: Claude Code**

```
Add a plugin bundling format that ships skills, agents, hooks, MCP
configs, and denylist patches as one unit.

Manifest at `.open-code-plugin/plugin.json`:
{
  "name": "indie-toolkit",
  "version": "0.1.0",
  "description": "...",
  "skills": ["skills/review-pr/SKILL.md"],
  "agents": ["agents/explorer.md"],
  "hooks": {"PreToolUse": ["hooks/log.sh"]},
  "mcpServers": {...},
  "denylist_extra": ["regex pattern", ...]
}

Discovery:
- `~/.open-code/plugins/<name>/.open-code-plugin/plugin.json`
- `<project>/.open-code-plugin/plugin.json`
- `--plugin-dir <path>` flag
- `--plugin-url <git-url>` clones into ~/.open-code/plugins/

Skills/agents from plugins are namespaced: `/skill plugin-name:skill-name`.

Implementation hints:
- New module `plugins.py` (~300 LOC).
- A future "marketplace" is just a curated list of git URLs;
  out of scope here.
- New slash command `/plugins` lists installed plugins.

Acceptance:
- A72 With a plugin installed, its skill is invocable via
  `/skill <plugin>:<name>`.
- A73 Plugin hooks fire alongside project hooks (#1).
- A74 `--plugin-url <git-url>` clones and loads a plugin.

Conventions:
- `tests/probe_plugins.py`. spec/gap-log/runs/commit.
```

---

## #23 Output styles / theming

**Tier 2 · Impact: low-medium · Complexity: S · Source: Claude Code**

```
Add user-pickable color/glyph themes for the tool-call trace.

Settings:
- `theme.name: "default"` (or "minimal", "verbose", "no-color")
- Themes defined in `~/.open-code/themes/<name>.json`:
    {
      "glyphs": {
        "tool_call_start": "▶",
        "tool_ok":   "✓",
        "tool_err":  "✗"
      },
      "colors": {
        "tool_call":  "cyan",
        "tool_ok":    "green",
        "tool_err":   "red"
      }
    }

Implementation hints:
- ~80 LOC; gate the existing `_render_tool_call` /
  `_render_tool_result` outputs through a theme lookup.
- `no-color` theme respects `NO_COLOR` env var (standard).
- ANSI codes via a tiny helper; no `rich` / `colorama` dep needed.

Acceptance:
- A75 `theme.name: minimal` produces glyph-free output.
- A76 `NO_COLOR=1` disables all ANSI sequences regardless of theme.

Conventions:
- `tests/probe_themes.py`. spec/gap-log/runs/commit.
```

---

## #24 `/loop` and `/schedule` commands

**Tier 2 · Impact: medium · Complexity: M · Source: Claude Code**

```
Add two recurring-execution commands for autonomous workflows.

`/loop <interval> <task>`:
- Re-runs <task> every <interval> (e.g. "5m", "1h").
- Output of each run goes to the same session JSONL.
- Stops on user input (Ctrl+C in REPL) or `/loop stop`.

`/schedule <cron> <task>`:
- Registers a cron-style background task; persists to
  `~/.open-code/schedules.json`.
- A separate `open-code --daemon` mode (or a host-OS scheduler entry)
  fires these. v0.5 ships the registry; v0.6 the daemon.

Implementation hints:
- ~200 LOC.
- /loop uses a simple in-process timer.
- /schedule writes a row; document how to wire to crontab / Task
  Scheduler in the docs.

Acceptance:
- A77 `/loop 10s "echo tick > tick.txt"` writes the file every 10s
  until interrupted.
- A78 `/schedule "0 9 * * *" "check inbox"` persists to schedules.json.
- A79 `/loop stop` halts the loop.

Conventions:
- `tests/probe_loop.py`. spec/gap-log/runs/commit.
```

---

## #25 Managed settings enforcement

**Tier 2 · Impact: low-medium · Complexity: M · Source: Claude Code**

```
Add an org-level settings file that's read but cannot be overridden
by user/project settings.

Path (platform-conventional):
- Linux: `/etc/open-code/managed.json`
- macOS: `/Library/Application Support/open-code/managed.json`
- Windows: `%ProgramData%\open-code\managed.json`

Or an `OPEN_CODE_MANAGED_PATH` env var.

Enforcement:
- managed.json is loaded FIRST (lowest precedence) — but specific
  keys can be marked `_locked: true` (sibling boolean), which makes
  them immutable from user/project layers.
- Locked keys win even over CLI flags (with a warning to stderr).

Implementation hints:
- ~150 LOC; integrate into settings.py from #2.

Acceptance:
- A80 `permissions.deny.run_shell` locked at managed -> user
  `allow.run_shell` is ignored with a warning.
- A81 Without managed.json, behavior unchanged.

Conventions:
- `tests/probe_managed.py`. spec/gap-log/runs/commit.
```

---

# Tier 3 — Advanced / polish

## #26 Codemaps

**Tier 3 · Impact: medium · Complexity: M · Source: Windsurf / Cognition**

```
Add a `/codemap generate` command that runs a strong model to write
a long-lived `CODEMAP.md` at repo root summarizing the codebase
structure: modules, key types, data flows.

After generation, CODEMAP.md is auto-loaded into the system
instruction whenever the user references it via `@codemap`, OR
always-loaded if settings `codemap.always_load: true`.

This is cached repo-map (#7), but human-inspectable and editable.

Implementation hints:
- ~200 LOC.
- The generation prompt asks the model to walk the repo (via tool
  calls), categorize files, draw an ASCII module graph.
- Use the architect model from #9 if configured.

Acceptance:
- A82 `/codemap generate` produces a CODEMAP.md with module groups.
- A83 `@codemap` references it in subsequent prompts.

Conventions:
- spec/gap-log/runs/commit.
```

---

## #27 OS-native sandbox

**Tier 3 · Impact: medium · Complexity: M · Source: OpenAI Codex CLI**

```
Add a kernel-level sandbox layer below the permission system.

Linux: use `landlock-python` to lock the working set to CWD + the
session's checkpoint dir + the user's cache dirs. Reject writes
anywhere else at the kernel level.

macOS: shell out to `sandbox-exec` with a Seatbelt profile.

Windows: use restricted access tokens (`AdjustTokenPrivileges`) to
strip admin rights from the subprocess.

Implementation hints:
- New module `oskbox.py` (~250 LOC).
- The sandbox is session-fixed: chosen at session start, can't be
  hot-swapped (defense-in-depth against prompt injection).
- An orthogonal approval policy (the existing permission modes #5)
  remains hot-swappable.
- Settings: `sandbox.profile: read-only | auto | full-access`,
  default `auto`.

Acceptance:
- A84 In read-only sandbox, write_file fails with a kernel error
  even with allow rules.
- A85 In auto mode, write_file works within CWD; outside CWD blocked
  at the kernel layer (not just the permission check).
- A86 Mode can be downgraded mid-session but never upgraded.

Conventions:
- `tests/probe_sandbox_kernel.py` skipped on platforms without the
  facility.
- spec/gap-log/runs/commit.
```

---

## #28 LSP context injection

**Tier 3 · Impact: medium · Complexity: L · Source: Crush**

```
Add language-server integration so the model has O(1) access to
symbol-precise queries instead of grepping.

Tools to add (new TOOL_DECLARATIONS entries):
- `lsp_diagnostics(path)` -> errors/warnings for the file
- `lsp_hover(path, line, col)` -> doc + type info
- `lsp_definition(path, line, col)` -> jump-to-def
- `lsp_references(path, line, col)` -> all usages

Implementation hints:
- New module `lsp.py` (~400 LOC).
- Speak LSP JSON-RPC. Spawn one server per language per session
  (gopls for Go, pyright for Python, etc.).
- Settings: `lsp.servers: { python: "pyright", go: "gopls", ... }`.

Acceptance:
- A87 With pyright installed, the model can call lsp_diagnostics
  on a Python file and get type errors.
- A88 If a server isn't installed, the corresponding tool returns
  a "server unavailable" error.

Conventions:
- `tests/probe_lsp.py` against a tiny Python file with intentional
  type errors. Requires pyright; skip if absent.
- spec/gap-log/runs/commit.
```

---

## #29 Oracle subagent pattern

**Tier 3 · Impact: medium · Complexity: S · Source: Sourcegraph Amp**

```
Add an `oracle` tool that wraps subagent delegation (#4) into a
single dedicated tool for "ask a smarter slower model a hard
question without context-switching the main session."

TOOL_DECLARATIONS entry:
{
  "name": "oracle",
  "description": "Ask a stronger reasoning model for a deep answer
                  to a single question. No tool access; pure
                  reasoning.",
  "parameters": {"question": {"type": "STRING"}}
}

Implementation hints:
- ~80 LOC if #4 is shipped: just a fixed-config delegate.
- The oracle model is settable via `models.oracle` (default:
  `gemini-3.1-pro-preview`).
- Oracle has NO tool access (forces it to reason from context only).
- Oracle's full transcript is saved as a subagent transcript per #4.

Acceptance:
- A89 `oracle("explain why this regex is slow")` returns a string
  answer; tool stats show it ran with no tool calls.
- A90 Without #4 shipped, this PROMPT depends on #4 being done first.

Conventions:
- `tests/probe_oracle.py`. spec/gap-log/runs/commit.
```

---

## #30 Browser-use tool

**Tier 3 · Impact: medium · Complexity: L · Source: Cline**

```
Add a Puppeteer/Playwright-driven browser tool.

New TOOL_DECLARATIONS entries:
- `browser_navigate(url)`
- `browser_click(selector)`
- `browser_type(selector, text)`
- `browser_screenshot()` -> base64 PNG
- `browser_snapshot()` -> accessibility tree text

Implementation hints:
- New module `browser.py` (~400 LOC).
- Use Playwright (`pip install playwright`); install Chromium once
  on first use.
- The model receives screenshots as Gemini's vision input.
- Browser session is per-open-code-session; close on /exit.

Acceptance:
- A91 `browser_navigate("https://example.com")` then
  `browser_screenshot()` returns a PNG; vision-capable model reads it.
- A92 Browser closes when the agent loop ends.

Conventions:
- `tests/probe_browser.py` with a local http.server fixture.
- New dep: playwright. Document.
- spec/gap-log/runs/commit.
```

---

## #31 Watch-mode AI comments

**Tier 3 · Impact: medium · Complexity: S · Source: Aider**

```
Add a `/watch` REPL command that tails the filesystem for files
containing an `# ai:` (or `// ai:`) marker.

When a marker is detected after a save, open-code reads the
surrounding context, treats the comment as the user prompt, makes
the change, and clears the marker.

Implementation hints:
- ~150 LOC using `watchdog` (cross-platform filesystem watcher).
- Markers recognized per language: `# ai: ...` (Python, shell),
  `// ai: ...` (JS, TS, Go, C), `<!-- ai: ... -->` (HTML/MD).
- The implicit prompt is "Apply this AI comment: `<comment>` to
  <file>. Remove the comment after." Append @file ref.

Acceptance:
- A93 With /watch active, saving `foo.py` containing
  `# ai: rename bar to baz` produces an apply_patch turn that
  renames and clears the comment.
- A94 /watch stop halts the watcher.

Conventions:
- New dep: watchdog.
- `tests/probe_watch.py` with a polled filesystem fixture.
- spec/gap-log/runs/commit.
```

---

## #32 Parallel subagent dispatch

**Tier 3 · Impact: medium · Complexity: L · Source: Cursor SDK**

```
Extend the delegate tool (#4) to support fanning out to multiple
subagents concurrently and merging results.

Tool: `delegate_parallel(tasks: list[{name, prompt}], max_workers=4)`
-> {results: [{name, summary}]}.

Implementation hints:
- ~300 LOC.
- Spawn subagents in threads (each calls run_loop with its own
  session). I/O-bound, so threads work despite GIL.
- Race condition: parent loop must wait for all to finish (or
  timeout) before continuing.
- Cumulative metrics aggregate across children.

Acceptance:
- A95 `delegate_parallel([4 tasks])` returns in roughly max(child
  durations), not sum.
- A96 If one subagent fails, the others still complete.

Conventions:
- `tests/probe_parallel_delegate.py`. spec/gap-log/runs/commit.
```

---

## #33 Cloud provider routing

**Tier 3 · Impact: low-medium · Complexity: M · Source: Claude Code**

```
Add LLM provider adapters beyond direct google-genai (already the
Mara persona trigger from v0.1's persona doc).

Adapters:
- Vertex AI (Gemini via GCP project)
- Bedrock (Claude / etc. via AWS — needs Anthropic adapter)
- Generic HTTP gateway (compatible with OpenAI API)

Mechanism:
- `provider` field in settings: "google" (default), "vertex",
  "bedrock", "openai-compat".
- Adapter wraps the existing `client.models.generate_content(_stream)`
  interface so run_loop is provider-agnostic.

Implementation hints:
- New module `providers.py` (~300 LOC for two adapters; more for
  Bedrock).
- Triggers the Mara persona from v0.1 — add it to personas.md
  alongside Jeff.

Acceptance:
- A97 With Vertex configured, a round-trip works and produces a
  Vertex-attributed metrics event.
- A98 OpenAI-compat adapter works against a local Ollama OpenAI
  endpoint.

Conventions:
- `tests/probe_providers.py` against mock HTTP fixtures.
- spec/gap-log/runs/commit.
```

---

## #34 IDE integrations (VS Code, JetBrains)

**Tier 3 · Impact: low-medium (for CLI-first) · Complexity: XL · Source: Claude Code**

```
Build VS Code + JetBrains extensions that share session state with
the CLI.

Scope (v0.5 — minimal):
- VS Code extension that:
  - Reads the JSONL transcripts and renders them in a panel
  - Has a "Continue in open-code" button that opens a terminal with
    `open_code --resume-id <id>`
  - No standalone agent loop in the IDE; it's a viewer + launcher

JetBrains: same shape via the JetBrains Platform plugin.

Implementation hints:
- VS Code: TypeScript extension in `ide/vscode/`. NPM package.
- Use the `vscode.workspace.fs` API to read `~/.open-code/projects/`.
- Bidirectional sync (IDE edits triggering an open-code turn) is
  out of scope for v0.5; v0.6 candidate.

Acceptance:
- A99 Installing the VS Code extension makes session JSONLs render
  as a tree in a sidebar.
- A100 Clicking "Continue" opens an integrated terminal running
  `open_code --resume-id <uuid>`.

Conventions:
- `ide/vscode/` directory; package.json + extension.ts.
- Doc in `roadmap/IDE-INTEGRATION.md`.
- spec/gap-log/runs/commit.
```

---

## #35 Auto-select edit format per model

**Tier 3 · Impact: low-medium · Complexity: M · Source: Aider**

```
After #8 (V4A apply_patch), some models will be better at one edit
format than another. Add an auto-selector.

Mechanism:
- Settings: `edit_format: auto | whole | diff | udiff | apply_patch`.
- "auto" looks up a per-model preference table at session start.
- The table is editable; defaults seeded from a small benchmark
  Aider has published.

Implementation hints:
- ~100 LOC.
- Surface the chosen format in the `session` event metadata.

Acceptance:
- A101 `edit_format: auto` with a Gemini Pro model selects
  apply_patch; with Flash, selects whole or diff (per the seeded
  table).
- A102 Explicit `edit_format: udiff` forces unified-diff regardless
  of model.

Conventions:
- `tests/probe_edit_format.py`. spec/gap-log/runs/commit.
```

---

## #36 Vim visual modes in REPL

**Tier 3 · Impact: low · Complexity: S · Source: Claude Code**

```
Add vim-style visual selection in the REPL prompt for users who
want to select / yank past turns.

Scope (v0.5):
- `v` enters character-visual mode (in the current line buffer)
- `V` enters line-visual mode (across the displayed transcript)
- `y` yanks; `d` deletes (selection from current buffer only)
- Esc returns to normal/insert

Implementation hints:
- Use `prompt_toolkit` for this (replaces `input()`). Adds a dep
  but unlocks proper TUI capabilities.
- Or build a tiny custom state machine over `readline` — but
  prompt_toolkit is simpler and gives history search, multiline,
  syntax highlighting for free.

Acceptance:
- A103 In REPL, pressing `v` followed by motion + `y` yanks the
  selection to the system clipboard.
- A104 Existing line editing (Ctrl+A / Ctrl+E etc.) still works.

Conventions:
- New dep: prompt_toolkit (substantial — consider gating behind
  `--tui` flag).
- `tests/probe_vim_repl.py` (hard to test; document manual
  verification).
- spec/gap-log/runs/commit.
```

---

## #37 PowerShell tool on Windows

**Tier 3 · Impact: low · Complexity: S · Source: Claude Code**

```
When `OPEN_CODE_USE_POWERSHELL=1` (env or settings), route
run_shell calls through `pwsh -Command` instead of `cmd /c`.

Implementation hints:
- ~30 LOC in tools.py.
- The denylist patterns already include PowerShell-specific entries
  (Remove-Item -rf, rd /s, etc.).
- Adjust subprocess.run's argv accordingly.

Acceptance:
- A105 With the env set, `run_shell("Get-ChildItem")` works on
  Windows.
- A106 Without it, behavior unchanged (cmd shell).

Conventions:
- `tests/probe_powershell.py` skipped on POSIX.
- spec/gap-log/runs/commit.
```

---

## #38 Native CLI binary

**Tier 3 · Impact: low · Complexity: L · Source: Claude Code**

```
Build a per-platform native binary via PyInstaller (simplest) or
Nuitka (faster startup) so users don't need a Python install.

Targets:
- macOS arm64 + x86_64 (universal)
- Linux x86_64 + arm64
- Windows x86_64

Implementation hints:
- New `build/build_binary.sh` (and a Windows .ps1) wrapping
  PyInstaller --onefile.
- The single-file binary is ~30-50 MB but starts in <200ms.
- Distribute via GitHub Releases.

Acceptance:
- A107 The built binary on macOS runs `open-code "task"` without
  Python installed.
- A108 Cold start is under 500ms.

Conventions:
- New dir `build/`.
- This is mostly a packaging task — minimal source change.
- spec/gap-log/runs/commit.
```

---

# How to use this prompt pack

1. Pick a feature row from FEATURE-INVENTORY.md by tier + impact.
2. Open the matching `## #N` section in this file.
3. Copy the fenced block into a fresh Claude Code session opened in
   the open-code repo root.
4. The session's kit hooks enforce: spec update + probe + gap-log +
   runs/ + commit conventions.
5. After ship, paste the kit's `/brutal-honest-review` and address
   findings.
6. Repeat.

If you batch multiple features into one release, name them like
`v0.5.0: features #1 + #5` in the commit, and update mvp-spec with
all new assertions together.

Pre-commitment from v0.4: when `open_code.py` next exceeds 1000
lines, extract `cli.py` (argparse + main glue) before adding new
scope. Several Tier 1 prompts above will push past that line —
expect to do the extraction before #1, #2, or #3.
