# 13. Apps Layer — Aplicaciones Desplegables

## Resumen

El directorio `apps/` contiene tres aplicaciones desplegables definidas como scaffolds dentro del monorepo Turborepo: **api-gateway** (Cloudflare Workers), **dashboard** (Next.js admin panel) y **worker-runner** (GitHub Actions runner). Sin embargo, estas tres apps existen **solo como `package.json`** sin codigo fuente (`src/` vacio en las tres). La produccion real del proyecto opera con una arquitectura completamente diferente: una API FastAPI en Python (`api/`), un worker Celery en Python (`worker/`), y un frontend Next.js independiente (`web/`). Esto crea una dualidad arquitectonica significativa entre la vision futura (monorepo TypeScript edge-first) y la realidad operativa (stack Python monolitico con frontend desacoplado).

---

## API Gateway (`apps/api-gateway/`)

### Archivos
- `package.json` — `@valinor/api-gateway` v2.0.0
- `wrangler.toml` — configuracion de Cloudflare Workers
- **Sin directorio `src/`** — no hay codigo implementado

### Stack Declarado
| Componente | Tecnologia |
|-----------|------------|
| Runtime | Cloudflare Workers |
| Framework | Hono ^3.12.0 |
| Validacion | Zod + @hono/zod-validator |
| Auth/DB | @supabase/supabase-js ^2.38.0 |
| Deploy tool | Wrangler ^3.22.0 |
| Tests | Vitest ^1.0.0 |

### Configuracion Wrangler
El `wrangler.toml` define una infraestructura Cloudflare completa con tres ambientes (development, staging, production):
- **KV Namespaces**: binding `CACHE` para caching por ambiente
- **R2 Buckets**: binding `STORAGE` para reportes (`valinor-reports-{env}`)
- **Queues**: binding `ANALYSIS_QUEUE` para jobs en background (`analysis-{env}`)
- **D1 Database**: comentado, preparado pero no activado
- **CPU limit**: 10,000ms (10s) para analysis jobs
- **Custom domains**: comentado, listo para `api.valinor.com/*`

### Dependencia de Packages
- `@valinor/shared` (workspace) — tipos y schemas compartidos

### Relacion con el Sistema Real
El API Gateway de Cloudflare Workers NO es lo que se ejecuta en produccion. La API real es `api/main.py`, un monolito FastAPI de ~102KB desplegado via `Dockerfile.api` a Railway. El gateway Hono/Workers es un plan futuro de migracion edge.

---

## Dashboard App (`apps/dashboard/`)

### Archivos
- `package.json` — `@valinor/dashboard` v2.0.0
- **Sin directorio `src/`** — no hay codigo implementado

### Stack Declarado
| Componente | Tecnologia |
|-----------|------------|
| Framework | Next.js ^14.0.0 |
| UI | Tailwind ^3.3.0, Headless UI, Heroicons |
| Charts | Tremor ^3.14.0, Recharts ^2.8.0 |
| Forms | react-hook-form + Zod |
| Data fetch | SWR ^2.2.0, Axios |
| Puerto | 3001 |

### Dependencia de Packages
- `@valinor/shared` (workspace) — tipos compartidos

### Relacion con el Sistema Real
El dashboard admin es un scaffold separado de la app frontend principal. La app frontend real vive en `web/` (fuera de `apps/`) con su propio `package.json` (`valinor-saas-web`) y se despliega independientemente a Vercel. Hay diferencias notables:

| Aspecto | `apps/dashboard/` (scaffold) | `web/` (real) |
|---------|------------------------------|---------------|
| Nombre | @valinor/dashboard | valinor-saas-web |
| Charts | Tremor + Recharts | Recharts solo |
| State | SWR | Zustand + React Query |
| UI components | Headless UI | Radix UI + Lucide |
| Animations | ninguna | Framer Motion |
| Deploy | no configurado | Vercel (project ID real) |
| Pages | 0 | 21 pages, 19 componentes |

La app `dashboard` en `apps/` estaba pensada como un panel de administracion interno, separado del frontend de clientes en `web/`. Pero nunca se implemento.

---

## Worker Runner (`apps/worker-runner/`)

