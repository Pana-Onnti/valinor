# 19. Scripts y Automatizacion

## Resumen

El directorio `scripts/` contiene 8 archivos principales y un subsistema completo de generacion de datos (`playground/`) que en conjunto forman la infraestructura de automatizacion del proyecto. Se dividen en cuatro categorias funcionales:

| Categoria | Scripts | Proposito |
|-----------|---------|-----------|
| Claude Proxy | `claude_proxy.py` | Bridge HTTP para acceso al CLI de Claude desde contenedores Docker |
| Dev Tools | `dev.sh`, `rebuild.sh` | Setup de entorno, gestion de servicios Docker, rebuild rapido |
| DB Seeds | `init.sql`, `seed_demo_profile.py` | Inicializacion de metadata DB y perfiles de demo |
| Gloria Integration | `setup_gloria_connection.py`, `test_gloria_queries.py` | Conexion SSH tunnel a BD de cliente y test E2E con ground truth |
| Health Checks | `health_check.sh` | Verificacion de salud del sistema (4 checks) |
| Playground | `playground/` (10 agentes, orchestrator, templates) | Swarm de generacion de datos sinteticos y testing continuo |

Lineas de codigo estimadas: ~4,500 (scripts principales) + ~2,500 (playground).

---

## Claude Proxy

**Archivo:** `scripts/claude_proxy.py` (88 lineas)

Servidor HTTP minimalista que expone el CLI de Claude (Plan Max) a contenedores Docker que no tienen acceso directo al binario del host.

**Arquitectura:**
- `GET /health` -- healthcheck, retorna binario detectado
- `POST /query` -- recibe `{prompt, model}`, ejecuta `claude --print --model <model>` via subprocess
- Puerto default: 8099, bind en 0.0.0.0
- Timeout de subprocess: 300s (5 min)
- Modelo default: `claude-sonnet-4-5`

**Mecanismo:** `BaseHTTPRequestHandler` sincrono (stdlib pura). Detecta el binario de Claude via `shutil.which("claude")`.

**Observaciones:**
- Sin autenticacion ni rate limiting -- cualquier proceso en la red puede hacer queries
- Servidor sincrono bloqueante: una request larga bloquea todas las demas
- Sin logging estructurado (solo print)
- Sin TLS
- `import subprocess` esta dentro del metodo `do_POST` en vez de top-level (menor)

---

## Dev Tools

### dev.sh (320 lineas)

Script maestro de desarrollo con subcomandos: `setup`, `start`, `stop`, `restart`, `reset`, `test`, `logs`, `shell`, `psql`, `redis-cli`.

**Flujo de `setup`:**
1. Verifica requisitos: Docker, Docker Compose, Python 3, Node.js
2. Crea `.env` desde `.env.example` o genera uno con defaults (incluye generacion de `ENCRYPTION_KEY` y `JWT_SECRET` via `openssl rand`)
3. Genera llaves SSH demo RSA-4096 en `demo/ssh_keys/demo_rsa`
4. Copia Valinor v0 core desde `/home/nicolas/Documents/delta4/Valinor/valinor` (path hardcodeado)
5. Levanta Docker Compose: postgres, redis, api, worker, flower
6. Espera readiness con polling (30 iteraciones para PG, 10 para Redis)

**Flags notables:**
- `--with-frontend` / `-f`: levanta perfil `full` (frontend en :3000)
- `--with-demo` / `-d`: levanta perfil `demo` (SSH en :2222, DB demo en :5433)

**Observaciones:**
- Path absoluto hardcodeado a `/home/nicolas/Documents/delta4/Valinor/valinor` -- no funciona en otro equipo
- Usa `docker-compose` (v1 legacy) en vez de `docker compose` (v2) en todos los comandos, aunque el check de requisitos verifica ambos
- `reset` pide confirmacion interactiva (`read -p`)
- El archivo `.env` generado tiene credenciales placeholder visibles

### rebuild.sh (17 lineas)

Script minimo para rebuild rapido:
```
docker compose build api worker
docker compose up -d --no-deps api worker
sleep 5
curl -s http://localhost:8000/health | python3 -m json.tool
```

