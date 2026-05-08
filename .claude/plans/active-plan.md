# Active Plan — VAL-161 closed (claim downgraded), branch ready to merge

**Última actualización:** 2026-05-07 (cierre de sesión)
**Branch actual:** `nicolasbaseggiodev/val-161-anti-hallucination-integration` (6 commits ahead de develop, 0 behind)
**Foco:** sprint cerrado en branch, listo para mergear a develop

---

## Sesión 2026-05-07 (cont.) — VAL-161 production test fix + adversarial validation

**Duración:** ~3h sumando ambas mitades.

### Qué se hizo

1. **Auditoría del cierre previo**: el production test (`tests/test_pipeline_production.py`) reconstruía el pipeline a mano stage por stage pero **no ejercitaba el wiring de VAL-161**: pasaba `verification_report=None` y `kg=None` hardcoded. Hubiera pasado idéntico aunque borraras los 5 commits previos del sprint.
2. **Fix surgical** del test (commit `bc12e610`): agregadas Stage 1.6 (KG) y Stage 3.6 (VerificationEngine) en posición canónica; `kg=kg` propagado a `run_analysis_agents`; `verification_report` propagado a `run_narrators`; assertions sobre `kg.tables > 0`, `verification.total_claims > 0`, registry no-vacío. Output JSON ampliado con stats de KG y verification. Docs alineadas (`docs/TESTING.md` + `.claude/skills/production-test/SKILL.md` agregan Stages 1.6 y 3.6).
3. **Run real contra Gloria PG (513s, PASSED)**: KG 7 tablas / 3 edges / 6 concepts; Verification 33 claims (19 VERIFIED / 14 UNVERIFIABLE / 0 FAILED); registry 6 entradas inyectado en los 4 narrators.
4. **VAL-162 creado** (priority High, Backlog): timeouts del proxy (analyst CLI 300s) + narrators (controller+sales 180s). Pre-existentes a VAL-161, expuestos al ejercitar el wiring.
5. **Audit adversarial**: agente skeptical comparando outputs PRE (2026-04-20) vs POST (2026-05-07). Smoking gun: las 5 queries que aparecen "nuevas y grounded" en POST (`churn_risk_scoring`, `concentration_hhi`, `concentration_top_customers`, `cross_sell_matrix`, `rfm_segmentation`) son atribuibles a **VAL-141 fixes**, no a VAL-161. PRE CEO ya retractaba con fraseo equivalente al POST. **Claim de "VAL-161 mejora calidad anti-hallucination en runs reales" downgraded a "wiring entregado y verificado; delta marginal sin medir aún".**
6. **Decision Log entry** registrada (2026-05-07 — VAL-161 closure, claim downgraded).
7. **VAL-161 comment** con resumen ejecutivo del cierre.

### Decisiones técnicas tomadas

- **Honestar el claim de VAL-161** en vez de venderlo. El sprint entrega plumbing, no quality improvement comprobable en runs reales. Engineering theater evitado.
- **VAL-162 como issue separado**, no como hotfix dentro de VAL-161. Los timeouts son pre-existentes y mezclar tuning de infra con anti-hallucination wiring rompe trazabilidad.
- **VAL-163 como candidato** (no creado aún): A/B controlado del Number Registry sobre los mismos `findings`/`query_results` (con y sin `verification_report`). Ese sería el sprint que justifica la afirmación cualitativa.
- **`tests/test_pipeline_production.py` queda como "main test"** del pipeline de producción, ejercitando ahora todas las stages.

### Estado del branch

- 6 commits ahead de develop, 0 behind:
  - `0465713d` refactor sql_safety + KG path cache
  - `b373d406` wire SchemaKnowledgeGraph into prod pipeline
  - `8f9ecb1f` instantiate VerificationEngine + feed narrators
  - `464ae07d` test anti-hallucination wiring regression (sintético)
  - `0aad7b40` chore docs VAL-161 sprint closure
  - `bc12e610` test production test exercises wired KG+verification (commit del cierre)
- Hooks OK en cada commit (Refs: VAL-161 validado).
- Suite completa al cierre de sesión: corriendo en background, **62% verde, sin fallos, solo skips esperados** (`test_pipeline_periods` 3 OK, `test_pipeline_integration` 100% OK, `test_narrators` OK).
- Working tree limpio salvo artifacts esperados (`web/tsconfig.tsbuildinfo`, `.claude/hooks/`, `.claude/scheduled_tasks.lock`, `.claude/settings.json`, `.claude/skills/karpathy-guidelines/`).

---

## Pendientes próxima sesión

1. **Verificar suite completa verde al final del run en background.** El log vive en `/tmp/val161_full_suite.log`. Confirmar 0 fallos antes de mergear.
2. **Mergear `nicolasbaseggiodev/val-161-anti-hallucination-integration → develop`** (push directo OK por política del 2026-04-24). Cerrar VAL-161 en Linear.
3. **Decidir VAL-163 (A/B controlado)**: si vale la pena medir el delta marginal del Number Registry, crear el issue. Si no, el closure de VAL-161 queda como está.
4. **Decidir prioridad de VAL-162** vs el siguiente issue urgent del backlog (GRO-15 SYSCOP, VAL-121 Gerardo, GRO-11 YC application).

---

## Backlog próximo (sin cambios desde sesión anterior)

### Urgent / High

- **VAL-162** (creado hoy, High): timeouts pipeline (analyst CLI 300s + narrators 180s).
- GRO-15 / VAL-121 (Urgent): SYSCOP Inventory Agent — blockeado por creds Gerardo.
- GRO-11 (Urgent): YC application (deadline 2026-08-01, plenty time).

### Paper (Medium, suspendidos)

- VAL-147 / VAL-146 / VAL-144: viven en repo `d4c-paper/` no presente local. Sincronizar Linear queda como TODO de cierre.
- ANN-1: Annatar roadmap, pausado.

### Out of scope (siguen como follow-up de VAL-161)

- A/B controlado real del Number Registry (candidato VAL-163).
- Active re-querying contra DB en VerificationEngine (acepta `connection_string`/`entity_map` pero no se pasan).
- SaaS corriendo los 4 narrators (sigue solo Executive — issue separado si surge).
- Performance tuning del KG/Verification (no es bottleneck actual).

---

## Hallazgos del audit 2026-04-27 (queue, no este sprint)

- Backend: 50 findings en `/tmp/valinor-backend-findings.md` (5 críticos: race demo cache, exception swallowing, hexagonal violation `data_quality_gate.py:174`, DQ degrada exceptions a WARNING, bare except verification.py:1207)
- Frontend: 22 findings en `/tmp/valinor-frontend-findings.md` (5 críticos: untyped API, stale closure polling, JWT plain en localStorage, FileUpload a11y, ErrorBoundary mistype)
- Doc-vs-code: 12 gaps en `/tmp/valinor-backend-architecture.md`
