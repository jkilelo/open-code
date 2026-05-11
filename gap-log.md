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

## Carried gaps (deferred to v0.2)

- ⚪ Streaming output — spec marks OUT of v0.1
- ⚪ Multi-turn session memory — spec marks OUT of v0.1
- ⚪ Tool sandboxing / `--ask` mode — spec marks OUT; document `run_shell` as v0.1 acceptable risk
- ⚪ Adapter abstraction for Mara persona (custom LLM gateway) — v0.2 trigger
- ⚪ Pyright `reportUnknownMemberType` warnings on TOOL_DECLARATIONS dict literals — cosmetic, runtime works

---

## Kit issues surfaced during this build

- 🟡 **persona-mvp-kit ships no `.gitattributes`** — every commit on Windows
  raises CRLF→LF warnings. Fixing in the kit repo this session.
