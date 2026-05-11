#!/bin/bash
# remind-gap-log.sh
#
# PostToolUse hook for the persona-mvp-kit standard.
# After Claude successfully writes/edits a source file, emit a reminder
# to update gap-log.md. The reminder goes to stdout so Claude sees it in
# the tool result.
#
# Exits 0 always -- this hook informs, it doesn't block.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Don't remind on kit/doc file edits -- gap-log isn't relevant there.
case "$FILE_PATH" in
  *personas.md|*mvp-spec.md|*gap-log.md|*README*|*CLAUDE.md|*.gitignore|*runs/*)
    exit 0
    ;;
esac

# Source file edited -- gentle reminder.
echo "[persona-mvp-kit] After this edit, consider updating gap-log.md: which gap is now closer to [OK]? Use the persona's success criterion as the test." >&1

exit 0
