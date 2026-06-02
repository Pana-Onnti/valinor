# 15. Pipeline de Datos y ETL -- Valinor SaaS

> Fecha: 2026-03-22
> Archivos analizados: 28 archivos en `core/valinor/`, `shared/connectors/`, `worker/`, `api/adapters/`, `docs/`

---

## 1. Resumen

Valinor SaaS implementa un pipeline de datos orientado a **analisis financiero bajo demanda** (no ETL clasico de ingesta masiva). El flujo es: API recibe solicitud de analisis -> Celery worker establece conexion efimera (opcionalmente via SSH tunnel) -> pipeline multi-stage ejecuta queries de solo lectura contra la DB del cliente -> agentes LLM analizan resultados -> se generan reportes.

El sistema **nunca almacena datos del cliente** (Zero Data Storage). Las conexiones son efimeras (max 1 hora). Solo se persisten metadata del job, resultados agregados y perfiles de cliente.

La capa de conectores (`shared/connectors/`) se basa en el patron Factory con una clase abstracta `DeltaConnector` que envuelve SQLAlchemy. Aunque la documentacion menciona dlt (Data Load Tool) como fundamento, **no hay uso real de la libreria dlt** -- es solo una referencia conceptual. Los conectores usan SQLAlchemy puro.

---

## 2. Fuentes de Datos Soportadas

### Actualmente disponibles

| Source Type | Clase | Driver | Notas |
|-------------|-------|--------|-------|
| `postgresql` | `PostgreSQLConnector` | `psycopg2` via SQLAlchemy | Aliases: `postgres`, `pg` |
| `mysql` | `MySQLConnector` | `pymysql` via SQLAlchemy | Aliases: `mariadb` |
| `etendo` | `EtendoConnector` | PostgreSQL + SSH tunnel (Paramiko) | Hereda de `PostgreSQLConnector` |
| Excel/CSV | `excel_to_sqlite` / `csv_to_sqlite` | pandas + sqlite3 | Stage 0 (Intake), convierte a SQLite temporal |

### Roadmap (de `docs/SUPPORTED_SOURCES.md`)

| Source | Prioridad |
|--------|-----------|
| SAP HANA | Alta |
| Microsoft SQL Server | Alta |
| Salesforce | Alta |
| Oracle Database | Media |
| BigQuery | Media |
| Snowflake | Media |
| HubSpot | Media |
| MongoDB | Baja |

---

## 3. Conectores (dlt / DeltaConnector)

### Arquitectura de conectores

- **Base abstracta**: `shared/connectors/base.py` -- `DeltaConnector(ABC)` con:
  - `connect()` / `close()` -- lifecycle con context manager
  - `execute_query(sql, params, max_rows=10_000)` -- solo SELECT/WITH
  - `get_schema(schema_name)` -- metadata de tablas/columnas/row_count
  - `_require_select()` -- guard que bloquea cualquier query que no sea SELECT/WITH
  - `_require_connected()` -- verifica estado de conexion

- **Factory**: `shared/connectors/factory.py` -- `ConnectorFactory.create(source_type, config)` con registry lazy-loaded

- **SourceType enum**: `POSTGRESQL`, `MYSQL`, `ETENDO`

### PostgreSQLConnector (`shared/connectors/postgresql.py`)

- SQLAlchemy `create_engine()` con verificacion `SELECT 1`
- `get_schema()`: usa `sa_inspect()` para listar tablas/columnas
- `_estimate_row_count()`: consulta `pg_class.reltuples` (evita full table scan)
- Max rows por query: 10,000 (configurable)

### MySQLConnector (`shared/connectors/mysql.py`)

- Auto-corrige `mysql://` a `mysql+pymysql://`
- `_estimate_row_count()`: consulta `information_schema.TABLES`
- Misma interfaz que PostgreSQL

### EtendoConnector (`shared/connectors/etendo.py`)

- Hereda de `PostgreSQLConnector`
- Agrega lifecycle de SSH tunnel via `SSHTunnelManager`
- `connect()`: crea tunnel SSH -> reescribe connection_string a `localhost:local_port` -> llama `super().connect()`
- `close()`: cierra engine SQLAlchemy + cierra tunnel SSH

### Nota sobre dlt

