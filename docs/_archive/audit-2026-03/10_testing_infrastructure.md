# 10. Infraestructura de Testing -- Valinor SaaS

**Fecha de analisis:** 2026-03-22
**Branch:** develop (commit afa3892f)

---

## 1. Resumen Ejecutivo

Valinor SaaS cuenta con una suite de testing robusta compuesta por **62 archivos de test** en `tests/` mas **2 archivos de test de seguridad** en `security/`, sumando aproximadamente **2,821 funciones de test** (2,795 en tests/ + 26 en security/). La suite incluye **434 clases de test** organizadas por modulo. El proyecto usa **pytest** como framework principal con soporte async nativo via `pytest-asyncio`. No existe `conftest.py` compartido; cada archivo gestiona sus propios stubs y fixtures inline.

La cobertura es amplia en capas de dominio (quality, memory, tools) y API endpoints, pero tiene gaps en los agentes LLM (cartographer, analyst, sentinel, hunter), el pipeline orquestador (`pipeline.py`, `run.py`), y los conectores de base de datos (`shared/connectors/`). El umbral de cobertura en CI es **60%** (`--cov-fail-under=60`).

---

## 2. Framework y Configuracion

### 2.1 Stack de Testing

| Componente | Herramienta | Version |
|---|---|---|
| Runner | pytest | >=7.4 (CI), 9.0.2 (local) |
| Async | pytest-asyncio | >=0.21, mode=auto |
| Coverage | pytest-cov | >=4.1 |
| HTTP Client | httpx (AsyncClient + ASGITransport) | >=0.25 |
| Mocking | unittest.mock (MagicMock, AsyncMock, patch) | stdlib |
| DB en tests | SQLite in-memory (via SQLAlchemy) | -- |
| Test data | Faker (disponible, poco usado) | >=20.1 |
| Linting | flake8 (CI), ruff + black (config) | -- |
| Type checking | mypy (configurado, no en CI pipeline) | >=1.7 |

### 2.2 Configuracion (pytest.ini + pyproject.toml)

Existen **dos configuraciones en tension**:

- **`pytest.ini`**: `testpaths = tests security`, `addopts = -v --tb=short`, `asyncio_mode = auto`
- **`pyproject.toml` [tool.pytest.ini_options]**: `testpaths = ["tests"]` (NO incluye security), `addopts = "-v --tb=short --strict-markers"`, `asyncio_mode = "auto"`

El `pytest.ini` tiene precedencia sobre `pyproject.toml` segun la documentacion de pytest. Esto significa que `security/` SI se ejecuta en local pero **podria no ejecutarse en CI** si el CI invoca `pytest tests/` explicitamente (que es lo que hace el workflow).

### 2.3 CI/CD Integration

**GitHub Actions** (`/.github/workflows/tests.yml`):

- **Trigger**: push a `master`, PR a `main`
- **Matrix**: Python 3.10 + 3.11
- **Pipeline**: lint (flake8) -> test (pytest con coverage)
- **Coverage**: `--cov=api --cov=shared --cov=core`, threshold 60%, reporte XML + Codecov
- **Artefactos**: JUnit XML, JSON report, coverage XML (retencion 14 dias)
- **Branches incorrectos**: El trigger dice `master` para push pero el proyecto usa `main` como branch principal. Esto puede causar que los tests no se disparen en push a `main`.

**Git Hooks**:
- `commit-msg`: Valida conventional commits (`tipo(scope): desc`) y exige `Refs: VAL-XX`
- No hay `pre-commit` hook que ejecute tests automaticamente

---

## 3. Cobertura por Modulo

### 3.1 Modulos CON tests directos

