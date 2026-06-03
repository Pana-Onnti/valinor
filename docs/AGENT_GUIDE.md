# Valinor SaaS — Guía para el Próximo Agente

> Este documento describe el estado actual del proyecto, cómo está organizado, qué fue construido, y cómo continuar el desarrollo sin romper nada.

---

## 1. Estado Actual (Junio 2026)

> **El estado vivo y verificado del proyecto está en `docs/PROJECT_STATE.md`.** Este
> doc conserva el mapa de código y las firmas críticas, pero los contadores puntuales
> pueden quedar viejos — verificá siempre contra el código.

- **~3358 tests** (~3302 en `tests/` + 56 en `security/`)
- **Pipeline completo funcionando** en Docker local
- **Fases 1–7 cerradas.** Deployment ya NO es Cloudflare/GH-Actions: producción corre en **Railway** (API+Worker) + **Vercel** (frontend).
- **Branch de integración**: `develop`; producción: `master` (PR develop→master). **No existe rama `main`.**

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
│   ├── deps.py                  # limiter (slowapi per-tenant) + get_redis — rate limiting vive ACÁ, no en api/middleware/
│   ├── metrics.py               # PrometheusMiddleware + DQ metrics hook (set_dq_metrics_hook)
│   ├── tenant.py                # TenantMiddleware (X-Tenant-ID) + get_tenant_id
│   ├── auth.py                  # verify_api_key (env-gated VALINOR_API_KEY) + PyJWT helpers
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
│   ├── quality/data_quality_gate.py  # DataQualityGate (9 checks, fail-closed en crash — VAL-165)
│   ├── quality/                 # CurrencyGuard, AnomalyDetector, SentinelPatterns
│   └── tools/                   # analysis_tools (revenue_calc, aging_calc, pareto_analysis...)
│
├── web/                         # Next.js frontend
│   └── src/app/                 # App Router — pages: /, /reports, /quality/[jobId], /anomalies
│
├── tests/                       # ~88 archivos, ~3302 tests (+ security/ = 56)
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
3. Conectar al pipeline en `core/adapters/valinor_adapter.py`
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

## 9. Estado de deployment (actualizado)

Producción **ya está desplegada** y NO usa Cloudflare/Supabase:
- **Railway** — API + Worker + PostgreSQL + Redis (ver `docs/INFRASTRUCTURE.md`)
- **Vercel** — frontend Next.js
- **GitHub Actions** — CI (tests en `master`+`develop`) + deploy automático
- **Monitoring** — Prometheus + Grafana + Loki (docker-compose); Sentry en prod

La agenda de la nueva etapa y los issues abiertos verificados están en
`docs/PROJECT_STATE.md`. Ver `CLAUDE.md` para arquitectura y decisiones de diseño.

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