**Observacion:** Usa `docker compose` (v2), inconsistente con `dev.sh` que usa `docker-compose` (v1).

---

## DB Seeds

### init.sql (281 lineas)

DDL completo del metadata database PostgreSQL. Diseho explicitamente para NO almacenar datos de clientes (solo metadata y audit trails).

**Tablas creadas:**
| Tabla | Proposito |
|-------|-----------|
| `analysis_jobs` | Tracking de ejecucion de jobs (status, timestamps) |
| `analysis_results` | Resultados agregados (findings_count, critical_issues, etc.) |
| `client_memory` | Memoria de aprendizaje entre analisis (JSONB) |
| `audit_log` | Append-only audit trail con constraint de tipos de evento |
| `system_config` | Configuracion sistema (JSONB key-value) |
| `user_sessions` | Sesiones de usuario (para auth futura) |

**Vistas:**
- `job_statistics`: metricas por cliente (total jobs, avg execution time, avg findings)
- `daily_usage`: uso diario ultimos 30 dias

**Funciones/Triggers:**
- `cleanup_old_metadata(retention_days)`: limpieza con retencion configurable; audit logs solo se borran si retention > 365 dias
- `log_audit_event()`: funcion helper para insertar en audit_log
- `log_job_state_change()`: trigger AFTER INSERT/UPDATE en analysis_jobs que registra cambios de estado automaticamente

**Seguridad preparada (comentada):**
- Row Level Security para multi-tenancy
- Grants para usuario `valinor_app`
- Politica de aislamiento por `client_name`

**Config defaults insertados:**
- `max_concurrent_jobs`: 5
- `job_timeout_seconds`: 3600
- `cleanup_after_hours`: 24
- `retention_days`: 90
- `api_rate_limit`: 60/min, 1000/hora

### seed_demo_profile.py (206 lineas)

Genera un `ClientProfile` sintetico completo para demos. Default: `Gloria_SA`.

**Datos generados:**
- 5 runs historicos con KPI trends (Facturacion, Cobranza, Clientes Activos, Margen Bruto)
- 4 findings activos (CRITICAL a LOW) con timestamps y conteo de runs abiertos
- 2 findings resueltos con fechas de resolucion
- Refinement block con query hints, focus areas, suppress_ids
- Entity map cache (invoices, customers, payments, products, orders con confidence scores)
- DQ history (5 entries, scores 87-93)

**Dependencias internas:** `shared.memory.client_profile`, `shared.memory.profile_store`. Guarda en `/tmp/valinor_profiles/{client_name}.json`.

---

## Gloria Integration

### setup_gloria_connection.py (330 lineas)

Setup interactivo para conexion a la BD de Gloria via SSH tunnel. Clase `GloriaDBSetup` con flujo wizard.

**Flujo:**
1. Recopila config SSH (host, port, user, key path o password)
2. Recopila config DB (host, port, name, user, password, tipo: PG/MySQL/MSSQL/Oracle)
3. Genera llave SSH ed25519 si no existe
4. Guarda config en `~/.valinor/gloria_config.json` con permisos 0o600
5. Testa conexion via `shared.ssh_tunnel.create_ssh_tunnel` + test query
6. Puede generar `.env` para Docker Compose

**Modos:**
- `--test`: testea config existente
- `--env`: genera `.env` desde config guardada
- Sin flags: wizard interactivo

**Observaciones:**
- La config se guarda en JSON plano con password en texto -- el comentario dice "In production, encrypt sensitive fields" pero no esta implementado
- El metodo `create_env_file` escribe `DB_PASSWORD` en plano al `.env`
- Soporta PostgreSQL, MySQL, MSSQL (no Oracle en URL builder aunque esta en la seleccion)

### test_gloria_queries.py (341 lineas)

Test E2E critico: ejecuta el pipeline completo contra la BD real de Gloria y compara con ground truth verificado manualmente.

**Pipeline testeado:**
1. **Knowledge Graph**: construye KG desde entity_map -> tablas, edges, conceptos
2. **Query Builder**: genera pack de queries SQL desde entity_map + periodo
3. **Ejecucion SQL**: ejecuta contra `postgresql://tad:tad@localhost:5432/gloria`
4. **Baseline**: computa metricas (revenue, invoices, AR, customers)
5. **Verification Engine**: verifica findings correctos vs hallucinated (test con $13.5M AR fabricado)
6. **Ground Truth**: compara con valores conocidos (tolerance 0.5-1.0%)