### Archivos
- `package.json` — `@valinor/worker-runner` v2.0.0
- **Sin directorio `src/`** — no hay codigo implementado

### Stack Declarado
| Componente | Tecnologia |
|-----------|------------|
| Runtime | Node.js (TypeScript compilado) |
| CI Integration | @actions/core ^1.10.0, @actions/github ^6.0.0 |
| Dev | tsx ^4.6.0 (watch mode) |
| Config | dotenv ^16.3.0 |

### Dependencias de Packages
- `@valinor/core` (workspace) — logica de negocio
- `@valinor/shared` (workspace) — tipos
- `@valinor/agents` (workspace) — agentes Claude AI
- `@valinor/workers` (workspace) — procesadores de jobs

Es la app con **mas dependencias internas** (4 de 7 packages), lo que indica que seria el punto de integracion principal del sistema.

### Relacion con el Sistema Real
El worker real es `worker/`, un proceso Python con Celery que consume de Redis (cola `valinor`). Se configura en `worker/celery_app.py` con:
- Hard limit: 1 hora por tarea
- Soft limit: 55 minutos
- Max 10 tasks por child process
- Beat schedule: limpieza de jobs expirados cada 6 horas

El `worker-runner` de `apps/` habria sido un runner de GitHub Actions para ejecutar analisis como jobs de CI, un concepto de ejecucion completamente diferente (ephemeral CI vs long-running Celery worker).

---

## Relacion con Packages

### Grafo de Dependencias Declarado (apps -> packages)

```
apps/api-gateway ─────> packages/shared
apps/dashboard ──────> packages/shared
apps/worker-runner ──> packages/shared
                   ──> packages/core
                   ──> packages/agents
                   ──> packages/workers
```

### Packages del Monorepo (7 total)

| Package | Nombre | Proposito | Dependencias internas |
|---------|--------|-----------|----------------------|
| `packages/shared` | @valinor/shared | Tipos, schemas Zod, utilidades | ninguna |
| `packages/core` | @valinor/core | DB connectors (pg, mysql2, tedious), SSH, auth | shared |
| `packages/agents` | @valinor/agents | Agentes Claude AI (cartographer, analyst, sentinel, hunter, narrator, orchestrator) | core, shared |
| `packages/api` | @valinor/api | Endpoints REST Hono + middleware | core, shared, agents |
| `packages/workers` | @valinor/workers | Job processors BullMQ + cron | core, shared, agents |
| `packages/web` | @valinor/web | Frontend Next.js + Radix UI + Playwright | shared |
| `packages/infra` | @valinor/infra | IaC con Pulumi (Cloudflare + GitHub) | ninguna |

### Problema: Dualidad Packages vs Directorios Python

Los `packages/` TypeScript y los directorios Python raiz sirven propositos analogos pero son sistemas completamente separados:

| Funcion | Package TS (sin implementar) | Directorio Python (real) |
|---------|------------------------------|--------------------------|
| API | packages/api (Hono) | api/ (FastAPI) |
| Workers | packages/workers (BullMQ) | worker/ (Celery) |
| Core | packages/core (pg, mysql2) | core/valinor/ |
| Shared | packages/shared (Zod) | shared/ (Pydantic) |
| Frontend | packages/web (Next.js) | web/ (Next.js) |
| Agents | packages/agents (Claude SDK) | core/agents/ |

La unica pieza que esta realmente operativa en el ecosistema Node.js es `web/`, que es un proyecto Next.js independiente (no usa workspace references).

---

## Deployment Model

### Modelo Real (Operativo)

```
                    ┌─────────────┐
                    │   Vercel     │
                    │   web/       │ ── Next.js frontend
                    │   :3000      │
                    └──────┬──────┘
                           │ HTTP
                    ┌──────▼──────┐
                    │   Railway    │
                    │   api/       │ ── FastAPI monolito
                    │   :8000      │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼──┐  ┌──────▼──┐  ┌─────▼──────┐
     │  Celery    │  │  Redis   │  │ PostgreSQL  │
     │  worker/   │  │  :6380   │  │  :5450      │
     │  (Railway) │  │          │  │  Supabase?   │
     └───────────┘  └─────────┘  └────────────┘
```

### Modelo Planeado (apps/ + packages/)

