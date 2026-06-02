# 06 — Worker System (Celery + Redis)

## Resumen

El sistema de workers de Valinor SaaS utiliza **Celery 5.x** con **Redis** como broker y backend de resultados. Ejecuta análisis financieros pesados en segundo plano, desacoplando la API FastAPI del procesamiento largo (hasta 1 hora). El diseño incluye progress tracking en Redis, webhooks post-ejecución, limpieza automática de jobs, y un health-check periódico. Los directorios `worker/tasks/` y `worker/processors/` existen pero están **vacíos** — toda la lógica vive concentrada en un solo archivo `tasks.py` (574 líneas).

---

## Arquitectura Celery

### Componentes

| Componente | Archivo | Rol |
|---|---|---|
| Celery App Factory | `worker/celery_app.py` | Crea la instancia `celery_app` con configuración desde env vars |
| Tasks monolíticas | `worker/tasks.py` | 6 tasks + helpers async + ProgressUpdater |
| Dockerfile | `Dockerfile.worker` | Python 3.11-slim, non-root user `valinor` |
| Docker Compose | `docker-compose.yml` (service `worker`) | `celery -A worker.celery_app worker -Q valinor -c 2`, mem_limit 512m |

### Flujo de ejecución

```
API (FastAPI)
  │
  ├── CELERY_ENABLED=true → run_analysis_task.apply_async(queue="valinor")
  │                           ↓
  │                       Celery Worker (2 concurrency)
  │                           ↓
  │                       _run_analysis_task_async()
  │                           ↓
  │                       ValinorAdapter.run_analysis()
  │                           ↓
  │                       Pipeline completo (cartographer → queries → agents → narrate → deliver)
  │
  └── CELERY_ENABLED=false → FastAPI BackgroundTasks (fallback in-process)
```

Si el dispatch a Celery falla, el API degrada a `BackgroundTasks` de FastAPI como fallback (línea 584-590 de `api/main.py`).

### Configuración clave (`celery_app.py`)

| Parámetro | Valor | Nota |
|---|---|---|
| `broker` / `backend` | Redis (env `REDIS_URL`, default `redis://localhost:6380/0`) | Mismo Redis para broker y resultados |
| `task_serializer` | JSON | No pickle — seguro |
| `task_time_limit` | 3600s (1 hora) | Hard kill |
| `task_soft_time_limit` | 3300s (55 min) | Señal SoftTimeLimitExceeded |
| `worker_max_tasks_per_child` | 10 | Recicla procesos para evitar memory leaks |
| `worker_prefetch_multiplier` | 1 | Fair dispatch — no acumula tareas |
| `task_track_started` | True | Visibilidad de estado "STARTED" |

---

## Colas

| Cola | Routing | Consumidores |
|---|---|---|
| `valinor` | `worker.tasks.*` → `valinor` (routing en `celery_app.py`) | 1 worker con `-c 2` (2 procesos) |

Solo existe **una cola**. No hay separación por prioridad, tipo de tarea, ni tenant. Todas las tasks (análisis pesado, cleanup, health_check) compiten por los mismos 2 slots de concurrencia.

---

## Tasks

### Inventario completo

| Task | Nombre registrado | Tipo | Retry | Beat |
|---|---|---|---|---|
| `run_analysis` | `worker.tasks.run_analysis` | bind=True | No (manual) | No |
| `run_analysis_task` | `worker.tasks.run_analysis_task` | bind=True, max_retries=2, retry_backoff=True | Sí (Celery nativo) | No |
| `cleanup_job` | `worker.tasks.cleanup_job` | Simple | No | No (triggered por analysis) |
| `cleanup_expired_jobs` | `worker.tasks.cleanup_expired_jobs` | Simple | No | Cada 6 horas |
| `health_check` | `worker.tasks.health_check` | Simple | No | Cada 5 minutos |
| `monitor_jobs` | `worker.tasks.monitor_jobs` | Simple | No | Cada 10 minutos |

