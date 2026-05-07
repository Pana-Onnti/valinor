# Active Plan — Sprint VAL-161 (Anti-Hallucination Wiring) shipped on branch

**Última actualización:** 2026-05-07
**Branch actual:** `nicolasbaseggiodev/val-161-anti-hallucination-integration` (4 commits sobre develop)
**Foco:** sprint terminado en branch — pendiente decidir merge a develop

---

## Sesión 2026-05-07 — VAL-161 closure on branch

**Duración:** sesión activa ~2h.

### Qué se hizo (en orden)

1. Reautoricé Linear MCP (token había expirado en sesión anterior).
2. Creé `VAL-161` (Urgent, In Progress) en team Valinor — "Wire Anti-Hallucination v1 (KG + VerificationEngine) into production pipeline".
3. Detecté WIP no documentado en working tree (sql_safety extract + KG path cache + confidence_scores hoist) — el usuario decidió commitearlo bajo VAL-161 como hotfix antes de arrancar.
4. Branch `nicolasbaseggiodev/val-161-anti-hallucination-integration` desde develop.
5. **Pasos 1–7 del plan ejecutados, 4 commits limpios sobre la branch:**
   - `0465713d` refactor(core/valinor): extract sql_safety + KG path cache (+38/-37, 5 archivos)
   - `b373d406` feat(valinor): wire SchemaKnowledgeGraph into prod pipeline (+38/-2, run.py + valinor_adapter.py)
   - `8f9ecb1f` feat(valinor): instantiate VerificationEngine and feed report to narrators (+71/-2, run.py + valinor_adapter.py)
   - `464ae07d` test(valinor): VAL-161 anti-hallucination wiring regression (+238, tests/test_anti_hallucination_wiring.py)
6. Suite completa verde en cada paso. Cierre: **3266 passed, 6 skipped (20:48)** — sin regresiones.
7. Memoria sincronizada: `project_anti_hallucination.md` reescrito al estado wired, `MEMORY.md` index sin cambios estructurales.

### Decisiones técnicas tomadas

- **WIP no documentado bajo VAL-161 como hotfix** (en lugar de issue separado). Razón: refactors chicos (sql_safety extract, KG path memoization, _CONFIDENCE_SCORES hoist), trazables al sprint, sin churn extra.
- **No tocar VAL-147/146/144 (paper)** ni ANN-1 mientras el sprint corre. Estado actual: siguen en *In Progress* en Linear pero el plan los marca pausados. Sincronizar Linear queda como TODO de cierre.
- **VerificationEngine pasa solo `(query_results, baseline, kg)`** — sin `connection_string`/`entity_map` opcionales (los acepta para active re-querying contra DB con timeout 5s, fuera de scope del sprint para mantener blast radius mínimo). Apertura para follow-up sprint.
- **SaaS sigue corriendo solo `narrate_executive`** — out of scope explícito del sprint. Los otros 3 narrators (CEO/Controller/Sales) ya aceptan `verification_report` en sus signatures, pero solo `run_narrators` (CLI) los invoca; en SaaS sigue una sola llamada directa a `narrate_executive`.

### Estado de la branch

- 4 commits ahead of develop, 0 behind. Hooks OK (flake8 + Refs: VAL-XX validados en cada commit).
- `web/tsconfig.tsbuildinfo` y `.claude/*` sin commitear (build artifact + local config).
- `.claude/plans/active-plan.md` (este archivo) modificado sin commit — se incluye en el último commit de cierre.

### Pendientes de cierre (esta sesión, antes del end-session)

1. Comment en `VAL-161` con resumen de los 4 commits + DoD checklist marcada.
2. Commit final con `.claude/plans/active-plan.md` y `MEMORY.md` (si cambió) → `chore(docs): VAL-161 sprint closure on branch`.
3. Decisión usuario: merge `nicolasbaseggiodev/val-161-anti-hallucination-integration → develop` (push directo a develop está OK por política, no requiere PR).
4. End-session.

### Blockers

- Ninguno actual. Linear conectado, tests verdes, branch limpia.

---

## Sprint plan (referencia, ya ejecutado)

### Objetivo
Integrar `knowledge_graph.py` + `verification.py` al pipeline de producción (CLI + SaaS) con narrators consumiendo el `verification_report` y el Number Registry como única fuente de números monetarios.

### Pasos completados

- [x] **Paso 1** — KG construido después del Cartographer en CLI y SaaS, shape logueada (`tables`/`edges`/`concepts`).
- [x] **Paso 2** — `kg=kg` propagado a `run_analysis_agents()`. Analyst/Sentinel/Hunter ya inyectaban `kg.to_prompt_context()` en sus prompts.
- [x] **Paso 3** — `VerificationEngine(query_results, baseline, kg)` instanciado como Stage 3.6 (post-reconciliación, pre-narrators) en CLI y SaaS.
- [x] **Paso 4** — `verification_report=verification_report` pasado a `run_narrators` (CLI) y `narrate_executive` (SaaS). Los 4 narrators ya inyectaban `to_prompt_context()` como "NUMBER REGISTRY — USE ONLY THESE VALUES".
- [x] **Paso 5** — Number Registry como única fuente: cubierto implícitamente por Paso 4 (los 4 narrators ya leen del registry vía `to_prompt_context()`).
- [x] **Paso 6** — `tests/test_anti_hallucination_wiring.py`: 4 tests verdes — 2 static checks + 1 KG sanity + 1 functional Gloria regression ($13.5M / 4854 → not VERIFIED, registry anchored on $3.27M / 616).
- [x] **Paso 7** — Memoria sincronizada (`project_anti_hallucination.md` → wired). Plan en este archivo. Falta solo end-session.

### Definition of done

- [x] KG construido en cada run (visible en `run_log["stages"]["knowledge_graph"]` y `results["stages"]["knowledge_graph"]`)
- [x] VerificationReport con `total_claims > 0` en runs reales (vía Stage 3.6)
- [x] `verification_report.to_prompt_context()` en prompts de los 4 narrators (ya implementado, ahora alimentado)
- [x] Test regresión Gloria pasa (`test_anti_hallucination_wiring.py`)
- [x] `pytest tests/ -v` pasa completo (3266 passed, 6 skipped)
- [x] Memoria sincronizada

### Out of scope (siguen como follow-up)

- Active re-querying contra DB en VerificationEngine (acepta `connection_string`/`entity_map` pero no los pasamos en este sprint).
- SaaS corriendo los 4 narrators (sigue solo Executive — issue separado si surge).
- Performance tuning del KG/Verification.
- Sincronizar paper issues (VAL-147/146/144) y ANN-1 con el pivot 2026-04-29 — TODO al volver a esos tracks.

---

## Otros hallazgos del audit 2026-04-27 (queue, no este sprint)

- Backend: 50 findings en `/tmp/valinor-backend-findings.md` (5 críticos: race demo cache, exception swallowing, hexagonal violation `data_quality_gate.py:174`, DQ degrada exceptions a WARNING, bare except verification.py:1207)
- Frontend: 22 findings en `/tmp/valinor-frontend-findings.md` (5 críticos: untyped API, stale closure polling, JWT plain en localStorage, FileUpload a11y, ErrorBoundary mistype)
- Doc-vs-code: 12 gaps en `/tmp/valinor-backend-architecture.md`
- Decisiones recientes: 57 en `/tmp/valinor-recent-decisions.md`

## Sprints relacionados (suspendidos, sin cambios)

- Sprint SYSCOP: blockeado por creds Gerardo
- Sprint Paper (VAL-144/146/147): vive en repo `d4c-paper/` no presente local
