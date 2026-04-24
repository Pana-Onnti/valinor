# Active Plan — SYSCOP Sprint + Bio4 Demo

**Ultima actualizacion:** 2026-04-21
**Branch actual:** nicolasbaseggiodev/val-158-sales-v2-dynamic-demo (2 commits ahead de develop)
**Foco:** GRO-15 SYSCOP (primer cliente pagante) + VAL-120 Bio4 Demo
**Deadlines:** GRO-15 → 2026-04-25 · VAL-120 → reagendar con Loren

---

## PRs abiertos (merge order)

| PR | Scope | Base | Status | Checks |
|----|-------|------|--------|--------|
| #40 | VAL-157 — sales_v2 queries fix (post-merge VAL-141) | develop | CLEAN | ✅ 3/3 |
| #41 | VAL-158 — dynamic demo (period picker + animated pipeline) | **#40** (stacked) | CLEAN | pendiente CI |

**Orden de merge:** #40 → develop primero, luego #41 rebasea sola.

---

## Sprint SYSCOP — Camino crítico

### Fase 1-5: CERRADAS
VAL-125 · VAL-131 · VAL-130 — todos Done.

### Pendientes activos SYSCOP

| Issue | Que | Due | Status | Owner |
|-------|-----|-----|--------|-------|
| GRO-17 | Creds SQL r/o `valinor_ro` + OK .exe de Gerardo | — | Todo | Loren→Gerardo |
| —      | Build físico `syscop_inventory.exe` (1h Windows host) | — | — | Nico |
| —      | Deploy remoto AnyDesk Tue 22 / Wed 23 | — | — | Nico + Gerardo |
| VAL-121 | Primer KO Report enviado exitosamente | Apr 25 | In Progress | Nico |
| GRO-15 | EPIC SYSCOP comercial | Apr 25 | In Progress | Nico |

**Bloquea first-run (2026-04-27 06:00):** solo GRO-17. Código listo, esperando creds+OK.

---

## Sprint Bio4 Demo — VAL-120

### VAL-141: Sales Report v2 — DONE (mergeado 2026-04-20)
PR #39 merged a develop · 7 commits · +3520 / -131 · cerrado en Linear.

### VAL-157: Post-merge follow-up — PR #40 ABIERTO

3 bugs descubiertos por production test contra Gloria:
- ✅ Semantic keys `customer_fk` / `amount_col` / `pk` (Cartographer canonical)
- ✅ `_base_filter` prefija ` AND ` (tolerant con legacy AND prefix)
- ✅ 3 queries con JOIN múltiple reworked (CTE invoices_filtered evita ambigüedad `isactive`)
- ✅ Schema: `NextAction.impact_eur` valida `None → 0.0`

**Validación:**
- 29/29 unit tests pass
- 13/13 queries contra Gloria (vs 8/13 pre-fix)
- Narrator LLM post-fix SIN validar — Stage 3 del test falló con `claude CLI error (exit 1)` transitorio (contención con Claude Code session, NO regresión). Re-run necesario cuando CLI esté libre.

### VAL-158: Dynamic demo — PR #41 ABIERTO

Demo path que se siente flow real sin arriesgar el CLI en vivo.

**3 fases:**
- `idle` — period selector (6m / 12m / 24m) + CTA "Ejecutar diagnóstico"
- `loading` — `PipelineProgress` con 9 stages animados (~14s cold, ~5s switch)
- `ready` — `SalesReportV2` con period bar persistente

**Backing data:** `generate_sales_report_v2_gloria.py --batch` emite 3 JSONs pre-calculados:
- 6m: €168.825 LTV dormido · 474 clientes · 67 Champions
- 12m: €3.878.732 LTV dormido · 2.813 clientes · 697 Champions
- 24m: €12.056.597 LTV dormido · 3.772 clientes · 1.038 Champions

Fijado `REFERENCE_DATE = 2025-12-15` en el generator para que rolling windows peguen a data real (Gloria va 2011 → Dec 2025).

### Pendientes VAL-120

- [ ] Merge #40 → develop
- [ ] Merge #41 → develop (auto-rebase post #40)
- [ ] **Browser walkthrough** — probar flow end-to-end en `http://localhost:3000/demo/sales-v2-gloria`
  - idle → click "Ejecutar diagnóstico" → progress ~14s → report
  - click 6m/24m → short progress ~5s → report swap