### `run_analysis` vs `run_analysis_task` — Duplicación

Existen **dos tasks de análisis** que hacen esencialmente lo mismo:

1. **`run_analysis`** (línea 105): usa `PipelineExecutor` con estrategias retry/fallback configurables via `request_data.options`. Sin retry nativo de Celery. Acepta un dict `request_data` monolítico.

2. **`run_analysis_task`** (línea 297): interfaz descompuesta (`job_id`, `client_name`, `connection_config`, `period`, `analysis_config`). Usa `self.retry(exc=exc)` nativo de Celery con `max_retries=2` y `retry_backoff=True`. Es la que realmente invoca `api/main.py`.

`run_analysis` parece ser la versión legacy. Solo `run_analysis_task` está wired en el endpoint principal.

### Patrón async en sync

Todas las tasks crean un `asyncio.new_event_loop()` ad-hoc porque Celery corre síncrono pero `ValinorAdapter` es async:

```python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
try:
    results = loop.run_until_complete(...)
finally:
    loop.close()
```

Este patrón se repite 4 veces (`run_analysis`, `run_analysis_task`, `_fire_webhooks_sync`, `health_check`).

### Beat Schedule (tareas periódicas)

| Tarea | Intervalo | Función |
|---|---|---|
| `cleanup-expired-jobs` | 6 horas | Escanea `job:*` en Redis, elimina jobs con `created_at` > 7 días |
| `health-check` | 5 minutos | Ping Redis + MetadataStorage health_check |
| `monitor-jobs` | 10 minutos | Detecta jobs "running" sin update por >2 horas, los marca failed |

**Nota**: El beat schedule se define en **dos sitios** — `celery_app.py` define `cleanup-expired-jobs`, y `tasks.py` hace `beat_schedule.update()` para agregar `health-check` y `monitor-jobs`. Esto funciona porque `include=["worker.tasks"]` fuerza la importación de `tasks.py`.

---

## Procesadores

Los directorios `worker/tasks/` y `worker/processors/` están **vacíos** (sin archivos .py). Toda la lógica de procesamiento se delega a:

- **`ValinorAdapter`** (`api/adapters/valinor_adapter.py`): Orquesta el pipeline completo (SSH tunnel → cartographer → query builder → analysis agents → narrator → delivery).
- **`PipelineExecutor`** (`api/adapters/valinor_adapter.py`): Wrapper con estrategias `run_with_retry` (backoff exponencial, filtra errores no-retryables) y `run_with_fallback` (degradación parcial si agentes no-críticos fallan).

El worker es un **thin dispatcher** — no contiene lógica de negocio propia.

---

## Retry / Error Handling

### Nivel Celery (task nativa)

`run_analysis_task` usa retry nativo:
- `max_retries=2` → hasta 3 intentos totales
- `retry_backoff=True` → backoff exponencial automático
- En excepción: `raise self.retry(exc=exc)` — Celery reencola

### Nivel PipelineExecutor (application-level)

`run_analysis` (legacy) delega a `PipelineExecutor`:

- **`run_with_retry`**: max_retries configurable, backoff `2^attempt` segundos, lista de errores no-retryables (auth, permisos, config inválida).
- **`run_with_fallback`**: si el error NO es de cartographer/connection, marca `partial_failure=True` y retorna resultados parciales.

### Manejo de estado en fallo

```
Exception capturada
  → Redis: hset job:{id} status=failed, error=str(exc), failed_at=timestamp
  → Webhook: _fire_webhooks_sync(status="failed")
  → Re-raise para Celery (permite retry nativo)
```

### Stale job detection

`monitor_jobs` (cada 10 min) busca jobs con `status=running` y `updated_at` > 2 horas atrás. Los marca como `failed` con error "Job timeout - marked as stale".

### Debilidades del error handling

- El `except:` desnudo en línea 195 y 535 (`pass`) suprime cualquier error silenciosamente.
- `_fire_webhooks_sync` atrapa toda excepción con un `logger.warning` — fallos de webhook son invisibles.
- No hay Dead Letter Queue ni alerting ante `MaxRetriesExceeded`.
- `cleanup_expired_jobs` usa `rc.keys("job:*")` — operación O(N) bloqueante en Redis.

