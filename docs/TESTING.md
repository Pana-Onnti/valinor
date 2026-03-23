# Testing Guide — Valinor SaaS

Guía completa de la suite de tests. Estrategia, archivos, convenciones, y cómo ejecutar.

## Filosofía de testing

1. **DB real, nunca mocks** — Los integration tests usan SQLite in-memory con schema real (Openbravo/Gloria). Nunca se mockea la base de datos.
2. **LLM agents: SIEMPRE REALES** — Los agentes (analyst, sentinel, hunter) corren contra Claude real via CLI local o proxy (`scripts/claude_proxy.py`) con Plan Max (gratis). Si el CLI/proxy no está disponible, los tests se **skipean** — nunca se mockean silenciosamente. Assertions sobre **estructura** (findings parseables, schema correcto), no valores exactos (Claude es no-determinista).
3. **Pipeline stages reales** — Query builder, execute_queries, compute_baseline, reconcile_swarm, prepare_narrator_context son código determinista Python puro — se ejecutan tal cual en tests.
4. **SDK stub en conftest** — `tests/conftest.py` instala un stub de `claude_agent_sdk` en `sys.modules` para imports. Los tests E2E lo reemplazan con el provider real via `shared/llm/monkey_patch.py`.

## Prerequisito para tests E2E

Los tests de agentes reales necesitan acceso a Claude. Antes de correr:

```bash
# Opción A: proxy (recomendado — Docker-friendly)
python3 scripts/claude_proxy.py &

# Opción B: claude CLI directo (si corres tests en el host)
which claude  # debe estar instalado
```

Si ninguno está disponible, los tests de agentes se skipean con mensaje claro.

## Ejecución rápida

```bash
# Full suite (~2500 tests)
pytest tests/ -v

# Solo el test E2E obligatorio (pipeline completo Gloria)
pytest tests/test_pipeline_gloria_e2e.py -v

# Solo un módulo
pytest tests/test_pipeline_integration.py -v

# Parar en primer fallo
pytest tests/ -x --tb=short

# Solo tests marcados como obligatorios
pytest tests/ -m mandatory -v

# Smoke rápido pre-PR
./scripts/smoke_test.sh
```

## Mapa de tests

### Test E2E obligatorio: `test_pipeline_gloria_e2e.py`

**El test más importante del proyecto.** Simula el pipeline completo que la app ejecuta
cuando un usuario lanza un análisis desde la UI. Usa schema Openbravo real en SQLite.

```
SQLite (Gloria schema) → Query Builder → Execute Queries → Baseline
→ Agents (mock LLM) → Reconciliation → Narrator Context → Narrators (mock LLM)
→ Validar estructura final de reportes
```

| Stage | Real o Mock | Por qué |
|-------|-------------|---------|
| SQLite con schema Gloria (4 tablas, ~40 rows) | **Real** | Datos reales de estructura Openbravo |
| Query Builder (`build_queries`) | **Real** | Código Python puro, genera SQL determinista |
| Execute Queries (`execute_queries`) | **Real** | Ejecuta SQL contra SQLite real |
| Compute Baseline (`compute_baseline`) | **Real** | Extrae métricas + provenance, Python puro |
| Agents: analyst, sentinel, hunter | **Mock** | Llaman a Claude Sonnet ($$, no-determinista) |
| Reconciliation (`reconcile_swarm`) | **Real** | Detección de conflictos es Python puro (arbiter Haiku solo se invoca si hay conflictos >2x) |
| Narrator Context (`prepare_narrator_context`) | **Real** | Filtrado por verification status, Python puro |
| Narrators (`run_narrators`) | **Mock** | Llaman a Claude para generar reportes narrativos |

**Tests en esta clase:**

| # | Test | Qué valida |
|---|------|------------|
| 1 | `test_query_builder_generates_all_domains` | Genera queries financial + data_quality. Inyecta base_filter. SQL no vacío. |
| 2 | `test_baseline_computation_from_query_results` | Extrae revenue, invoices, AR, customers. Provenance tracking. |
| 3 | `test_full_pipeline_stages_with_mocked_agents` | Pipeline completo: build → execute → baseline → agents → reconcile |
| 4 | `test_narrator_context_preparation` | Filtra findings por VERIFIED/FAILED. CEO solo ve verificados. |
| 5 | `test_entity_map_schema_compliance` | CartographerOutput parsea y roundtripea sin pérdida. |
| 6 | `test_full_pipeline_produces_app_output` | **Pipeline completo hasta reportes.** Valida que la estructura final sea idéntica a lo que la app entrega al usuario. |

### Tests de integración por módulo: `test_pipeline_integration.py`

El archivo más grande (~2900 líneas, 20+ suites). Testea cada componente del pipeline en profundidad.

