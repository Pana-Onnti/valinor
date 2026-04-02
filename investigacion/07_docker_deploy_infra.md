# 07 - Docker, Deploy & Infraestructura

**Fecha:** 2026-03-22
**Scope:** docker-compose (3 variantes), Dockerfiles (5), deploy/, infra/, Makefile, CI/CD workflows, INFRASTRUCTURE.md, setup_infra_val23.sh

---

## 1. Resumen Ejecutivo

Valinor SaaS tiene una infraestructura multi-capa con tres niveles de complejidad Docker (simple, dev, produccion), un pipeline CI/CD via GitHub Actions, deployment split entre Railway (API + Worker) y Vercel (Frontend), un proxy edge en Cloudflare Workers, y un stack de observabilidad local completo (Prometheus + Loki + Grafana). Existe ademas un paquete `@valinor/infra` con Pulumi para IaC, aunque su uso real no esta evidenciado en los workflows actuales. La infraestructura refleja una evolucion organica: de un MVP simple (`docker-compose.simple.yml`) a un stack full con monitoring (`docker-compose.yml`), con restos de configuraciones intermedias (`docker-compose.dev.yml`) que generan cierta redundancia.

---

## 2. Servicios Docker

### 2.1 Archivos Docker Compose

| Archivo | Proposito | Servicios |
|---------|-----------|-----------|
| `docker-compose.yml` | Stack principal (dev + observabilidad) | redis, postgres, api, worker, web, loki, promtail, prometheus, grafana, nginx (profile: production), adminer (profile: dev) |
| `docker-compose.dev.yml` | Stack dev legacy | postgres, redis, api, worker, flower, ssh-demo (profile: demo), demo-db (profile: demo), web (profile: mvp) |
| `docker-compose.simple.yml` | MVP minimalista | api (usa Dockerfile.simple), demo-db (profile: demo) |
| `scripts/docker-compose.dev.yml` | Servicios auxiliares de dev | postgres, redis, minio, mailhog |

### 2.2 Dockerfiles

| Archivo | Base | Multi-stage | Non-root | Healthcheck | Uso |
|---------|------|-------------|----------|-------------|-----|
| `Dockerfile` | python:3.11-slim | Si (builder + runtime) | Si (valinor:1000) | Si (curl /health) | Imagen general (usada en docker-compose.dev.yml) |
| `Dockerfile.api` | python:3.11-slim | No | Si (valinor:1000) | Si (curl /health) | API FastAPI (usada en docker-compose.yml) |
| `Dockerfile.worker` | python:3.11-slim | No | Si (valinor:1000) | No | Worker Celery (usada en docker-compose.yml) |
| `Dockerfile.simple` | python:3.11-slim | No | No | No | MVP simplificado |
| `web/Dockerfile.dev` | node:20-alpine | No | No | No | Frontend Next.js dev |

### 2.3 Detalle de Servicios (docker-compose.yml principal)

| Servicio | Imagen/Build | Puerto Host | Puerto Interno | Mem Limit | Healthcheck |
|----------|-------------|-------------|----------------|-----------|-------------|
| redis | redis:7-alpine | 6380 | 6379 | - | redis-cli ping (5s) |
| postgres | postgres:15-alpine | 5450 | 5432 | - | pg_isready (10s) |
| api | Dockerfile.api | host mode (8000) | 8000 | 512m | curl /health (30s) |
| worker | Dockerfile.worker | - | - | 512m | - |
| web | web/Dockerfile.dev | 3000 | 3000 | - | - |
| loki | grafana/loki:2.9.8 | 3100 | 3100 | - | - |
| promtail | grafana/promtail:2.9.8 | - | 9080 | - | - |
| prometheus | prom/prometheus:v2.51.0 | 9090 | 9090 | - | - |
| grafana | grafana/grafana:10.3.0 | 3001 | 3000 | - | - |
| nginx | nginx:alpine | 80, 443 | 80, 443 | - | - |
| adminer | adminer:latest | 8080 | 8080 | - | - |

---

