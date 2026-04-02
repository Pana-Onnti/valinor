# Active Plan — Post V3, Road to YC

**Ultima actualizacion:** 2026-03-23
**Branch:** develop

## Estado actual — Todo cerrado

### ✅ Sesión 2026-03-23
- **VAL-65**: Schema-aware DQ Gate (Done)
- **VAL-66**: Schema-aware Cartographer + entity mapping (Done)
- **VAL-89**: Alembic 003 applied + `_uploads_registry` → PostgreSQL (Done)
- **VAL-8**: Demo mode: copy link, OG tags, mobile grid (Done)
- **VAL-4**: Diagnósticos pagados (Done, no dev)
- **VAL-14**: Onboarding Wizard: AnalysisProgress wired to step 5 (Done)
- Test fix: `gate_cartographer` fixtures con `type` field (Done)

### ✅ Sprint V3 — File Ingestion (VAL-82 epic, todo Done)
- VAL-83→89 completados

### ✅ Sprints anteriores
- VAL-1→61, VAL-65→67 (todo Done)

## Roadmap: 4 sprints hasta YC (Aug 1)

| Sprint | Plan | Issues | Esfuerzo | Semana |
|--------|------|--------|----------|--------|
| **1. Bugs + Security** | `sprint-bugs-security.md` | VAL-68 epic (13 issues) | 5 días | Próximo |
| **2. CI/CD Remaining** | `sprint-cicd-remaining.md` | VAL-18 gaps (5 tareas) | 3-4 días | Después de Sprint 1 |
| **3. Product Features** | `sprint-product-features.md` | VAL-62, 63, 64 | 8-10 días | Paralelo con Sprint 2 |
| **4. Scale + YC App** | `sprint-yc-application.md` | VAL-22 + GRO-11 | Semana 9-18 | Jun-Jul |

### CI/CD — Estado real (auditoría 2026-03-23)
- Phase 1 Foundation: **DONE** (tests, lint, Docker build)
- Phase 2 Staging+CD: **50%** (prod deploy OK, falta staging)
- Phase 3 Observability: **DONE** (Prometheus, Loki, Grafana, Sentry)
- Phase 4 Scale: **60%** (Alembic OK, falta load testing + auto-scaling)

## Próximo paso
Arrancar Sprint 1 (Bugs + Security). P0 crashers primero (VAL-69, VAL-71).
