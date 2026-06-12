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

## Resultados

### Demo fixture (capa 0 determinista, 2026-06-10)

| Pregunta | Split | flat | flat_narrator | community | forbidden |
|---|---|---|---|---|---|
| q1-exposicion-compuesta | train | 1.00 | 0.20 | 1.00 | 0 |
| q2-cross-sell-gap | train | 1.00 | 0.00 | 1.00 | 0 |
| q3-radio-explosion-churn | test | 1.00 | 0.00 | 1.00 | 0 |
| q4-atribucion-hhi | train | 1.00 | 0.67 | 1.00 | 0 |
| q5-convergencia-agentes | train | 1.00 | 1.00 | 1.00 | 0 |
| q7-columna-vertebral | test | 1.00 | 0.17 | 1.00 | 0 |
| q8-puntos-ciegos | test | 0.50 | 0.50 | 0.50 | 0 |

**Lectura**: en la demo (38 nodos, TODO entra en el budget de contexto) el
flat fuerte resuelve 1.00 — el grafo no puede ganar cuando los datos crudos
caben enteros en el prompt, como predijo el diseño. Lo que la demo SÍ valida:
(a) plumbing end-to-end (grafo→comunidades→PPR→answer→judge), (b) **la brecha
flat_narrator** (0.00–0.67): lo que los narrators ven hoy falla
estructuralmente estas preguntas — el claim de producto, medido. El gate
discriminante corre sobre la captura real (abajo), donde las filas crudas NO
entran en el budget.

### Captura real (Gloria) — capa 0 + juez LLM (3 reps test, 2026-06-10)

Grafo real: 101 nodos / 137 edges / **52 comunidades** (fragmentación alta —
los datos reales tienen menos links cross-query que la demo).

| Pregunta | Split | flat | flat_nar | community | forbidden (comm) |
|---|---|---|---|---|---|
| q1-exposicion-compuesta | train | 0.50 | 0.50 | 0.33 | 4 |
| q2-cross-sell-gap | train | 0.00 | 0.00 | **0.67** | 6 |
| q3-radio-explosion-churn | test | 0.33 | 0.17 | **0.67** | 0 |
| q4-atribucion-hhi | train | 0.00 | 0.17 | **0.83** | 1 |
| q5-convergencia-agentes | train | 0.00 | 0.00 | 0.00 | 2 |
| q7-columna-vertebral | test | 0.25 | 0.25 | 0.25 | 1 |
| q8-puntos-ciegos | test | 1.00 | 0.00 | 0.50 | 1 |

**Gate: NOT PASSED** (0 wins con la vara ≥0.8 + cero forbidden; se necesitan ≥5).

**Lectura honesta del primer datapoint:**
1. **flat falla 5/7** con el juez (6/7 en capa 0) — las preguntas son
   genuinamente globales en datos reales; el claim estructural se sostiene.
2. **community supera a flat direccionalmente en las estructurales**
   (q2 0→0.67, q3 0.33→0.67, q4 0→0.83) — la única que cruza 0.8 es q4.
3. **El bloqueo del gate son los forbidden hits**: el arm community hace
   claims sobre-granulares / no derivables que el juez castiga — el harness
   detecta el defecto exacto a iterar (no es un fallo del juez, es la regla
   de oro de N5 asomando: toda afirmación con cita o marcada como inferencia).

### Iteración v2 (2026-06-10, SOLO train — ejecutada con swarm de agentes cheap)

Diagnóstico (2 agentes) → fixes medidos → train gate **PASSED** (4/4 community
≥0.83, forbidden 0, 3 wins estrictas):
1. **Consolidación**: hub-detach exime segment/category (detachar
   `segment:at_risk` huérfanaba el grafo) + absorción de singletons → 52→6
   comunidades de contenido. Resúmenes 639s→~55s (skip singletons).
2. **Agregados deterministas**: nodos segmento (ΣLTV, share, n) +
   `metric:exposicion_riesgo` (unión dedup churn∪dormancia) +
   `missing_categories_top5` por segmento — y un header "Agregados clave"
   auto-descriptivo en la evidencia (el dict crudo no lo usaba el modelo).
