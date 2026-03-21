# VALINOR SAAS v2 - AGENT HARNESS

## 🎯 WHAT IS VALINOR SAAS?

Valinor SaaS es una plataforma de Business Intelligence 100% agéntica que analiza cualquier base de datos empresarial y genera reportes ejecutivos en 15 minutos, sin configuración ni almacenamiento de datos del cliente.

## 🏗️ ARQUITECTURA ACTUAL

```
Cliente → SSH Tunnel → DB Cliente → Agentes Claude → Reportes
         ↓
    (Zero Data Storage)
```

- **NO almacenamos datos de clientes**, solo metadata y resultados
- **Conexiones efímeras** via SSH tunneling (máximo 1 hora)
- **Multi-agent pipeline**: Cartographer → Query Builder → [Analyst, Sentinel, Hunter] → Narrators
- **Quality pipeline**: DataQualityGate (8+1 checks) → CurrencyGuard → SegmentationEngine → AnomalyDetector → SentinelPatterns → AlertEngine
- **Intelligence layer**: ProfileExtractor → QueryEvolver → RevenueFactorModel → AdaptiveContextBuilder
- **Costo operativo**: ~$8 por análisis (Claude API)
- **Deployment zero-cost**: Cloudflare Workers + GitHub Actions + Supabase free

## 📁 ESTRUCTURA DEL PROYECTO

```
valinor-saas/
├── core/           # Código migrado de Valinor v0 (preserved)
│   ├── valinor/    # Pipeline actual sin modificar
│   └── .claude/    # Skills de agentes
├── api/            # FastAPI endpoints
├── web/            # Next.js frontend
├── worker/         # Background processing (Celery/GitHub Actions)
├── shared/         # Types, utils, SSH tunnel manager
├── deploy/         # Cloudflare Workers, GitHub workflows
└── docs/           # Documentación técnica
```

## 🔑 REGLAS CRÍTICAS

### SEGURIDAD Y COMPLIANCE
1. **NUNCA almacenar datos de clientes** - solo metadata y resultados agregados
2. **Conexiones SSH temporales** - máximo 1 hora, cleanup automático
3. **Credenciales encriptadas** - usar AWS Secrets Manager o Redis con TTL
4. **Audit logging completo** - todas las conexiones y accesos
5. **Zero-trust architecture** - validar cada request

### ARQUITECTURA Y CÓDIGO
1. **Preservar código Valinor v0** - wrapper instead of rewrite
2. **SSH tunneling obligatorio** - no conexiones directas a DBs
3. **Queues para análisis largos** - GitHub Actions como worker gratuito
4. **Streaming de resultados** - WebSockets o SSE para progreso
5. **Fallback mechanisms** - si falla un agente, continuar con el resto

### DESARROLLO
1. **Development local primero** - Docker Compose para todo
2. **Testing incremental** - cada agente por separado
3. **Rollback checkpoints** - poder volver a CLI si falla
4. **API versioning** - `/api/v1/` desde el inicio
5. **Type safety** - TypeScript frontend, Pydantic backend

## 💰 ECONOMÍA Y COSTOS

### Free Tier Strategy (0-10 clientes)
- **Cloudflare Workers**: 100k requests/día gratis
- **GitHub Actions**: Unlimited en repos públicos
- **Supabase**: 500MB database free
- **Vercel**: 100GB bandwidth free
- **Total**: $0/mes infraestructura

### Pricing Model
- Cliente paga: $200/mes (25 análisis incluidos)
- Costo Claude: ~$8 por análisis
- Margen bruto: 92% inicial

## 🚀 DEPLOYMENT STRATEGY

### Fase 0: Local Development
```bash
docker-compose up  # Everything local
```

### Fase 1: Zero-Cost Deployment
- API: Cloudflare Workers (100k req/day free)
- Queue: GitHub Actions (unlimited public repo)
- DB: Supabase free tier
- Frontend: Vercel hobby

### Fase 2: Scale (50+ clientes)
- Upgrade a paid tiers según necesidad
- Usar startup credits (AWS $100k, Azure $150k)

