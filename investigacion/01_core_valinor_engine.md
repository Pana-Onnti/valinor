# Investigacion Exhaustiva: core/valinor/ — Motor de BI Valinor v0

**Fecha:** 2026-03-22
**Archivos analizados:** 49 archivos Python
**Lineas de codigo estimadas:** ~8,500 LOC

---

## 1. Resumen Ejecutivo

`core/valinor/` es el motor central de Valinor, un pipeline de Business Intelligence multi-agente que analiza bases de datos ERP (Openbravo, Odoo, SAP, Excel/CSV) y produce reportes ejecutivos para CEO, Controller, Ventas y Direccion General. El sistema implementa una arquitectura de 6 stages (0-5) con gates de calidad entre cada etapa, un Knowledge Graph para razonamiento sobre esquemas, un Verification Engine anti-alucinacion, y un sistema de calibracion que aprende entre ejecuciones.

El motor se distingue por tres principios arquitectonicos:
1. **Zero hardcoded ERP knowledge** — toda la semantica se descubre de los datos via Cartographer + Discovery
2. **Anti-hallucination by design** — Number Registry, provenance tracking, triple verification, frozen baseline
3. **Multi-agent with reconciliation** — 3 agentes analizan en paralelo, un arbiter Haiku resuelve conflictos numericos

---

## 2. Arquitectura

### 2.1 Pipeline de 6 Stages

```
Stage 0: INTAKE          → excel_to_sqlite / csv_to_sqlite (opcional)
Stage 1: CARTOGRAPHER    → Descubrimiento de esquema (Phase 1 determinista + Phase 2 Sonnet)
  └─ Stage 1.5: GUARD RAIL → Verificacion base_filter con SQL COUNTs (Reflexion retry loop)
Stage 2: QUERY BUILDER   → Generacion SQL determinista desde templates o KG-guided
  └─ Stage 2.5: EXECUTE  → Ejecucion contra DB con REPEATABLE READ isolation
  └─ Post-2.5: BASELINE  → Computo de frozen brief con provenance
Stage 3: ANALYSIS AGENTS → Analyst + Sentinel + Hunter en paralelo (Sonnet)
  └─ Stage 3.5: RECONCILE → Debate + Judge con Haiku arbiter para conflictos >2x
  └─ Stage 3.75: VERIFY   → Preparation de findings por rol de narrator
Stage 4: NARRATORS       → 4 reportes: CEO, Controller, Ventas, Ejecutivo (Sonnet)
Stage 5: DELIVER         → Persistencia: markdown, JSON, memory
```

### 2.2 Mapa de Directorios

