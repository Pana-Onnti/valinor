# Investigacion 02 — Sistema de Agentes de Valinor (`core/valinor/agents/`)

**Fecha:** 2026-03-22
**Autor:** Analisis automatizado (Claude Opus 4.6)
**Scope:** `core/valinor/agents/`, `core/valinor/pipeline.py`, `core/valinor/run.py`, modulos de soporte

---

## 1. Resumen Ejecutivo

Valinor implementa un **pipeline de analisis de inteligencia de negocio de 6 etapas** (Stages 0-5) orquestado por `pipeline.py` y `run.py`. El sistema consta de **12 agentes funcionales** organizados en 4 capas: descubrimiento (Cartographer), generacion de queries (QueryBuilder/QueryGenerator), analisis paralelo (Analyst, Sentinel, Hunter), y narracion audience-specific (CEO, Controller, Sales, Executive). Adicionalmente, existe un agente de renderizado frontend (Vaire) y un sistema de verificacion post-hoc (VerificationEngine).

La arquitectura sigue un patron **Swarm con Frozen Brief**: los agentes de analisis reciben un contexto compartido inmutable (`baseline`) con provenance tags, trabajan en paralelo sin comunicacion directa, y sus resultados pasan por un nodo de reconciliacion (Haiku arbiter) antes de llegar a los narradores. No hay estado compartido mutable entre agentes — toda coordinacion se hace via datos inmutables pasados por el orquestador.

Todos los agentes LLM usan **Claude Agent SDK** con modelo Sonnet, excepto el arbiter de reconciliacion que usa Haiku.

---

## 2. Arquitectura de Agentes

### 2.1 Pipeline de Ejecucion (6 Stages)

```
Stage 0: Intake (Excel/CSV → SQLite)
   ↓
Stage 1: Cartographer (Schema Discovery)
   ↓  ← Guard Rail loop (Stage 1.5): SQL COUNTs verifican base_filter
   ↓     Maximo 2 retries con feedback estructurado (Reflexion pattern)
   ↓
Stage 2: Query Builder (deterministic SQL generation)
   ↓
Stage 2.5: Query Execution (REPEATABLE READ isolation)
   ↓  → compute_baseline() → Frozen Brief con provenance
   ↓
Stage 3: Analysis Agents [PARALELO]
   ├── Analyst   (financial intelligence)
   ├── Sentinel  (data quality + fraud)
   └── Hunter    (opportunity detection)
   ↓
Stage 3.5: Reconciliation Node (Haiku arbiter resuelve conflictos >2x)
   ↓
Stage 3.75: Verification-aware Finding Preparation
   ↓  → Filtrado por rol: CEO solo ve VERIFIED, Sales ve VERIFIED+UNVERIFIABLE
   ↓
Stage 4: Narrators [SECUENCIAL]
   ├── CEO Briefing      (5 numeros + 3 decisiones)
   ├── Controller Report (P&L, provisiones, anomalias)
   ├── Sales Report      (call list, reactivacion, cross-sell)
   └── Executive Summary (top 7 hallazgos + calendario de acciones)
   ↓
Stage 5: Delivery (archivos + memoria persistente)
   └── Vaire Agent (HTML KO Report + PDF + WhatsApp summary)
```

### 2.2 Mapa de Archivos

| Archivo | Rol | LLM? | Modelo |
|---------|-----|------|--------|
| `agents/__init__.py` | Package marker | No | - |
| `agents/cartographer.py` | Schema discovery | Si | Sonnet |
| `agents/query_builder.py` | SQL generation (templates) | No | - |
| `agents/query_generator.py` | SQL generation (KG-guided) | No | - |
| `agents/analyst.py` | Financial analysis | Si | Sonnet |
| `agents/sentinel.py` | Data quality analysis | Si | Sonnet |
| `agents/sentinel_patterns.py` | 15 anomaly/fraud SQL patterns | No | - |
| `agents/hunter.py` | Opportunity detection | Si | Sonnet |
| `agents/narrators/ceo.py` | CEO briefing | Si | Sonnet |
| `agents/narrators/controller.py` | Controller report | Si | Sonnet |
| `agents/narrators/sales.py` | Sales report | Si | Sonnet |
| `agents/narrators/executive.py` | Executive summary | Si | Sonnet |
| `agents/narrators/system_prompts.py` | Prompt building + context injection | No | - |
| `agents/narrators/quality_certifier.py` | Post-processing: confidence badges | No | - |
| `agents/vaire/agent.py` | HTML/PDF/WhatsApp rendering | No | - |
| `agents/vaire/pdf_renderer.py` | WeasyPrint PDF generation | No | - |
| `agents/vaire/templates/ko_report.py` | HTML template (D4C design tokens) | No | - |
| `pipeline.py` | Master orchestrator | Si (Haiku) | Haiku (arbiter) |
| `run.py` | CLI entry point | No | - |

