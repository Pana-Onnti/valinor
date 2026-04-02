# 14. Arquitectura de Proveedores LLM

> Investigacion: 2026-03-22 | Branch: `develop` | Commit base: `afa3892f`

---

## Resumen

Valinor SaaS implementa una capa de abstraccion LLM en `shared/llm/` que permite switching transparente entre proveedores sin modificar el codigo de los agentes. La arquitectura sigue el principio de sustitucion de Liskov: todos los proveedores implementan `LLMProvider` (ABC), y un factory con decorator pattern (`MonitoredProvider`) agrega fallback, metricas y cost tracking de forma transversal.

Los 12 agentes del swarm (`analyst`, `hunter`, `sentinel`, `cartographer`, 4 narrators, `query_builder`, `profiler`, `fk_discovery`, `ontology_builder`) importan `claude_agent_sdk`, que es interceptado en runtime por un monkey patch (`shared/llm/monkey_patch.py`) que redirige todas las llamadas al sistema de providers. Este diseno permite zero-code-change switching.

Adicionalmente, Vanna AI (`core/valinor/nl/vanna_adapter.py`) usa la API de Anthropic directamente para NL-a-SQL, operando fuera de la capa de abstraccion.

---

## Proveedores Soportados

### 1. Anthropic API (`AnthropicProvider`)
- **Archivo**: `shared/llm/providers/anthropic_provider.py`
- **Autenticacion**: `ANTHROPIC_API_KEY` (SDK oficial `anthropic`)
- **Modelos**: Opus, Sonnet, Haiku
- **Mapping hardcoded**: `claude-3-opus-20240229`, `claude-3-5-sonnet-20241022`, `claude-3-haiku-20240307`
- **Features**: Streaming, retry con backoff exponencial en `RateLimitError`, tool calling, KV-cache
- **Costo**: ~$3-15/MTok input, ~$15-75/MTok output segun modelo
- **Latencia**: ~1.2s promedio
- **Reliability**: 99.9%

### 2. Claude CLI (`ClaudeCliProvider`)
- **Archivo**: `shared/llm/providers/cli_provider.py`
- **Autenticacion**: Sesion local de Claude Code (Plan Max) — sin API key
- **Dos modos**:
  - **Directo**: Subprocess al binario `claude --print --model <model>`
  - **Proxy**: HTTP via `claude_proxy.py` (port 8099) para contenedores Docker
- **Modelos**: `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5` (mapping actualizado)
- **Costo**: $0 (incluido en suscripcion Plan Max)
- **Limitacion**: ~30 req/min, latencia ~2.5s, sin token tracking real (usage = 0,0,0)
- **Auto-deteccion**: `initialize()` intenta CLI local primero, luego proxy via `host.docker.internal`

### 3. Mock (`MockProvider`)
- **Archivo**: `shared/llm/factory.py` (inline)
- **Uso**: Testing y CI/CD
- **Respuesta fija**: `"This is a mock response"`
- **Costo**: $0, latencia ~0.01s

---

## Switching Logic

### Jerarquia de Resolucion de Proveedor

```
LLM_FORCE_PROVIDER (override absoluto)
    |
    v
LLM_DYNAMIC_PROVIDER (switching en runtime via env)
    |
    v
LLM_PROVIDER (configuracion base, default: console_cli)
```

### Mecanismos de Switching

1. **Environment variables**: `LLM_PROVIDER=anthropic_api|console_cli|mock`
2. **Archivo JSON**: `LLMConfig.from_file("config.json")`
3. **Codigo**: `LLMConfig(provider_type=ProviderType.CONSOLE_CLI)`
4. **Runtime hot-switch**: `switch_provider("anthropic_api", api_key="...")`  (en `monkey_patch.py`)
5. **Feature flag sources**: ENV, file, Redis, API (enum definido, solo ENV implementado)

### Monkey Patch (Punto Critico)

