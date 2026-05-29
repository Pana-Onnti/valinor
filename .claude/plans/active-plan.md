# Active Plan — Audit hardening sprint (2026-05-29)

**Última actualización:** 2026-05-29
**Branch actual:** `nicolasbaseggiodev/audit-demo-cache-race`
**develop:** `bd18d2c0` (VAL-162). Esta branch tiene VAL-164 (demo lock) + el trabajo de abajo, aún sin mergear.

---

## Sesión 2026-05-29 — Audit workflow + VAL-107 + 3 fixes backend + harness

### Qué se hizo

1. **Workflow dinámico de auditoría** (8 subsistemas en paralelo → verificación adversaria → síntesis, 32 agentes). Reconstruyó los findings perdidos del audit 2026-04-27 (los `/tmp/*.md` ya no existían) y los priorizó con verificación contra el árbol vivo. 43 findings crudos → 13 críticos/altos confirmados como reales y sin arreglar.

2. **VAL-107 — rate limiting activado y cerrado** (era Urgent, Todo):
   - `limiter` singleton movido a `api/deps.py` con key per-tenant (`_rate_limit_key`: header `X-Tenant-ID`, fallback IP) + `retry_after="delta-seconds"` (429 lleva Retry-After).
   - Decorators `@limiter.limit` en 6 endpoints: `start_analysis` 5/min, `stream_job_progress` 10/min, `nl_query` 20/min, `list_clients` 30/min, `verify_token` (portal, brute-force) 10/min, `run_demo` 10/min.
   - Tests: `TestRateLimitWiring` en `test_api_endpoints.py` — key-func + chequeo estático de presencia de decorators (robusto a import-order; el stub `_FakeLimiter` strippea decorators y poluciona `slowapi.errors` globalmente, por eso NO se testea enforcement real en-proceso).

3. **3 fixes backend quirúrgicos (verificados por el workflow):**
   - **`api/routers/jobs.py`** (HIGH): el conteo de jobs concurrentes tragaba errores Redis con `except: continue` → bypass del cap de 2 jobs. Ahora **fail-closed**: `except redis.RedisError` → log + HTTP 503. Test: `test_analyze_fails_closed_when_redis_errors_in_concurrency_check`.
   - **`core/valinor/quality/data_quality_gate.py`** (HIGH): un check FATAL crasheado se degradaba a WARNING con peso//3 → el gate emitía PROCEED en vez de HALT (fail-open en el moat anti-alucinación). Ahora un check crasheado se trata con la **peor severidad que vigila** (mapa `CRASH_SEVERITY`) + peso completo (con `_WEIGHT_ALIASES` para los 2 checks cuyo nombre de método difiere de la key) + `logger.exception`. Tests: `TestCrashedCheckFailsClosed` (3).
   - **`core/valinor/quality/data_quality_gate.py:174`** (MEDIUM): violación hexagonal `from api.metrics import DQ_CHECKS_TOTAL` (el único `from api` en todo core/). Resuelto por **inversión de dependencia**: el Domain expone `set_dq_metrics_hook(hook)`; `api/metrics.py` registra el sink al cargar. Domain ya no importa Infrastructure.

4. **Harness del entorno:**
   - `.claude/hooks/*.sh` (commit-refs-check, commit-linear-sync, plan-freshness) ahora versionados; `plan-freshness.sh` usa `$CLAUDE_PROJECT_DIR` (portable).
   - `.claude/settings.json` versionado y portable (`$CLAUDE_PROJECT_DIR` en vez de path absoluto).
   - `.claude/skills/karpathy-guidelines/` versionado.
   - `.gitignore`: añadido `.claude/scheduled_tasks.lock` + `.claude/*.lock`.
   - `scripts/claude_proxy.py`: host/timeout/token configurables por env (`CLAUDE_PROXY_HOST`, `CLAUDE_PROXY_TIMEOUT`, `CLAUDE_PROXY_TOKEN`). Defaults sin cambios (0.0.0.0, 960s — respeta VAL-162; auth opt-in).

### Findings stale / descartados (NO re-investigar)

- VAL-164 (demo cache race) — ya arreglado (commit 125ac141, `_demo_lock`).
- Audit api-2 (portal bare-except JWT→static-token) y api-4 (`body: dict`) — `portal.py` ya refactorizado a Pydantic `TokenVerifyRequest` + `Depends`. Resueltos.

---

## Backlog verificado (queue, no este sprint)

| Rank | Finding | Sev | Esfuerzo | Linear |
|------|---------|-----|----------|--------|
| 5 | Externalizar SYSTEM_PROMPTs hardcoded (inventory.py, narrators sales/controller/ceo) a `.claude/skills/*.md` | low | medium | VAL-106 |
| 6 | JWT portal en localStorage plano → httpOnly cookie (XSS) | medium | medium (backend) | — |
| 7 | `verification.py` daemon-thread query: dispose engine en timeout / statement_timeout | low | medium | — |
| 8 | `FileUpload.tsx` notify en render → useEffect | low | small | VAL-119 |
| — | Cloudflare Worker edge rate limiting (TODO, solo loggea) | medium | large | infra ticket aparte |
| — | 500-handler test coverage gap | low | small | — |

### Out of scope persistente (otros repos/productos)

- VAL-144/146/147 — research paper (repo d4c-paper).
- GRO-15/GRO-25 — SYSCOP (repo Pana-Onnti/syscop-agent, live prod).
- ANN-1 — Annatar (repo separado).
- VAL-106 (externalizar prompts), VAL-119 (catálogo versionado) — siguen Todo/Urgent.

---

## Pendientes próxima sesión

- **Mergear esta branch a develop** una vez verde la suite (excl. production E2E).
- Cerrar VAL-107 en Linear con la nota de scope real (6 endpoints + per-tenant + Retry-After + test).
- Documentar la política de crash-handling del DQ gate en `DOMAIN_MODEL.md`/`ARCHITECTURE.md` (check FATAL/CRITICAL crasheado → HALT, no degradar a WARNING).
- VAL-106 / VAL-119 siguen siendo la cola Urgent in-repo.