| Modulo | Archivo(s) de Test | Tipo | Tests aprox. |
|---|---|---|---|
| **API Endpoints** (main.py) | test_api_endpoints, test_system_endpoints, test_job_lifecycle, test_job_management, test_streaming | Integration (httpx) | ~300 |
| **Client Endpoints** | test_client_endpoints | Integration | ~70 |
| **Alert Engine** | test_alert_engine, test_alert_thresholds | Unit + Integration | ~90 |
| **Webhook** | test_webhook_endpoints, test_webhook_dispatcher | Unit + Integration | ~70 |
| **Digest/Email** | test_digest_endpoints, test_email_digest | Unit + Integration | ~80 |
| **Data Quality Gate** | test_data_quality_gate, test_data_quality | Unit | ~50 |
| **Currency Guard** | test_currency_guard | Unit | ~50 |
| **Anomaly Detector** | test_anomaly_detector | Unit | ~30 |
| **Factor Model** | test_factor_model | Unit (mock _get_period_metrics) | ~30 |
| **Statistical Checks** | test_statistical_checks | Unit (math puro) | ~30 |
| **Provenance** | test_provenance | Unit | ~20 |
| **Analysis Tools** | test_analysis_tools | Unit (async) | ~40 |
| **DB Tools** | test_db_tools | Unit (SQLite real) | ~40 |
| **Excel Tools** | test_excel_tools | Unit (tmp files) | ~20 |
| **Memory Tools** | test_memory_tools | Unit (tmp_path) | ~20 |
| **Query Builder** | test_query_builder | Unit | ~30 |
| **Query Evolver** | test_query_evolver | Unit | ~20 |
| **Cartographer** | test_cartographer | Unit (SQLite + mock SDK) | ~30 |
| **Narrators** | test_narrators | Unit (mock SDK) | ~30 |
| **Sentinel Patterns** | test_sentinel_patterns | Unit (puro) | ~20 |
| **Client Profile** | test_profile_store, test_profile_extractor, test_profile_extractor_and_tuner | Unit | ~60 |
| **Memory Layer** | test_memory_layer | Unit | ~40 |
| **Adaptive Context** | test_adaptive_context | Unit | ~50 |
| **Industry Detector** | test_industry_detector | Unit | ~20 |
| **Segmentation Engine** | test_segmentation_engine | Unit | ~20 |
| **Refinement** | test_refinement | Unit | ~30 |
| **Date/Formatting Utils** | test_date_utils, test_formatting_utils, test_utils | Unit | ~80 |
| **SSH Tunnel** | test_ssh_tunnel | Unit (mock paramiko) | ~15 |
| **Exceptions** | test_exceptions | Unit | ~15 |
| **MVP** | test_mvp | Unit/Integration | ~16 |
| **Performance** | test_performance | Benchmark | ~10 |
| **PDF Generator** | test_pdf_generator | Unit | ~15 |
| **Onboarding** | test_onboarding | Integration (httpx) | ~15 |
| **Rate Limiting** | test_rate_limiting | Integration (httpx) | ~36 |
| **Smoke Pipeline** | test_smoke_pipeline | Integration (pipeline chain) | ~6 |
| **FastMCP Etendo** | test_fastmcp_etendo | Unit (mock) | ~15 |
| **Seguridad** | security/test_prompt_injection, test_tenant_isolation | Seguridad | ~26 |

### 3.2 Modulos SIN tests (o con cobertura minima)

| Modulo | Path | Razon probable |
|---|---|---|
| **Pipeline orquestador** | `core/valinor/pipeline.py` | Requiere LLM + DB |
| **Run entry point** | `core/valinor/run.py` | Requiere stack completo |
| **Analyst agent** | `core/valinor/agents/analyst.py` | Depende de LLM |
| **Sentinel agent** | `core/valinor/agents/sentinel.py` | Depende de LLM |
| **Hunter agent** | `core/valinor/agents/hunter.py` | Depende de LLM |
| **Vaire agent + PDF** | `core/valinor/agents/vaire/` | Depende de LLM |
| **Query Generator** | `core/valinor/agents/query_generator.py` | Tiene test pero parcial |
| **Deliver module** | `core/valinor/deliver.py` | Parcial en test_profile_extractor_and_tuner |
| **Conectores** | `shared/connectors/{etendo,mysql,postgresql}.py` | Requieren DB real |
| **LLM layer** | `shared/llm/` (adapter, providers, monkey_patch) | Depende de API keys |
| **Vanna adapter** | `core/valinor/nl/vanna_adapter.py` | Requiere Vanna AI |
| **Worker tasks** | `worker/` (solo test_worker_tasks parcial) | Requiere Celery/Redis |
| **Observability** | `shared/observability.py` | Tiene test (test_observability) |
| **API metrics** | `api/metrics.py` | Sin tests |
| **Logging config** | `api/logging_config.py` | Sin tests |
| **Calibration** | `core/valinor/calibration/` | Tiene tests (test_calibration) |
| **Discovery** | `core/valinor/discovery/` | Tiene tests (test_discovery) |
| **Knowledge Graph** | `core/valinor/knowledge_graph.py` | Tiene tests (test_knowledge_graph) |
| **Verification** | `core/valinor/verification.py` | Tiene tests (test_verification, test_active_verification) |

