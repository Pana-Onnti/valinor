# Developer Guide — Valinor SaaS

Guía operativa para el agente y el equipo. Flujo de implementación, comandos frecuentes, y gotchas críticos.

## Flujo de implementación: Domain → App → Infrastructure

Siempre implementar en este orden para respetar arquitectura hexagonal:

```
1. Domain layer (core/valinor/, shared/)
   → Entidades, reglas de negocio, interfaces
   → NUNCA importa de Infrastructure

2. Application layer (api/)
   → Use cases, adapters, controllers
   → Usa Domain layer vía interfaces

3. Infrastructure layer (docker, config, deploy)
   → Implementaciones concretas (DB, Redis, Docker)
   → Depende de Application y Domain
```

## Comandos de desarrollo

### Arranque completo
```bash
docker compose up -d                    # Todos los servicios
python3 scripts/claude_proxy.py &       # OBLIGATORIO: proxy Claude CLI (host, no Docker)
docker compose ps                       # Verificar estado
curl http://localhost:8000/health       # Verificar API
curl http://localhost:8099/health       # Verificar proxy
```

### Logs y debugging
```bash
docker compose logs -f api              # Logs API en tiempo real
docker compose logs -f worker           # Logs Celery worker
docker compose ps                       # Estado de containers
```

### Rebuild tras cambios en requirements o Dockerfiles
```bash
docker compose build api worker
docker compose up -d --no-deps api worker
```

### Testing
```bash
source venv/bin/activate && pytest tests/ -v
pytest tests/ -x --tb=short            # Para en el primer fallo
pytest tests/test_[módulo].py -v       # Módulo específico
```

### Reset completo
```bash
docker compose down -v                  # Borra volúmenes (reset DB)
docker compose up -d                    # Arrancar de nuevo
```

## Puertos en uso (Docker)

| Servicio    | Puerto Host | Container | URL                              |
|-------------|-------------|-----------|----------------------------------|
| API         | 8000        | 8000      | http://localhost:8000/docs       |
| Frontend    | 3000        | 3000      | http://localhost:3000            |
| PostgreSQL  | **5450**    | 5432      | (valinor metadata DB)            |
| Redis       | **6380**    | 6379      |                                  |
| Prometheus  | 9090        | 9090      | http://localhost:9090            |
| Grafana     | 3001        | 3000      | http://localhost:3001 (admin/valinor) |
| Loki        | 3100        | 3100      |                                  |
| Promtail    | 9080        | 9080      | http://localhost:9080/targets    |
| Claude Proxy| 8099        | —         | http://localhost:8099/health     |

**DB del cliente (gloria/Openbravo):**
- Host: `localhost` — la API corre con `network_mode: host`
- Puerto: `5432` (el postgres local del host)
- Usuario: `tad` / Password: `tad` / DB: `gloria`

## Known Issues & Solutions

### Claude CLI proxy no responde
```
Causa: python3 scripts/claude_proxy.py no está corriendo
Fix: python3 scripts/claude_proxy.py & (en el host, no en Docker)
Verificar: curl http://localhost:8099/health
```

### "Connection refused" a DB del cliente
```
Causa: remapeo de host.docker.internal:5444 (ya removido)
Fix: usar localhost como host en el form
NUNCA usar host.docker.internal para la DB del cliente
```

### Worker crashea "No module named 'api'"
```
Causa: Dockerfile.worker no copiaba api/
Fix: verificar que ./api:/app/api esté en los volúmenes del worker en docker-compose.yml
```

### Logs no aparecen en Grafana/Loki
```
Causa: Docker API v1.42 vs v1.44
Fix: Promtail usa lectura directa con user: root y /var/lib/docker/containers/*/*.log
```

### "Invalid period format: 2025-04"
```
Ya resuelto. Formatos válidos: 2025-04 (mes), Q1-2025 (trimestre), H1-2025 (semestre), 2025 (año)
Código: core/valinor/config.py → parse_period(), api/main.py → _validate_period()
```

### AnalysisForm salta pasos
```
Ya resuelto. Botones sin type="button" hacían submit. Guard if (step !== 2) return en onSubmit.
```

## Environment Variables

### API & Auth
| Variable | Default | Description |
|---|---|---|
| `VALINOR_API_KEY` | — | API key for authentication. Required in production. |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins for CORS. |

### Connection Pooling (`shared/db_pool.py`)
| Variable | Default | Description |
|---|---|---|
| `VALINOR_DB_POOL_SIZE` | `5` | Base pool size per connection string. |
| `VALINOR_DB_POOL_MAX` | `10` | Max overflow connections. |
| `VALINOR_DB_POOL_TIMEOUT` | `30` | Checkout timeout in seconds. |
| `VALINOR_DB_POOL_RECYCLE` | `1800` | Connection recycle time in seconds. |
| `VALINOR_DB_POOL_PRE_PING` | `true` | Health check on checkout (recommended). |

### Encryption & SSH
| Variable | Default | Description |
|---|---|---|
| `ENCRYPTION_KEY` | — | Fernet key for encrypting credentials at rest. |

Connection pooling is automatic: `db_tools.py` uses `shared.db_pool.get_pooled_engine()` when available. Engines are cached by connection string and reused across tool calls. To force cleanup, call `shared.db_pool.dispose_pool()`.

---

## Reglas de codigo

### Python
- Type hints en todas las funciones publicas
- Pydantic models para todos los request/response bodies
- NUNCA almacenar datos de clientes — solo metadata y resultados
- SSH tunneling obligatorio — no conexiones directas a DBs

### Commits
```
tipo(scope): descripcion corta

Detalle opcional.

Refs: VAL-XX  <- OBLIGATORIO
```

### Tests
- Integration tests > unit tests triviales
- NO mockear la DB — integration tests usan la DB real
- LLM agents: mock `claude_agent_sdk` (see `tests/test_agent_llm_interactions.py` for patterns)
- Consolidar con @pytest.mark.parametrize
- Suite actual: ~2500+ tests (verificar no duplicar)

### Test Patterns for LLM Agents
When testing agents that use `claude_agent_sdk`:
1. Stub `claude_agent_sdk` in `sys.modules` before importing agent modules
2. Mock `query()` as an async generator yielding `AssistantMessage` with `TextBlock`
3. Verify prompt construction by inspecting `mock_query.call_args`
4. Test error handling by making the mock raise exceptions
5. See `tests/test_agent_llm_interactions.py` and `tests/test_narrators.py` for reference

## Dependencias clave

```
hiredis>=2.3.2          # (2.3.0 no existe en PyPI)
oracledb>=2.0.0          # reemplaza cx-Oracle obsoleto
claude-agent-sdk         # sin pin, última versión
mcp>=1.8.0               # ToolAnnotations desde 1.8
anthropic>=0.19.0
pydantic>=2.5.0 + pydantic-settings>=2.5.2
python-multipart>=0.0.9
cachetools>=5.5.0
supabase>=2.0.0
```
