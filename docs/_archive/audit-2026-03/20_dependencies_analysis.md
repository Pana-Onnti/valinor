# Analisis de Dependencias — Valinor SaaS

**Fecha:** 2026-03-22
**Proyecto:** valinor-saas v2.0.0
**Python:** 3.11 (Dockerfile y pyproject.toml)
**Node:** Next.js 14 (web/)

---

## Resumen

El proyecto tiene **4 archivos de dependencias Python** (`requirements.txt`, `requirements_simple.txt`, `pyproject.toml`, mas Dockerfiles) y **1 archivo Node** (`web/package.json`). Existen inconsistencias significativas de versiones entre `requirements.txt` y `pyproject.toml`. No hay lock file Python (ni `poetry.lock`, ni `Pipfile.lock`, ni `pip-compile`), lo que representa un riesgo de reproducibilidad. El lado Node si cuenta con `package-lock.json`.

El stack combina ~50 dependencias Python directas y ~17 dependencias Node directas. Varias dependencias Python estan pinneadas a versiones de finales de 2023, lo que las hace obsoletas para marzo 2026 (2+ anos de antiguedad).

---

## Dependencias Python

### Fuentes de verdad (conflictivas)

| Archivo | Rol | Problemas |
|---------|-----|-----------|
| `pyproject.toml` | Definicion formal del proyecto | Versiones con `>=` flexibles |
| `requirements.txt` | Instalacion en Docker/CI | Versiones pinneadas (`==`) mezcladas con `>=` |
| `requirements_simple.txt` | MVP simplificado | Subset minimo, versiones `>=` |

### Inventario completo (requirements.txt como referencia principal)

#### Core Web Framework
| Paquete | Version (req.txt) | Version (pyproject) | Estado 2026 |
|---------|-------------------|---------------------|-------------|
| fastapi | ==0.109.0 | >=0.104 | OBSOLETA — FastAPI esta en ~0.115+ para 2026; 0.109 tiene ~2 anos |
| uvicorn[standard] | ==0.27.0 | >=0.24 | OBSOLETA — uvicorn ~0.32+ en 2026 |
| pydantic | >=2.5.0 | >=2.5 | OK pero deberia pinnearse a >=2.10 |
| pydantic-settings | >=2.5.2 | no listado | OK |

#### Base de datos
| Paquete | Version | Estado 2026 |
|---------|---------|-------------|
| asyncpg | ==0.29.0 | OBSOLETA — asyncpg ~0.30+ |
| psycopg2-binary | ==2.9.9 | OBSOLETA — psycopg 3.x es el estandar moderno; psycopg2 esta en mantenimiento |
| sqlalchemy | ==2.0.25 | OBSOLETA — SQLAlchemy ~2.0.36+ |
| alembic | ==1.13.0 | OBSOLETA — alembic ~1.14+ |

#### Redis y colas
| Paquete | Version | Estado 2026 |
|---------|---------|-------------|
| redis | ==5.0.1 | OBSOLETA — redis-py ~5.2+ |
| hiredis | ==2.3.2 | OBSOLETA — hiredis ~3.0+ |
| celery | ==5.3.4 | OBSOLETA — celery ~5.4+; considerar alternativas como taskiq o arq |
| flower | ==2.0.1 | OK, evoluciona lento |

#### Seguridad y SSH
| Paquete | Version | Estado 2026 | Vulnerabilidad |
|---------|---------|-------------|----------------|
| paramiko | ==3.4.0 | OBSOLETA | CVEs periodicos; actualizar a >=3.5 |
| cryptography | ==41.0.7 | **CRITICA** | **41.x tiene CVEs conocidos** (CVE-2023-49083, CVE-2024-26130, etc.); version actual ~43+ |
| python-jose | ==3.3.0 | **CRITICA** | **Proyecto abandonado desde 2022**; migrar a PyJWT o python-jose fork (authlib) |
| passlib | ==1.7.4 | **CRITICA** | **Proyecto abandonado** (ultimo release 2020); migrar a argon2-cffi o bcrypt directo |

#### LLM y agentes
| Paquete | Version (req.txt) | Version (pyproject) | Estado 2026 |
|---------|-------------------|---------------------|-------------|
| anthropic | >=0.19.0 | >=0.45.0 | **INCONSISTENCIA** — req.txt acepta 0.19+, pyproject 0.45+; anthropic SDK ~0.50+ en 2026 |
| claude-agent-sdk | sin version | >=0.1.48 | OK si se mantiene actualizado |
| mcp | >=1.8.0 | no listado | OK |
| fastmcp | >=2.2.0 | no listado | OK |
| openai | ==1.10.0 | no listado | OBSOLETA — openai SDK ~1.60+ |
| aiohttp | ==3.9.1 | no listado | OBSOLETA — aiohttp ~3.11+ |