---

## Monitoreo

### Actual

| Mecanismo | Frecuencia | Qué verifica |
|---|---|---|
| `health_check` task | 5 min | Redis ping + MetadataStorage health |
| `monitor_jobs` task | 10 min | Stale jobs (>2h sin update) |
| Docker logging | Continuo | `json-file`, max 50MB x 5 archivos |
| `task_track_started` | Por task | Celery registra estado STARTED |

### Ausente

- No hay **Flower** ni dashboard de Celery configurado en docker-compose (aunque Flower está instalado en venv del worktree).
- No hay **métricas Prometheus/StatsD** exportadas.
- No hay **alerting** (Sentry integration existe en deps pero no está wired en el worker).
- No hay **tracing distribuido** (OpenTelemetry).
- Los health checks no se exponen via HTTP — son tasks internas sin consumidor externo.

---

## Progress Tracking

`ProgressUpdater` escribe en Redis hash `job:{id}`:

```python
{
    "status": "running",
    "stage": "cartographer",    # etapa actual del pipeline
    "progress": 25,              # porcentaje
    "message": "Mapping database schema...",
    "updated_at": "2026-03-22T10:00:00"
}
```

El API puede consultar este hash para dar progress al frontend. Solo `run_analysis` (legacy) usa ProgressUpdater con callback; `run_analysis_task` (la activa) **no lo usa** — pierde granularidad de progreso.

---

## Almacenamiento de resultados

| Dato | Backend | TTL |
|---|---|---|
| Job metadata (hash) | Redis `job:{id}` | 24h initial, extendido a 7 días por cleanup_job |
| Resultados completos | Redis `job:{id}:results` | 24h initial, extendido a 7 días |
| Metadata persistente | Supabase `analysis_jobs` / local JSON fallback | 90 días (cleanup_old_metadata) |
| Archivos temporales | `/tmp/valinor_output/{id}` | Eliminados por cleanup_job a las 24h |

---

## Fortalezas

1. **Configuración de confiabilidad sólida**: `worker_max_tasks_per_child=10` previene memory leaks, `prefetch_multiplier=1` asegura fair scheduling, time limits separados (soft/hard).
2. **Fallback graceful**: Si Celery no está disponible, la API degrada a BackgroundTasks in-process.
3. **JSON-only serialization**: Sin pickle — elimina vector de deserialización arbitraria.
4. **Stale job detection**: `monitor_jobs` es un safety net útil contra jobs zombies.
5. **Separación de concerns**: El worker es un thin dispatcher sin lógica de negocio; toda la lógica vive en `ValinorAdapter`.
6. **Non-root container**: `Dockerfile.worker` crea usuario `valinor` con UID 1000.
7. **Limpieza automatizada**: Doble capa (per-job a las 24h + scan global cada 6h).
8. **Webhook notifications**: Notifica a clientes registrados tanto en éxito como en fallo.

---

## Debilidades

1. **Duplicación de tasks**: `run_analysis` y `run_analysis_task` hacen lo mismo con interfaces distintas. `run_analysis` es dead code — confuso.
2. **Cola única**: Un health_check o cleanup puede competir con un análisis pesado por los 2 slots de concurrencia.
3. **`redis.keys("job:*")`**: Usado en `cleanup_expired_jobs` y `monitor_jobs` — operación O(N) bloqueante. En producción con miles de jobs, bloquea Redis.
4. **Event loop ad-hoc**: `asyncio.new_event_loop()` se crea y destruye por cada task. Overhead de setup y riesgo de leaks si no se cierra bien.
5. **Directorios vacíos**: `worker/tasks/` y `worker/processors/` sugieren una modularización planeada pero nunca ejecutada.
6. **ProgressUpdater sin uso**: La task activa (`run_analysis_task`) no inyecta progress callback, perdiendo visibilidad de etapas intermedias.
7. **Inconsistencia de Redis URL**: `celery_app.py` usa default `redis://localhost:6380/0`, pero `tasks.py` usa `redis://localhost:6379`. En Docker no importa (env var override), pero en desarrollo local puede causar split-brain.
8. **Sin Dead Letter Queue**: Tasks que agotan retries desaparecen silenciosamente.
9. **Sin Sentry/alerting**: Errores de worker solo van a logs.
10. **512MB mem_limit**: Un análisis pesado con datasets grandes puede OOM-kill el worker.
11. **Beat schedule split**: Definido en dos archivos — propenso a conflictos.
12. **No hay tests para workers**: No se encontraron tests unitarios para tasks.py.

