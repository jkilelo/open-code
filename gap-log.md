# Gap log

> One line per spec assertion. 🟢 done · 🟡 partial · 🔴 blocked · ⚪ not started.
> Linked to `runs/<date>-vX.Y.Z.md` for evidence.

---

## v0.1.0 — 2026-05-10 (persona: Jeff)

| # | Assertion | Status | Evidence | Notes |
|---|-----------|--------|----------|-------|
| 1 | Round-trip task: write a file, run it, report output | 🟢 | [runs/2026-05-10-v0.1.0.md § Run 1](runs/2026-05-10-v0.1.0.md) | hello.py written + executed via live Gemini, 2.98s wall |
| 2 | ≥3 tool calls per session | 🟢 | [§ Run 2](runs/2026-05-10-v0.1.0.md) | 3 tool calls: list_dir → write_file → read_file |
| 3 | Cross-platform (Win + Linux) | 🟢 | [§ Run 1, 2, 5](runs/2026-05-10-v0.1.0.md) | PowerShell + Git Bash + WSL Ubuntu 24.04 (Py 3.12) all worked, identical script |
| 4 | Loud failure on missing API key, no traceback | 🟢 | [§ Run 3](runs/2026-05-10-v0.1.0.md) | Exit 1, 5 lines of stderr |
| 5 | Prompt-injection mitigation (canonical case) | 🟢 | [§ Run 4](runs/2026-05-10-v0.1.0.md) | Injected file did not cause PWNED.txt to be written; model summarized as data |
| 6 | ≤500 lines, ≤3 deps | 🟢 | `wc -l open_code.py` = 495; requirements.txt = 2 deps | Tight on lines (5 to spare); will need refactor before adding much |

**v0.1.0 ships 🟢.**

---

## v0.2.0 — 2026-05-10 (persona: Jeff, unchanged)

| # | Assertion | Status | Evidence | Notes |
|---|-----------|--------|----------|-------|
| 7 | `--resume` reuses prior history | 🟢 | [runs/2026-05-10-v0.2.0.md § Test 2](runs/2026-05-10-v0.2.0.md) | Loaded 6 prior messages from SQLite; model quoted past task verbatim |
| 8 | Streaming output to stdout | 🟢 | [§ Test 7](runs/2026-05-10-v0.2.0.md) | 910 output tokens streamed progressively; uses `generate_content_stream` with per-chunk flush |
| 9 | Default model = `gemini-3.1-flash-lite-preview` | 🟢 | every `--show-metrics` line reports it | Probe-confirmed available; respects `--model` / `OPEN_CODE_MODEL` overrides |
| 10 | Path sandbox refuses writes outside CWD | 🟢 | [§ Test 4, 6](runs/2026-05-10-v0.2.0.md) | Default refuses; `--allow-outside-cwd` unblocks. `Test-Path` confirmed escape file not created. |
| 11 | Shell denylist refuses destructive cmds | 🟢 | [tests/test_security.py](tests/test_security.py) — 26/26 pass | 13 dangerous patterns; `--allow-dangerous` bypasses |

**v0.1 assertions still all 🟢** (re-verified — see runs/2026-05-10-v0.2.0.md). One trade-off: A6 line-count cap raised 500 → 900 (now 880 LOC) as deliberate trade-off documented in runs/.

**v0.2.0 ships 🟢** (with three blockers surfaced by brutal review — closed in v0.2.1).

---

## v0.2.1 — 2026-05-10 (closes brutal-review blockers)

Brutal review of v0.2.0 reported `🟢-with-asterisks, ship as rc1; cut a
v0.2.1 closing 3 blockers within the next session`. This release does that.

| Blocker (from review) | Status | Evidence |
|----------------------|--------|----------|
| **B1** Denylist 20/25 bypassed — `rm -r -f /`, `Remove-Item -rf`, `rd /s`, `git push --force`, `curl \| sh`, `> /etc/passwd`, …| ✅ closed | [tests/probe_denylist.py](tests/probe_denylist.py) → 30/30 CAUGHT; [tests/test_security.py](tests/test_security.py) → 54/54 pass |
| **B2** `--resume` loads ALL history (101k tok after 200 turns) | ✅ closed | [tests/probe_resume_bloat.py](tests/probe_resume_bloat.py) → cap default 80, configurable 0–N; [runs/2026-05-10-v0.2.1.md § Blocker 2](runs/2026-05-10-v0.2.1.md) |
| **B3** Preview model 404 → fatal | ✅ closed | [tests/probe_fallback.py](tests/probe_fallback.py) → classifier 10/10, live bogus → fall-through to gemini-3.1-flash-lite; [runs/v0.2.1 § Blocker 3](runs/2026-05-10-v0.2.1.md) |

