# 04 - API Layer: Investigacion Exhaustiva

**Fecha:** 2026-03-22
**Scope:** `/api/` completo — main.py, routers/, routes/, adapters/, middleware/, refinement/, webhooks.py, pdf_generator.py, email_digest.py
**Lineas de codigo analizadas:** ~2,740 (main.py) + ~1,200 (modulos satelite) = ~3,940 LOC Python

---

## 1. Resumen Ejecutivo

La API de Valinor SaaS es una aplicacion **FastAPI v2.0.0** monolitica que expone ~50 endpoints REST, 1 SSE stream, y 1 WebSocket. Orquesta un pipeline multi-agente de analisis de BI sobre bases de datos empresariales (Odoo, iDempiere, SAP B1, genericas). La arquitectura sigue un patron **adapter/wrapper** sobre el core CLI original de Valinor v0, con Redis como state store para jobs y PostgreSQL (asyncpg) para perfiles de clientes.

**Stack critico:** FastAPI + Uvicorn + Redis + asyncpg + structlog + Prometheus + Sentry + slowapi (rate limiting) + ReportLab (PDF) + SMTP (email).

---

## 2. Endpoints Completos

### 2.1 Sistema y Observabilidad

| Metodo | Ruta | Rate Limit | Descripcion |
|--------|------|------------|-------------|
| GET | `/health` | - | Health check: Redis + storage + uptime + version |
| GET | `/api/version` | - | Version API, DBs soportadas, costo por analisis |
| GET | `/api/system/status` | - | Estado servicios, paquetes instalados, feature flags, checks DQ |
| GET | `/api/system/metrics` | - | Metricas operacionales: jobs por estado, success rate, costo estimado, avg DQ |
| GET | `/metrics` | - | Prometheus text exposition (excluido de OpenAPI schema) |
| GET | `/api/cache/stats` | - | Estadisticas del cache in-memory de resultados |
| GET | `/sentry-debug` | - | Trigger test error para Sentry (solo non-prod, excluido de schema) |

### 2.2 Analisis y Jobs

| Metodo | Ruta | Rate Limit | Descripcion |
|--------|------|------------|-------------|
| POST | `/api/analyze` | **10/min** | Inicia analisis — devuelve job_id. Limite: 25/mes por cliente, 2 concurrentes por cliente |
| GET | `/api/jobs/{job_id}/status` | - | Estado del job (pending/running/completed/failed/cancelled) |
| GET | `/api/jobs/{job_id}/results` | - | Resultados completos (con cache in-memory 5min TTL) |
| GET | `/api/jobs/{job_id}/stream` | - | **SSE** streaming de progreso — polling Redis cada 2s, max 30min |
| WS | `/api/jobs/{job_id}/ws` | - | **WebSocket** para progreso en tiempo real |
| GET | `/api/jobs` | - | Listar jobs con paginacion, filtro por status/client, sort configurable |
| POST | `/api/jobs/{job_id}/cancel` | - | Cancelar job pending/running |
| POST | `/api/jobs/{job_id}/retry` | - | Reintentar job failed/cancelled con mismos parametros |
| DELETE | `/api/jobs/cleanup` | - | Eliminar jobs terminados mas viejos que N dias |

### 2.3 Descargas y Reportes

| Metodo | Ruta | Rate Limit | Descripcion |
|--------|------|------------|-------------|
| GET | `/api/jobs/{job_id}/pdf` | **30/min** | PDF branded con BrandedPDFGenerator (ReportLab) |
| GET | `/api/jobs/{job_id}/export/pdf` | **10/min** | Exportar PDF via shared.pdf_generator |
| GET | `/api/jobs/{job_id}/download/{filename}` | - | Descarga archivos (whitelist: 5 archivos permitidos) |
| GET | `/api/jobs/{job_id}/quality` | - | Reporte Data Quality Gate del job |
| GET | `/api/jobs/{job_id}/digest` | - | Preview HTML del email digest |
| POST | `/api/jobs/{job_id}/send-digest` | - | Enviar email digest via SMTP |