## 🛠️ HERRAMIENTAS Y SERVICIOS

### Core Services
- **Claude Agent SDK**: Orquestación de agentes
- **FastAPI**: API backend
- **Next.js**: Frontend
- **Celery**: Queue system (dev) / GitHub Actions (prod)
- **Paramiko**: SSH tunneling
- **Supabase**: Metadata storage

### Development Tools
- **Docker Compose**: Local environment
- **Pytest**: Testing
- **Turborepo**: Monorepo management
- **TypeScript**: Type safety
- **Tailwind CSS**: Styling

## 📋 CURRENT TASK FOCUS

### MIGRATION PHASES

#### Phase 1: Core Preservation ✅
- [x] Preserve all v0 code
- [x] Create adapter layer
- [x] SSH tunneling implementation

#### Phase 2: API Layer ✅
- [x] FastAPI endpoints (POST /api/analyze, GET /api/jobs/{id}/status, GET /api/jobs/{id}/results)
- [x] GET /metrics (Prometheus scrape endpoint)
- [x] WS /api/jobs/{id}/ws (WebSocket real-time progress)
- [x] Queue system (Celery + Redis)
- [x] Metadata storage (PostgreSQL en Docker, puerto 5450)

#### Phase 3: Agent Migration ✅
- [x] Adapter pattern conectando API con agentes v0
- [x] Test each agent individually
- [x] Implement fallback mechanisms
- [x] Progress streaming (WebSocket implementado)

#### Phase 4: Frontend ✅
- [x] Next.js dashboard con Tailwind CSS
- [x] AnalysisForm — formulario de conexión DB + SSH
  - Wizard 3 pasos: ERP → Conexión → Período/Confirmación
  - Guard en `onSubmit`: solo ejecuta en step 2 (nunca salta pasos por Enter/bug)
  - Selector de período con tabs: **Mes / Trimestre / Año**
  - Períodos mensuales dinámicos (últimos 24 meses en español)
  - Si se hizo "Probar conexión", los períodos se limitan al rango real de la DB (`data_from`/`data_to`)
- [x] AnalysisProgress — polling de estado del job, muestra error real del backend
- [x] ResultsDisplay — visualización de reportes
- [x] Real-time updates via WebSocket
- [x] Secure credential upload (form con campos password)
- [x] Metrics dashboard — visualización de KPIs y alertas
- [x] Quality report page — resultados del DQ Gate
- [x] Anomaly explorer — detalle de patrones detectados

#### Phase 5: Deployment 🔄
- [ ] Cloudflare Workers
- [ ] GitHub Actions workflows
- [x] Monitoring setup — Prometheus + Grafana + Loki + Promtail corriendo en Docker

#### Phase 6: Quality Pipeline ✅
- [x] **DQ Check 1** — Row count vs baseline (schema drift guard)
- [x] **DQ Check 2** — Null ratio per column (configurable threshold)
- [x] **DQ Check 3** — Type consistency (no silent cast coercions)
- [x] **DQ Check 4** — PK uniqueness enforcement
- [x] **DQ Check 5** — Referential integrity spot-check
- [x] **DQ Check 6** — Numeric range / outlier pre-screen
- [x] **DQ Check 7** — Date range plausibility (no future timestamps)
- [x] **DQ Check 8** — Freshness check via CurrencyGuard (max stale threshold)
- [x] **DQ Check +1** — REPEATABLE READ isolation snapshot for query consistency
- [x] Provenance tracking — every result tagged with source table + query hash
- [x] Auto-abort analysis when critical DQ checks fail (configurable severity)

## 🔧 COMMON COMMANDS

