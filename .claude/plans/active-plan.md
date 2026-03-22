# Active Plan — Post Mega Sprint

**Última actualización:** 2026-03-22 (sesión vespertina)
**Branch:** develop
**PR #5:** MERGED

## Estado actual

### ✅ Completados (sprints anteriores + mega sprint)
- VAL-1, VAL-10, VAL-11, VAL-16, VAL-17, VAL-24, VAL-26
- VAL-28→34 (Arsenal Sprint)
- VAL-36, VAL-44, VAL-45, VAL-46 (grounded/v7)
- VAL-5 (audit — ya estaba hecho)
- VAL-48, VAL-49, VAL-50, VAL-51, VAL-52 (P0 Security + Infra)
- VAL-53, VAL-54, VAL-55, VAL-56, VAL-57 (P1 Quality)
- VAL-37, VAL-38, VAL-39, VAL-40, VAL-41, VAL-42, VAL-43 (Swarm Features)
- VAL-58, VAL-59, VAL-60, VAL-61 (Medium Quality)
- VAL-3, VAL-27, VAL-35 (UI/UX)
- VAL-2 (entity_map JSON schema formalizado con Pydantic)
- VAL-7 (E2E pipeline tests sobre Gloria — 5 tests)
- VAL-19 Fase 1 (Alembic migrations baseline)
- VAL-25 (Batch API provider — 50% cost savings)
- VAL-54 structlog + Redis mock + anthropic stub test fixes
- VAL-56 N+1 query batching (fk_discovery, cartographer, connectors)

### 🔄 En progreso
- VAL-23: Gestión de accesos — PARCIALMENTE RESUELTO. CI/CD workflows ya existen (tests, deploy, docker-build). Pendiente humano: verificar secrets en GitHub, Railway project/environments, Sentry, Slack webhooks, DNS, INFRASTRUCTURE.md
- VAL-20: Staging + CD — CD pipeline ya existe (deploy.yml → Railway + Vercel). Pendiente: approval gate para prod, Sentry SDK, health checks, smoke tests post-deploy

### ⏳ Backlog técnico pendiente
- VAL-20: Fase 2 Staging — CD pipeline existe, falta approval gate + Sentry + health checks (movido a En progreso)
- VAL-21: Fase 3 Multi-tenant RLS + observability
- VAL-22: Fase 4 Scale — load testing, zero-downtime
- VAL-25: Claude API Cost Optimization — prompt caching OK, falta Batch API
- VAL-7: Tests E2E pipeline completo sobre Gloria
- VAL-13: Client Portal shell
- VAL-15: Operator Dashboard

### ⏳ Backlog UI/GTM (necesitan producto + design)
- VAL-8: Demo mode sales tool
- VAL-12: Demo Mode UI branded
- VAL-14: Onboarding Wizard UI
- VAL-6: Self-serve onboarding (due: junio 30)

### ⏳ EPICs (contenedores)
- VAL-9: UI/UX Professionalization — sub-issues mayormente done
- VAL-18: CI/CD Infrastructure — fases 1-4 pendientes
- VAL-47: Hardening Post-Investigación — P0s done, P2s pendientes

### 🚫 No ejecutables por código
- VAL-4: Entregar diagnósticos (ops/gtm, due: abril 30)
- VAL-23: Gestión de accesos (humano)
- GRO-1→14: Growth team tasks (Lorenzo/equipo)

## Checkpoint

Última acción (2026-03-22 sesión completa — 7 commits):
- PR #5 merged
- VAL-56: N+1 query batching (fk_discovery, cartographer, connectors)
- VAL-54: structlog test fix + Redis mock fix + anthropic stub → ~200 tests recovered
- VAL-2: entity_map JSON schema formalizado (probed_values, Relationship model, validation)
- VAL-19: Alembic migrations inicializado con baseline
- VAL-7: 5 E2E pipeline tests sobre Gloria (query builder, baseline, agents, narrators, schema)
- VAL-25: Batch API provider (50% cost savings, 15 tests)

Commits: e17be26a → 40c9852a (7 commits)
Tests: ~900 passing por archivo individual (before: 0 por collection errors)

## Próximos pasos
1. VAL-20: Staging (Railway config)
2. VAL-21: Multi-tenant RLS + observability
3. Fix test collection order poisoning (sys.modules stub conflicts between files)
4. VAL-13: Client Portal shell
5. VAL-15: Operator Dashboard