### 2.4 Clientes y Perfiles

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/clients` | Listar clientes con perfiles |
| GET | `/api/clients/summary` | Dashboard operador: total clientes, criticals, avg DQ, runs totales |
| GET | `/api/clients/comparison` | Comparar DQ scores y tendencias entre clientes |
| GET | `/api/clients/{name}/profile` | Perfil completo del cliente |
| GET | `/api/clients/{name}/profile/export` | Exportar perfil como JSON descargable |
| POST | `/api/clients/{name}/profile/import` | Importar/sobreescribir perfil desde JSON |
| DELETE | `/api/clients/{name}/profile` | Reset (borrar) perfil de cliente |
| PUT | `/api/clients/{name}/profile/false-positive` | Marcar finding como falso positivo |
| GET | `/api/clients/{name}/refinement` | Configuracion de refinamiento actual |
| PATCH | `/api/clients/{name}/refinement` | Merge parcial de refinamiento |
| GET | `/api/clients/{name}/findings` | Findings activos con filtro por severidad |
| GET | `/api/clients/{name}/findings/{id}` | Detalle de un finding especifico |
| GET | `/api/clients/{name}/costs` | Resumen de costos ($8/run default) |
| GET | `/api/clients/{name}/stats` | Estadisticas: run_count, tendencias, KPIs, focus tables |
| GET | `/api/clients/{name}/analytics` | Analiticas profundas: success rate, velocity, runs por mes |
| GET | `/api/clients/{name}/kpis` | Historial de KPIs baseline |
| GET | `/api/clients/{name}/dq-history` | Historial de scores DQ con tendencia |
| GET | `/api/clients/{name}/segmentation` | Ultima segmentacion de clientes (RFM) |

### 2.5 Alertas

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/clients/{name}/alerts` | Thresholds + ultimos triggers |
| POST | `/api/clients/{name}/alerts` | Agregar threshold (label/metric/operator/value) |
| DELETE | `/api/clients/{name}/alerts/{label}` | Eliminar threshold por label |
| GET | `/api/clients/{name}/alerts/thresholds` | Listar thresholds por metrica |
| POST | `/api/clients/{name}/alerts/thresholds` | Upsert threshold con 5 tipos de condicion |
| DELETE | `/api/clients/{name}/alerts/thresholds/{metric}` | Eliminar threshold por metrica |
| GET | `/api/clients/{name}/alerts/triggered` | Alertas disparadas del ultimo run |

### 2.6 Webhooks

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | `/api/clients/{name}/webhooks` | Registrar webhook URL (max 5 por cliente) |
| GET | `/api/clients/{name}/webhooks` | Listar webhooks registrados |
| DELETE | `/api/clients/{name}/webhooks` | Eliminar webhook por URL |

### 2.7 Audit Log

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | `/api/audit` | Log evento de auditoria (capped list 1000 en Redis) |
| GET | `/api/audit` | Leer eventos recientes con filtro por event_type |

### 2.8 Onboarding (router `/api/onboarding`)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | `/api/onboarding/test-connection` | Test conexion DB + auto-deteccion ERP (Odoo/iDempiere/SAP B1) |
| POST | `/api/onboarding/ssh-test` | Test SSH tunnel + DB con zero-trust validation |
| GET | `/api/onboarding/supported-databases` | Lista DBs soportadas (PostgreSQL, MySQL, SQL Server, Oracle) |
| POST | `/api/onboarding/estimate-cost` | Estimacion de costo ($5-$15 range) y duracion |
| POST | `/api/onboarding/validate-period` | Validar formato de periodo (Q1-2025, H1-2025, 2025, 2025-01) |

### 2.9 NL Query (router `/api/v1`)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| POST | `/api/v1/nl-query` | Natural Language -> SQL via VannaAdapter. Cache per-tenant. Ejecucion opcional |

### 2.10 Quality (router `/api/quality`)

| Metodo | Ruta | Descripcion |
|--------|------|-------------|
| GET | `/api/quality/schema/{client_name}` | Schema integrity check (placeholder — requiere conexion activa) |
| GET | `/api/quality/methodology` | Documentacion de metodologia DQ (Renaissance, Bloomberg, ECB, Big 4) |

---

## 3. Middleware Stack

El orden de aplicacion de middleware (bottom-up en Starlette, el ultimo registrado ejecuta primero):

