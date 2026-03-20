# Valinor SaaS v2 — Guía Completa de Setup y Deployment

## Prerequisitos

| Herramienta     | Versión Mínima | Notas                                      |
|-----------------|----------------|--------------------------------------------|
| Python          | 3.10+          | Se usa 3.10.12 en producción               |
| Node.js         | 18+            | Se usa 20.x                               |
| Docker Engine   | 29.x           | API mínima requerida: 1.44                 |
| Docker Compose  | v2.25+         | Ver fix de versión abajo                   |
| Buildx          | v0.17+         | Ver fix de versión abajo                   |

---

## Setup Inicial (Primera Vez)

### 1. Clonar y posicionarse

```bash
cd /home/nicolas/Documents/delta4/valinor-saas
```

### 2. Ejecutar el script de setup

```bash
chmod +x setup.sh
./setup.sh
```

El script:
1. Verifica Python, Node, Docker
2. Crea directorios: `ssh_keys/`, `logs/`, `temp/`, `deploy/sql/`
3. Crea y activa virtualenv Python en `venv/`
4. Instala dependencias Python (`requirements.txt`)
5. Instala dependencias Node en `web/`
6. Genera `.env` con claves secretas aleatorias
7. Genera `deploy/sql/init.sql` (schema de metadata)
8. Crea la red Docker `valinor-network`
9. Menú interactivo → **elegir opción 1** para levantar servicios

### 3. Configurar API key

Editar `.env` y poner tu Anthropic API key:

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

### 4. Verificar que todo está corriendo

```bash
docker compose ps
curl http://localhost:8000/health
```

Resultado esperado:
```json
{"status":"healthy","timestamp":"...","components":{"redis":"healthy","storage":"healthy"},"version":"1.0.0"}
```

---

## Iniciar / Detener Servicios

### Iniciar

```bash
# Desde el directorio raíz del proyecto
docker compose up -d
```

### Verificar estado

```bash
docker compose ps
```

Debe mostrar todos los servicios en estado `healthy` o `Up`:

```
NAME                      STATUS
valinor-saas-api-1        Up (healthy)
valinor-saas-postgres-1   Up (healthy)
valinor-saas-redis-1      Up (healthy)
valinor-saas-web-1        Up
valinor-saas-worker-1     Up
```

### Ver logs en tiempo real

```bash
docker compose logs -f api        # API FastAPI
docker compose logs -f worker     # Celery worker
docker compose logs -f web        # Next.js frontend
docker compose logs -f postgres   # PostgreSQL
```

### Detener

```bash
docker compose down               # Para y elimina containers (preserva volúmenes)
docker compose down -v            # Reset completo: elimina también volúmenes/datos
```

### Reiniciar un servicio

```bash
docker compose restart api
```

### Rebuild tras cambios en código/dependencias

```bash
docker compose build api worker web
docker compose up -d
```

---

## URLs de los Servicios

| Servicio        | URL                          | Notas                        |
|-----------------|------------------------------|------------------------------|
| Frontend        | http://localhost:3000        | Next.js app                  |
| API             | http://localhost:8000        | FastAPI                      |
| API Docs        | http://localhost:8000/docs   | Swagger UI                   |
| Health Check    | http://localhost:8000/health | Estado de los componentes    |
| PostgreSQL      | localhost:**5450**           | Usuario: valinor / valinor_secret |
| Redis           | localhost:**6380**           | Sin auth en dev              |

> Los puertos 5450 y 6380 se usan porque 5432 y 6379 ya están ocupados por instancias locales.

---

## Conectar Base de Datos del Cliente (Gloria)

```bash
# Con el venv activado
source venv/bin/activate
python3 scripts/setup_gloria_connection.py
```

Necesitarás:
- Host/puerto/usuario SSH
- Clave SSH privada (se guarda en `ssh_keys/`, nunca se commitea)
- Credenciales de la base de datos del cliente
- Tipo de BD (PostgreSQL, MySQL, SQL Server, Oracle)

---

## Hacer un Análisis via API

```bash
# Iniciar análisis
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "db_config": {
      "type": "postgresql",
      "host": "cliente.ejemplo.com",
      "port": 5432,
      "database": "mi_bd",
      "user": "usuario",
      "password": "secreto"
    }
  }'
# Respuesta: {"job_id": "abc123..."}

# Consultar estado
curl http://localhost:8000/api/jobs/abc123/status

# Obtener resultados
curl http://localhost:8000/api/jobs/abc123/results
```

---

## Fixes Aplicados Durante el Setup Inicial

Esta sección documenta todos los problemas encontrados y cómo se resolvieron, para facilitar setups futuros en otras máquinas.

### Fix 1 — hiredis==2.3.0 no existe

**Error:** `ERROR: Could not find a version that satisfies the requirement hiredis==2.3.0`

**Causa:** La versión 2.3.0 nunca fue publicada en PyPI (saltó de 2.2.3 a 2.3.2).

