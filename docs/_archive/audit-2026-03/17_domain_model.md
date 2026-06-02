# 17 — Domain Model Analysis: Valinor SaaS

**Fecha**: 2026-03-22
**Scope**: `core/valinor/` — pipeline de analisis financiero multi-agente
**Archivos analizados**: 22 archivos Python en 7 modulos

---

## Resumen

Valinor implementa un **pipeline de analisis financiero multi-agente** (swarm) que conecta a bases de datos de clientes (ERPs como Odoo, OpenBravo, Tango, o archivos Excel/CSV), descubre su schema automaticamente, ejecuta queries de analisis, y genera reportes ejecutivos tipo KO Report con estructura Minto Pyramid.

El domain model se organiza en torno a tres conceptos centrales:
1. **Los Valar** — 7 agentes con responsabilidades especificas (Cartografo, QueryBuilder, Analista, Centinela, Cazador, Narrador, Vaire)
2. **El Pipeline** — flujo secuencial con stages numerados (0-5) y gates entre cada etapa
3. **Data Quality** — un sistema de verificacion multi-capa que garantiza que los numeros en reportes son trazables a datos reales

El modelo es **schema-agnostic**: mapea tablas reales a entidades universales (Cliente, Transaccion, Producto, Pago, Empleado) independientemente del ERP subyacente.

---

## Entidades Principales

### 1. Agentes (Los Valar)

| Entidad | Archivo | Responsabilidad |
|---------|---------|-----------------|
| `Cartografo` | `agents/cartographer.py` | Descubre y cataloga el schema de la DB del cliente |
| `QueryBuilder` | `agents/query_builder.py` | Construye queries SQL optimizadas (determinista, no LLM) |
| `Analyst` | `agents/analyst.py` | Analisis financiero — revenue, concentracion, estacionalidad |
| `Sentinel` | `agents/sentinel.py` | Data quality monitoring + deteccion de anomalias/fraude |
| `Hunter` | `agents/hunter.py` | Busca oportunidades de negocio y anomalias |
| `Narrador` | `agents/narrators/` | Genera reportes ejecutivos (CEO, Sales, Controller, Executive) |
| `Vaire` | `agents/vaire/` | Renderiza KO Report como HTML/PDF |

Observacion: QueryBuilder es determinista (Python puro), no un agente LLM, aunque usa el mismo schema de output por uniformidad.

### 2. Pipeline & Orchestracion

| Entidad | Archivo | Descripcion |
|---------|---------|-------------|
| `Pipeline` | `pipeline.py` | Orquestador master — 6 stages con gates intermedios |
| `AnalysisJob` | (implicito en `run.py`) | Lifecycle: pending -> running -> quality_check -> analyzing -> narrating -> completed/failed |
| `ClientConfig` | `config.py` | Configuracion por cliente — connection string, ERP type, sector, overrides |

### 3. Schemas de Output (Pydantic v2)

Definidos en `schemas/agent_outputs.py`:

| Modelo | Stage | Contenido |
|--------|-------|-----------|
| `CartographerOutput` | 1 | Entity map con tablas, relaciones, confidence scores |
| `EntityDefinition` | 1 | Tabla individual descubierta — tipo, row_count, key_columns, base_filter |
| `QueryBuilderOutput` | 2 | Lista de CompiledQuery + SkippedQuery |
| `CompiledQuery` | 2 | SQL listo para ejecutar con params y domain |
| `AnalystOutput` | 3a | Findings financieros con severity, value_eur, confidence |
| `AnalystFinding` | 3a | Finding individual — headline, evidence, action, value_eur |
| `SentinelOutput` | 3b | Findings de data quality con tabla/columna afectada |
| `SentinelFinding` | 3b | Finding DQ individual con table, column, severity |

### 4. Knowledge Graph

Definido en `knowledge_graph.py`:

