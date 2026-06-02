# 12 — Packages & Monorepo Structure

> Fecha: 2026-03-22
> Scope: `packages/`, `apps/`, root config (`turbo.json`, `tsconfig.json`, `package.json`)

---

## 1. Resumen

Valinor SaaS v2 es un monorepo gestionado con **npm workspaces + Turborepo** que contiene **7 paquetes** (`packages/*`) y **3 aplicaciones** (`apps/*`), con un tercer workspace `tools/*` declarado pero actualmente vacío. El monorepo usa TypeScript 5.3 con target ES2022, Vitest como test runner universal, y un pipeline de build topológico orquestado por Turbo.

**Estado actual**: Los paquetes son mayoritariamente esqueletos (scaffolding). Solo `@valinor/shared` tiene código fuente real (`src/`). Los demás 6 paquetes y las 3 apps solo contienen `package.json` sin directorios `src/`, `tsconfig.json` propios (excepto `shared`), ni código implementado. El sistema productivo real corre sobre Python/FastAPI (ver `docs/ARCHITECTURE.md`), no sobre este monorepo TypeScript.

---

## 2. Paquetes

### 2.1 `@valinor/shared` (packages/shared)
- **Rol**: Tipos compartidos, schemas Zod, utilidades, constantes.
- **Dependencias externas**: `zod ^3.22`, `date-fns ^2.30`.
- **Dependencias internas**: Ninguna (hoja del grafo).
- **Estado**: Tiene `src/index.ts` y `src/types/index.ts` con ~250 lineas de tipos bien definidos: `User`, `Client`, `AnalysisJob`, `EntityMap`, `Finding`, `Report`, `DatabaseConnection`, `AgentContext`, `ApiResponse`, `WebhookEvent`, etc. Exporta sub-paths: `./types`, `./schemas`, `./utils`.
- **Tiene tsconfig.json propio**: Si (extiende el root, `outDir: dist`, `declaration: true`).

### 2.2 `@valinor/core` (packages/core)
- **Rol**: Logica de negocio, conectores de BD, utilidades.
- **Dependencias externas**: `pg ^8.11`, `mysql2 ^3.6`, `tedious ^16.6` (MSSQL), `ssh2 ^1.15`, `zod ^3.22`, `nanoid ^5.0`.
- **Dependencias internas**: `@valinor/shared`.
- **Sub-paths exportados**: `./database`, `./ssh`, `./auth`.
- **Estado**: Solo `package.json`. Sin codigo fuente.

### 2.3 `@valinor/agents` (packages/agents)
- **Rol**: Agentes Claude AI para analisis de bases de datos.
- **Dependencias externas**: `@anthropic-ai/sdk ^0.20`, `claude-agent-sdk ^1.0`, `openai ^4.20`.
- **Dependencias internas**: `@valinor/core`, `@valinor/shared`.
- **Sub-paths exportados**: `./cartographer`, `./analyst`, `./sentinel`, `./hunter`, `./narrator`, `./orchestrator` -- 6 agentes nombrados.
- **Estado**: Solo `package.json`. Sin codigo fuente.

### 2.4 `@valinor/api` (packages/api)
- **Rol**: API REST y logica de negocio server-side.
- **Dependencias externas**: `hono ^3.12`, `@hono/node-server ^1.8`, `cors`, `helmet`, `compression`, `morgan`, `express-rate-limit`, `jsonwebtoken`, `bcryptjs`.
- **Dependencias internas**: `@valinor/core`, `@valinor/shared`, `@valinor/agents`.
- **Estado**: Solo `package.json`. Sin codigo fuente. Mezcla middlewares de Express (cors, helmet, morgan) con Hono -- posible inconsistencia.

### 2.5 `@valinor/workers` (packages/workers)
- **Rol**: Procesadores de jobs en background, colas.
- **Dependencias externas**: `bullmq ^4.15`, `ioredis ^5.3`, `cron ^3.1`.
- **Dependencias internas**: `@valinor/core`, `@valinor/shared`, `@valinor/agents`.
- **Sub-paths exportados**: `./analysis`, `./report`, `./notification`.
- **Estado**: Solo `package.json`. Sin codigo fuente.