- [ ] **Re-run production test** cuando CLI esté libre — capturar narrator LLM v2-complete output
- [ ] Screencast 3-5 min del flow completo
- [ ] 10 talking points para la demo
- [ ] Coordinar con Loren el agendamiento con Bio4

---

## No bloquean sprints activos

| Issue | Que | Due |
|-------|-----|-----|
| VAL-22 | Scale: load testing | Jul 31 |
| GRO-11 | YC application | Aug 1 |
| ANN-1 | Annatar Roadmap | — |
| VAL-156 | Magic Matrix weighted gap (v3) | — |

---

## Arquitectura relevante (descubierta)

### Sales Report v2 stack (VAL-141 + VAL-157 + VAL-158)
- **Schema:** `core/valinor/schemas/sales_report_v2.py` — SalesReportV2 + ConcentrationReport con None coerción + NextAction con `impact_eur` validator (VAL-157)
- **Queries:** `core/valinor/queries/sales_v2.py` — 5 builders con semantic keys canonical + AND prefix helper + CTE `invoices_filtered` para JOIN queries (VAL-157)
- **Narrator:** `core/valinor/agents/narrators/sales.py` — emite JSON string-serialized, fallback schema-valid
- **Frontend:**
  - `web/components/ko-report/SalesReportV2.tsx` — render estructurado
  - `web/components/ko-report/PipelineProgress.tsx` (VAL-158) — animated timeline
  - `web/app/demo/sales-v2-gloria/page.tsx` — state machine idle/loading/ready (VAL-158)
- **Generator:** `scripts/generate_sales_report_v2_gloria.py` — CLI `--months/--label/--output/--batch`, REFERENCE_DATE anchor, empty-dormants fallback

### Discovery Engine (VAL-125)
`profiler.py` · `fk_discovery.py` · `ontology_builder.py` · `semantic_enricher.py` · `golden_dataset.py` + `benchmark.py` (gloria_full P=1.00 R=0.88 F1=0.93)

### Connectors (`shared/connectors/`)
Base `DeltaConnector` + Factory. Existentes: PostgreSQL, MySQL, SQLite, Etendo, MSSQL.

### Verticals (VAL-130)
`core/valinor/verticals/` — registry + InventoryVertical (Haiku) + FinancialVertical (swarm).

---

## Completado

### Sesion 2026-04-21 — VAL-141 merge + VAL-157 fix + VAL-158 dynamic demo
- **Merge:** PR #39 VAL-141 → develop (commit `ddeab48d`). VAL-141 cerrado en Linear.
- **Fix (PR #40):** 3 bugs sales_v2 post-merge detectados por production test:
  - Semantic keys mismatch (Cartographer emite `customer_fk`/`amount_col`/`pk`, no `customer_id`/`total_amount`/`invoice_id`)
  - `base_filter` sin AND prefix rompía sintaxis
  - JOIN con customers/invoice_lines/products ambiguaba `isactive` → CTE pre-filter
  - `NextAction.impact_eur` validator coerce None → 0.0
  - 4 tests nuevos (29/29), 13/13 queries OK contra Gloria
- **Demo dinámico (PR #41):** period picker + animated progress + 3 pre-generated period JSONs
  - Backend: `--batch` flag + REFERENCE_DATE anchor + fallback empty-dormants
  - Frontend: `PipelineProgress.tsx` (9 stages), `page.tsx` state machine
- **Linear MCP:** token vencido durante la sesión → no se pudo crear VAL-157/VAL-158 como issues formales ni actualizar Session Log remoto. **TODO al re-auth:** crear VAL-157 + VAL-158 como sub-issues de VAL-141, portar comentarios post-merge.

### Sesion 2026-04-18/20 — Sales Report v2 (VAL-141 shipped)
- 6 commits · PR #39 · +3520 / -131
- 8 fixes de primera pasada · segunda pasada narrator LLM · tercera pasada cuenta_top + cadence_factor
- Audit trail VAL-152/153/154/155 Done · VAL-156 Backlog
- Detalle en Session Log — Dev (Linear)

### Sesion 2026-04-17/18 — SYSCOP Sprint Closure
VAL-125, VAL-127/128/129, VAL-130 (4 capas), VAL-131, VAL-140 Done. PRs #33, #34, #35, #36, #37 merged.

### Sesion 2026-04-15a — Setup + commits pendientes
Commits infra/web/docs. Linear conectado. Agentes en worktrees paralelos.
