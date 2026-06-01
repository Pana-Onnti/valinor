# Valinor SaaS — Estado del Proyecto (punto de partida)

> **Empezá acá.** Este es el estado vivo y *verificado contra el código* del proyecto,
> producido por la auditoría de cimientos del **2026-06-01** (workflow adversario de 16
> agentes). Es la fuente de verdad para arrancar la etapa nueva.
>
> - Status de issues individuales → **Linear** (canónico).
> - Plan táctico de la sesión en curso → `.claude/plans/active-plan.md`.
> - Historia por fases → `docs/ROADMAP.md`.

---

## 1. Qué es el sistema (realidad verificada)

Valinor SaaS es un **monorepo Python/FastAPI** que convierte un connection-string en
reportes ejecutivos con un swarm de agentes Claude, **sin almacenar datos del cliente**.

> ⚠️ **No es** un monorepo TypeScript/Turborepo. Cualquier doc que mencione
> `packages/@valinor/*`, `apps/api-gateway` o Cloudflare Workers describe scaffolding
> muerto archivado en `_archived/ts-scaffolding/`. El track "simple MVP" (`simple_api.py`)
> también está muerto y archivado en `_archived/simple-stack/` (devolvía datos mock).

| Capa | Dónde | Realidad |
|---|---|---|
| Engine de análisis | `core/valinor/` | pipeline (facade de 89 LOC sobre `pipeline_stages`/`_reconciliation`/`_narrator`), agentes (cartographer, analyst, sentinel, hunter, query_builder/generator, narrators), `quality/` (DQ gate + stats), `knowledge_graph`, `verification`, `discovery`, `verticals` |
| API | `api/` | FastAPI; `main.py` 308 LOC bien factorizado; routers en `routers/` + `routes/`; `deps.py` (limiter), `tenant.py`, `auth.py`, `metrics.py`; adapter en `adapters/valinor_adapter.py` (1483 LOC, candidato a split) |
| Worker | `worker/` | Celery + Redis (`celery_app.py`, `tasks.py`, `scheduler.py`) |
| Frontend | `web/` | Next.js 14 App Router (TS, Tailwind, React Query, recharts); operator console + demo público + portal cliente |
| Shared | `shared/` | `connectors/` (PostgreSQL, MySQL, Etendo, SQLite, **MSSQL**), `llm/` (provider switcher), `memory/` (ProfileStore, segmentation, alerts), `db_pool` |
| Deploy | — | **Railway** (API+Worker+Postgres+Redis) + **Vercel** (frontend) + Sentry, vía `.github/workflows/deploy.yml`. Ver `docs/INFRASTRUCTURE.md`. |

---

## 2. Bases que están sólidas (no tocar sin razón)

- **Moat anti-alucinación wired en prod**: KnowledgeGraph + VerificationEngine + Calibration
  se instancian en el path real (`run.py:211` `build_knowledge_graph`, `run.py:332` `VerificationEngine`).
- **Data Quality Gate**: 9 checks; **fail-closed** en checks crasheados (`CRASH_SEVERITY`,
  VAL-165) — un check FATAL/CRITICAL que crashea → HALT, no se degrada a WARNING.
- **Hexagonal limpio**: Domain (`core/`) ya no importa Infrastructure. La métrica del DQ gate
  usa inversión de dependencia (`set_dq_metrics_hook`; `api/metrics.py` registra el sink). No
  quedan `from api` en `core/`.
- **Rate limiting per-tenant** (VAL-107): limiter en `api/deps.py`, key `X-Tenant-ID` (fallback IP),
  6 endpoints, 429 con `Retry-After`.
- **Suite de tests**: ~3358 (~3302 en `tests/` + 56 en `security/`), colecta sin errores de import.
- **CI**: `tests.yml`/`deploy.yml`/`docker-build.yml` disparan en `master`+`develop` (VAL-51).
- **Harness `.claude/`** versionado y portable (`$CLAUDE_PROJECT_DIR`, hooks de commit/plan).

---

## 3. Issues abiertos verificados (la agenda)

Hallazgos de la auditoría 2026-06-01, verificados adversarialmente con evidencia `file:line`.
Los marcados ✅ se resolvieron en el sprint de cimientos (2026-06-01).

