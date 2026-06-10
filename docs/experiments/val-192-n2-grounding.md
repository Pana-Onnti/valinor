# VAL-192 N2 — Grounding de 2 etapas: enrichment + rerank — RESULTADO

> **Status: MEDIDO (2026-06-10). Veredicto: NO se wirea a prod.** El módulo
> queda como tooling opt-in (`core/valinor/verification_rerank.py`,
> `--enriched` en el runner); la hipótesis de mejora a nivel narrator quedó
> refutada en este state. Eval-gated significa exactamente esto.

## Qué se construyó

1. **Stage 1.5 — enrichment genérico del registry** (determinista): el builder
   legacy de `VerificationEngine` solo conoce 5 nombres de query → las queries
   de VAL-141 (concentración, RFM, churn, HHI) nunca entraban al Number
   Registry. El enrichment lo lleva de **6 → 79 entradas** en el state de
   referencia (scalars single-row, rank-1, sumas de columna).
2. **Stage 2 — rerank LLM** (caro, selectivo): una llamada batched propone
   derivaciones aritméticas para claims UNVERIFIABLE; **el código las recomputa
   y solo un match numérico upgradea** (el LLM propone, el código dispone —
   una propuesta alucinada no puede corromper el report). Contradicciones →
   issues disputados, nunca retractación automática. Lección de prompt: pedirle
   al modelo que NO haga la aritmética (la hace el código) — pedirle "proponé
   solo si los datos lo sostienen" lo paraliza (0 propuestas).

Nivel claim (state de referencia): 35/70 verified → 36-37/70 según rep
(la variación es del LLM proponente; la confirmación es determinista).
Ej. confirmado: €914,861 = suma ltv_eur del top-10 de concentración.

## A/B a nivel narrator (3 reps, Haiku CLI local, instrumento N1)

| Métrica | Control | Treatment2 (79 entries) | Treatment1 (6 entries, VAL-163) |
|---|---|---|---|
| Grounded rate | 0.9323 ± 0.0184 | **0.9195 ± 0.0124** | 0.9356 ± 0.0110 |
| Números alucinados (abs) | 17.3 | 12.1 | 9.4 |
| Hedging / 100 palabras | 0.60 | **0.38** | 0.67 |
| Word count | 2095 | 1612 | 1391 |

(1 captura corrupta — rep2/treatment/ejecutivo vacía — detectada y excluida
por el scorer; el detector de capturas ahora atrapa outputs vacíos.)

## Lectura honesta

1. **El registry enriquecido NO mejora la grounded-rate** (0.920 vs 0.936 del
   registry chico, vs 0.932 control — dentro de ~1.5σ, dirección negativa).
2. **Efecto colateral indeseado**: con 79 números "verificados" a mano, los
   narrators **hedgean menos** (0.38 vs 0.67 del treatment1) — más confianza
   declarada sin más grounding real. Lo opuesto de lo que queremos.
3. La capacidad a nivel claim (sumas/derivaciones confirmadas
   determinísticamente) es real pero **no se traduce** en mejor grounding
   narrativo en este state.

## Decisión (hito N2)

**El hito N2 NO se cumple** ("mejora medida... sin degradar") → el enrichment
**no se wirea a producción**. El módulo queda para: (a) tooling de análisis
offline, (b) re-test cuando cambie el prompt de narrators (cómo consumen el
registry puede ser el cuello, no el tamaño del registry), (c) el rerank
propose-confirm como patrón para N5 (citas por claim).

## Caveats

- n=3, Haiku, un solo state (Gloria 2026-05-08); ejecutivo n=2 tras el drop.
- El prompt de narrators ("USE ONLY THESE VALUES") no fue tuneado para un
  registry grande — hipótesis alternativa sin testear, requeriría su propio A/B.

## Reproducir

```bash
venv/bin/python scripts/run_capture_ab_live.py \
    --state docs/experiments/val-163/state.json \
    --out-dir docs/experiments/val-163/n2 --reps 3 --model haiku \
    --cli-path ~/.claude/local/node_modules/.bin/claude --enriched
venv/bin/python scripts/eval.py ab --dir docs/experiments/val-163/n2 \
    --csv docs/experiments/val-163/n2/metrics.csv
```

*Refs: VAL-192 (N2), VAL-163. Tests: `tests/test_verification_rerank.py` (11).*