| # | Middleware | Archivo | Funcion |
|---|-----------|---------|---------|
| 1 | **PrometheusMiddleware** | `api/metrics.py` | Conteo HTTP requests + histograma de duracion. Excluye `/metrics`, `/health`, `/docs`, `/redoc`, `/openapi.json` |
| 2 | **RequestIDMiddleware** | `api/main.py` | Genera/propaga `X-Request-ID` (UUID corto 8 chars), bind a structlog contextvars |
| 3 | **SecurityHeadersMiddleware** | `api/main.py` | Inyecta headers de seguridad: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()` |
| 4 | **CORSMiddleware** | FastAPI built-in | Origins: `localhost:3000`, `localhost:8080`, `valinor-saas.vercel.app` + env `CORS_ORIGINS`. All methods, all headers, credentials enabled |

### Global Exception Handlers

| Handler | Codigo | Comportamiento |
|---------|--------|----------------|
| `not_found_handler` | 404 | JSON con `error`, `path`, `request_id` |
| `global_exception_handler` | 500 | Log con exc_info, JSON generico con `request_id` |
| `validation_exception_handler` | 422 | Pydantic errors formateados como `{field, message, type}[]` |

---

## 4. Autenticacion

**Estado actual: NO HAY AUTENTICACION.**

No existe ningun mecanismo de autenticacion implementado:
- No hay middleware de auth (JWT, API key, OAuth)
- No hay dependency de FastAPI para verificar tokens
- No hay header `Authorization` requerido en ningun endpoint
- Los endpoints de cliente (`/api/clients/{name}/...`) no verifican ownership
- El endpoint `/api/analyze` acepta conexiones DB de cualquier origen
- El endpoint `/api/clients/{name}/profile/import` permite sobreescribir cualquier perfil

**Mitigaciones existentes parciales:**
- CORS limita origenes del browser
- Rate limiting via slowapi (`10/min` en analyze, `30/min` en PDF)
- Validacion de input en `client_name` (regex alfanumerico)
- Zero-trust SSH validation (bloquea rangos privados/loopback para prevenir SSRF)
- Sentry filtra headers sensibles (`Authorization`, `X-API-Key`, `Cookie`) antes de enviar
- Security headers (nosniff, DENY, XSS protection)
- Limite mensual de 25 analisis por cliente (Redis counter)
- Limite de 2 jobs concurrentes por cliente

---

## 5. Rate Limiting

Implementado con **slowapi** (Limiter basado en IP via `get_remote_address`):

| Endpoint | Limite |
|----------|--------|
| `POST /api/analyze` | 10/min |
| `GET /api/jobs/{id}/export/pdf` | 10/min |
| `GET /api/jobs/{id}/pdf` | 30/min |

**Limites de negocio adicionales (Redis-backed):**
- 25 analisis/mes por `client_name` (key con TTL 33 dias)
- 2 jobs concurrentes por `client_name` (scan de keys activos)

---

## 6. Adaptadores (`api/adapters/`)

### 6.1 ValinorAdapter (`valinor_adapter.py`)

Wrapper central sobre el core CLI de Valinor v0. Responsabilidades:

- **Monkey-patch del SDK Claude** antes de importar core (critical path)
- Orquestacion del pipeline completo: SSH Tunnel -> Cartographer -> DQ Gate -> QueryBuilder -> Analysis Agents -> Narrators -> Delivery
- Integracion con **ClientProfile** (memoria persistente entre runs)
- **Auto-refinement**: PromptTuner, FocusRanker, QueryEvolver, RefinementAgent
- **IndustryDetector**: deteccion automatica de industria
- **SegmentationEngine**: segmentacion RFM de clientes
- **CurrencyGuard**: prevencion de agregaciones multi-moneda silenciosas
- **DataQualityGate**: 9 checks pre-analisis
- **ProvenanceRegistry**: trazabilidad de datos
- Webhooks post-run via `WebhookDispatcher`
- Metricas Prometheus (JOBS_TOTAL, ACTIVE_JOBS, ANALYSIS_COST_USD, DQ_CHECKS_TOTAL)

### 6.2 Excepciones (`exceptions.py`)

Jerarquia de errores tipados:
- `ValinorError` (base)
  - `SSHConnectionError`
  - `DatabaseConnectionError`
  - `PipelineTimeoutError`
  - `DQGateHaltError` (con `dq_score` y `gate_decision`)

---

## 7. Refinement Engine (`api/refinement/`)

Sistema de auto-mejora entre runs de analisis:

| Modulo | Clase | Funcion |
|--------|-------|---------|
| `refinement_agent.py` | `RefinementAgent` | Post-run analyzer LLM-powered (Haiku). Genera `ClientRefinement`: table_weights, query_hints, focus_areas, suppress_ids. Fallback a heuristicas sin LLM |
| `focus_ranker.py` | `FocusRanker` | Re-ordena entity_map por peso historico de señal. Tablas con mas findings -> mas queries |
| `prompt_tuner.py` | `PromptTuner` | Genera bloque de contexto adaptativo para prompts de agentes. Zero LLM calls. Inyecta industria, moneda, findings persistentes, hints validados |
| `query_evolver.py` | `QueryEvolver` | Trackea queries vacias entre runs. Identifica tablas de alto valor. Persiste contadores en `profile.metadata` |

---

## 8. Webhooks (`api/webhooks.py`)

- **Eventos:** `job.completed`, `job.failed`
- **Retry:** 3 intentos con backoff [1s, 5s, 15s]
- **Firma:** HMAC-SHA256 en header `X-Valinor-Signature` (secret hardcoded: `valinor_webhook_v1`)
- **Headers custom:** `X-Valinor-Event`, `User-Agent: Valinor-Webhooks/1.0`
- **Timeout:** 10s por intento
- **Payload summary:** total_findings, critical_count, high_count, dq_score, dq_label, period, run_delta, triggered_alerts

Registro de webhooks via endpoints `/api/clients/{name}/webhooks` (max 5 por cliente).

---

## 9. PDF Generator (`api/pdf_generator.py`)

**BrandedPDFGenerator** — ReportLab-based, ~600 LOC:

- **Formato:** A4 con margenes 2.2cm
- **Brand:** Colores corporativos Valinor (violet #7C3AED, dark #08090F)
- **Secciones:**
  1. Cover header (cliente + fecha + brand)
  2. Stats bar (criticos/altos/medios/nuevos/resueltos)
  3. Data Quality section (score bar visual, checks table, warnings)
  4. Audit waterfall table (snapshot BD, queries ejecutadas, calidad, advertencias)
  5. Report body (markdown -> ReportLab flowables con deteccion de severidad)
  6. Triggered alerts section
  7. Provenance footer (trazabilidad de datos, REPEATABLE READ)
  8. Page header/footer en cada pagina

- **DQ Score visualization:** Progress bar coloreado por banda (green >= 85, amber >= 65, orange >= 45, red < 45)
- **Confidence badges:** `[CONFIRMED]`, `[PROVISIONAL]`, `[UNVERIFIED]`, `[BLOCKED]` despues de cada h3

---

## 10. Email Digest (`api/email_digest.py`)

- **HTML responsive** para clientes email (table-based layout, 600px width)
- **Secciones:** Header branded, headline contextual por severidad, stats row, DQ box coloreado, alertas disparadas, top 5 findings, KPIs con tendencia, sugerencia de proximo analisis, CTA, footer
- **Envio:** SMTP via env vars (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`)
- **Decision de headline:** Criticos -> rojo urgente, Altos -> naranja, Resueltos -> verde, Default -> violeta
- **Proximo analisis sugerido:** >= 3 criticos -> "URGENTE 24h", >= 1 critico -> "7 dias", 0 criticos -> "30 dias rutina"

