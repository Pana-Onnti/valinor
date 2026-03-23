# Sprint: Bugs + Security (VAL-68)

**Prioridad**: Primero. Desbloquea onboarding de clientes reales.
**Esfuerzo estimado**: 5 días
**Issues**: 13 (VAL-69 a VAL-81)

## P0 — Crashers (Day 1)

- **VAL-69** (S): `LLMConfig.from_env()` referencia `console_config` inexistente → crash. Fix: agregar campo o renombrar a `cli_config`.
- **VAL-71** (M): Race condition en refinement background save. `asyncio.create_task` muta el mismo profile que el pipeline ya guardó. Fix: copiar profile antes del background save. También: `TokenTracker.reset()` al inicio de cada run.

## P1 — Security (Day 1-2, paralelo con P0)

- **VAL-77** (M): 3 sub-issues:
  - Webhook secret hardcoded `"valinor_webhook_v1"` → env var
  - Passwords en Redis sin cifrar → redactar connection_config antes de serializar
  - `_adapter_cache` sin límite → `functools.lru_cache` o bounded dict
- **VAL-74** (M): 3 sub-issues:
  - Borrar task duplicada `run_analysis` (legacy, línea 106 de tasks.py)
  - `redis.keys("job:*")` → `scan_iter()` (O(N) bloquea Redis)
  - Separar colas: `analysis` vs `maintenance`

## P2 — Correctness (Day 2-3, paralelo)

- **VAL-70** (S): Model IDs divergen: base.py usa 2024, cli_provider usa 2026. Centralizar en `MODEL_REGISTRY`.
- **VAL-79** (S): Pricing duplicado entre token_tracker y anthropic_provider → `shared/llm/pricing.py`.
- **VAL-76** (M): Pydantic schemas existen en `agent_outputs.py` pero no se usan. Wiring: `model_validate()` post-agente en adapter.
- **VAL-72** (L): DQ Gate hardcodea tablas ERP. Refactorizar 8 checks para usar entity_map dinámico.

## P3 — Cleanup (Day 3-4, paralelo)

- **VAL-78** (S): Dead code: `run_analysis` legacy, `web/index.html`, zustand dep, tools huérfanas.
- **VAL-81** (M): 135 `sys.path.insert` → `pip install -e .` + PYTHONPATH en Docker.
- **VAL-80** (L): ClientProfile god object (22+ campos) → sub-objetos tipados.
- **VAL-73** (L): Frontend: React Query real, borrar index.html, tests básicos. Puede diferirse.
- **VAL-75** (L): OpenTelemetry tracing. Puede diferirse (observabilidad ya existe con Prometheus/Loki/Grafana).

## Lanes de paralelización

```
Agent A (core):     VAL-69 → VAL-71 → VAL-70 → VAL-79
Agent B (security): VAL-77 → VAL-74
Agent C (pipeline): VAL-72 → VAL-76
Agent D (cleanup):  VAL-78 → VAL-81 → VAL-80
```