#### Observabilidad
| Paquete | Version | Estado 2026 |
|---------|---------|-------------|
| structlog | ==24.1.0 | OBSOLETA — structlog ~24.4+ |
| python-json-logger | ==2.0.7 | OBSOLETA — python-json-logger ~3.0+ |
| sentry-sdk | ==1.39.0 | **OBSOLETA** — sentry-sdk ~2.x en 2026 (breaking change mayor) |
| prometheus-client | >=0.19.0 | OK |
| lmnr | >=0.7.0 | OK |

#### Data processing
| Paquete | Version (req.txt) | Version (pyproject) | Estado 2026 |
|---------|-------------------|---------------------|-------------|
| pandas | ==2.1.4 | >=2.2 | **INCONSISTENCIA** — req.txt pinea 2.1.4 pero pyproject pide >=2.2 |
| numpy | ==1.26.2 | no listado | OBSOLETA — numpy 2.x es estandar en 2026 |
| openpyxl | ==3.1.2 | >=3.1 | OBSOLETA — openpyxl ~3.2+ |
| vanna | >=0.7.0 | no listado | OK |
| dlt | >=1.0.0 | no listado | OK |
| scipy | >=1.11.0 | no listado | OK pero deberia ser >=1.14 |
| statsmodels | >=0.14.0 | no listado | OK |

#### Dev tools
| Paquete | Version | Estado 2026 |
|---------|---------|-------------|
| pytest | ==7.4.3 | OBSOLETA — pytest ~8.3+ |
| pytest-asyncio | ==0.21.1 | OBSOLETA — pytest-asyncio ~0.24+ |
| black | ==23.12.0 | OBSOLETA — black ~24.10+; considerar ruff format |
| ruff | ==0.1.9 | OBSOLETA — ruff ~0.8+ en 2026; evoluciona rapido |
| mypy | ==1.8.0 | OBSOLETA — mypy ~1.13+ |
| pre-commit | ==3.6.0 | OBSOLETA — pre-commit ~4.0+ |

#### Otros
| Paquete | Version | Estado 2026 |
|---------|---------|-------------|
| supabase | >=2.0.0 | OK |
| httpx | >=0.27.0 | OK |
| python-dotenv | ==1.0.0 | OK, estable |
| tenacity | ==8.2.3 | OBSOLETA — tenacity ~9.0+ |
| reportlab | >=4.0.0 | OK |
| pymysql | ==1.1.0 | OBSOLETA — pymysql ~1.1.1+ |
| pyodbc | ==5.0.1 | OBSOLETA — pyodbc ~5.2+ |
| oracledb | ==2.3.0 | OBSOLETA — oracledb ~2.5+ |

---

## Dependencias Node (web/package.json)

### Dependencies (produccion)
| Paquete | Version | Estado 2026 |
|---------|---------|-------------|
| next | 14.1.0 | **OBSOLETA** — Next.js 15.x es estable en 2026; 14.1 tiene ~2 anos |
| react | ^18.2.0 | **OBSOLETA** — React 19.x es estable en 2026 |
| react-dom | ^18.2.0 | **OBSOLETA** — igual que React |
| @tanstack/react-query | ^5.0.0 | OK, rango ^5 captura actualizaciones |
| axios | ^1.6.0 | OK, pero considerar fetch nativo con Next.js |
| clsx | ^2.1.0 | OK |
| date-fns | ^3.0.0 | OK — date-fns 3.x es actual |
| framer-motion | ^10.16.0 | **OBSOLETA** — framer-motion ~11.x+ en 2026; rango ^10 no captura 11.x |
| lucide-react | ^0.300.0 | OBSOLETA — lucide-react usa semver calendarizado, versiones mucho mayores en 2026 |
| react-hook-form | ^7.48.0 | OK |
| react-hot-toast | ^2.4.1 | OK, estable |
| react-markdown | ^10.1.0 | OK |
| recharts | ^2.10.0 | OK |
| tailwind-merge | ^2.2.0 | OK |
| zod | ^3.22.0 | OK, ^3 captura actualizaciones |
| zustand | ^4.4.0 | **OBSOLETA** — zustand 5.x en 2026; ^4 no captura 5.x |
| @hookform/resolvers | ^3.3.0 | OK |
| @tailwindcss/typography | ^0.5.19 | OK, pero Tailwind 4.x cambia el modelo de plugins |

