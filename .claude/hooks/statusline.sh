#!/bin/bash
# statusline.sh
#
# Custom status line for the persona-mvp-kit standard.
# Receives JSON session info on stdin; prints a single line summary
# of the kit's enforcement state to stdout.
#
# What it shows:
#   [persona-mvp-kit]  P? S? R?  gap-log: N🔴 K🟢  | branch: main
#
# - P? : ✓ if personas.md exists; ✗ otherwise
# - S? : ✓ if mvp-spec.md exists; ✗ otherwise
# - R? : N (count of runs/ files) or "—" if no runs/
# - gap-log: count of 🔴 open and 🟢 closed
# - branch: current git branch
#
# Color codes used minimally; status line should be fast and visible.

set -euo pipefail

INPUT=$(cat)
PROJECT_DIR=$(echo "$INPUT" | jq -r '.cwd // empty')
[[ -z "$PROJECT_DIR" ]] && PROJECT_DIR="$(pwd)"

# Persona/spec presence (one char each).
if [[ -s "$PROJECT_DIR/personas.md" ]]; then
  P="✓"
else
  P="✗"
fi

if [[ -s "$PROJECT_DIR/mvp-spec.md" ]]; then
  S="✓"
else
  S="✗"
fi

# Runs count.
if [[ -d "$PROJECT_DIR/runs" ]]; then
  R=$(ls -1 "$PROJECT_DIR/runs"/*.md 2>/dev/null | wc -l | tr -d ' ')
else
  R="—"
fi

# Gap-log counts.
# We use `awk index()` for byte-level substring search instead of `grep`
# because grep's regex engine fails to match multi-byte UTF-8 emoji on
# some platforms (notably Git Bash / msys2 on Windows). index() is
# byte-substring and works everywhere.
# Counts 🔴 OPEN, 🟡 IN-PROGRESS, 🟢 CLOSED. Omits 🟡 from the display when zero.
if [[ -s "$PROJECT_DIR/gap-log.md" ]]; then
  RED=$(awk 'BEGIN{c=0} {if (index($0,"🔴")>0) c++} END{print c}' "$PROJECT_DIR/gap-log.md")
  YELLOW=$(awk 'BEGIN{c=0} {if (index($0,"🟡")>0) c++} END{print c}' "$PROJECT_DIR/gap-log.md")
  GREEN=$(awk 'BEGIN{c=0} {if (index($0,"🟢")>0) c++} END{print c}' "$PROJECT_DIR/gap-log.md")
  if [[ "$YELLOW" -gt 0 ]]; then
    GAP="${RED}🔴 ${YELLOW}🟡 ${GREEN}🟢"
  else
    GAP="${RED}🔴 ${GREEN}🟢"
  fi
else
  GAP="—"
fi

# Git branch.
# `git rev-parse --abbrev-ref HEAD` in a no-commit repo prints "HEAD"
# to stdout AND exits 128 — the OR fallback then ALSO prints, producing
# garbled output. `git symbolic-ref --short HEAD` exits cleanly with
# the branch name even before the first commit.
BRANCH=$(cd "$PROJECT_DIR" 2>/dev/null && git symbolic-ref --short HEAD 2>/dev/null)
[[ -z "$BRANCH" ]] && BRANCH="—"

# Context-fill percent (if hook input includes it).
CTX_PCT=$(echo "$INPUT" | jq -r '.context_used_percent // empty' 2>/dev/null || echo "")
CTX=""
[[ -n "$CTX_PCT" ]] && CTX=" | ctx: ${CTX_PCT}%"

# Compose. Keep it ONE line.
echo "[persona-mvp-kit] P:${P} S:${S} R:${R} | gap: ${GAP} | ${BRANCH}${CTX}"
