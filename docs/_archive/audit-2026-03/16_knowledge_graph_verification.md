# 16. Knowledge Graph y Sistema de Verificacion Anti-Alucinacion

## Resumen

Valinor implementa un sistema anti-alucinacion de tres capas que garantiza que los numeros presentados en reportes provienen exclusivamente de sistemas deterministicos, no de generacion LLM. El sistema se compone de:

1. **Schema Knowledge Graph** (`core/valinor/knowledge_graph.py`) -- grafo de esquema construido 100% desde el `entity_map` del Cartographer, sin conocimiento ERP hardcodeado.
2. **Verification Engine** (`core/valinor/verification.py`) -- motor de verificacion post-analisis que descompone hallazgos en claims atomicos y los valida contra un Number Registry.
3. **Calibration Loop** (`core/valinor/calibration/`) -- ciclo de auto-calibracion con evaluador, memoria persistente y ajustador, inspirado en Reflexion (NeurIPS 2023).

Principio rector: **los numeros vienen de sistemas deterministicos, los LLMs solo narran hechos verificados.**

---

## Knowledge Graph Structure

### Arquitectura del Grafo

La clase `SchemaKnowledgeGraph` modela el esquema de base de datos como un grafo dirigido con pesos. No contiene conocimiento hardcodeado de ningun ERP.

**Nodos** (`TableNode`):
- Nombre de tabla, entidad, tipo (TRANSACTIONAL, MASTER, etc.)
- Columnas con `ColumnProfile`: cardinalidad, top values, flag `is_low_cardinality` (<=10 valores distintos)
- `base_filter`: filtros que el Cartographer determino necesarios (e.g., `issotrx='Y' AND docstatus='CO'`)
- `filter_columns`: columnas extraidas del `base_filter` via regex

**Aristas** (`FKEdge`):
- Relaciones FK entre tablas con `confidence` (0.0-1.0)
- `weight = 1.0 - confidence` -- Dijkstra prefiere aristas de alta confianza
- Cardinalidad (N:1, 1:N, N:N)

**Conceptos de Negocio** (`BusinessConcept`):
- Auto-generados desde la semantica de entidades
- Tres tipos: filtered (entidades con base_filter), total (TRANSACTIONAL con amount_col), needs_join (filtro referencia columnas de otra tabla)

### Construccion del Grafo

El metodo `build_from_entity_map()` construye todo desde el `entity_map` del Cartographer:

1. Itera entidades para crear `TableNode` con columnas desde `key_columns` y `probed_values`
2. Detecta columnas de baja cardinalidad (discriminadores) automaticamente
3. Construye aristas FK desde `relationships`, incluyendo confidence de FK Discovery
4. Genera conceptos de negocio por inferencia de tipo de entidad
5. Construye indices de adyacencia (forward y reverse) para pathfinding

### JOIN Path Reasoning

El metodo `find_join_path()` usa Dijkstra (no BFS simple) con pesos basados en confianza:

- `weight = 1 - confidence`: aristas con alta confianza tienen bajo peso
- Traversa aristas en ambas direcciones (forward y reverse adjacency)
- Retorna `JoinPath` con la secuencia de tablas, aristas y peso total
- Genera fragmento SQL automatico via `sql_fragment` property

### Validacion de Queries

`validate_query()` detecta dos anti-patrones sin logica ERP hardcodeada:

1. **MISSING_FILTER_COLUMN**: el Cartographer definio un `base_filter` para la tabla, pero el query no referencia las columnas del filtro. Severidad critica si la columna es de baja cardinalidad.
2. **AMBIGUOUS_COLUMN**: columnas que aparecen en multiples tablas del JOIN sin cualificacion de tabla.

### Prompt Context

`to_prompt_context()` serializa el KG para inyeccion en prompts de agentes. Los agentes reciben:
- Tablas con sus filtros requeridos
- Columnas de baja cardinalidad con valores muestreados
- Paths de JOIN con pesos de confianza
- Conceptos de negocio con tablas y filtros requeridos

---

## Verification Engine

### Arquitectura