El archivo `shared/llm/monkey_patch.py` es el puente entre el codigo legacy y el sistema nuevo:

- Se auto-ejecuta al importar (`apply_monkey_patch()` al final del modulo)
- Crea un modulo falso `claude_agent_sdk` en `sys.modules`
- Expone: `query`, `ClaudeAgentOptions`, `AssistantMessage`, `TextBlock`, `tool`, `create_sdk_mcp_server`
- El `query()` del monkey patch devuelve `AssistantMessage(content=[TextBlock(text=...)])` para mantener compatibilidad con los agentes que esperan ese formato

---

## Fallback Chain

```
Proveedor Primario (ej: anthropic_api)
    |--- Error: rate limit, timeout, auth failure, connection error
    v
Proveedor Fallback (configurable, default: mock)
    |--- Error: fallo tambien
    v
Exception propagada al caller
```

### Implementacion

- **Config**: `enable_fallback=True`, `fallback_provider=ProviderType.MOCK`
- **Triggers**: Matching por substring en el mensaje de error: `"rate limit"`, `"quota exceeded"`, `"authentication failed"`, `"timeout"`, `"connection error"`
- **Dos niveles de fallback**:
  1. **Factory-level** (`LLMProviderFactory.create`): Si `initialize()` falla, intenta crear el fallback
  2. **Query-level** (`MonitoredProvider.query`): Si una query falla, intenta con el fallback provider
- **Limitacion**: Solo 1 nivel de fallback (no hay cadena de 3+ providers)

### CLI Provider — Fallback Interno

El `ClaudeCliProvider` tiene su propio mini-fallback:
1. Intenta subprocess directo al binario `claude`
2. Si falla, intenta HTTP proxy en `host.docker.internal:8099`
3. Si ambos fallan, lanza `RuntimeError`

---

## KV-Cache

### Implementacion (VAL-31)

- **Archivo**: `shared/llm/providers/anthropic_provider.py` (lineas 39-43, 90-111)
- **Activacion**: Automatica cuando `ENABLE_TOKEN_TRACKING=true` (default)
- **Mecanismo**: System prompts se wrappean con `cache_control: {"type": "ephemeral"}`
- **Header**: `anthropic-beta: prompt-caching-2024-07-31`
- **Reduccion de costo**: ~90% en tokens de input repetidos (cache_read = $0.30/MTok vs input = $3.00/MTok para Sonnet)

### Token Tracking (VAL-31)

- **Archivo**: `shared/llm/token_tracker.py`
- **Patron**: Singleton thread-safe con `threading.Lock`
- **Metricas por agente**: input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, call_count, total_cost_usd, cache_hit_rate
- **Prometheus**: Counters opcionales (`valinor_analysis_tokens_total`, `valinor_analysis_cost_usd_total`) con labels `[agent, model, token_type]`
- **Pricing table**: Hardcoded para Sonnet, Opus, Haiku con precios 2025 incluyendo cache_write y cache_read rates

### Limitacion del KV-Cache

- Solo cachea system prompts (no user messages ni tool results)
- El `ClaudeCliProvider` no soporta KV-cache (usage siempre reporta 0)
- No hay cache de respuestas completas (semantic caching) — solo prompt caching de Anthropic

---

## Cost Optimization

### Estrategias Actuales

1. **Dual-provider**: CLI provider ($0) para desarrollo, API ($$$) para produccion
2. **KV-cache**: ~90% reduccion en system prompts repetidos (significativo para swarm de 12 agentes con prompts largos)
3. **Model tiering en base.py**:
   - Opus ($15/$75 MTok) — no usado por defecto
   - Sonnet ($3/$15 MTok) — default para todos los agentes
   - Haiku ($0.25/$1.25 MTok) — health checks
4. **Budget limits**: `CostTracker(budget_limit=100.0)` — exception si se excede
5. **Token tracking**: Visibilidad por agente para identificar outliers
6. **Cost-by-hour tracking**: Tendencias temporales en `CostTracker.costs_by_hour`