## 3. Networking

### 3.1 Red principal
- **Network:** `valinor-network` (bridge driver) en docker-compose.yml y docker-compose.dev.yml
- **Network alternativa:** `valinor-dev-network` en scripts/docker-compose.dev.yml

### 3.2 Inconsistencia critica: network_mode: host en API
El servicio `api` en docker-compose.yml usa `network_mode: host`, lo que significa:
- No participa en la red Docker `valinor-network`
- Se conecta a postgres/redis via `localhost:5450` / `localhost:6380` (puertos del host)
- El worker, en cambio, usa DNS Docker normal (`postgres:5432`, `redis:6379`)
- Esto genera una asimetria: API y Worker usan URLs de conexion distintas para los mismos servicios

### 3.3 Prometheus extra_hosts
- Usa `host.docker.internal:host-gateway` para alcanzar la API que corre en modo host

### 3.4 Mapa de puertos

| Puerto Host | Servicio | Notas |
|-------------|----------|-------|
| 80 / 443 | nginx | Solo profile: production |
| 3000 | web (Next.js) | Dev frontend |
| 3001 | grafana | Dashboards |
| 3100 | loki | Log aggregation |
| 5450 | postgres | Metadatos (no client data) |
| 6380 | redis | Cache + broker Celery |
| 8000 | api (FastAPI) | network_mode: host |
| 8080 | adminer | Solo profile: dev |
| 9090 | prometheus | Metrics |

---

## 4. Volumes

### 4.1 Named Volumes
| Volume | Servicio | Contenido |
|--------|----------|-----------|
| `redis_data` | redis | Datos AOF persistidos |
| `postgres_data` | postgres | Data PostgreSQL |
| `valinor_profiles` | api | Client profiles en /tmp/valinor_profiles |
| `prometheus_data` | prometheus | TSDB (retencion 30d) |
| `grafana_data` | grafana | Dashboards, config |
| `loki_data` | loki | Chunks de logs (retencion 30d) |

### 4.2 Bind Mounts relevantes
| Mount | Servicio | Modo | Riesgo |
|-------|----------|------|--------|
| `./core`, `./api`, `./shared` | api, worker | rw | Hot-reload; ok para dev |
| `./ssh_keys` | api, worker | ro | Claves SSH para tunneling a DBs de clientes |
| `${HOME}/.nvm/.../claude` | api, worker | ro | Monta el CLI de Claude del host |
| `${HOME}/.claude` | api, worker | ro | Config de Claude del host |
| `/var/lib/docker/containers` | promtail | ro | Acceso a logs de Docker |
| `./deploy/sql/init.sql` | postgres | ro | Schema inicial |

### 4.3 Observaciones
- El mount de Claude CLI (`v20.20.1`) esta hardcodeado a una version especifica de Node via NVM. Si se actualiza Node, los contenedores fallan silenciosamente.
- El volume `valinor_profiles` usa `/tmp/` como punto de montaje -- no es persistente ante reinicios del host si no se usa named volume (aqui si se usa, pero la ruta sugiere temporalidad).

---

## 5. Environments (Variables de Entorno)

### 5.1 Desarrollo local (docker-compose.yml)

| Variable | Valor | Notas |
|----------|-------|-------|
| `DATABASE_URL` | postgresql://valinor:valinor_secret@localhost:5450/valinor_metadata | API usa host mode |
| `REDIS_URL` | redis://localhost:6380 | API usa host mode |
| `LLM_PROVIDER` | ${LLM_PROVIDER:-console_cli} | Default: usa Claude CLI local |
| `ANTHROPIC_API_KEY` | ${ANTHROPIC_API_KEY:-} | Opcional si usa console_cli |
| `CELERY_ENABLED` | true | - |
| `CORS_ORIGINS` | * | Permisivo en dev |
| `WORKERS` | 4 | Uvicorn workers |
| `GF_SECURITY_ADMIN_PASSWORD` | valinor | Hardcodeado para dev |

### 5.2 Produccion (Railway)

