# 18. Shared Module — Investigacion Completa

**Fecha**: 2026-03-22
**Ruta**: `/home/nicolas/Documents/delta4/valinor-saas/shared/`
**LOC totales**: ~6.482 lineas (34 archivos .py, excluyendo __pycache__)

---

## Resumen

El modulo `shared/` es el nucleo transversal de Valinor SaaS. Provee cuatro pilares fundamentales que consumen todos los demas modulos del sistema: (1) abstraccion LLM con multi-provider y fallback, (2) capa de memoria de cliente con perfil persistente, (3) conectores de base de datos unificados, y (4) utilidades de infraestructura (observabilidad, storage, SSH, email, PDF, webhooks). Es el modulo mas acoplado del proyecto — 132 archivos lo importan, incluyendo api/, worker/, mcp_servers/, tests/ y security/.

---

## Contenido — Estructura de Directorios

```
shared/
  __init__.py                    # Version 1.0.0, package marker
  email_digest.py                # Generacion y envio de digests HTML via SMTP
  observability.py               # Tracing con lmnr/Laminar + fallback no-op
  pdf_generator.py               # Generador PDF stdlib (sin dependencias externas)
  ssh_tunnel.py                  # Tuneles SSH efimeros + ZeroTrustValidator
  storage.py                     # MetadataStorage (Supabase o fallback local)
  webhook_dispatcher.py          # Dispatch de webhooks con HMAC-SHA256
  connectors/
    __init__.py                  # Re-exports de todos los conectores
    base.py                      # DeltaConnector ABC + SourceType enum
    factory.py                   # ConnectorFactory (patron Factory)
    postgresql.py                # PostgreSQLConnector (SQLAlchemy)
    mysql.py                     # MySQLConnector (SQLAlchemy + pymysql)
    etendo.py                    # EtendoConnector (PostgreSQL + SSH tunnel)
  llm/
    __init__.py                  # Re-exports: LLMProvider, LLMResponse, LLMOptions, etc.
    base.py                      # LLMProvider ABC, LLMResponse, LLMOptions, ModelType
    config.py                    # LLMConfig, ProviderType, FeatureFlagSource
    factory.py                   # LLMProviderFactory + MonitoredProvider wrapper
    adapter.py                   # Drop-in replacement para claude_agent_sdk
    monkey_patch.py              # Monkey-patch de claude_agent_sdk en sys.modules
    monitoring.py                # MetricsCollector + CostTracker
    token_tracker.py             # TokenTracker singleton + Prometheus + pricing
    providers/
      anthropic_provider.py      # AnthropicProvider (SDK oficial + KV-cache)
      cli_provider.py            # ClaudeCliProvider (CLI local o proxy HTTP)
  memory/
    __init__.py                  # Package marker (vacio)
    client_profile.py            # ClientProfile, FindingRecord, KPIDataPoint, ClientRefinement
    profile_store.py             # ProfileStore (asyncpg + fallback JSON)
    profile_extractor.py         # ProfileExtractor — actualiza perfil post-run
    adaptive_context_builder.py  # Genera bloque de contexto adaptativo para prompts
    alert_engine.py              # AlertEngine — 5 tipos de condicion + auto-alerts
    industry_detector.py         # IndustryDetector — heuristicas + LLM fallback
    segmentation_engine.py       # SegmentationEngine — segmentacion Pareto por revenue
  utils/
    __init__.py                  # Re-exports de todos los helpers
    date_utils.py                # parse_period, format_duration, days_since
    formatting.py                # format_currency, format_percentage, format_delta, slugify, truncate_text
```

---

## Tipos Compartidos

### Enums
| Enum | Archivo | Valores |
|------|---------|---------|
| `SourceType` | `connectors/base.py` | POSTGRESQL, MYSQL, ETENDO |
| `ModelType` | `llm/base.py` | OPUS, SONNET, HAIKU, GPT4, GPT4_TURBO |
| `ProviderType` | `llm/config.py` | ANTHROPIC_API, CONSOLE_CLI, MOCK |
| `FeatureFlagSource` | `llm/config.py` | ENV, FILE, REDIS, API |

