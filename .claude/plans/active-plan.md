# Active Plan — Validation & Merge to Main

**Ultima actualizacion:** 2026-04-10
**Branch:** develop

## Completado (sesiones anteriores)

### Epics cerradas
- **VAL-92/93**: Transparency Engine (backend + 3 capas frontend)
- **VAL-95**: Journey Wizard (onboarding → análisis → revelación)

### Issues completados
- **VAL-91**: Theme toggle dark/light + skeleton loading screens (PR #28)
- **VAL-97**: Confidence metadata en API response (PR #19)
- **VAL-104**: KO Report Revelation — count-up, trust badges, drill-down (PR #26)
- **VAL-105**: SSE/WebSocket real-time pipeline progress (PR #20)
- VAL-94, VAL-99, VAL-100, VAL-101, VAL-102, VAL-103, VAL-96 (dup), VAL-98 (dup)

### PRs mergeados a develop
#18-#28

## Sesión 2026-04-10

### Validación
- TypeScript: 14 errores → 0 (fixes en AnalysisProgress.tsx, AuditTrailPanel.tsx)
- Pytest: 3029 passed, 2 failed (e2e Gloria — requieren infra), 5 skipped
- Pendiente: PR develop → main

## En progreso

| Issue | Qué | Estado |
|-------|-----|--------|
| VAL-18 | CI/CD epic (Railway staging, auto-migration) | Partial |

## Backlog

| Issue | Qué | Due |
|-------|-----|-----|
| VAL-22 | Scale: load testing, zero-downtime, auto-scaling | Jul 31 |
| GRO-11 | YC application con métricas reales | Aug 1 |
| ANN-1 | Annatar roadmap & arquitectura | — |
