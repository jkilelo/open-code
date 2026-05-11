#!/bin/bash
# check-prompt-bypass.sh
#
# UserPromptSubmit hook for the persona-mvp-kit standard.
# When the user prompt contains language suggesting they want to bypass
# the kit's persona-first discipline, inject context reminding Claude
# of the standard.
#
# Does NOT block the prompt — adds context. The kit prefers persuasion
# over censorship; the user can still override explicitly, but Claude
# will at least pause to confirm.
#
# Exits 0 always.

set -euo pipefail

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // ""' | tr '[:upper:]' '[:lower:]')

# Patterns that suggest bypass intent. Lower-case; checked against the
# lower-cased prompt with `grep -E` (POSIX extended regex — uses `(...)`
# not `(?:...)`). False negatives are expected — language is flexible.
# False positives are tolerable because the hook only ADDS context (doesn't
# block), and Claude is told to confirm intent before complying.
BYPASS_PATTERNS=(
  "skip personas?"
  "no personas?"
  "without personas?"
  "just code"
  "just build"
  "just make it"
  "just write (the )?code"
  "just go ahead"
  "just do it"
  "just hack it"
  "just wing it"
  "go ahead and (code|write|build|make)"
  "(can you|could you|please) just"
  "don't ask"
  "don't bother"
  "skip the (questions|spec|mvp|verification|testing)"
  "no (mvp-spec|spec needed)"
  "ship it (now|already)"
  "claim done"
  "mark as done"
  "say it's done"
  "tag (it|the) (v|version)"
  "we (don't|do not) need (personas|spec|tests|verification)"
  "forget (the )?(personas|spec)"
  "we'?ll do (personas|spec|tests) later"
  "quick (and dirty|prototype)"
  "no need for (personas|spec|verification)"
  "hack (it )?together"
  "throw together"
)

MATCHED=""
for pattern in "${BYPASS_PATTERNS[@]}"; do
  if echo "$PROMPT" | grep -qE "$pattern"; then
    MATCHED="$pattern"
    break
  fi
done

if [[ -z "$MATCHED" ]]; then
  exit 0
fi

# Build context reminder.
cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "The user's prompt contains a pattern ('${MATCHED}') that may indicate they want to bypass the persona-mvp-kit standard. BEFORE complying, explicitly tell the user which bright line they're asking you to skip (see CLAUDE.md § 'Bright lines'). Then ask for confirmation. Possible bright lines being skipped:\n- #1 NEVER write code before personas exist\n- #2 One persona, one workflow, one slice\n- #3 NEVER mock what should be real\n- #4 NEVER claim done without running the workflow yourself\n- #5 NEVER paper over failures (trace 3-deep)\n- #6 NEVER add features beyond mvp-spec.md without re-confirming personas\n- #7 NEVER introduce a dependency without persona justification\n- #8 One commit per gap, persona named\n\nIf the user is genuinely doing something the kit allows (e.g., bug fix to an already-shipped slice), don't be reflexive — confirm the intent and proceed. If they're truly skipping, ask for explicit override confirmation before doing the thing."
  }
}
EOF
exit 0
