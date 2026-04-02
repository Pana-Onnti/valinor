# Sprint: CI/CD Remaining (VAL-18 gaps)

**Estado**: Phase 1 (Foundation) y Phase 3 (Observability) ya HECHAS.
**Lo que falta**: Staging deploy + auto-migrations + minor hardening.
**Esfuerzo estimado**: 3-4 días

## Ya completado (no tocar)

- ✅ GitHub Actions: tests.yml (flake8 + pytest matrix + coverage 60%)
- ✅ GitHub Actions: docker-build.yml (builds API + Worker, no push)
- ✅ GitHub Actions: deploy.yml (Railway API + Vercel frontend, master-only)
- ✅ Prometheus metrics (7 tipos: jobs, cost, DQ, HTTP, etc.)
- ✅ Loki log aggregation (30d retention)
- ✅ Grafana dashboards (2: valinor + logs)
- ✅ Sentry error tracking (init en main.py, DSN-based)
- ✅ Structured logging (structlog JSON)
- ✅ Pre-commit hooks (flake8)
- ✅ Dockerfiles (API + Worker multi-stage, non-root, healthcheck)
- ✅ Alembic migrations (3 versiones)
- ✅ Cloudflare worker config (wrangler.toml, 3 envs)

## Pendiente real

### 1. Staging deploy workflow (2-3h)
- Nuevo workflow o branch en deploy.yml: push to `develop` → deploy a Railway staging
- Requiere: crear Railway staging environment (o environment variable toggle)
- Post-deploy: health check `curl /health`

### 2. GHCR image push (1-2h)
- docker-build.yml actualmente usa `push: false`
- Agregar login a `ghcr.io` + push con tags `:develop-latest` y `:sha`

### 3. Auto-migration en deploy (1-2h)
- Agregar step pre-deploy: `alembic upgrade head`
- O ejecutar migrations como container init

### 4. Branch protection (30min)
- Configurar via GitHub API: require tests.yml pass para merge a develop/master

### 5. Cleanup menor
- Network asymmetry: API usa `network_mode: host`, worker usa bridge → normalizar
- production.env.example tiene vars aspiracionales (Stripe, Datadog) no implementadas → limpiar

## Nota
VAL-22 (Scale: load testing, zero-downtime, auto-scaling, métricas YC) queda para semana 9-12.
No es urgente hasta que haya clientes reales.