### 2.6 `@valinor/web` (packages/web)
- **Rol**: Frontend Next.js para usuarios finales.
- **Dependencias externas**: `next ^14`, `react ^18.2`, Radix UI (alert-dialog, button, dropdown-menu, label, select, toast), Tailwind, Headless UI, Heroicons, Lucide, `swr`, `axios`, `react-hook-form`, `zod`.
- **Dependencias internas**: `@valinor/shared`.
- **Marcado**: `private: true`.
- **Estado**: Solo `package.json`. Sin codigo fuente.

### 2.7 `@valinor/infra` (packages/infra)
- **Rol**: Infrastructure as Code con Pulumi.
- **Dependencias externas**: `@pulumi/pulumi ^3.96`, `@pulumi/cloudflare ^5.15`, `@pulumi/github ^5.25`, `@pulumi/random ^4.14`.
- **Dependencias internas**: Ninguna.
- **Marcado**: `private: true`.
- **Estado**: Solo `package.json`. Sin codigo fuente.

---

## 3. Aplicaciones (`apps/`)

### 3.1 `@valinor/api-gateway` (apps/api-gateway)
- **Rol**: API Gateway en Cloudflare Workers.
- **Dependencias internas**: `@valinor/shared`.
- **Dependencias externas**: `hono ^3.12`, `@hono/zod-validator`, `zod`, `@supabase/supabase-js ^2.38`.
- **Infra**: `wrangler.toml` configura KV (cache), R2 (storage de reports), Queues (analysis), 3 envs (dev/staging/prod). Supabase para auth/DB.
- **Estado**: Solo `package.json` + `wrangler.toml`. Sin codigo fuente.

### 3.2 `@valinor/dashboard` (apps/dashboard)
- **Rol**: Dashboard admin (Next.js en puerto 3001).
- **Dependencias internas**: `@valinor/shared`.
- **Dependencias externas**: `next ^14`, React, Tremor (charts), Recharts, Tailwind.
- **Estado**: Solo `package.json`. Sin codigo fuente.

### 3.3 `@valinor/worker-runner` (apps/worker-runner)
- **Rol**: Runner de GitHub Actions para procesamiento de analisis.
- **Dependencias internas**: `@valinor/core`, `@valinor/shared`, `@valinor/agents`, `@valinor/workers`.
- **Dependencias externas**: `@actions/core ^1.10`, `@actions/github ^6.0`, `dotenv`.
- **Estado**: Solo `package.json`. Sin codigo fuente.

---

## 4. Dependencias Internas (Grafo)

```
@valinor/shared          (hoja - sin dependencias internas)
    ^
    |
@valinor/core            (depende de: shared)
    ^
    |
@valinor/agents          (depende de: core, shared)
    ^
    |
+---+---+---+
|       |   |
api  workers |
|       |   |
+---+---+   |
    |       |
    v       v
worker-runner

api-gateway --> shared
dashboard   --> shared
web         --> shared
infra       --> (ninguna)
```

**Grafo completo de dependencias workspace:**

| Paquete/App | Depende de |
|---|---|
| `@valinor/shared` | -- |
| `@valinor/core` | shared |
| `@valinor/agents` | core, shared |
| `@valinor/api` | core, shared, agents |
| `@valinor/workers` | core, shared, agents |
| `@valinor/web` | shared |
| `@valinor/infra` | -- |
| `@valinor/api-gateway` | shared |
| `@valinor/dashboard` | shared |
| `@valinor/worker-runner` | core, shared, agents, workers |

**Orden topologico de build**: shared -> core -> agents -> [api, workers, web, infra, api-gateway, dashboard] -> worker-runner

---

## 5. Build System (Turborepo)

### Configuracion (`turbo.json`)
- **Schema**: Turbo v1.11 con `pipeline` (no `tasks` -- formato pre-v2).
- **Global dependencies**: `**/.env.*local`.
- **Outputs cacheados**: `.next/**`, `dist/**`, `build/**`, `.wrangler/**`, `coverage/**`.

### Pipelines

| Task | dependsOn | Cache | Notas |
|---|---|---|---|
| `build` | `^build` (topologico) | Si | Outputs: .next, dist, build, .wrangler |
| `dev` | -- | No | `persistent: true` |
| `test` | `build` | Si | Inputs filtrados a `src/**`, `test/**` |
| `test:integration` | `build` | Si | |
| `test:e2e` | `build` | Si | |
| `lint` | `^build` | Si (sin outputs) | |
| `typecheck` | `^build` | Si (sin outputs) | |
| `format` | -- | Si (sin outputs) | |
| `clean` | -- | No | |
| `deploy:staging` | `build`, `test` | Si | |
| `deploy:production` | `build`, `test`, `test:integration` | Si | |
| `db:migrate` | -- | No | |
| `db:seed` | -- | No | |
| `postinstall` | -- | No | |

