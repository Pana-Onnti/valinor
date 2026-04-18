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

### Fase 4: Runner Standalone (VAL-131) — CASI CERRADA
Repo separado `Pana-Onnti/syscop-agent`. VAL-133 a VAL-139 Done, VAL-140 In Review.

| Issue | Que | Status |
|-------|-----|--------|
| VAL-133 | Setup repo syscop-agent | DONE |
| VAL-134 | Docker SQL Server + schema BDPYME + data sintética | DONE |
| VAL-135 | Prefetcher runner + data_pack.json | DONE |
| VAL-136 | Agent loop (tool-use con anthropic SDK) | DONE |
| VAL-137 | 4 agentes: Centinela/Analista/Cazador/Narrador | DONE |
| VAL-138 | Renderer Jinja2 + weasyprint PDF | DONE |
| VAL-139 | Mailer SMTP + Healthcheck | DONE |
| VAL-140 | Build .exe + install Task Scheduler + test VM | IN REVIEW |

### Pendientes activos

| Issue | Que | Due | Status | Repo |
|-------|-----|-----|--------|------|
| VAL-140 | Validación .exe en Windows VM limpia | — | In Review | syscop-agent |
| VAL-130 | Scheduling + Reporting composable (3 capas: pipelines por vertical, redbeat, NotificationRouter+WhatsApp) | Apr 25 | Backlog | valinor-saas |
| GRO-17 | Lorenzo + Gerardo: user SQL + ODBC 17 en PC cliente | — | Bloquea deploy | — |

### Bloquea first-run (lunes 27 Abr 06:00)
- VAL-140 (validación) + GRO-17 (infra cliente) + deploy remoto

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
