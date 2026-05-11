#!/bin/bash
# enforce-verification.sh
#
# Stop hook for the persona-mvp-kit standard.
# Blocks turn-end if the build appears done but the workflow hasn't
# been run as the persona (no recent runs/ file).
#
# Triggers a soft block: returns JSON with decision=block + reason,
# which tells Claude "you're not done yet -- run /run-as-persona."
#
# This is the deterministic enforcement of bright line #4:
# "Never claim 'done' without running the workflow yourself."
#
# Exits 0 always (the block is signaled via JSON, not exit code).
# Skips enforcement if personas haven't been set up yet -- that's
# what require-personas.sh is for.

set -euo pipefail

INPUT=$(cat)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Only act if the kit is set up (otherwise we're not in build mode yet).
if [[ ! -s "$PROJECT_DIR/personas.md" ]] || [[ ! -s "$PROJECT_DIR/mvp-spec.md" ]]; then
  exit 0
fi

# Did any source file get touched since the last runs/ file?
LATEST_RUN=""
if [[ -d "$PROJECT_DIR/runs" ]]; then
  LATEST_RUN=$(ls -1t "$PROJECT_DIR/runs"/*.md 2>/dev/null | head -1 || true)
fi

# Portable check: are there source files NEWER than the latest runs/ file?
# Search by file extension across the whole project tree (excluding kit-internal
# and vendored dirs), since many projects keep code at the root rather than
# under src/lib/app. Use POSIX `find -newer` which works on macOS BSD-find AND
# GNU find (unlike `find -printf` which is GNU-only).
#
# Extension list covers the languages the kit's PreToolUse hook guards. Add
# more here if your project uses something exotic (Kotlin, Swift, Vue, etc.).

# Build the find expression for source extensions.
FIND_EXPR=( -type f \( \
  -name "*.py" -o -name "*.ts" -o -name "*.tsx" \
  -o -name "*.js" -o -name "*.jsx" -o -name "*.rs" \
  -o -name "*.go" -o -name "*.java" -o -name "*.rb" \
  -o -name "*.c"  -o -name "*.cpp" -o -name "*.h" \
  -o -name "*.swift" -o -name "*.kt" -o -name "*.vue" -o -name "*.svelte" \
  -o -name "*.php" -o -name "*.lua" -o -name "Dockerfile" \
\) )

# Directories to EXCLUDE from the search.
EXCLUDES=( \
  -not -path "*/.git/*" \
  -not -path "*/.claude/*" \
  -not -path "*/.claude-plugin/*" \
  -not -path "*/node_modules/*" \
  -not -path "*/.venv/*" \
  -not -path "*/venv/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  -not -path "*/target/*" \
)

# If no runs/ file exists yet AND source files exist, that's the block case.
if [[ -z "$LATEST_RUN" ]]; then
  ANY_SRC=$(find "$PROJECT_DIR" "${FIND_EXPR[@]}" "${EXCLUDES[@]}" 2>/dev/null | head -1)
  if [[ -z "$ANY_SRC" ]]; then
    exit 0
  fi
  NEWER_COUNT=1
else
  NEWER_COUNT=$(find "$PROJECT_DIR" "${FIND_EXPR[@]}" "${EXCLUDES[@]}" \
    -newer "$LATEST_RUN" 2>/dev/null | wc -l | tr -d ' ')

  if [[ "$NEWER_COUNT" -eq 0 ]]; then
    exit 0
  fi
fi

# Source files have changed since the last (or only) run. Soft-block.
cat <<'EOF'
{
  "decision": "block",
  "reason": "The persona-mvp-kit standard requires running the workflow as the persona BEFORE claiming done. Source files have changed since the last runs/ file (or no run exists yet). Invoke /run-as-persona to execute mvp-spec.md Sec. 'How v0.1 is verified' against real systems and save the output to runs/YYYY-MM-DD-vX.Y.Z.md. Then claim done."
}
EOF
exit 0