| Variable | Fuente |
|----------|--------|
| `APP_ENV` | Manual (production) |
| `DATABASE_URL` | Auto-injected por Railway |
| `REDIS_URL` | Auto-injected por Railway |
| `SENTRY_DSN` | Configurado via setup_infra_val23.sh |
| `SENTRY_TRACES_SAMPLE_RATE` | 0.1 |
| `ANTHROPIC_API_KEY` | Secret manual |
| `PORT` | 8000 |

### 5.3 Templates de entorno
- `deploy/production.env.example` — template exhaustivo con Supabase, Stripe, Resend, Datadog, rate limiting, SSL, backups. Muchas variables son aspiracionales (Stripe, Datadog, custom domains) y no estan implementadas en el codigo actual.
- `deploy/staging.env.example` — similar, con valores reducidos (MAX_CONCURRENT_JOBS=5 vs 20 en prod).

---

## 6. Deploy Pipeline (CI/CD)

### 6.1 GitHub Actions Workflows

| Workflow | Trigger | Jobs | Estado |
|----------|---------|------|--------|
| `tests.yml` | push a master, PR a main | lint (flake8) -> test (matrix 3.10, 3.11, con coverage 60% min) | Activo |
| `docker-build.yml` | push a master | Build API + Worker images (sin push a registry) | Activo |
| `deploy.yml` | push a master, manual | deploy-api (Railway), deploy-frontend (Vercel) | Activo |

### 6.2 Flujo de deploy

```
push a master
    |
    +---> tests.yml: lint -> test (matrix Python 3.10/3.11)
    |         |-- coverage >= 60%
    |         |-- upload artefactos (test-results.xml, coverage.xml)
    |         +-- upload Codecov
    |
    +---> docker-build.yml: build API + Worker (validacion, no push)
    |
    +---> deploy.yml:
              |-- deploy-api: railway up --service API --detach
              +-- deploy-frontend: vercel build --prod + vercel deploy --prebuilt --prod
```

### 6.3 Inconsistencia de branches
- `tests.yml` hace push a `master` y PR a `main`
- `deploy.yml` hace push a `master`
- El branch actual del repo es `develop`
- La branch principal declarada en el README es `main`
- El setup script referencia la default branch del repo como variable
- **Esto indica confusion entre master/main/develop** que puede causar que deploys no se disparen correctamente

### 6.4 Cloudflare Workers Deploy
- Script `deploy/deploy-cloudflare.sh` permite deploy manual a Cloudflare Workers (production/staging/dev)
- Worker actua como reverse proxy con CORS, security headers, health check shortcut, y logging de IPs
- Rate limiting real aun no implementado (TODO: requiere KV/Durable Objects)
- No esta integrado en GitHub Actions -- es un paso manual

### 6.5 Setup de Infraestructura
- `scripts/setup_infra_val23.sh` es un script interactivo (con `read -p`) que:
  - Instala Railway CLI y GitHub CLI
  - Autentica en ambos servicios
  - Linkea el proyecto Railway y configura variables
  - Configura GitHub Secrets (SENTRY_DSN, RAILWAY_TOKEN, ANTHROPIC_API_KEY)
  - Opcionalmente configura branch protection y custom domain

---

## 7. Infra Cloud

### 7.1 Servicios Cloud en Produccion

| Componente | Proveedor | Tipo |
|------------|-----------|------|
| API Backend | Railway | Containerized (FastAPI) |
| Worker (Celery) | Railway | Containerized |
| PostgreSQL | Railway | Managed |
| Redis | Railway | Managed (cache + broker) |
| Frontend | Vercel | Next.js (auto-deploy) |
| Edge Proxy | Cloudflare Workers | TypeScript worker |
| Error Tracking | Sentry | SaaS |
| DNS / CDN | Cloudflare | Managed |
| Repo / CI | GitHub Actions | SaaS |
| Coverage | Codecov | SaaS |

### 7.2 URLs de Produccion

