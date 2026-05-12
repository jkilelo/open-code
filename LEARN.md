# Learn open-code -- a hands-on tutorial

A self-contained, copy-paste tutorial. Every example below is
runnable verbatim. No "configure X first" steps -- if a command
needs setup, the setup is in the same code block.

You need:

- Python 3.13 (`py -3.13` on Windows; `python3.13` on POSIX)
- `pip install -r requirements.txt` from a fresh clone
- A Gemini API key at `https://aistudio.google.com/app/apikey` --
  put it in a `.env` file in your project directory:

```
GEMINI_API_KEY=your-key-here
```

open-code auto-loads `.env` via python-dotenv. No shell exports
required.

---

## Section 1 -- First 5 minutes

### 1.1 -- Hello, agent

```
python open_code.py "what's in this directory?"
```

Expected output (abridged):

```
  session: 6e2679e6-ffb8-...  --resume-id 6e2679e6-...
[iter 1] calling gemini-3.1-flash-lite-preview...
  -> list_dir({"path": "."})
  [OK] list_dir -> 46 entries
[iter 2] calling gemini-3.1-flash-lite-preview...
The directory contains 46 entries including Python source files
(open_code.py, repl.py, ...), tests/, runs/, .open-code/ ...
  [iters=2 in=3027t out=46t wall=2.34s tools=1 errs=0]
```

What just happened:

1. open-code created a session at
   `~/.open-code/projects/<encoded-cwd>/<uuid>.jsonl` --
   a JSONL transcript you can replay later.
2. The model called `list_dir(".")` -- a tool open-code provides --
   to inspect the working directory.
3. The model returned a summary.
4. The bottom line shows what the turn cost.

### 1.2 -- Write a file + run it

```
python open_code.py "write fizzbuzz to fizz.py, then run it and show output"
```

Expected (the model will use `write_file` then `run_shell`):

```
  -> write_file({"path": "fizz.py"}) [185 chars]
  [OK] write_file -> wrote 185 bytes to fizz.py
  -> run_shell({"command": "python fizz.py"})
  [OK] run_shell -> exit=0, stdout: 1\n2\nFizz\n4\nBuzz...

I wrote fizz.py and ran it. Output: 1, 2, Fizz, 4, Buzz, Fizz, 7,
8, Fizz, Buzz, 11, Fizz, 13, 14, FizzBuzz.
```

`fizz.py` will exist in your directory afterward. Delete with
`rm fizz.py`.

### 1.3 -- Read a file via @-reference

```
python open_code.py "summarize @README.md in 3 sentences"
```

The `@README.md` is read and injected BEFORE the model sees your
prompt. No tool call needed -- the content is already there.

### 1.4 -- The REPL (interactive)

```
python open_code.py
```

You get a prompt:

```
> _
```

Try:

```
> read fizz.py and explain it
> /skills
> /sessions
> /help
> /exit
```

Up-arrow walks your history (persisted at `~/.open-code/history.txt`).
Tab completes slash commands. Type a partial command and a "ghost"
suggestion appears from your prior prompts (fish-shell style).

---

## Section 2 -- Common patterns

### 2.1 -- Plan first, act second (safe refactors)

`--mode plan` is read-only: the model describes what it would do
without touching anything.

```
python open_code.py --mode plan "refactor open_code.py for testability"
```