3. **El grafo encontró un bug en la REFERENCIA**: rfm/churn traen
   `recency_days` que el builder no leía — KONG DE (champion, €582K,
   recency>90) era dormancia real que la referencia perdía. Tras el fix ambas
   implementaciones independientes convergen al centavo (€2.653.209,27 /
   54,41%). Ídem share de champions: 45,3% (el grafo sumaba shares parciales
   del top-10 — inconsistencia interna detectada por el juez).
4. **Juez auditable**: forbidden = solo frases citables (atribución
   cliente→categoría o contradicción de referencia); ausencia-de-la-referencia
   NO es forbidden. `forbidden_quotes` persistidas. Mediana de 3 reps en ambos
   splits (a 1 rep el forbidden oscila ±1, medido).
5. **Facts top-k**: listas de 20 elementos son inevaluables en 250 palabras →
   top-5 por valor (q1 clientes, q2 categorías).

### Veredicto FINAL — test congelado (3-rep mediana, código frozen)

| Pregunta | Split | flat | flat_nar | community | forb | Win |
|---|---|---|---|---|---|---|
| q1-exposicion-compuesta | train | 0.50 | 0.50 | **1.00** | 0 | borde (flat 0.50) |
| q2-cross-sell-gap | train | 0.00 | 0.00 | **1.00** | 0 | ✅ |
| q3-radio-explosion-churn | test | 0.33 | 0.50 | **0.83** | 1 | ✗ (1 forbidden) |
| q4-atribucion-hhi | train | 0.00 | 0.33 | **1.00** | 0 | ✅ |
| q5-convergencia-agentes | train | 0.25 | 0.50 | **1.00** | 0 | ✅ |
| q7-columna-vertebral | test | 0.25 | 0.25 | 0.25 | 0 | ✗ (spec 10-labels sin re-spec) |
| q8-puntos-ciegos | test | 0.75 | 0.50 | **1.00** | 0 | ✗ (flat no falla acá) |

**Gate (≥5 wins): NOT PASSED — 3 wins.** Community domina en calidad absoluta
(≥0.83 en 6/7, forbidden ≈0 — v1 era 0.00–0.83 con forbidden 1–6), pero el
hito exige wins ESTRUCTURALES (flat <0.5 ∧ community ≥0.8) y en este state
q8 no es estructuralmente global (flat 0.75: con puntos ciegos vacíos en
Gloria, "no hay" es fácil para flat) y q7 arrastra el defecto de spec de
listas largas que NO se re-especificó en test (disciplina de freeze).

### v3 — re-freeze del test (2026-06-11, ejecutada)

Protocolo: q3/q7 → train (vistas; q7 con re-spec top-k ya legal), q8 →
replaced (flat 0.75 en este state), **3 candidatas nuevas** diseñadas solo
desde el catálogo de queries (q9 riesgo×segmento, q10 top-10∩churn, q13
cobertura del scoring), referencias **verificadas adversarialmente por una
implementación independiente (agente): MATCH, cero mismatches** en demo y
Gloria. Trampas capa-0 pasan a semántica de sustitución (co-ocurrencia junto
al número correcto = contexto legítimo). **Gate v3 endurecido**: ≥5 wins
totales ∧ ≥2 wins en test virgen. Código del grafo congelado en v2.2 (cero
features nuevas — agregar agregados "casualmente útiles" para las candidatas
sería teach-to-the-test).

**Veredicto (una pasada, mediana 3 reps):**

| Pregunta | Split | flat | flat_nar | community | forb | Win |
|---|---|---|---|---|---|---|
| q1-exposicion-compuesta | train | 0.50 | 0.50 | **1.00** | 0 | borde (flat 0.50) |
| q2-cross-sell-gap | train | 0.00 | 0.00 | **1.00** | 0 | ✅ |
| q3-radio-explosion-churn | train | 0.33 | 0.50 | 0.83 | 1 | ✗ |
| q4-atribucion-hhi | train | 0.00 | 0.50 | **1.00** | 0 | ✅ |
| q5-convergencia-agentes | train | 0.00 | 0.00 | **1.00** | 0 | ✅ |
| q7-columna-vertebral | train | 0.50 | 0.25 | **1.00** | 0 | borde (flat 0.50) |
| **q9-riesgo-por-segmento** | **test** | 0.00 | 0.00 | **1.00** | 0 | ✅ **win en test VIRGEN** |
| q10-doble-exposicion | test | 0.33 | 0.50 | 0.50 | 2 | ✗ (mordió la trampa all-risky) |
| q13-cobertura-scoring | test | 0.00 | 0.33 | 0.00 | 2 | ✗ (flat también 0.00) |