### TypeScript Root (`tsconfig.json`)
- **Target**: ES2022, module ESNext, moduleResolution bundler.
- **Strict mode**: Habilitado.
- **Path aliases**: `@valinor/shared`, `@valinor/core`, `@valinor/agents`, `@valinor/api`, `@valinor/workers` mapeados a `./packages/*/src`.
- **Project references**: 7 packages + 3 apps (10 total).
- **Plugin Next.js**: Configurado en root (solo aplica a web/dashboard).

---

## 6. Fortalezas

1. **Arquitectura bien planificada**: El grafo de dependencias es limpio y aciciclico. `shared` como hoja, `core` como capa intermedia, `agents/api/workers` como consumidores. Respeta la separacion hexagonal declarada en CLAUDE.md.

2. **Nombres de dominio expresivos**: Los 6 sub-agentes (cartographer, analyst, sentinel, hunter, narrator, orchestrator) mapean directamente al pipeline Valinor documentado en ARCHITECTURE.md.

3. **Multi-runtime preparado**: Cloudflare Workers (api-gateway), Node.js (api, workers, worker-runner), Next.js (web, dashboard). La separacion en apps/ vs packages/ es correcta.

4. **Sub-path exports**: Los paquetes usan `exports` con paths granulares (`@valinor/agents/cartographer`, `@valinor/core/database`), permitiendo tree-shaking e imports selectivos.

5. **Deploy pipeline robusto**: `deploy:production` depende de `build + test + test:integration`, obligando a pasar tests antes de deploy. Staging solo requiere `build + test`.

6. **Infraestructura como paquete**: `@valinor/infra` con Pulumi para Cloudflare y GitHub, dentro del mismo monorepo.

7. **Tipos compartidos bien modelados**: `@valinor/shared` tiene ~250 lineas de tipos que cubren el modelo de dominio completo (User, Client, AnalysisJob, Finding, Report, DatabaseConnection, AgentContext, WebhookEvent).

8. **Workspace protocol**: Usa `workspace:*` para dependencias internas, asegurando resolucion local.

---

## 7. Debilidades

1. **Monorepo esqueleto -- zero codigo real**: Solo `@valinor/shared/src/types/index.ts` tiene codigo implementado. Los otros 9 paquetes/apps son solo `package.json`. No hay un solo test, ni un handler de API, ni un agente implementado en TypeScript. El sistema productivo real es Python/FastAPI/Celery.

2. **Dualidad Python-TypeScript sin resolver**: El `ARCHITECTURE.md` documenta FastAPI + Celery + Redis como stack real. Este monorepo TS es un plan futuro que no ha arrancado. Hay riesgo de divergencia entre tipos Python y tipos TS.

3. **Turbo v1 pipeline syntax**: Usa `pipeline` en vez de `tasks` (formato de Turbo v2+). Turbo ^1.11 funciona, pero ya esta deprecado. Deberia migrar antes de que Turbo v1 pierda soporte.

4. **Inconsistencia en @valinor/api**: Mezcla Hono (framework moderno para edge) con middlewares Express clasicos (cors, helmet, morgan, compression, express-rate-limit). Estos no son compatibles entre si -- Hono tiene sus propios middlewares equivalentes.

5. **Duplicacion de apps frontend**: `@valinor/web` (packages/) y `@valinor/dashboard` (apps/) son ambos Next.js con dependencias casi identicas (Tailwind, Headless UI, react-hook-form, zod, swr, axios). Dashboard agrega Tremor/Recharts. La separacion es semantica pero hay alto overlap.

6. **No hay tsconfig.json por paquete**: Solo `@valinor/shared` tiene su propio `tsconfig.json`. Los demas 6 packages y 3 apps no lo tienen, lo cual impedira que `tsc` funcione correctamente en ellos (sus scripts de build son `tsc`).

7. **workspace `tools/*` declarado pero vacio**: El directorio ni siquiera existe. Genera ruido en la configuracion.

8. **`shared/src/index.ts` exporta modulos que no existen**: Exporta de `./schemas`, `./utils`, `./constants` pero solo existe `./types`. Los builds fallaraan.

9. **No hay `node_modules/` ni lock file visible**: No se evidencia `package-lock.json` ni que se hayan instalado dependencias, lo que implica que el monorepo nunca se ha bootstrapped.