### DevDependencies
| Paquete | Version | Estado 2026 |
|---------|---------|-------------|
| typescript | ^5.3.0 | OK — ^5 captura 5.x |
| tailwindcss | ^3.4.0 | **OBSOLETA** — Tailwind CSS 4.x es estable en 2026 |
| eslint | ^8.55.0 | **OBSOLETA** — ESLint 9.x con flat config es estandar en 2026 |
| postcss | ^8.4.32 | OK |
| autoprefixer | ^10.4.16 | OK |
| @types/node | ^20.10.0 | OBSOLETA — Node 22.x types son estandar |
| @types/react | ^18.2.0 | OBSOLETA si se migra a React 19 |
| eslint-config-next | 14.1.0 | OBSOLETA — pinneado a Next 14.1 |

---

## Analisis de Vulnerabilidades

### Criticas (accion inmediata requerida)

1. **cryptography==41.0.7** — Multiples CVEs conocidos. La version 41.x fue EOL. Actualizar a >=43.0.0.
2. **python-jose==3.3.0** — Proyecto abandonado. Ultima actividad 2022. Vulnerabilidades conocidas en manejo de JWT. Migrar a `PyJWT` o `authlib`.
3. **passlib==1.7.4** — Proyecto abandonado. Ultimo release octubre 2020. Sin parches de seguridad en 5+ anos. Migrar a `argon2-cffi` + `bcrypt`.

### Altas

4. **aiohttp==3.9.1** — CVEs en versiones <3.9.4 (HTTP request smuggling, CRLF injection).
5. **sentry-sdk==1.39.0** — La v1.x esta en mantenimiento; migrar a 2.x.
6. **Next.js 14.1.0** — Multiples CVEs parcheados en 14.2+ (Server Actions, SSRF).

### Medias

7. **paramiko==3.4.0** — Vulnerabilidades conocidas en versiones anteriores a 3.4.1.
8. **openai==1.10.0** — Versiones antiguas pueden filtrar headers de auth en redirects.
9. **numpy==1.26.2** — numpy 1.x esta en modo de mantenimiento; numpy 2.x tiene fixes de seguridad.

---

## Dependencias Obsoletas (resumen cuantitativo)

| Categoria | Total | Obsoletas | % Obsoletas |
|-----------|-------|-----------|-------------|
| Python (req.txt pinneadas) | ~42 | ~30 | ~71% |
| Node dependencies | 17 | 6 | ~35% |
| Node devDependencies | 7 | 4 | ~57% |
| **Total** | **~66** | **~40** | **~61%** |

---

## Lock Files

| Tipo | Existe | Riesgo |
|------|--------|--------|
| `package-lock.json` (Node) | Si (`web/package-lock.json`) | Bajo — builds reproducibles |
| `poetry.lock` (Python) | **No** | **Alto** — builds no reproducibles |
| `Pipfile.lock` (Python) | **No** | **Alto** |
| `pip-compile` output (Python) | **No** | **Alto** |

**Impacto:** Sin lock file Python, cada `pip install -r requirements.txt` puede resolver sub-dependencias diferentes. Las dependencias con `>=` (anthropic, mcp, httpx, etc.) pueden instalar versiones incompatibles entre si en diferentes momentos.

---

## Fortalezas

1. **Stack moderno y coherente** — FastAPI + Celery + Redis + Supabase es una arquitectura probada para SaaS.
2. **Separacion clara** — `pyproject.toml` como fuente de verdad, `requirements.txt` para Docker, `requirements_simple.txt` para MVP.
3. **Observabilidad integrada** — Sentry, Prometheus, structlog, lmnr forman una buena base de monitoreo.
4. **Frontend moderno** — Next.js + React Query + Zustand + Tailwind + Zod es un stack frontend solido.
5. **Dependencias opcionales bien organizadas** — Drivers de BD como extras opcionales en pyproject.toml.
6. **Lock file Node presente** — `web/package-lock.json` garantiza builds reproducibles del frontend.
7. **Tipado estricto** — TypeScript, Pydantic v2, mypy configurados.
8. **Tooling de calidad** — ruff, black, pre-commit, pytest con coverage.

---

## Debilidades