| Estructura | Descripcion |
|------------|-------------|
| `SchemaKnowledgeGraph` | Grafo completo — tablas, edges FK, business concepts |
| `TableNode` | Nodo: tabla con columns, pk_columns, base_filter, filter_columns |
| `FKEdge` | Arista: relacion FK con confidence, weight para Dijkstra |
| `JoinPath` | Camino resuelto entre dos tablas con sql_fragment generado |
| `BusinessConcept` | Concepto de negocio derivado de la semantica de entidades |
| `ColumnProfile` | Perfil estadistico de una columna (distinct_count, top_values, is_low_cardinality) |

### 5. Data Quality Gate

Definido en `quality/data_quality_gate.py`:

| Estructura | Descripcion |
|------------|-------------|
| `DataQualityGate` | Clase principal — corre 9 checks ponderados (score 0-100) |
| `QualityCheckResult` | Resultado de un check individual (passed, severity, score_impact) |
| `DataQualityReport` | Reporte agregado con gate_decision (PROCEED/HALT), confidence_label |

### 6. Verification Engine

Definido en `verification.py`:

| Estructura | Descripcion |
|------------|-------------|
| `VerificationEngine` | Verificacion determinista de claims de agentes vs datos fuente |
| `AtomicClaim` | Claim atomico verificable (numeric, comparison, existence, attribution) |
| `VerificationResult` | Resultado: VERIFIED / FAILED / UNVERIFIABLE / APPROXIMATE |
| `NumberRegistryEntry` | Numero verificado autorizado para uso en reportes (measured/computed/estimated) |
| `VerificationReport` | Reporte completo con verification_rate y number_registry |

### 7. Auto-Discovery

Definido en `discovery/`:

| Estructura | Archivo | Descripcion |
|------------|---------|-------------|
| `SchemaProfiler` | `profiler.py` | Profiling estadistico de tablas — cardinality, nulls, distributions |
| `FKDiscovery` | `fk_discovery.py` | Descubrimiento de FKs implicitas via Inclusion Dependencies |
| `OntologyBuilder` | `ontology_builder.py` | Clasifica tablas en EntityType + BusinessConcept |
| `ColumnProfile` (profiler) | `profiler.py` | Perfil detallado: db_type, null_rate, semantic_type, top_values |
| `TableProfile` | `profiler.py` | Perfil completo de tabla con discriminators, monetary/temporal columns |
| `PKCandidate` | `fk_discovery.py` | Candidato a primary key detectado estadisticamente |
| `FKCandidate` | `fk_discovery.py` | Candidato a foreign key con inclusion_ratio, name_similarity, score |
| `EntityClassification` | `ontology_builder.py` | Clasificacion: entity_type, business_concept, base_filter recomendado |

---

## Value Objects

Los value objects son inmutables y definidos por sus atributos (no tienen identidad propia):

| Value Object | Ubicacion | Descripcion |
|--------------|-----------|-------------|
| `EntityType` (enum) | `schemas/agent_outputs.py` | MASTER / TRANSACTIONAL / CONFIG / BRIDGE / UNKNOWN |
| `Severity` (enum) | `schemas/agent_outputs.py` | critical / warning / opportunity / info |
| `ValueConfidence` (enum) | `schemas/agent_outputs.py` | measured / estimated / inferred |
| `SemanticType` (enum) | `discovery/profiler.py` | monetary / temporal / categorical / identifier / text / boolean / numeric / unknown |
| `BusinessConcept` (enum) | `discovery/ontology_builder.py` | revenue / customer / product / payment / generic_* / unknown |
| `Dimension` (enum) | `verification.py` | EUR / count / percent / days / ratio / unknown |
| `CurrencyCheckResult` | `quality/currency_guard.py` | Resultado de check de moneda — is_homogeneous, dominant_currency, safe_to_aggregate |
| `QualityCheckResult` | `quality/data_quality_gate.py` | Resultado de check DQ individual |
| `StatisticalAnomaly` | `quality/anomaly_detector.py` | Anomalia detectada — method (iqr/zscore/benford), severity, outlier_values |
| `FactorDecomposition` | `quality/factor_model.py` | Descomposicion factorial: client_count × avg_ticket × frequency |
| `FindingProvenance` | `quality/provenance.py` | Lineage de un finding — tables_accessed, confidence_score, dq_warnings |
| `CheckResult` | `calibration/evaluator.py` | Resultado de check de calibracion (score_impact 0-20) |
| `CalibrationScore` | `calibration/evaluator.py` | Score 0-100 con query_coverage, baseline_completeness, verification_rate |
| `DiscriminatorCandidate` | `discovery/profiler.py` | Columna discriminadora con distinct_count, recommended_value |

