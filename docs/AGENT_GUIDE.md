# Valinor SaaS — Guía para el Próximo Agente

> Este documento describe el estado actual del proyecto, cómo está organizado, qué fue construido, y cómo continuar el desarrollo sin romper nada.

---

## 1. Estado Actual (Marzo 2026)

- **2481 tests pasando** (`pytest tests/ -q`) — cobertura del 100% de los módulos públicos
- **Pipeline completo funcionando** en Docker local
- **Todas las fases 1–4 y 6 completadas** — queda solo Phase 5 (deployment a Cloudflare/GH Actions)
- **Branch activo**: `develop` (main branch para PRs: `main`)

---

## 2. Cómo arrancar

```bash
cd /home/nicolas/Documents/delta4/valinor-saas

# Activar virtualenv (SIEMPRE antes de correr cualquier cosa Python)
source venv/bin/activate

# Correr tests
pytest tests/ -q --tb=short

# Levantar stack completo
docker compose up -d

# Verificar que todo esté OK
curl http://localhost:8000/health
```

**Puertos en Docker:**
| Servicio | Host | Container |
|---|---|---|
| API | 8000 | 8000 |
| Frontend | 3000 | 3000 |
| PostgreSQL | **5450** | 5432 |
| Redis | **6380** | 6379 |
| Prometheus | 9090 | 9090 |

> ⚠️ 5432 y 6379 están ocupados por servicios locales del host. Siempre usar 5450/6380.

---

## 3. Mapa del código

```
valinor-saas/
├── api/
│   ├── main.py                  # FastAPI app, middleware, routers
│   ├── webhooks.py              # build_job_summary, fire_job_completion_webhook
│   ├── email_digest.py          # DigestComposer, build_subject(client_name, delta, dq_score)
│   ├── pdf_generator.py         # PDFGenerator — export a PDF con DQ bar + alerts
│   ├── adapters/
│   │   ├── valinor_adapter.py   # Punto de entrada al pipeline v0 — NO modificar internals
│   │   └── exceptions.py        # ValinorError, SSHConnectionError, DatabaseConnectionError,
│   │                            # PipelineTimeoutError, DQGateHaltError(msg, dq_score, gate_decision)
│   ├── routes/
│   │   ├── onboarding.py        # /api/onboarding/*, connection tester
│   │   └── quality.py           # /api/quality/* — DQ reports por job
│   ├── middleware/              # Rate limiting, request_id, audit logging
│   └── refinement/
│       ├── query_evolver.py     # Aprende qué queries dan resultados valiosos
│       ├── prompt_tuner.py      # Ajusta prompts según historial del cliente
│       ├── focus_ranker.py      # Rankea entidades por relevancia analítica
│       └── refinement_agent.py  # Orquesta todo el ciclo de refinement
│
├── shared/
│   ├── ssh_tunnel.py            # SSHTunnelManager + ZeroTrustValidator
│   ├── webhook_dispatcher.py    # WebhookDispatcher con retry exponencial
│   ├── email_digest.py          # Shared email utilities
│   ├── pdf_generator.py         # Shared PDF utilities
│   ├── storage.py               # Abstracción de storage (Redis + PostgreSQL)
│   ├── memory/
│   │   ├── client_profile.py    # ClientProfile dataclass — perfil persistido por cliente
│   │   ├── profile_store.py     # ProfileStore — CRUD de perfiles en Redis/PostgreSQL
│   │   ├── profile_extractor.py # Extrae perfil de los resultados de un análisis
│   │   ├── adaptive_context_builder.py  # Construye contexto histórico para los agentes
│   │   ├── segmentation_engine.py       # Segmenta clientes por valor/frecuencia/recencia
│   │   ├── alert_engine.py      # AlertEngine — evalúa umbrales, dispara alerts
│   │   ├── industry_detector.py # Detecta industria del cliente por las tablas que tiene
│   │   └── storage.py           # Memory-specific storage layer
│   ├── llm/                     # LLM provider abstraction
│   ├── storage/                 # Storage backends
│   ├── types/                   # Pydantic models compartidos
│   └── utils/                   # date_utils, statistical_checks, etc.
│
├── core/valinor/                # Pipeline v0 — PRESERVADO, no modificar
│   ├── pipeline.py              # Orquestador principal del análisis
│   ├── agents/                  # Cartographer, QueryBuilder, Analysts, Narrators
│   ├── gates.py                 # DataQualityGate (8+1 checks)
│   ├── quality/                 # CurrencyGuard, AnomalyDetector, SentinelPatterns
│   └── tools/                   # analysis_tools (revenue_calc, aging_calc, pareto_analysis...)
│
├── web/                         # Next.js frontend
│   └── src/app/                 # App Router — pages: /, /reports, /quality/[jobId], /anomalies
│
├── tests/                       # 50 archivos, 2481 tests
└── docker-compose.yml
```