```
core/valinor/
├── __init__.py              # Version 0.1.0
├── config.py                # Client config loader, period parser
├── run.py                   # CLI entry point (asyncio.run)
├── pipeline.py              # Master orchestrator (1041 lineas)
├── gates.py                 # Quality gates entre stages
├── deliver.py               # Output generation + memory builder
├── knowledge_graph.py       # SchemaKnowledgeGraph (Dijkstra, BFS)
├── verification.py          # VerificationEngine (triple verification)
├── agents/
│   ├── cartographer.py      # Stage 1: Schema discovery (2-phase)
│   ├── query_builder.py     # Stage 2: SQL template generation
│   ├── query_generator.py   # KG-guided dynamic SQL (SQLBuilder fluent API)
│   ├── analyst.py           # Stage 3a: Financial Intelligence (Sonnet)
│   ├── sentinel.py          # Stage 3b: Data Quality (Sonnet)
│   ├── hunter.py            # Stage 3c: Opportunity Detection (Sonnet)
│   ├── sentinel_patterns.py # 15 anomaly patterns (ACFE-based)
│   ├── narrators/
│   │   ├── ceo.py           # CEO briefing (5 numeros + 3 decisiones)
│   │   ├── controller.py    # P&L, provisiones, anomalias
│   │   ├── sales.py         # Call list, reactivacion, cross-sell
│   │   ├── executive.py     # Master synthesis + reconciliation
│   │   ├── system_prompts.py # Output KO methodology + DQ context
│   │   └── quality_certifier.py # Post-process: confidence badges
│   └── vaire/
│       ├── agent.py         # Frontend rendering (HTML/PDF/WhatsApp)
│       ├── pdf_renderer.py  # WeasyPrint wrapper
│       └── templates/
│           └── ko_report.py # KO Report v2 HTML template (D4C tokens)
├── calibration/
│   ├── evaluator.py         # Post-run accuracy scorer (0-100)
│   ├── adjuster.py          # Improvement suggestions (anti-overfitting)
│   └── memory.py            # Cross-run calibration persistence
├── discovery/
│   ├── profiler.py          # Statistical column profiler (semantic type inference)
│   ├── fk_discovery.py      # FK detection via inclusion dependencies
│   └── ontology_builder.py  # Business ontology from profiler + FK results
├── quality/
│   ├── data_quality_gate.py # 8-check DQ gate (schema, nulls, Benford, STL, cointegration)
│   ├── anomaly_detector.py  # IQR 3x log-transformed outlier detection
│   ├── currency_guard.py    # Mixed-currency aggregation prevention
│   ├── provenance.py        # FindingProvenance + ProvenanceRegistry
│   ├── statistical_checks.py # Seasonal z-score, cointegration, Benford, CUSUM
│   └── factor_model.py      # Revenue decomposition (clients x ticket x frequency)
├── schemas/
│   └── agent_outputs.py     # Pydantic v2 schemas (CartographerOutput, AnalystOutput, etc.)
├── nl/
│   └── vanna_adapter.py     # NL→SQL via Vanna AI + Anthropic
└── tools/
    ├── db_tools.py          # MCP tools: connect, introspect, sample, classify, probe, execute
    ├── excel_tools.py       # Excel/CSV → SQLite conversion
    ├── analysis_tools.py    # Revenue calc, aging calc, Pareto analysis
    └── memory_tools.py      # read_memory, write_memory, write_artifact
```

---

## 3. Modulos Principales

### 3.1 `pipeline.py` — Master Orchestrator (1041 LOC)

El archivo mas grande y critico. Contiene:

- **`execute_queries()`** — Ejecuta SQL con REPEATABLE READ isolation (fallback a default si no soportado). Serializa tipos no estandar, captura errores por query.
- **`gate_calibration()`** — Guard Rail determinista: COUNT(*) total vs filtered, SUM(amount) no null, FK orphan check. Genera feedback estructurado para Reflexion retry.
- **`compute_baseline()`** — Frozen Brief con provenance. Cada metrica (total_revenue, num_invoices, etc.) lleva `_provenance: {source_query, row_count, executed_at, confidence}`. Los agentes DEBEN usar estos numeros.
- **`compute_mom_delta()`** — Comparacion MoM/QoQ con alertas por threshold configurable por metrica.
- **`run_analysis_agents()`** — Lanza Analyst, Sentinel, Hunter en `asyncio.gather()` con `return_exceptions=True`.
- **`reconcile_swarm()`** — Detecta conflictos numericos >2x entre agentes, invoca Haiku arbiter que selecciona (no promedia) el valor mas defensible.
- **`prepare_narrator_context()`** — Filtra findings por rol (CEO solo ve VERIFIED, Sales no ve FAILED, Controller ve todo).
- **`run_narrators()`** — Ejecuta 4 narrators secuencialmente, cada uno con context preparado por rol.

### 3.2 `knowledge_graph.py` — SchemaKnowledgeGraph (582 LOC)

Grafo de esquema 100% data-driven. Structures:
- `TableNode` — tabla, entity_name, base_filter, filter_columns, pk_columns
- `FKEdge` — relacion FK con confidence y weight (1-confidence para Dijkstra)
- `JoinPath` — resultado de BFS, incluye `sql_fragment` property
- `BusinessConcept` — concepto derivado de entity semantics