El `VerificationEngine` es codigo Python puro, no usa LLM. Opera en 4 pasos secuenciales:

**Paso 1 -- Number Registry**: Construye un registro de numeros "ground truth" desde:
- Resultados de queries ejecutados (`_build_registry_from_queries`): revenue total, facturas, AR outstanding, aging buckets, concentracion de clientes
- Baseline computado (`_build_registry_from_baseline`): valores que no vinieron de queries directos

Cada entrada (`NumberRegistryEntry`) registra: valor, unidad, query fuente, descripcion, nivel de confianza (`measured`, `computed`, `estimated`), y dimension (EUR, COUNT, PERCENT, DAYS).

**Paso 2 -- Claim Decomposition**: Descompone hallazgos de agentes en claims atomicos (`AtomicClaim`):
- Valores EUR explicitios (`value_eur` del finding)
- Valores inline extraidos via regex de headlines (detecta $, EUR, sufijos M/K)
- Porcentajes (`\d+%`)
- Conteos con entidad asociada ("3,139 invoices", "4,854 customers")

**Paso 3 -- Verification Pipeline**: Verifica cada claim con 5 estrategias en cascada:

| Estrategia | Confianza Base | Descripcion |
|------------|---------------|-------------|
| 1. Registry match directo | 0.95 (measured) / 0.85 (computed) | Valor coincide con entrada del registry dentro de tolerancia |
| 2. Valor derivado | 0.60 | Valor es division, multiplicacion o resta de dos entradas del registry |
| 3. Raw results search | 0.75 | Busqueda exhaustiva en filas crudas de resultados de queries |
| 4. Active re-query (CRITIC) | 0.90 | Genera SQL de verificacion, ejecuta contra BD, compara resultado |
| 5. Approximate match | 0.30-0.50 | Coincidencia dentro de 5% con penalizacion de confianza |

Si ninguna estrategia produce match, el claim se marca `UNVERIFIABLE` con confianza 0.0.

**Paso 4 -- Cross-Validation**: Chequeos de consistencia matematica:
- `customers_with_debt / distinct_customers > 3x` = critico (probable inclusion de AP)
- `total_outstanding_ar / total_revenue > 5x` = warning (acumulacion multi-anual?)
- `avg_invoice != total_revenue / num_invoices` = warning (error de calculo)
- `overdue_ar > total_outstanding_ar` = critico (imposible matematicamente)

### Tolerancias por Tipo

La verificacion usa tolerancias diferenciadas segun tipo de claim:
- **Conteos**: match exacto (despues de redondeo a entero)
- **Porcentajes**: 2% de tolerancia absoluta
- **EUR/moneda**: escalonado por magnitud: >1M = 0.5%, >10K = 0.1%, <10K = 0.01%

### Active Re-Query (CRITIC Pattern)

Cuando las estrategias pasivas fallan, el engine genera un SQL de verificacion:
- Usa `entity_map` para encontrar tabla, columnas y filtros correctos
- Soporta claims de conteo (COUNT) y revenue (SUM)
- Para claims sobre clientes especificos, genera JOIN y usa query parametrizado (`ILIKE :cust_name_pattern`)
- Guardias de seguridad: bloqueo de operaciones de escritura, timeout de 5s, limite de 100 filas, solo SELECT/WITH

### Prompt Context para Narradores

El `VerificationReport.to_prompt_context()` inyecta en prompts de narradores:
- Tasa de verificacion global
- Number Registry completo con tiers de confianza (HIGH >= 0.85, MEDIUM >= 0.60, LOW < 0.60)
- Issues encontrados (max 10)
- Claims fallidos marcados como "DO NOT use these values"

---

## Auto-Calibration Loop

El sistema de auto-calibracion consta de tres modulos en `core/valinor/calibration/`:

### Evaluator (`evaluator.py`)

Puntua cada ejecucion de pipeline en escala 0-100 con 5 categorias de checks:

