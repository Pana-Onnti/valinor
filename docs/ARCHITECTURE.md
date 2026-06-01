# Valinor SaaS v2 — Arquitectura Tecnica

> Estado: Junio 2026. Fases 1–7 cerradas (ver docs/ROADMAP.md). Estado vivo verificado: docs/PROJECT_STATE.md.
> SYSCOP (Fase 8) suspendido — corre en repo separado `Pana-Onnti/syscop-agent`, no en este repo.

---

## Vista de alto nivel

```
Cliente
  │
  ▼
FastAPI (puerto 8000)
  │
  ├── Middleware: rate-limiting / request_id / audit log
  │
  ├── POST /api/analyze ──► Celery Worker (Redis queue, puerto 6380)
  │                              │
  │                              ▼
  │                    SSHTunnelManager (Paramiko)
  │                              │
  │                              ▼
  │                    DB del Cliente (túnel efímero, max 1h)
  │                              │
  │                              ▼
  │                    Valinor Pipeline v0 (core/valinor/)
  │                    ┌─────────────────────────────┐
  │                    │ 1. DataQualityGate (8+1)     │
  │                    │ 2. Cartographer               │
  │                    │ 3. QueryEvolver               │
  │                    │ 4. QueryBuilder               │
  │                    │ 5. Analysts + Sentinels        │
  │                    │ 6. CurrencyGuard              │
  │                    │ 7. SegmentationEngine         │
  │                    │ 8. AnomalyDetector            │
  │                    │ 9. SentinelPatterns (16)      │
  │                    │ 10. AlertEngine               │
  │                    │ 11. Narrators                 │
  │                    └─────────────────────────────┘
  │                              │
  │                    SSE /api/jobs/{id}/stream ──► Redis Pub/Sub
  │                    (real-time per-agent progress to frontend)
  │                              │
  │                    ProfileExtractor ──► ProfileStore (Redis/PG)
  │                    AdaptiveContextBuilder
  │                              │
  │                    Outputs: JSON + PDF + Email + Webhooks
  │
  ├── GET /api/jobs/{id}/status   ──► Redis
  ├── GET /api/jobs/{id}/results  ──► PostgreSQL (puerto 5450 en dev)
  ├── WS  /api/jobs/{id}/ws       ──► WebSocket streaming
  └── GET /metrics                ──► Prometheus scrape
```

---

## Pipeline de análisis — detalle

### 0. Pre-check: DataQualityGate
Antes de cualquier análisis, 8+1 checks bloqueantes:
1. Row count vs baseline (schema drift)
2. Null ratio por columna (threshold configurable)
3. Type consistency (no silent coercions)
4. PK uniqueness
5. Referential integrity spot-check
6. Numeric range / outlier pre-screen
7. Date range plausibility (no timestamps futuros)
8. Freshness check via CurrencyGuard
+1. REPEATABLE READ isolation snapshot

Si DQ score < threshold configurado → `DQGateHaltError` → job abortado con reporte.

### 1. Cartographer
Mapea el schema de la DB del cliente. Detecta entidades conocidas:
`customers / invoices / products / payments / ...`

### 2. QueryEvolver
Lee el historial del cliente (ProfileStore) y adapta qué queries priorizar basado en qué dio resultados valiosos en análisis anteriores.

### 3. QueryBuilder
Genera las queries SQL según el schema mapeado y las preferencias del QueryEvolver.

### 4. Analysts + Sentinels
- **Analyst**: revenue_calc, aging_calc, pareto_analysis, segmentation
- **Sentinel**: fraud detection, anomalies, pattern matching
- **Hunter**: busca oportunidades de revenue no capturadas

### 5. Quality post-análisis
- **CurrencyGuard**: detecta si los datos están stale
- **SegmentationEngine**: segmenta clientes por RFM (recencia/frecuencia/monto)
- **AnomalyDetector**: STL decomposition + Z-score
- **SentinelPatterns**: 16 patrones de fraude incluyendo Benford's Law

### 6. AlertEngine
Evalúa umbrales configurados por cliente. Genera alerts si hay desvíos.