**Fix en `requirements.txt`:**
```
hiredis==2.3.2
```

---

### Fix 2 — Docker Compose demasiado antiguo (API version 1.43)

**Error:** `client version 1.43 is too old. Minimum supported API version is 1.44`

**Causa:** Docker Compose v2.23.3-desktop.2 (bundled con Docker Desktop) usa API version 1.43, pero el Docker Engine 29.x requiere mínimo 1.44.

**Fix:** Instalar la versión latest en el directorio de plugins del usuario:

```bash
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
  -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
docker compose version  # debe mostrar v5.x o superior
```

---

### Fix 3 — Buildx demasiado antiguo

**Error:** `compose build requires buildx 0.17.0 or later`

**Causa:** Buildx v0.12.0-desktop.2 demasiado antiguo para docker compose build.

**Fix:**

```bash
curl -fsSL "https://github.com/docker/buildx/releases/download/v0.32.1/buildx-v0.32.1.linux-amd64" \
  -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx
docker buildx version  # debe mostrar v0.32.1 o superior
```

---

### Fix 4 — Dockerfile.dev del frontend no existía

**Error:** `failed to read dockerfile: open Dockerfile.dev: no such file or directory`

**Causa:** `docker-compose.yml` referencia `web/Dockerfile.dev` pero el archivo no había sido creado.

**Fix:** Crear `web/Dockerfile.dev`:

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]
```

---

### Fix 5 — cx-Oracle==8.3.0 falla el build (pkg_resources)

**Error:** `ModuleNotFoundError: No module named 'pkg_resources'`

**Causa:** `cx-Oracle==8.3.0` es el driver Oracle antiguo y obsoleto. Su `setup.py` legacy llama `import pkg_resources` (de setuptools), pero las imágenes modernas de Python no incluyen setuptools por defecto y la versión de setuptools que pip instala en el build env aislado tiene incompatibilidades.

**Fix:** Reemplazar `cx-Oracle==8.3.0` por el driver oficial actual en `requirements.txt`:
```
oracledb==2.3.0
```

---

### Fix 6 — claude-agent-sdk no estaba en requirements

**Error:** `ModuleNotFoundError: No module named 'claude_agent_sdk'`

**Causa:** El código en `core/valinor/agents/` usa el SDK de agentes de Claude, pero no estaba declarado en `requirements.txt`.

**Fix:** Agregar a `requirements.txt`:
```
claude-agent-sdk
mcp>=1.8.0
```

> **Nota:** `mcp` (Model Context Protocol) debe ser `>=1.8.0` porque `claude-agent-sdk` importa `ToolAnnotations` desde `mcp.types`, que solo existe a partir de la versión 1.8.

---

### Fix 7 — Conflictos de versiones en requirements.txt

Al agregar `claude-agent-sdk` y `mcp>=1.8.0`, surgieron múltiples conflictos con versiones pinadas. Solución: relajar las versiones conflictivas.

| Paquete              | Antes          | Después            |
|----------------------|----------------|--------------------|
| `httpx`              | `==0.26.0`     | `>=0.26.0`         |
| `pydantic`           | `==2.5.0`      | `>=2.5.0`          |
| `pydantic-settings`  | `==2.1.0`      | `>=2.5.2`          |
| `python-multipart`   | `==0.0.6`      | `>=0.0.9`          |
| `cachetools`         | `==5.3.2`      | `>=5.5.0`          |
| `anthropic`          | `==0.19.0`     | `>=0.19.0`         |

---

### Fix 8 — supabase no estaba en requirements

**Error:** `ModuleNotFoundError: No module named 'supabase'`

**Causa:** `shared/storage.py` importa `supabase` pero no estaba declarado.

**Fix:** Agregar a `requirements.txt`:
```
supabase>=2.0.0
```

---

### Fix 9 — Puertos 5432 y 6379 ya en uso

**Error:** `failed to bind host port 0.0.0.0:5432/tcp: address already in use`

**Causa:** El sistema ya tiene instancias de PostgreSQL (puertos 5432, 5433, 5434, 5435, 5436) y Redis (puerto 6379) corriendo localmente.

**Fix en `docker-compose.yml`:**
```yaml
postgres:
  ports:
    - "5450:5432"   # host:container

redis:
  ports:
    - "6380:6379"   # host:container
