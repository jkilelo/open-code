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

**v0.2.0 ships 🟢.**

---

## Carried gaps (deferred to v0.3+)

- ⚪ Multi-LLM support (Mara persona trigger)
- ⚪ Tool allowlist mode + `--ask` interactive permission prompts
- ⚪ Audit log of denylist hits / path-sandbox refusals
- ⚪ `--prune-sessions` to clean old SQLite history
- ⚪ Streaming-aware function-call rendering (calls still appear at end of iter)
- ⚪ Pyright `reportUnknownMemberType` warnings (cosmetic, runtime works)

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