```
                    ┌──────────────────┐
                    │  Vercel/CF Pages │
                    │  packages/web    │
                    │  apps/dashboard  │
                    └───────┬──────────┘
                            │
                    ┌───────▼──────────┐
                    │ Cloudflare Workers│
                    │ apps/api-gateway  │
                    │ (Hono + KV + R2) │
                    └───────┬──────────┘
                            │
              ┌─────────────┼───────────────┐
              │             │               │
     ┌────────▼──┐  ┌──────▼────┐  ┌───────▼──────┐
     │ CF Queues  │  │  Supabase  │  │ GitHub Actions│
     │ + Workers  │  │  (D1/PG)   │  │ worker-runner │
     └───────────┘  └───────────┘  └──────────────┘
```

### Docker Compose — 4 variantes

| Archivo | Proposito | Servicios |
|---------|-----------|-----------|
| `docker-compose.yml` | Produccion-like completa | api, worker, web, redis, postgres, nginx, loki, promtail, prometheus, grafana |
| `docker-compose.dev.yml` | Desarrollo con demos | api, worker, redis, postgres, flower, ssh-demo, demo-db |
| `docker-compose.simple.yml` | MVP minimo | api (simple_api.py), demo-db |
| `scripts/docker-compose.dev.yml` | Scripts de desarrollo | (variante auxiliar) |

### CI/CD Pipelines

| Workflow | Trigger | Que hace |
|----------|---------|----------|
| `tests.yml` | push master, PR main | flake8 lint + pytest (Python 3.10/3.11) con coverage |
| `docker-build.yml` | push master | Build Dockerfile.api + Dockerfile.worker (sin push) |
| `deploy.yml` | push master | API a Railway + Frontend a Vercel |

Nota: Los workflows son 100% Python-centric. No hay pipelines para el monorepo Turborepo, ni builds de los packages/ TypeScript.

---

## Fortalezas

1. **Vision arquitectonica clara**: El diseno apps/ + packages/ sigue las mejores practicas de monorepos Turborepo con separacion limpia entre aplicaciones desplegables y librerias compartidas.

2. **Configuracion Wrangler completa**: El `wrangler.toml` del api-gateway tiene una configuracion de 3 ambientes profesional con KV, R2, Queues, limites de CPU y dominios custom preparados.

3. **Grafo de dependencias bien pensado**: `@valinor/shared` como base, `@valinor/core` como capa de dominio, `@valinor/agents` como capa de AI, y las apps como consumidores finales — sigue principios hexagonales.

4. **Pipeline Turborepo configurada**: `turbo.json` define correctamente build, test, deploy con dependencias topologicas (`^build`), caching selectivo y outputs especificos por tipo de artefacto.

5. **Stack Python operativo robusto**: El sistema real funciona con FastAPI + Celery + Redis + PostgreSQL, con observabilidad completa (Prometheus, Grafana, Loki, Sentry), healthchecks, rate limiting (slowapi) y webhooks.

6. **Deploy multi-plataforma pragmatico**: Railway para backend Python + Vercel para frontend Next.js es una combinacion probada y costo-efectiva.

7. **Seguridad operativa**: Non-root containers, SSH keys read-only, Sentry con filtrado de headers sensibles, CORS configurado, rate limiting.

---

## Debilidades

1. **Apps sin implementacion**: Las tres apps en `apps/` son scaffolds vacios (solo `package.json`, sin `src/`). Representan ~0 lineas de codigo productivo. No se ha escrito ni una linea de TypeScript para ellas.

2. **Dualidad de arquitectura confusa**: Coexisten dos visiones incompatibles del sistema:
   - **Python actual**: FastAPI + Celery + directorios planos en raiz
   - **TypeScript futuro**: Hono + BullMQ + Cloudflare Workers en monorepo

   No hay un plan documentado de migracion entre ambas.

3. **Monorepo Turborepo fantasma**: `turbo.json` configura pipelines para packages que no tienen codigo. `npm run build` ejecutaria Turbo sobre 10 workspaces vacios. Overhead de configuracion sin valor.