Funcionalidad clave:
- `find_join_path()` — Dijkstra bidireccional (forward + reverse edges), confidence-weighted
- `validate_query()` — Detecta MISSING_FILTER_COLUMN y AMBIGUOUS_COLUMN
- `to_prompt_context()` — Serializa el KG completo para inyeccion en prompts de agentes
- `_generate_concepts()` — Auto-genera conceptos de negocio desde entity_map (filtered queries, totals, cross-table joins)

### 3.3 `verification.py` — VerificationEngine (1100+ LOC)

Implementa "Triple Verification" (CoVe + SAFE + CRITIC):

1. **Claim decomposition** — Descompone findings en AtomicClaims (numericos, porcentajes, conteos)
2. **Number Registry** — Construye registro de valores verificados desde query results + baseline
3. **5-strategy verification chain:**
   - Strategy 1: Direct registry match (tolerance-aware por tipo: EUR 0.5%, count exacto, pct 2% absoluto)
   - Strategy 2: Derived value check (division, multiplicacion, sustraccion de registry entries)
   - Strategy 3: Raw query result search (busca en todas las rows de todos los queries)
   - Strategy 4: Active re-query (genera SQL desde entity_map/KG, ejecuta con timeout 5s, thread safety)
   - Strategy 5: Approximate match (<5% deviation)
4. **Cross-validation** — customers_with_debt vs distinct_customers, AR vs revenue, avg_invoice consistency
5. **SQL Safety** — Bloquea INSERT/UPDATE/DELETE/DROP, solo permite SELECT/WITH, timeout via thread

Confidence scoring con deviation penalty: `base_score - abs(deviation_pct) * 0.02`, clamped to [0.0, 1.0].

### 3.4 `agents/cartographer.py` — Schema Discovery (315 LOC)

Dos fases:
- **Phase 1 (determinista):** Pre-scan de columnas discriminadoras (ad_client_id, issotrx, docstatus) en tablas con nombres business-like. Probes hasta 6 tablas, 4 columnas por tabla. Zero LLM cost.
- **Phase 2 (Sonnet):** Deep map con hints de Phase 1 + feedback de Guard Rail. Usa MCP tools (connect_database, introspect_schema, sample_table, classify_entity, probe_column_values, write_artifact). Max 35 turns.

Reflexion pattern: si Guard Rail falla, los failures se formatean como `CALIBRATION FEEDBACK` y se reinyectan en el prompt para retry (max 2 reintentos).

### 3.5 `agents/query_builder.py` + `query_generator.py`

**query_builder.py (714 LOC):** Generacion SQL determinista via templates con `{placeholder}` interpolation. 14 templates cubriendo financial, credit, sales, data_quality domains. Maneja:
- Entity filters desde base_filter (qualified con alias para multi-table JOINs)
- Entity prioritization con scoring (weight + row_count + focus_tables multiplier)
- `build_queries_adaptive()` — Intenta KG-guided primero, fallback a templates

**query_generator.py (793 LOC):** SQLBuilder fluent API + QueryGenerator:
- `SQLBuilder` — `select().from_table().join_to().where_filters().build()`. `join_to()` usa KG.find_join_path() automaticamente.
- `QueryGenerator` — Detecta entidades por TYPE (TRANSACTIONAL, MASTER), columnas por SEMANTIC ROLE (amount_col, date_col). 8 generators: revenue_summary, ar_outstanding, aging, customer_concentration, top_debtors, dormant_customers, revenue_trend, yoy_comparison.

### 3.6 Agentes de Analisis (analyst.py, sentinel.py, hunter.py)