| Servicio | URL |
|----------|-----|
| API (Railway) | https://api-production-ca22.up.railway.app |
| Frontend (Vercel) | https://valinor-saas.vercel.app |
| Swagger Docs | https://api-production-ca22.up.railway.app/docs |
| Health | https://api-production-ca22.up.railway.app/health |

### 7.3 Pulumi IaC (packages/infra)
- Paquete `@valinor/infra` v2.0.0 con dependencias Pulumi para Cloudflare y GitHub
- Scripts para deploy/preview/destroy a staging y production
- **No esta referenciado en ningun workflow de CI/CD** -- parece ser aspiracional o abandonado

### 7.4 Observabilidad Local
Stack completo para desarrollo local:

```
[API /metrics] --> [Prometheus :9090] --> [Grafana :3001]
[Container logs] --> [Promtail] --> [Loki :3100] --> [Grafana :3001]
```

- Prometheus: scrape cada 15s, retencion 30 dias, hot-reload habilitado
- Loki: schema v13, retencion 30 dias, ingestion rate 16 MB/s
- Promtail: parsea JSON de Docker, extrae structlog fields (level, event, job_id, request_id)
- Grafana: dashboards pre-provisionados (valinor.json, logs.json), datasources auto-configuradas
- **En produccion, la observabilidad es solo Sentry** -- no hay Prometheus/Grafana cloud

---

## 8. Makefile Targets

| Target | Descripcion | Comando |
|--------|-------------|---------|
| `help` | Muestra targets disponibles | awk auto-doc |
| `dev` | Inicia todos los servicios | `docker compose up -d` |
| `stop` | Para todos los servicios | `docker compose down` |
| `logs` | Tail de logs del API | `docker compose logs -f api` |
| `shell` | Shell en contenedor API | `docker compose exec api bash` |
| `db-shell` | psql en contenedor Postgres | `docker compose exec postgres psql -U valinor -d valinor_saas` |
| `install` | Instala dependencias Python | `pip install -r requirements.txt` |
| `test` | Suite completa de tests | `pytest tests/ -v` |
| `test-cov` | Tests con coverage HTML + terminal | pytest --cov (min 60%) |
| `test-fast` | Tests rapidos (sin slow/perf/integ) | pytest -m markers |
| `lint` | Flake8 en api/, shared/, core/ | max-line 120 |
| `typecheck` | mypy en api/ y shared/ | ignore-missing-imports |
| `clean` | Limpia pycache, pytest, coverage | find + rm |

**Bug en db-shell:** Usa `valinor_saas` como nombre de DB pero el compose crea `valinor_metadata`. El comando fallara.

---

## 9. Fortalezas

1. **Separacion de concerns clara:** API, Worker, Frontend como servicios independientes con Dockerfiles dedicados. Facilita scaling horizontal.

2. **Observabilidad local completa:** Stack Prometheus + Loki + Grafana con dashboards pre-provisionados y parsing automatico de structlog. Permite debug local con la misma calidad que produccion.

3. **Multiples niveles de complejidad:** Tres variantes de compose (simple, dev, full) permiten onboarding rapido (simple) o desarrollo completo (full).

4. **Security by default en Dockerfiles:** Non-root user (valinor:1000) en Dockerfile, Dockerfile.api y Dockerfile.worker. SSH keys montadas read-only.

5. **Cloudflare Worker como edge proxy:** Security headers, CORS centralizado, health check shortcut, y preparacion para rate limiting. Buena arquitectura edge-first.

6. **Healthchecks y depends_on con condiciones:** Redis y Postgres verifican salud antes de que API y Worker inicien. Evita race conditions en startup.

7. **Logging estructurado:** json-file driver con limites de tamano (10m/50m), tags por contenedor. Promtail parsea automaticamente los campos structlog.

8. **CI con matrix testing:** Tests en Python 3.10 y 3.11, coverage enforced al 60%, artefactos retenidos 14 dias. Buena base de calidad.

9. **Script de setup idempotente:** `setup_infra_val23.sh` automatiza la configuracion inicial de Railway + GitHub completa, con verificaciones previas.

