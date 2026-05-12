# open-code

An LLM-agnostic terminal coding agent. Like Claude Code, with a
pluggable backend (Gemini / Anthropic / OpenAI), ~6500 lines of
pure-Python source, and a deliberately small footprint.

```
pip install -r requirements.txt
# Pick ONE provider (install only the SDK you'll use):
pip install google-genai   &&  export GEMINI_API_KEY=...     # https://aistudio.google.com/app/apikey
pip install anthropic      &&  export ANTHROPIC_API_KEY=...  # https://console.anthropic.com/
pip install openai         &&  export OPENAI_API_KEY=...     # https://platform.openai.com/api-keys
python open_code.py
```

Gemini is the default. Switch providers via
`.open-code/settings.json -> "llm": {"provider": "anthropic"}` (or
`"openai"`). The factory lazy-imports adapters, so you only pay for
the SDKs you actually use. See [`llm/`](llm/) for the full neutral
protocol + per-provider translation; [`runs/2026-05-12-llm-design.md`](runs/2026-05-12-llm-design.md)
documents the 3-provider research that shaped the interface.

That drops you into a REPL with persistent history, autosuggest from
your prior prompts, tab-complete on slash commands, and Rich-styled
output. Pipe it (`open-code "task" | tee log`) and the output
auto-degrades to pure ASCII. Pass `--print` and you get one JSON
event per line, suitable for IDE integrations or CI scripts.

**Hands-on tutorial:** [`LEARN.md`](LEARN.md) -- progressive walkthrough
with 10 standalone copy-paste-runnable scenarios. Start there if
this is your first time with open-code.

## What you get

- **REPL + one-shot** modes (`python open_code.py` vs `python open_code.py "task"`)
- **Multi-turn conversations** with auto-saved JSONL transcripts under
  `~/.open-code/projects/<encoded-cwd>/<uuid>.jsonl`
- **Tool calls**: `read_file`, `write_file`, `list_dir`, `run_shell`
- **V4A apply_patch** -- multi-file edits in a single envelope
  (OpenAI Codex CLI-compatible)
- **Permission model** -- `default` / `acceptEdits` / `plan` /
  `bypassPermissions` modes; per-tool allow/ask/deny rules with
  fnmatch + regex matchers; sticky-session "always" grants persist
  to `.open-code/settings.local.json`
- **Hooks** -- `PreToolUse` / `PostToolUse` / `Stop` / `SessionStart` /
  `UserPromptSubmit` shell scripts in `.open-code/hooks/`, with a
  per-project trust prompt (no RCE-by-clone)
- **Skills** -- reusable prompt templates at
  `.open-code/skills/<name>/SKILL.md` with `$ARGUMENTS` and
  `` !`shell command` `` blocks; opt-in caching via `cache: true`
- **Subagents** -- `delegate(agent, task)` tool with isolated
  transcripts, restricted tool allowlists, no recursion
- **Architect/editor split** -- different models for `/plan` vs `/act`
- **Repo-map** -- Aider-style symbol skeleton with personalized
  PageRank; auto-injected into the system prompt
- **MCP servers** -- stdio JSON-RPC clients in `settings.json`
- **Shadow-git checkpointing** -- `/checkpoint` / `/restore` / `/undo`
  back to any prior turn without touching your real `.git/`
- **Atomic-commit per turn** -- turn-start + turn-end snapshots
  bracket every prompt
- **`/compact`** -- LLM-summarize older history, keep recent N
  messages verbatim
- **Status line** + **effort levels** (`--effort low/medium/high/xhigh`)
  + **ultrathink** keyword override
- **Four-tier memory** -- global / ancestors / project / private
  OPEN_CODE.md files
- **Extended @-providers** -- `@README.md`, `@diff`, `@tree`,
  `@problems`, `@cwd`
- **Output styles** -- system-instruction overlays
  (default / concise / explanatory / learning / pair-programmer / yolo)