```bash
# Development — arranque completo
docker compose up -d                    # Start all services (detached)
python3 scripts/claude_proxy.py &       # OBLIGATORIO: proxy del CLI de Claude (puerto 8099)
docker compose ps                       # Ver estado de containers
docker compose logs -f api              # Ver logs de la API en tiempo real
docker compose down                     # Detener servicios
docker compose down -v                  # Reset completo (borra volúmenes)

# Rebuild tras cambios en requirements o Dockerfiles
docker compose build api worker
docker compose up -d --no-deps api worker

# Testing
pytest tests/               # Run tests
source venv/bin/activate && python -m valinor.adapter  # Test adapter

# Deployment
wrangler deploy            # Deploy to Cloudflare
vercel --prod             # Deploy frontend
gh workflow run analyze   # Trigger analysis

# SSH Tunnel Testing
python shared/ssh_tunnel.py test --host client.com --key ~/.ssh/id_rsa

# Verificar salud del sistema
curl http://localhost:8000/health
curl http://localhost:8099/health       # Verificar proxy Claude CLI
```

## 🔌 PUERTOS EN USO (DOCKER)

Los puertos del host fueron ajustados porque 5432 y 6379 están ocupados por servicios locales:

| Servicio    | Puerto Host | Puerto Container | URL                              |
|-------------|-------------|-----------------|----------------------------------|
| API         | 8000        | 8000            | http://localhost:8000/docs       |
| Frontend    | 3000        | 3000            | http://localhost:3000            |
| PostgreSQL  | **5450**    | 5432            | (valinor metadata DB)            |
| Redis       | **6380**    | 6379            |                                  |
| Prometheus  | 9090        | 9090            | http://localhost:9090            |
| Grafana     | 3001        | 3000            | http://localhost:3001 (admin/valinor) |
| Loki        | 3100        | 3100            | (log backend, no UI directa)     |
| Promtail    | 9080        | 9080            | http://localhost:9080/targets    |
| Claude Proxy| 8099        | —               | http://localhost:8099/health     |

**IMPORTANTE — DB del cliente (gloria/Openbravo):**
- Host: `localhost` (NO `host.docker.internal`) — la API corre con `network_mode: host`
- Puerto: `5432` (NO `5444`) — postgres local del host
- Usuario: `tad` / Password: `tad` / DB: `gloria`

## 📦 DEPENDENCIAS CLAVE (ESTADO ACTUAL)

Versiones relajadas en requirements.txt para compatibilidad con claude-agent-sdk y mcp:

- `hiredis>=2.3.2` (2.3.0 no existe en PyPI)
- `oracledb>=2.0.0` (reemplaza cx-Oracle obsoleto)
- `claude-agent-sdk` (sin pin, última versión)
- `mcp>=1.8.0` (ToolAnnotations disponible desde 1.8)
- `anthropic>=0.19.0` (sin pin por compatibilidad)
- `pydantic>=2.5.0` + `pydantic-settings>=2.5.2`
- `python-multipart>=0.0.9`
- `cachetools>=5.5.0`
- `supabase>=2.0.0`

## 🧹 TEST SUITE HYGIENE

La suite llegó a 2481 tests. Hay duplicados. La próxima vez que se toque un módulo:
1. **Pasar `/simplify`** sobre los test files del módulo — eliminar tests que verifican lo mismo con datos trivialmente distintos
2. **Consolidar con `@pytest.mark.parametrize`** en lugar de repetir funciones casi idénticas
3. **Priorizar**: integration tests > contract tests > unit triviales
4. No agregar tests en masa de nuevo sin este criterio.

## ⚠️ KNOWN ISSUES & SOLUTIONS

### Issue: "Claude CLI not available locally and proxy not reachable"
**Causa**: El proxy del CLI de Claude no está corriendo en el host.
**Solution**: `python3 scripts/claude_proxy.py &` — debe correr en el host (no en Docker). Verificar: `curl http://localhost:8099/health`. El proxy usa la sesión autenticada del browser (Plan Max), no API key.

### Issue: Análisis falla con "Connection refused" a la DB del cliente
**Causa**: El adapter tenía lógica que remapeaba `localhost:5432` → `host.docker.internal:5444`. Ya fue removida (commit actual).
**Solution**: Usar siempre `localhost` como host en el form. La API corre con `network_mode: host`, así que `localhost` dentro del contenedor ES el localhost del host. **Nunca usar `host.docker.internal` para la DB del cliente.**