La documentacion (`shared/connectors/__init__.py`, `base.py`) referencia dlt como fundamento conceptual, pero **no se importa ni usa la libreria dlt en ningun conector**. Los conectores son wrappers puros de SQLAlchemy. El nombre "DeltaConnector" evoca dlt pero la implementacion es independiente.

---

## 4. Pipeline de Ingesta

El pipeline NO es un ETL clasico -- es un pipeline de **analisis bajo demanda** con las siguientes stages:

### Stage 0: Intake (solo para archivos)
- **Archivo**: `core/valinor/tools/excel_tools.py`
- Excel (.xlsx/.xls) -> SQLite via pandas `read_excel()` + `to_sql()`
- CSV -> SQLite via pandas
- La DB temporal se crea en `/tmp/valinor/{client_name}.db`
- Cada hoja de Excel se convierte en una tabla SQLite

### Stage 1: Cartographer (Schema Discovery)
- **Archivo**: `core/valinor/agents/cartographer.py`
- **Phase 1 (determinista)**: Pre-scan de columnas discriminadoras (`ad_client_id`, `issotrx`, `docstatus`, etc.) en tablas con nombres de negocio (`invoice`, `payment`, `order`). Sin costo LLM.
- **Phase 2 (Sonnet)**: Mapeo profundo de entidades con hints de Phase 1. Patron Reflexion con retry loop (max 2 reintentos si Gate 1.5 falla).
- Output: `entity_map` con tablas mapeadas a entidades de negocio (`customers`, `invoices`, `products`, `payments`), cada una con `confidence`, `base_filter`, `key_columns`.

### Stage 1.5: Gate Calibration (Deterministic Guard Rail)
- **Archivo**: `core/valinor/pipeline.py` -- `gate_calibration()`
- Sin LLM, solo SQL COUNT:
  1. `COUNT(*)` total > 0 (tabla tiene datos)
  2. `COUNT(*) WHERE filter` > 0 (filtro no elimina todo)
  3. `SUM(amount)` no NULL para entidades transaccionales
  4. FK orphan check por relaciones declaradas en entity_map
- Si falla: feedback estructurado -> Cartographer retry (patron Reflexion)

### Stage 2: QueryBuilder (Deterministic SQL Generation)
- **Archivo**: `core/valinor/agents/query_builder.py`
- **NO es un agente** -- Python puro, zero LLM cost
- Templates SQL parametrizados con `{entity_filter}` placeholders
- Queries clave: `total_revenue_summary`, `revenue_by_period`, `data_freshness`, aging, pareto, etc.
- Genera un query pack con `id`, `sql`, `domain`, `description`

### Stage 2.5: Execute Queries
- **Archivo**: `core/valinor/pipeline.py` -- `execute_queries()`
- Ejecuta todas las queries del pack contra la DB del cliente
- **REPEATABLE READ isolation** para snapshot consistency (fallback si no soportado)
- Resultados: `{results: {query_id: {columns, rows, row_count, domain}}, errors: {}, snapshot_timestamp}`

### Post-2.5: Compute Baseline (Frozen Brief)
- **Archivo**: `core/valinor/pipeline.py` -- `compute_baseline()`
- Construye brief compartido con provenance: `total_revenue`, `num_invoices`, `avg_invoice`, etc.
- Cada metrica lleva `_provenance`: `source_query`, `row_count`, `executed_at`, `confidence: "measured"`
- Este baseline es la **single source of truth** para todos los agentes downstream

### Stage 3: Analysis Agents (paralelo)
- `run_analyst()`, `run_sentinel()`, `run_hunter()` en paralelo
- Reciben baseline + query results + anomaly scan + currency context

### Stage 3.5: Reconcile Swarm
- Detecta conflictos numericos entre agentes (>2x discrepancy)
- Haiku arbiter resuelve conflictos

### Stage 4: Narrators
- Generan reportes por audiencia (CEO, Controller, Sales, Executive)
- Reciben contexto adaptativo via `AdaptiveContextBuilder` (historial, segmentacion, alertas)

---

## 5. Transformaciones

El sistema no hace ETL de transformacion clasica. Las "transformaciones" son:

### En ingesta
- **Excel -> SQLite**: normalizacion de nombres de tablas (lowercase, replace spaces/hyphens)
- **Type coercion**: pandas infiere tipos al importar Excel

### En ejecucion de queries
- **Serialization segura**: valores no-JSON (`Decimal`, `date`, etc.) se convierten a `str` en `execute_queries()`
- **Row capping**: max 10,000 rows por query (configurable)