---

## 4. Fixtures

### 4.1 Patron General

No existe un **`conftest.py`** centralizado. Cada archivo de test define sus propios fixtures y helpers inline. Esto genera **duplicacion significativa** del codigo de stub/mock.

### 4.2 Fixtures Recurrentes

| Fixture | Uso | Archivos |
|---|---|---|
| `sqlite_db` / `minimal_engine` / `empty_engine` | SQLite tmp_path para tests de DB | test_db_tools, test_cartographer |
| `client` (httpx.AsyncClient) | HTTP client via ASGITransport | 12+ archivos de endpoints |
| `_make_redis_mock()` | Mock completo de redis.asyncio | test_api_endpoints, test_digest_endpoints, etc |
| `_profile()` / `make_profile()` | ClientProfile factory | test_adaptive_context, test_alert_engine, etc |
| `_make_stub()` / `_stub_missing()` | Stubbing de dependencias opcionales | 15+ archivos |

### 4.3 Patron de Stubbing de Dependencias

El patron mas prominente es el **stubbing masivo de sys.modules** al inicio de cada archivo de test de endpoints. Cada archivo replica ~50 lineas de stubs para:
- `supabase` (create_client, Client)
- `slowapi` (Limiter, RateLimitExceeded)
- `structlog` (get_logger)
- `adapters.valinor_adapter` (ValinorAdapter, PipelineExecutor)
- `shared.storage` (MetadataStorage)
- `shared.memory.profile_store` (get_profile_store)
- `claude_agent_sdk` (tool, query, etc)

Este patron se repite en al menos **15 archivos** identicamente.

---

## 5. Mocking Strategy

### 5.1 Niveles de Mocking

| Nivel | Tecnica | Ejemplo |
|---|---|---|
| **Dependencias no instaladas** | `sys.modules` stubs con `types.ModuleType` | claude_agent_sdk, supabase, slowapi, structlog |
| **IO externo (Redis)** | `AsyncMock` con `patch()` | redis.asyncio.from_url |
| **IO externo (HTTP)** | `httpx.AsyncClient` + ASGITransport | Tests de API sin servidor real |
| **IO externo (DB)** | SQLite in-memory via `tmp_path` | test_db_tools, test_cartographer |
| **IO externo (filesystem)** | `tmp_path` de pytest | test_memory_tools, test_profile_store |
| **LLM calls** | `MagicMock` / `AsyncMock` de `claude_agent_sdk.query` | test_cartographer, test_narrators |
| **Time** | `time.perf_counter()` directo | test_performance |
| **Date pinning** | `unittest.mock.patch("...datetime")` | test_date_utils |

### 5.2 Patrones Destacados

1. **Tool decorator passthrough**: El decorator `@tool` del claude_agent_sdk se stubea como identity function, permitiendo testear las funciones de herramienta como funciones Python normales.

2. **Async sync bridge**: Muchos tests usan `asyncio.get_event_loop().run_until_complete(coro)` para ejecutar funciones async de forma sincrona, en lugar de usar el marker `@pytest.mark.asyncio`.

3. **Parse result pattern**: Funcion helper `parse_result()` que desenvuelve la estructura `{"content": [{"text": "..."}]}` del SDK de agentes.

---

## 6. Integration vs Unit Tests

### 6.1 Distribucion

| Tipo | Archivos | Tests aprox. | % |
|---|---|---|---|
| **Unit tests puros** (sin IO) | ~35 | ~1,500 | 53% |
| **Unit tests con SQLite** (IO minimo) | ~5 | ~200 | 7% |
| **Integration tests API** (httpx + ASGITransport) | ~15 | ~800 | 28% |
| **Smoke / pipeline** | 1 | ~6 | <1% |
| **Performance / benchmark** | 1 | ~10 | <1% |
| **Security** | 2 | ~26 | 1% |
| **Async integration** (pytest.mark.asyncio) | ~11 | ~437 | 15% |