**Ground Truth Values (Dec 2024):**
| Metrica | Valor |
|---------|-------|
| Total Revenue | $1,631,559.62 |
| Invoice Count | 3,139 |
| Avg Invoice | $519.77 |
| Distinct Customers | 1,223 |
| AR Outstanding | $3,267,365.43 |
| Customers with Debt | 509 |
| Top Debtor | ISKAY PET S.LU. ($865,514.74) |

**Entity Map de Gloria:**
- `c_invoice`: 4,117 rows, filtro `issotrx='Y' AND docstatus='CO' AND isactive='Y'`
- `c_bpartner`: 88 rows, filtro `iscustomer='Y' AND isactive='Y'`
- `fin_payment_schedule`: 8,019 rows, filtro `isactive='Y'`

**Observacion importante:** Re-implementa `compute_baseline` localmente porque `pipeline.py` importa `claude_agent_sdk` que no esta disponible fuera del entorno de agentes. Esto crea riesgo de divergencia si el original cambia.

---

## Health Checks

### health_check.sh (73 lineas)

Script de verificacion de salud del sistema con 4 checks:

1. **Docker containers**: `docker compose ps` exitoso
2. **API health**: `GET http://localhost:8000/health` retorna JSON valido
3. **System status**: `GET http://localhost:8000/api/system/status` retorna version y features
4. **Test suite**: `pytest tests/ -q` todos pasan

**Output:** Resumen coloreado con conteo de pass/fail. Exit code 0 si todo pasa, 1 si hay fallos.

**Observacion:** Usa `set -euo pipefail` pero el check de health endpoint usa `|| true` para no abortar en fallos individuales -- bien implementado.

---

## Playground

### Arquitectura

Sistema de generacion de datos sinteticos y testing continuo compuesto por 10 agentes organizados en 4 tiers:

```
Tier 1: Hunters (fetch real data)
  #1 PublicDataScoutAgent    -- World Bank API + SEC EDGAR
  #2 RealCompanyHarvesterAgent -- yfinance (10 tickers: AAPL, MSFT, GOOGL...)

Tier 2: Generators (synthetic data)
  #3 ERPForgeAgent           -- Etendo + Odoo schemas, Pareto/log-normal distributions
  #4 IndustryMimickerAgent   -- Retail/wholesale/services/manufacturing + anomalias
  #5 EdgeCaseForgeAgent      -- 10 edge cases (empty, nulls, unicode, huge amounts...)

Tier 3: Bootstrappers (resample/mutate/evolve)
  #6 BootstrapResamplerAgent -- N=3 variaciones bootstrap por dataset
  #7 PerturbationEngineAgent -- 6 mutaciones (noise, nulls, FK corruption, currency swap...)
  #8 TimeWarpGeneratorAgent  -- 6 periodos con growth 5%/mes, seasonality, churn

Tier 4: Testers (continuous validation)
  #9 PipelineSmokerAgent     -- Sube SQLite a PG temporal, ejecuta pipeline, poll resultado
  #10 QualityAuditorAgent    -- Lee smoke reports, audita calidad (5 checks, scoring)
```

### Orchestrator (297 lineas)

Punto de entrada con CLI completo:
- `--agents 3,9`: seleccion de agentes especificos
- `--cycles 2`: limitar ciclos
- `--dry-run`: validar carga sin ejecutar
- `--verbose`: logging DEBUG

Usa `asyncio.Semaphore(MAX_CONCURRENT_JOBS=3)` para bounded concurrency. Signal handlers para graceful shutdown (SIGINT/SIGTERM).

### Base Agent Framework

`PlaygroundAgent` abstracto con:
- `DatasetRecord`: metadata de dataset generado (name, path, row_counts, tags)
- `PlaygroundContext`: shared state (dirs, API URL, DB config, asyncio.Queue, stop_event)
- `AgentResult`: outcome con datasets, errors, stats
- `run_continuous()`: loop infinito con backoff para testers