---

## 11. Logging y Observabilidad

### structlog (`api/logging_config.py`)
- JSON output en containers (non-TTY), colored dev output en TTY
- Contextvars para request_id propagation
- Noisy libs silenciados: `uvicorn.access`, `httpx`, `asyncio`
- Log level configurable via env `LOG_LEVEL`

### Prometheus (`api/metrics.py`)
- **Counters:** `valinor_jobs_total` (by status), `valinor_analysis_cost_usd_total`, `valinor_dq_checks_total` (by check_name/result), `valinor_http_requests_total` (by method/path/status_code)
- **Gauges:** `valinor_active_jobs`, `valinor_clients_total`
- **Histogram:** `valinor_http_request_duration_seconds` (buckets 10ms-10s)

### Sentry
- DSN via env `SENTRY_DSN`
- Traces sample rate configurable (`SENTRY_TRACES_SAMPLE_RATE`, default 0.1)
- `before_send` hook filtra headers sensibles

### Audit Log
- Redis list capped a 1000 entries
- Eventos: `analysis_started` (con job_id, client_name, timestamp)

---

## 12. Fortalezas

1. **Pipeline end-to-end completo:** Desde onboarding (test conexion, deteccion ERP) hasta delivery (PDF branded, email digest, webhooks). Pocas plataformas SaaS tienen un pipeline tan integrado en esta etapa.

2. **Data Quality Gate institucional:** 9 checks inspirados en Renaissance/Bloomberg/ECB/Big4. Score visual en PDF, provenance footer, REPEATABLE READ isolation. Esto es diferenciador real.