### Dataclasses
| Dataclass | Archivo | Descripcion |
|-----------|---------|-------------|
| `ClientProfile` | `memory/client_profile.py` | Perfil persistente por cliente (30+ campos). Nucleo del sistema de memoria. |
| `FindingRecord` | `memory/client_profile.py` | Hallazgo visto en al menos un run (id, title, severity, agent, first/last_seen, runs_open) |
| `KPIDataPoint` | `memory/client_profile.py` | Medicion KPI (period, label, value, numeric_value, run_date) |
| `ClientRefinement` | `memory/client_profile.py` | Output del Auto-Refinement Engine (table_weights, query_hints, focus_areas, suppress_ids) |
| `LLMOptions` | `llm/base.py` | Opciones unificadas para queries LLM (model, temperature, max_tokens, stream, tools) |
| `LLMResponse` | `llm/base.py` | Respuesta unificada de cualquier provider (content, model, usage, finish_reason) |
| `LLMConfig` | `llm/config.py` | Configuracion master con feature flags y fallback |
| `AgentTokenStats` | `llm/token_tracker.py` | Stats acumulados por agente (tokens in/out, cache, cost) |
| `CustomerSegment` | `memory/segmentation_engine.py` | Segmento de clientes (nombre, count, revenue, share) |
| `SegmentationResult` | `memory/segmentation_engine.py` | Resultado completo de segmentacion |

### Abstract Base Classes
| ABC | Archivo | Metodos abstractos |
|-----|---------|-------------------|
| `DeltaConnector` | `connectors/base.py` | connect(), close(), execute_query(), get_schema() |
| `LLMProvider` | `llm/base.py` | initialize(), query(), health_check(), close(), supported_models(), estimate_cost() |

---

## Utilidades

### `utils/date_utils.py`
- `parse_period(period: str) -> tuple[str, str]` — Parsea Q1-2025, H1-2025, 2025, 2025-04 a fechas ISO start/end
- `format_duration(seconds: float) -> str` — 45 -> "45s", 154 -> "2m 34s"
- `days_since(date_str: str) -> int` — Dias desde una fecha ISO

### `utils/formatting.py`
- `format_currency(value, currency, compact, decimals)` — Soporte EUR, USD, GBP, ARS, BRL, MXN con separadores correctos
- `format_percentage(value, decimals)` — "8.2%"
- `format_delta(value, as_percentage)` — "+12.3%" o "-5.1"
- `truncate_text(text, max_len, suffix)` — Trunca con "..."
- `slugify(text)` — Unicode-safe slug generation

### `pdf_generator.py`
- `generate_pdf_report(results: dict) -> bytes` — PDF valido con raw PDF syntax (sin reportlab/weasyprint). Solo stdlib.

### `observability.py`
- `observe_agent(agent_name)` — Decorator para tracing (lmnr o no-op). Soporta sync y async.
- `get_tracer()` — Tracer OpenTelemetry-compatible
- `record_token_usage(agent_name, input_tokens, output_tokens)` — Registro de tokens por agente
- `SWARM_AGENTS` — Lista de los 8 agentes del swarm

---

## Configuracion

### Variables de Entorno Consumidas
| Variable | Modulo | Uso |
|----------|--------|-----|
| `LMNR_API_KEY` | observability.py | Activacion de Laminar tracing |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | email_digest.py | Envio de digests |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | storage.py | MetadataStorage backend |
| `DATABASE_URL` | memory/profile_store.py | PostgreSQL para perfiles |
| `ENCRYPTION_KEY` | ssh_tunnel.py | Cifrado Fernet de credenciales |
| `LLM_PROVIDER` | llm/config.py, monkey_patch.py | Seleccion de provider (anthropic_api, console_cli, mock) |
| `ANTHROPIC_API_KEY` | llm/config.py | API key de Anthropic |
| `CLAUDE_CLI_PATH` | llm/config.py | Path al CLI de Claude |
| `CLAUDE_PROXY_HOST/PORT` | llm/providers/cli_provider.py | Proxy para Docker |
| `ENABLE_TOKEN_TRACKING` | llm/token_tracker.py | Prometheus metrics |
| `LLM_ENABLE_FALLBACK/CACHING/MONITORING` | llm/config.py | Feature flags |

### Patrones de Configuracion
- **Dual-backend con fallback**: MetadataStorage (Supabase -> local), ProfileStore (asyncpg -> JSON), LLM (API -> CLI -> Mock)
- **Feature flags via env vars**: `LLM_ENABLE_*`, `LLM_FORCE_PROVIDER`, `LLM_DRY_RUN`
- **Runtime switching**: `switch_provider()` en monkey_patch.py permite cambiar provider sin restart