### En analisis
- **Compute Baseline**: agrega metricas de las queries ejecutadas (total_revenue, avg_invoice, etc.)
- **AnomalyDetector**: log-transform + 3x IQR fence para detectar outliers en columnas financieras
- **RevenueFactorModel**: descomposicion multiplicativa (`Revenue = client_count x avg_ticket x transactions_per_client`)
- **Statistical Checks**: STL decomposition, Benford's Law, CUSUM structural break, cointegration test

### En naracion
- **CurrencyGuard context injection**: inyecta instrucciones de manejo de moneda mixta en prompts de agentes
- **Provenance badges**: cada finding lleva `[CONFIRMED / PROVISIONAL / UNVERIFIED / BLOCKED . score/100 . tag]`

---

## 6. Data Quality Pre-checks

### DataQualityGate (`core/valinor/quality/data_quality_gate.py`)

8+1 checks bloqueantes antes de cualquier analisis:

| # | Check | Score Weight | Severidad | Que verifica |
|---|-------|-------------|-----------|--------------|
| 1 | `schema_integrity` | 15 pts | FATAL | Tablas esperadas existen, columnas no han cambiado |
| 2 | `null_density` | 15 pts | CRITICAL | Ratio de NULLs por columna bajo threshold |
| 3 | `duplicate_rate` | 10 pts | WARNING | PKs sin duplicados |
| 4 | `accounting_balance` | 20 pts | CRITICAL | Debitos = creditos (balance contable) |
| 5 | `cross_table_reconcile` | 15 pts | CRITICAL | Facturas vs pagos reconciliados |
| 6 | `outlier_screen` | 10 pts | WARNING | Pre-screen numerico (z-score) |
| 7 | `date_plausibility` | -- | WARNING | Sin timestamps futuros |
| 8 | `freshness_check` | -- | WARNING | CurrencyGuard verifica datos no stale |
| +1 | `REPEATABLE READ` | -- | INFO | Snapshot isolation |

**Gate Decision**:
- `PROCEED`: score >= 85
- `PROCEED_WITH_WARNINGS`: score 45-84
- `HALT`: score < 45 -> `DQGateHaltError`, job abortado con reporte

### Gate Calibration (`pipeline.py` -- `gate_calibration()`)
- Verifica `base_filter` para cada entidad mapeada por Cartographer
- 3 checks SQL deterministicos + FK orphan check
- Si falla -> feedback a Cartographer para retry (max 2 reintentos)

### Gates inter-stage (`core/valinor/gates.py`)
- `gate_cartographer()`: al menos 2 de {customers, invoices, products, payments} con confidence > 0.7
- `gate_analysis()`: al menos 2 de 3 agentes produjeron findings
- `gate_sanity()`: numeros en reportes vs query results dentro de tolerancia
- `gate_monetary_consistency()`: EUR values cross-report max/min ratio < 50x
- `gate_verification()`: verification rate >= 80%, 0 issues criticos

### CurrencyGuard (`core/valinor/quality/currency_guard.py`)
- Detecta mezcla de monedas en result sets
- Auto-detecta columnas de currency y amount
- Si mixto: inyecta instrucciones en prompts para no sumar EUR + USD
- Threshold: < 0.1% valor mixto = homogeneo

### AnomalyDetector (`core/valinor/quality/anomaly_detector.py`)
- 3x IQR fence en log-transform sobre columnas financieras
- Severidad: HIGH (>20% valor en outliers), MEDIUM (>5%), LOW
- Formatea anomalias para inyeccion en memoria de agentes

### Statistical Checks (`core/valinor/quality/statistical_checks.py`)
- `seasonal_adjusted_zscore()`: STL decomposition + z-score estacional
- `cointegration_test()`: Engle-Granger para detectar divergencia revenue vs receivables
- `benford_test()`: Benford's Law para first-digit distribution (n >= 100)
- `cusum_structural_break()`: CUSUM para regimen changes

---

## 7. Fortalezas

1. **Zero Data Storage**: nunca se almacenan datos del cliente, solo metadata. Conexiones efimeras con max 1 hora y cleanup automatico. Excelente postura de seguridad y compliance.

2. **Data Quality Gate robusto**: 8+1 checks con scoring ponderado y gate decision automatica. El sistema puede abortar un job si los datos no cumplen calidad minima, evitando reportes sobre basura.