- **Plugins** -- bundles of skills + agents + styles at
  `~/.open-code/plugins/<name>/`
- **`/loop` + `/schedule`** -- repeat a task every N seconds, or
  run once after a delay
- **Managed (enterprise) settings** -- `/etc/open-code/managed.json`
  overrides per-user choices for org-wide policy

## Quick examples

```bash
# One-shot
python open_code.py "write a fizzbuzz to fizz.py and run it"

# REPL with autosuggest + history (~/.open-code/history.txt)
python open_code.py

# Plan mode -- read-only, narrates without writing
python open_code.py --mode plan "refactor this for testability"

# JSON output -- for IDE plugins / CI
python open_code.py --print "summarize README.md"
# emits one JSON event per line:
#   {"type":"session_start","session_id":"...","model":"...","task":"...","cwd":"..."}
#   {"type":"text","iteration":1,"text":"...","input_tokens":42,"output_tokens":120}
#   {"type":"tool_use","iteration":1,"name":"read_file","args":{"path":"README.md"}}
#   {"type":"tool_result","iteration":1,"name":"read_file","ok":true,"result":{...}}
#   {"type":"session_end","session_id":"...","exit_code":0,"iterations":2,...}

# Plain ASCII (auto-detected when piped; force with --plain or NO_COLOR=1)
python open_code.py --plain "show me the tests"

# Auto-checkpoint every turn; recoverable via /undo
python open_code.py --auto-checkpoint

# Resume a prior session
python open_code.py --list-sessions
python open_code.py --resume                 # most recent in this CWD
python open_code.py --resume-id <uuid>       # specific
```

## REPL slash commands

| Command | What it does |
|---|---|
| `/help` | Show all commands |
| `/exit`, `/quit` | Leave |
| `/clear` | Start a fresh session in this CWD |
| `/sessions` | List recent sessions |
| `/switch <uuid>` | Switch to a different session |
| `/cost` | Cumulative tokens/iterations/refusals |
| `/model <name>` | Change the model for subsequent turns |
| `/dump` | Print the path of this session's JSONL |
| `/skills` | List skills under `.open-code/skills/` |
| `/skill <name> [args]` | Run a skill with `$ARGUMENTS` interpolation |
| `/agents` | List subagents under `.open-code/agents/` |
| `/compact [keep]` | Summarize older history; keep last N msgs verbatim |
| `/effort [name]` | Show or set reasoning effort (low/medium/high/xhigh) |
| `/style [name]` | Show or set output style overlay |
| `/mode [name]` | Show or set permission mode |
| `/plan <task>` | Read-only plan mode + save plan to session |
| `/act [task]` | Load most recent plan + execute under `acceptEdits` |
| `/checkpoints` | List shadow-git checkpoints |
| `/checkpoint [label]` | Manual snapshot now |
| `/restore <ref>` | Restore working tree to a prior checkpoint |
| `/undo [N]` | Restore to start of Nth-most-recent turn |
| `/loop <dur> <task>` | Repeat task every duration (e.g. `30`, `5m`, `1h`) |
| `/schedule <dur> <task>` | Run task once after a delay |

## @-references in prompts

```
> review @open_code.py and explain the run_loop
> what changed since main? @diff
> summarize the test failures @problems
> what's in this dir? @tree
> @cwd        -- absolute path of current working directory
```

Local files are read and injected. The `@diff` / `@tree` / `@problems`
/ `@cwd` providers run shell commands at expansion time.

## Configuration

Layered, read in this order (later wins):

1. `~/.open-code/settings.json` -- user
2. `<cwd>/.open-code/settings.json` -- project (committed)
3. `<cwd>/.open-code/settings.local.json` -- project, gitignored
4. `/etc/open-code/managed.json` (POSIX) or
   `%PROGRAMDATA%\open-code\managed.json` (Windows) -- enterprise

Example `.open-code/settings.json` (Gemini default; pick whichever
`llm.provider` you want):

