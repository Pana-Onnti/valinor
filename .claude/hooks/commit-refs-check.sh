#!/bin/bash
# Hook: Pre git commit — validate Refs: VAL-XX is present
# Trigger: PreToolUse on Bash when command contains "git commit"

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)

# Only fire on git commit commands
if [[ "$COMMAND" != *"git commit"* ]]; then
    exit 0
fi

# Skip if it's an amend or merge commit
if [[ "$COMMAND" == *"--amend"* ]] || [[ "$COMMAND" == *"merge"* ]]; then
    exit 0
fi

# Check if Refs: is present in the commit message
if [[ "$COMMAND" != *"Refs:"* ]]; then
    echo "BLOCKED: Commit message must include 'Refs: VAL-XX' (or GRO-XX/ANN-XX)."
    echo "This is required by project rules. Add the reference to the Linear issue."
    exit 2
fi
