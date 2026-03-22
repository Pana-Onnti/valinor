#!/usr/bin/env bash
# =============================================================================
# Delta 4C — VAL-23: Infraestructura CLI Setup
# =============================================================================
# Ejecutar desde el root del repo valinor.
# Prerequisitos: Node.js (para Railway CLI), git
#
# Variables requeridas (exportar antes de correr):
#   export ANTHROPIC_API_KEY=sk-ant-...
#   export RAILWAY_TOKEN=...         # crear en railway.app/account/tokens
# =============================================================================

set -euo pipefail

# ── Colores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}━━━ $1 ━━━${NC}\n"; }

# ── Variables — configurar via env, nunca hardcodear secrets ─────────────────
RAILWAY_PROJECT_ID="b78babfc-1b70-45f5-a866-eb23d08e04ac"
RAILWAY_SERVICE_ID="28adc6de-bca8-4837-a3e6-cfa6b9bc25c2"
SENTRY_DSN="${SENTRY_DSN:-https://15c4503c94501c490facc831f3f36917@o4511084080594944.ingest.us.sentry.io/4511084086296576}"
GITHUB_REPO="Pana-Onnti/valinor"

ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
RAILWAY_TOKEN="${RAILWAY_TOKEN:-}"

# =============================================================================
# FASE 0: Instalar CLIs
# =============================================================================
step "FASE 0: Instalando CLIs"

if ! command -v railway &> /dev/null; then
    warn "Instalando Railway CLI..."
    npm install -g @railway/cli || err "No se pudo instalar Railway CLI"
    log "Railway CLI instalado"
else
    log "Railway CLI ya instalado ($(railway --version))"
fi

if ! command -v gh &> /dev/null; then
    warn "Instalando GitHub CLI..."
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        out=$(mktemp)
        trap 'rm -f "$out"' EXIT
        (type -p wget >/dev/null || (sudo apt update && sudo apt-get install wget -y)) \
            && sudo mkdir -p -m 755 /etc/apt/keyrings \
            && wget -nv -O "$out" https://cli.github.com/packages/githubcli-archive-keyring.gpg \
            && cat "$out" | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
            && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
            && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
                | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
            && sudo apt update \
            && sudo apt install gh -y || err "No se pudo instalar GitHub CLI"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install gh || err "No se pudo instalar GitHub CLI"
    else
        err "OS no soportado. Instalá gh manualmente: https://cli.github.com/"
    fi
    log "GitHub CLI instalado"
else
    log "GitHub CLI ya instalado ($(gh --version | head -1))"
fi

# =============================================================================
# FASE 1: Login a servicios
# =============================================================================
step "FASE 1: Autenticación"

if ! gh auth status &> /dev/null; then
    warn "Necesitás loguearte a GitHub..."
    gh auth login || err "GitHub auth falló"
else
    log "GitHub: ya autenticado"
fi

if ! railway whoami &> /dev/null 2>&1; then
    warn "Necesitás loguearte a Railway..."
    railway login || err "Railway login falló"
else
    log "Railway: ya autenticado"
fi

# =============================================================================
# FASE 2: Railway — Configurar proyecto
# =============================================================================
step "FASE 2: Railway — Configurar proyecto de producción"

railway link --project "$RAILWAY_PROJECT_ID" || err "No se pudo linkear el proyecto Railway"
log "Proyecto Railway linkeado"

railway service link "$RAILWAY_SERVICE_ID" 2>/dev/null || railway service link API || err "No se pudo linkear el servicio API"
log "Servicio API linkeado"

# Databases (idempotente si ya existen)
read -p "¿Agregar PostgreSQL managed? (y/n): " ADD_PG
if [[ "$ADD_PG" == "y" ]]; then
    railway add --database postgres && log "PostgreSQL agregado" || warn "PostgreSQL ya existe o falló"
fi

read -p "¿Agregar Redis managed? (y/n): " ADD_REDIS
if [[ "$ADD_REDIS" == "y" ]]; then
    railway add --database redis && log "Redis agregado" || warn "Redis ya existe o falló"
fi

# Variables
step "Railway — Variables de entorno (production)"

railway variable set APP_ENV=production && log "APP_ENV=production"
printf '%s' "$SENTRY_DSN" | railway variable set --stdin SENTRY_DSN && log "SENTRY_DSN configurado"
railway variable set SENTRY_TRACES_SAMPLE_RATE=0.1 && log "SENTRY_TRACES_SAMPLE_RATE=0.1"

if [[ -n "$ANTHROPIC_API_KEY" ]]; then
    printf '%s' "$ANTHROPIC_API_KEY" | railway variable set --stdin ANTHROPIC_API_KEY && log "ANTHROPIC_API_KEY configurado"
else
    warn "ANTHROPIC_API_KEY no seteada. Exportala antes de correr o seteala manualmente."
fi