---

## Aggregates

El domain model no implementa aggregates formales al estilo DDD con aggregate roots y transactional boundaries. Sin embargo, hay clusters naturales que funcionan como aggregates logicos:

### Aggregate 1: Entity Map (Cartographer Output)
- **Root**: `CartographerOutput`
- **Componentes**: `EntityDefinition[]`, `relationships[]`, phase1 metadata
- **Invariante**: Al menos 2 de {customers, invoices, products, payments} con confidence > 0.7
- **Proteccion**: `gate_cartographer()` valida antes de avanzar al Stage 2

### Aggregate 2: Data Quality Report
- **Root**: `DataQualityReport`
- **Componentes**: `QualityCheckResult[]`, blocking_issues, warnings
- **Invariante**: Si checks Critical fallan -> gate_decision = "HALT"
- **Propiedad derivada**: `confidence_label` (CONFIRMED/PROVISIONAL/UNVERIFIED/BLOCKED segun score)

### Aggregate 3: Verification Report
- **Root**: `VerificationReport`
- **Componentes**: `VerificationResult[]`, `NumberRegistryEntry{}`, issues
- **Invariante**: `is_trustworthy` = verification_rate >= 80%
- **Propiedad derivada**: Solo numeros en el registry llegan al Narrador

### Aggregate 4: Knowledge Graph
- **Root**: `SchemaKnowledgeGraph`
- **Componentes**: `TableNode{}`, `FKEdge[]`, `BusinessConcept{}`
- **Invariante**: 100% data-driven — zero hardcoded ERP knowledge
- **Servicio**: `find_join_path()` con Dijkstra confidence-weighted

### Aggregate 5: Calibration History (por cliente)
- **Root**: `CalibrationMemory` (fichero JSON por cliente)
- **Componentes**: `CalibrationScore[]` historicos
- **Invariante**: Detecta regresiones si score cae > 5 puntos vs run anterior

---

## Domain Events

No hay un sistema de domain events explicito (no hay EventBus ni publish/subscribe). Los eventos estan **implicitos en las transiciones del pipeline**:

| Evento Implicito | Trigger | Efecto |
|------------------|---------|--------|
| `EntityMapDiscovered` | Stage 1 completa | Se ejecuta `gate_cartographer()`, si pasa -> Stage 2 |
| `CalibrationPassed` | `gate_calibration()` pasa | Entity map aceptado; si falla -> feedback al Cartografo para retry |
| `QueriesExecuted` | Stage 2.5 completa | `compute_baseline()` construye brief con provenance |
| `AnalysisComplete` | Stage 3 (3 agentes en paralelo) | `gate_analysis()` verifica >= 2 agentes produjeron findings |
| `SwarmReconciled` | `reconcile_swarm()` | Conflictos numericos resueltos por arbitro Haiku |
| `FindingsVerified` | `VerificationEngine.verify_findings()` | Number registry listo; `gate_verification()` evalua rate |
| `ReportsGenerated` | Stage 4 completa | `gate_sanity()` + `gate_monetary_consistency()` |
| `RunDelivered` | Stage 5 completa | Artifacts guardados, swarm memory actualizado |
| `CalibrationScored` | Post-pipeline | Score 0-100, regression detection, memory persisted |

---

## Bounded Contexts

