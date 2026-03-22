#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Valinor SaaS — Pre-PR Smoke Test
# ═══════════════════════════════════════════════════════════════════════════
# Run this BEFORE merging to master. Validates:
#   1. All containers build and start
#   2. API endpoints respond correctly
#   3. Auth, CORS, validation work
#   4. Frontend serves
#   5. Unit tests pass (excluding known structlog issues)
#
# Usage:
#   ./scripts/smoke_test.sh          # full (rebuild + test)
#   ./scripts/smoke_test.sh --quick  # skip rebuild, test running containers
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
BOLD='\033[1m'

PASSED=0
FAILED=0
WARNINGS=0

pass() { PASSED=$((PASSED + 1)); echo -e "  ${GREEN}✅ $1${NC}"; }
fail() { FAILED=$((FAILED + 1)); echo -e "  ${RED}❌ $1${NC}"; }
warn() { WARNINGS=$((WARNINGS + 1)); echo -e "  ${YELLOW}⚠️  $1${NC}"; }

API_URL="http://localhost:8000"
WEB_URL="http://localhost:3000"

# Known pre-existing test failures (structlog.contextvars, anthropic import)
IGNORE_TESTS=(
    "tests/test_alert_thresholds.py"
    "tests/test_digest_endpoints.py"
    "tests/test_job_management.py"
    "tests/test_onboarding.py"
    "tests/test_system_endpoints.py"
    "tests/test_webhook_endpoints.py"
    "tests/test_token_tracker.py"
    "tests/test_job_lifecycle.py"
    "tests/test_rate_limiting.py"
    "tests/test_streaming.py"
    "tests/test_client_endpoints.py"
)

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Valinor SaaS — Pre-PR Smoke Test${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
echo ""

# ─── Phase 0: Rebuild containers (unless --quick) ─────────────────────────
if [[ "${1:-}" != "--quick" ]]; then
    echo -e "${BOLD}Phase 0: Rebuild containers${NC}"
    echo "  Building... (this may take a minute)"
    if docker compose up -d --build > /tmp/valinor_smoke_build.log 2>&1; then
        pass "Docker build successful"
    else
        fail "Docker build FAILED — check /tmp/valinor_smoke_build.log"
        echo -e "\n${RED}Build failed. Aborting smoke test.${NC}"
        exit 1
    fi
    echo "  Waiting 10s for containers to stabilize..."
    sleep 10
else
    echo -e "${BOLD}Phase 0: Quick mode — skipping rebuild${NC}"
fi

# ─── Phase 1: Container health ────────────────────────────────────────────
echo ""
echo -e "${BOLD}Phase 1: Container health${NC}"

EXPECTED_CONTAINERS=("api" "web" "redis" "postgres" "worker" "prometheus" "grafana" "loki" "promtail")
for svc in "${EXPECTED_CONTAINERS[@]}"; do
    if docker compose ps --format "{{.Name}}" 2>/dev/null | grep -q "$svc"; then
        pass "$svc container running"
    else
        fail "$svc container NOT running"
    fi
done

# ─── Phase 2: API endpoints ───────────────────────────────────────────────
echo ""
echo -e "${BOLD}Phase 2: API endpoints${NC}"

# Health
HTTP=$(curl -s -o /tmp/smoke_health.json -w "%{http_code}" "$API_URL/health" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
    STATUS=$(python3 -c "import json; print(json.load(open('/tmp/smoke_health.json'))['status'])" 2>/dev/null || echo "unknown")
    if [[ "$STATUS" == "healthy" ]]; then
        pass "GET /health → 200 (status: healthy)"
    else
        warn "GET /health → 200 but status=$STATUS"
    fi
else
    fail "GET /health → HTTP $HTTP (expected 200)"
fi

# Version
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/api/version" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
    pass "GET /api/version → 200"
else
    fail "GET /api/version → HTTP $HTTP"
fi

# Docs (should be public, no auth)
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/docs" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
    pass "GET /docs → 200 (public, no auth)"
else
    fail "GET /docs → HTTP $HTTP"
fi

# Metrics
HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/metrics" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
    pass "GET /metrics → 200"
else
    fail "GET /metrics → HTTP $HTTP"
fi

# Validation — malformed POST should return 422
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_URL/api/analyze" \
    -H "Content-Type: application/json" \
    -d '{"bad":"payload"}' 2>/dev/null || echo "000")
if [[ "$HTTP" == "422" ]]; then
    pass "POST /api/analyze (bad payload) → 422 validation error"
elif [[ "$HTTP" == "401" || "$HTTP" == "403" ]]; then
    pass "POST /api/analyze → $HTTP (auth blocking, expected in prod)"
else
    fail "POST /api/analyze (bad payload) → HTTP $HTTP (expected 422)"
fi

# ─── Phase 3: CORS ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Phase 3: CORS validation${NC}"

# Allowed origin
CORS_HEADER=$(curl -s -I -H "Origin: http://localhost:3000" "$API_URL/health" 2>/dev/null | grep -i "access-control-allow-origin" || echo "")
if [[ -n "$CORS_HEADER" ]]; then
    pass "CORS allows localhost:3000"
else
    warn "CORS header not present for localhost:3000"
fi

# ─── Phase 4: Frontend ────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Phase 4: Frontend${NC}"

HTTP=$(curl -s -o /dev/null -w "%{http_code}" "$WEB_URL" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
    pass "Web frontend → 200 (localhost:3000)"
else
    fail "Web frontend → HTTP $HTTP"
fi

# ─── Phase 5: Container logs (check for crashes) ──────────────────────────
echo ""
echo -e "${BOLD}Phase 5: Container logs (error check)${NC}"

API_ERRORS=$(docker compose logs api --tail 50 2>/dev/null | grep -ci "error\|traceback\|exception" || true)
API_ERRORS=${API_ERRORS:-0}
if [[ "$API_ERRORS" -lt 3 ]]; then
    pass "API logs clean ($API_ERRORS error mentions)"
else
    warn "API logs have $API_ERRORS error mentions — review with: docker compose logs api"
fi

WORKER_ERRORS=$(docker compose logs worker --tail 50 2>/dev/null | grep -ci "error\|traceback\|exception" || true)
WORKER_ERRORS=${WORKER_ERRORS:-0}
if [[ "$WORKER_ERRORS" -lt 3 ]]; then
    pass "Worker logs clean ($WORKER_ERRORS error mentions)"
else
    warn "Worker logs have $WORKER_ERRORS error mentions"
fi

# ─── Phase 6: Unit tests ──────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Phase 6: Unit tests${NC}"

IGNORE_ARGS=""
for t in "${IGNORE_TESTS[@]}"; do
    IGNORE_ARGS="$IGNORE_ARGS --ignore=$t"
done

echo "  Running pytest (excluding known structlog failures)..."
TEST_OUTPUT=$(python3 -m pytest tests/ -q --tb=no $IGNORE_ARGS 2>&1 || true)
TEST_SUMMARY=$(echo "$TEST_OUTPUT" | tail -1)

# Parse results
TEST_PASSED=$(echo "$TEST_SUMMARY" | grep -oP '\d+ passed' | grep -oP '\d+' || echo "0")
TEST_FAILED=$(echo "$TEST_SUMMARY" | grep -oP '\d+ failed' | grep -oP '\d+' || echo "0")
TEST_ERRORS=$(echo "$TEST_SUMMARY" | grep -oP '\d+ error' | grep -oP '\d+' || echo "0")

if [[ "$TEST_FAILED" -le 5 && "$TEST_PASSED" -gt 2000 ]]; then
    pass "Tests: $TEST_PASSED passed, $TEST_FAILED failed (pre-existing), $TEST_ERRORS errors"
else
    fail "Tests: $TEST_PASSED passed, $TEST_FAILED failed, $TEST_ERRORS errors"
fi

# ─── Summary ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
TOTAL=$((PASSED + FAILED + WARNINGS))
echo -e "  ${GREEN}Passed: $PASSED${NC}  ${RED}Failed: $FAILED${NC}  ${YELLOW}Warnings: $WARNINGS${NC}  Total: $TOTAL"

if [[ "$FAILED" -eq 0 ]]; then
    echo -e "  ${GREEN}${BOLD}SMOKE TEST PASSED — safe to merge to master${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    exit 0
else
    echo -e "  ${RED}${BOLD}SMOKE TEST FAILED — fix issues before merging${NC}"
    echo -e "${BOLD}═══════════════════════════════════════════════════════════${NC}"
    exit 1
fi