Estructura identica: cargan skill file, construyen shared_context + baseline_summary + kg_context, ejecutan con Sonnet (max 20 turns). Cada uno tiene CRITICAL RULES anti-alucinacion:
- **Analyst:** Patrones financieros. Findings FIN-001+. Valores MUST derivar de baseline.
- **Sentinel:** Data quality. Findings DQ-001+. Detecta multi-tenant, nulls, orphans.
- **Hunter:** Oportunidades comerciales. Findings HUNT-001+. Usa datos reales de dormant_customer_list, no inventa nombres.

Todos producen JSON arrays con: id, severity, headline, evidence, value_eur, value_confidence, action, domain.

### 3.7 `agents/narrators/` — 4 Reportes por Audiencia

- **CEO (`ceo.py`):** 5 Numeros Que Importan + 3 Decisiones Esta Semana. Max 1 pagina.
- **Controller (`controller.py`):** P&L, provisiones, aging, anomalias, forecast. Cada EUR marcado [MEDIDO/ESTIMADO/INFERIDO].
- **Sales (`sales.py`):** Call list con nombres reales de DB, reactivacion, cross-sell, restricciones.
- **Executive (`executive.py`):** Master synthesis. Rank findings por IMPACT x URGENCY x SURPRISE. Top 7. Calendario de acciones.
- **system_prompts.py:** Output KO methodology (conclusion primero, evidencia, accion). Inyecta DQ context, factor model, segmentation, Benford alerts, CUSUM warnings, persistent findings.
- **quality_certifier.py:** Post-processor que anade badges de confianza a montos monetarios en markdown.

### 3.8 `agents/vaire/` — Frontend Rendering