### BC1: Schema Discovery
- **Modulos**: `agents/cartographer.py`, `discovery/` (profiler, fk_discovery, ontology_builder), `knowledge_graph.py`
- **Responsabilidad**: Descubrir estructura de DB desconocidas, clasificar tablas, inferir relaciones
- **Lenguaje**: entity_type, base_filter, discriminator, probed_values, inclusion_dependency

### BC2: Query Generation & Execution
- **Modulos**: `agents/query_builder.py`, `agents/query_generator.py`, `pipeline.py` (execute_queries, gate_calibration)
- **Responsabilidad**: Generar SQL parametrizado, ejecutar con REPEATABLE READ isolation
- **Lenguaje**: CompiledQuery, SkippedQuery, query_pack, snapshot_timestamp

### BC3: Financial Analysis
- **Modulos**: `agents/analyst.py`, `agents/hunter.py`, `agents/sentinel.py`, `agents/sentinel_patterns.py`
- **Responsabilidad**: Analizar datos financieros, detectar anomalias, buscar oportunidades
- **Lenguaje**: finding, severity, value_eur, value_confidence, domain

### BC4: Data Quality & Verification
- **Modulos**: `quality/` (data_quality_gate, currency_guard, anomaly_detector, factor_model, provenance), `verification.py`, `gates.py`
- **Responsabilidad**: Garantizar integridad de datos y trazabilidad de numeros
- **Lenguaje**: DQ score, gate_decision, AtomicClaim, NumberRegistry, provenance, verification_rate

### BC5: Report Generation
- **Modulos**: `agents/narrators/` (executive, ceo, sales, controller, quality_certifier), `agents/vaire/`
- **Responsabilidad**: Generar reportes ejecutivos con Minto Pyramid, renderizar HTML/PDF
- **Lenguaje**: KO Report, Hero Numbers, FindingCard, severity badge, loss framing

### BC6: Calibration & Memory
- **Modulos**: `calibration/` (evaluator, memory, adjuster), `deliver.py`, `config.py`
- **Responsabilidad**: Evaluar accuracy post-run, persistir aprendizajes, detectar regresiones
- **Lenguaje**: CalibrationScore, regression, trend, swarm_memory, baseline

---

## Ubiquitous Language

| Termino | Definicion en el dominio |
|---------|--------------------------|
| **Valar / Vala** | Un agente del swarm, nombrado segun mitologia Tolkien |
| **Entity Map** | Mapa semantico de la DB del cliente: tablas -> entidades universales |
| **Base Filter** | Fragmento SQL que filtra una tabla a los datos relevantes (ej. `issotrx='Y'`) |
| **Discriminator** | Columna de baja cardinalidad usada para segmentar datos (ej. move_type, state) |
| **KO Report** | Reporte ejecutivo final — "Knock Out" report, estructura Minto Pyramid |
| **Hero Numbers** | Metricas clave al inicio del reporte con Kahneman loss framing |
| **Finding** | Hallazgo de un agente — tiene id, severity, headline, evidence, action |
| **Gate** | Checkpoint de validacion entre stages del pipeline |
| **Provenance** | Metadata de lineage que acompana cada numero en un reporte |
| **Number Registry** | Registro de numeros verificados — UNICA fuente autorizada para narradores |
| **Baseline** | Metricas financieras de referencia computadas de query results |
| **Frozen Brief** | Contexto compartido inmutable que reciben los agentes de Stage 3 |
| **Swarm Memory** | Memoria persistida entre runs de un cliente (findings, baselines, entity summary) |
| **Calibration Score** | Score 0-100 que mide la accuracy de un pipeline run |
| **REPEATABLE READ** | Nivel de aislamiento SQL para snapshot consistency entre queries |
| **Reflexion** | Patron de retry donde gate failures alimentan feedback al Cartografo |
| **Reconciliation** | Resolucion de conflictos numericos entre agentes (>2x discrepancia) |

---

## Invariantes