10. **Multi-stage build en Dockerfile principal:** Reduce tamano de imagen final separando build deps de runtime deps.

---

## 10. Debilidades

1. **Confusion de branches master/main/develop:** Los workflows de CI/CD apuntan a `master`, el repo trabaja en `develop`, y el branch principal declarado es `main`. Los deploys probablemente no se disparan automaticamente.

2. **network_mode: host en API:** Rompe el aislamiento Docker, impide que la API use DNS de contenedores. Genera asimetria con el Worker (que si usa DNS Docker). Causa problemas en Mac/Windows donde host mode se comporta diferente.

3. **Claude CLI hardcodeado a version de Node:** El mount `${HOME}/.nvm/versions/node/v20.20.1/bin/claude` se rompe al actualizar Node. Deberia resolverse dinamicamente.

4. **Docker images no se publican a un registry:** `docker-build.yml` construye las imagenes pero con `push: false`. Railway redeploys desde el source, haciendo el workflow redundante.

5. **Pulumi IaC abandonado:** `packages/infra` tiene dependencias de Pulumi pero no esta integrado en CI/CD ni referenciado desde ningun script. Genera confusion sobre la fuente de verdad de la infra.

6. **Variables de entorno aspiracionales:** `production.env.example` incluye Stripe, Datadog, Resend, CSRF protection que no estan implementados. Genera falsa sensacion de completitud.

7. **Sin staging real:** No hay workflow de deploy a staging. Solo existe el template de variables. El pipeline va directo de local a produccion.

8. **Grafana/Prometheus solo local:** En produccion solo hay Sentry. No hay metricas de negocio, latencia, ni throughput en un dashboard de produccion.

9. **CORS_ORIGINS: "*" en desarrollo:** Aunque es aceptable en dev, el Worker de Cloudflare tiene una allowlist restrictiva. Si el backend se expone directamente (sin pasar por el Worker), queda abierto.

10. **Ausencia de healthcheck en Worker:** El Dockerfile.worker y el servicio worker en compose no tienen healthcheck. Si Celery se congela, no hay deteccion automatica.

11. **Nginx referenciado pero no configurado:** El servicio nginx en docker-compose.yml monta `./deploy/nginx/nginx.conf` pero ese archivo no existe en el repo. El profile production falla.

12. **Bug en Makefile db-shell:** Referencia `valinor_saas` como base de datos, pero el compose crea `valinor_metadata`.

13. **Promtail corre como root:** Necesario para leer `/var/lib/docker/containers` pero es un riesgo de seguridad. Deberia evaluarse Docker socket proxy como alternativa.

14. **Sin docker-compose override workflow:** No hay `.env.example` en la raiz ni documentacion de que variables de entorno setear antes de `docker compose up`. El onboarding depende de conocimiento tribal.

---

## 11. Recomendaciones 2026

### Prioridad Alta

1. **Unificar branches:** Decidir si la rama principal es `main` o `master`. Actualizar todos los workflows de CI/CD para usar la misma referencia. Configurar `develop` -> PR a `main` -> auto-deploy como flujo canonico.

2. **Eliminar network_mode: host del API:** Migrar a la red bridge standard. Usar DNS Docker (`postgres:5432`, `redis:6379`) consistentemente en API y Worker. Actualizar `DATABASE_URL` y `REDIS_URL` para ambos servicios.

3. **Agregar environment staging en CI/CD:** Crear un workflow de deploy a staging (Railway environment o servicio separado) que se dispare en push a `develop`. Produccion solo desde `main` con approval manual.

4. **Dinamizar mount de Claude CLI:** Reemplazar la ruta hardcodeada de NVM con una resolucion tipo `$(which claude)` en un `.env` local o un script wrapper.

