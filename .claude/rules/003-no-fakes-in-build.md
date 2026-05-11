---
paths:
  - "src/**/*"
  - "lib/**/*"
  - "app/**/*"
  - "server/**/*"
  - "backend/**/*"
  - "frontend/**/*"
---

# No fakes in the build (source files)

You are editing build code. The persona-mvp-kit's bright line #3:
**NEVER mock what should be real**.

## What's allowed

Tests may stub at boundaries. The boundary is the interface to an
external system (LLM API, third-party service, file system, network).

## What's NOT allowed

- **Mocks behind the curtain in the build itself.** If `brief.py`
  returns canned output when its dependencies aren't available, the
  brief doesn't actually work -- but a casual reader thinks it does.
- **Silent fallbacks.** `try: real_call() except: return ""` hides
  the real failure mode. The persona will hit it; you'll be blamed.
- **"Demo mode" data that's hardcoded in the production code path.**
  Demo mode lives in test fixtures or a separate demo file.
- **Retry-without-diagnostic loops.** `for _ in range(3): try ...`
  hides intermittent failures from the user.

## Acceptable patterns

- **Boundary validation at the user/external interface.** Validate
  input from the user with Pydantic; let internal calls trust
  internal types.
- **Loud failure at boundary errors.** When the LLM API is down,
  surface that to the user with a clear diagnostic -- don't return
  empty results that look like "no data."
- **Test fixtures in `tests/`.** Mocks live with tests, not with
  build code.

## How to know you violated this rule

When you find yourself writing:

- `try: ... except Exception: return <default>` -- the exception is a
  signal you're suppressing
- `if result is None: result = {}` after a function that should never
  return None
- A function called `_fallback_*` or `_mock_*` in `src/`
- Comments like `# TODO: replace this stub before shipping`

Each of these means the persona will see broken behavior labeled as
"works." Refuse.

See `@methodology/03-BUILD.md` Sec. "Real systems, real data, real wiring."
See `@methodology/ANTI-PATTERNS.md` Sec. "Mocking what should be real."