---

## Acoplamiento

### Consumidores Principales (excl. worktrees y tests)
| Consumidor | Imports de shared/ |
|------------|-------------------|
| `api/main.py` | connectors, memory, llm |
| `api/adapters/valinor_adapter.py` | memory (profile_store, profile_extractor, adaptive_context_builder, alert_engine, segmentation, industry_detector), observability, utils |
| `api/refinement/` (4 archivos) | memory (client_profile, profile_store), llm (monkey_patch, base) |
| `worker/tasks.py` | storage (MetadataStorage), memory (profile_store) |
| `mcp_servers/etendo_server.py` | ssh_tunnel (SSHTunnelManager) |
| `scripts/seed_demo_profile.py` | memory (client_profile, profile_store) |
| `security/test_prompt_injection.py` | connectors (postgresql) |

### Dependencias Internas (dentro de shared/)
- `email_digest.py` -> `memory.client_profile`
- `webhook_dispatcher.py` -> `memory.client_profile`
- `connectors/etendo.py` -> `ssh_tunnel`
- `llm/monkey_patch.py` -> `llm.base`, `llm.config`, `llm.factory`
- `llm/providers/anthropic_provider.py` -> `llm.token_tracker`
- `memory/adaptive_context_builder.py` -> `memory.client_profile`
- `memory/alert_engine.py` -> `memory.client_profile`
- `memory/industry_detector.py` -> `llm.monkey_patch`, `llm.base`
- `memory/profile_extractor.py` -> `memory.client_profile`
- `memory/profile_store.py` -> `memory.client_profile`
- `memory/segmentation_engine.py` -> `memory.client_profile`

### ClientProfile: El Hub Central
`ClientProfile` es el tipo mas referenciado de todo el proyecto. Es importado por 10+ modulos dentro de shared/ y por api/adapters, api/refinement, worker y scripts. Tiene 30+ campos y actua como el estado persistente completo de cada cliente.

---

## Fortalezas

1. **Abstraccion LLM solida**: El patron Provider + Factory + MonitoredProvider permite switching transparente entre Anthropic API, CLI local y Mock sin cambiar codigo de agentes. El monkey-patch mantiene compatibilidad backward con `claude_agent_sdk`.

2. **Sistema de memoria de cliente maduro**: ClientProfile + ProfileExtractor + AlertEngine + SegmentationEngine + AdaptiveContextBuilder forman un pipeline completo de inteligencia acumulativa por cliente. El perfil crece con cada run.

3. **Conectores bien diseñados**: DeltaConnector ABC con Factory pattern y context managers. Read-only enforcement (`_require_select()`). Soporte PostgreSQL, MySQL y Etendo (con SSH tunnel). Facil de extender.

4. **Dual-backend resiliente**: Todos los servicios de persistencia (ProfileStore, MetadataStorage, observability) tienen fallback local. El sistema funciona sin infraestructura externa.

5. **Observabilidad integrada**: lmnr/OpenTelemetry con no-op fallback, Prometheus para tokens, CostTracker con budget limits, structured logging con structlog.

6. **Seguridad consciente**: ZeroTrustValidator para SSH, HMAC-SHA256 en webhooks, cifrado Fernet para credenciales, filtrado de datos sensibles en MetadataStorage, audit log append-only.

7. **Utilidades bien acotadas**: date_utils y formatting son puros, sin side-effects, con soporte multi-moneda (6 currencies) y multi-formato de periodo.

8. **Token tracking con KV-cache**: TokenTracker con pricing Anthropic 2025, cache_hit_rate, Prometheus counters. AnthropicProvider integra cache_control automaticamente.

---

## Debilidades

1. **ClientProfile es un God Object**: 30+ campos en un solo dataclass, desde entity_map_cache hasta webhooks y segmentation_history. Viola Single Responsibility. Cualquier cambio en el perfil impacta todo el sistema.

2. **LLMConfig.from_env() con campo fantasma**: Referencia `console_config` como parametro (linea 75-81 de config.py) pero el dataclass solo define `anthropic_config` y `cli_config`. Esto causa un `TypeError` en runtime si se invoca `from_env()`. Bug critico no detectado.

