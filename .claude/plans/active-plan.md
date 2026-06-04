# Active Plan — Worker fix + moat analysis + tenant-isolation foundation (2026-06-04)

**Última actualización:** 2026-06-04
**Rama de integración:** `develop` == `master` (niveladas; prod al día).
**Estado vivo canónico:** `docs/PROJECT_STATE.md`. Tesis de moat: memoria `project_moat_thesis`.

---

## ✅ Completado y en PRODUCCIÓN

- **VAL-169** — Worker corre Celery en prod por primera vez (vivía un placeholder nginx). Orquestador reubicado `api/`→`core/` + `Dockerfile.worker` PYTHONPATH `+/app/core`. Verificado en logs.
- **VAL-172** — webhooks `api/`→`shared/` (worker los firea en prod).
- **VAL-173** — sacado el job rojo de staging del CI.
- **VAL-174 (parcial, aditivo, inerte)** — `nl_query` hardening (tenant del auth + DSN inline gateado/SSRF); **A1** fundación de identidad (alembic `004` + `shared/credentials.py`); **VAL-176** mecanismo Redis de aislamiento (helper + `get_job_for_tenant`, con fix de un IDOR que cazó la review). Nada de esto activa aislamiento todavía.

Shippeado a master vía PR #47 (VAL-169) y PR #49 (el resto). CI verde.

- **VAL-175 (Done 2026-06-04, en `develop`)** — el benchmark de discovery ya mide el moat: modo ablation `ensemble_hinted` con el `argentina_gestion.yaml` real (fix del naming mismatch), `hint_pack_deltas()` + gate `compare_hint_delta_to_baseline()` (recall+precision, fail-closed), baseline 6→9. **Moat datapoint: `gloria_no_fks` ΔR +0.125**; full/obfuscated Δ=0 (honesto). Review adversarial (workflow 5 dims) → 3 capas fail-closed. DoD #5 (ERP real) diferido a VAL-121/VAL-145.
- **VAL-122 (parcial, en `develop`)** — fix del prescan del Cartographer para MSSQL: `_build_probe_sql()` dialect-aware (T-SQL `TOP`/`[brackets]`/`NVARCHAR`, no `::text`/`LIMIT`/`GROUP BY 2`) + schema default `dbo`. Era un bug que daba cero hints de discovery sobre cualquier ERP en SQL Server. Falta (cuando se priorice SQL Server): test E2E live contra SQL Server Docker, reconciliar pyodbc↔pymssql (onboarding usa pyodbc, conector pymssql), service en docker-compose.

## 🔄 En progreso / diferido

- **VAL-174 epic — DIFERIDO A LO ÚLTIMO** (decisión 2026-06-04: producto/ontología primero; alinea con el moat real). Sub-issues specced + gateados: **VAL-176** (B wiring), **VAL-177** (A2 enforcement), **VAL-178** (D RLS), **VAL-179** (E tests E2E), **VAL-118** (vault cifrado). Requieren **entorno multi-tenant real** (PG+Supabase+Redis) para los 4 E2E adversarios.
- **Track de cliente single-tenant (ex-VAL-121) — DESCOPED** (2026-06-04): el deal externo no avanzó. Se sacó del repo todo lo cliente-específico (ver commit de cleanup). VAL-121 cancelado en Linear; VAL-122 (SQL Server) vuelve a Backlog como capacidad genérica a validar más adelante.

## ⏳ Próximo (el moat real)

1. **VAL-163** — A/B del Number Registry (accuracy, hoy *downgraded*).
2. **VAL-145 / VAL-114 / VAL-117** — eval empírico de discovery, eval LLM offline, golden datasets multi-cliente. (El "primer datapoint de generalización cross-ERP" ya no depende de un cliente externo — se hará con un golden dataset de segunda familia ERP cuando se priorice.)
3. **VAL-175 ✅** — métrica de moat (hint-pack ablation) ya en `develop`; deja la generalización cross-ERP como plug-in (inyectar un segundo hint pack / variante).

_VAL-175 completado — movido a "Completado" arriba._

## Notas / gotchas de la sesión

- `railway up --detach` da **falso-verde** (no espera el build) — verificar prod por `railway logs`/`status`, no por el check de GitHub.
- master pide 1 approval → self-PRs necesitan `gh pr merge --admin`.
- El path real de metadata en prod = **Supabase REST anon-key**, NO aislable con filtros app-side (`.eq`) — necesita RLS de Supabase + JWT per-tenant.
- Hook de commit: sólo lintea `^(api|shared)/`; exige `Refs: VAL-XX`.