```

---

### Fix 10 — deploy/sql/init.sql creado como directorio

**Error:** `could not read from input file: Is a directory`

**Causa:** Docker montó el volumen `./deploy/sql/init.sql:/docker-entrypoint-initdb.d/init.sql` antes de que el archivo existiera, creando un directorio en su lugar.

**Fix:**
```bash
rm -rf deploy/sql/init.sql
# Luego crear el archivo manualmente (ya está en el repo)
docker compose down -v  # limpiar volúmenes
docker compose up -d    # reiniciar con el archivo correcto
```

---

### Fix 11 — PYTHONPATH incompleto (módulo adapters no encontrado)

**Error:** `ModuleNotFoundError: No module named 'adapters'`

**Causa:** El módulo `adapters` está en `/app/api/adapters/`, pero `PYTHONPATH` solo incluía `/app`, no `/app/api`.

**Fix en `Dockerfile.api` y `Dockerfile.worker`:**
```dockerfile
ENV PYTHONPATH=/app:/app/api:$PYTHONPATH
```

---

### Fix 12 — curl no disponible en el container (healthcheck fallaba)

**Error:** `/bin/sh: 1: curl: not found` (en el healthcheck de Docker)

**Causa:** El `HEALTHCHECK` del `Dockerfile.api` usa curl para hacer GET a `/health`, pero curl no estaba instalado.

**Fix en `Dockerfile.api`:**
```dockerfile
RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev openssh-client curl \
    && rm -rf /var/lib/apt/lists/*
```

---

### Fix 13 — Componentes React faltantes en el frontend

**Error:** `Module not found: Can't resolve '@/components/AnalysisForm'`

**Causa:** `web/app/page.tsx` importa tres componentes que no existían, y tampoco existían `providers.tsx`, `globals.css`, `tailwind.config.js`, ni `postcss.config.js`.

**Fix:** Crear los archivos faltantes:

```
web/
├── app/
│   ├── globals.css          # Directivas Tailwind
│   └── providers.tsx        # QueryClient + Toaster
├── components/
│   ├── AnalysisForm.tsx     # Formulario de conexión DB
│   ├── AnalysisProgress.tsx # Polling de progreso del job
│   └── ResultsDisplay.tsx   # Visualización de reportes
├── tailwind.config.js       # Configuración Tailwind
└── postcss.config.js        # Plugin autoprefixer
```

---

### Fix 14 — tsconfig.json sin path alias @/

**Causa:** Next.js necesita `baseUrl` y `paths` en `tsconfig.json` para resolver el alias `@/`.

**Fix en `web/tsconfig.json`:**
```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./*"]
    }
  }
}
```

---

## Troubleshooting General

### La API no levanta

```bash
# Ver logs detallados
docker compose logs api

# Errores comunes:
# - "No module named X" → agregar X a requirements.txt y rebuild
# - "Address already in use" → cambiar puerto en docker-compose.yml
# - "cannot import name Y from mcp.types" → mcp versión < 1.8, actualizar requirements.txt
```

### El frontend muestra error 500

```bash
docker compose logs web
# Buscar "Module not found" → el componente o archivo referenciado no existe
```

### PostgreSQL no arranca

```bash
docker compose logs postgres
# "Is a directory" → deploy/sql/init.sql es un directorio, no un archivo
# Fix: rm -rf deploy/sql/init.sql && docker compose down -v && docker compose up -d
```

### Rebuild forzado de una imagen

```bash
docker compose build --no-cache api
docker compose up -d --no-deps api
```

### Conectar al PostgreSQL de Docker directamente

```bash
# Desde el host (puerto 5450)
psql -h localhost -p 5450 -U valinor -d valinor_metadata

# Desde dentro del container
docker compose exec postgres psql -U valinor -d valinor_metadata
```

### Conectar al Redis de Docker directamente

```bash
# Desde el host (puerto 6380)
redis-cli -p 6380 ping

# Desde dentro del container
docker compose exec redis redis-cli ping
```

---

## Deployment en Producción (Fase 1 — Zero Cost)

### Cloudflare Workers (API gateway)

```bash
# Instalar Wrangler
npm install -g wrangler

# Login
wrangler login

# Deploy
cd deploy/
wrangler deploy

# Configurar secretos
wrangler secret put ANTHROPIC_API_KEY
```

### Vercel (Frontend)

```bash
cd web/
npx vercel --prod
```

### Supabase (Metadata DB en producción)

1. Crear proyecto en supabase.com
2. Ejecutar `deploy/sql/init.sql` en el SQL editor
3. Agregar `SUPABASE_URL` y `SUPABASE_KEY` al `.env`

---

## Checklist de Verificación Post-Setup

```bash
# 1. Containers corriendo
docker compose ps

# 2. API healthy
curl http://localhost:8000/health
# Esperado: {"status":"healthy",...}

# 3. Frontend accesible
curl -s http://localhost:3000 | grep -o "DOCTYPE"
# Esperado: DOCTYPE

# 4. PostgreSQL accesible
docker compose exec postgres pg_isready -U valinor
# Esperado: /var/run/postgresql:5432 - accepting connections

# 5. Redis accesible
docker compose exec redis redis-cli ping
# Esperado: PONG

# 6. API docs accesibles
curl -s http://localhost:8000/docs | grep -o "swagger"
# Esperado: swagger
```

---

*Valinor SaaS v2 — Delta 4C — Marzo 2026*
