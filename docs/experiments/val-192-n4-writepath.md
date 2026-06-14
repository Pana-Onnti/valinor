# VAL-192 N4 — Write-path con revisión humana + procedencia (slice 1)

**Fecha:** 2026-06-14 · **Estado:** primera tajada end-to-end shippeada, **gated por `VALINOR_MEMORY_REVIEW=1`** (default off = comportamiento legacy intacto).

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
| `tests/test_n4_writepath.py` | 18 tests: stage-no-activa, approve-merge, reject-archiva, doble-review bloqueado, procedencia obligatoria, flag gating, round-trip, linter, intercepción del adapter (flag on/off) |

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

## Pendiente (próximas tajadas)

- Consumidor frontend (página de revisión reusando DeltaPanel/FindingTimeline) para ambas colas.
- Flip del default a review-on cuando el flujo esté probado en vivo.

*Refs: VAL-192 (N4). Relaciona N1–N3 (mismo método eval-gated, wire-careful).*