3. **Auto-refinement engine:** El sistema aprende entre runs (FocusRanker, QueryEvolver, PromptTuner, RefinementAgent). Cada analisis sucesivo es mas preciso. Esto es raro en el mercado.

4. **Observabilidad profunda:** Prometheus metrics + structlog JSON + Sentry + request ID tracing + audit log. Stack de observabilidad maduro para una startup.

5. **Security headers y Zero-Trust SSH:** Headers de seguridad correctos, validacion SSRF anti-rangos-privados en SSH, CORS restrictivo, Sentry header filtering.

6. **Operaciones de lifecycle completas:** Cancel, retry, cleanup de jobs. Limites por cliente (25/mes, 2 concurrentes). Cache de resultados con TTL.

7. **Multi-ERP auto-detection:** Odoo, iDempiere, SAP B1, genericos. Deteccion de rango de fechas y capacidades por tipo de ERP.

8. **Celery-ready:** Dispatch condicional a Celery (`CELERY_ENABLED`), fallback a BackgroundTasks. Preparado para escalar workers.

9. **PDF y Email de calidad profesional:** Generacion de reportes con brand consistente, DQ visualization, alerts section. Competitivo con herramientas enterprise.

---

## 13. Debilidades

### Criticas

1. **ZERO autenticacion/autorizacion.** Cualquier request puede acceder a cualquier cliente, perfil, job. Un `DELETE /api/clients/{name}/profile` sin auth es un vector de ataque destructivo. Este es el gap mas critico de toda la capa API.

2. **Webhook secret hardcoded.** `WEBHOOK_SECRET = "valinor_webhook_v1"` en codigo fuente. Deberia ser per-client, almacenado en el perfil, y rotable.

3. **Passwords en Redis.** `request_data` se guarda como JSON en Redis hash (`job:{id}`) con los datos completos del request, incluyendo la password de DB. Aunque hay un `safe_request` sin passwords para retry, el `request` original con password se almacena en la misma key.

4. **SQL injection potencial en onboarding.** `_detect_date_range()` concatena nombres de tabla y columna directamente en SQL via f-string: `f"SELECT MIN({col})::date, MAX({col})::date FROM {table}"`. Los valores vienen de `inspector.get_table_names()` (relativamente seguro) pero el patron es peligroso.

### Altas

5. **Archivo main.py monolitico de 2,740 lineas.** Todos los endpoints estan en un solo archivo. Dificulta mantenimiento, testing aislado, y code review. Los endpoints de clientes (~800 LOC), jobs (~400 LOC), y alerts (~200 LOC) deberian ser routers separados.

6. **`sys.path.insert(0, ...)` repetido ~20 veces.** Casi cada endpoint de clientes hace `import sys, os; sys.path.insert(0, ...)`. Indica un problema de estructura de proyecto (el modulo `shared` no esta instalado como package).

7. **Scan de Redis O(N) para listar jobs.** `list_jobs` y `start_analysis` (para verificar concurrencia) hacen `scan_iter("job:*")` sobre TODAS las keys. Con miles de jobs, esto degrada performance. Deberia usar Redis sorted sets o indices.

8. **Dos endpoints de PDF con logica duplicada.** `/api/jobs/{id}/pdf` y `/api/jobs/{id}/export/pdf` hacen lo mismo con implementaciones diferentes y distintos rate limits.

9. **In-memory results cache sin bound.** `_results_cache` crece indefinidamente (solo eviction por TTL cuando se consulta `/cache/stats`). No hay LRU ni max-size.

### Medias

10. **Endpoints de alertas duplicados.** Hay dos conjuntos de CRUD para alerts: `/api/clients/{name}/alerts` (by label) y `/api/clients/{name}/alerts/thresholds` (by metric). API confusa.

11. **No hay versionado de API consistente.** NL Query usa `/api/v1/`, el resto usa `/api/`. Migraciones futuras seran dolorosas.

12. **SSE stream no usa Redis Pub/Sub.** El stream de progreso hace polling a Redis cada 2 segundos. Con muchos clientes conectados, esto genera carga innecesaria. Redis Pub/Sub o Streams seria mas eficiente.

13. **Endpoint `/api/quality/schema/{client_name}` es placeholder.** Solo retorna un mensaje estatico, no ejecuta ningun check real.

14. **Email CTA apunta a localhost.** `http://localhost:3000` hardcoded en el HTML del digest. Deberia ser configurable via env var.

---

## 14. Recomendaciones 2026

### P0 — Antes de ir a produccion

