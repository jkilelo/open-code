#!/bin/bash
# session-start-context.sh
#
# SessionStart hook (replaces the static echo). Reads current state of
# personas.md / mvp-spec.md / gap-log.md / runs/ and injects a
# concise status summary as additionalContext.
#
# Triggers Claude to enter the correct loop state (A/B/C/D/E) from
# the kit's persona-driven-mvp skill.
#
# Output is JSON on stdout per the hooks API:
#   { hookSpecificOutput: { hookEventName: "SessionStart",
#                           additionalContext: "<text>" } }
#
# Exits 0 always.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Build status fragments.
status=""
state="A"   # default: extraction mode

if [[ -s "$PROJECT_DIR/personas.md" ]]; then
  primary=$(grep -m1 '^### ' "$PROJECT_DIR/personas.md" 2>/dev/null | sed 's/^### //' || echo "?")
  status="${status}personas.md: [OK] (primary: ${primary})"$'\n'
  state="B"
else
  status="${status}personas.md: MISSING"$'\n'
fi

if [[ -s "$PROJECT_DIR/mvp-spec.md" ]]; then
  status="${status}mvp-spec.md: [OK]"$'\n'
  [[ "$state" == "B" ]] && state="C"
else
  status="${status}mvp-spec.md: MISSING"$'\n'
fi

if [[ -d "$PROJECT_DIR/runs" ]]; then
  run_count=$(ls -1 "$PROJECT_DIR/runs"/*.md 2>/dev/null | wc -l)
  if [[ "$run_count" -gt 0 ]]; then
    latest=$(ls -1t "$PROJECT_DIR/runs"/*.md | head -1 | xargs basename)
    status="${status}runs/: ${run_count} files (latest: ${latest})"$'\n'
    state="D"
  else
    status="${status}runs/: empty"$'\n'
  fi
else
  status="${status}runs/: not yet created"$'\n'
fi

if [[ -s "$PROJECT_DIR/gap-log.md" ]]; then
  # awk index() works portably across grep regex/locale quirks on Git Bash
  open_count=$(awk 'BEGIN{c=0} {if (index($0,"[FAIL]")>0) c++} END{print c}' "$PROJECT_DIR/gap-log.md")
  wip_count=$(awk 'BEGIN{c=0} {if (index($0,"[WARN]")>0) c++} END{print c}' "$PROJECT_DIR/gap-log.md")
  closed_count=$(awk 'BEGIN{c=0} {if (index($0,"[OK]")>0) c++} END{print c}' "$PROJECT_DIR/gap-log.md")
  status="${status}gap-log.md: ${open_count} [FAIL] open, ${wip_count} [WARN] in-progress, ${closed_count} [OK] closed"$'\n'
fi

# Map state to next action.
case "$state" in
  A) next_action="Run /persona-extract -- the kit's first bright line is no code before personas." ;;
  B) next_action="Run /mvp-spec -- translate the primary persona's success criterion into a concrete bar." ;;
  C) next_action="Build the smallest end-to-end slice per mvp-spec.md, then /run-as-persona." ;;
  D) next_action="Read the latest runs/ file. If green (met), invoke /brutal-honest-review for the verdict. If yellow/red, /trace-root-cause." ;;
  E) next_action="Confirm with user before tagging v0.X.Y, then ship." ;;
esac

# Emit JSON for additionalContext.
context="persona-mvp-kit project state:
${status}
Next action: ${next_action}

Read CLAUDE.md, personas.md, mvp-spec.md, gap-log.md before proceeding."

# JSON-escape via jq (-Rs reads raw input as a single string, emits a
# JSON-encoded string literal). Avoids the Python dependency the kit
# doesn't otherwise require.
escaped=$(printf '%s' "$context" | jq -Rs '.')

cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": ${escaped}
  }
}
EOF
exit 0