### 6.2 Tests de Integracion Reales

El **test_smoke_pipeline.py** es el unico test que simula el pipeline end-to-end con datos reales (SQLite con 3 tablas y 8 facturas). Ejecuta: `build_queries -> execute_queries -> currency_guard -> anomaly_detector -> segmentation_engine -> query_evolver`. No invoca LLM.

No existen tests de integracion que:
- Conecten a Redis real
- Usen Docker Compose
- Ejecuten contra PostgreSQL/MySQL real
- Invoquen el LLM (ni siquiera con responses mockeadas realistas)

---

## 7. CI Integration

### 7.1 Workflow Actual (.github/workflows/tests.yml)

```
lint (flake8) -> test (pytest con coverage, matrix 3.10+3.11) -> upload artefactos
```

**Problemas detectados:**
1. **Branch mismatch**: Push trigger en `master` pero proyecto usa `main` como branch principal
2. **Security tests excluidos**: CI ejecuta `pytest tests/` explicitamente, ignorando `security/`
3. **No hay stage de type checking**: mypy configurado pero no ejecutado en CI
4. **No hay test de integracion con servicios**: No hay Docker Compose en CI
5. **Coverage threshold bajo**: 60% es permisivo para un proyecto en produccion

### 7.2 Coverage Config

```toml
[tool.coverage.run]
source = ["valinor_saas", "api", "worker", "shared"]
omit = ["*/tests/*", "*/test_*.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
```

Nota: `source` incluye `valinor_saas` (que no existe como paquete) y no incluye `core`, pero el CI flag `--cov=core` lo corrige.

---

## 8. Fortalezas

1. **Volumen impresionante**: ~2,821 tests es una cifra alta para el tamano del proyecto. La mayoria de los modulos de dominio tienen cobertura densa.

2. **Tests puros sin IO**: La mayoria de los unit tests son "pure logic" -- no requieren DB, red, ni filesystem. Esto los hace rapidos y deterministicos.

3. **API tests completos**: Los endpoints de FastAPI se testean exhaustivamente via httpx.AsyncClient con ASGITransport, cubriendo happy paths, error handling, edge cases, y status codes.

4. **Edge cases y boundary testing**: Multiples archivos incluyen secciones explicitas de "boundary conditions" y "edge cases" (ej: test_adaptive_context tiene 14 clases de test, test_alert_engine cubre 35+ escenarios).

5. **Security testing**: Suite dedicada con payloads adversariales para prompt injection y tenant isolation (VAL-34).

6. **Performance tests**: Benchmarks con tolerancias explicitas para CI runners con carga variable.

7. **Docstrings en tests**: Cada test function tiene un docstring explicativo del comportamiento esperado.

8. **Smoke test de pipeline**: test_smoke_pipeline verifica la cadena completa de post-procesamiento sin LLM.

9. **Conventional commits enforced**: Hook de commit-msg valida formato y referencia a Linear.

---

## 9. Debilidades

1. **No hay conftest.py**: La duplicacion de stubs/mocks en 15+ archivos es un problema de mantenimiento critico. Cambiar un stub requiere editar multiples archivos.

2. **Stubbing fragil via sys.modules**: El patron de inyectar modulos falsos en `sys.modules` antes del import es fragil -- el orden de ejecucion de archivos de test puede causar side effects cruzados (un test puede romper los stubs de otro).

3. **asyncio.get_event_loop() deprecado**: Multiples archivos usan `asyncio.get_event_loop().run_until_complete()` que esta deprecated desde Python 3.10 y genera warnings. Deberian usar `@pytest.mark.asyncio` o `asyncio.run()`.

4. **Sin tests de agentes LLM**: Los agentes analyst, sentinel, hunter, y vaire no tienen tests unitarios. Son el nucleo del producto pero estan completamente sin testear en aislamiento.

5. **Coverage threshold al 60%**: Para un SaaS en produccion con datos financieros, 60% es insuficiente. El target deberia ser 80%+ para modulos criticos.

6. **Branch mismatch en CI**: El workflow dispara en push a `master` pero el proyecto usa `main`. Los tests pueden no ejecutarse automaticamente.