---

## 3. Tipos de Agentes

### 3.1 Agente de Descubrimiento: Cartographer

**Archivo:** `agents/cartographer.py` (315 lineas)
**Funcion:** `run_cartographer(client_config, calibration_feedback=None) → dict`

Patron de 2 fases:
- **Fase 1 (Deterministic):** Pre-scan de columnas discriminadoras usando SQLAlchemy `inspect()`. Busca patrones como `ad_client_id`, `issotrx`, `docstatus` en tablas con nombres de negocio (invoice, payment, order...). Cero costo LLM. Limita a 6 tablas y 4 columnas discriminadoras por tabla.
- **Fase 2 (Sonnet):** Mapeo profundo con Claude Agent SDK. Usa MCP tools: `connect_database`, `introspect_schema`, `sample_table`, `classify_entity`, `probe_column_values`, `write_artifact`. Max 35 turns. Output: `entity_map.json` con entidades clasificadas (MASTER/TRANSACTIONAL/CONFIG/BRIDGE).

Patron clave: **Explore-Verify-Commit** con **Reflexion retry loop**. Si el Guard Rail (Stage 1.5) falla, el feedback estructurado se reinyecta al prompt como `calibration_feedback`. Maximo 2 retries.

### 3.2 Agentes de Generacion de Queries

#### QueryBuilder (`query_builder.py`, 714 lineas)
- **Deterministic** — cero LLM, puro Python
- 17 templates SQL parametrizados cubriendo: revenue, AR, aging, debtors, dormant customers, retention, data quality, seasonality
- Templates usan `{entity_filter}` placeholders inyectados desde `base_filter`
- Funcion `prioritize_entities()` prioriza por score = weight + row_count_normalizado, con multiplicador 2x para focus_tables
- Cap en MAX_ENTITIES=20

#### QueryGenerator (`query_generator.py`, 793 lineas)
- **KG-guided** — usa Knowledge Graph para JOINs automaticos via BFS
- Clase `SQLBuilder`: fluent API con `join_to()` que consulta el KG para ON conditions
- Clase `QueryGenerator`: genera queries por tipo semantico (TRANSACTIONAL, MASTER), no por nombre
- Fallback: si KG falla, usa `build_queries()` de templates estaticos
- `build_queries_adaptive()` intenta KG primero, luego fallback

### 3.3 Agentes de Analisis (Stage 3) — Ejecutan en Paralelo

Los tres comparten interfaz identica:
```python
async def run_X(query_results, entity_map, memory, baseline, kg=None) → dict
```

#### Analyst (`analyst.py`, 107 lineas)
- **Dominio:** Financial intelligence
- **Output:** JSON array de findings con id `FIN-XXX`, severity, headline, evidence, value_eur, value_confidence, action
- **Foco:** Revenue trends, customer concentration, margin analysis, seasonality, YoY comparisons
- **Regla anti-hallucination:** Valores EUR deben derivar de baseline o query_results. Si no, marcar [ESTIMADO]