### Issue: Worker crashea con "No module named 'api'"
**Causa**: `Dockerfile.worker` no copiaba el directorio `api/`. Ya corregido en `docker-compose.yml` (volumen `./api:/app/api`).
**Solution**: Ya resuelto. Si vuelve a pasar, verificar que `./api:/app/api` esté en los volúmenes del worker.

### Issue: Logs no aparecen en Grafana/Loki
**Causa**: El docker_sd_configs de Promtail usa Docker API v1.42 pero el daemon exige mínimo v1.44.
**Solution**: Promtail usa lectura directa de archivos (`/var/lib/docker/containers/*/*.log`) con `user: root`. El tag del servicio viene del log-opt `tag: "{{.Name}}"` configurado en cada servicio del compose.

### Issue: Supabase auto-pause after 7 days
**Solution**: Upgrade to Pro ($25/mes) when annoying

### Issue: GitHub Actions timeout (6 hours max)
**Solution**: Split large analyses into chunks

### Issue: Cloudflare Workers 10ms CPU limit
**Solution**: Use queues, don't process inline

### Issue: SSH key management security
**Solution**: Encrypted storage with TTL, never persist

### Issue: "Invalid period format: 2025-04" al iniciar análisis mensual
**Causa**: `parse_period()` en `core/valinor/config.py` y `shared/utils/date_utils.py` no reconocía el formato `YYYY-MM`. Igualmente `_validate_period()` en `api/main.py`.
**Solution**: Ya resuelto en los tres lugares. Formatos válidos actuales: `2025-04` (mes), `Q1-2025` (trimestre), `H1-2025` (semestre), `2025` (año).

### Issue: AnalysisForm salta directamente a "Análisis en progreso" sin mostrar paso 3
**Causa**: Botones de selección de ERP sin `type="button"` dentro del `<form>` — hacían submit al clickear. Además, el `onSubmit` de react-hook-form podía dispararse por Enter en los inputs de Step 2.
**Solution**: Ya resuelto. Todos los botones no-submit tienen `type="button"`. El handler `onSubmit` tiene guard `if (step !== 2) return` como primera línea.

## 📊 SUCCESS METRICS

- **API Response Time**: < 200ms
- **Analysis Completion**: < 15 minutes
- **Success Rate**: > 95%
- **Cost per Analysis**: < $10
- **Customer Onboarding**: < 30 minutes

## 🎯 NEXT ACTIONS (Phase 5 — lo que falta)

1. **Cloudflare Workers** — deploy edge de la API (ver `deploy/`)
2. **GitHub Actions workflows** — análisis como jobs asíncronos en CI
3. **Supabase** — migrar metadata de PostgreSQL local a Supabase (free tier)
4. **Monitoring en producción** — Prometheus + Grafana (ya funciona en Docker local)
5. **Primeros 3 clientes reales** — validar pipeline con datos reales

### Estado actual del formulario de análisis (`/new-analysis`)
El wizard funciona end-to-end:
1. Paso 1: Seleccionar ERP + nombre del cliente
2. Paso 2: Credenciales DB + "Probar conexión" (devuelve ERP detectado, tablas, rango de fechas)
3. Paso 3: Selector de período tabbed (Mes/Trimestre/Año), fechas limitadas al rango real de la DB
4. Submit → análisis en background via Celery/BackgroundTasks

> Todo lo anterior (Docker, API, pipeline, tests, frontend, monitoring) está completo. Ver `docs/AGENT_GUIDE.md` para onboarding del próximo agente.

## 📚 KEY DOCUMENTS

- `docs/AGENT_GUIDE.md`: **Leer primero** — guía completa para el próximo agente
- `docs/ARCHITECTURE.md`: Arquitectura técnica actualizada (Marzo 2026)
- `docs/SSH_TUNNELING.md`: Security implementation
- `docs/MIGRATION_PLAN.md`: Step-by-step migration
- `docs/API_REFERENCE.md`: Endpoint documentation
- `scripts/dev.sh`: Development setup script

---

*Valinor SaaS v2 - From CLI to scalable SaaS with zero data storage*
*March 2026 - Delta 4C*