7. **Security tests no incluidos en CI**: `pytest tests/` en el workflow excluye el directorio `security/`.

8. **No hay pytest markers definidos**: No hay markers custom como `@pytest.mark.slow`, `@pytest.mark.integration`, `@pytest.mark.security`. Solo se usa `asyncio` y `skipif`.

9. **Sin parametrize extensivo**: Solo 2 usos de `@pytest.mark.parametrize` en toda la suite. Muchos tests repiten patrones que serian candidatos naturales para parametrizacion.

10. **Sin property-based testing**: No hay uso de Hypothesis para testing basado en propiedades, que seria especialmente valioso en los modulos de quality (currency guard, anomaly detector, statistical checks).

11. **No hay mutation testing**: No hay herramientas como mutmut o cosmic-ray configuradas para validar la calidad de los tests.

12. **TESTING_INSTRUCTIONS.md desactualizado**: Describe pruebas manuales del MVP simple original, no la suite de testing actual.

---

## 10. Recomendaciones 2026

### P0 -- Critico (Sprint actual)

1. **Crear `tests/conftest.py` centralizado**: Extraer los stubs comunes (supabase, slowapi, structlog, claude_agent_sdk, redis mock, httpx client fixture) a un conftest compartido. Esto eliminara ~750 lineas de codigo duplicado.

2. **Corregir CI workflow**: Cambiar trigger de `master` a `main`. Agregar `security/` al path de ejecucion de pytest.

3. **Subir coverage threshold**: De 60% a 75% inicialmente, con target 80% para Q2.

### P1 -- Alto (Proximo sprint)

4. **Agregar tests de agentes con respuestas mockeadas**: Crear tests para analyst, sentinel, hunter con responses LLM pre-grabadas (cassettes/fixtures). No requiere API keys pero valida la logica de parsing y decision.

5. **Migrar a `@pytest.mark.asyncio`**: Reemplazar todos los `asyncio.get_event_loop().run_until_complete()` por el decorator nativo de pytest-asyncio.

6. **Definir markers custom**: `@pytest.mark.slow`, `@pytest.mark.integration`, `@pytest.mark.security`, `@pytest.mark.smoke`. Registrarlos en pyproject.toml con `--strict-markers`.

7. **Agregar mypy al CI**: El type checking esta configurado pero no se ejecuta. Agregarlo como stage del workflow.

### P2 -- Medio (Q2 2026)

8. **Parametrizar tests repetitivos**: Identificar tests con patrones identicos (ej: currency_guard tiene 5 clases con tests casi identicos) y convertirlos a `@pytest.mark.parametrize`.

9. **Agregar property-based testing**: Usar Hypothesis en statistical_checks, currency_guard, formatting utils.

10. **Integration tests con Docker Compose**: Crear un workflow separado que levante Redis + PostgreSQL via Docker Compose para tests de integracion reales.

11. **Agregar tests de conectores**: `shared/connectors/` (etendo, mysql, postgresql) no tienen tests. Al menos cubrir la logica de conexion con mocks.

12. **Test de pipeline end-to-end con LLM mock**: Extender test_smoke_pipeline para cubrir el flujo completo incluyendo narrators con respuestas pre-grabadas.

### P3 -- Mejoras (Q3 2026)

13. **Mutation testing**: Integrar mutmut para validar que los tests realmente detectan bugs.

14. **Actualizar TESTING_INSTRUCTIONS.md**: Reescribirlo para reflejar la suite actual, incluyendo como ejecutar subsets de tests, generar reportes de coverage, y correr security tests.

15. **Snapshot testing para reportes**: Usar snapshot assertions para el HTML del email digest y los PDFs generados.

16. **Contract testing**: Agregar tests de contrato para la API publica (OpenAPI schema validation contra tests).

---

## Anexo A: Estructura de Archivos de Test

