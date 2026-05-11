# Personas

> v0.1 ships the primary persona's workflow. Secondary/tertiary wait
> until v0.1 is concretely [OK] against the primary's criterion.

---

## Primary persona -- v0.1 ships this workflow

### Jeff -- Indie developer building LLM-driven systems

**Daily pain (current workflow):**

Jeff has been building agentGraph in Claude Code. Each session costs
$0.20-$1.00, with ~95k tokens of context overhead per call. A
productive coding day burns $5-$15 in Anthropic credits. He has a
Gemini API key with a generous free tier (Gemini 1.5/2.5 Flash is
free for most personal use) sitting idle. When he wants to spin up
a quick coding task -- "scaffold a small CLI", "add a feature to a
prototype", "explore an unfamiliar codebase" -- paying Anthropic
prices feels disproportionate for the task. He's also wary of
vendor lock-in: every project he builds in Claude Code is a
project he can't trivially run with a different LLM if Anthropic
changes terms, pricing, or availability.

What he tries today: VS Code + chat panels (no agentic loop, lots
of copy-paste). Aider (good, but Python-only and limited tool
surface). Direct curl to Gemini (no loop, no tool use). None of
these match Claude Code's "describe what you want, watch it read
files / write files / run commands / iterate" workflow.

**Primary workflow (v0.1 ships this one thing):**

From a terminal in any project directory:

```
open-code "scaffold a Python CLI that does X"
```

`open-code` is a single-file Python 3.13 script. It talks to Gemini
(or any LLM with a function-calling API), runs an agentic loop with
four tools: `read_file`, `write_file`, `run_shell`, `list_dir`.
Jeff watches it work, the same way he watches Claude Code work.
When it finishes, he has new/edited files in his project. He runs
his own tests, accepts or rejects.

**Success criterion (the "outperforms Claude Code for cheap tasks" bar):**

- Cold-start `open-code "task"` to first model token: < 5 seconds.
- Successfully completes a task that requires >=3 tool calls (e.g.,
  "read foo.py, add a docstring, save it"). Real Gemini API. No
  mocks.
- Cost per task: at least 10x cheaper than Claude Code for an
  equivalent task. Measured by tokens.
- Cross-platform: same `python open_code.py "task"` works on
  Windows / macOS / Linux without per-platform branches.
- Total surface: one Python file <= 500 lines, plus
  `requirements.txt` with <= 5 deps.
- Fails loudly on bad input: missing API key -> clear error, not a
  traceback. Network error -> clear error. Tool-execution error ->
  surfaced to model, model decides next step.

**What "no" looks like (anti-success):**

- Silently produces broken code without surfacing tool errors.
- Hidden prompt-injection vulnerability (e.g., a file Jeff reads
  contains "ignore previous instructions" and open-code obeys).
- Hardcoded paths or shell syntax that breaks on Windows.
- Requires a server, daemon, or background process.
- More than one file to ship in v0.1.
- Anthropic dependency anywhere (no claude SDK, no anthropic
  package).

---

## Secondary persona -- v0.2 candidate

### Mara -- Backend engineer at a SOC2-regulated startup

Wants the same workflow but pinned to her org's internal LLM gateway
(routes to Vertex/Bedrock/OpenAI behind a SSO/compliance layer).
v0.2 should let her plug a custom HTTP endpoint + custom request/
response adapter so open-code works against her gateway.

Out of v0.1; will land in v0.2 once Jeff's loop is concretely [OK].

---

## Tertiary persona -- v0.3+ backlog

### Quinn -- ML researcher running on a laptop without internet

Wants open-code to work against a local model (Ollama,
llama.cpp, MLX). Needs offline tool-use compatibility. Adds a
local-LLM adapter when Mara's gateway adapter exists.

Out of v0.1.

---

## Notes

- The primary persona's pain is real and measurable (cost). The MVP
  bar is "useful enough that Jeff would reach for `open-code` instead
  of `claude` for at least 30% of his daily sessions" -- operationalized
  in mvp-spec.md as a token-cost ratio.
- v0.1 is deliberately LLM-singular (Gemini only) to keep the slice
  small. v0.2's Mara persona is what motivates the adapter abstraction;
  building it for v0.1 would be speculative.