| Check | Deduccion Max | Umbral Pass |
|-------|--------------|-------------|
| Query coverage (vs. 5 queries esperadas) | 20 pts | >= 80% |
| Baseline completeness (5 campos criticos) | 15 pts | >= 80% |
| Cross-consistency (4 chequeos matematicos) | 15 pts cada uno | Match exacto/tolerancia |
| Verification coverage | 15 pts | >= 70% claims verificados |
| Error rate (queries fallidos) | 20 pts | <= 10% |

Checks de cross-consistency:
- `avg_invoice ~ total_revenue / num_invoices` (1% tolerancia)
- `SUM(aging_buckets) ~ total_outstanding` (5% tolerancia)
- `top_customer_revenue <= total_revenue`
- `customers_with_debt <= distinct_customers`

### Memory (`memory.py`)

Persistencia JSON por cliente (`calibration/<client>.json`) con:
- Historial completo de scores con timestamps
- **Deteccion de regresion**: score actual < score anterior - 5 puntos = warning, - 15 = critico
- **Analisis de tendencia**: compara promedio de ultimos N scores vs anteriores N, clasifica como improving/stable/degrading (umbral +/- 3 puntos)
- **Vista cross-client**: ultimo score de cada cliente para bird's eye view

### Adjuster (`adjuster.py`)

Genera recomendaciones de mejora con guardia anti-overfitting:

- **Query fixes**: error rate alto o coverage baja
- **Filter improvements**: checks especificos que fallan (aging, top_customer, debt)
- **Verification improvements**: tasa de verificacion baja o baseline incompleto

**Deteccion de overfitting**: si hay >= 2 clientes en memoria y los otros promedian > 90 de score pero el actual tiene problemas, la sugerencia se flaggea como "potential overfitting" y se marca `is_generic = False`.

---

## Query Generation

### SQLBuilder (API Fluent)

`SQLBuilder` en `core/valinor/agents/query_generator.py` construye SQL programaticamente con el KG:

- `join_to(target)` consulta `kg.find_join_path()` para determinar el JOIN correcto -- no acepta condiciones ON manuales
- `where_filters(table)` inyecta todos los filtros requeridos del KG para esa tabla
- Genera JOINs intermedios automaticamente si el path requiere tablas intermedias
- Soporta CTEs, HAVING, ORDER BY, LIMIT

### QueryGenerator

Genera 8 tipos de queries dinamicamente:

1. `revenue_summary` -- SUM, COUNT, AVG, MIN, MAX con filtros y periodo
2. `ar_outstanding` -- JOIN payment->invoice con outstanding_amount > 0
3. `aging_analysis` -- Buckets por dias de vencimiento (CASE con 7 tramos)
4. `customer_concentration` -- Revenue por cliente con porcentaje (subquery para total)
5. `top_debtors` -- JOIN payment->invoice->customer, top 20 por deuda
6. `dormant_customers` -- Clientes sin compra en 90+ dias con lifetime revenue
7. `revenue_trend` -- Agregacion mensual con LAG para MoM growth y moving average 3M
8. `yoy_comparison` -- Comparacion year-over-year por mes

**Deteccion de entidades por TIPO** (TRANSACTIONAL, MASTER), no por nombre. Deteccion de columnas por **ROL SEMANTICO** (amount_col, date_col, customer_fk), no por nombre de columna.

---

## Fact Checking

El sistema implementa fact checking en multiples capas:

1. **Pre-query** (KG): `validate_query()` detecta filtros faltantes y columnas ambiguas antes de ejecutar
2. **Post-query** (Verification): Registry match + derivation + raw search + active re-query
3. **Post-analysis** (Cross-validation): Consistencia matematica entre metricas
4. **Post-pipeline** (Calibration): Score 0-100 con deteccion de regresion

El pipeline esta conectado en `core/valinor/pipeline.py`:
- Importa `build_knowledge_graph` y `VerificationEngine`
- KG se construye despues de `gate_calibration()`
- Verificacion se ejecuta despues de `reconcile_swarm()`
- Narradores reciben el Number Registry como unica fuente de valores EUR