5. **Crear `.env.example` en la raiz:** Documentar las variables minimas necesarias (`LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `LOG_LEVEL`) para que `docker compose up` funcione sin leer docs.

### Prioridad Media

6. **Healthcheck en Worker:** Agregar un healthcheck basado en `celery inspect ping` o un endpoint HTTP simple para detectar workers congelados.

7. **Publicar images a GHCR o Railway registry:** Integrar `docker/login-action` y push a GitHub Container Registry. Permite rollbacks rapidos y desacopla build de deploy.

8. **Observabilidad cloud:** Agregar Grafana Cloud Free tier o Railway Observability para metricas de produccion. Sentry cubre errores pero no metricas de negocio (jobs/min, latencia p99, tokens LLM consumidos).

9. **Crear la config de nginx:** Implementar `deploy/nginx/nginx.conf` con reverse proxy, SSL termination, y rate limiting. O eliminar el servicio nginx del compose si no se va a usar (Railway y Vercel ya manejan SSL).

10. **Limpiar docker-compose.dev.yml legacy:** Consolidar en un solo `docker-compose.yml` con profiles (`dev`, `monitoring`, `demo`, `production`). Eliminar el compose redundante en `scripts/`.

### Prioridad Baja

11. **Decidir sobre Pulumi:** Si se va a usar, integrar en CI/CD. Si no, eliminar `packages/infra` para reducir confusion.

12. **Integrar Cloudflare Worker deploy en CI/CD:** Agregar un job en `deploy.yml` que corra `wrangler deploy --env production` despues del deploy de Railway.

13. **Rate limiting real en Worker:** Implementar con Cloudflare KV o Durable Objects. El logging actual sin enforcement no protege contra abuso.

14. **Corregir bug db-shell en Makefile:** Cambiar `valinor_saas` a `valinor_metadata`.

15. **Evaluar docker-compose watch:** Docker Compose 2.22+ soporta `watch` para hot-reload sin bind mounts, lo cual es mas performante que montar volumenes en dev.

---

## Anexo: Arbol de Archivos de Infraestructura

```
valinor-saas/
+-- docker-compose.yml              # Stack principal (11 servicios)
+-- docker-compose.dev.yml           # Stack dev legacy (7 servicios)
+-- docker-compose.simple.yml        # MVP minimalista (1-2 servicios)
+-- Dockerfile                       # Multi-stage, general
+-- Dockerfile.api                   # API FastAPI
+-- Dockerfile.worker                # Worker Celery
+-- Dockerfile.simple                # MVP simplificado
+-- Makefile                         # 12 targets (dev, test, lint, etc.)
+-- INFRASTRUCTURE.md                # Dashboards, URLs, secrets, accesos
+-- web/
|   +-- Dockerfile.dev               # Frontend Next.js dev
+-- deploy/
|   +-- deploy-cloudflare.sh         # Deploy manual a CF Workers
|   +-- production.env.example       # Template env produccion
|   +-- staging.env.example          # Template env staging
|   +-- sql/init.sql                 # Schema DDL (6 tablas, indices)
|   +-- cloudflare/
|   |   +-- wrangler.toml            # Config CF Workers (prod + staging)
|   |   +-- src/index.ts             # Edge proxy (CORS, security, logging)
|   |   +-- package.json             # Deps del worker
|   +-- prometheus/prometheus.yml     # Scrape config (API + self)
|   +-- loki/loki-config.yml          # Log storage (30d retention)
|   +-- promtail/promtail-config.yml  # Log collection + structlog parsing
|   +-- grafana/
|       +-- dashboards/              # valinor.json, logs.json
|       +-- provisioning/
|           +-- datasources/         # prometheus.yml, loki.yml
|           +-- dashboards/          # dashboards.yml (auto-provision)
+-- scripts/
|   +-- setup_infra_val23.sh         # Setup Railway + GitHub (interactivo)
|   +-- docker-compose.dev.yml       # Servicios auxiliares (minio, mailhog)
+-- packages/
|   +-- infra/package.json           # Pulumi IaC (sin uso en CI/CD)
+-- .github/workflows/
    +-- tests.yml                    # Lint + test matrix (3.10, 3.11)
    +-- docker-build.yml             # Build validation (sin push)
    +-- deploy.yml                   # Deploy Railway + Vercel
```
