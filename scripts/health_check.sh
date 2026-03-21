#!/usr/bin/env bash
# health_check.sh — Valinor SaaS system health check
# Runs four checks and prints a summary with pass/fail counts.

set -euo pipefail

FAILURES=0
CHECKS=0

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
RESET='\033[0m'

pass() { echo -e "  ${GREEN}✓${RESET} $1"; }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAILURES=$(( FAILURES + 1 )); }
header() { echo -e "\n${YELLOW}==> $1${RESET}"; }

# ── 1. Docker containers ────────────────────────────────────────────────────
header "Docker containers"
CHECKS=$(( CHECKS + 1 ))
if docker compose ps 2>&1; then
    pass "docker compose ps succeeded"
else
    fail "docker compose ps failed"
fi

# ── 2. Health endpoint ──────────────────────────────────────────────────────
header "API health endpoint  (http://localhost:8000/health)"
CHECKS=$(( CHECKS + 1 ))
HEALTH_RESPONSE=$(curl -sf http://localhost:8000/health 2>&1) || true
if [ -n "$HEALTH_RESPONSE" ]; then
    echo "$HEALTH_RESPONSE" | python3 -m json.tool && pass "Health endpoint OK" || fail "Health endpoint returned invalid JSON"
else
    fail "Health endpoint unreachable"
fi

# ── 3. System status endpoint ───────────────────────────────────────────────
header "API system status   (http://localhost:8000/api/system/status)"
CHECKS=$(( CHECKS + 1 ))
STATUS_RESPONSE=$(curl -sf http://localhost:8000/api/system/status 2>&1) || true
if [ -n "$STATUS_RESPONSE" ]; then
    echo "$STATUS_RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('Version:', d.get('version'))
print('Features:', list(d.get('features', {}).get('data_quality', {}).keys()))
" && pass "System status endpoint OK" || fail "System status endpoint returned unexpected data"
else
    fail "System status endpoint unreachable"
fi

# ── 4. Test suite ───────────────────────────────────────────────────────────
header "Test suite  (pytest tests/)"
CHECKS=$(( CHECKS + 1 ))
if python3 -m pytest tests/ -q; then
    pass "All tests passed"
else
    fail "One or more tests failed"
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "────────────────────────────────────────"
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}✓ All ${CHECKS} checks passed${RESET}"
    exit 0
else
    echo -e "${RED}✗ ${FAILURES} of ${CHECKS} checks failed${RESET}"
    exit 1
fi
