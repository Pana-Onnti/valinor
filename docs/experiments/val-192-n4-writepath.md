# VAL-192 N4 — Write-path con revisión humana + procedencia

**Fecha:** 2026-06-14 · **Estado:** ✅ **CERRADO** (5 slices: seam B + seam A + audit + frontend + flip del default). Review-on es ahora el **default** (`VALINOR_MEMORY_REVIEW=0` restaura el auto-write legacy). Validado end-to-end en vivo.

## El problema que resuelve

Hoy el aprendizaje entre runs es **write-directo**: `RefinementAgent` corre en background y escribe `profile.refinement` sin revisión (`valinor_adapter.py:_run_refinement_background`). El riesgo que nombra la épica: *el conocimiento compone, pero la basura también*. Una alucinación del run 1 sobrevive a run 5, **auto-escala a CRITICAL** y se cita con autoridad en run 6. N4 corta ese loop: ningún learning entra a la memoria sin **procedencia** y **aprobación humana explícita**.

## El motion (capturar → proponer → revisar → merge)

```
run → RefinementAgent propone → [VALINOR_MEMORY_REVIEW=1] →
  PendingRefinement (con procedencia) en profile.pending_refinements (NO activo)
  → operador revisa (GET) → approve (merge a profile.refinement) | reject (archiva)
```

- **Sin el flag** (default): el comportamiento legacy de write-directo se mantiene — prod byte-idéntico.
- **Con el flag**: la propuesta se **estaciona** con procedencia; `profile.refinement` (lo que consumen los agentes en el próximo run) **solo** cambia por un approve explícito.

## Procedencia (obligatoria, linteada en CI)

Cada `PendingRefinement` lleva: `run_id`, `client_tag`, `generated_at`, `source_findings_ids`, `confidence` + `confidence_label`. La confianza se reusa de `ProvenanceRegistry.run_confidence()` (media de confianza por finding, ya existente — no se reinventó). El linter `scripts/provenance_linter.py` falla el build si cualquier propuesta carece de la procedencia requerida.

## Cambios (cambio quirúrgico)

| Archivo | Qué |
|---|---|
| `shared/memory/client_profile.py` | `PendingRefinement` dataclass + campo `pending_refinements` (round-trip en to_dict/from_dict, backward-compat) + métodos `add_/get_/approve_/reject_pending_refinement` + helpers `memory_review_enabled`, `build_pending_refinement`, `extract_finding_ids`, `has_provenance` |
| `core/valinor/quality/provenance.py` | `ProvenanceRegistry.run_confidence()` (reusable) |
| `core/adapters/valinor_adapter.py` | intercepta el seam B (`_run_refinement_background`): si el flag → estaciona con procedencia; si no → auto-write legacy |
| `api/routers/clients.py` | 3 endpoints: `GET .../pending-refinements`, `POST .../{id}/approve`, `POST .../{id}/reject` |
| `scripts/provenance_linter.py` | gate de CI |
| `tests/test_n4_writepath.py` | 25 tests (18 al primer write, +7 tras la revisión adversarial): stage-no-activa, approve-merge, reject-archiva, doble-review bloqueado, procedencia obligatoria, flag gating, round-trip, linter, intercepción del adapter (flag on/off) |

## Revisión

API/CLI primero (decisión del usuario): el frontend/Linear quedan como consumidores aditivos de la misma cola + endpoints.

**Review adversarial multi-dimensión (4 lentes, 24 hallazgos confirmados → triados):** encontró un **blocker real** — `from_dict` dejaba que `"pending_refinements": null` (corrupción/migración) sobrescribiera el `default_factory` → `None` → crash de todos los métodos. **Arreglado** con guard en `from_dict` (skip de None) + normalización en `__post_init__`. Otros fixes: el adapter solo estaciona **con** procedencia (si falta → fallback a auto-write, no estaciona basura que el linter rechazaría); approve documentado como *replace* (misma semántica que el auto-write legacy, no merge); guard de procedencia en el endpoint approve (400). 25 tests (todos verdes, order-independent — se corrigió pollution de loop asyncio y de mock de `ValinorAdapter`).

## Reproducir

```bash
# estacionar (en un run con el flag):  VALINOR_MEMORY_REVIEW=1 python -m valinor.run ...
# revisar:
curl localhost:8000/api/clients/Gloria_SA/pending-refinements
curl -XPOST localhost:8000/api/clients/Gloria_SA/pending-refinements/<id>/approve
# lint CI:
python scripts/provenance_linter.py   # escanea /tmp/valinor_profiles/*.json
```

## Slice 2 — Seam A (findings) ✅ 2026-06-14

El write-directo de findings vive en `profile_extractor.update_from_run`. No todo se gatea: el tracking rutinario (new/resolved/runs_open, weights, KPIs) es **observación** y sigue automático (la UI de deltas lo necesita; no hereda autoridad). Lo que sí se trata con el motion es lo que **gana autoridad sin base**:

1. **Procedencia en findings nuevos (siempre-on):** cada `known_finding` nuevo ahora lleva `run_id`, `source_query` (el `sql` estaba disponible pero el record legacy lo tiraba) y `confidence` run-level. Cierra el gap de procedencia que la síntesis marcó.
2. **Auto-escalación gateada (`_auto_escalate_persistent`):** un finding que sube de severidad (hasta CRITICAL) solo por persistir ≥5 runs, sin evidencia ni confirmación — el caso más claro de "autoridad sin base". Con `VALINOR_MEMORY_REVIEW=1` + provenance se **estaciona** una `PendingFindingEscalation` (from/to severity, runs_open, procedencia) en `profile.pending_escalations`; el bump se aplica al record **solo** en approve. Default off → auto-escala como antes. Dedup: no re-estaciona la misma escalación mientras espera revisión.

API: `GET pending-escalations`, `POST {id}/approve` (aplica la severidad, guard de procedencia 400), `POST {id}/reject`. El linter de CI cubre **ambas** colas. +15 tests (`tests/test_n4_seam_a.py`).

## Slice 3 — Audit trail ✅ 2026-06-14

Cada decisión de revisión (approve/reject de ambas colas) emite un evento al log de audit (`audit_log`, lista FIFO de Redis, cap 1000). Se extrajo `api/audit.py::emit_audit_event` como **única fuente** del append (el endpoint `/api/audit` ahora lo reusa — DRY) y es **best-effort**: un problema de Redis nunca rompe el approve/reject (devuelve False y loguea, no levanta).

El evento `memory_review` lleva: `action`, `queue` (refinements/escalations), `client_name`, `proposal_id`, `reviewed_by`, `reason` (en reject), + procedencia/decisión (`run_id`, `confidence`, y para escalaciones `finding_id`/`from_severity`/`to_severity`) + `timestamp`. Consultable vía `GET /api/audit?event_type=memory_review`. +6 tests (`tests/test_audit.py`).

## Slice 4 — Consumidor frontend ✅ 2026-06-14

Página de revisión para el operador en `web/app/clients/[clientId]/review/page.tsx` (Next.js app router, brand D4C: void oscuro, teal, mono para todo número, bordes de severidad). Tab "Revisión" agregado al hub del cliente.

- Dos secciones: **Refinamientos** (borde púrpura, resumen del payload: #pesos/hints/focus/suprimidos + chips de pesos) y **Escalaciones de severidad** (borde = color del to-severity, from→to con badges, "por persistir N runs").
- Cada card muestra **procedencia** (run_id, #findings fuente, generado) + **badge de confianza** (CONFIRMED/PROVISIONAL/UNVERIFIED/BLOCKED con color).
- Acciones: **Aprobar** (teal, aplica) / **Rechazar** (expande textarea de motivo → confirma). Toast + refetch.
- Toggle **Pendientes / Historial** (status=pending vs all; el historial muestra status + quién/cuándo revisó).
- Consume los 6 endpoints (`GET/approve/reject` × 2 colas) vía `fetch` directo (idiom de las páginas recientes). Verificado: `tsc --noEmit` limpio + `next build`.

## Slice 5 — Flip del default + prueba en vivo ✅ 2026-06-14

`memory_review_enabled()` ahora devuelve True **por defecto** (review-on): los learnings se estacionan para revisión humana en vez de auto-aplicarse. Para restaurar el auto-write legacy: `VALINOR_MEMORY_REVIEW=0`. (El gate de procedencia sigue: los callers sin provenance —tests legacy, paths viejos— caen a auto-write igual, así que el flip solo afecta el path real del adapter que sí pasa provenance.)

**Prueba en vivo (stack real: uvicorn + ProfileStore + Redis 6380):**
1. `update_from_run` con el default (flag sin setear) → `memory_review_enabled()=True`, la escalación MEDIUM→HIGH **se estaciona** (no se auto-aplica), severidad queda MEDIUM. Persistido al store real.
2. `GET /api/clients/.../pending-escalations` (API HTTP) → devuelve la propuesta con procedencia completa.
3. `POST .../{id}/approve` → status `approved`, `reviewed_by`/`reviewed_at` sellados.
4. Severidad **aplicada y persistida**: el finding re-leído por la API es `HIGH`. Pendientes → 0.
5. `GET /api/audit?event_type=memory_review` → el evento aterrizó en **Redis real** con action/queue/proposal_id/reviewed_by + procedencia (run_id, confidence) + from/to_severity + timestamp.

El ciclo completo del write-path queda validado end-to-end en el stack corriendo. Suite: 3513 passed (las 61 son la pollution de orden de VAL-193).

**N4 CERRADO** — los 5 slices shippeados; el aprendizaje entre runs ya no compone con autoridad sin pasar por revisión humana con procedencia.

*Refs: VAL-192 (N4). Relaciona N1–N3 (mismo método eval-gated, wire-careful).*