#### Sentinel (`sentinel.py`, 105 lineas)
- **Dominio:** Data quality
- **Output:** JSON array con id `DQ-XXX`
- **Foco:** Duplicates, null rates, orphan records, outliers, inconsistencias
- **Complemento:** `sentinel_patterns.py` — 15 patrones ACFE de fraude financiero con SQL templates (ghost vendor, round amount concentration, split invoices, Benford's law, etc.)

#### Hunter (`hunter.py`, 111 lineas)
- **Dominio:** Sales/Opportunities
- **Output:** JSON array con id `HUNT-XXX`
- **Foco:** Churn risk, dormant customers, cross-sell, pricing anomalies, debt recovery
- **Regla de honestidad:** No inventar nombres de clientes. Usar los de query_results o declarar ausencia

### 3.4 Narradores (Stage 4) — Ejecutan Secuencialmente

Todos comparten interfaz similar:
```python
async def narrate_X(findings, entity_map, memory, client_config, baseline, ...) → str
```

#### CEO Narrator (`ceo.py`, 109 lineas)
- **Output:** 5 Numbers That Matter + 3 Decisions This Week
- **Restriccion:** Max 1 pagina. Valores medidos sin asterisco, estimados con *(estimado)*
- **Freshness rule:** Si datos >14 dias, nota de advertencia

#### Controller Narrator (`controller.py`, 134 lineas)
- **Output:** P&L summary, provisions/debt, DQ alerts, anomalias, indicadores prospectivos
- **Recibe extra:** `query_results` completos para cross-check
- **Tags obligatorios:** [MEDIDO] / [ESTIMADO] / [INFERIDO] por cada valor EUR
- **Referencia fuentes:** Cada claim cita query o tabla origen

#### Sales Narrator (`sales.py`, 133 lineas)
- **Output:** Call list top 15, reactivacion plan, cross-sell, restricciones, quick wins
- **Recibe extra:** `query_results` customer-level (dormant_customer_list, customer_concentration)
- **Lenguaje:** Plain language para vendedores, no contable
- **Prioridad:** Revenue impact x ease of action

#### Executive Narrator (`executive.py`, 144 lineas)
- **Output:** Resumen en 30 Segundos + Top 7 Hallazgos + Reconciliacion + Calendario de Acciones
- **Es el master narrator:** Reconcilia contradicciones, rankea por IMPACT x URGENCY x SURPRISE
- **System prompt enriquecido:** Usa `build_executive_system_prompt()` que inyecta DQ context, factor model, segmentacion, anomalias estadisticas, CUSUM warnings, Benford alerts, y hallazgos persistentes

### 3.5 Agente de Renderizado: Vaire

**Archivo:** `agents/vaire/agent.py` (200 lineas)
**Clase:** `VaireAgent` (no es async, no usa LLM)

- **Input:** `VaireInput` (company_name, run_date, executive_report markdown, findings, metrics)
- **Output:** `VaireOutput` (HTML, PDF bytes, WhatsApp summary)
- **Funciones:**
  - `_parse_findings()` — Extrae findings del markdown ejecutivo usando regex
  - `_enforce_loss_framing()` — Convierte "podrias ganar" → "estas perdiendo" (psicologia behavioral)
  - `_build_whatsapp_summary()` — Texto plano conciso para WhatsApp
- **Template:** KO Report v2 con design tokens D4C (dark theme, Inter + JetBrains Mono, badges por severidad)
- **PDF:** WeasyPrint con graceful fallback si no esta instalado

---

## 4. Orquestacion

### 4.1 Patron Central: Pipeline Secuencial con Paralelismo Interno

El orquestador principal esta en `run.py:main()` y `pipeline.py`. La ejecucion es:

1. **Secuencial** entre stages (cada stage depende del anterior)
2. **Paralelo** dentro de Stage 3 (`asyncio.gather` de analyst, sentinel, hunter)
3. **Secuencial** en Stage 4 (narrators no se paralelizan)

### 4.2 Guard Rail Pattern (Stage 1.5)

`pipeline.py:gate_calibration()` — verificacion deterministica sin LLM:
- Para cada entidad con `base_filter`: ejecuta 3 SQL COUNTs
  1. `COUNT(*)` total > 0
  2. `COUNT(*) WHERE filter` > 0 (filter no elimina todo)
  3. `SUM(amount)` no null para TRANSACTIONAL
- Chequeo adicional: FK orphan detection via LEFT JOIN
- Si falla: feedback estructurado se reinyecta al Cartographer (max 2 retries)

### 4.3 Reconciliation Node (Stage 3.5)

`pipeline.py:reconcile_swarm()` — detecta conflictos numericos entre agentes:
- Agrupa findings por domain
- Si value_eur difiere >2x entre agentes (mismo domain, overlap de keywords en headline): CONFLICTO
- Invoca **Haiku arbiter** con frozen baseline como ground truth
- Arbiter selecciona el valor mas defensible (no promedia) y explica discrepancia
- Output: `_reconciliation` metadata adjunta a findings

### 4.4 Verification-Aware Preparation (Stage 3.75)

`pipeline.py:prepare_narrator_context()` — filtrado por rol:
- **CEO:** Solo findings VERIFIED
- **Sales:** VERIFIED + UNVERIFIABLE (no FAILED, no retracciones)
- **Controller:** Todo con tags explicitos
- **Executive:** Todo incluyendo detalles de retraccion

### 4.5 Quality Gates

`gates.py`:
- `gate_cartographer()`: PASS si >=2 de {customers, invoices, products, payments} con confidence >0.7
- `gate_analysis()`: PASS si >=2 de 3 agentes produjeron findings
- `gate_sanity()`: Post-delivery sanity checks
- `gate_monetary_consistency()`: Verifica consistencia monetaria entre reports y baseline

---

## 5. Estado y Persistencia

### 5.1 Memoria del Swarm

- **Carga:** `config.py:load_memory(client)` al inicio
- **Inyeccion:** Se pasa como `memory` a todos los agentes de analisis y narradores
- **Actualizacion:** `deliver.py:build_memory()` al final del pipeline
- **Almacenamiento:** `memory/{client}/swarm_memory_{period}.json`

### 5.2 Que Contiene la Memoria

Segun los prompts de agentes, la memoria puede incluir:
- `run_timestamp` — timestamp del ultimo analisis
- `data_quality_context` — estado de calidad de datos
- `factor_model_context` — descomposicion por factores (clientes activos, ticket promedio, etc.)
- `segmentation_context` — segmentacion de clientes (Champions, Growth, etc.)
- `statistical_anomalies` — anomalias estadisticas
- `sentinel_patterns` — patrones de fraude activos
- `cusum_warning` — rupturas estructurales detectadas
- `benford_warning` — alertas de Ley de Benford
- `query_evolution_context` — evoluciones en queries vacias vs. de alto valor
- `run_history_summary` — resumen historico con persistent_findings
- `adaptive_context` — contexto adaptativo (currency, etc.)

### 5.3 Artefactos en Disco

- `output/{client}/{period}/` — reportes y run_log
- `output/{client}/discovery/entity_map.json` — mapa de entidades del Cartographer
- `memory/{client}/swarm_memory_{period}.json` — memoria persistente

### 5.4 Run Log

Struct `run_log` en `run.py` registra duracion y resultados por stage, incluyendo calibration status, agent completions, reconciliation conflicts.

---

## 6. Comunicacion Inter-agente

### 6.1 No Hay Comunicacion Directa

Los agentes **nunca se comunican entre si**. Todo fluye a traves del orquestador:

```
Cartographer → entity_map → QueryBuilder → query_pack → Execute → query_results
                                                                     ↓
                                                              compute_baseline()
                                                                     ↓
                                                              baseline (frozen brief)
                                                                     ↓
                                              ┌──────────────────────┼──────────────────────┐
                                              ↓                      ↓                      ↓
                                           Analyst              Sentinel                Hunter
                                              ↓                      ↓                      ↓
                                              └──────────────────────┼──────────────────────┘
                                                                     ↓
                                                              reconcile_swarm()
                                                                     ↓
                                                              findings + _reconciliation
                                                                     ↓
                                              ┌──────────────────────┼──────────────────────┐
                                              ↓                      ↓                      ↓
                                           CEO              Controller/Sales          Executive
```

### 6.2 Contratos de Datos

- **entity_map:** Dict con `entities`, `relationships`. Cada entidad tiene `table`, `key_columns`, `type`, `base_filter`, `row_count`, `confidence`.
- **baseline (Frozen Brief):** Dict plano con metricas + `_provenance` dict que mapea cada metrica a su source_query, row_count, executed_at, confidence.
- **findings:** Dict con agent_name → `{agent, output}`. Output es texto libre con JSON embebido.
- **structured findings:** JSON array de `{id, severity, headline, evidence, value_eur, value_confidence, action, domain}`.

### 6.3 Provenance Tagging

El `compute_baseline()` implementa provenance-tagged handoff:
```python
baseline["_provenance"]["total_revenue"] = {
    "source_query": "total_revenue_summary",
    "row_count": 1,
    "executed_at": "2026-03-22T...",
    "confidence": "measured",
}
```

---

## 7. Patrones de Diseno Identificados

### 7.1 Patrones Arquitectonicos

| Patron | Implementacion | Referencia |
|--------|---------------|------------|
| **Frozen Brief** | `compute_baseline()` — metricas inmutables con provenance | Anthropic harness |
| **Explore-Verify-Commit** | Cartographer → Guard Rail → retry loop | Reflexion (arXiv:2303.11366) |
| **Debate + Judge** | `reconcile_swarm()` — Haiku arbiter selecciona valor | Multi-Agent Collaboration (arXiv:2501.06322) |
| **Schema-Then-Data** | Cartographer Phase 1 (schema) → Phase 2 (data sampling) | Anthropic harness |
| **ReFoRCE Column Exploration** | `probe_column_values` en Cartographer | arXiv:2502.00675 |
| **KG-guided SQL** | `QueryGenerator` + `SQLBuilder` con BFS pathfinding | SchemaGraphSQL (arXiv:2505.18363) |
| **Output KO** | Loss framing en narrators + Vaire | Delta4C methodology |
| **Verification-aware routing** | `prepare_narrator_context()` filtra por rol | CoVe (Meta, ACL 2024) |

### 7.2 Patrones de Anti-Hallucination

1. **Baseline como ground truth:** Todos los agentes reciben `baseline` con numeros medidos. Instrucciones prohiben inventar EUR values.
2. **Provenance tags:** Cada metrica lleva su query origen y timestamp.
3. **Confidence labeling:** MEDIDO / ESTIMADO / INFERIDO obligatorio en narradores.
4. **Customer name grounding:** Agentes instruidose a usar nombres de `query_results`, nunca inventar.
5. **Data freshness caveat:** Si datos >14 dias, se flagea en cada finding dependiente.
6. **Reconciliation node:** Conflictos >2x arbitrados por Haiku con baseline como referencia.
7. **Verification engine:** Triple verification (claim decomposition + re-execution + number registry).
8. **Quality certifier:** Post-processing que agrega badges [CONFIRMED/PROVISIONAL] segun DQ score.

### 7.3 Patrones de Safety

1. **REPEATABLE READ isolation:** Queries ejecutadas en un snapshot consistente.
2. **SQL identifier validation:** `_is_safe_identifier()` previene injection.
3. **ROW_COUNT_CAP = 100,000:** Previene dominio injusto de tablas grandes en priorizacion.
4. **MAX_ENTITIES = 20:** Cap para evitar explosion de queries.
5. **Graceful degradation:** Si REPEATABLE READ no soportado, continua con warning.

---

## 8. Fortalezas

### 8.1 Diseno Solido

- **Separacion clara de concerns:** Cada agente tiene un rol unico y bien definido. No hay overlap funcional.
- **Frozen Brief pattern:** Elimina la causa raiz de numeros divergentes entre agentes — todos parten del mismo baseline inmutable.
- **Provenance tracking:** Cada numero lleva su cadena de custodia. Esto es raro en sistemas de agentes y extremadamente valioso para auditoria.
- **Pipeline deterministic-first:** Stages 1 (Phase 1), 2, 2.5 no usan LLM. Solo se invoca LLM cuando hay decision ambigua.

### 8.2 Anti-Hallucination Excepcional

- El sistema tiene **7 capas de proteccion** contra hallucinations numericas.
- La combinacion baseline + provenance + verification engine + quality certifier es mas robusta que la mayoria de sistemas multi-agente comparables.
- Instrucciones en prompts son explicitas y detalladas sobre que esta permitido estimar y que no.

### 8.3 Audience-Aware Delivery

- 4 narradores para 4 audiencias distintas con diferente nivel de detalle y filtrado de verificacion.
- Vaire convierte a HTML/PDF/WhatsApp — cobertura de delivery channels.
- Loss framing automatico en el renderizado final.

### 8.4 Resiliencia

- Guard Rail con retry loop permite auto-correccion sin intervencion humana.
- `asyncio.gather(return_exceptions=True)` evita que un agente fallido mate al pipeline.
- Gates multiples a lo largo del pipeline (cartographer, analysis, sanity, monetary consistency).

### 8.5 Extensibilidad del Sentinel

- 15 patrones ACFE con SQL templates parametrizados — facil agregar nuevos.
- Ley de Benford, CUSUM, ghost vendors — cobertura profesional de deteccion de fraude.

---

## 9. Debilidades

### 9.1 Narradores Secuenciales Sin Justificacion Tecnica

Los 4 narradores ejecutan secuencialmente (`run_narrators()` usa un loop, no `asyncio.gather`). No hay dependencia entre ellos — podrian ejecutar en paralelo, reduciendo latencia total de Stage 4 a ~1/4.

### 9.2 Parsing Fragil de Findings

`_parse_findings_from_output()` en `pipeline.py` usa regex para extraer JSON de texto libre del agente. Si el agente produce JSON malformado o con formato inesperado, los findings se pierden silenciosamente. No hay validacion con Pydantic ni schema enforcement.

### 9.3 Exception Swallowing Generalizado

Todos los agentes de analisis (analyst, sentinel, hunter) y narradores usan:
```python
except Exception:
    pass
```
Esto significa que errores del Claude Agent SDK se traguen sin logging. Un agente podria fallar completamente y el pipeline no sabria por que.

### 9.4 Acoplamiento con Claude Agent SDK

Todos los agentes importan directamente de `claude_agent_sdk`. Si se quisiera cambiar de proveedor LLM o usar un modelo local, habria que reescribir cada agente. No hay abstraccion intermedia (e.g., un `AgentRunner` generico).

### 9.5 No Hay Retry para Agentes de Analisis

El Cartographer tiene retry loop con feedback (Reflexion), pero Analyst/Sentinel/Hunter no tienen ninguno. Si Sonnet produce output malformado, no hay segundo intento.

### 9.6 Singleton Knowledge Graph

El KG se construye una vez y se pasa opcionalmente. Si el entity_map tiene errores parciales, el KG hereda esos errores sin correccion.

### 9.7 Ausencia de Metricas/Observabilidad

No hay tracing (OpenTelemetry), no hay metricas de latencia por agente, no hay token counting. `run_log` captura duraciones pero no costos. Para un sistema productivo, esto es insuficiente.

### 9.8 Vaire Desacoplado del Pipeline Principal

`VaireAgent` existe como clase pero no se invoca en `run.py` ni en `pipeline.py`. El pipeline genera reportes markdown pero no los renderiza a HTML/PDF automaticamente. Vaire parece un componente preparado pero no integrado.

### 9.9 Query Results Como Texto Libre en Prompts

Los agentes de analisis reciben `query_results` serializado como JSON en el prompt. Para datasets grandes, esto puede exceder la ventana de contexto. No hay truncamiento inteligente ni resumen previo.

### 9.10 Memory Sin Versionado

La memoria se sobreescribe por periodo (`swarm_memory_{period}.json`). No hay diff entre runs, no hay merge de conocimiento cross-period, y no hay TTL para hallazgos obsoletos.

---

## 10. Recomendaciones 2026

### 10.1 Paralelizar Narradores (Quick Win)

Cambiar `run_narrators()` de loop secuencial a `asyncio.gather()`. Los 4 narradores son independientes. Impacto estimado: reduccion de 75% en latencia de Stage 4.

### 10.2 Structured Output con Pydantic

Reemplazar el parsing regex de findings por structured output:
- Definir `Finding` como modelo Pydantic con validacion
- Usar `response_format` o tool calling para forzar schema
- Eliminar `_parse_findings_from_output()` y su fragilidad

### 10.3 Observabilidad (OpenTelemetry + Token Counting)

- Agregar spans por agente con latencia, token usage, model version
- Dashboard Grafana/Datadog para monitoring de costos y calidad
- Alertas si un agente excede X tokens o Y segundos

### 10.4 Agent Runner Abstraction

Crear `AgentRunner` que encapsule:
- Retry logic configurable
- Timeout handling
- Structured output parsing
- Logging/tracing
- Fallback de modelo (Sonnet → Haiku para degradacion graceful)

Esto elimina la repeticion de try/except en cada agente y desacopla del SDK.

### 10.5 Integrar Vaire en el Pipeline

Conectar `VaireAgent.render()` en Stage 5 (Delivery). El pipeline ya genera markdown — solo falta parsear findings y pasar a Vaire para HTML/PDF/WhatsApp.

### 10.6 Logging de Errores en Agentes

Reemplazar `except Exception: pass` por:
```python
except Exception as e:
    logger.error("Agent failed", agent=name, error=str(e), exc_info=True)
```
Minimo esfuerzo, maximo impacto en debuggability.

### 10.7 Truncamiento Inteligente de Context

Para query_results grandes, implementar:
- Top-N rows por query (ya existe LIMIT en templates, pero no en la inyeccion al prompt)
- Resumen estadistico para queries con >50 rows
- Referencia a artefacto en disco si el resultado excede threshold

### 10.8 Memory Con Diff y TTL

- Calcular delta entre runs consecutivos
- TTL para findings: auto-expirar hallazgos no confirmados despues de N runs
- Cross-period merge: combinar insights de Q1+Q2 para tendencias anuales

### 10.9 Retry Loop para Agentes de Analisis

Implementar Reflexion-lite para Analyst/Sentinel/Hunter:
- Si output no parsea como JSON valido → retry con instruccion correctiva
- Max 1 retry (no 2 como Cartographer, para mantener costos)
- Guardar el parsing error en run_log para diagnostico

### 10.10 Evaluacion Continua (Evals)

- Definir golden datasets con findings esperados
- Correr pipeline mensualmente contra goldens
- Medir precision/recall de findings y exactitud de valores EUR
- Detectar regression si un agente empeora entre versiones de modelo

---

## Apendice A: Sentinel Patterns (15 patrones ACFE)

| ID | Nombre | Severidad | Categoria |
|----|--------|-----------|-----------|
| `ghost_vendor` | Proveedor fantasma | CRITICAL | fraud_risk |
| `round_amount_concentration` | Montos redondos sospechosos | MEDIUM | fraud_risk |
| `split_invoices_threshold` | Facturas divididas para evadir limite | HIGH | fraud_risk |
| `customers_no_activity` | Clientes activos sin actividad | MEDIUM | operational |
| `credit_note_ratio` | Ratio de notas de credito anormal | HIGH | financial |
| `duplicate_invoices` | Facturas duplicadas | HIGH | fraud_risk |
| `weekend_invoices` | Facturas en fin de semana | MEDIUM | fraud_risk |
| `end_of_period_spike` | Concentracion de ingresos al cierre | HIGH | financial |
| `inactive_vendor_large_payment` | Pago grande a proveedor inactivo | HIGH | fraud_risk |
| `margin_compression_by_product` | Compresion de margen por producto | MEDIUM | financial |
| `overdue_receivables_concentration` | Concentracion de cartera vencida | HIGH | financial |
| `journal_entry_without_invoice` | Asientos manuales sin factura | HIGH | fraud_risk |
| `purchase_without_receipt` | Compra sin recepcion | MEDIUM | fraud_risk |
| `excessive_discounts` | Descuentos excesivos por vendedor | MEDIUM | financial |
| `benford_first_digit_invoices` | Anomalia Ley de Benford | HIGH | fraud_risk |

## Apendice B: Query Templates (17 templates)

| ID | Dominio | Entidades Requeridas |
|----|---------|---------------------|
| `total_revenue_summary` | financial | invoices |
| `ar_outstanding_actual` | credit | payments, invoices |
| `dormant_customer_list` | sales | invoices, customers |
| `never_invoiced_customers` | sales | invoices, customers |
| `orders_without_invoices` | financial | orders, invoices |
| `revenue_by_period` | financial | invoices |
| `customer_concentration` | financial | invoices, customers |
| `revenue_yoy` | financial | invoices |
| `aging_analysis` | credit | payments, invoices |
| `top_debtors` | credit | payments, invoices, customers |
| `customer_retention` | sales | invoices, customers |
| `null_analysis` | data_quality | invoices |
| `duplicate_detection` | data_quality | invoices |
| `data_freshness` | data_quality | invoices |
| `monthly_seasonality` | financial | invoices |

## Apendice C: Reglas Anti-Hallucination por Agente

| Agente | Regla Principal |
|--------|----------------|
| Analyst | EUR derivados de baseline o query_results. Si no, marcar [ESTIMADO] |
| Sentinel | Multi-tenant = CRITICAL. Siempre incluir table + column name |
| Hunter | No inventar nombres de clientes. Estimaciones conservadoras > optimistas |
| CEO | Medidos sin asterisco. Estimados con *(estimado)*. Datos >14d = warning |
| Controller | Cada valor con [MEDIDO/ESTIMADO/INFERIDO] + fuente de dato |
| Sales | Nombres reales con DB ID. Si no hay nombres: declarar ausencia explicitamente |
| Executive | Reconciliar contradicciones. No ocultar desacuerdos entre agentes |
