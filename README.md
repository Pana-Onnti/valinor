# Valinor SaaS v2

**Business Intelligence 100% Agéntico** — De connection string a reportes ejecutivos en 15 minutos, sin almacenar datos del cliente.

---

## Inicio Rápido

```bash
cd /home/nicolas/Documents/delta4/valinor-saas
chmod +x setup.sh
./setup.sh
# Elegir opción 1 → inicia todos los servicios
```

Una vez levantado:

| Servicio    | URL                           |
|-------------|-------------------------------|
| Frontend    | http://localhost:3000         |
| API         | http://localhost:8000         |
| API Docs    | http://localhost:8000/docs    |
| Health      | http://localhost:8000/health  |

---

## Arquitectura

```
Cliente → SSH Tunnel → DB Cliente → Agentes Claude → Reportes
```

**Principios:**
- Zero Data Storage — no se almacenan datos del cliente, solo metadata y resultados
- Conexiones SSH efímeras (máximo 1 hora)
- Pipeline multi-agente: Cartographer → Query Builder → [Analyst, Sentinel, Hunter] → Narrators
- Costo operativo: ~$8 por análisis

---

## Stack

| Capa       | Tecnología                                |
|------------|-------------------------------------------|
| Backend    | FastAPI + Uvicorn                         |
| Workers    | Celery + Redis                            |
| Agentes    | Claude Agent SDK (claude-agent-sdk)       |
| Frontend   | Next.js 14 + Tailwind CSS                 |
| DB Metadata| PostgreSQL (Docker)                       |
| Cache/Queue| Redis (Docker)                            |
| SSH        | Paramiko                                  |

---

## Estructura del Proyecto

```
valinor-saas/
├── api/                    # FastAPI — endpoints REST
│   ├── main.py             # App principal, rutas
│   └── adapters/           # Puente con core Valinor v0
├── core/                   # Código Valinor v0 preservado
│   └── valinor/
│       └── agents/         # Cartographer, Analyst, Sentinel, Hunter, Narrators
├── web/                    # Next.js frontend
│   ├── app/                # App Router (layout, page, providers)
│   ├── components/         # AnalysisForm, AnalysisProgress, ResultsDisplay
│   ├── tailwind.config.js
│   └── tsconfig.json
├── worker/                 # Celery workers
├── shared/                 # SSH tunnel, storage, utils
├── deploy/
│   └── sql/init.sql        # Schema PostgreSQL (metadata only)
├── docker-compose.yml      # Entorno completo
├── Dockerfile.api          # Imagen API
├── Dockerfile.worker       # Imagen Worker
├── requirements.txt        # Dependencias Python
├── setup.sh                # Script de setup interactivo
└── .env                    # Variables de entorno (no commitear)
```

---

## Variables de Entorno

El archivo `.env` se genera automáticamente con `setup.sh`. Los valores mínimos necesarios:

```bash
# LLM Provider (elegir uno)
LLM_PROVIDER=anthropic_api
ANTHROPIC_API_KEY=sk-ant-...

# Base de datos del cliente (se configura en setup opción 2)
DB_TYPE=postgresql
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=

# SSH Tunnel (opcional, si la DB no es accesible directamente)
SSH_HOST=
SSH_PORT=22
SSH_USER=
SSH_KEY_PATH=

# Servicios internos (auto-configurados en Docker)
REDIS_URL=redis://localhost:6379
SECRET_KEY=<auto-generado>
```

---

## Puertos Docker

Los puertos del host fueron ajustados para evitar conflictos con instancias locales de PostgreSQL y Redis:

| Servicio    | Puerto Host | Puerto Container |
|-------------|-------------|-----------------|
| API         | 8000        | 8000            |
| Frontend    | 3000        | 3000            |
| PostgreSQL  | **5450**    | 5432            |
| Redis       | **6380**    | 6379            |

---

## Comandos de Gestión

```bash
# Iniciar todos los servicios (detached)
docker compose up -d

# Ver estado de los containers
docker compose ps

# Ver logs
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f web

# Reiniciar un servicio específico
docker compose restart api

# Detener todo
docker compose down

# Detener y eliminar volúmenes (reset completo)
docker compose down -v

# Rebuild tras cambios en requirements.txt o Dockerfiles
docker compose build api worker
docker compose up -d
```

---

## Pipeline de Análisis

```
POST /api/analyze
    └── ValinorAdapter
         ├── CartographerAgent    → Mapea el esquema de la BD
         ├── QueryBuilderAgent    → Genera queries optimizadas
         ├── AnalystAgent         → Análisis estadístico
         ├── SentinelAgent        → Detección de anomalías
         ├── HunterAgent          → Búsqueda de patrones ocultos
         └── NarratorAgents       → Genera reportes ejecutivos

GET /api/jobs/{job_id}/status     → Polling del progreso
GET /api/jobs/{job_id}/results    → Resultados y reportes
GET /api/jobs/{job_id}/download/{file}  → Descarga archivos
```

---

## Economía

| Concepto              | Valor         |
|-----------------------|---------------|
| Infraestructura       | $0/mes        |
| Costo por análisis    | ~$8 (Claude)  |
| Precio cliente        | $200/mes      |
| Análisis incluidos    | 25/mes        |
| Margen bruto          | ~92%          |

---

## Documentación Adicional

- [README_DEPLOYMENT.md](README_DEPLOYMENT.md) — Setup detallado, troubleshooting y fixes aplicados
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Arquitectura técnica detallada
- [docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md) — Plan de migración desde v0
- [CLAUDE.md](CLAUDE.md) — Instrucciones para el agente de desarrollo

---

*Valinor SaaS v2 — Delta 4C — Marzo 2026*