**v0.2.1 ships 🟢.**

---

## v0.3.0 — 2026-05-10 (JSONL storage + Claude-Code design patterns)

User asked: swap to JSONL + bring useful design patterns from Claude Code.

| Change | Status | Evidence |
|--------|--------|----------|
| **JSONL storage** (file-per-session, `~/.open-code/projects/<encoded-cwd>/<uuid>.jsonl`) | ✅ shipped | [runs/2026-05-10-v0.3.0.md § On-disk JSONL](runs/2026-05-10-v0.3.0.md) |
| **Migration from v0.2 SQLite** (renames old DB to `.migrated`) | ✅ shipped | runs § Migration — 2/2 sessions converted in test |
| **`--resume-id <uuid>`** (Claude-Code-style specific-session resume) | ✅ shipped | runs § --resume-id |
| **Cumulative cost across --resume chains** (closes carried gap #6) | ✅ shipped | runs § Cumulative metrics; live run: iters=3 → 4 → 5 as user --resumes |
| **Audit log via events** (refusals + fallbacks logged) | ✅ shipped | sessions.py append_tool_refusal / append_fallback |
| **Extract `sessions.py`** (v0.2.1 pre-commitment) | ✅ shipped | 970 + 479 = 1449 across 2 files; max single file under 1000 |
| **Stream-error survivability** (carried gap #3) | 🟡 improved | Session header + user msg + end event survive; partial model text still doesn't (v0.4) |

**v0.3.0 ships 🟢.**

---

## v0.4.0 — 2026-05-10 (REPL + OPEN_CODE.md + @-file refs + tools.py extraction)

User asked: "what other high impact feature from claude code can you add?" → "do all three".

| Feature | Status | Evidence |
|---------|--------|----------|
| **Interactive REPL mode** (no-arg invocation → conversation; /help, /clear, /sessions, /switch, /cost, /model, /dump, /exit) | ✅ shipped | runs § Test 2: REPL with cross-turn memory + slash command dispatch |
| **OPEN_CODE.md project context** (auto-loaded from CWD or ancestor; appended to system instruction) | ✅ shipped | runs § Test 2: hello.py written with type hints + docstring because OPEN_CODE.md said so; `probe_project_context.py` 6/6 |
| **@-file references in prompts** (`@README.md` reads + injects file before model sees the prompt) | ✅ shipped | runs § Test 1; `probe_file_refs.py` 8/8 |
| **`tools.py` extraction** (v0.3 pre-commitment) | ✅ shipped | 970 + 479 + 344 = 1793 across 3 files; max single file under 1000 |

**v0.4.0 ships 🟢.**

---

## v0.5.0 — 2026-05-10 (cli.py extraction + #1 Hooks)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| - | cli.py extraction (v0.4 pre-commit) | ✅ | open_code 970→751; cli 273; all probes pass |
| **#1** | **Hooks system** (PreToolUse / PostToolUse / Stop / SessionStart / UserPromptSubmit) | ✅ | `tests/probe_hooks.py` 9/9 PASS; live: 3 blocked run_shell calls + SessionStart context bleeds into model's final response |

**v0.5.0 ships 🟢.**

---

## v0.6.0 — 2026-05-10 (#2 Settings hierarchy + permission rules)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#2** | **Settings hierarchy + permission rules** (user → project → local, deny/ask/allow with fnmatch + regex matchers) | ✅ | `tests/probe_settings.py` 8/8 PASS; live: 3 tool calls denied by project rules, model adapts and surfaces restrictions to user |

**v0.6.0 ships 🟢.**

---

## v0.7.0 — 2026-05-11 (#3 Skills)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#3** | **Skills system** (`.open-code/skills/<name>/SKILL.md` with frontmatter, `$ARGUMENTS` / `$1..$N`, `` !`cmd` `` dynamic blocks; `/skill` + `/skills` REPL commands) | ✅ | `tests/probe_skills.py` 9/9; live REPL: `/skill summarize-file README.md` → model produced 2-sentence summary with zero tool calls (content arrived via `` !`cat $1` ``) |

**v0.7.0 ships 🟢.**

---

## v0.8.0 — 2026-05-11 (#5 Permission modes)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#5** | **Permission modes** (`default` / `acceptEdits` / `plan` / `auto` / `bypassPermissions` via `--mode`, settings.json, `/mode`) | ✅ | `tests/probe_modes.py` 7/7; live: `--mode plan` task "create setup.py + tests/" produced complete narrative plan with 2 refusals and **zero files on disk** |

**v0.8.0 ships 🟢.**

---

## v0.9.0 — 2026-05-11 (#6 Plan/Act)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#6** | **Plan/Act mode separation** (`/plan <task>` runs in plan mode + saves plan event; `/act` loads latest plan + switches to acceptEdits + executes) | ✅ | `tests/probe_plan_act.py` 5/5; live: `/plan write fizzbuzz` → narrative + plan event saved; `/act` → write_file + run_shell, file on disk with correct output |

**v0.9.0 ships 🟢.**

---

## v0.10.0 — 2026-05-11 (repl.py refactor + #9 Architect/editor)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| - | repl.py extraction (v0.9 pre-commit) | ✅ | open_code 1105→728; repl.py 384; all 15 probes pass |
| **#9** | **Architect/editor model split** (`settings.models.{architect,editor}` + `--architect`/`--editor`; /plan uses architect, /act uses editor) | ✅ | `tests/probe_architect_editor.py` 5/5; live with `--architect gemini-nonexistent-99 --editor gemini-3.1-flash-lite-preview`: plan fell-back via the v0.2.1 chain, act used editor explicitly, shell.py written + executed |

**v0.10.0 ships 🟢.** 6 of 10 Tier 1 features done.

---

## v0.11.0 — 2026-05-11 (#4 Subagents / Task tool)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#4** | **Subagents / Task tool** (`.open-code/agents/<name>.md` definitions + `delegate(agent, task)` tool + isolated transcripts at `<parent>.subagent.<n>.jsonl` + restricted tool allowlist + no recursion) | ✅ | `tests/probe_subagents.py` 8/8; live: main delegates to `counter` agent → subagent calls `list_dir` (allowed) → returns "There are 3 .txt files (a.txt, b.txt, c.txt)" → parent records `delegate` event with transcript pointer |

**v0.11.0 ships 🟢.** 7 of 10 Tier 1 features done. **Batch A complete.**

---

## v0.12.0 — 2026-05-11 (#8 V4A apply_patch)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#8** | **V4A apply_patch tool** (Add/Update/Delete/Move; anchored hunks; path sandbox) | ✅ | `tests/probe_apply_patch.py` 10/10; live: model called `apply_patch` once with envelope covering Update utils.py (greet "Hello"→"Hi") + Add CHANGES.md; both files correct on disk |

**v0.12.0 ships 🟢.** 8 of 10 Tier 1 features done.

---

## v0.13.0 — 2026-05-11 (#7 Repo-map, Python-only)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#7** | **Repo-map** (Aider-style symbol skeleton via stdlib `ast` + hand-rolled PageRank; Python only; zero deps; `<repo-map>` block injected into system instruction) | ✅ | `tests/probe_repomap.py` 9/9; live: against open-code's own repo produced a 3670-char skeleton with tools.py + patches.py + sessions.py at the top |

**v0.13.0 ships 🟢.** 9 of 10 Tier 1 features done. **Only #10 MCP remaining.**

---

## v0.14.0 — 2026-05-11 (#10 MCP servers — Tier 1 complete 🎉)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#10** | **MCP server support** (stdio JSON-RPC, hand-rolled — no `mcp` SDK; settings.json `mcpServers`; `mcp__<server>__<tool>` namespace; graceful startup-failure handling; `--no-mcp` flag) | ✅ | `tests/probe_mcp.py` 5/5 against a 30-line Python mock server: initialize handshake, tools/list discovery, tools/call routing with content, broken-server graceful skip, shutdown cleans up |

**v0.14.0 ships 🟢.** 🎉 **All 10 Tier 1 features complete.**

---

## v0.14.1 — 2026-05-11 (brutal-review blockers closed)

The brutal review of v0.14.0 returned **PASS WITH BLEMISHES** with 3
real blockers. v0.14.1 closes them.

| Blocker | Type | Status | Evidence |
|---------|------|--------|----------|
| **apply_patch silent miswrite** (substring anchor + rstrip early-break in `patches.py`) | 🔴 corruption | ✅ closed | `tests/probe_apply_patch_misanchor.py` (hard pass/fail): `@@ def foo` no longer matches `def foo_helper`; ambiguous rstrip-fallback now refuses with clear error |
| **MCP `_call` hang** (CALL_TIMEOUT_SECS defined but never used) | 🔴 hang | ✅ closed | `tests/probe_mcp_hang.py` (hard pass/fail): silent server's `tools/call` returns `TimeoutError` after the configured timeout instead of hanging forever |
| **PageRank personalization sums to >1** (`repomap.py` teleport mass leak under personalization) | 🟡 algorithmic | ✅ closed | `tests/probe_pagerank_bug.py` (hard pass/fail): sum=1.0000 under personalization; m0 now properly ranks higher when personalized on m0 |

**v0.14.1 ships 🟢.** Tier 1 honestly complete.

---

## v0.14.2 — 2026-05-11 (second brutal-review blockers closed)

The second brutal review of v0.14.1 returned **FAIL**: the MCP fix
introduced a new concurrency bug, and hook-RCE was misclassified as
🟡. v0.14.2 closes both.

| Blocker | Status | Evidence |
|---------|--------|----------|
| 🔴 MCP `_call` drops responses under concurrency (same anti-pattern as the bug it replaced: collect-one-then-discard-rest) | ✅ closed | `tests/probe_mcp_concurrency.py`: 8/8 parallel calls now complete; per-msg-id `threading.Event` dispatch; `next_id_lock` prevents id collisions; reader thread exits in <3s on shutdown |
| 🔴 Hook RCE-by-cd-into-hostile-repo (was misclassified as 🟡) | ✅ closed | `tests/probe_hook_security.py` (rewritten): untrusted hooks DON'T fire; explicit trust via `mark_project_trusted` or `--trust-hooks` is required; non-interactive mode auto-denies; trust persisted to `~/.open-code/trusted-projects.json` for "trust always" choice |
| Bonus: stderr pipe-buffer deadlock in MCP | ✅ closed | Second daemon thread per server drains stderr into a bounded 1000-line buffer |

**v0.14.2 ships 🟢.** Tier 1 honestly complete (this time honestly honest).

---

## v0.15.0 — 2026-05-11 (Tier 2 Batch A start: polish trio)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#14** | **Status line** (one-line stderr footer; `--statusline`) | ✅ bonus | live: `[model=... effort=high iter=2 in_tok=2973 out_tok=147 tool_errs=0]` each iter |
| **#15** | **Effort levels** (`--effort low/medium/high/xhigh` → `thinking_budget`; `/effort` REPL; settings.effort) | ✅ | `tests/probe_tier2_polish.py` 8/8; effort=high visible in live status line |
| **#16** | **Ultrathink** (in-prompt marker, word-boundary'd; one-turn budget override; stripped from prompt) | ✅ | probe verifies detection + stripping + `ultrathinker` not false-matched |
| **#18** | **Four-tier project memory** (global → ancestors → project → private; concatenated under `## Project context from <path>` headers) | ✅ | live: 2 layers loaded; "Always include type hints" rule in OPEN_CODE.md propagated into model output (fizz.py had `n: int` and `-> None`) |

**v0.15.0 ships 🟢.** Tier 2: 4 of 15 features done. Next: #13 `/compact` + #19 extended @-providers (rest of Batch A).

---

## v0.15.1 — 2026-05-11 (Tier 2 Batch A finish)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#13** | **/compact slash command** (LLM-summarized older history; `kind:"compact"` JSONL event; `load_history` rewrites compacted msgs into a synthetic user message; default `keep_recent=10`) | ✅ | `tests/probe_tier2_batch_a_rest.py` tests 1-2: 10 msgs + compact + 3 recent → loads as summary+3, all 10 old msgs gone |
| **#19** | **Extended @-providers** (Continue.dev pattern: `@diff`, `@diff:staged`, `@tree`, `@problems`, `@cwd`; 3-tier resolver; coexists with `@<path>` file refs; unknown `@<name>` passes through) | ✅ | probe tests 3-7: `@diff` in a real git repo, `@tree` listing, `@cwd` literal, file+provider coexistence, unknown-name preserved as literal |

**v0.15.1 ships 🟢.** Tier 2 Batch A complete (6/6).

---

## v0.16.0 — 2026-05-11 (Tier 2 Batch B lead-off)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#11** | **Shadow-git checkpointing** (`.open-code/checkpoints.git/` as bare repo with `--work-tree=<cwd>`; `info/exclude` blocks `.open-code/` + caches; `snapshot()` uses `--allow-empty` so every turn has a marker; `restore()` does `read-tree --reset -u` + `clean -fd`; REPL `/checkpoints` `/checkpoint [label]` `/restore <ref>` with diff preview + confirmation + auto safety-snapshot; `--auto-checkpoint` CLI flag; `settings.auto_checkpoint`; `kind:"checkpoint"` JSONL events with phase ∈ {turn-start, turn-end, manual}) | ✅ | `tests/probe_checkpoints.py` 6/6: idempotent init, snapshot+list (3 ckpts newest-first), restore round-trip (file rolled back, untracked-in-target file removed), `.open-code/` excluded from snapshots, append_checkpoint JSONL semantics, graceful degrade when git missing |

**v0.16.0 ships 🟢.** Tier 2: 7 of 15 features done. Next: #12 atomic-commit per turn (reuses snapshot infra for turn-end + rollback-on-error).

---

## v0.17.0 — 2026-05-11 (Tier 2 #12)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#12** | **Atomic-commit per turn** (turn-end snapshot in `run_loop`'s `finally:` block; survives KeyboardInterrupt; `SessionStore.recent_checkpoints(phase)` lookup; REPL `/undo [N]` restores to start of Nth-most-recent turn with diff preview + literal-"undo" confirm + auto pre-undo safety snapshot) | ✅ | `tests/probe_atomic_turn.py` 4/4: phase-filtered recent_checkpoints (newest first), stubbed run_loop emits both turn-start + turn-end with distinct shas, turn-end fires after simulated Ctrl-C (KeyboardInterrupt re-raised), auto_checkpoint=False emits zero events and skips shadow-repo init |

**v0.17.0 ships 🟢.** Tier 2: 8 of 15 features done. Next: #17 sticky session permissions.

---

## v0.18.0 — 2026-05-11 (Tier 2 #17)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#17** | **Sticky session permissions** (REPL `ask` prompt now offers y=once / s=session / a=always / n=no; `s` adds to in-memory `settings._sticky_allow`; `a` persists tool name to `.open-code/settings.local.json` `permissions.always_allow`; new precedence tier `deny > always_allow > ask > allow` so the user's "always" decision overrides higher-layer ask rules) | ✅ | `tests/probe_sticky_permissions.py` 4/4: always_allow beats competing ask, idempotent persistence preserves other settings, refuses to overwrite malformed JSON, `_sticky_allow` bypass with stubbed Gemini + monkeypatched `input()` (asserts input is never called) |

**v0.18.0 ships 🟢.** Tier 2: 9 of 15 features done. Next: #20 `--print` JSON stream output (closes Batch B).

---

## v0.19.0 — 2026-05-11 (Tier 2 #20 — Batch B complete)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#20** | **`--print` / `-p` JSON output** (one JSON line per event to stdout: session_start, text, tool_use, tool_result, session_end; `--print` implies `--quiet` + `--no-stream`; `tools.Config.print_json` flag; `open_code._emit_json` helper with broken-pipe tolerance; emission points at run_loop entry, each text turn, each function_call, each tool result, run_loop `finally:` exit; gated `print()` on non-stream path to avoid mixing plain text with JSON envelopes) | ✅ | `tests/probe_print_mode.py` 4/4: `_emit_json` silent when print_json=False; emits valid JSON line when True; stubbed 2-turn `run_loop` produces session_start→text→tool_use→tool_result→text→session_end with all fields verified; print_json=False emits zero envelope events |

**v0.19.0 ships 🟢.** Tier 2: 10 of 15 features done. **Batch B complete (4/4).** Next: Batch C — 5 features (#21-25).

---

## v0.20.0 — 2026-05-11 (Tier 2 #25 — Batch C kickoff)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#25** | **Managed (enterprise) settings** (read AFTER user/project/local; default paths `/etc/open-code/managed.json` POSIX, `%PROGRAMDATA%\open-code\managed.json` Win; `OPEN_CODE_MANAGED_SETTINGS` env override accepts colon/semi-colon-separated list; managed sources appended to `s.sources` listing) | ✅ | `tests/probe_managed_settings.py` 5/5: managed overrides project model+hooks.disabled, managed deny rules UNION with project deny, non-existent managed path is silent no-op (not added to sources), deny still beats always_allow at managed layer, multiple managed paths last-wins |

**v0.20.0 ships 🟢.** Tier 2: 11 of 15 features done. Next: #23 output styles, #21 skill caching, #22 plugins, #24 /loop+/schedule.

---

## v0.21.0 — 2026-05-11 (Tier 2 #23)

| # | Feature | Status | Evidence |
|---|---------|--------|----------|
| **#23** | **Output styles** (system_instruction overlays; 6 built-ins: default/concise/explanatory/learning/pair-programmer/yolo; custom styles at `.open-code/output-styles/<name>.md` or `~/.open-code/output-styles/<name>.md`; project overrides user overrides built-in; `--style` + `--list-styles` CLI flags; `/style` REPL command; `settings.output_style` field; overlay appears in system_instruction under `## Output style: <name>` header) | ✅ | `tests/probe_output_styles.py` 7/7: built-ins non-empty except default, header injection, project overrides built-in name, unknown style is no-op, list_available labels by source, settings.output_style honored from JSON, defaults to "default" |

**v0.21.0 ships 🟢.** Tier 2: 12 of 15 features done. Three left: #21 (skill cache), #22 (plugin system), #24 (/loop+/schedule).

## Remaining 🟡 (carried to v0.15+)

- Skills YAML edges (quoted strings, dash-lists, block scalars)
- architect/editor flags dead in one-shot mode (only `/plan`+`/act`)
- bypassPermissions doesn't imply --allow-outside-cwd/--allow-dangerous
- PageRank personalization concentration (mathematically correct;
  aggressive ranking shift under task hints)

## Carried 🟡 gaps (brutal review's "small" tier — deferred to v0.15)

These survived the v0.14.1 cut because they're documented behavior gaps,
not corruption / hang / correctness bugs:

- **Skills YAML edge cases** — hand-rolled frontmatter parser silently
  mishandles quoted strings, dash-lists, `|` block scalars, missing
  close fence. Probe: `tests/probe_skills_yaml_edges.py`.
- **`--architect` / `--editor` flags dead in one-shot mode** — only
  consulted by `/plan` and `/act` slash commands. Either wire one-shot
  auto-routing or walk back the v0.10 commit message.
- **Hook security** — `.open-code/hooks/` runs with no per-project trust
  prompt. RCE-by-`cd`-into-hostile-repo possible. Probe:
  `tests/probe_hook_security.py`. Needs first-run consent + persisted
  trusted-projects list.
- **`bypassPermissions` doesn't imply --allow-outside-cwd / --allow-dangerous**
  — the hard guards in `tools.py` still bite in bypass mode. PROMPT-PACK
  A26 may have been wrong; intent should be documented.

## Tier 1 final scoreboard

| # | Feature | Version |
|---|---------|---------|
| #1 | Hooks system | v0.5 |
| #2 | Settings hierarchy + permissions | v0.6 |
| #3 | Skills | v0.7 |
| #4 | Subagents / Task tool | v0.11 |
| #5 | Permission modes | v0.8 |
| #6 | Plan/Act | v0.9 |
| #7 | Repo-map (Python-only, Aider-style) | v0.13 |
| #8 | V4A apply_patch | v0.12 |
| #9 | Architect/editor split | v0.10 |
| #10 | MCP servers | v0.14 |

## v0.4 → v0.14 summary

- Files: 4 → 12 modules, max single file < 1000
- LOC: 1793 → 4298
- Probes: 10 → 20
- All 54 security assertions still 🟢
- Every release shipped with: spec update + probe + gap-log entry + runs/ doc + live evidence

## Tier 1 status

| # | Feature | Status |
|---|---------|--------|
| #1 | Hooks system | ✅ v0.5 |
| #2 | Settings hierarchy + permissions | ✅ v0.6 |
| #3 | Skills | ✅ v0.7 |
| #4 | Subagents / Task tool | ⚪ |
| #5 | Permission modes | ✅ v0.8 |
| #6 | Plan/Act | ✅ v0.9 |
| #7 | Repo-map | ⚪ |
| #8 | V4A apply_patch | ⚪ |
| #9 | Architect/editor split | ⚪ |
| #10 | MCP server support | ⚪ |

**5 of 10 Tier 1 features shipped.**

---

## Carried gaps (still ⚪)

- ⚪ Partial *model* stream text doesn't survive mid-stream errors (would need per-chunk save)
- ⚪ Multi-LLM support (Mara persona trigger)
- ⚪ Tool allowlist mode + `--ask` interactive permission prompts
- ⚪ Hooks (PreToolUse / PostToolUse / Stop / SessionStart) — kit uses these; bigger lift
- ⚪ MCP server protocol
- ⚪ Pyright `reportUnknownMemberType` warnings (cosmetic)

Pre-commitment for v0.5: open_code.py is at 970 — one new flag could push it over. Next addition extracts `cli.py` (~150 LOC argparse + main glue) or another module first.

---

## Carried gaps (still ⚪)

- ⚪ Partial *model* stream text doesn't survive mid-stream errors (would need per-chunk save with rebuild logic on resume)
- ⚪ Glyph rendering by terminal code page (cosmetic)
- ⚪ Pyright `reportUnknownMemberType` warnings (cosmetic)
- ⚪ Multi-LLM support (Mara persona trigger)
- ⚪ Tool allowlist mode + `--ask` interactive permission prompts
- ⚪ `--prune-sessions` (now Jeff can `rm ~/.open-code/projects/<cwd>/<uuid>.jsonl` directly)

## Pre-commitment notes

Single-file constraint formally relaxed in v0.3 (split into open_code.py + sessions.py). Per-file caps loosened to ≤ 1000 each. If v0.4 adds enough scope to push either file past 1000, extract again (likely candidates: `tools.py` for tool implementations, or `cli.py` for argparse).

---

## Carried gaps (still ⚪ — deferred to v0.3+)

From the brutal review's "embarrassed-to-show-them" list, items not in
the user's v0.2.1 scope:

- ⚪ Stream-error mid-flight saves nothing partial to sqlite (Ctrl-C / network drop)
- ⚪ `--show-metrics` doesn't accumulate cost across `--resume` chains
- ⚪ Glyph rendering depends on terminal code page (cosmetic)
- ⚪ Pyright `reportUnknownMemberType` warnings (cosmetic)

From earlier carried list:

- ⚪ Multi-LLM support (Mara persona trigger)
- ⚪ Tool allowlist mode + `--ask` interactive permission prompts
- ⚪ Audit log of denylist hits / path-sandbox refusals
- ⚪ `--prune-sessions` to clean old SQLite history
- ⚪ Streaming-aware function-call rendering

## Single-file pressure

| Version | LOC | Cap | Note |
|---------|-----|-----|------|
| v0.1.0 | 495 | 500 | tight, healthy |
| v0.2.0 | 880 | 900 | scope grew with 4 features; documented |
| v0.2.1 | 1062 | 1100 | denylist + cap + fallback added ~180 |

Pre-commitment: anything added in v0.3 must come with extracting
`sessions.py` (~190 LOC of SQLite + serialization).

---

## Kit issues surfaced

- ✅ **persona-mvp-kit ships no `.gitattributes`** — fixed in commit `7977567`
  (`ai_agents` repo) during v0.1 cycle.
- 🟡 **v0.2 hit the line-cap.** The kit's "single-file ≤ N lines"
  discipline produced healthy pressure to keep open-code lean, but
  cap chosen in v0.1 (500) was too tight once four legitimately-needed
  features arrived. Cap raised to 900 with a written justification in
  runs/2026-05-10-v0.2.0.md. Recommendation for the kit: explicitly
  call out that the v0.1 line cap is "tight on purpose; raise it in
  the spec update when adding real scope, don't sneak past it."