Expected: a narrative of proposed changes. NO write_file / run_shell
calls (they're denied in plan mode).

Then, in a REPL session:

```
> /plan refactor open_code.py for testability
[... model produces a plan, saved to the session ...]
> /act
[... model executes the plan, calling write_file etc ...]
```

The plan is saved to the session JSONL; `/act` loads it and switches
to `acceptEdits` mode (auto-allow write_file).

### 2.2 -- Tighter permission control

By default, write_file prompts you in REPL mode. In a single
session you might say "yes-once" 10 times for the same edit pattern.
Use `s=session` to allow that tool for the whole REPL session:

```
> Edit fizz.py to use a function
  ? write_file({"path": "fizz.py", "content": "..."}) [y=once / s=session / a=always / n=no]: s
[sticky-session: 'write_file' will skip prompts until /clear]
  -> write_file({"path": "fizz.py"}) [220 chars]
  [OK] write_file -> wrote 220 bytes to fizz.py
```

`a=always` persists the rule to `.open-code/settings.local.json`
(gitignored, per-machine). The rule is SCOPED to the exact args, so
saying "always" for `run_shell(npm install)` doesn't auto-allow
`run_shell(rm -rf /)`.

### 2.3 -- Structured output for IDE / CI scripts

```
python open_code.py --print "summarize @README.md"
```

Emits one JSON object per line on stdout:

```json
{"type":"session_start","session_id":"...","model":"...","task":"...","cwd":"..."}
{"type":"tool_use","iteration":1,"name":"read_file","args":{"path":"README.md"}}
{"type":"tool_result","iteration":1,"name":"read_file","ok":true,"result":{...}}
{"type":"text","iteration":2,"text":"open-code is ...","input_tokens":2870,"output_tokens":85}
{"type":"session_end","session_id":"...","exit_code":0,"iterations":2,...}
```

Pipe into `jq`:

```
python open_code.py --print "summarize @README.md" | jq -r 'select(.type=="text") | .text'
```

### 2.4 -- Resume an earlier session

```
python open_code.py --list-sessions

# Output:
# Recent sessions in <cwd>
# ID                                    STARTED                    MODEL                              TASK
# ec03649d-aa74-4090-9f56-0f945fc90c96  2026-05-12T15:20:01+00:00  gemini-3.1-flash-lite-preview      what's the larg...

python open_code.py --resume-id ec03649d-aa74-4090-9f56-0f945fc90c96 \
    "what was the largest file again?"
```

The model sees the prior turn's history and can answer without
re-reading anything.

```
python open_code.py --resume   # = most recent in this CWD
```

### 2.5 -- Cheap vs deep thinking

```
python open_code.py --effort low  "fix the typo in @README.md line 3"
python open_code.py --effort high "find every potential race condition in @sessions.py"
```

`--effort` maps to thinking_budget passed to the model
(low=0, medium=512, high=4096, xhigh=16384). Use `low` for cheap
edits; `high`/`xhigh` for analysis.

Also: the magic word `ultrathink` in your prompt bumps THIS turn
to max budget:

```
> ultrathink: design a lock-free MPMC ring buffer with bounded
  capacity and proper visibility semantics
```

The word is stripped before the model sees the prompt.

---

## Section 3 -- The agent library

open-code has THREE layers of named workflow templates:

| Concept | Where | What it is |
|---|---|---|
| **Skill** | `.open-code/skills/<name>/SKILL.md` | a reusable prompt template invoked via `/skill <name>` |
| **Subagent** | `.open-code/agents/<name>.md` | a delegated mini-agent invoked via the `delegate` tool |
| **Autobuild agent** | `.open-code/autobuild-agents/<name>.md` | a subagent the system built for you on demand |

### 3.1 -- Create a skill

```
mkdir -p .open-code/skills/review-pr
cat > .open-code/skills/review-pr/SKILL.md << 'EOF'
---
name: review-pr
description: Brutal review of a PR against project standards
allowed-tools: read_file, list_dir
---
You are reviewing PR $ARGUMENTS.

Project state:
!`git diff main --stat | head -40`

Walk the diff. Find: untested branches, surface-area widening,
silent failures, performance cliffs.
EOF
```

Now in the REPL:

```
> /skill review-pr 1234
```

`$ARGUMENTS` gets `1234`. The `!\`git diff ...\`` block runs the
shell command BEFORE the model sees it; the output replaces the
backtick block. The model sees a complete prompt with real data.

### 3.2 -- Create a subagent

```
mkdir -p .open-code/agents
cat > .open-code/agents/counter.md << 'EOF'
---
name: counter
description: Counts files of a given type in a directory
model: gemini-3.1-flash-lite-preview
allowed-tools: [list_dir, read_file]
---
You are a counting subagent. The user asks you to count files of
a given type. Use list_dir to inspect the working directory. Reply
with one sentence: "There are N <type> files."
EOF
```

In the REPL:

```
> count .py files in this dir
```

The main agent will see the `counter` subagent in the library and
likely call `delegate(agent="counter", task="count .py files")`.
The subagent runs with ONLY `list_dir` and `read_file` permitted
(no write, no shell). Its transcript goes to a separate file:
`<parent-session>.subagent.<n>.jsonl`.

### 3.3 -- Let the system grow specialists for you (Tier 3 autobuild)

When you ask a domain-specific question that doesn't match an
existing agent well, the model:

1. Calls `find_specialist(query)` -- BM25 search across the library
2. If no strong match, calls `request_specialist(domain, task_example)`
3. open-code runs an architect meta-prompt to author a structured
   agent file (role / expert knowledge / workflow / examples /
   edge cases / refusal cases), validates it, saves to
   `.open-code/autobuild-agents/<name>.md`
4. The model immediately delegates to the new agent

Example trigger:

```
python open_code.py "I have a Postgres customers + purchases table.
  Build a recurring monthly-cohort retention report SQL that
  computes 30/60/90-day retention by acquisition month."
```

You'll see (in TTY/rich mode):

```
  -> find_specialist({"query": "sql cohort retention monthly purchases"})
  [OK] find_specialist -> ok       (no strong match)
  + autobuild  building specialist for sql (recurring monthly cohort retention...)
  [spinner: autobuild: gemini-3.1-flash-lite-preview authoring...]
  + autobuild  saved sql-cohort-analytics-agent -> .open-code/autobuild-agents/...
    tools: read_file, list_dir
  -> delegate({"agent": "sql-cohort-analytics-agent", ...})
  [... specialist runs ...]
```

Next session, ask another cohort question -- it routes to
`sql-cohort-analytics-agent` immediately. Compounds with use.

Manage the library:

```
python open_code.py --no-autobuild "..."    # disable for one run

# In the REPL:
> /autobuild                        # status + table
> /autobuild search sql cohort      # BM25 query
> /autobuild history sql-cohort-analytics-agent
> /autobuild revert sql-cohort-analytics-agent
> /autobuild on | off
```

### 3.4 -- Approval flow

By default `auto_approve=true` -- builds happen and get saved.
For stricter control:

```
mkdir -p .open-code
cat > .open-code/settings.local.json << 'EOF'
{
  "autobuild": {
    "auto_approve": false
  }
}
EOF
```

Now requested specialists land in `.open-code/autobuild-agents/.pending/`
and the model is told to ask you for approval first:

```
> /autobuild pending
> /autobuild approve sql-cohort-analytics-agent
> /autobuild reject some-bad-spec
```

### 3.5 -- Versioning

Every overwrite archives the prior version:

```
.open-code/autobuild-agents/
  sql-cohort-analytics-agent.md            <-- live
  .history/sql-cohort-analytics-agent/
    2026-05-12T10-22-14-871234Z.md         <-- archived
    2026-05-12T10-25-03-411082Z.md         <-- archived
```

```
> /autobuild history sql-cohort-analytics-agent
> /autobuild revert sql-cohort-analytics-agent 2026-05-12T10-22
```

Revert itself is reversible -- it archives the outgoing version.

---

## Section 4 -- Customize the system

### 4.1 -- Project memory (OPEN_CODE.md)

Drop an `OPEN_CODE.md` in your project root with project-specific
instructions:

```
cat > OPEN_CODE.md << 'EOF'
# This project conventions

- Always use type hints
- Tests live in tests/probe_*.py
- All comments must be plain ASCII (CI enforces it)
- Never write to /tmp -- use tempfile.TemporaryDirectory()
EOF
```

open-code auto-loads it (plus any in ancestor dirs, plus
`~/.open-code/OPEN_CODE.md` for global memory) and appends to
the system instruction.

Tier order: global -> ancestors -> project -> private
(`.open-code/OPEN_CODE.local.md`, gitignored).

### 4.2 -- Hooks

A hook is a shell script under `.open-code/hooks/<EventName>.sh`.

```
mkdir -p .open-code/hooks
cat > .open-code/hooks/PreToolUse.sh << 'EOF'
#!/bin/bash
# Block any write_file outside the src/ directory.
read -r payload
tool=$(echo "$payload" | jq -r '.tool')
path=$(echo "$payload" | jq -r '.args.path // ""')
if [ "$tool" = "write_file" ]; then
  case "$path" in
    src/*) exit 0 ;;
    *)     echo "writes restricted to src/" >&2; exit 2 ;;
  esac
fi
exit 0
EOF
chmod +x .open-code/hooks/PreToolUse.sh
```

First time you `cd` into a project with hooks, open-code asks for
your trust (the v0.14.2 hook-trust gate -- protects against
RCE-by-cd-into-hostile-repo). Trust is persisted to
`~/.open-code/trusted-projects.json`.

Other events: `PostToolUse`, `Stop`, `SessionStart`, `UserPromptSubmit`.

### 4.3 -- Output style overlays

```
python open_code.py --style concise "explain the agent loop"
```

Built-in styles: `default`, `concise`, `explanatory`, `learning`,
`pair-programmer`, `yolo`.

```
python open_code.py --list-styles
```

Or write your own at `.open-code/output-styles/my-style.md`:

```
You are answering with extreme concision. Lead with the number
or the verdict. Single paragraph unless the user asks for more.
```

```
python open_code.py --style my-style "is this code thread-safe?"
```

### 4.4 -- Settings hierarchy

Four merged layers (lowest precedence first):

1. `~/.open-code/settings.json` -- per-user defaults
2. `<cwd>/.open-code/settings.json` -- per-project (committed)
3. `<cwd>/.open-code/settings.local.json` -- per-machine (gitignored)
4. `/etc/open-code/managed.json` (POSIX) or
   `%PROGRAMDATA%\open-code\managed.json` (Windows) -- enterprise
   policy, overrides everything

Example `.open-code/settings.json`:

```json
{
  "model": "gemini-3.1-flash-lite-preview",
  "permissions": {
    "deny":  ["run_shell(rm -rf *)", "run_shell(sudo *)"],
    "ask":   ["write_file(*)"],
    "allow": ["read_file", "list_dir"]
  },
  "models": {
    "architect": "gemini-3.1-pro-preview",
    "editor":    "gemini-3.1-flash-lite-preview"
  },
  "checkpoints": {"auto": true},
  "output_style": "concise",
  "effort": "medium",
  "autobuild": {
    "enabled": true,
    "auto_approve": true,
    "semantic_search": false
  }
}
```

### 4.5 -- Shadow-git checkpointing + undo

```
python open_code.py --auto-checkpoint "refactor X"
```

Every turn snapshots your working tree into
`.open-code/checkpoints.git/` (a SIDE git repo -- doesn't touch
your real `.git/`). In the REPL:

```
> /checkpoints                  # list recent snapshots
> /restore 9b2c4f1a              # restore to a specific snapshot
> /undo                          # restore to start of last turn
> /undo 3                        # restore to start of 3-turns-ago
```

The `info/exclude` in the shadow repo skips `.open-code/`,
`node_modules/`, `__pycache__/`, etc.

---

## Section 5 -- What's happening inside

### The agent loop (per iteration)

1. **Build the system instruction**: base prompt + OPEN_CODE.md
   layers + repo-map + output-style overlay
2. **Check shadow-git checkpoint** (if `auto_checkpoint`)
3. **Call the model** with: tools = base 4 + delegate +
   find_specialist + request_specialist + apply_patch + every
   MCP-server-exposed tool, plus the full conversation history
4. **For each function-call returned**:
   - Evaluate permission rules (deny > always_allow > ask > allow)
   - Honor permission mode (plan / acceptEdits / auto / bypass)
   - Fire `PreToolUse` hook (can block or modify args)
   - Execute the tool function
   - Fire `PostToolUse` hook
5. **Render**: rich panels on TTY, ASCII columns when piped, JSON
   envelopes under `--print`
6. **If the model produced text** with no further function calls:
   fire `Stop` hook; if it doesn't soft-block, exit the loop.

### Session storage

```
~/.open-code/projects/<encoded-cwd>/<session-uuid>.jsonl
```

Each line is one event: `session`, `msg`, `metrics`, `fallback`,
`refusal`, `plan`, `compact`, `checkpoint`, `end`. Append-only +
per-event flush -- partial output survives Ctrl-C.

`--resume[-id]` reads the file and reconstructs the conversation.
`/compact` summarizes older history and writes a `compact` event
that `load_history` honors -- so you can keep a long-running session
without bloating context.

### Why the BM25 + embeddings hybrid

BM25 is bag-of-words; deterministic; sub-ms over thousands of
agents. It misses semantic matches ("find slow queries" doesn't
match "query performance analysis" via tokens).

Embeddings via Gemini's `text-embedding-004` close the gap. The
hybrid scoring is `alpha * normalized_bm25 + (1 - alpha) *
cosine_sim`, default alpha=0.4. The sidecar `.embeddings.json`
caches vectors per (name, mtime) so re-embedding only fires for
new or edited agents.

Enable via `settings.autobuild.semantic_search: true`. If the
embedding API fails (offline, quota), we silently fall back to
pure BM25 -- the feature MUST NOT break the base path.

---

## Section 6 -- 10 standalone runnable scenarios

Each is a single command. No setup beyond `pip install -r requirements.txt`
and the `.env` file.

### Scenario 1 -- Generate a script

```
python open_code.py "write a Python script word_count.py that takes
a filename arg and prints {word: count} sorted by count desc, then
run it on @README.md"
```

### Scenario 2 -- Audit security

```
python open_code.py --effort high --mode plan
"audit @tools.py for path traversal vulnerabilities. List concrete
attacks and the lines that protect against them."
```

### Scenario 3 -- Generate tests

```
python open_code.py "write 5 pytest-style assertions for the
function `tokenize` in @agent_search.py. Include edge cases
(empty input, all stopwords, unicode)."
```

### Scenario 4 -- Cross-file refactor

```
python open_code.py --mode plan
"@open_code.py @cli.py @repl.py - propose a refactor that extracts
all run_loop-aware UI calls into a single UIPlumbing class."
```

### Scenario 5 -- Bisect a bug

```
python open_code.py "I get TypeError: 'NoneType' object is not
iterable in repl.py:128. Read the file, find the cause, write the
fix to a new file fix.patch."
```

### Scenario 6 -- Documentation

```
python open_code.py --style explanatory
"Document @agent_search.py: one paragraph per public function,
explain WHY each design decision (BM25, mtime cache, etc)."
```

### Scenario 7 -- Migration script

```
python open_code.py --auto-checkpoint
"Migrate every @runs/2026-05-10*.md to the new format defined in
@templates/gap-log.md. Show me a diff first via plan mode."
```

### Scenario 8 -- Performance review

```
python open_code.py --effort xhigh --mode plan
"@agent_search.py: BM25 search is sub-ms for 1000 agents. What
breaks at 10K? at 100K? Suggest the cheapest mitigation per
breakpoint."
```

### Scenario 9 -- Pipe into another tool

```
python open_code.py --print "list every probe_*.py file with its
line count" | jq -r 'select(.type=="tool_result") | .result.stdout'
```

### Scenario 10 -- Use a custom skill

```
mkdir -p .open-code/skills/extract-todos
cat > .open-code/skills/extract-todos/SKILL.md << 'EOF'
---
name: extract-todos
description: Extract every TODO / FIXME / XXX comment in a file
allowed-tools: [read_file]
---
Find every TODO, FIXME, XXX in $ARGUMENTS. Output as a markdown
table with columns: line number | tag | comment | suggested action.
EOF

python open_code.py
> /skill extract-todos open_code.py
```

---

## Section 7 -- When things go wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `GEMINI_API_KEY is not set` | no `.env` or shell var | put key in `.env` or `export GEMINI_API_KEY=...` |
| `model returned no candidates` | invalid model name or content policy | check `--model` arg vs `--list-styles` |
| `refusing dangerous command` | shell denylist caught a risky pattern | add `--allow-dangerous` if intentional |
| `outside CWD` | write_file to a path outside the project | add `--allow-outside-cwd` if intentional |
| `permission denied` | permission rule said deny | check `.open-code/settings.json` |
| autobuilt agent doesn't work | LLM's spec was malformed (rare); a stale cache | `/autobuild revert <name>` or hand-edit |
| `(no sessions yet)` after a run | running in a different CWD than before | `--root` or check `~/.open-code/projects/` |
| empty rich output piped | `--plain` or `NO_COLOR=1` or stderr-not-TTY | works as designed |

Logs are in `~/.open-code/projects/<encoded-cwd>/<uuid>.jsonl`.
Every event is there. `tail -f` works.

---

## Section 8 -- Reference

- [README.md](README.md) -- feature catalog + comparison vs Claude Code / Aider
- [gap-log.md](gap-log.md) -- one line per shipped feature, oldest first; every brutal review's findings
- [runs/](runs/) -- one detailed run doc per release (`runs/2026-MM-DD-vX.Y.Z.md`)
- [tests/probe_*.py](tests/) -- 45+ hermetic probes, one per feature

Source files are kept small and readable:

| File | LOC | What |
|---|---|---|
| `open_code.py` | ~1700 | the agent loop |
| `cli.py` | ~550 | argparse + main() |
| `repl.py` | ~750 | interactive REPL |
| `agent_search.py` | ~290 | BM25 index |
| `agent_builder.py` | ~510 | architect meta-prompt + versioning + approval |
| `agent_embed.py` | ~250 | embedding rerank |
| `ui.py` | ~600 | rich + prompt_toolkit |
| `subagents.py` | ~280 | delegate tool |
| (others) | ... | hooks, plugins, mcp, checkpoints, skills, ... |

Pure ASCII; cross-platform; minimal deps (`google-genai`,
`python-dotenv`, `rich`, `prompt_toolkit`).