10. **Path aliases en root tsconfig duplican workspace resolution**: Los paths `@valinor/*` estan mapeados tanto via `workspace:*` (npm) como via `paths` (tsconfig). Esto puede causar discrepancias si las resoluciones divergen.

11. **`@valinor/web` deberia estar en `apps/`**: Semanticamente es una aplicacion deployable (Next.js), no una libreria reutilizable. Esta en `packages/` pero marcada `private: true`, inconsistente con el patron del repo.

---

## 8. Recomendaciones 2026

### Prioridad Alta

1. **Decidir Python vs TypeScript**: El monorepo TS es aspiracional. El sistema real es Python. Antes de invertir en implementar los paquetes TS, definir si la migracion es real o si este scaffolding deberia archivarse. Si se mantiene, crear un plan de migracion incremental con milestones claros.

2. **Arreglar `@valinor/shared` antes de que rompa**: Eliminar o implementar las exportaciones `./schemas`, `./utils`, `./constants` que `src/index.ts` referencia pero no existen. Actualmente cualquier `turbo build` fallara.

3. **Agregar `tsconfig.json` a cada paquete**: Sin el, los scripts `"build": "tsc"` de los 6 paquetes restantes no compilaran. Crear un `tsconfig.base.json` root y que cada paquete extienda con su `outDir`/`rootDir`.

4. **Mover `@valinor/web` a `apps/web`**: Alinear con la convencion del repo donde las aplicaciones deployables viven en `apps/`.

### Prioridad Media

5. **Migrar Turbo pipeline a tasks**: Actualizar `turbo.json` al formato v2 (`"tasks"` en vez de `"pipeline"`). El formato actual funcionara hasta que Turbo v1 se discontinue.

6. **Limpiar dependencias de `@valinor/api`**: Reemplazar middlewares Express (cors, helmet, morgan, compression) por equivalentes de Hono (`@hono/cors`, `@hono/secure-headers`, etc.), o cambiar Hono por Express.

7. **Eliminar workspace `tools/*`**: No existe. Remover de `package.json` root, o crearlo si hay plan concreto.

8. **Sincronizar tipos Python ↔ TS**: Si ambos stacks coexistiran, implementar generacion automatica de tipos (e.g., pydantic2ts, openapi-typescript) para que `@valinor/shared` se genere desde los schemas Pydantic del backend Python.

### Prioridad Baja

9. **Unificar frontends**: Evaluar si `@valinor/web` y `@valinor/dashboard` deberian ser una sola app Next.js con route groups (`/dashboard/...`) en vez de dos apps separadas con dependencias duplicadas.

10. **Agregar Changesets o similar**: Para versionado coordinado de los paquetes publicables (`shared`, `core`, `agents`, `workers`).

11. **Implementar CI**: No hay `.github/workflows/` que ejecute el pipeline Turbo. El `worker-runner` depende de GitHub Actions pero no hay workflow definido.

12. **Considerar pnpm**: El monorepo usa npm workspaces con `workspace:*` protocol (que es nativo de pnpm/yarn, no npm). Migrar a pnpm mejoraria performance y el soporte nativo del protocolo `workspace:*`.

---

## Diagrama Resumen

```
valinor-saas/
├── package.json          # npm workspaces: packages/*, apps/*, tools/*
├── turbo.json            # Turborepo v1 pipeline config
├── tsconfig.json         # Root TS config con path aliases y project refs
│
├── packages/
│   ├── shared/           # Tipos + schemas + utils (UNICO CON CODIGO)
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── index.ts
│   │       └── types/index.ts
│   │
│   ├── core/             # BD connectors, logica negocio (SCAFFOLDING)
│   ├── agents/           # 6 agentes AI (SCAFFOLDING)
│   ├── api/              # REST API Hono (SCAFFOLDING)
│   ├── workers/          # BullMQ jobs (SCAFFOLDING)
│   ├── web/              # Next.js frontend (SCAFFOLDING, deberia ir en apps/)
│   └── infra/            # Pulumi IaC (SCAFFOLDING)
│
├── apps/
│   ├── api-gateway/      # CF Workers gateway (SCAFFOLDING + wrangler.toml)
│   ├── dashboard/        # Next.js admin (SCAFFOLDING)
│   └── worker-runner/    # GH Actions runner (SCAFFOLDING)
│
└── tools/                # NO EXISTE (declarado en workspaces)
```