```json
{
  "llm": {
    "provider": "gemini",
    "model":    "gemini-3.1-flash-lite-preview"
  },
  "max_iterations": 25,
  "permissions": {
    "allow": ["read_file", "list_dir"],
    "ask":   ["write_file"],
    "deny":  ["run_shell(rm -rf *)", "run_shell(sudo *)"]
  },
  "models": {
    "architect": "gemini-3.1-pro-preview",
    "editor":    "gemini-3.1-flash-lite-preview"
  },
  "checkpoints": {"auto": true},
  "output_style": "concise",
  "effort": "medium",
  "mcpServers": {
    "ripgrep": {"command": "mcp-rg-server", "args": ["--root", "."]}
  }
}
```

Switch providers by changing the `llm` block. Supported values:

| Provider | `llm.provider` | Default model       | API key env var      | SDK        | Verified  |
|----------|----------------|---------------------|----------------------|------------|-----------|
| Gemini   | `"gemini"`     | `gemini-3.1-flash-lite` | `GEMINI_API_KEY`     | `google-genai` >= 2.1.0 | full REPL + tools + resume + structured + embed (v0.30.0) |
| Anthropic| `"anthropic"`  | `claude-haiku-4-5`  | `ANTHROPIC_API_KEY`  | `anthropic` >= 0.101.0 | full REPL + tools + thinking + adapter smoke 6/6 (v0.30.2) |
| OpenAI Responses (modern) | `"openai"` | `gpt-5-mini` | `OPENAI_API_KEY` | `openai` >= 2.36.0 | full REPL + tools + structured + embed + reasoning_effort (v0.30.3) |
| OpenAI Chat Completions (legacy / OSS-compat) | `"openai_chat"` | `gpt-5-mini` | `OPENAI_API_KEY` | `openai` >= 2.36.0 | adapter compiles + structurally accepted; no live REPL run yet |

"Verified" means a real REPL session against the production API on
that provider produced correct multi-iteration tool dispatch with
identifier round-trip (Gemini `thought_signature`, Anthropic
`tool_use_id`, OpenAI Responses `call_id`). See `runs/2026-05-12-v0.30.{0,2,3}.md`
for the live transcripts.