# Custom domain
read -p "¿Configurar api.delta4c.com como custom domain? (y/n): " ADD_DOMAIN
if [[ "$ADD_DOMAIN" == "y" ]]; then
    railway domain api.delta4c.com && log "Dominio api.delta4c.com configurado. Agregá el CNAME en tu DNS." \
        || warn "No se pudo configurar el dominio"
fi

# Railway token para CI/CD
step "Railway — Token para CI/CD"
echo "  Creá el token en: https://railway.app/account/tokens"
echo "  Luego exportalo: export RAILWAY_TOKEN=tu-token"
echo ""
if [[ -z "$RAILWAY_TOKEN" ]]; then
    warn "RAILWAY_TOKEN no seteado. Setealo como variable de entorno y volvé a correr el step 3."
fi

# =============================================================================
# FASE 3: GitHub — Secrets + Configuración
# =============================================================================
step "FASE 3: GitHub — Configuración del repo"

printf '%s' "$SENTRY_DSN" | gh secret set SENTRY_DSN --repo "$GITHUB_REPO" && log "Secret SENTRY_DSN ok"

if [[ -n "$RAILWAY_TOKEN" ]]; then
    printf '%s' "$RAILWAY_TOKEN" | gh secret set RAILWAY_TOKEN --repo "$GITHUB_REPO" && log "Secret RAILWAY_TOKEN ok"
else
    warn "RAILWAY_TOKEN no disponible — crealo en railway.app/account/tokens y agregalo manualmente"
fi

if [[ -n "$ANTHROPIC_API_KEY" ]]; then
    printf '%s' "$ANTHROPIC_API_KEY" | gh secret set ANTHROPIC_API_KEY --repo "$GITHUB_REPO" && log "Secret ANTHROPIC_API_KEY ok"
else
    warn "ANTHROPIC_API_KEY no disponible — seteala manualmente"
fi

# GitHub Actions
gh api \
    --method PUT \
    -H "Accept: application/vnd.github+json" \
    "/repos/$GITHUB_REPO/actions/permissions" \
    --field "enabled=true" \
    --field 'allowed_actions=all' \
    2>/dev/null && log "GitHub Actions habilitado" || warn "No se pudo habilitar Actions — verificá permisos"

# Branch protection
DEFAULT_BRANCH=$(gh api "/repos/$GITHUB_REPO" --jq '.default_branch' 2>/dev/null || echo "main")  # VAL-51
read -p "¿Configurar branch protection en $DEFAULT_BRANCH? (y/n): " ADD_PROTECTION
if [[ "$ADD_PROTECTION" == "y" ]]; then
    cat <<JSON | gh api \
        --method PUT \
        -H "Accept: application/vnd.github+json" \
        "/repos/$GITHUB_REPO/branches/$DEFAULT_BRANCH/protection" \
        --input - \
        2>/dev/null && log "Branch protection configurado en $DEFAULT_BRANCH" \
        || warn "Branch protection falló — puede que el branch no tenga commits aún"
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "typecheck", "test", "build"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1
  },
  "restrictions": null
}
JSON
fi

# =============================================================================
# RESUMEN
# =============================================================================
step "RESUMEN"

echo "┌─────────────────────────────────────────────────────┐"
echo "│  Delta 4C — Infraestructura VAL-23                  │"
echo "├─────────────────────────────────────────────────────┤"
echo "│  Railway (proyecto: fearless-enthusiasm)            │"
echo "│  ├─ Servicio: API linkeado                          │"
echo "│  ├─ APP_ENV=production           ✓                  │"
echo "│  ├─ SENTRY_DSN                   ✓                  │"
echo "│  └─ SENTRY_TRACES_SAMPLE_RATE    ✓                  │"
echo "│                                                     │"
echo "│  GitHub Secrets ($GITHUB_REPO)                      │"
echo "│  ├─ SENTRY_DSN                   ✓                  │"

if [[ -n "$RAILWAY_TOKEN" ]]; then
echo "│  ├─ RAILWAY_TOKEN                ✓                  │"
else
echo "│  ├─ RAILWAY_TOKEN                ⏳ pendiente       │"
fi

if [[ -n "$ANTHROPIC_API_KEY" ]]; then
echo "│  └─ ANTHROPIC_API_KEY            ✓                  │"
else
echo "│  └─ ANTHROPIC_API_KEY            ⏳ pendiente       │"
fi

echo "│                                                     │"
echo "│  Pendiente manual:                                  │"
echo "│  ├─ Railway token: railway.app/account/tokens       │"
echo "│  ├─ DNS: CNAME para api.delta4c.com                 │"
echo "│  ├─ Invitar Pedro a Railway + Sentry                │"
echo "│  └─ Slack: workspace + canales (puede esperar)      │"
echo "│                                                     │"
echo "└─────────────────────────────────────────────────────┘"

log "Script terminado. Revisá los items marcados ⏳."
