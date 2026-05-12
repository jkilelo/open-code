# Run log -- venv refresh -- 2026-05-12

**Persona:** Jeff.
**Trigger:** User ran `python .\open_code.py "what's in this
directory"` from the activated `.venv` and the output stopped at
the session pointer with no `[iter 1]` line and no model response.

## Root cause

The repo's `.venv\` had drifted away from `requirements.txt`. Audit:

| Package | venv had | Required | Status |
|---|---|---|---|
| `google-genai` | 2.0.1 | >=2.1.0 | stale |
| `prompt_toolkit` | -- | >=3.0.0 | **missing** |
| `anthropic` | -- | optional | missing |
| `openai` | -- | optional | missing |
| `rich` | (ok) | >=14.0.0 | ok |
| `python-dotenv` | (ok) | >=1.0.0 | ok |

Why this looked like a hang at the session-pointer line: rich's
Live panel was probably (a) holding stdout in its redirect buffer
and (b) running with an older rich behavior we'd previously
patched in v0.27.x. Without `prompt_toolkit`, the UI fell back to
a degraded path. The model call may also have been slow on the
older google-genai 2.0.1; either way, the user got no visible
output and bailed.

## Fix

```powershell
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt
.venv\Scripts\python.exe -m pip install "anthropic>=0.101.0" "openai>=2.36.0"
```

After: `google-genai 2.2.0`, `prompt_toolkit 3.0.52`, `anthropic 0.101.0`,
`openai 2.36.0`. All three providers now installable into the venv
without re-running install when switching `settings.llm.provider`.

## Verification

One-shot from the refreshed venv:

```
> python .\open_code.py "in one sentence, what is open-code?" --no-mcp --no-stream

[loaded settings from .open-code/settings.local.json]
[repo-map: included 3 files]
  session: 518abac5-...
[iter 1] calling gemini-3.1-flash-lite-preview...
  [iters=1 in=3541t out=41t wall=1.34s]
Open-code is an autonomous terminal-based AI agent ...
```

REPL piped session:

```
> python .\open_code.py
Session 9cf675da-... in C:\Users\kleiy\OneDrive\Desktop\open-code
Model: gemini-3.1-flash-lite-preview

> what python files are in this directory? use list_dir
[iter 1] calling gemini-3.1-flash-lite-preview...
  -> list_dir({"path": "."})
  [OK] list_dir -> 50 entries
[iter 2] calling gemini-3.1-flash-lite-preview...
> [model listed all 21 .py files]
> /cost  -> iters=2 input_tok=8166 output_tok=213
> /exit  -> goodbye.
```

End-to-end: settings load -> banner -> Gemini call -> tool dispatch
-> followup turn -> /cost -> clean exit.

## Honest note

This isn't a code change -- the source has been correct all along
(the v0.30.5 README pins `google-genai>=2.1.0` and lists
`prompt_toolkit>=3.0.0`). The venv just lagged. Anyone setting up
open-code in a fresh clone via `pip install -r requirements.txt`
gets the right state automatically.

Documented this run for one reason: if YOU see this symptom again
in a few weeks, recognize it instantly as "venv drifted" and run
the upgrade one-liner rather than chasing it as a code bug.

## No commit needed for code

No source files changed. This run log is the only artifact.
The venv itself isn't tracked (gitignored at `.venv/`).
