#!/bin/bash
# require-personas.sh
#
# PreToolUse hook for the persona-mvp-kit standard.
# Blocks Edit/Write on source files until personas.md and mvp-spec.md
# exist at the project root.
#
# Exits with:
#   0  -> allow (edit is on a non-source file, or personas exist)
#   2  -> deny (block the edit; Claude sees stderr and adjusts)
#
# Tweak the SOURCE_PATTERNS / DOC_EXCEPTIONS arrays to match your project's
# layout. Doc/config files that don't represent the "build" are allowed
# even when personas are missing so Claude can write personas.md itself.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Files Claude is allowed to write without personas (the kit's own
# scaffolding, plus persona/spec docs themselves).
DOC_EXCEPTIONS=(
  "personas.md"
  "mvp-spec.md"
  "gap-log.md"
  "runs/"
  ".claude/"
  "CLAUDE.md"
  "README.md"
  "INSTALL.md"
  "methodology/"
  "templates/"
  "examples/"
  "prompts/"
  "persona-mvp-kit/"
  ".gitignore"
  "package.json"
  "pyproject.toml"
  ".env.example"
)

# Source-file patterns we guard. Anything matching these REQUIRES personas.
# Keep in sync with enforce-verification.sh.
SOURCE_PATTERNS=(
  ".py"
  ".ts"
  ".tsx"
  ".js"
  ".jsx"
  ".rs"
  ".go"
  ".java"
  ".rb"
  ".c"
  ".cpp"
  ".h"
  ".sql"
  ".swift"
  ".kt"
  ".scala"
  ".vue"
  ".svelte"
  ".php"
  ".lua"
  ".pl"
  "Dockerfile"
)

# If we couldn't read a file path, allow -- not our concern.
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Skip kit-internal files.
for exception in "${DOC_EXCEPTIONS[@]}"; do
  if [[ "$FILE_PATH" == *"$exception"* ]]; then
    exit 0
  fi
done

# Is this a source file we should guard?
IS_SOURCE=0
for pattern in "${SOURCE_PATTERNS[@]}"; do
  if [[ "$FILE_PATH" == *"$pattern" ]]; then
    IS_SOURCE=1
    break
  fi
done

if [[ "$IS_SOURCE" -eq 0 ]]; then
  exit 0
fi

# At this point, Claude is trying to edit/write a source file. Verify
# the persona-mvp-kit prerequisites exist.
PERSONAS="$PROJECT_DIR/personas.md"
MVP_SPEC="$PROJECT_DIR/mvp-spec.md"

if [[ ! -s "$PERSONAS" ]]; then
  cat >&2 <<EOF
[persona-mvp-kit] BLOCKED: cannot edit "$FILE_PATH" because personas.md is missing or empty.

The kit's first bright line: NEVER write code before personas exist.
Take this action first:

  1. Read CLAUDE.md if you haven't already.
  2. Run /persona-extract to ask the user the extraction questions.
  3. Write personas.md from templates/persona.md.
  4. Get user confirmation.
  5. Then run /mvp-spec to draft mvp-spec.md.
  6. Then come back to writing this file.

If you have a STRONG reason to skip this step (e.g., user explicitly
told you to), ask the user to confirm and then create an empty
personas.md with "OVERRIDE: <reason>" as its content. The hook
allows the edit when personas.md exists with any content.
EOF
  exit 2
fi

if [[ ! -s "$MVP_SPEC" ]]; then
  cat >&2 <<EOF
[persona-mvp-kit] BLOCKED: cannot edit "$FILE_PATH" because mvp-spec.md is missing or empty.

personas.md exists but the MVP spec hasn't been drafted yet. Run
/mvp-spec to translate the primary persona's success criterion into
a concrete bar, then get user confirmation, then come back here.
EOF
  exit 2
fi

# All checks passed. Allow the edit.
exit 0
