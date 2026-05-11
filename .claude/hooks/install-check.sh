#!/bin/bash
# install-check.sh
#
# Run once after installing the kit to verify dependencies + structure.
# Not invoked by Claude Code -- operator runs manually:
#
#   bash .claude/hooks/install-check.sh
#
# Prints pass/fail per check. Non-zero exit if any blocking check fails.

set -uo pipefail

# Resolve the project root: prefer CLAUDE_PROJECT_DIR (set by Claude Code at
# hook time), then infer from this script's location (the script lives at
# .claude/hooks/install-check.sh, so project root is two levels up), then
# fall back to pwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFERRED_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$INFERRED_ROOT}"
FAILS=0
WARNS=0

ok()    { echo "  [OK] $1"; }
fail()  { echo "  [X] $1"; FAILS=$((FAILS+1)); }
warn()  { echo "  ! $1"; WARNS=$((WARNS+1)); }

echo "=== persona-mvp-kit install check ==="
echo "  project: $PROJECT_DIR"
echo ""

# 1. Required external tools
echo "[1/5] External tools"
command -v bash > /dev/null && ok "bash" || fail "bash (REQUIRED for hooks)"
command -v jq > /dev/null && ok "jq" || fail "jq (REQUIRED -- 4 hooks parse stdin JSON; install: brew install jq / apt install jq / scoop install jq)"
command -v git > /dev/null && ok "git" || fail "git (REQUIRED -- kit commits per-gap)"
command -v find > /dev/null && ok "find" || fail "find"

echo ""

# 2. Kit structure
echo "[2/5] Kit structure"
for f in CLAUDE.md .claude/settings.json .claude-plugin/plugin.json; do
  test -f "$PROJECT_DIR/$f" && ok "$f" || fail "$f missing"
done
for d in .claude/skills .claude/agents .claude/hooks .claude/rules .claude/commands methodology templates; do
  test -d "$PROJECT_DIR/$d" && ok "$d/" || fail "$d/ missing"
done

echo ""

# 3. Hook scripts executable
echo "[3/5] Hook scripts executable"
for sh in "$PROJECT_DIR"/.claude/hooks/*.sh; do
  if [[ -x "$sh" ]]; then
    ok "$(basename "$sh")"
  else
    fail "$(basename "$sh") not executable (run: chmod +x .claude/hooks/*.sh)"
  fi
done

echo ""

# 4. settings.json + plugin.json + mcp.json.example valid JSON
echo "[4/5] JSON validity"
for j in "$PROJECT_DIR/.claude/settings.json" "$PROJECT_DIR/.claude-plugin/plugin.json"; do
  if jq empty "$j" 2>/dev/null; then
    ok "$(basename "$j") valid"
  else
    fail "$(basename "$j") INVALID JSON"
  fi
done
if [[ -f "$PROJECT_DIR/.mcp.json.example" ]]; then
  jq empty "$PROJECT_DIR/.mcp.json.example" 2>/dev/null && ok ".mcp.json.example valid" || warn ".mcp.json.example invalid JSON"
fi

echo ""

# 5. Project state (informational -- these don't exist until first /persona-extract)
echo "[5/5] Project state (informational)"
test -f "$PROJECT_DIR/personas.md"  && ok "personas.md present"  || warn "personas.md absent -- run /persona-extract"
test -f "$PROJECT_DIR/mvp-spec.md"   && ok "mvp-spec.md present"   || warn "mvp-spec.md absent -- run /mvp-spec after personas"
test -f "$PROJECT_DIR/gap-log.md"    && ok "gap-log.md present"    || warn "gap-log.md absent -- created when first gap is found"
test -d "$PROJECT_DIR/runs"          && ok "runs/ present"         || warn "runs/ absent -- created by /run-as-persona"

echo ""
echo "=== Summary ==="
if [[ "$FAILS" -eq 0 ]] && [[ "$WARNS" -eq 0 ]]; then
  echo "  [OK] All checks passed. Kit is ready."
  exit 0
elif [[ "$FAILS" -eq 0 ]]; then
  echo "  [OK] ${WARNS} warnings (project not yet bootstrapped -- that's expected on first install)."
  echo "  Kit infrastructure is ready. Run the kit to create personas.md / mvp-spec.md."
  exit 0
else
  echo "  [X] ${FAILS} blocking issues, ${WARNS} warnings."
  echo "  Fix the blocking issues before using the kit."
  exit 1
fi
