# Active Plan — SYSCOP Sprint

**Ultima actualizacion:** 2026-04-18
**Branch:** develop
**Foco:** GRO-15 — Agente de Inventario para SYSCOP (Gerardo), primer cliente pagante
**Deadline:** 2026-04-25

---

## Sprint SYSCOP — Camino critico

### Fase 1-3: Discovery Engine v2 (VAL-125) — CERRADA
VAL-125 EPIC cerrado 2026-04-18. Todos los sub-issues en develop:

| Issue | Que | Status |
|-------|-----|--------|
| VAL-122 | MSSQLConnector | DONE |
| VAL-126 | SchemaExtractor dialect-aware + Structural Profiler | DONE |
| VAL-128 | BusinessContext + argentina_gestion.yaml | DONE (PR #34) |
| VAL-127 | Multi-Agent Inference + Ensemble Evaluator | DONE (PR #33) |
| VAL-129 | Golden Dataset + Benchmark | DONE (PR #35) |

### Fase 4: Runner Standalone (VAL-131) — CERRADA
Repo separado `Pana-Onnti/syscop-agent`. Todos los sub-issues Done + hardening pass (commit `32d85381`).

| Issue | Que | Status |
|-------|-----|--------|
| VAL-133 | Setup repo syscop-agent | DONE |
| VAL-134 | Docker SQL Server + schema BDPYME + data sintética | DONE |
| VAL-135 | Prefetcher runner + data_pack.json | DONE |
| VAL-136 | Agent loop (tool-use con anthropic SDK) | DONE |
| VAL-137 | 4 agentes: Centinela/Analista/Cazador/Narrador | DONE |
| VAL-138 | Renderer Jinja2 + weasyprint PDF | DONE |
| VAL-139 | Mailer SMTP + Healthcheck | DONE |
| VAL-140 | Build .exe + install Task Scheduler + test VM | DONE (código; build físico Win pendiente) |

### Fase 5: Scheduling + Reporting composable (VAL-130) — CERRADA
Mergeado a develop via PR #36 + PR #37.

| Capa | Que | Status |
|------|-----|--------|
| L1.a | `core/valinor/verticals/` + `run_vertical` + InventoryVertical | DONE |
| L1.b | analyst/sentinel/hunter detrás del registry + FINANCIAL_VERTICAL | DONE |
| L3.a | NotificationRouter + Email/Webhook adapters | DONE |
| L3.b | WhatsAppAdapter (Twilio) + format_whatsapp_body | DONE |
| L2   | redbeat + VerticalSchedule + ScheduleManager | DONE |

### Pendientes activos

| Issue | Que | Due | Status | Owner |
|-------|-----|-----|--------|-------|
| GRO-17 | Creds SQL r/o `valinor_ro` + OK .exe de Gerardo | — | Todo | Loren→Gerardo |
| —      | Build físico `syscop_inventory.exe` (1h Windows host) | — | — | Nico |
| —      | Deploy remoto AnyDesk Tue 22 / Wed 23 | — | — | Nico + Gerardo |
| VAL-121 | Primer KO Report enviado exitosamente | Apr 25 | In Progress | Nico |
| GRO-15  | EPIC SYSCOP comercial (cierra con primer report en vivo) | Apr 25 | In Progress | Nico |

### Bloquea first-run (lunes 27 Abr 06:00)
**Solo GRO-17.** Todo el código está listo. Sin creds + OK de Gerardo no se puede deployar — escalado a Loren 2026-04-18.

### Nota técnica 2026-04-18
- Hardening pass del runner migró a `pymssql` (TDS nativo). **ODBC Driver 17 ya no es requerido** en la PC de Gerardo. GRO-17 actualizado.
- VAL-130 L3.b WhatsAppAdapter queda listo pero el runner .exe manda por email. WhatsApp Twilio se cablea cuando Gerardo lo pida (V2).
- Wirings cloud-side (task `run_vertical_schedule`, API endpoint, CRUD schedule_config) NO bloquean SYSCOP — son para clientes futuros que usen Valinor cloud scheduler.

### No bloquean SYSCOP
| Issue | Que | Due |
|-------|-----|-----|
| VAL-120 | Demo Valinor para Bio4 | Apr 18 |
| ANN-1 | Annatar Roadmap (otro proyecto) | — |
| VAL-22 | Scale: load testing | Jul 31 |
| GRO-11 | YC application | Aug 1 |

---

## Arquitectura relevante (descubierta)

### Discovery Engine (`core/valinor/discovery/`)
- `profiler.py` — SchemaProfiler → TableProfile, ColumnProfile
- `fk_discovery.py` — FKDiscovery (inclusion dependency, estadistico)
- `ontology_builder.py` — OntologyBuilder → EntityClassification
- `semantic_enricher.py` — SemanticColumnType enum

### Connectors (`shared/connectors/`)
- Base: `DeltaConnector(abc.ABC)` — connect(), execute_query(), get_schema()
- Factory: `ConnectorFactory.create(source_type, config)`
- Existentes: PostgreSQL, MySQL, SQLite, Etendo
- **Falta: MSSQL** ← VAL-122

### Cartographer (`core/valinor/agents/cartographer.py`)
- Phase 1: SQLAlchemy inspector directo (determinista, ~5s)
- Phase 2: Agente Sonnet con MCP tools (introspect_schema, sample_table, etc)
- Output: entity_map.json

### DB Tools (`core/valinor/tools/db_tools.py`)
- connect_database, introspect_schema, sample_table, classify_entity, probe_column_values
- **No hay get_schema_info()** — split entre introspect_schema + connect_database

---

## Completado

### Sesion 2026-04-15a — Setup + commit pendientes
- Committed: fix(infra,web) — PYTHONPATH worker, metric collision, null-safety 9 archivos frontend
- Committed: chore(docs) — plan + CLAUDE.md update
- Linear MCP conectado y funcional
- VAL-126 + VAL-122 movidos a In Progress
- Agentes lanzados en worktrees paralelos

### Sesion 2026-04-14b — Infra + null safety
- Docker compose up: todos los servicios levantados
- Worker fix: PYTHONPATH=/app:/app/core
- Metric collision fix: counter duplicado
- Null safety en 11 archivos frontend