**GATE v3 (≥5 ∧ ≥2 test): NOT PASSED — 4 wins, 1/2 test.**

**Lectura:**
1. **q9 = la win que importa**: join churn×rfm con group-by, en pregunta
   nunca vista, sin features nuevas — el sistema v2 GENERALIZA a la clase de
   preguntas que modela (joins/agregaciones sobre entidades y segmentos).
2. **El test virgen localizó los límites de capacidad reales** (lo que train
   ya no podía ver): q10 exige membresía de set explícita (top-10 por LTV —
   la evidencia está rankeada por PPR, no por LTV) y q13 exige razonamiento
   por AUSENCIA (quién NO tiene score — la evidencia muestra edges presentes,
   no faltantes). Ninguna es alcanzable con la evidencia actual.
3. Las preguntas seen están saturadas (0.83–1.00) — el cuello ya no es
   iteración de prompts sino **capacidades del grafo**.

### v4 — re-freeze #2 ejecutado (2026-06-11)

Protocolo: q10/q13 → train; features genéricas construidas e iteradas contra
train (`rank_by_ltv`, `metric:cobertura_scoring` espejo de exposicion_riesgo,
header TOP-10 POR LTV con flags riesgo/score, aliases de cobertura) — q10 y
q13 pasaron de 0.50/0.00 a **6/6 con forbidden 0 en UNA ronda**. Test virgen
nuevo (q14 dormancia×segmento, q15 top10∩sin-score, q16 concentración del
riesgo por score), referencias verificadas adversarialmente (MATCH, cero
mismatches). Código congelado → una pasada, mediana 3 reps.

**Veredicto v4: NOT PASSED — 7 wins totales (≥5 ✓) pero 1/2 test (✗).**

| Pregunta | Split | flat | community | forb | Win |
|---|---|---|---|---|---|
| q1/q2/q3/q4/q5/q13 | train | 0.00–0.33 | **0.83–1.00** | 0 | ✅ ×6 |
| q10 | train | 0.50 | 1.00 | 0 | borde (flat 0.50) |
| q7 | train | 0.50 | **0.25** | 0 | ✗ regresión (1.00 en v3) |
| q9 (vista en v3; mal etiquetada test en este run, no sumó win) | train | 0.00 | 0.67 | 2 | ✗ regresión (1.00 en v3) |
| **q15-top10-sin-score** | **test** | 0.00 | **1.00** | 0 | ✅ **win virgen** |
| q14-dormancia-por-segmento | test | 0.00 | 0.67 | 1 | ✗ |
| q16-concentracion-del-riesgo | test | 0.00 | 0.67 | 2 | ✗ |

**Lecciones (las tres importan):**
1. **El patrón se confirma por tercera vez**: las preguntas cuyo agregado
   determinista está pre-servido dan 1.00 (q15 virgen ✅ — las features
   nuevas generalizaron a una combinación no vista); las que exigen un
   group-by NO servido dan ~0.67 con forbidden (q14: dormancia×segmento;
   q16: ranking por score). **El techo de capacidad ES la biblioteca de
   agregados** — coherente con el diseño "el LLM narra, nunca calcula".
2. **Varianza answer-side sin medir**: q7 (1.00→0.25) y q9 (1.00→0.67)
   regresionaron al re-samplear sus respuestas bajo la evidencia v4 (header
   nuevo desplaza contexto + n=1 por respuesta). El juez tiene mediana de 3;
   la RESPUESTA no. Gap de instrumento para v5.
