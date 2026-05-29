#!/bin/bash
# Hook: Post git commit — remind to sync Linear issues
# Trigger: PostToolUse on Bash when command contains "git commit"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)
STDOUT=$(echo "$INPUT" | jq -r '.tool_result.stdout // ""' 2>/dev/null)

# Only fire on successful git commits
if [[ "$COMMAND" != *"git commit"* ]] || [[ "$STDOUT" == *"nothing to commit"* ]]; then
    exit 0
fi

# Extract VAL-XX / GRO-XX refs from the commit output or command
REFS=$(echo "$COMMAND" "$STDOUT" | grep -oE '(VAL|GRO|ANN)-[0-9]+' | sort -u | tr '\n' ', ' | sed 's/,$//')

if [[ -n "$REFS" ]]; then
    echo "SYNC REMINDER: Commit references $REFS. Remember to:"
    echo "  1. Comment on the issue(s) in Linear with what was done"
    echo "  2. Move to Done if acceptance criteria are met"
    echo "  3. Update active-plan.md if the sprint status changed"
fi