3. **REPEATABLE READ isolation**: todas las queries ven el mismo snapshot de la DB, previniendo phantom reads. Fallback gracioso si no soportado.

4. **Provenance tracking end-to-end**: cada metrica lleva lineage (source query, row count, timestamp, confidence). Los agentes downstream saben si un numero es "measured" vs "estimated".

5. **CurrencyGuard anti-mixing**: prevencion explicita de errores de moneda mixta -- uno de los errores mas comunes en reporting de ERPs multinacionales.

6. **Patron Reflexion en Cartographer**: retry loop con feedback estructurado de Gate 1.5. Si el mapeo de schema falla, el sistema re-intenta con informacion sobre que fallo.

7. **QueryBuilder deterministico**: Stage 2 no usa LLM -- templates SQL parametrizados con zero hallucination risk y zero cost.

8. **Statistical checks avanzados**: STL decomposition, Benford's Law, CUSUM, cointegration -- metodos de quant finance aplicados a data quality.

9. **Frozen Brief pattern**: baseline compartido evita que agentes paralelos diverjan en sus numeros base. Single source of truth.

10. **SSH tunnel con ZeroTrust**: validacion de configs, tunnels efimeros, encryption at rest de credentials, auto-cleanup.

---

## 8. Debilidades

1. **dlt es solo referencia conceptual**: la documentacion y naming (`DeltaConnector`, "built on top of dlt") sugieren uso de la libreria dlt, pero **no hay integracion real**. Esto es confuso y podria ser misleading para nuevos developers.

2. **Solo 3 conectores operativos**: PostgreSQL, MySQL y Etendo. Faltan SAP HANA, SQL Server, Salesforce (marcados como alta prioridad en roadmap) y todos los cloud warehouses (BigQuery, Snowflake).

3. **Sin pipeline de ingesta incremental**: cada analisis es un "full scan" ad-hoc. No hay CDC (Change Data Capture), no hay diff entre runs a nivel de datos. El `QueryEvolver` adapta que queries priorizar pero no hay cache de datos entre jobs.

4. **Excel/CSV pathway es fragil**: la conversion a SQLite es naive -- no hay validacion de tipos, no hay manejo de encodings, no hay deteccion de estructura (header row, merged cells, multi-sheet relationships).

5. **Sin connection pooling entre jobs**: cada job crea un nuevo `create_engine()` y lo dispone al final. Para clientes con analisis frecuentes, esto es ineficiente (handshake SSL + SSH tunnel + auth en cada run).

6. **Pipeline acoplado al core legacy**: `pipeline.py` importa directamente `sqlalchemy.create_engine()` en `execute_queries()` y `gate_calibration()`, bypaseando la capa de conectores (`DeltaConnector`). Hay dos caminos de acceso a DB: el connector layer y el acceso directo via SQLAlchemy.

7. **SQL injection surface en `gate_calibration()`**: aunque hay validacion `_is_safe_identifier()` para tabla y columna, el `base_filter` se inyecta como string crudo en SQL. Un `base_filter` malicioso podria ejecutar SQL arbitrario. La validacion existe pero es parcial.

8. **Sin streaming de resultados**: todas las queries cargan resultados en memoria (hasta 10,000 rows). Para tablas grandes con analisis detallado, esto puede ser un cuello de botella.

9. **Celery worker single-threaded per job**: cada job crea un event loop nuevo (`asyncio.new_event_loop()`). No hay paralelismo real a nivel de queries dentro de un job. Las queries se ejecutan secuencialmente en `execute_queries()`.

10. **Sin soporte para APIs REST como data source**: Salesforce, HubSpot y otros CRMs requieren API connectors, no database connectors. La abstraccion `DeltaConnector` esta disenada exclusivamente para SQL databases.

---

## 9. Recomendaciones 2026

### Prioridad Alta

1. **Integrar dlt de verdad o eliminar las referencias**: si dlt es parte de la estrategia, implementar `dlt.pipeline()` para los conectores y aprovechar schema evolution, normalization y incremental loading. Si no, renombrar `DeltaConnector` y limpiar la documentacion para evitar confusion.

2. **Unificar acceso a DB via DeltaConnector**: migrar `pipeline.py` (`execute_queries`, `gate_calibration`) para usar `DeltaConnector.execute_query()` en lugar de `create_engine()` directo. Esto centraliza connection management y facilita agregar nuevos backends.

