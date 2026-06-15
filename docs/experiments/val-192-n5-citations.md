# VAL-192 N5 — El KG dentro del harness (toda afirmación con cita)

**Fecha:** 2026-06-14 · **Estado:** slice 1 (instrumento + baseline, eval-first, sin enforcement).

## El hito y el método

N5: *toda afirmación de agente lleva cita (la query/registry entry que la resolvió) o se marca como inferencia; la tasa de claims-sin-cita medida y bajando.* Fiel a la disciplina de la épica (sin eval, cada cambio es a ciegas), **el primer entregable es el instrumento que mide la tasa, no el enforcement.**

## El descubrimiento

El substrato de citación **ya existe** a nivel claim en `verification.py`: `AtomicClaim.source_query`, `VerificationResult.verification_query`, y la clasificación 4-vías (VERIFIED/APPROXIMATE/FAILED/UNVERIFIABLE). Lo que **faltaba**: nadie computa la tasa de claims-sin-cita, y el artefacto serializado `verification_report.json` **dropeaba `results[]`** (los per-claim) — así que ningún run capturado persistía lo que N5 mide.

## Definición operativa (decisiones tomadas, recomendadas por la síntesis)

Sobre los `results[]` de un `VerificationReport`:

| Bucket | Regla | Qué es |
|---|---|---|
| **declared** | claim_text marca `[ESTIMADO]/[INFERIDO]/~` | inferencia declarada → **fuera del denominador** (protocolo de honestidad, regex reusado de N1) |
| **cited** | status VERIFIED/APPROXIMATE ∧ `verification_query` ≠ None | linaje resuelto a una query/registry |
| **failed** | status FAILED | tenía linaje pero el valor se contradijo |
| **unresolvable** | status UNVERIFIABLE ∧ query intentada | hueco de cobertura de datos, NO falla de autoría |
| **uncited** | status UNVERIFIABLE ∧ sin query | la falla de autoría que N5 ataca |

`uncited_rate = uncited / (total − declared)` (espeja el denominador "verifiable" de N1).

**Forks resueltos (documentados, no bloqueé porque son metodología eval, alineada con N1 y reversible):** granularidad = numéricos (como `_decompose_finding`; prosa = blind-spot documentado, igual que N1); cita válida = `verification_query` ≠ None (mide "tiene linaje"; el tier de confianza se difiere al enforcement); marca de inferencia = regex de N1 (el campo typed `value_confidence` queda para enforcement); uncited vs unresolvable = **se reportan aparte** (solo uncited es falla de autoría).

## Baseline (real, sobre Gloria)

`scripts/agent_grounding_baseline.py --state docs/experiments/val-163/state.json` corre el `VerificationEngine` REAL offline sobre el state capturado de Gloria → report con `results[]` → instrumento:

```
total_claims: 70 · cited: 32 · uncited: 38 · unresolvable: 0 · failed: 0 · declared: 0
uncited_rate: 0.5429   (cited_rate: 0.4571)
```

**54% de los claims atómicos de Gloria no tienen cita.** Más de la mitad de las afirmaciones de los agentes no rastrean a una fuente verificable en los datos estáticos.

**Caveat honesto:** offline (sin DB) la estrategia de active re-query no corre, así que claims que se resolverían vía re-query cuentan como uncited → este baseline es conservador (sobreestima uncited). Es la *cobertura de citación estática*. El número full-pipeline (con DB + re-query) vendrá de un run capturado con el `results[]` que ahora persiste `deliver.py`.

## Lo construido (slice 1)

| Archivo | Qué |
|---|---|
| `core/valinor/quality/agent_grounding_metrics.py` | `AgentClaimsAudit` + `score_agent_claims(results, claims)` — puro, post-hoc, reusa el regex declarado de N1 |
| `core/valinor/deliver.py` | serializa `results[]` (claim_id/status/verification_query/confidence) — el enabler de infra |
| `scripts/agent_grounding_baseline.py` | runner reproducible (--state corre verificación offline · --report puntúa el artefacto) |
| `tests/test_agent_grounding_metrics.py` | 12 tests: las 5 categorías, rate sobre denom verifiable, declared excluido, compat dict/objeto |

## Próximas tajadas

- **Golden + gate CI**: `evals/agent_grounding/golden.yaml` + `scripts/eval.py agent-grounding` + baseline.json con gate de regresión (como N1), una vez fijado el umbral.
- **Baseline full-pipeline**: un run capturado con DB → uncited_rate con active re-query.
- **Enforcement**: bajar la tasa — wirear `value_confidence` typed a los claims (cita-o-marca-inferencia en el origen, no regex), y subir la cobertura de citación de los agentes. Medir el delta contra este baseline.

*Refs: VAL-192 (N5). Mismo método eval-gated que N1–N4.*