---

## 4. APIs y firmas críticas — NO asumir, verificar

Estos fueron los errores más comunes. Antes de escribir tests o usar estas funciones:

| Función | Firma correcta | Error común |
|---|---|---|
| `revenue_calc` | Retorna `{"breakdown": {...}}` | Asumir `{"groups": {...}}` |
| `aging_calc` | Param: `due_date_field` | Usar `date_field` |
| `pareto_analysis` | Param: `value_field` | Usar `amount_field` |
| `gate_cartographer` | Entities: `customers/invoices/products/payments` | Usar nombres arbitrarios |
| `build_subject` | `(self, client_name: str, delta: dict, dq_score: float)` | Pasar un profile object |
| `DQGateHaltError` | `(msg, dq_score=None, gate_decision=None)` | Pasar `failed_checks=` |
| `_make_query_results` | Dict con key `client_name` | Usar `customer_name` |
| `IndustryDetector` distribución | Tablas: `c_order/m_warehouse/c_invoice` | Usar `sale_order/stock_picking` |

**Regla de oro**: antes de escribir tests para una función, hacer:
```bash
source venv/bin/activate
python3 -c "from module import Func; import inspect; print(inspect.signature(Func))"
```

---

## 5. Test isolation gotcha

`tests/test_worker_tasks.py` instala stubs en `sys.modules` para `api.webhooks`. Si corrés tests en orden alfabético, contamina `test_webhook_endpoints.py`.

**Fix ya aplicado**: los métodos `_import()` en `TestBuildJobSummary` y `TestFireJobCompletionWebhook` usan `importlib.reload(api.webhooks)`. No remover eso.

```python
def _import(self):
    import importlib, api.webhooks as _wh
    importlib.reload(_wh)
    return _wh.build_job_summary
```

---

## 6. Patrón de desarrollo establecido

### Para agregar un nuevo módulo:
1. Crear en `shared/` (si es cross-cutting) o `api/` (si es API-only)
2. Escribir tests en `tests/test_<module>.py`
3. Conectar al pipeline en `api/adapters/valinor_adapter.py`
4. Si inyecta contexto a los agentes: hacerlo en `adaptive_context_builder.py`

### Para agregar un nuevo endpoint:
1. Agregar route en `api/routes/` o en `api/main.py` si es top-level
2. Documentar en `docs/API_REFERENCE.md`
3. Tests en `tests/test_<area>_endpoints.py`

### Para agregar análisis al Quality Pipeline:
El orden del pipeline es:
```
DataQualityGate → CurrencyGuard → SegmentationEngine → AnomalyDetector → SentinelPatterns → AlertEngine
```
Insertar antes de AlertEngine salvo que sea un gate bloqueante (va antes de DQ).

---

## 7. Reglas heredadas del proyecto

- **NUNCA almacenar datos de clientes** — solo metadata y resultados agregados
- **El código v0 en `core/valinor/` es intocable** — siempre wrapper, nunca rewrite
- **SSH tunneling obligatorio** — no conexiones directas a DBs de clientes
- **Type safety**: Pydantic en backend, TypeScript en frontend
- **Tests antes de merge** — `pytest tests/ -q` debe pasar al 100%

---

## 8. Test suite — criterio de calidad

La suite llegó a 2481 tests con algo de redundancia. Al tocar cualquier módulo:

1. Correr `/simplify` sobre los test files del módulo
2. Consolidar casos similares con `@pytest.mark.parametrize`
3. Eliminar tests que solo verifican que Python no tira excepción
4. Mantener: integration tests, contract tests (shapes de respuesta), edge cases reales

---

## 9. Qué falta (Phase 5)

- [ ] **Cloudflare Workers** — deploy de la API edge
- [ ] **GitHub Actions workflows** — análisis como jobs asíncronos en CI
- [ ] **Monitoring** — Prometheus + Grafana en producción
- [ ] **Supabase** — migrar de PostgreSQL local a Supabase para metadata

Ver `CLAUDE.md` para contexto completo de arquitectura y decisiones de diseño.

---

## 10. Commits de referencia

| Commit | Descripción |
|---|---|
| `f25b0d96` | First Commit — estructura base |
| `3a1a6642` | Client Memory Layer + Auto-Refinement Engine (Módulos 1–5) |
| `7f094cfd` | Data Quality Gate — 8+1 checks institucionales |
| `d3c26194` | PDF export, email digest, alerts, segmentation, wizard |
| `587ab915` | SSE streaming, sentinel fraud patterns, anomaly detector |
| `44fdcea6` | Test suite 2439 tests |
| `2b884af5` | Test suite 2481 tests (estado actual) |

---

*Última actualización: Marzo 2026 — Delta 4C*