4. **Inconsistencia frontend**: Existen tres definiciones del frontend:
   - `packages/web` (Radix UI, Playwright, workspace) — vacio
   - `apps/dashboard` (Tremor, SWR) — vacio
   - `web/` (Zustand, React Query, Vercel) — **el unico real**, con 21 pages y 19 componentes

5. **Worker conceptualmente diferente**: `apps/worker-runner` (GitHub Actions ephemeral) vs `worker/` (Celery long-running) son modelos de ejecucion incompatibles. No es una migracion, es un cambio de paradigma.

6. **CI/CD ignora el monorepo**: Los 3 workflows de GitHub Actions (tests, docker-build, deploy) solo tocan Python. No hay `npm run build`, `turbo run test`, ni deploy de Cloudflare Workers.

7. **api/main.py monolitico**: 102KB en un solo archivo Python es un code smell grave. Concentra rutas, modelos, logica de negocio y caching en un unico modulo, contradiciendo la separacion hexagonal declarada en los packages.

8. **Packages duplican packages**: `packages/api` (Hono) duplica la intencion de `api/` (FastAPI). `packages/workers` (BullMQ) duplica `worker/` (Celery). Esto genera confusion sobre cual es la fuente de verdad.

9. **No hay integracion workspace real**: `web/` tiene su propio `package-lock.json` y `node_modules/`. No consume `@valinor/shared` via workspace. Es un proyecto Next.js completamente independiente.

10. **Deploy workflow apunta a `master`**: Los workflows se triggean en `master`, pero el branch principal es `main` (segun git status). PRs van a `main` pero deploys se disparan en `master`.

---

## Recomendaciones 2026

### R1: Decidir la arquitectura target y eliminar la dualidad
Tomar una decision explicita: o se migra a Cloudflare Workers + TypeScript, o se consolida en Python + FastAPI. Mantener ambos scaffolds sin implementar genera deuda cognitiva.

**Si la decision es Python (recomendado a corto plazo)**:
- Eliminar `apps/api-gateway/`, `apps/worker-runner/`
- Eliminar `packages/api`, `packages/core`, `packages/agents`, `packages/workers`
- Conservar solo `packages/shared` (tipos Zod compartidos con el frontend)
- Mover `web/` a `apps/web/` y conectarlo al workspace

**Si la decision es TypeScript (migracion a mediano plazo)**:
- Crear un plan de migracion incremental documentado
- Empezar por `apps/api-gateway/src/` con un endpoint health/proxy
- Implementar `packages/shared/src/` con los tipos Zod que ya tiene `web/`

### R2: Refactorizar api/main.py
Partir el monolito de 102KB en modulos coherentes. Ya existen `api/routers/` y `api/routes/` pero la mayoria de la logica sigue en `main.py`. Target: ningun archivo Python mayor a 500 lineas.

### R3: Integrar web/ al workspace
```json
// web/package.json
"dependencies": {
  "@valinor/shared": "workspace:*"
}
```
Eliminar `web/package-lock.json`, usar el lockfile raiz, y beneficiarse del hoisting de dependencias.

### R4: Alinear CI/CD con la realidad
- Cambiar triggers de `master` a `main` (o viceversa, pero ser consistente)
- Agregar un job de typecheck/build para el monorepo TS si se decide mantenerlo
- Agregar deploy de Cloudflare Workers si se decide avanzar con el api-gateway

### R5: Resolver la triplicacion del frontend
Unificar en una sola definicion del frontend:
- Eliminar `packages/web` y `apps/dashboard` (ambos vacios)
- Mantener `web/` como la unica fuente de verdad del frontend
- Si se necesita un dashboard admin, crearlo como ruta dentro de `web/app/admin/`

### R6: Documentar la decision de deployment model
Crear un ADR (Architecture Decision Record) que explique:
- Por que se eligio Railway + Vercel sobre Cloudflare Workers
- Cuando (si alguna vez) se planea migrar al edge
- Que servicios de Cloudflare (KV, R2, Queues) se usarian y por que

### R7: Eliminar o activar el monorepo Turborepo
Si no se van a usar los packages TypeScript, eliminar `turbo.json` y las dependencias de Turbo para simplificar el proyecto. Si se van a usar, implementar al menos un package (`@valinor/shared`) con codigo real para validar el pipeline.