### Datasets Generados (observados en disco)

| Categoria | Archivos | Ejemplo |
|-----------|----------|---------|
| Real (yfinance) | 10 .db | `company_aapl.db`, `company_msft.db` |
| Synthetic (ERP) | ~10 .db | `erp_etendo_694ea4ec.db`, `erp_odoo_b59770fa.db` |
| Synthetic (Industry) | ~4 .db | `industry_wholesale_77e01fd8.db` |
| Edge Cases | 10 .db | `edge_empty_tables.db`, `edge_unicode_hell.db` |
| Bootstrapped | ~30+ .db | `boot_company_aapl_1.db`, `perturb_*.db` |
| Smoke Reports | 3 .json | `smoke_2026-03-22_02-50-17.json` |

### Detalle de Agentes Notables

**ERPForgeAgent (#3):** Genera ERP completos con distribucion Pareto (alpha=1.16) para concentracion de clientes (regla 80/20), montos log-normal, 95% CO / 3% DR / 2% VO en docstatus, 70% de facturas con pago, 10% pagos parciales. Soporta Etendo y Odoo schemas.

**EdgeCaseForgeAgent (#5):** 10 escenarios adversariales incluyendo: tablas vacias, todos NULLs, valores `#REF!`/`NaN` en columnas numericas, montos de $999,999,999,999.99, PKs duplicados (sin constraint), inyeccion SQL en nombres (`Robert'); DROP TABLE...`), fechas extremas (1900-2099), texto unicode con RTL/zero-width/emojis.

**PerturbationEngineAgent (#7):** 6 mutaciones: gaussian noise (5-50% de std), null injection (5-30% rate), row duplication (5-20%), FK corruption (10% de IDs), currency swap (factor random 0.01-100x), column shuffle.

**PipelineSmokerAgent (#9):** Carga SQLite en schema PG temporal (`play_*`), envia a `/api/analyze`, poll cada 10s con timeout 300s, limpia schema despues. Los smoke reports en disco muestran que algunos tests fallan con "Insufficient entity mapping".

---

## Fortalezas

1. **Playground Swarm es sofisticado y unico.** El sistema de 10 agentes con 4 tiers (hunt -> generate -> bootstrap -> test) es un pipeline de testing continuo raro de ver en proyectos de este tamanho. La generacion de datos estadisticamente realistas (Pareto, log-normal) y los edge cases adversariales son de calidad de produccion.

2. **Ground truth testing riguroso.** `test_gloria_queries.py` compara pipeline output contra valores verificados manualmente con tolerancia de 0.5-1.0%. El test de anti-hallucination (valor fabricado de $13.5M AR) valida directamente que el Verification Engine funciona.

3. **init.sql bien estructurado.** Triggers automaticos para audit log, funcion de cleanup con retencion configurable, vistas analiticas pre-construidas, RLS preparado para multi-tenancy. El principio de "zero client data" esta claro en el diseho.

4. **dev.sh completo.** Un solo script para todo el ciclo de desarrollo: setup, start, stop, reset, test, shell, psql, redis-cli. Buena ergonomia de desarrollo.

5. **Health check integral.** Verifica containers, API, system status, y test suite en un solo script con output coloreado y exit codes apropiados.

6. **Seed data contextualizada.** El perfil demo incluye findings, KPI history, refinement hints, y entity maps que reflejan casos reales del dominio (distribucion mayorista argentina, facturas vencidas >90 dias).

---

## Debilidades

1. **Claude Proxy sin seguridad.** Sin autenticacion, sin TLS, bind en 0.0.0.0. Cualquier proceso en la red puede ejecutar prompts con el plan del usuario. El servidor sincrono se bloquea con una sola request lenta.

2. **Credenciales en texto plano en multiples lugares.** `setup_gloria_connection.py` guarda passwords en JSON plano. `config.py` del playground tiene `user: "tad", password: "tad"`. `test_gloria_queries.py` tiene connection string hardcodeada. `dev.sh` genera `.env` con `dev_password_change_in_prod`.

3. **Paths absolutos hardcodeados.** `dev.sh` referencia `/home/nicolas/Documents/delta4/Valinor/valinor` directamente. No funciona en otro equipo ni en CI.

4. **Inconsistencia docker-compose v1 vs v2.** `dev.sh` usa `docker-compose` (legacy), `rebuild.sh` y `health_check.sh` usan `docker compose` (moderno). Puede causar problemas si solo uno de los dos esta instalado.

5. **Duplicacion de `compute_baseline`.** `test_gloria_queries.py` re-implementa la funcion porque no puede importar el modulo original. Si el original diverge, los tests pasan pero la produccion falla.

6. **Duplicacion de `_read_tables`/`_write_tables`.** Tres agentes del playground (bootstrap_resampler, perturbation_engine, time_warp_generator) tienen la misma implementacion copy-paste de estos metodos.

7. **Playground sin tests unitarios.** 10 agentes complejos sin un solo test. Si un cambio rompe ERPForgeAgent, solo se descubre al correr el orchestrator completo.

8. **Playground datasets no tiene .gitignore dedicado.** Los .db generados aparecen como untracked (el directorio esta en git status como `??`). Si alguien hace `git add .` accidentalmente, decenas de archivos binarios entran al repo.

9. **Sin mecanismo de limpieza de datasets antiguos.** El playground acumula .db files indefinidamente. No hay rotacion ni limite de espacio.

10. **Oracle incompleto en setup_gloria_connection.py.** Se lista como opcion 4 en el wizard interactivo pero `build_db_url` no tiene branch para Oracle -- lanza `ValueError: Unsupported database type`.

---

## Recomendaciones 2026

### Prioridad Alta

1. **Asegurar Claude Proxy.** Agregar autenticacion bearer token (leer de env var), limitar bind a 127.0.0.1 o docker network, agregar rate limiting basico (token bucket en memoria). Considerar migrar a `aiohttp` para no bloquear en requests lentas.

2. **Encriptar credenciales en setup_gloria_connection.** Implementar el TODO existente: usar `cryptography.fernet` con key derivada de master password, o delegar a un secret manager (Vault, AWS Secrets Manager). No escribir `DB_PASSWORD` en plano al `.env`.

3. **Eliminar paths absolutos.** Reemplazar `/home/nicolas/...` en `dev.sh` con variable de entorno `VALINOR_CORE_PATH` o parametro. Usar path relativo al repo root.

4. **Unificar docker-compose v1/v2.** Estandarizar en `docker compose` (v2) en todos los scripts. Agregar wrapper function que detecte cual esta disponible.

### Prioridad Media

5. **Extraer `compute_baseline` a modulo importable.** Separar de `pipeline.py` en un modulo que no dependa de `claude_agent_sdk`. Eliminar la copia local en `test_gloria_queries.py`.

6. **DRY en playground agents.** Extraer `_read_tables`/`_write_tables` a un modulo utilitario compartido (`scripts/playground/utils/sqlite_io.py`). Los tres bootstrappers pueden importar de ahi.

7. **Agregar tests unitarios al playground.** Al menos tests para ERPForgeAgent (verificar schema generado, conteo de filas, distribuciones), EdgeCaseForgeAgent (cada caso genera DB valido), y PerturbationEngineAgent (cada mutacion no crashea).

8. **Agregar .gitignore en playground/datasets.** `echo "*.db" > scripts/playground/datasets/.gitignore` para prevenir inclusion accidental de binarios.

9. **Rotacion de datasets.** Agregar flag `--max-datasets N` al orchestrator que borre los mas antiguos cuando se exceda el limite. O agregar cleanup agent como tier 5.

### Prioridad Baja

10. **Logging estructurado en Claude Proxy.** Migrar de `print()` a `logging` con formato JSON para integracion con observabilidad.

11. **Completar soporte Oracle.** Agregar connection string Oracle en `build_db_url` o remover la opcion del wizard para no confundir.

12. **Parametrizar ground truth en test_gloria_queries.py.** Mover GROUND_TRUTH a un JSON externo para facilitar actualizacion cuando los datos de Gloria cambien.

13. **Agregar smoke test report aggregation.** El QualityAuditor lee reports individuales; seria util un reporte consolidado con tendencias (% pass rate over time, avg execution time trend).