3. **Monkey-patch como solucion permanente**: `monkey_patch.py` reemplaza `claude_agent_sdk` en `sys.modules` al importarse. Es fragil, auto-ejecuta side-effects al import, y mezcla mocks (AssistantMessage, TextBlock, tool, create_sdk_mcp_server) con logica real.

4. **Duplicacion de pricing**: El pricing de Anthropic esta duplicado en `token_tracker.py` (ANTHROPIC_PRICING) y `anthropic_provider.py` (estimate_cost hardcoded). No hay fuente unica de verdad.

5. **storage.py y profile_store.py solapan responsabilidades**: Ambos manejan persistencia con Supabase/PostgreSQL + fallback local. MetadataStorage almacena client_memory y job metadata; ProfileStore almacena ClientProfile. La linea divisoria es difusa.

6. **Audit log escribe a /tmp**: `ssh_tunnel.py` escribe audit a `/tmp/valinor_audit.jsonl`. Perfiles se guardan en `/tmp/valinor_profiles/`. En produccion esto se pierde al reiniciar contenedores.

7. **Sin tests unitarios dentro de shared/**: Todos los tests estan en `tests/` a nivel raiz. No hay cobertura inmediata visible para edge cases de formatting, date parsing o segmentation.

8. **pdf_generator.py maneja solo una pagina**: El generador PDF construye un unico content stream. Reportes largos se salen del area visible del PDF sin paginacion.

9. **Imports circulares potenciales**: `industry_detector.py` importa de `llm.monkey_patch` que a su vez importa de `llm.base`, `llm.config`, `llm.factory`. La cadena es fragil si alguno de esos modulos necesita algo de memory/.

10. **No hay interfaces explicitamente tipadas para almacenamiento**: ProfileStore y MetadataStorage no implementan una ABC comun. Inyeccion de dependencias se hace ad-hoc.

---

## Recomendaciones 2026

### Criticas (Q2-2026)

1. **Corregir bug en LLMConfig.from_env()**: Eliminar la referencia a `console_config` que no existe en el dataclass, o agregar el campo. Este es un bug latente que rompe en runtime.

2. **Descomponer ClientProfile**: Extraer sub-modelos: `ClientFindings`, `ClientKPIs`, `ClientSegmentation`, `ClientAlerts`, `ClientRefinement` (ya existe pero embebido). El profile principal deberia ser un compositor que referencia sub-objetos.

3. **Unificar pricing en un solo modulo**: Crear `shared/llm/pricing.py` con una fuente de verdad para los costos Anthropic. TokenTracker y AnthropicProvider deben consumir de ahi.

### Altas (Q2-Q3 2026)

4. **Eliminar monkey-patch progresivamente**: Migrar los agentes core para importar directamente de `shared.llm.adapter` en lugar de depender de `claude_agent_sdk` interceptado en sys.modules. El monkey-patch deberia ser opcional, no auto-ejecutado.

5. **ABC para storage**: Crear `StorageBackend` ABC que implementen tanto `ProfileStore` como `MetadataStorage`. Facilitaria testing con mocks y migracion a otros backends.

6. **PDF multi-pagina**: Implementar paginacion en pdf_generator.py o migrar a weasyprint (ya disponible en el ecosistema Docker). Los reportes actuales se truncan.

7. **Mover paths de /tmp a volumenes configurables**: Parametrizar `_LOCAL_DIR`, `local_storage_dir` y la ruta de audit log con env vars y defaults a paths dentro del proyecto, no /tmp.

### Medias (Q3-Q4 2026)

8. **Consolidar storage.py y profile_store.py**: Evaluar si MetadataStorage puede ser reemplazado por ProfileStore + tablas adicionales, o si ambos deben heredar de una ABC comun.

9. **Agregar tests colocados**: Mover tests especificos de shared/ a `shared/tests/` para facilitar desarrollo aislado y CI rapido.

10. **Documentar contratos de datos**: Los tipos compartidos (especialmente ClientProfile y LLMOptions) necesitan schemas JSON-Schema o Pydantic para validacion en boundaries.

11. **Desacoplar IndustryDetector de LLM monkey-patch**: La deteccion con LLM deberia recibir un provider inyectado, no importar `_interceptor` directamente de monkey_patch.

12. **Feature flags en Redis/API**: `FeatureFlagSource` enum define REDIS y API como opciones pero no estan implementados. Evaluar si se necesitan o eliminar dead code.