3. Progresión de wins por ronda: v1 0 → v2 3 → v3 4 → v4 7 (test virgen:
   0 → — → 1/3 → 1/3).

### v5 — re-freeze #3 ejecutado (2026-06-11/12, swarm + dynamic workflow)

Build vía workflow (3 agentes sonnet en paralelo): **group-by genérico**
(agregados por segmento avg/en-riesgo/dormido/sin-score + headers sistemáticos
GROUP-BY SEGMENTO / TOP-5 POR SCORE / TOP-5 CATEGORÍAS + totales globales por
edge-type), **protocolo 3-sample** (mediana de 3 trials end-to-end por
(pregunta, arm) — elimina el n=1 answer-side), **referencias q17/q18/q20
verificadas adversarialmente** (MATCH, cero mismatches). Iteración train: q14
0.67→6/6, q16 0.67→5/6 forb 0 en UNA ronda (+2 fixes de instrumento: totales
globales como denominadores; listas de referencia declaradas conjuntos sin
orden — el juez penalizaba un ranking CORRECTO leyendo el orden alfabético
como ranking). Test virgen #3: q17 convergencia×share, q18 avg LTV por
segmento, q20 dimensión categoría.

**Veredicto OFICIAL (una pasada, 3 samples, juez por sample):**

| Pregunta | Split | flat | community | forb | Win |
|---|---|---|---|---|---|
| q1/q2/q5/q9/q10/q13/q14/q15/q16 | train | 0.00–0.33 | **1.00** | 0 | ✅ ×9 |
| q3/q4 | train | 0.00–0.33 | 0.83 | 1 | ✗ |
| q7 | train | 0.00 | 0.50 | 0 | ✗ |
| **q17-peso-convergentes** | **test** | 0.17 | **0.83** | 1 | ✗ |
| **q18-ltv-promedio-segmento** | **test** | 0.00 | **1.00** | 1 | ✗ |
| **q20-categoria-lider** | **test** | 0.00 | **1.00** | 0 | ✅ **win virgen** |

**GATE v5 (≥5 ∧ ≥2 test): NOT PASSED — 10 wins (récord), test 1/2.**

**Forense de los 2 forbidden bloqueantes (post-veredicto, preguntas ya
quemadas):** ambos son **falsos positivos del JUEZ**: q17 flaggeó "11.07%"
como contradicción de la referencia 11.08% (redondeo de 0.01pp, tolerancia
del fact ±2pp); q18 sacó 6/6 PERFECTO y el forbidden es una recomendación de
cross-sell correcta a nivel segmento con agregados servidos. Fix de
calibración aplicado al juez (contradicción = solo fuera de tolerancia;
comentario de negocio sobre agregados servidos no es forbidden).

**Análisis de sensibilidad (mismas respuestas, juez calibrado — reportado
como sensibilidad, NO como gate):** test virgen **3/3 wins, community
1.00/1.00/1.00, forbidden 0**. El sistema generalizó al test virgen completo;
lo que falló fue el instrumento de juicio. **La certificación formal requiere
un par virgen nuevo bajo el juez calibrado (v6)** — regla de no re-gatear
sobre test visto.

Incidente operativo: un auto-update de Claude Code borró el binario del CLI
a mitad del juicio (scores 0.00 espurios de q14 en adelante) — detectado por
el patrón todo-cero + el error en el log, re-juzgado con el binario nuevo.
Ruta estable: `~/.claude/local/claude`.

**Progresión final de las 5 rondas: v1 0 wins → v2 3 → v3 4 → v4 7 → v5 10**
(test virgen: 0 → — → 1/3 → 1/3 → 1/3 oficial · 3/3 en sensibilidad).

## Wiring a producción

`VALINOR_GRAPHRAG=1` (Stage 3.7 opcional, inerte por defecto) queda para
DESPUÉS de que el gate pase — eval-first, wire-later (la lección pre-N1).

*Refs: VAL-192 (N3). Harness: `core/valinor/graphrag.py` ·
`core/valinor/agents/graph_global.py` · `core/valinor/quality/global_judge.py` ·
`scripts/graphrag_answer.py` · `scripts/eval.py graphrag`.*
