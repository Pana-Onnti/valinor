# Active Plan — Post Mega Sprint

**Última actualización:** 2026-03-22 (sesión nocturna, continuación)
**Branch:** develop + val-21 branch

## Estado actual

### ✅ Completados (sprints anteriores + mega sprint + esta sesión)
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
- VAL-20 (Staging + CD — Railway + Vercel deploy pipeline completo)
- VAL-23 (Gestión de accesos — infra ya configurada, verificado en Linear KB)
- VAL-51 CI fix: 28 test failures resolved, 2975/2975 passing

### 🔄 En progreso
- VAL-21: Multi-tenant RLS — branch pusheado, PR pendiente
  - ✅ Alembic migration: tenant_id + RLS en 7 tablas
  - ✅ TenantMiddleware + get_tenant_id dependency
  - ✅ Agent observability con tenant context
  - ✅ 13 tests de aislamiento multi-tenant
  - ⏳ Pendiente: PgBouncer (nice-to-have), E2E tests con Gloria Docker

### ⏳ Backlog técnico pendiente
- VAL-22: Fase 4 Scale — load testing, zero-downtime
- VAL-13: Client Portal shell
- VAL-15: Operator Dashboard
- Fix test collection order poisoning (sys.modules stub conflicts between files)

### ⏳ Backlog UI/GTM (necesitan producto + design)
- VAL-8: Demo mode sales tool
- VAL-12: Demo Mode UI branded
- VAL-14: Onboarding Wizard UI
- VAL-6: Self-serve onboarding (due: junio 30)

### ⏳ EPICs (contenedores)
- VAL-9: UI/UX Professionalization — sub-issues mayormente done
- VAL-18: CI/CD Infrastructure — fases 1-2 done, fase 3 en progreso
- VAL-47: Hardening Post-Investigación — P0s done, P2s pendientes

### 🚫 No ejecutables por código
- VAL-4: Entregar diagnósticos (ops/gtm, due: abril 30)
- GRO-1→14: Growth team tasks (Lorenzo/equipo)

## Checkpoint

Última acción (2026-03-22 sesión nocturna, continuación — 2 commits):
1. fix(test): 28 CI test failures resolved
   - Mock targets corregidos (run_analysis_task, agent_query)
   - Query builder tests: entities faltantes agregadas
   - Cartographer: SQLite dialect-aware SQL
   - Duck typing (hasattr) en lugar de isinstance en 9 agent modules
   - 2975 tests passing, 0 failures
2. feat(infra): Multi-tenant RLS + TenantMiddleware + observability (VAL-21)
   - Alembic migration con RLS policies
   - api/tenant.py: middleware + dependency + db context helper
   - Observability: tenant_id en spans y logs
   - 13 tests de multi-tenant aislamiento

Commits: dab77366 (develop) + 3abeb3c1 (val-21 branch)

## Próximos pasos
1. Crear PR para VAL-21 branch → develop
2. VAL-13: Client Portal shell
3. VAL-15: Operator Dashboard
4. VAL-22: Scale — load testing