### Pricing Table (Hardcoded, 2025)

| Modelo | Input/MTok | Output/MTok | Cache Write/MTok | Cache Read/MTok |
|--------|-----------|------------|-----------------|----------------|
| Sonnet | $3.00 | $15.00 | $3.75 | $0.30 |
| Opus | $15.00 | $75.00 | $18.75 | $1.50 |
| Haiku | $0.25 | $1.25 | $0.30 | $0.03 |

---

## Monitoring

### MetricsCollector (`shared/llm/monitoring.py`)

- Requests/successes/failures por provider
- Latency: mean, min, max, p50, p95
- Failure breakdown por tipo de error
- Uptime tracking

### CostTracker (`shared/llm/monitoring.py`)

- Costo acumulado por provider
- Costo por hora (timeseries)
- Budget limit con exception automatica
- Export a JSON file

### MonitoredProvider (Decorator Pattern)

Envuelve cualquier provider con:
1. Pre-query: `record_request(provider_name)`
2. Post-query success: `record_success(provider_name, duration)` + `record_cost()`
3. Post-query failure: `record_failure(provider_name, error)` + fallback attempt

---

## Fortalezas

1. **Abstraccion limpia**: Interface ABC bien definida con LSP, factory pattern, y decorator para monitoring — facilita agregar proveedores nuevos
2. **Zero-code-change switching**: El monkey patch permite cambiar proveedor sin tocar ningun agente del swarm
3. **Dual-mode CLI provider**: Subprocess directo + proxy HTTP resuelve el problema Docker vs host
4. **KV-cache integrado**: Reduccion real de costos con metricas de cache hit rate por agente
5. **Token tracking granular**: Prometheus-ready, per-agent, con desglose cache read/write
6. **Budget guardrails**: Hard limit con exception para evitar sorpresas de costo
7. **Backward compatibility**: Adapter layer completo que emula `claude_agent_sdk` incluyendo `AssistantMessage`, `TextBlock`, `tool` decorator
8. **Costo $0 en desarrollo**: CLI provider usa la sesion activa de Claude Code (Plan Max)

---

## Debilidades

1. **Vendor lock-in**: Solo Anthropic implementado. `ModelType` enum define `GPT4` y `GPT4_TURBO` pero no hay `OpenAIProvider`. Vanna adapter usa Anthropic directamente, bypasseando la abstraccion
2. **Model mappings desactualizados**: `base.py` mapea a `claude-3-5-sonnet-20241022` y `claude-3-opus-20240229` (modelos 2024), mientras `cli_provider.py` usa `claude-opus-4-6` y `claude-sonnet-4-6` (modelos 2026). Inconsistencia que puede causar comportamiento diferente entre providers
3. **Fallback naive**: Matching por substring en mensajes de error es fragil. Un error `"connection timeout during rate limit check"` triggerea dos categorias. No hay circuit breaker pattern
4. **Sin semantic caching**: KV-cache solo aplica a system prompts. No hay cache de respuestas similares, que seria valioso para queries repetitivas del swarm
5. **Config inconsistencia**: `LLMConfig.from_env()` referencia `console_config` (linea 75) que no es un campo del dataclass (solo `anthropic_config` y `cli_config`). Bug latente que lanzaria error si se llama
6. **CLI provider sin token tracking**: Retorna `usage={0,0,0}`, haciendo invisible el consumo real de tokens cuando se usa en desarrollo
7. **Feature flags parciales**: Solo `ENV` esta implementado como source. Redis y API sources estan definidos como enum values pero sin implementacion
8. **MonitoredProvider leaks**: `_instances` es un class-level dict que nunca se limpia automaticamente (solo via `cleanup()` explicito), potencial memory leak en procesos long-running
9. **Singleton pattern en TokenTracker**: No se resetea entre analisis a menos que se llame `reset()` explicitamente. En un servidor multi-tenant, las stats se mezclan
10. **Health check costoso**: `AnthropicProvider.health_check()` hace una llamada real a la API con Haiku — consume tokens y agrega latencia en cada verificacion de cache en la factory
11. **Monkey patch fragil**: Se auto-ejecuta al import, reemplazando `sys.modules['claude_agent_sdk']` globalmente. Si algun import ocurre antes del patch, el codigo falla silenciosamente