1. **Sin lock file Python** — Riesgo critico de reproducibilidad. Builds pueden fallar silenciosamente.
2. **Inconsistencias entre archivos** — `requirements.txt` y `pyproject.toml` declaran versiones diferentes para `anthropic`, `pandas`, `structlog` y otros. Esto causa confusion sobre que version realmente se usa.
3. **3 dependencias de seguridad abandonadas** — `python-jose`, `passlib`, y `cryptography` en version vulnerable representan riesgo directo.
4. **71% de dependencias Python obsoletas** — La mayoria estan pinneadas a versiones de diciembre 2023, con 2+ anos de antiguedad.
5. **psycopg2-binary en produccion** — La documentacion de psycopg2 explicitamente desaconseja `psycopg2-binary` en produccion. Deberia usarse `psycopg2` compilado o migrar a `psycopg` (v3).
6. **Dev dependencies mezcladas con produccion** — `requirements.txt` incluye pytest, black, flake8, ruff, mypy en el mismo archivo que las dependencias de produccion. Esto infla la imagen Docker.
7. **Python 3.11 vs 3.10** — El pyproject.toml requiere `>=3.11` pero el venv local usa Python 3.10 (`venv/lib/python3.10/`), lo que puede causar incompatibilidades.
8. **Duplicacion de linters** — `black` + `flake8` + `ruff` son redundantes. Ruff reemplaza a ambos.
9. **openai pinneado pero posiblemente no usado** — Si el stack es Anthropic-first, la dependencia de openai agrega superficie de ataque innecesaria.

---

## Recomendaciones 2026

### Prioridad 1 — Seguridad (inmediato)

| Accion | Detalle |
|--------|---------|
| Reemplazar `python-jose` | Migrar a `PyJWT>=2.9.0` o `authlib>=1.3.0` |
| Reemplazar `passlib` | Migrar a `argon2-cffi>=23.1.0` + `bcrypt>=4.1.0` directo |
| Actualizar `cryptography` | Subir a `>=43.0.0` (corrige CVEs criticos) |
| Actualizar `aiohttp` | Subir a `>=3.10.0` |
| Actualizar `Next.js` | Subir a `>=14.2.20` minimo, idealmente evaluar 15.x |

### Prioridad 2 — Reproducibilidad (esta semana)

| Accion | Detalle |
|--------|---------|
| Adoptar `pip-tools` o `uv` | Generar `requirements.lock` con `pip-compile` o `uv lock` |
| Unificar fuente de verdad | Usar `pyproject.toml` como unica fuente; generar requirements.txt via pip-compile |
| Separar dev de prod | Crear `requirements-dev.txt` separado o usar extras `[dev]` de pyproject.toml en Docker |
| Resolver inconsistencia Python 3.10 vs 3.11 | Alinear venv local con la version del Dockerfile |

### Prioridad 3 — Actualizacion de dependencias (Q2 2026)

| Accion | Detalle |
|--------|---------|
| Actualizar FastAPI | A >=0.115.0 (mejoras de performance, Pydantic v2 optimizado) |
| Actualizar pandas + numpy | pandas >=2.2, numpy >=2.0 (breaking changes en numpy 2.x, requiere testing) |
| Migrar psycopg2 a psycopg 3 | psycopg (v3) es async-native y el futuro del ecosistema PostgreSQL en Python |
| Actualizar sentry-sdk a 2.x | Breaking change; requiere revision de integraciones |
| Actualizar React a 19.x | Evaluar React 19 + Next.js 15; requiere revision de Server Components |
| Eliminar linters redundantes | Quitar `black` y `flake8`, usar solo `ruff format` + `ruff check` |
| Evaluar celery vs taskiq/arq | Celery es pesado; taskiq o arq son alternativas mas modernas y ligeras |
| Actualizar Tailwind a 4.x | Tailwind 4 cambia el modelo de configuracion; requiere migracion |
| Actualizar ESLint a 9.x | Migrar a flat config |
| Evaluar zustand 5.x | API mejorada, pero breaking changes |

### Prioridad 4 — Limpieza (backlog)

- Eliminar `openai` si no se usa activamente (reducir superficie de ataque).
- Eliminar `flower` si hay alternativas de monitoreo via Prometheus/Grafana.
- Considerar `uv` como reemplazo de pip (10-100x mas rapido, lock files nativos).
- Agregar `npm audit` y `pip-audit` al CI/CD pipeline.
- Evaluar migracion a monorepo con `turborepo` si el frontend crece.