| # | Accion | Esfuerzo |
|---|--------|----------|
| 1 | **Implementar autenticacion.** JWT via Supabase Auth o API keys con middleware FastAPI `Depends(verify_token)`. Agregar `tenant_id` al token y verificar ownership en cada endpoint de cliente. | 3-5 dias |
| 2 | **Mover webhook secret a env/config per-client.** Generar secret unico al registrar webhook, almacenar en perfil, exponer endpoint de rotacion. | 1 dia |
| 3 | **Eliminar password de DB del Redis hash.** El campo `request` en `job:{id}` contiene credenciales. Solo guardar `request_data` (sanitizado). | 0.5 dia |
| 4 | **Parametrizar queries de onboarding.** Usar SQLAlchemy `text()` con binds en vez de f-strings para nombres de tabla/columna (o al menos whitelist estricta). | 0.5 dia |

### P1 — Proximos 30 dias

| # | Accion | Esfuerzo |
|---|--------|----------|
| 5 | **Refactorizar main.py en routers.** Separar en: `routers/jobs.py`, `routers/clients.py`, `routers/alerts.py`, `routers/reports.py`, `routers/system.py`. Eliminar `sys.path.insert` repetidos instalando `shared` como package editable. | 2-3 dias |
| 6 | **Consolidar endpoints de alertas.** Unificar los dos CRUDs (by label y by metric) en uno solo coherente. | 1 dia |
| 7 | **Eliminar endpoint PDF duplicado.** Mantener solo `/api/jobs/{id}/pdf`, eliminar `/api/jobs/{id}/export/pdf`. | 0.5 dia |
| 8 | **Bound el results cache.** Usar `cachetools.LRUCache` o similar con max_size (e.g., 100 entries). | 0.5 dia |
| 9 | **Migrar SSE a Redis Pub/Sub.** Crear channel `job:{id}:progress`, publicar desde el worker, suscribir desde SSE handler. Elimina polling. | 1-2 dias |
| 10 | **Versionado de API.** Mover todos los endpoints a `/api/v1/` con router prefix. Preparar estructura para `/api/v2/`. | 1 dia |

### P2 — Q2 2026

| # | Accion | Esfuerzo |
|---|--------|----------|
| 11 | **Indice Redis para jobs.** Usar sorted set `jobs:by_created` con score=timestamp para pagination eficiente sin scan. | 1 dia |
| 12 | **Email CTA configurable.** Extraer `BASE_URL` de env y usarla en digest HTML y PDF footer. | 0.5 dia |
| 13 | **Implementar `/api/quality/schema/{client_name}` real.** Conectar con DataQualityGate para checks on-demand. | 2-3 dias |
| 14 | **OpenAPI schema mejorado.** Agregar `tags` consistentes, `response_model` a todos los endpoints, `summary` y `description` completos. Varios endpoints retornan `dict` sin modelo tipado. | 2 dias |
| 15 | **Webhook delivery log.** Persistir historial de entregas (success/fail/retries) en perfil de cliente para debugging. | 1 dia |

---

## 15. Mapa de Archivos

```
api/
  __init__.py                    # v1.0.0
  main.py                        # ~2,740 LOC — App principal, ~50 endpoints
  logging_config.py              # structlog JSON/pretty config
  metrics.py                     # Prometheus counters/gauges/histogram + middleware
  webhooks.py                    # fire_job_completion_webhook + HMAC signing + retry
  pdf_generator.py               # BrandedPDFGenerator (ReportLab, A4, DQ visualization)
  email_digest.py                # build_digest_html + send_digest (SMTP)
  adapters/
    valinor_adapter.py           # ValinorAdapter — wrapper sobre core CLI v0
    exceptions.py                # ValinorError hierarchy (SSH, DB, Timeout, DQHalt)
  routers/
    __init__.py
    nl_query.py                  # POST /api/v1/nl-query — NL->SQL via VannaAdapter
  routes/
    __init__.py
    onboarding.py                # test-connection, ssh-test, supported-databases, estimate-cost, validate-period
    quality.py                   # schema check (placeholder), methodology docs
  refinement/
    __init__.py
    refinement_agent.py          # RefinementAgent — LLM post-run analyzer (Haiku)
    focus_ranker.py              # FocusRanker — re-rank entity_map by signal weight
    prompt_tuner.py              # PromptTuner — adaptive context block for agent prompts
    query_evolver.py             # QueryEvolver — track empty queries, high-value tables
```
