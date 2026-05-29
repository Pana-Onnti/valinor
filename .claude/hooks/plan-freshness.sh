#!/bin/bash
# Hook: Check if active-plan.md is stale (>3 days since last update)
# Trigger: PostToolUse on Bash when running git status or git log

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)

# Only fire on git status/log commands (session start indicators)
if [[ "$COMMAND" != *"git status"* ]] && [[ "$COMMAND" != *"git log"* ]]; then
    exit 0
fi

PLAN="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}/.claude/plans/active-plan.md"
if [[ ! -f "$PLAN" ]]; then
    echo "WARNING: No active-plan.md found. Run /start-session to create one."
    exit 0
fi

# Check last modification time
PLAN_MOD=$(stat -c %Y "$PLAN" 2>/dev/null || stat -f %m "$PLAN" 2>/dev/null)
NOW=$(date +%s)
DIFF=$(( (NOW - PLAN_MOD) / 86400 ))

if [[ $DIFF -ge 3 ]]; then
    echo "WARNING: active-plan.md is ${DIFF} days old. Run /start-session to refresh it."
fi
