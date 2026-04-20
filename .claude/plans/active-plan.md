# Active Plan — SYSCOP Sprint + Bio4 Demo

**Ultima actualizacion:** 2026-04-20
**Branch:** develop (master 92 commits behind)
**Foco:** GRO-15 SYSCOP (primer cliente pagante) + VAL-120 Bio4 Demo
**Deadlines:** GRO-15 → 2026-04-25 · VAL-120 → vencido (reagendar con Loren)

---

## Sprint SYSCOP — Camino critico

### Fase 1-5: CERRADAS
VAL-125 (Discovery v2) · VAL-131 (Runner standalone) · VAL-130 (Scheduling composable) — todos Done. Detalles en Session Log 2026-04-17/18.

### Pendientes activos SYSCOP

| Issue | Que | Due | Status | Owner |
|-------|-----|-----|--------|-------|
| GRO-17 | Creds SQL r/o `valinor_ro` + OK .exe de Gerardo | — | Todo | Loren→Gerardo |
| —      | Build físico `syscop_inventory.exe` (1h Windows host) | — | — | Nico |
| —      | Deploy remoto AnyDesk Tue 22 / Wed 23 | — | — | Nico + Gerardo |
| VAL-121 | Primer KO Report enviado exitosamente | Apr 25 | In Progress | Nico |
| GRO-15  | EPIC SYSCOP comercial (cierra con primer report en vivo) | Apr 25 | In Progress | Nico |

### Bloquea first-run (lunes 27 Abr 06:00)
**Solo GRO-17.** Todo el código está listo. Sin creds + OK de Gerardo no se puede deployar — escalado a Loren 2026-04-18.

---

## Sprint Bio4 Demo — VAL-120

### VAL-141: Sales Report v2 — LISTO PARA REVIEW

**Estado:** In Progress · PR #39 open (base develop) · 6 commits · +3520 / -131

**Entregables completos:**
- ✅ Pydantic `SalesReportV2` schema con 4 tiers de CustomerProfile, hero fields, next_actions
- ✅ 5 queries SQL parametrizadas con JOIN m_product_category real · confidence_factor + cadence_factor en recovery_potential
- ✅ Narrator LLM v2 system prompt alineado con schema (loss framing, HHI reconciliation, 4 script variants, UUID strip)
- ✅ React `SalesReportV2.tsx` con hero 44px rojo + NextActionsBlock + Magic Matrix heatmap
- ✅ Script `generate_sales_report_v2_gloria.py` — datos reales de Gloria sin LLM (1.928 clientes, HHI 290, 5 cuenta_top)
- ✅ Rutas demo: `/demo/sales-v2` (sample) y `/demo/sales-v2-gloria` (real)
- ✅ 3199/6 unit tests pass · test_pipeline_production 397s PASSED · TS clean

**Sub-issues audit trail:** VAL-152/153/154/155 Done · VAL-156 Backlog (Magic Matrix weighted gap para v3)

### Pendientes VAL-120 (post-merge PR #39)

- [ ] Review + merge PR #39 a develop
- [ ] Re-correr `test_pipeline_production` post-merge para capturar narrator LLM output v2-complete (run anterior emitió fallback por falta de wiring)
- [ ] Validación visual browser — `http://localhost:3000/demo/sales-v2-gloria`
- [ ] Screencast 3-5 min del reporte renderizado
- [ ] 10 talking points para demo
- [ ] Coordinar con Loren el agendamiento con Bio4 (due original 2026-04-18 pasó)

---

## No bloquean sprints activos

| Issue | Que | Due |
|-------|-----|-----|
| VAL-22 | Scale: load testing | Jul 31 |
| GRO-11 | YC application | Aug 1 |
| ANN-1 | Annatar Roadmap (otro proyecto) | — |
| VAL-156 | Magic Matrix weighted gap (v3) | — |

---

## Arquitectura relevante (descubierta)

### Sales Report v2 stack (VAL-141)
- **Schema:** `core/valinor/schemas/sales_report_v2.py` — SalesReportV2, ConcentrationReport con coerción de None, CustomerProfile enum (cuenta_top > account_grande > outlier > cuenta_media)
- **Queries:** `core/valinor/queries/sales_v2.py` — 5 builders parametrizados, `append_to_query_pack` wired en `build_queries`
- **Narrator:** `core/valinor/agents/narrators/sales.py` — emite JSON string-serialized, fallback schema-valid
- **Frontend:** `web/components/ko-report/SalesReportV2.tsx` + `web/app/demo/sales-v2*`

### Discovery Engine (VAL-125)
- `profiler.py` — SchemaProfiler → TableProfile, ColumnProfile
- `fk_discovery.py` — FKDiscovery (inclusion dependency, estadistico)
- `ontology_builder.py` — OntologyBuilder → EntityClassification
- `semantic_enricher.py` — SemanticColumnType enum
- `golden_dataset.py` + `benchmark.py` — ensemble baseline (gloria_full P=1.00 R=0.88 F1=0.93)

### Connectors (`shared/connectors/`)
- Base: `DeltaConnector(abc.ABC)` — connect(), execute_query(), get_schema()
- Factory: `ConnectorFactory.create(source_type, config)`
- Existentes: PostgreSQL, MySQL, SQLite, Etendo, MSSQL (VAL-122 done)

### Verticals (VAL-130)
- `core/valinor/verticals/` — registry + run_vertical + InventoryVertical (Haiku) + FinancialVertical (swarm)
- `core/valinor/notifications/` — NotificationRouter + Email/Webhook/WhatsApp adapters
- redbeat scheduler por (client, vertical) en `ClientProfile.schedule_config`

---

## Completado

### Sesion 2026-04-18/20 — Sales Report v2 (VAL-141)
- 6 commits en rama VAL-141 · PR #39 · +3520 / -131
- 8 fixes críticos de primera pasada (loss framing, reconciliation, recovery, categorías, MoM, scripts, UUIDs, next_actions)
- Segunda pasada: narrator LLM alineado, fallback robusto, 13 tests nuevos
- Tercera pasada: cuenta_top tier + cadence_factor (ISKAY correcta clasificación, EL CORTE recovery €29→€4.549)
- Audit trail VAL-152/153/154/155 Done · VAL-156 Backlog
- Detalle completo en Session Log — Dev (Linear docs)

### Sesion 2026-04-17/18 — SYSCOP Sprint Closure
- VAL-125, VAL-127/128/129, VAL-130 (4 capas), VAL-131 (runner), VAL-140 — todos Done
- PRs mergeados: #33, #34, #35, #36, #37
- 24 branches locales mergeadas borradas (28 → 4)
- GRO-17 actualizado (sin ODBC, solo creds + OK)

### Sesion 2026-04-15a — Setup + commit pendientes
- Committed: fix(infra,web) — PYTHONPATH worker, metric collision, null-safety 9 archivos frontend
- Committed: chore(docs) — plan + CLAUDE.md update
- Linear MCP conectado y funcional
- VAL-126 + VAL-122 movidos a In Progress
- Agentes lanzados en worktrees paralelos
