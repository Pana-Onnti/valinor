# Valinor SaaS — Infrastructure

## Dashboards

| Servicio | URL | Acceso |
|----------|-----|--------|
| Railway (prod) | https://railway.app/project/b78babfc-1b70-45f5-a866-eb23d08e04ac | Invite → railway.app |
| Sentry | https://delta4c.sentry.io/projects/valinor/ | Invite → sentry.io |
| GitHub Actions | https://github.com/Pana-Onnti/valinor/actions | Repo collaborator |
| Vercel (frontend) | https://vercel.com/nicolasbaseggiodev-gmailcoms-projects/valinor-saas | Invite → vercel.com |
| lmnr (futuro) | — | Pendiente VAL-27 |

## URLs de producción

| Servicio | URL |
|----------|-----|
| API (Railway) | https://api-production-ca22.up.railway.app |
| Frontend (Vercel) | https://valinor-saas.vercel.app |
| API Docs (Swagger) | https://api-production-ca22.up.railway.app/docs |
| Health check | https://api-production-ca22.up.railway.app/health |

## Accesos por servicio

| Servicio | nicolasbaseggiodev | Pedro |
|----------|-------------------|-------|
| Railway | Owner | ⏳ pendiente invitación |
| Sentry | Owner | ⏳ pendiente invitación |
| GitHub | Owner | Collaborator |
| Vercel | Owner | ⏳ pendiente invitación |

## Variables de entorno por servicio

### API (Railway — production)

| Variable | Descripción | Fuente |
|----------|-------------|--------|
| `APP_ENV` | Environment tag (`production`) | Manual |
| `SENTRY_DSN` | DSN del proyecto Valinor en Sentry | Sentry > Project Settings |
| `SENTRY_TRACES_SAMPLE_RATE` | Sampling de performance (`0.1` en prod) | Manual |
| `ANTHROPIC_API_KEY` | API key de Anthropic | anthropic.com |
| `DATABASE_URL` | PostgreSQL connection string | Auto-injected por Railway |
| `REDIS_URL` | Redis connection string | Auto-injected por Railway |
| `PORT` | Puerto de la app (`8000`) | Manual |
| `CORS_ORIGINS` | Origins adicionales para CORS | Manual (opcional) |

### Frontend (Vercel)

| Variable | Descripción | Valor actual |
|----------|-------------|--------------|
| `NEXT_PUBLIC_API_URL` | URL base del backend | `https://api-production-ca22.up.railway.app` |
| `NEXT_PUBLIC_LLM_PROVIDER` | Provider LLM para UI | `claude` |

## Rotación de secrets

1. **ANTHROPIC_API_KEY** → regenerar en console.anthropic.com → `railway variable set ANTHROPIC_API_KEY=<nueva>` + `gh secret set ANTHROPIC_API_KEY --repo Pana-Onnti/valinor`
2. **RAILWAY_TOKEN** (CI/CD) → railway.app/account/tokens → crear nuevo → borrar viejo → `gh secret set RAILWAY_TOKEN --repo Pana-Onnti/valinor`
3. **SENTRY_DSN** → no rotar a menos que haya leak (es semi-público por diseño)

Después de rotar cualquier secret de Railway: `railway redeploy --yes` para que el servicio tome los nuevos valores.

## Logs por environment

### Producción (Railway)
```bash
railway logs --tail 100            # últimas 100 líneas
railway logs --tail 50 --json      # formato JSON estructurado
```

### Local
```bash
docker compose up -d
docker compose logs -f api         # API
docker compose logs -f worker      # Worker
```

### Sentry
- Errors en tiempo real: https://delta4c.sentry.io/issues/
- Performance traces: https://delta4c.sentry.io/performance/
- Endpoint de test (no-prod): `GET /sentry-debug`

## Servicios en Railway

| Servicio | ID | Descripción |
|----------|-----|-------------|
| API | `28adc6de-bca8-4837-a3e6-cfa6b9bc25c2` | FastAPI — entrypoint principal |
| Worker | `8497cb0d-7b77-4209-8c68-3ad398887ccb` | Celery worker async |
| Postgres | `3a0fc7c7-f78d-4a47-b4d2-2469a176f543` | PostgreSQL managed |
| Redis | `4aaca6d5-e309-4a73-a736-16a93b89fec0` | Redis managed (caché + broker) |

## GitHub Secrets (CI/CD)

| Secret | Descripción |
|--------|-------------|
| `RAILWAY_TOKEN` | Deploy token — creado via API (`valinor-ci-cd`) |
| `SENTRY_DSN` | Para reportar errores de build en Sentry |
| `ANTHROPIC_API_KEY` | Para tests de integración con Claude |