### 7. Narrators (parallelized)
Run in parallel via `asyncio.gather()` with per-narrator timeout (default: 60s). Each narrator (CEO, Controller, Sales, Executive) runs independently. If one fails or times out, the others continue (graceful degradation). Reciben contexto inyectado por AdaptiveContextBuilder (histórico del cliente, findings persistentes, currency context, segmentation) y generan el reporte por audiencia.

### 8. ProfileExtractor
Post-análisis, extrae el perfil actualizado del cliente y lo persiste para el próximo análisis.

---

## Verification & Anti-Hallucination Layer

### Verification Engine
Post-analysis verification of agent findings against actual database values. Extracts numeric claims from agent output, generates verification SQL, and classifies claims as VERIFIED / APPROXIMATE / FAILED. Failed findings are retracted before they reach narrators.

### Knowledge Graph
Data-driven schema understanding built entirely from the Cartographer's entity_map. Provides:
- Automatic JOIN path reasoning via BFS (shortest path)
- Discriminator awareness from probed data
- Required filter injection (base_filter from entity_map)
- Business concept generation from entity semantics

### Calibration Loop (Guard Rail)
Deterministic pre-flight check (no LLM cost). Verifies base_filter correctness via COUNT queries. If checks fail, structured feedback is fed back to Cartographer for correction (Reflexion pattern).

### Discovery (Schema Topology)
Classifies schema complexity (FULL / SLIM / MINIMAL) to gate query generation. FULL topology requires invoices + customers + payments. SLIM requires invoices + customers. MINIMAL generates only base financial queries.

### Discovery v2 (DONE — VAL-125, cerrado 2026-04-18)
Multi-agent schema understanding for databases without explicit FK constraints (typical of Argentine ERP systems). Architecture (shipped):
- SchemaExtractor: SQLAlchemy Inspector, dialect-aware (PostgreSQL, MySQL, SQL Server)
- Structural Profiler: column type/name pattern analysis
- Multi-Agent Inference: 4 parallel agents (structural, semantic, statistical, LLM) producing candidate relations
- Ensemble Evaluator: deterministic consensus across agent outputs

---

## Connection Pooling (`shared/db_pool.py`)

SQLAlchemy `QueuePool`-based connection pooling. Configuration via environment variables:

| Variable | Default | Description |
|---|---|---|
| `VALINOR_DB_POOL_SIZE` | 5 | Base pool size |
| `VALINOR_DB_POOL_MAX` | 10 | Max overflow connections |
| `VALINOR_DB_POOL_TIMEOUT` | 30 | Checkout timeout (seconds) |
| `VALINOR_DB_POOL_RECYCLE` | 1800 | Connection recycle time (seconds) |
| `VALINOR_DB_POOL_PRE_PING` | true | Health check on checkout |

Engines are cached by connection string and reused across tool calls. `db_tools.py` uses the pool automatically when available, with fallback to direct `create_engine()`.

---

## Auth Layer

API key authentication via `VALINOR_API_KEY` environment variable. CORS origins configurable via `CORS_ORIGINS`. Rate limiting middleware on all API endpoints.

---

## Conflict Reconciliation (Haiku arbiter)

When 2+ agents report conflicting values (>2x difference), a Haiku arbiter reconciles
them and records which agent was closer to truth.
**Live implementation:** `core/valinor/pipeline_reconciliation.py` (`reconcile_swarm`,
CONFLICT_THRESHOLD 2x), invoked from `run.py`.

> **Not wired (experimental — referenced only by their own tests):**
> `core/valinor/agents/cash_flow_forecaster.py`, `core/valinor/agents/anomaly_explainer.py`,
> `core/valinor/quorum.py`, and `core/valinor/calibration/`. These are NOT in the
> production pipeline. Do not describe them as live capabilities. Candidates to wire
> or archive — tracked in VAL-167.

---

## Intelligence Layer (Memory)

```
ProfileStore (Redis + PostgreSQL)
    ▲                │
    │                ▼
ProfileExtractor    AdaptiveContextBuilder
    │                    │
    │                    ▼
    │              Inyección en system prompt de Narrators
    │
    ▼
IndustryDetector → detecta industria por tablas presentes
SegmentationEngine → RFM segmentation
AlertEngine → umbrales por cliente
```