Fundamento academico implementado:
- **CoVe** (Meta, ACL 2024): claim decomposition + registry matching
- **SAFE** (DeepMind, NeurIPS 2024): descomposicion en hechos atomicos
- **CRITIC** (ICLR 2024): verificacion con herramientas externas (SQL como tool)
- **SchemaGraphSQL** (arXiv:2505.18363): pathfinding en grafo de esquema
- **GAIT** (PAKDD 2024): deteccion de discriminadores por baja cardinalidad
- **Reflexion** (NeurIPS 2023): auto-correccion via memoria de calibracion

---

## Fortalezas

1. **Zero hardcoded ERP knowledge**: todo viene del `entity_map` del Cartographer. Verificado con tests contra schemas Openbravo, Odoo y SAP-like. El KG y Verification Engine no contienen nombres de tablas ni columnas.

2. **5 estrategias de verificacion en cascada**: desde match exacto (confianza 0.95) hasta re-query activo (0.90) y approximate (0.30-0.50). Cada claim tiene un score de confianza granular.

3. **Confidence-weighted pathfinding**: Dijkstra con `weight = 1 - confidence` prioriza JOINs de alta confianza de FK Discovery sobre relaciones especulativas.

4. **Separacion estricta numeros/narrativa**: el Number Registry es la unica fuente de verdad para narradores. Claims no verificados se marcan `[NO VERIFICADO]`.

5. **Calibracion con deteccion de overfitting**: el Adjuster compara scores entre clientes y flaggea sugerencias que solo ayudarian a un cliente especifico.

6. **Seguridad en re-queries**: bloqueo de operaciones de escritura, validacion de identificadores SQL, queries parametrizados, timeouts, limites de filas.

7. **Tolerancias diferenciadas por tipo**: conteos requieren exactitud, EUR escala por magnitud, porcentajes tienen banda absoluta. Evita falsos positivos/negativos.

8. **Auto-generacion de conceptos de negocio**: detecta entidades que necesitan JOIN cruzado para aplicar filtros, sin que nadie lo configure manualmente.

---

## Debilidades

1. **Descomposicion de claims basada en regex**: `_decompose_finding()` usa patrones regex para extraer valores de headlines. No maneja formatos de numeros localizados (1.234,56 vs 1,234.56), ni claims complejos multi-sentencia.

2. **Number Registry con naming fragil**: las labels del registry (`total_revenue`, `avg_invoice`) son strings magicos. Un typo en el pipeline o un cambio de nombre de query rompe el matching silenciosamente.

3. **Active re-query limitado en scope**: solo genera queries de COUNT y SUM. No soporta verificacion de porcentajes, ratios, tendencias, ni claims comparativos ("crecio 15% vs mes anterior").

4. **Cross-validation con pocas reglas**: solo 4 checks de consistencia matematica. No valida aging buckets vs periodos de facturacion, ni concentracion de clientes vs total, ni tendencias vs periodos anteriores.

5. **Evaluator con queries esperadas hardcodeadas**: `EXPECTED_QUERIES` y `CRITICAL_BASELINE_FIELDS` en el Evaluator son listas fijas. Si el pipeline genera queries distintos (por diferente tipo de entidad), el coverage score baja artificialmente.

6. **Deteccion de overfitting superficial**: solo compara scores promedio entre clientes. No analiza el tipo de checks que fallan ni la correlacion entre sugerencias y mejoras posteriores.

7. **Sin verificacion temporal**: no hay check de que los datos del periodo solicitado sean coherentes con el rango de datos disponible en la BD. Un analisis de diciembre 2024 sobre una BD que solo tiene datos hasta junio 2024 pasaria sin warning.

8. **Calibration Memory sin compactacion**: el historial JSON crece indefinidamente por cliente. Sin mecanismo de archivado, poda o compactacion.

9. **QueryGenerator fallback ausente**: cuando `generate_all()` falla para un query, lo registra en `skipped` pero no intenta el template estatico de `query_builder.py` como fallback.

10. **Dimension checking parcial**: el sistema tiene `Dimension` enum (EUR, COUNT, PERCENT, DAYS) pero no previene comparaciones cross-dimension (e.g., verificar un claim de COUNT contra una entrada EUR del registry).