```
tests/
  __init__.py
  test_active_verification.py    # Verification engine
  test_adaptive_context.py       # AdaptiveContextBuilder (50 tests, 14 clases)
  test_agent_schemas.py          # Pydantic schemas de agentes
  test_alert_engine.py           # AlertEngine.check_thresholds (35+ tests)
  test_alert_thresholds.py       # API endpoints de alertas (44 async)
  test_analysis_tools.py         # revenue_calc, aging_calc, pareto, gates (~40)
  test_anomaly_detector.py       # AnomalyDetector IQR (~30)
  test_api_endpoints.py          # Endpoints core del API (~50 async)
  test_calibration.py            # Self-calibration loop
  test_cartographer.py           # Cartographer agent (SQLite + mock)
  test_client_endpoints.py       # /api/clients/* (~70 async)
  test_connectors.py             # Connector factory
  test_currency_guard.py         # CurrencyGuard (~50)
  test_data_quality_gate.py      # DQ gate, scoring, context
  test_data_quality.py           # DQ checks adicionales
  test_date_utils.py             # parse_period, format_duration, days_since
  test_db_tools.py               # connect_database, introspect, sample, probe
  test_digest_endpoints.py       # /digest, /send-digest, /quality
  test_discovery.py              # FK discovery, profiler, ontology
  test_email_digest.py           # EmailDigestBuilder
  test_excel_tools.py            # excel_to_sqlite, csv_to_sqlite
  test_exceptions.py             # Exception hierarchy
  test_factor_model.py           # RevenueFactorModel, Shapley
  test_fastmcp_etendo.py         # FastMCP server (VAL-28)
  test_formatting_utils.py       # format_currency, slugify, etc
  test_grounded_v2_integration.py # Grounded analysis v2
  test_industry_detector.py      # IndustryDetector
  test_job_lifecycle.py          # Job create -> status -> results
  test_job_management.py         # cancel, retry, cleanup, export
  test_knowledge_graph.py        # Knowledge graph
  test_memory_layer.py           # Memory layer completa
  test_memory_tools.py           # read_memory, write_memory
  test_mvp.py                    # MVP basic functionality
  test_narrators.py              # Narrator system prompts
  test_nl_query.py               # Natural language query
  test_observability.py          # Observability module
  test_onboarding.py             # Onboarding routes
  test_pdf_generator.py          # PDF generation
  test_performance.py            # CPU benchmarks
  test_pipeline_integration.py   # Pipeline integration
  test_profile_extractor.py      # ProfileExtractor
  test_profile_extractor_and_tuner.py  # Extractor + PromptTuner + FocusRanker
  test_profile_store.py          # ProfileStore file backend
  test_provenance.py             # FindingProvenance, ProvenanceRegistry
  test_query_builder.py          # Deterministic SQL generation
  test_query_evolver.py          # QueryEvolver
  test_query_generator.py        # Query generator
  test_rate_limiting.py          # Rate limiting, CORS, headers
  test_refinement.py             # PromptTuner, FocusRanker, QueryEvolver, RefinementAgent
  test_segmentation_engine.py    # SegmentationEngine
  test_sentinel_patterns.py      # PATTERNS, get_patterns_for_tables
  test_smoke_pipeline.py         # Pipeline end-to-end smoke
  test_ssh_tunnel.py             # ZeroTrustValidator, SSHTunnelManager
  test_statistical_checks.py     # CUSUM, Benford, z-score, cointegration
  test_streaming.py              # SSE and WebSocket endpoints
  test_system_endpoints.py       # /health, /metrics, /system
  test_token_tracker.py          # Token tracking
  test_utils.py                  # Shared utils
  test_verification.py           # Verification module
  test_webhook_dispatcher.py     # WebhookDispatcher
  test_webhook_endpoints.py      # /api/clients/{name}/webhooks
  test_worker_tasks.py           # Celery worker tasks

security/
  adversarial_inputs.py          # Payloads adversariales (PI, SQL, tenant)
  test_prompt_injection.py       # Prompt injection guardrails (18 tests)
  test_tenant_isolation.py       # Cross-tenant isolation (8 tests)
```

## Anexo B: Dependencias de Test

```toml
# pyproject.toml [project.optional-dependencies.dev]
pytest>=7.4
pytest-asyncio>=0.21
pytest-cov>=4.1
black>=23.12
ruff>=0.1
mypy>=1.7
httpx>=0.25       # AsyncClient para API tests
faker>=20.1       # Poco utilizado actualmente
```

Dependencias adicionales usadas en tests pero no declaradas como dev-deps:
- `sqlalchemy` (ya en deps principales)
- `numpy` (usado en test_statistical_checks)
- `pytest-json-report` (requerido en CI pero no en dev deps)