---

## Módulos clave y sus responsabilidades

| Módulo | Archivo | Responsabilidad |
|---|---|---|
| `ValinorAdapter` | `api/adapters/valinor_adapter.py` | Punto de entrada al pipeline v0 |
| `SSHTunnelManager` | `shared/ssh_tunnel.py` | Túneles SSH efímeros + ZeroTrust |
| `ConnectionPoolManager` | `shared/db_pool.py` | Connection pooling con SQLAlchemy QueuePool |
| `DataQualityGate` | `core/valinor/quality/data_quality_gate.py` | 9 checks pre-análisis (8 + REPEATABLE READ snapshot); fail-closed en crash (VAL-165) |
| `CurrencyGuard` | `core/valinor/quality/` | Detección de datos stale |
| `VerificationEngine` | `core/valinor/verification.py` | Anti-hallucination: verifica findings contra DB |
| `SchemaKnowledgeGraph` | `core/valinor/knowledge_graph.py` | Grafo de schema para JOINs y filtros |
| `QueryGenerator` | `core/valinor/agents/query_generator.py` | SQL dinámico guiado por KG |
| `ProfileStore` | `shared/memory/profile_store.py` | Persistencia de perfiles de cliente |
| `AdaptiveContextBuilder` | `shared/memory/adaptive_context_builder.py` | Contexto histórico para agentes |
| `QueryEvolver` | `api/refinement/query_evolver.py` | Aprendizaje de queries valiosas |
| `AlertEngine` | `shared/memory/alert_engine.py` | Umbrales y alertas por cliente |
| `WebhookDispatcher` | `shared/webhook_dispatcher.py` | Webhooks con retry exponencial |
| `PDFGenerator` | `api/pdf_generator.py` | Export PDF con DQ bar + alerts |
| `DigestComposer` | `api/email_digest.py` | Email digest con delta entre runs |

---

## Connectors (shared/connectors/)

| Connector | Class | Estado |
|-----------|-------|--------|
| PostgreSQL | `PostgreSQLConnector` | Production (Gloria/Etendo) |
| MySQL | `MySQLConnector` | Tested |
| SQLite | `SQLiteConnector` | Production (file ingestion) |
| Etendo | `EtendoConnector` | Production (Gloria) |
| SQL Server | `MSSQLConnector` | Implementado (`shared/connectors/mssql_connector.py`) |

## Stack tecnologico

| Capa | Tecnologia |
|---|---|
| Backend API | FastAPI + Pydantic v2 |
| Queue | Celery + Redis |
| DB Metadata | PostgreSQL (dev: puerto 5450) |
| Cache/State | Redis (dev: puerto 6380) |
| SSH Tunneling | Paramiko |
| AI Agents | Claude API (claude-sonnet-4-6 / claude-opus-4-6) |
| Real-time | SSE + Redis Pub/Sub (per-agent progress) |
| Frontend | Next.js + Tailwind CSS + D4C Design System |
| Monitoring | Prometheus (puerto 9090) + Grafana + Loki |
| Testing | pytest (~3358 tests: ~3302 en tests/ + 56 en security/) |
| CI/CD | GitHub Actions (GHCR + staging deploy + PR checks) |
| Deployment | Railway (staging) + Vercel (frontend) |

---

## Decisiones de diseño

**Zero Data Storage**: nunca se almacenan datos del cliente, solo metadata del job y resultados agregados. Las conexiones SSH son efímeras (max 1 hora, cleanup automático).

**Wrapper sobre v0**: todo el código en `core/valinor/` es preservado intacto. La API v2 lo envuelve con adapter pattern. Esto permite rollback inmediato a CLI si algo falla.

**Costo operativo**: ~$8 por análisis (Claude API). Precio al cliente: $200/mes (25 análisis). Margen bruto: 92%.

---

*Última actualización: Junio 2026 — Delta 4C*
*Estado vivo: docs/PROJECT_STATE.md | Roadmap: docs/ROADMAP.md | Plan táctico: .claude/plans/active-plan.md*