### Invariantes de Seguridad
1. **Nunca conexion directa a DB de cliente** — siempre via SSH Tunnel con TTL de 1 hora
2. **SQL injection prevention** — `_is_safe_identifier()` valida todos los nombres de tabla/columna
3. **Write operations blocked** — `FORBIDDEN_SQL_KEYWORDS` en VerificationEngine impide INSERT/UPDATE/DELETE/DROP
4. **Nunca almacenar datos de clientes** — regla no negociable del proyecto

### Invariantes de Pipeline
5. **Gate Cartographer** — minimo 2 de {customers, invoices, products, payments} con confidence > 0.7
6. **Gate Analysis** — minimo 2 de 3 agentes deben producir findings para continuar
7. **Gate Verification** — warn si verification_rate < 80%, no bloquea
8. **Gate Monetary Consistency** — warn si max/min EUR value ratio > 50x entre reportes
9. **DQ Critical checks** — si checks Critical (DQ-1, DQ-4, DQ+1) fallan -> analisis abortado
10. **Currency Guard** — NUNCA sumar amounts de diferentes monedas sin normalizacion FX

### Invariantes de Calibracion
11. **Regression detection** — alerta si score cae > 5 puntos vs run anterior
12. **Cross-consistency** — avg_invoice debe igualar total_revenue / num_invoices (1% tolerancia)
13. **Bounded metrics** — top_customer_revenue <= total_revenue, customers_with_debt <= distinct_customers

### Invariantes de Verificacion
14. **Triple Verification** — claim decomposition -> re-execution -> number registry
15. **Tolerance** — deviation <= 0.5% se acepta como VERIFIED
16. **Confidence tiers** — measured (0.95), computed (0.85), estimated (0.50)

---

## Fortalezas

### 1. Arquitectura Anti-Hallucination robusta
El sistema tiene **4 capas de proteccion** contra numeros fabricados: (a) DataQualityGate pre-analisis, (b) VerificationEngine post-analisis, (c) Number Registry como unica fuente para narradores, (d) gate_monetary_consistency cross-report. Esta es la fortaleza mas diferenciadora del dominio.

### 2. Schema-agnostic design
El Business Abstraction Layer permite analizar cualquier ERP (Odoo, OpenBravo, Tango, Excel) mapeando a entidades universales. El Knowledge Graph es 100% data-driven — zero hardcoded ERP patterns.

### 3. Pipeline con gates explicitos
Cada transicion entre stages tiene un gate con criterios claros. Esto previene que datos de baja calidad lleguen a etapas costosas (LLM). El patron Reflexion (retry con feedback) en el Cartografo es particularmente elegante.

### 4. Provenance completa
Cada numero en un reporte ejecutivo lleva metadata de lineage: tablas consultadas, DQ score, confidence label, timestamp. Esto permite auditar cualquier afirmacion del reporte.

### 5. Calibration loop
El sistema aprende de runs anteriores: detecta regresiones, genera recomendaciones, y persiste memoria por cliente. Esto habilita mejora continua sin intervencion manual.

### 6. Pydantic v2 schemas tipados
Los outputs de agentes tienen schemas formales (`agent_outputs.py`) con validaciones, factory methods para backward compatibility, y propiedades derivadas. Esto elimina errores por dict key access.

### 7. Factor model financiero
`RevenueFactorModel` descompone revenue en drivers observables (client_count x avg_ticket x frequency), detectando anomalias que un simple z-score no captaria.

---

## Debilidades

### 1. Ausencia de Aggregate Roots formales
No hay transactional boundaries explicitas. Los "aggregates" son clusters logicos de dataclasses/Pydantic models, pero no hay mecanismo que impida modificar un `QualityCheckResult` despues de creado el `DataQualityReport`. La inmutabilidad es por convencion, no por enforcement.

### 2. No hay Domain Events explicitos
Las transiciones del pipeline son llamadas directas a funciones. No hay EventBus, no hay subscribe/publish. Esto hace dificil agregar side effects (notificaciones, logging avanzado, webhooks) sin modificar el pipeline.py directamente.