---

## Recomendaciones 2026

### Prioridad Alta

1. **Sincronizar model mappings**: Unificar `base.py` y `cli_provider.py` para usar los mismos model IDs (claude-*-4-6). Crear un unico `MODEL_REGISTRY` centralizado
2. **Corregir bug `console_config`**: `LLMConfig` dataclass no tiene campo `console_config`, pero `from_env()` lo asigna. Renombrar a `cli_config` o agregar el campo
3. **Implementar OpenAI provider**: Completar la promesa de multi-provider. GPT-4o y o3 son alternativas viables para diversificar riesgo
4. **Circuit breaker**: Reemplazar el fallback basado en substring con un circuit breaker real (ej: `pybreaker`) que trackee failure rate y abra/cierre automaticamente

### Prioridad Media

5. **Semantic caching**: Implementar cache de respuestas basado en similarity de prompts (ej: hash del prompt + parametros). El swarm ejecuta queries similares entre analisis
6. **Integrar Vanna en la abstraccion**: Mover el adapter de Vanna para que use `LLMProvider` en lugar de llamar a Anthropic directamente
7. **Token tracking para CLI provider**: Parsear el output del CLI o usar la API de billing de Anthropic para estimar tokens reales en desarrollo
8. **Feature flags via Redis**: Implementar el source de Redis para switching distribuido en produccion multi-nodo
9. **Actualizar pricing**: Los precios hardcoded son de 2025. Implementar fetching dinamico o al menos un config file externo

### Prioridad Baja

10. **A/B testing framework**: Documentado como "Next Steps" en la arquitectura pero no implementado. Permitiria comparar calidad de respuestas entre providers/modelos
11. **Request queuing**: Para manejar rate limits proactivamente en lugar de reactivamente con backoff
12. **Dashboard de metricas**: Los datos de Prometheus estan disponibles pero no hay dashboard configurado (Grafana)
13. **Multi-tenant isolation**: Separar TokenTracker por tenant/analisis en lugar de singleton global

---

## Archivos Clave

| Archivo | Rol |
|---------|-----|
| `shared/llm/base.py` | Interface ABC `LLMProvider`, `LLMOptions`, `LLMResponse`, `ModelType` |
| `shared/llm/config.py` | `LLMConfig`, `ProviderType`, feature flags, `from_env()` |
| `shared/llm/factory.py` | `LLMProviderFactory`, `MonitoredProvider`, `MockProvider`, `get_provider()` |
| `shared/llm/providers/anthropic_provider.py` | Anthropic SDK wrapper con KV-cache |
| `shared/llm/providers/cli_provider.py` | Claude CLI subprocess/proxy provider |
| `shared/llm/adapter.py` | Backward-compatible adapter (drop-in `claude_agent_sdk`) |
| `shared/llm/monkey_patch.py` | Runtime interception de `claude_agent_sdk` imports |
| `shared/llm/token_tracker.py` | Singleton token/cost accumulator con Prometheus |
| `shared/llm/monitoring.py` | `MetricsCollector`, `CostTracker` |
| `scripts/claude_proxy.py` | HTTP proxy para Docker -> host CLI |
| `core/valinor/nl/vanna_adapter.py` | Vanna AI NL-SQL (usa Anthropic directamente) |
| `docs/LLM_PROVIDER_ARCHITECTURE.md` | Documentacion oficial de la arquitectura |
| `test_provider_switch.py` | Test suite para switching, fallback, metricas |
