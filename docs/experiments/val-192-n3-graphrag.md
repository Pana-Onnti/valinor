# VAL-192 N3 — GraphRAG: preguntas globales (flat vs community)

> **Status: harness completo, AWAITING LIVE RUN.** Los `[TK]` se llenan con el
> primer run real. Hasta entonces este doc es runbook + rúbrica, no resultado.

## Tesis

El análisis por-query falla **estructuralmente** las preguntas que cruzan
result sets (exposición churn∩dormancia, gaps de cross-sell por segmento,
Pareto con flags de riesgo, puntos ciegos del swarm). El salto de N3 es el
**grafo de entidades a nivel instancia** — construido determinísticamente del
estado post-verificación (cero extracción LLM) — con comunidades (greedy
modularity + refinement de conectividad, *Leiden-equivalente a n<500*;
leidenalg/igraph rechazados como dependency theater) y **Personalized
PageRank** (power iteration numpy) para rankear evidencia.

El LLM aparece en exactamente 3 lugares: resumen por comunidad, respuesta por
pregunta, juez — todos Haiku vía CLI local ($0).

## Diseño anti-strawman

| Arm | Contexto (mismo budget de chars) | Rol |
|---|---|---|
| **flat** | baseline + findings + registry + filas crudas hasta el budget | control FUERTE — el gate corre contra este |
| **flat_narrator** | baseline + findings + registry (lo que ven los narrators hoy) | reportado, no gated — soporta el claim de producto |
| **community** | resúmenes por comunidad + evidencia PPR top-30 | el candidato |

## Golden set

`evals/golden/global_questions.yaml` — 7 preguntas activas (q6 cayó por la
**regla de computabilidad**: AR por-cliente no está en los states; documentado
en el YAML). Referencias calculadas por joins deterministas
(`scripts/build_global_references.py`), independientes del grafo bajo test:

- **Demo fixture** (committable, CI): `evals/fixtures/state_demo.json`
  (sintética, aritméticamente consistente) → `references_demo.json`. Las 7
  computan.
- **Captura real** (gitignored): `docs/experiments/val-163/state.json` →
  `docs/experiments/val-192-n3/references_gloria.json`. Las 7 computan
  (verificado 2026-06-10).

Split: 4 train (q1, q2, q4, q5) / 3 test (q3, q7, q8) — el test se congela
antes de iterar prompts; con n=7 esto guarda contra prompt-overfitting, no
significancia (dicho explícitamente).

## Juez (2 capas — `core/valinor/quality/global_judge.py`)

- **Capa 0, determinista**: required_facts (números vía el extractor N1 con
  tolerancia; labels por containment normalizado) + must_not_include (trampas,
  p.ej. la suma naive sin dedup de q1). Corre primero, sin LLM, en CI.
- **Capa 1, LLM-as-judge** (Haiku local, 3 reps mediana en test split): por
  fact 0/1/2, forbidden −2, penaliza claims sobre-granulares (cross-sell es
  segmento×categoría).

**Gate que cierra N3**: community ≥0.8 en ≥5 preguntas donde flat <0.5, cero
forbidden hits en community.

## Cómo correr

```bash
# 1. fixture + referencias (deterministas, sin LLM):
venv/bin/python scripts/build_demo_state.py
venv/bin/python scripts/build_global_references.py \
    --state evals/fixtures/state_demo.json --out evals/fixtures/references_demo.json

# 2. responder los arms (LLM, CLI local ≥2.x):
venv/bin/python scripts/graphrag_answer.py \
    --state evals/fixtures/state_demo.json \
    --out-dir docs/experiments/val-192-n3/demo \
    --cli-path ~/.claude/local/node_modules/.bin/claude

# 3. score (capa 0 sola = CI-safe; --judge agrega capa 1):
venv/bin/python scripts/eval.py graphrag \
    --dir docs/experiments/val-192-n3/demo \
    --references evals/fixtures/references_demo.json \
    --judge --gate --csv docs/experiments/val-192-n3/demo/scores.csv
```

## Resultados `[TK]`

| Pregunta | Split | flat | flat_narrator | community | forbidden |
|---|---|---|---|---|---|
| `[TK]` | | | | | |

Gate: `[TK]` · Run real (Gloria): `[TK]`

## Wiring a producción

`VALINOR_GRAPHRAG=1` (Stage 3.7 opcional, inerte por defecto) queda para
DESPUÉS de que el gate pase — eval-first, wire-later (la lección pre-N1).

*Refs: VAL-192 (N3). Harness: `core/valinor/graphrag.py` ·
`core/valinor/agents/graph_global.py` · `core/valinor/quality/global_judge.py` ·
`scripts/graphrag_answer.py` · `scripts/eval.py graphrag`.*