VaireAgent: toma output del Narrator y produce:
- HTML con design tokens D4C (dark theme: #0A0A0F, teal accent #2A9D8F)
- PDF via WeasyPrint
- WhatsApp summary (texto plano con emojis de severidad)

Loss framing enforcement: convierte "podrias ganar X" → "estas perdiendo X".

### 3.9 `calibration/` — Self-Calibration Loop

- **evaluator.py:** Califica runs 0-100. Checks: query coverage, baseline completeness, cross-consistency (avg=total/count, aging_sum=outstanding, top_customer<=total, debt_customers<=total), verification rate, error rate.
- **adjuster.py:** Genera sugerencias de mejora. Anti-overfitting: si otros clientes no tienen el mismo problema, la sugerencia es marcada como potencial overfitting.
- **memory.py:** Persiste scores por cliente en JSON. Detecta regresiones (>5 puntos), calcula tendencias (improving/stable/degrading).

### 3.10 `discovery/` — Auto-Discovery Pipeline

- **profiler.py:** Profiling estadistico puro. Infiere SemanticType (MONETARY, TEMPORAL, CATEGORICAL, IDENTIFIER, BOOLEAN, NUMERIC, TEXT) desde data patterns. Detecta discriminadores (cardinality <=10, uniqueness <0.5).
- **fk_discovery.py:** Detecta FKs via Inclusion Dependency: si col_A.values ⊆ col_B.values AND col_B is PK candidate AND name_similarity > 0.3. Score = 0.5*inclusion + 0.3*name_sim + 0.2*cardinality_ratio.
- **ontology_builder.py:** Clasifica entidades (TRANSACTIONAL si date+monetary+rows>100, MASTER si inbound FKs, BRIDGE si pocas columnas y >=2 FKs, CONFIG si <100 rows). Infiere business concepts (REVENUE, CUSTOMER, PRODUCT, PAYMENT).

### 3.11 `quality/` — Data Quality Suite

- **data_quality_gate.py:** 9 checks ponderados (schema_integrity 15, null_density 15, duplicate_rate 10, accounting_balance 20, cross_table_reconcile 15, outlier_screen 10, benford 5, temporal_consistency 10, receivables_cointegration 5). Score → DQ tag (FINAL/REVISED/PRELIMINARY/ESTIMATED).
- **anomaly_detector.py:** IQR 3x en log-transform de columnas financieras. Clasifica por value_share de outliers.
- **currency_guard.py:** Detecta mezcla de monedas antes de agregar. Genera context block con instrucciones IFRS 21/ASC 830.
- **provenance.py:** FindingProvenance con data lineage completa. ProvenanceRegistry acumula por run.
- **statistical_checks.py:** seasonal_adjusted_zscore (STL), cointegration_test (Engle-Granger), benford_test (chi-squared), cusum_structural_break.
- **factor_model.py:** Revenue = clients x avg_ticket x transactions_per_client. Shapley-like attribution. Anomalia si residual >15%.

### 3.12 `schemas/agent_outputs.py` — Pydantic v2 Type Safety

Modelos: CartographerOutput, QueryBuilderOutput, AnalystOutput, SentinelOutput. Incluyen:
- Field validators (base_filter strip, sql not empty)
- Properties computadas (critical_findings, total_value_eur, has_multi_tenant_risk)
- Factory methods from_entity_map_dict(), from_agent_dict(), from_query_pack_dict()
- Backward-compatible to_entity_map_dict()

### 3.13 `nl/vanna_adapter.py` — NL→SQL

Wrapper de Vanna AI con Anthropic backend + in-memory vector store. train_from_entity_map() genera DDL sintetico + documentacion desde CartographerOutput. ask() convierte NL a SQL. ask_and_run() ejecuta contra DB.

### 3.14 `tools/` — MCP Tool Suite

6 DB tools (connect, introspect, sample, classify, probe, execute), 2 Excel/CSV tools, 3 analysis tools (revenue_calc, aging_calc con provision rates, pareto_analysis con HHI), 3 memory tools (read, write, write_artifact). Todos con SQL safety guards (bloqueo de write operations).

---

## 4. Flujo de Datos

```
config.json ──────┐
Excel/CSV ────────┤
                  ▼
         [Stage 0: Intake]
              │ SQLite DB
              ▼
         [Stage 1: Cartographer]
              │ entity_map.json
              │   ├── entities (table, key_columns, base_filter, confidence)
              │   ├── relationships (from, to, via, cardinality)
              │   └── _phase1_prescan metadata
              ▼
         [Stage 1.5: Guard Rail]  ←──── calibration_feedback (Reflexion loop)
              │ calibration result
              ▼
         [Stage 2: Query Builder]
              │ query_pack {queries: [{id, sql, domain}], skipped: [...]}
              ▼
         [Stage 2.5: Execute Queries]
              │ query_results {results: {qid: {rows, columns}}, errors: {...}}
              ▼
         [Post-2.5: Compute Baseline]
              │ baseline {total_revenue, num_invoices, ..., _provenance: {...}}
              ▼
         [Stage 3: Analyst ║ Sentinel ║ Hunter]  (parallel)
              │ findings {agent_name: {agent, output/findings}}
              ▼
         [Stage 3.5: Reconcile Swarm]
              │ findings + _reconciliation {conflicts_found, notes}
              ▼
         [Stage 3.75: Prepare Narrator Context]
              │ role-filtered findings (verified/unverifiable/retracted)
              ▼
         [Stage 4: CEO │ Controller │ Sales │ Executive]  (sequential)
              │ reports {name: markdown_content}
              ▼
         [Stage 5: Deliver]
              ├── output/{client}/{period}/*.md
              ├── entity_map.json, run_log.json, raw_findings.json
              └── memory/{client}/swarm_memory_{period}.json
```

### Flujo de Numeros (Anti-Hallucination Chain)

```
DB rows → query_results → baseline (provenance-tagged)
                              ↓
                    Number Registry (ground truth)
                              ↓
              Agent findings (value_eur + value_confidence)
                              ↓
              Verification Engine (5-strategy chain)
                              ↓
              VerificationReport (VERIFIED/FAILED/APPROXIMATE/UNVERIFIABLE)
                              ↓
              Narrator context (role-filtered: CEO only sees VERIFIED)
                              ↓
              Reports ([MEDIDO] / [ESTIMADO] / [INFERIDO] tags)
```

---

## 5. Patrones de Diseno

### 5.1 Multi-Agent Swarm con Reconciliacion
- 3 agentes especializados ejecutan en paralelo (asyncio.gather)
- Conflictos numericos >2x detectados por domain + headline keyword overlap
- Haiku arbiter selecciona (no promedia) el valor mas defensible con cita de evidencia
- Patron: "Debate + Judge" (arxiv:2501.06322)

### 5.2 Reflexion Loop (Explore-Verify-Commit)
- Cartographer mapea esquema → Guard Rail verifica con SQL COUNTs → failures se reinyectan como feedback → max 2 retries
- Patron: Reflexion (arxiv:2303.11366)

### 5.3 Frozen Brief con Provenance
- baseline es inmutable despues de compute_baseline()
- Cada metrica lleva source_query, row_count, executed_at, confidence
- Agentes DEBEN usar baseline como ground truth para EUR estimates
- Patron: Provenance-Tagged Handoff (Palantir Foundry)

### 5.4 Knowledge Graph para SQL Generation
- SchemaKnowledgeGraph construido 100% desde entity_map
- Dijkstra confidence-weighted para JOIN paths
- SQLBuilder fluent API que consulta KG para JOINs automaticos
- Patron: SchemaGraphSQL (arXiv:2505.18363)

### 5.5 Triple Verification Anti-Hallucination
- Number Registry (ground truth desde queries)
- 5-strategy verification chain (exact → derived → raw → active requery → approximate)
- Role-based filtering (CEO solo VERIFIED, Controller todo, Sales sin FAILED)
- Patron: CoVe + SAFE + CRITIC

### 5.6 Schema-Then-Data Discovery
- Phase 1 determinista (zero LLM cost): probes de columnas discriminadoras
- Phase 2 LLM-assisted: deep map con hints de Phase 1
- FK Discovery via Inclusion Dependencies (statistical, no metadata)
- Patron: ReFoRCE Column Exploration (arxiv:2502.00675)

### 5.7 Gate Pattern (Quality Checkpoints)
- gate_cartographer: >=2 entidades con confidence >0.7
- gate_analysis: >=2 agentes produjeron findings
- gate_sanity: revenue available, reports non-empty
- gate_monetary_consistency: cross-report EUR values <50x ratio
- gate_verification: verification rate >=80%
- DataQualityGate: 9 checks ponderados, score 0-100, tags IFRS-style

### 5.8 Output KO Methodology
- Conclusion primero, evidencia despues, accion recomendada
- Loss framing: "estas perdiendo X" > "podrias ganar X"
- Estilo McKinsey/YC: verbos de accion, numeros con contexto

### 5.9 Self-Calibration Loop
- Evaluator → Adjuster → Memory
- Anti-overfitting: sugerencias que solo benefician un cliente se flagean
- Regression detection: score actual < previous - 5 puntos
- Trend analysis: improving/stable/degrading sobre ultimas N ejecuciones

---

## 6. Dependencias

### 6.1 Dependencias Internas (dentro de core/valinor/)

| Modulo | Depende de |
|--------|-----------|
| run.py | agents.cartographer, agents.query_builder, pipeline, deliver, gates, config |
| pipeline.py | agents.analyst/sentinel/hunter, knowledge_graph, verification, claude_agent_sdk, sqlalchemy |
| knowledge_graph.py | (standalone — solo stdlib + structlog) |
| verification.py | knowledge_graph (opcional), sqlalchemy (opcional para active requery) |
| cartographer.py | tools.db_tools, tools.memory_tools, claude_agent_sdk |
| query_builder.py | query_generator (opcional), knowledge_graph (opcional) |
| query_generator.py | knowledge_graph |
| narrators/*.py | claude_agent_sdk, system_prompts |
| calibration/*.py | (standalone — structlog) |
| discovery/*.py | (standalone — sqlalchemy, structlog) |
| quality/*.py | sqlalchemy, numpy, scipy (opcional), statsmodels (opcional) |
| vaire/*.py | (standalone — weasyprint opcional) |
| nl/vanna_adapter.py | vanna, anthropic SDK |

### 6.2 Dependencias Externas

| Paquete | Uso | Criticidad |
|---------|-----|------------|
| claude_agent_sdk | Agentes LLM (query, tool, MCP) | CRITICO |
| sqlalchemy | Conexion DB, introspection, queries | CRITICO |
| structlog | Logging estructurado | ALTO |
| pydantic | Schemas de output (v2) | ALTO |
| rich | CLI progress/panels | MEDIO |
| numpy | Statistical checks, anomaly detection | MEDIO |
| scipy | Chi-square (Benford), z-score | OPCIONAL |
| statsmodels | STL decomposition, cointegration | OPCIONAL |
| pandas | Excel/CSV ingestion, Vanna training data | MEDIO |
| weasyprint | PDF rendering | OPCIONAL |
| vanna | NL→SQL | OPCIONAL |

---

## 7. Fortalezas

### 7.1 Arquitectura Anti-Hallucination Robusta
El sistema tiene multiples capas de proteccion contra numeros fabricados: Number Registry, provenance tagging, triple verification, frozen baseline, role-based filtering, cross-report consistency checks. Este es el diferenciador mas fuerte del sistema.

### 7.2 Zero Hardcoded ERP Knowledge
El KnowledgeGraph, QueryGenerator, Discovery pipeline, y la mayoria de quality gates operan sin conocimiento hardcoded de ningun ERP. Todo se descubre de los datos. Esto hace al sistema genuinamente source-agnostic.

### 7.3 Self-Calibration Loop
El ciclo Evaluator → Adjuster → Memory con anti-overfitting es un patron sofisticado que permite al sistema mejorar iterativamente sin sobreajustarse a un cliente especifico.

### 7.4 Comprehensive Data Quality Suite
9 checks estadisticos incluyendo Benford, STL decomposition, cointegration, CUSUM, currency guard, y factor model. Nivel de hedge fund / Big 4 audit.

### 7.5 Pipeline Determinista donde Posible
Phase 1 del Cartographer, Query Builder, Verification Engine, Quality Gates, Baseline Computation — todos son deterministas (zero LLM cost). El LLM se usa solo donde agrega valor irreemplazable.

### 7.6 Reconciliation Pattern
El arbiter Haiku que resuelve conflictos numericos entre agentes es un patron bien implementado que evita el problema comun de agentes divergentes.

---

## 8. Debilidades

### 8.1 `pipeline.py` es un God Module
Con 1041 lineas, pipeline.py contiene 7 funciones de stage diferentes, cada una con logica sustancial. Deberia descomponerse en modulos por stage. El riesgo: un cambio en reconcile_swarm puede romper gate_calibration si comparten state implicitamente.

### 8.2 Duplicacion de Codigo de Parseo de Findings
`_parse_findings_from_output()` se repite en pipeline.py y deliver.py con logica casi identica (buscar JSON array en texto, fallback a regex de IDs). Deberia extraerse a un modulo shared.

### 8.3 SQL Injection Surface en `gate_calibration()`
`base_filter` del entity_map se interpola directamente en SQL queries (`f"SELECT COUNT(*) FROM {table} WHERE {base_filter}"`). Aunque hay `_is_safe_identifier()` para table names, el base_filter puede contener SQL arbitrario. La verificacion del Cartographer mitiga esto, pero un entity_map corrupto podria ser explotado.

### 8.4 Factor Model Hardcoded a Odoo
`factor_model.py` tiene queries hardcoded a `account_move` con `move_type = 'out_invoice'`. Contradice el principio "zero hardcoded ERP knowledge" del resto del sistema. Deberia usar entity_map como los demas modulos.

### 8.5 Error Handling Silencioso en Agentes
Los 3 agentes de analisis y 4 narrators usan `except Exception: pass` al iterar sobre mensajes del SDK. Si un agente falla completamente, retorna un output vacio sin indicar el error. Esto puede ocultar problemas criticos.

### 8.6 Sentinel Patterns Hardcoded a Odoo
`sentinel_patterns.py` tiene 15 patterns con SQL hardcoded para `account_move`, `res_partner`, `sale_order` (tablas Odoo). No son source-agnostic como el resto del sistema.

### 8.7 Schemas Pydantic No Integrados al Pipeline Principal
`schemas/agent_outputs.py` define CartographerOutput, AnalystOutput, etc. pero el pipeline principal (`run.py`, `pipeline.py`) sigue usando dicts crudos. Los schemas estan disponibles pero no se usan para validacion en runtime.

### 8.8 Narrators Secuenciales
Los 4 narrators se ejecutan secuencialmente en `run_narrators()`. Dado que son independientes, podrian ejecutarse en paralelo como los agentes de analisis. Esto duplica el wall-clock time de Stage 4 innecesariamente.

### 8.9 REPEATABLE READ Fragil
La logica de isolation level usa un try/except global que cae a default isolation si REPEATABLE READ falla por cualquier razon (no solo incompatibilidad). Un error transitorio de conexion descartaria silenciosamente la garantia de consistency.

### 8.10 Memory Build No Valida Findings
`build_memory()` en deliver.py extrae findings con `_extract_findings()` que parsea JSON de texto libre. Si el formato del agente cambia sutilmente, la memoria almacenara findings vacios sin warning.

---

## 9. Recomendaciones 2026

### 9.1 Descomponer `pipeline.py` en Modulos por Stage
Crear `stages/execute.py`, `stages/calibration.py`, `stages/reconcile.py`, `stages/narrate.py`. pipeline.py queda como orquestador thin que delega.

### 9.2 Integrar Pydantic Schemas en Runtime
Usar AnalystOutput.from_agent_dict() y SentinelOutput.from_agent_dict() en pipeline.py despues de cada agente. Fallar explicito si parse_error != None. Esto atrapa regresiones de formato temprano.

### 9.3 Parametrizar SQL en Quality Checks
Reemplazar queries hardcoded en `factor_model.py` y `sentinel_patterns.py` para que usen entity_map. Para sentinel_patterns: generar SQL parametrizado desde KG en lugar de tablas hardcoded.

### 9.4 Paralelizar Narrators
Cambiar `run_narrators()` de secuencial a `asyncio.gather()`. Cada narrator es independiente. Estimacion: 2-3x speedup en Stage 4.

### 9.5 Sanitizar base_filter
Agregar validacion de base_filter en gate_calibration() antes de interpolarlo en SQL. Opciones: parametrizar con sqlalchemy text() bindings, o parsear y reconstruir con whitelist de operadores.

### 9.6 Extraer Parsing de Findings a Modulo Shared
Crear `core/valinor/parsing.py` con la logica de parseo de JSON arrays y finding IDs. Usado por pipeline.py, deliver.py, verification.py.

### 9.7 Mejorar Error Handling en Agentes
Reemplazar `except Exception: pass` con logging explicito del error. Propagar excepciones al caller con context (agent_name, stage, turn_count).

### 9.8 Agregar Telemetria/Metricas
El sistema tiene hooks para DQ_CHECKS_TOTAL (Prometheus counter en data_quality_gate.py). Extender a: agent_duration_seconds, query_error_rate, verification_rate_histogram, reconciliation_conflicts.

### 9.9 Implementar Streaming de Reportes
Los narrators acumulan todo el output en memoria antes de retornar. Para reportes largos con datos de muchos clientes, implementar streaming del markdown.

### 9.10 Test Coverage para KG y Verification Engine
knowledge_graph.py y verification.py son modulos criticos con logica compleja (Dijkstra, active requery, derived value checking) que se beneficiarian enormemente de unit tests exhaustivos con edge cases.