---

## Recomendaciones 2026

### Corto Plazo (Q2 2026)

1. **Dimension-aware verification**: antes de comparar un claim con una entrada del registry, validar que `claim.claimed_unit` sea compatible con `entry.dimension`. Evitaria falsos positivos donde un conteo coincide numericamente con un monto EUR.

2. **Registry labels como enum**: reemplazar strings magicos por un enum tipado (`RegistryLabel.TOTAL_REVENUE`) con validacion en tiempo de compilacion.

3. **Descomposicion de claims con LLM ligero**: usar un modelo small (Haiku) para la extraccion de claims en lugar de regex. Manejar formatos localizados y claims complejos. Mantener el registry match como deterministico.

4. **Temporal coherence check**: antes de ejecutar queries, verificar que `period.start` y `period.end` estan dentro del rango de datos disponible (query `MIN/MAX(date_col)` al inicio).

### Mediano Plazo (Q3-Q4 2026)

5. **LLM-FK integration** (arXiv:2603.07278): reemplazar definicion manual de relationships en `entity_map` con deteccion automatica de FK via multi-agente. El paper reporta F1 0.93-1.00.

6. **RIGOR ontology** (arXiv:2506.01232): auto-generar conceptos de negocio desde schema + documentacion, reemplazando la generacion basada en heuristicas del `_generate_concepts()`.

7. **Verification Engine con re-query de derivaciones**: extender active re-query para verificar porcentajes (genera query con division), tendencias (query con LAG/window), y comparativos (query multi-periodo).

8. **Cross-validation dinamica**: generar reglas de consistencia desde el KG en lugar de hardcodearlas. Si el KG sabe que aging tiene buckets y AR tiene total, auto-generar el check `SUM(buckets) ~ total`.

9. **QueryGenerator con fallback a templates**: cuando la generacion dinamica falla, intentar `query_builder.py` automaticamente. Registrar el motivo del fallback para mejora continua.

### Largo Plazo (2027)

10. **VerifiAgent pattern** (EMNLP 2025): meta-verificacion que evalua completitud del reporte (faltan secciones?) ademas de precision numerica. Routing adaptativo a herramienta de verificacion segun tipo de claim.

11. **Multi-Agent Debate para reconciliacion**: en lugar del arbiter Haiku actual en `reconcile_swarm`, implementar debate estructurado entre agentes con rondas de argumentacion y evidencia.

12. **Calibracion automatica end-to-end**: ejecutar el loop evaluator->adjuster->memory sin intervencion humana entre runs. Implementar las sugerencias genericas automaticamente (ajustar tolerancias, agregar filtros) y solo escalar las flaggeadas como overfitting.

---

## Archivos Clave

| Archivo | Lineas | Rol |
|---------|--------|-----|
| `core/valinor/knowledge_graph.py` | 582 | Schema graph, Dijkstra, validacion, prompt context |
| `core/valinor/verification.py` | 1122 | Number registry, claim decomposition, 5 estrategias, cross-validation, active re-query |
| `core/valinor/agents/query_generator.py` | 793 | SQLBuilder fluent API, 8 query generators, deteccion por tipo/rol |
| `core/valinor/calibration/evaluator.py` | 466 | Scoring 0-100, 5 categorias de checks |
| `core/valinor/calibration/memory.py` | 195 | Persistencia JSON, regresion, tendencias, cross-client |
| `core/valinor/calibration/adjuster.py` | 242 | Sugerencias genericas, deteccion de overfitting |
| `core/valinor/pipeline.py` | -- | Orquestador, integra KG + Verification en el pipeline |
| `.claude/skills/grounded-analysis/SKILL.md` | 281 | Documentacion del sistema, principios, calibration loop, tests |
| `.claude/skills/grounded-analysis/references/research.md` | -- | 30+ papers organizados por dominio |
| `.claude/skills/grounded-analysis/references/roadmap.md` | -- | Roadmap 6 fases con branch strategy |