3. **Agregar SQL Server y SAP HANA connectors**: son las fuentes mas demandadas segun el roadmap. Implementar como subclases de `DeltaConnector` con drivers `pyodbc` (SQL Server) y `hdbcli` (SAP HANA).

4. **Sanitizar `base_filter` en `gate_calibration()`**: implementar AST-based SQL validation o parametrizar los filtros como bind parameters en lugar de string interpolation.

### Prioridad Media

5. **Agregar API connectors para CRMs**: crear una interfaz `DeltaAPIConnector` paralela a `DeltaConnector` que abstraiga REST APIs (Salesforce, HubSpot). Devolver resultados en el mismo formato `{tables, columns, rows}` para compatibilidad con el pipeline.

6. **Implementar cache de schema entre runs**: guardar el `entity_map` del Cartographer en ProfileStore. En el siguiente run del mismo cliente, validar que el schema no cambio (schema drift) antes de re-ejecutar Stage 1. Si el schema es identico, skip Stage 1 completo.

7. **Connection pooling para clientes frecuentes**: evaluar mantener un pool de conexiones (sin SSH tunnel) para clientes con analisis recurrentes. Implementar TTL y max connections per client.

8. **Streaming para queries grandes**: implementar cursor-based streaming en `execute_query()` usando `server_side_cursors=True` en SQLAlchemy para PostgreSQL. Procesar en chunks en lugar de cargar 10k rows en memoria.

### Prioridad Baja

9. **Agregar BigQuery y Snowflake**: usar `sqlalchemy-bigquery` y `snowflake-sqlalchemy` como drivers. La abstraccion DeltaConnector deberia funcionar sin cambios mayores.

10. **CDC para analisis incremental**: integrar Debezium o dlt incremental loading para clientes enterprise con analisis diarios. Esto permitiria analizar solo los datos nuevos desde el ultimo run.

11. **Robustecer Excel intake**: agregar deteccion de header row, manejo de merged cells, validacion de tipos, soporte de encoding, y un pre-check de estructura antes de convertir a SQLite.

---

## Archivos Clave

| Archivo | Rol |
|---------|-----|
| `shared/connectors/base.py` | Clase abstracta DeltaConnector |
| `shared/connectors/factory.py` | ConnectorFactory con registry |
| `shared/connectors/postgresql.py` | PostgreSQL via SQLAlchemy |
| `shared/connectors/mysql.py` | MySQL/MariaDB via SQLAlchemy |
| `shared/connectors/etendo.py` | Etendo ERP (PostgreSQL + SSH) |
| `core/valinor/pipeline.py` | Orquestador maestro (execute_queries, gate_calibration, compute_baseline, run_analysis_agents, reconcile_swarm, run_narrators) |
| `core/valinor/gates.py` | Gates inter-stage (cartographer, analysis, sanity, monetary) |
| `core/valinor/quality/data_quality_gate.py` | DataQualityGate (8+1 checks) |
| `core/valinor/quality/currency_guard.py` | Deteccion de moneda mixta |
| `core/valinor/quality/anomaly_detector.py` | IQR outlier detection |
| `core/valinor/quality/statistical_checks.py` | STL, Benford, CUSUM, cointegration |
| `core/valinor/quality/provenance.py` | Lineage tracking por finding |
| `core/valinor/quality/factor_model.py` | Descomposicion factorial de revenue |
| `core/valinor/agents/cartographer.py` | Schema discovery (Phase 1 determinista + Phase 2 LLM) |
| `core/valinor/agents/query_builder.py` | SQL generation deterministico |
| `core/valinor/tools/db_tools.py` | MCP tools para operaciones DB |
| `core/valinor/tools/excel_tools.py` | Excel/CSV a SQLite |
| `core/valinor/nl/vanna_adapter.py` | NL->SQL via Vanna AI |
| `shared/ssh_tunnel.py` | SSH tunnels efimeros + ZeroTrust |
| `api/adapters/valinor_adapter.py` | Punto de entrada SaaS al pipeline |
| `worker/tasks.py` | Celery tasks (run_analysis, cleanup, health) |
| `worker/celery_app.py` | Configuracion Celery (Redis broker) |
| `docs/SUPPORTED_SOURCES.md` | Documentacion de fuentes soportadas |
| `docs/ARCHITECTURE.md` | Arquitectura tecnica general |