Override the env var name via `llm.api_key_env`. Pass provider-
specific knobs (Gemini `safety_settings`, Anthropic `betas`, OpenAI
`previous_response_id`, etc.) via `llm.extra`. The neutral protocol
+ per-Part `extra` dict round-trip provider-specific opaque state
(Gemini's `thought_signature`, Anthropic's thinking `signature`,
OpenAI's reasoning `encrypted_content`) through JSONL storage, so
`--resume` works across providers without losing reasoning context.

Permission rules: `Tool` (any args), `Tool(specifier)` (fnmatch on
arg values), `Tool(/regex/)` (regex search). Evaluation order is
`deny > always_allow > ask > allow > default-allow`. `always_allow`
is what the REPL's `[always]` prompt option writes.

## Project memory (OPEN_CODE.md)

Drop an `OPEN_CODE.md` in your project root with project-specific
instructions. open-code auto-loads it (plus any in ancestor dirs,
plus `~/.open-code/OPEN_CODE.md` for global memory, plus
`.open-code/OPEN_CODE.local.md` for private overrides) and appends
to the system instruction.

## Skills

A skill is a reusable, named prompt at
`.open-code/skills/<name>/SKILL.md`:

```markdown
---
name: review-pr
description: Brutal-review a pull request against project standards
allowed-tools: read_file, list_dir, run_shell
cache: false
---
You are reviewing PR $ARGUMENTS.

Project state:
!`git status --short`
!`git diff main --stat | head -40`

Walk the diff. Find: untested branches, surface-area widening, ...
```

Invoke: `/skill review-pr 1234`. The `!` blocks run before the model
sees the prompt; `$ARGUMENTS` / `$1` / `$N` are substituted.

## Subagents

`.open-code/agents/<name>.md`:

```markdown
---
name: counter
description: Counts files of a given type in this CWD
model: gemini-3.1-flash-lite-preview
allowed_tools: [list_dir, read_file]
---
You are a counting subagent. The user will ask you to count files.
Use list_dir to inspect the working directory. Reply with one
sentence: "There are N <type> files: a, b, c."
```

The main agent calls `delegate(agent="counter", task="count .txt
files")`; the subagent gets its own isolated transcript.

## Dynamic specialist agents (autobuild)

The system grows specialists on demand. When the user asks something
domain-specific (SQL, scraping, ML, infra, security, testing), the
model:

1. Calls `find_specialist(query)` -- BM25 search across
   `.open-code/agents/` + `.open-code/autobuild-agents/`
2. If a strong match exists, delegates to it
3. Else calls `request_specialist(domain, task_example, notes)`
   which runs an architect meta-prompt to author a structured agent
   file with role / expert knowledge / workflow / examples / edge
   cases / refusal cases. The file is validated, deduplicated, and
   saved to `.open-code/autobuild-agents/<name>.md`
4. Immediately delegates to the new specialist

Each novel domain teaches the library. By turn 4 you typically have
3-5 specialists; subsequent questions route in microseconds via BM25.

Defense in depth: autobuilt agents are restricted to read-only tools
(`read_file`, `list_dir`). Promoting to `run_shell` / `write_file` /
`apply_patch` requires the user to hand-edit the generated file.
Hand-curated agents in `.open-code/agents/` always shadow autobuild
on name collision.

REPL commands:
- `/autobuild` -- show status + table of the full agent library
- `/autobuild on` / `/autobuild off` -- session toggle
- `/autobuild search <query>` -- direct BM25 query (debugging)

CLI: `--no-autobuild` disables the capability for one invocation.

Probes: `tests/probe_agent_search.py` (7 BM25 assertions),
`tests/probe_agent_builder.py` (10 validation + end-to-end
assertions with a stub LLM).

## Plugins

A plugin bundles skills + agents + styles into one installable unit.
Install by cloning into either:

- `~/.open-code/plugins/<name>/` (user-wide)
- `<cwd>/.open-code/plugins/<name>/` (project-local)

Layout:

```
<plugin-name>/
  plugin.json
  skills/<skill-name>/SKILL.md
  agents/<agent-name>.md
  output-styles/<style-name>.md
```

`plugin.json`:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "...",
  "exposes": {
    "skills":        ["review-pr"],
    "agents":        ["counter"],
    "output_styles": ["zen-mode"]
  }
}
```

`python open_code.py --list-plugins` shows what's installed.

## Hooks

Shell scripts under `.open-code/hooks/` fire on lifecycle events:

| Event | When |
|---|---|
| `PreToolUse` | Before each tool call (block / modify args) |
| `PostToolUse` | After each tool call |
| `Stop` | Before exit (soft-block to force continuation) |
| `SessionStart` | Once on entry (inject additional context) |
| `UserPromptSubmit` | After user types a prompt (transform / block) |

Hooks read JSON from stdin and write JSON to stdout. **The first
time you `cd` into a project with a `.open-code/hooks/` dir,
open-code asks for your trust.** Trust is per-CWD, persisted to
`~/.open-code/trusted-projects.json`. Pass `--trust-hooks` once
to accept without prompting; `--no-hooks` to disable entirely.

## MCP servers

Add to `settings.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
  }
}
```

Each server's tools become available as `mcp__<server>__<tool>`.
The MCP client is hand-rolled (no `mcp` SDK dep): per-msg-id Event
dispatch, separate stderr drainer, graceful startup-failure handling.

## Output

Three modes, auto-detected unless overridden:

| Mode | When |
|---|---|
| `rich` | TTY stderr + no `NO_COLOR` / `OPEN_CODE_PLAIN` env |
| `plain` | piped / `--plain` / `NO_COLOR=1` / `OPEN_CODE_PLAIN=1` |
| `json` | `--print` -- one JSON event per line on stdout |

REPL input (rich + TTY): prompt_toolkit gives you Up/Down history,
autosuggest from history (fish-shell ghost text), Ctrl-R reverse
search, and Tab completion for slash commands. History persists at
`~/.open-code/history.txt`. Falls back to `input()` + readline if
prompt_toolkit can't init (Git Bash on Windows, weird terminals).

## Security

- **Path sandbox** -- `write_file` refuses paths outside CWD unless
  `--allow-outside-cwd`
- **Shell denylist** -- `run_shell` refuses 13 destructive patterns
  (`rm -rf /`, `sudo *`, `curl ... | sh`, etc.) unless
  `--allow-dangerous`. 54-assertion security probe.
- **Hook trust gate** -- per-project consent, persisted, prompts on
  first encounter with `.open-code/hooks/`
- **Permission rules** -- declarative deny/ask/allow at three layers
- **Managed-settings layer** -- org-wide policy overrides for kiosk /
  enterprise deployments
- **Encoding** -- source files are 100% ASCII; enforced by a CI-style
  probe so future commits can't add mojibake

## Development

Build discipline borrowed from the parent
[persona-mvp-kit](https://github.com/jkilelo/ai_agents):

- Every feature ships with a spec, a probe, a runs/ doc, a gap-log
  entry, and a single commit
- 45 probe files in `tests/`
- 54-assertion security test in `tests/test_security.py`
- ASCII-only guard in `tests/probe_ascii_only.py`
- Four brutal-review cycles to date; every blocker closed before
  the next feature

To run the full regression locally:

```bash
for f in tests/probe_*.py; do python "$f" || echo "FAIL: $f"; done
python tests/test_security.py
```

To normalize encoding if it ever drifts:

```bash
python scripts/fix_encoding.py
python tests/probe_ascii_only.py   # verify
```

## How this differs from Claude Code / Aider

| | Claude Code | Aider | open-code |
|---|---|---|---|
| Backend | Anthropic only | many | Gemini / Anthropic / OpenAI (Responses + Chat); pluggable |
| UI | rich + prompt_toolkit | rich + prompt_toolkit | rich + prompt_toolkit |
| MCP servers | yes | no | yes |
| Plugins | yes | no | yes |
| Skills | yes | no | yes |
| Subagents | yes | no | yes |
| Hooks | yes | no | yes |
| Repo-map | no | yes (tree-sitter) | yes (Python stdlib `ast` only) |
| Shadow-git | yes | no | yes |
| LOC | closed-source | ~20K LOC | ~6500 LOC |
| Deps | closed-source | ~30 | 4 + 1 per provider (lazy) |

open-code is not trying to beat them. It's trying to be small enough
that you can read every line in an afternoon, hackable enough that
adding a feature is a single commit, and honest about what it can
and can't do (every gap is in `gap-log.md`).

## License

MIT. Use freely. If you make it better, PRs welcome.

## Status

Tier 1 (10 features) and Tier 2 (15 features) complete. 26 commits
across the v0.1 -> v0.25 line. 4 brutal reviews completed; all
findings closed. 45/45 probes green; 54/54 security tests green.

Honest carry items (none corruption / hang / security; all
documented in [gap-log.md](gap-log.md)):

- Skills YAML edge cases (quoted strings, block scalars)
- `--architect` / `--editor` flags are dead in one-shot mode
  (only `/plan`+`/act` honor them)
- `bypassPermissions` doesn't auto-imply `--allow-outside-cwd`
  / `--allow-dangerous`
- PageRank personalization concentration (mathematically correct,
  aggressive ranking shift under task hints)

If you find a real bug, file an issue with a reproducer. The
build discipline is "every blocker closes with a probe."