| Suite | Qué cubre |
|-------|-----------|
| `TestDataQualityGateIntegration` | DQ gate: 8 checks, scoring, gate decision |
| `TestCurrencyGuardIntegration` | Detección de moneda en datos |
| `TestSegmentationEngineIntegration` | Segmentación de clientes/productos |
| `TestProvenanceRegistryIntegration` | Tracking de origen de cada finding |
| `TestAnomalyDetectorIntegration` | Detección de outliers |
| `TestQualityCertifierIntegration` | Certificación de reportes |
| `TestProfileExtractorIntegration` | Extracción de perfil del cliente |
| `TestComputeBaselineIntegration` | Cálculo de baseline con edge cases |
| `TestGateCalibrationIntegration` | Guard Rail: SQL COUNTs reales |
| `TestExecuteQueriesIntegration` | Ejecución de queries con timeout |
| `TestReconcileSwarmIntegration` | Reconciliación de conflictos entre agentes |
| `TestDQGatePipelineIntegration` | Cadena DQ gate → provenance completa |
| `TestMultiAgentFallbackScenarios` | Degradación cuando agentes fallan |
| `TestPipelineDegradation` | Pipeline con datos parciales o vacíos |

### Smoke tests: `test_smoke_pipeline.py`

Tests rápidos (<5s) que verifican que nada crashea. Útiles para desarrollo.

| Test | Qué verifica |
|------|-------------|
| `test_execute_queries_returns_dict_format` | Formato de retorno de queries |
| `test_segmentation_no_crash` | Segmentación engine no explota |
| `test_currency_guard_no_crash` | Currency guard no explota |
| `test_anomaly_detector_no_crash` | Anomaly detector no explota |
| `test_query_evolver_no_crash` | Query evolver no explota |
| `test_full_post_query_chain` | Cadena completa post-query sin crash |

### Knowledge Graph + Verification: `test_grounded_v2_integration.py`

Anti-hallucination system tests.

| Test | Qué verifica |
|------|-------------|
| Build KG from entity_map | Grafo de conocimiento se construye correctamente |
| Verification engine on query results | Claims se verifican contra datos reales |
| Gate verification pass/warn | Gate distingue datos verificados vs no |
| Verification report serialization | Reporte serializa/deserializa sin pérdida |

### API + Adapters: `test_mvp.py`

Tests a nivel de adapter (capa de aplicación).

| Test | Qué verifica |
|------|-------------|
| `test_run_analysis_success` | SSH → Pipeline → Storage completo |
| `test_complete_analysis_flow_mock` | Config validation → Storage → Retrieval |
| `test_adapter_timeout_raises_error` | Timeout handling |

### API Endpoints: `test_api_endpoints.py`

50+ tests HTTP con `httpx.AsyncClient` contra FastAPI.

- `/health`, `/system/status`
- `/analyze` — creación de jobs, validación de periodos
- Job status retrieval
- PDF export
- Rate limiting y error handling

## Infraestructura de tests

### `tests/conftest.py`

Fixtures compartidos entre todos los tests:

| Fixture | Uso |
|---------|-----|
| `gloria_entity_map` | Entity map con schema Openbravo real (4 entidades, 3 relaciones) |
| `generic_entity_map` | Entity map genérico (no atado a ERP) |
| `minimal_client_config` | Config mínima de cliente |
| `populated_baseline` | Baseline con métricas reales medidas |
| `minimal_baseline` | Baseline sin datos |
| `mock_profile` | ClientProfile mock |
| `run_async()` | Helper para ejecutar coroutines en tests sync |

### SDK Stubs

`conftest.py` instala stubs automáticos si los SDKs no están instalados:

- `claude_agent_sdk` — `query()` retorna async generator vacío, `ClaudeAgentOptions`, `TextBlock`, `AssistantMessage` disponibles
- `anthropic` — `AsyncAnthropic`, `Message` disponibles

### pytest config (`pyproject.toml`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
addopts = "-v --tb=short --strict-markers"
asyncio_mode = "auto"
markers = [
    "mandatory: tests that must pass before any merge",
]
```

## Convenciones

1. **Archivos**: `tests/test_<módulo>.py`
2. **Clases**: `TestXxxIntegration` para suites de integración
3. **Async**: `@pytest.mark.asyncio` con `asyncio_mode = "auto"`
4. **Parametrize**: Usar `@pytest.mark.parametrize` para variaciones del mismo test
5. **No duplicar**: Suite actual ~2500+ tests. Verificar que no exista antes de agregar.
6. **Imports**: Siempre importar desde `valinor.*`, nunca paths relativos.

## Pipeline completo vs qué está testeado

```
Stage 0:  DQ Gate              → TestDataQualityGateIntegration ✓
Stage 1:  Cartographer          → (mock en test_mvp.py) ⚠ LLM
Stage 1.5: Guard Rail           → TestGateCalibrationIntegration ✓
Stage 2:  Query Builder         → test_gloria_e2e test 1 ✓
Stage 2.5: Execute Queries      → test_gloria_e2e test 3 ✓
Post-2.5: Compute Baseline      → test_gloria_e2e tests 2,3 ✓
Stage 3:  Analysis Agents       → test_gloria_e2e test 3 (mock LLM) ✓
Stage 3.5: Reconciliation       → test_gloria_e2e test 3 ✓
Stage 3.75: Narrator Context    → test_gloria_e2e test 4 ✓
Stage 4:  Narrators             → test_gloria_e2e test 6 (mock LLM) ✓
Stage 5:  Deliver               → (no testeado aisladamente) ⚠
```
