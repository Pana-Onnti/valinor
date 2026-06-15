# VAL-192 N5 — El KG dentro del harness (toda afirmación con cita)

**Fecha:** 2026-06-14 · **Estado:** slice 1 (instrumento + baseline) + slice 2 (value_confidence + golden gate CI) + slice 3 (enforcement A/B prompt-side → **inconcluso**, lever determinista pendiente).

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

## Slice 2 — `value_confidence` typed + golden gate CI ✅ 2026-06-14

**El 54% estaba inflado.** La detección de inferencia del slice 1 era solo regex sobre el claim_text — pero los agentes YA marcan su incertidumbre vía el campo typed `value_confidence` (MEASURED/ESTIMATED/INFERRED, `schemas/agent_outputs.py`). En el state de Gloria: **18 de 30 findings (60%) son estimated/inferred**. El instrumento los contaba como uncited.

Wireé `value_confidence` a la detección de inferencia (un claim cuyo finding es `estimated`/`inferred` es inferencia declarada → fuera del denominador, la mitad "o marcada inferencia" de la regla N5, vía el campo del agente y no regex). Join: `AtomicClaim.finding_id → finding["id"] → value_confidence`.

**Baseline corregido (Gloria):**
```
total_claims: 70 · declared_inference: 40 · verifiable: 30 · cited: 14 · uncited: 16
uncited_rate: 0.5333
```
La tasa es similar (54%→53%) pero el **denominador ahora es correcto**: 40/70 claims son inferencias que el agente declaró honestamente; de los **30 claims MEASURED** (los que sí deben citarse), **16 (53%) no tienen cita**. Esa es la falla de autoría real que el enforcement debe bajar, sin contaminar con inferencias honestas.

**Gobernanza (mirror N1):** `evals/agent_grounding/golden.yaml` (14 casos sintéticos, 10 train / 4 test, cubren las 5 categorías + value_confidence) + `scripts/eval.py agent-grounding [--gate]` + `baseline.json` (`case_accuracy/test = 1.0`) + gate de CI en `tests/test_eval_gate.py` (pytest falla si el instrumento regresiona en el split de test). Train/test respetado.

## Slice 3 — Enforcement A/B (directiva de citación) → INCONCLUSO 2026-06-14

**El lever:** `_extract_query_ref` solo resuelve la cita si el `query_id` exacto aparece verbatim en el `evidence`. Los agentes citan en prosa ("the concentration query"), no la key → no resuelve → uncited. El **treatment**: una directiva que exige citar el `query_id` EXACTO (o marcar `value_confidence: inferred` si no rastrea). Enabler: `run_analyst(citation_directive=, model=)` (inerte por defecto).

**El A/B** (`scripts/agent_citation_ab.py`, mirror VAL-163): analyst 2× sobre el MISMO state de Gloria, control (sin directiva) vs treatment (con), **mismo Haiku** ambos brazos (Sonnet cuelga en el CLI local — documentado), 3 reps.

| | control | treatment | Δ |
|---|---|---|---|
| rep1 | 0.571 | 0.200 | **−0.371** |
| rep2 | 0.471 | 0.591 | **+0.120** (peor) |
| rep3 | 0.467 | 0.400 | −0.067 |
| **mediana** | **0.471** | **0.400** | **−0.067** |

**Veredicto: INCONCLUSO — no se puede claimar que la directiva baja la tasa.** El −37pp de la rep1 era **ruido de muestreo del LLM**: sobre 3 reps la mejora mediana es chica (−6.7pp), una rep dio *peor*, y el rango cruza el cero. La varianza del LLM (cuántos claims produce + cuántos cita) domina el efecto. **El método atrapó un falso-win de 1 rep** — la misma disciplina que refutó el overclaim de VAL-162 y el claim de tasa de VAL-163.

Datos: el treatment SÍ tiende a citar más (cited 16/15 vs 9/8 en reps 1/3) y a marcar más inferencias honestas, pero también produce más claims totales que diluyen, y a veces (rep2) no cita más. No es un lever robusto a este n con prompt-side + Haiku.

## Próximas tajadas

- **Lever determinista (resolución-side)**: mejorar `_extract_query_ref` con fuzzy-match (tabla/concepto → query_id) — **cero varianza de LLM**, delta limpio y reproducible (A/B post-hoc sobre los findings capturados). Probablemente el lever real.
- **Enforcement más fuerte**: rechazar/degradar findings MEASURED sin cita resoluble (no solo pedirlo en el prompt).
- **Baseline full-pipeline**: run con DB → uncited_rate con active re-query (el `results[]` ya persiste).
- Multi-rep + Sonnet + 3 agentes si se persigue el lever prompt-side.

*Refs: VAL-192 (N5). Mismo método eval-gated que N1–N4.*
