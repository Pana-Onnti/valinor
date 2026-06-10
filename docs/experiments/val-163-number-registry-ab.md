# VAL-163 — Number Registry A/B (control vs treatment) — RESULTADO

> **Status: MEDIDO (2026-06-09/10).** 3 reps por branch, mismo pipeline-state
> capturado (run real del 2026-05-08, shape de producción `{results, errors}`),
> narrators reales (Haiku vía CLI local, $0 API), scoring offline con el
> instrumento N1 arreglado (VAL-192: string numerics, date masking, frontera
> Bug-3). Datos crudos en `docs/experiments/val-163/` (gitignored — datos de
> cliente). CSV: `docs/experiments/val-163/metrics.csv`.

## Pregunta

¿El wiring del Number Registry / `VerificationEngine` en los narrators (VAL-161)
mejora la calidad anti-hallucination, o es inerte? El audit 2026-04-29 degradó
el claim a "wiring entregado; delta sin medir". Este experimento lo midió.

## Diseño

| Branch | `verification_report` | Estado |
|---|---|---|
| **control** | `None` | pre-VAL-161 (narrators ciegos al registry) |
| **treatment** | `VerificationReport` poblado (35/70 claims verified, registry=6) | post-VAL-161 (wiring de prod fiel) |

Mismos findings/query_results/baseline en ambas ramas y reps → todo delta es
atribuible al registry. El VR del treatment se construye offline (el engine no
re-queryea la DB). Narrators: ceo, controller, ejecutivo (sales stubbeado —
known issue VAL-162; causa probable encontrada: techo de 8192 output tokens
del CLI, error que iba a stdout y el provider ocultaba — fix en `cli_provider.py`).

## Resultados (mean ± std sobre 3 reps, medias por narrator)

| Métrica | Control | Treatment | Δ |
|---|---|---|---|
| Grounded rate | 0.9335 ± 0.0099 | 0.9356 ± 0.0110 | **+0.002 (ruido)** |
| Hallucinated rate | 0.0665 ± 0.0099 | 0.0644 ± 0.0110 | −0.002 (ruido) |
| Números alucinados (abs/narrator) | 15.9 ± 1.2 | 9.4 ± 3.1 | **−40%** |
| Estimaciones declaradas | 1.1 | 1.4 | ~ |
| Hedging / 100 palabras | 0.43 ± 0.08 | 0.67 ± 0.07 | **+58%** |
| Word count | 2175 ± 197 | 1391 ± 15 | **−36%** |

Por narrator (grounded rate): briefing_ceo 0.923→0.939, controller 0.948→0.935,
ejecutivo 0.930→0.933 — todos dentro del ruido.

## Lectura honesta

1. **El claim "el registry mejora la grounded-rate" NO se sostiene** (Δ≈0 con
   σ≈0.01). El escepticismo del audit adversarial era correcto. Con el
   instrumento de fidelidad-al-input, los narrators ya citan ~93% grounded
   incluso sin registry: el grueso de lo que escriben sale de findings y
   query_results que tienen delante en el prompt.
2. **El efecto real y consistente del registry es de comportamiento**: reportes
   36% más cortos, hedging +58% (más honestidad sobre incertidumbre), y −40%
   de números no citables en términos absolutos (consecuencia de la
   concisión + el anclaje). La varianza del word count colapsa
   (±197 → ±15): el registry estabiliza el formato del output.
3. **Lo que este instrumento no mide**: utilidad ejecutiva (¿más corto y más
   cauto es mejor para el CEO?). Eso requiere LLM-as-judge (N3 de VAL-192).

## Decisión (rúbrica del DoD)

**KEEP always-on.** Justificación por el Δ medido: a costo marginal ~0 (el VR
se computa igual para el report), el registry corta el volumen absoluto de
números no citables un 40%, estabiliza la longitud y aumenta la honestidad
declarada. Se mantiene el wiring actual. **Queda explícitamente prohibido
claimear "mejora la tasa de grounding"** — el claim defendible es:
*"outputs más concisos, más honestos y con menos números no verificables en
términos absolutos, medido en A/B controlado n=3"*.

Upside adicional ya medido (VAL-192 N2, pendiente de A/B propio): el registry
de prod está hambreado — el builder legacy solo conoce 5 queries; el
enrichment genérico lo lleva de 6 → 79 entradas y el rerank de 2 etapas suma
claims verificados (35→37 en el state de referencia). Ese delta se mide como
treatment2 en el harness N2.

## Caveats

- Modelo: Haiku (override `VALINOR_NARRATOR_MODEL`) vía CLI local ≥2.x — el
  default de prod es Sonnet. La dirección del efecto (concisión/anclaje) es
  esperable que transfiera; la magnitud no está medida en Sonnet.
- Sin control de seed (el CLI no lo expone): 3 reps cuantifican la varianza de
  sampling en su lugar.
- `reporte_ventas` excluido (VAL-162).

## Cómo reproducir

```bash
# 1. state.json desde un output de producción guardado (sin swarm):
venv/bin/python scripts/build_ab_state.py \
    --output tests/output/production/gloria_<run>.json \
    --state docs/experiments/val-163/state.json --narrator-timeout 300

# 2. capturas (CLI ≥2.x para el override de output tokens):
venv/bin/python scripts/run_capture_ab_live.py \
    --state docs/experiments/val-163/state.json \
    --out-dir docs/experiments/val-163 --reps 3 --model haiku \
    --cli-path ~/.claude/local/node_modules/.bin/claude

# 3. scoring offline (sin LLM):
venv/bin/python scripts/eval.py ab --dir docs/experiments/val-163 \
    --csv docs/experiments/val-163/metrics.csv
```

*Harness: `scripts/run_capture_ab_live.py` + `scripts/capture_narrator_ab.py` +
`scripts/eval.py` + `core/valinor/quality/narrator_metrics.py` (instrumento N1,
golden set en `evals/narrator_grounding/`). Refs: VAL-163, VAL-192, VAL-161.*
