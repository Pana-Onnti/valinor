#!/usr/bin/env bash
# =============================================================================
# Valinor SaaS — Cloudflare Workers deployment helper
# Usage:
#   ./deploy/deploy-cloudflare.sh [production|staging|dev]
#
# Prerequisites:
#   - wrangler CLI installed  (npm i -g wrangler)
#   - CLOUDFLARE_API_TOKEN exported in the shell (or stored via `wrangler login`)
#   - BACKEND_URL stored as a wrangler secret for the target environment
#       wrangler secret put BACKEND_URL --env production
#       wrangler secret put BACKEND_URL --env staging
# =============================================================================

set -euo pipefail

WORKER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/cloudflare" && pwd)"
ENVIRONMENT="${1:-production}"

# ---------------------------------------------------------------------------
# Validate environment argument
# ---------------------------------------------------------------------------
case "${ENVIRONMENT}" in
  production|staging|dev) ;;
  *)
    echo "ERROR: Unknown environment '${ENVIRONMENT}'. Use: production | staging | dev" >&2
    exit 1
    ;;
esac

echo "==> Deploying Valinor Cloudflare Worker — environment: ${ENVIRONMENT}"

# ---------------------------------------------------------------------------
# Check wrangler is available
# ---------------------------------------------------------------------------
if ! command -v wrangler &>/dev/null; then
  echo "ERROR: wrangler CLI not found. Install it with:" >&2
  echo "  npm install -g wrangler" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Install worker dependencies (if package.json exists)
# ---------------------------------------------------------------------------
if [[ -f "${WORKER_DIR}/package.json" ]]; then
  echo "==> Installing worker dependencies..."
  (cd "${WORKER_DIR}" && npm ci --silent)
fi

# ---------------------------------------------------------------------------
# Type-check (if tsconfig.json exists)
# ---------------------------------------------------------------------------
if [[ -f "${WORKER_DIR}/tsconfig.json" ]]; then
  echo "==> Running TypeScript type-check..."
  (cd "${WORKER_DIR}" && npx tsc --noEmit)
fi

# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------
echo "==> Running wrangler deploy..."

if [[ "${ENVIRONMENT}" == "dev" ]]; then
  echo "NOTE: 'dev' environment starts a local miniflare instance (no remote deploy)."
  (cd "${WORKER_DIR}" && wrangler dev --env dev)
else
  (cd "${WORKER_DIR}" && wrangler deploy --env "${ENVIRONMENT}")
  echo "==> Deploy complete for environment: ${ENVIRONMENT}"

  # Print worker URL
  if [[ "${ENVIRONMENT}" == "production" ]]; then
    echo "==> Worker URL: https://api.valinor.app"
  else
    echo "==> Worker URL: https://api-staging.valinor.app"
  fi
fi
