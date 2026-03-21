#!/bin/bash
# d4c-commit.sh — Helper for D4C conventional commits
# Usage: ./d4c-commit.sh <type> <scope> <message> <issue>
# Example: ./d4c-commit.sh feat ko-report "add hero numbers grid" VAL-11

TYPE=$1
SCOPE=$2
MESSAGE=$3
ISSUE=$4

if [ -z "$TYPE" ] || [ -z "$SCOPE" ] || [ -z "$MESSAGE" ] || [ -z "$ISSUE" ]; then
  echo "Usage: ./d4c-commit.sh <type> <scope> <message> <issue>"
  echo ""
  echo "Types: feat | fix | style | refactor | docs | chore | test"
  echo "Scopes: design-system | ko-report | demo | vaire | onboarding | portal | operator | swarm | api | infra"
  echo "Issue: VAL-XX"
  echo ""
  echo "Example: ./d4c-commit.sh feat ko-report 'add hero numbers grid' VAL-11"
  exit 1
fi

# Validate type
VALID_TYPES="feat fix style refactor docs chore test"
if ! echo "$VALID_TYPES" | grep -qw "$TYPE"; then
  echo "❌ Invalid type: $TYPE"
  echo "Valid types: $VALID_TYPES"
  exit 1
fi

# Validate issue format
if ! echo "$ISSUE" | grep -qE "^(VAL|NAR|GRO)-[0-9]+$"; then
  echo "❌ Invalid issue format: $ISSUE (expected VAL-XX, NAR-XX, or GRO-XX)"
  exit 1
fi

git commit -m "${TYPE}(${SCOPE}): ${MESSAGE}

Refs: ${ISSUE}"

echo "✅ Committed: ${TYPE}(${SCOPE}): ${MESSAGE} [${ISSUE}]"