| Sev | Issue | Qué | Linear | Estado |
|---|---|---|---|---|
| 🔴 CRIT | Auth sin cablear | `verify_api_key` (env-gated) wired a 0/72 rutas; `TenantMiddleware` cae siempre a `DEFAULT_TENANT_ID` | VAL-108 | ✅ cableada (env-gated) en este sprint; **falta auth real de usuario en el operator console** |
| 🟠 HIGH | Onboarding SSRF | `POST /api/onboarding/test-connection` = sonda de credenciales DB sin auth, sin rate-limit, sin validación de host | VAL-108 | ✅ host-validation + rate-limit agregados |
| 🟠 HIGH | Portal 404 | Frontend llama `/api/v1/portal/*` y `/api/v1/*` pero el backend monta `/portal` y `/api` | VAL-168 | ✅ prefijos corregidos |
| 🟠 HIGH | security/ sin gate CI | CI corría `pytest tests/` → excluía 56 tests de `security/` | VAL-169 | ✅ CI corre `pytest` (incluye security/) |
| 🟠 HIGH | Prometheus cardinalidad | `request.url.path` crudo (UUIDs) como label → explosión de series | VAL-169 | ✅ usa template de ruta |
| 🟡 MED | SQL identifier injection | `entity_map` (LLM) interpolado sin `is_safe_identifier` en `data_quality_gate.py` y `queries/sales_v2.py` (live) | VAL-170 | ✅ validación agregada |
| 🟡 MED | Celery sin consumer | beat agenda `maintenance`/`analysis` pero el worker solo corre `-Q valinor` → cleanup nunca corre | VAL-169 | ✅ worker consume las 3 colas |
| 🟡 MED | pytest config dual | `pytest.ini` gana sobre el bloque en `pyproject.toml` (dead config divergente) | VAL-169 | ✅ bloque muerto eliminado |
| 🟡 MED | CORS amplio | `allow_credentials=True` + `allow_methods/headers=['*']` + localhost hardcodeado en allowlist prod | VAL-108 | ⏳ revisar al endurecer auth de usuario |
| 🟡 MED | `valinor_adapter.py` 1483 LOC | módulo más grande de `api/`, candidato a split | — | ⏳ backlog |
| ⚪ INFO | `verification.py` 1744 LOC | el verdadero heavyweight (no `pipeline.py`); decomposición candidata | — | ⏳ backlog |
| ⚪ INFO | Dead code en core | `cash_flow_forecaster`, `anomaly_explainer`, `quorum`, `calibration/` referenciados solo por tests | VAL-167 | ⏳ wire-o-archive (tiene tests acoplados) |

---

## 4. Estado de branches / release

- **Producción (`master`)** está **detrás**: `origin/develop` tenía ~13 commits sin PR a
  `master` desde 2026-04-24 (anti-alucinación VAL-161/162 + demo-lock VAL-164). El sprint de
  cimientos abre el PR `develop → master` para shipear esa deuda.
- **Política** (`CLAUDE.md`): `develop` = integración (push directo OK), `master` = producción
  vía PR desde `develop`. **No existe rama `main`** (varios docs viejos la citaban). 
- Branches locales `val-161`, `val-162` están 100% mergeadas en develop → borrables.

---

## 5. Agenda sugerida para la etapa nueva

1. **Auth de usuario real en el operator console** (`web/app/{dashboard,clients,...}`): hoy no
   envía token. `verify_api_key` está cableado y env-gated en el backend; falta el login del
   frontend y setear `VALINOR_API_KEY` en prod. (extiende VAL-108)
2. **Endurecer multi-tenant**: con `VALINOR_MULTI_TENANT=true`, `TenantMiddleware` ya rechaza en
   vez de defaultear; falta ejercer RLS (`set_tenant_db_context`) en los routers que tocan datos.
3. **Contrato tipado backend↔frontend**: generar cliente TS desde el OpenAPI para que un mismatch
   de prefijo sea error de compilación, no 404 en runtime. (sigue VAL-168)
4. **Tests de frontend**: hoy `web/` no tiene framework de test. Agregar vitest + un smoke Playwright.
5. **Lockfile de dependencias**: adoptar pip-tools (o tratar `requirements.txt` como verdad
   hand-maintained) y reconciliar `pyproject.toml`.
6. **Backlog Urgent in-repo**: VAL-106 / VAL-119 (externalizar + catalogar prompts).
7. **Limpieza de core dead code** (VAL-167): wire-o-archive con manejo de sus tests.

---

## 6. Cómo correr / verificar

```bash
docker compose up -d                  # api.main:app + worker.celery_app + web (Next.js)
python3 scripts/claude_proxy.py &     # OBLIGATORIO en host (ver DEVELOPER_GUIDE)
pytest                                 # suite completa: tests/ + security/ (~3358)
pytest tests/test_pipeline_production.py -v -s   # E2E real contra Gloria (~6 min)
```

Convención de commits: `tipo(scope): desc` + `Refs: VAL-XX` (hook valida). Domain nunca importa
Infrastructure. Nunca almacenar datos de clientes.

---

*Generado por la auditoría de cimientos — Delta 4C — 2026-06-01.*