### 3. ColumnProfile duplicado
Hay **dos definiciones distintas** de `ColumnProfile`: una en `knowledge_graph.py` y otra en `discovery/profiler.py`, con atributos diferentes. Esto viola DRY y puede causar confusion.

### 4. Pipeline.py es un God Module
Con 44K+ caracteres y multiples stages en un solo archivo, `pipeline.py` concentra demasiada logica: execute_queries, gate_calibration, compute_baseline, run_analysis_agents, reconcile_swarm, run_narrators. Deberia dividirse en modulos por stage.

### 5. Analysis Job sin estado persistido
El lifecycle del job (pending -> running -> ... -> completed/failed) esta implicito en el flujo de `run.py` pero no hay un modelo `AnalysisJob` persistido. Si el proceso se cae a mitad, no hay forma de retomar.

### 6. Falta de Repository pattern
Los datos se leen/escriben directamente a JSON files (config, memory, calibration). No hay abstraccion de repositorio, lo que dificulta migrar a una base de datos sin tocar multiples archivos.

### 7. EntityType duplicado entre bounded contexts
`EntityType` esta definido tanto en `schemas/agent_outputs.py` (MASTER/TRANSACTIONAL/CONFIG/BRIDGE/UNKNOWN) como en `discovery/ontology_builder.py` (transactional/master/bridge/config/unknown) con valores ligeramente diferentes (casing). Esto puede causar bugs silenciosos.

### 8. Verificacion no bloquea pipeline
`gate_verification()` solo advierte cuando verification_rate < 80% pero nunca bloquea. Un reporte con 0% de verificacion puede llegar al cliente con solo un warning.

---

## Recomendaciones 2026

### R1: Introducir Domain Events con un EventBus ligero
Implementar un `DomainEventBus` simple (in-process, sincrono) para desacoplar side effects del pipeline. Permitiria agregar observabilidad (Laminar), webhooks, y notificaciones sin modificar el core. Prioridad: **alta**.

### R2: Refactorizar pipeline.py en modulos por stage
Dividir en `stages/execute.py`, `stages/calibrate.py`, `stages/analyze.py`, `stages/narrate.py`, `stages/reconcile.py`. El pipeline.py quedaria como orquestador puro de ~100 lineas. Prioridad: **alta**.

### R3: Unificar ColumnProfile y EntityType
Eliminar duplicados: una sola definicion canonica de `ColumnProfile` en `schemas/` y una sola `EntityType` enum. Las otras ubicaciones importan de ahi. Prioridad: **media**.

### R4: Modelo AnalysisJob persistido
Crear una entidad `AnalysisJob` con su propio lifecycle state machine, persistida (SQLite o Postgres). Permitiria: reintentos parciales, dashboard de runs, y audit trail completo. Prioridad: **media**.

### R5: Repository pattern para memoria y calibracion
Abstraer el acceso a JSON files detras de interfaces (`CalibrationRepository`, `MemoryRepository`). Facilita testing (in-memory) y migracion futura a Postgres. Prioridad: **media**.

### R6: Gate de verificacion con threshold configurable
Hacer que `gate_verification()` sea configurable: por defecto warn en <80%, pero permitir al cliente activar bloqueo strict donde un verification_rate bajo impide la entrega del reporte. Prioridad: **baja**.

### R7: Inmutabilidad forzada en Value Objects
Usar `frozen=True` en todos los dataclasses que son value objects (`QualityCheckResult`, `AtomicClaim`, `VerificationResult`, etc.). Actualmente la inmutabilidad es solo por convencion. Prioridad: **baja**.

### R8: Tests de invariantes como propiedades
Crear property-based tests (Hypothesis) para las invariantes criticas: top_customer_revenue <= total_revenue, SUM(aging) ~= total_outstanding, avg_invoice ~= total/count. Esto asegura que las invariantes matematicas se mantienen ante cambios de codigo. Prioridad: **baja**.