---

## Recomendaciones 2026

### Prioridad Alta

| # | Acción | Impacto |
|---|---|---|
| 1 | **Eliminar `run_analysis` legacy** — solo dejar `run_analysis_task` | Reducir confusión, eliminar dead code |
| 2 | **Reemplazar `redis.keys()` por `SCAN`** en `cleanup_expired_jobs` y `monitor_jobs` | Evitar bloqueo de Redis en producción |
| 3 | **Separar colas**: `valinor.analysis` (pesada), `valinor.maintenance` (cleanup, health) | Evitar que mantenimiento bloquee análisis |
| 4 | **Inyectar ProgressUpdater en `run_analysis_task`** | Recuperar visibilidad de progreso en frontend |
| 5 | **Unificar Redis URL default** entre `celery_app.py` y `tasks.py` | Evitar bugs en desarrollo local |

### Prioridad Media

| # | Acción | Impacto |
|---|---|---|
| 6 | **Agregar Sentry integration** al worker (ya está en deps) | Alerting proactivo en fallos |
| 7 | **Configurar Flower** como servicio en docker-compose | Dashboard visual de tasks/workers |
| 8 | **Implementar DLQ** con `task_reject_on_worker_lost=True` y callback `on_failure` | Visibilidad de tasks terminalmente fallidas |
| 9 | **Subir mem_limit a 1GB** o implementar streaming en el adapter | Evitar OOM en datasets grandes |
| 10 | **Modularizar en `worker/tasks/`**: `analysis.py`, `maintenance.py`, `monitoring.py` | Separación clara, testabilidad |

### Prioridad Baja

| # | Acción | Impacto |
|---|---|---|
| 11 | **Reemplazar event loop ad-hoc** por `asgiref.sync_to_async` o Celery async worker | Código más limpio, menos overhead |
| 12 | **Agregar métricas Prometheus** (task duration, queue depth, failure rate) | Observabilidad para SRE |
| 13 | **Consolidar beat_schedule** en un solo archivo (`celery_app.py` o `tasks.py`, no ambos) | Mantenibilidad |
| 14 | **Tests unitarios** para cada task (mocking Redis + ValinorAdapter) | Confianza en refactors |
| 15 | **Rate limiting por tenant** con `task_annotations` o custom routing | Fair resource allocation en multi-tenant |

---

## Archivos clave

| Archivo | Ruta absoluta |
|---|---|
| Celery app | `/home/nicolas/Documents/delta4/valinor-saas/worker/celery_app.py` |
| Tasks | `/home/nicolas/Documents/delta4/valinor-saas/worker/tasks.py` |
| Dockerfile | `/home/nicolas/Documents/delta4/valinor-saas/Dockerfile.worker` |
| Docker Compose | `/home/nicolas/Documents/delta4/valinor-saas/docker-compose.yml` (service `worker`, líneas 111-145) |
| ValinorAdapter | `/home/nicolas/Documents/delta4/valinor-saas/api/adapters/valinor_adapter.py` |
| MetadataStorage | `/home/nicolas/Documents/delta4/valinor-saas/shared/storage.py` |
| API dispatch | `/home/nicolas/Documents/delta4/valinor-saas/api/main.py` (líneas 552-596) |
