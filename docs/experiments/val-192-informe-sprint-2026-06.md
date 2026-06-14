# Informe — Máquina de Conocimiento Valinor (VAL-192 + VAL-163)

**Período:** 2026-06-09 → 2026-06-14 · **Estado:** VAL-163 Done · VAL-192 In Progress (N1 ✅ · N2 medido-no-wireado · **N3 ✅ GATE CERTIFICADO en v6** — test virgen 3/3, 15 wins, auditoría adversarial superada)
**Tesis de la épica:** *sin eval, cada cambio es un refactor a ciegas; con eval, cada cambio tiene veredicto.* Este sprint la aplicó literalmente: **9 veredictos medidos, 4 negativos honestos, 8 bugs de instrumento encontrados por los propios experimentos.**

---

## 1 · Resumen ejecutivo

| Entregable | Veredicto medido |
|---|---|
| **VAL-163** (A/B Number Registry) | **Done.** Claim de tasa REFUTADO (Δ≈0); registry **keep always-on** por el delta de comportamiento: −40% números no citables, −36% largo, +58% hedging honesto. |
| **N1** (instrumento + golden + gate) | **Cerrado.** 3 bugs arreglados con evidencia, golden 39 casos verificados adversarialmente, regression gate en CI (`pytest` falla si el instrumento regresiona). |
| **N2** (grounding 2 etapas) | **Medido → NO se wirea** (gate honesto): enrichment 6→79 entradas no mejora la tasa (0.920 vs 0.936) y baja el hedging. Queda opt-in. |
| **N3** (GraphRAG, 6 rondas eval-gated) | **Wins: v1 0 → v2 3 → v3 4 → v4 7 → v5 10 → v6 15. GATE CERTIFICADO** (v6, juez calibrado, par virgen nuevo): test virgen **3/3** (1.00/1.00/1.00, forbidden 0), auditoría adversarial de 9 escépticos superada sin refutes válidos. |

**Producto medido (claim defendible):** la vista actual del pipeline (flat_narrator) falla estructuralmente las 15 preguntas globales del golden (0.00–0.50); el modo GraphRAG las responde 0.83–1.00 con cero alucinaciones de granularidad en 13/15. El claim "el registry mejora la grounded-rate" queda **prohibido** (refutado n=3); el claim correcto es conciso/honesto/menos-números-no-citables.

---

## 2 · VAL-163 — A/B del Number Registry (cerrado)

3 reps por branch, mismo estado de pipeline real (shape de prod `{results,errors}` — el shape plano hambrea el registry: 4 vs 35/70 claims verificados), narrators reales vía CLI local, scoring con el instrumento N1 arreglado.

| Métrica | Control | Treatment | Δ |
|---|---|---|---|
| Grounded rate | 0.9335 ± 0.0099 | 0.9356 ± 0.0110 | ≈0 (ruido) |
| Números alucinados (abs) | 15.9 | 9.4 | **−40%** |
| Hedging /100 palabras | 0.43 | 0.67 | **+58%** |
| Word count | 2175 ± 197 | 1391 ± 15 | **−36%** |

**Decisión: keep always-on.** El escepticismo del audit 2026-04-29 era correcto sobre la tasa; el valor real del registry es comportamiento (concisión, estabilidad ±197→±15, honestidad declarada) a costo ~0.

**Bonus:** clase de error "API error a stdout con stderr vacío" verificada y arreglada en `cli_provider.py` (el techo de 8192 output tokens reproducido en vivo); el path del fallback de 679 chars de VAL-162 confirmado; la causa exacta de sales sigue abierta — el fix de visibilidad la mostrará. Gotcha: CLI v2.1.17x + sonnet cuelga >600s en el prompt de sales (v1: 141s; v2+haiku perfecto).

## 3 · N1 — el instrumento (cerrado)

- **Bug-1**: numéricos string (`"364517.30"`) e intervalos (`"147 days"` — ¡no era una fecha!) entraban como alucinación. **Bug-2**: fechas/horas/Q-labels/rank-labels contaban como claims; sufijos sin boundary ("### 2. Base" = 2 mil millones). **Bug-3** (frontera por evidencia): prosa de findings = input; `[ESTIMADO]/~` = bucket declarado fuera del denominador; derivados within-column opt-in; **pairwise cross-corpus refutado** (acredita "Top 200" arbitrarios).
- Golden 39 casos sintéticos (26/13 split), labels verificados por 3 lentes adversariales (0 flags). Gate en CI con baseline 1.0.

## 4 · N2 — grounding 2 etapas (medido, no wireado)

Enrichment genérico del registry (el builder legacy solo conocía 5 queries → 6→79 entradas) + rerank LLM-propone/código-confirma (propuesta alucinada no puede corromper el report). **A/B treatment2: grounded 0.920 vs 0.936 (peor) y hedging 0.67→0.38** (confianza sin grounding) → **gate falla → prod intacto**. Lección de prompt: pedir la derivación SEMÁNTICA — pedirle al modelo que verifique la aritmética lo paraliza (0 propuestas).

## 5 · N3 — GraphRAG en 5 rondas eval-gated

**Arquitectura final:** entity graph determinista a nivel instancia (resolución de entidades cross-query, hub-detach + CNM + refinement "Leiden-equivalente a n<500", PPR numpy, cero deps nuevas) + **biblioteca de agregados servidos** (exposición compuesta, cobertura de scoring, group-by genérico por segmento, top-N con flags, totales globales por edge-type) + LLM que **narra y nunca calcula** + juez de 2 capas con referencias por joins independientes verificadas adversarialmente.

| Ronda | Qué cambió | Wins | Test virgen |
|---|---|---|---|
| v1 | harness + 1er datapoint | 0 | — |
| v2 | consolidación 52→6 comunidades, seeds ES, convergencia surfaceada, juez auditable | 3 | — (train gate ✅) |
| v3 | re-freeze #1: pool repair + 3 vírgenes verificadas | 4 | 1/3 (q9 1.00) |
| v4 | features membresía/cobertura (1 ronda train: q10/q13 → 6/6) | 7 | 1/3 (q15 1.00) |
| v5 | **group-by genérico + 3-sample mediana** (workflow swarm) | **10** | **1/3 oficial · 3/3 sensibilidad** |

**v5 test virgen (oficial):** q17 0.83/forb 1 · q18 **1.00**/forb 1 · q20 **1.00**/forb 0. Los 2 forbidden bloqueantes son **falsos positivos del juez** (forense: "11.07%" vs referencia 11.08% con tolerancia ±2pp; una recomendación correcta a nivel segmento). **Sensibilidad con juez calibrado: 3/3 wins, 1.00/1.00/1.00, forbidden 0.** La certificación formal exige par virgen nuevo bajo el juez calibrado (v6) — regla de no re-gatear sobre test visto.

**La conclusión arquitectural (confirmada 3 rondas):** el techo de capacidad ES la biblioteca de agregados — GraphRAG-mínimo es un *servidor de joins deterministas + narrador*. Cada clase de agregado nuevo (exposición → membresía/cobertura → group-by genérico) convirtió su clase de pregunta de ~0.67-con-forbidden a 1.00.

**El harness se auto-corrigió 8 veces** (el valor del método): la referencia perdía `recency_days` (el grafo la corrigió — convergencia al centavo después), share de segmento internamente inconsistente, listas como rankings, contradicción-sin-tolerancia, trampas de co-ocurrencia, denominadores globales ausentes, capturas vacías, CLI errors a stdout.

## 6 · Testing

- **+181 tests nuevos del sprint** (offline, deterministas, sin LLM/DB), todos verdes en subset y en suite.
- Suite completa: 3402 passed / 51 failed **pre-existentes** (pollución de orden, VAL-193 creado — eran 52 antes del sprint).
- Gates en CI: instrumento N1 (`tests/test_eval_gate.py`) activo; el gate N3 corre por CLI (capa 0 CI-safe).

## 7 · Operativo / runbooks

- Recetas reproducibles: `build_ab_state.py` → `run_capture_ab_live.py` → `eval.py ab` (VAL-163) · `build_demo_state.py` → `build_global_references.py` → `graphrag_answer.py --samples 3` → `eval.py graphrag --judge` (N3).
- Gotchas vivos: CLI ≥2.x para `CLAUDE_CODE_MAX_OUTPUT_TOKENS`; ruta estable `~/.claude/local/claude` (un auto-update borró el binario a mitad de un juicio — scores 0.00 espurios, detectado y re-juzgado); v2+sonnet cuelga en prompts largos.
- Todo dato de cliente gitignored (`docs/experiments/val-163/`, `val-192-n3/`); fixtures committeadas 100% sintéticas.

## 8 · Próximos pasos (en orden)

1. ~~**v6**: par virgen nuevo bajo el juez calibrado → certificación formal del hito N3.~~ ✅ **HECHO (2026-06-14): GATE PASSED** — test virgen 3/3, 15 wins, auditoría adversarial superada. Detalle en `val-192-n3-graphrag.md` §v6.
2. **Wirear N3 a narrators** detrás de `VALINOR_GRAPHRAG=1` con su propio A/B (patrón eval-first probado) — **ahora habilitado** (gate pasado).
3. **N4 write-path** (memoria con human-in-loop) — el siguiente nivel de la épica.
4. VAL-193 (higiene de suite) cuando haya un hueco.

*Refs: VAL-192, VAL-163, VAL-161, VAL-162, VAL-193. Detalle por ronda: `val-192-n3-graphrag.md` · `val-192-n2-grounding.md` · `val-163-number-registry-ab.md` · `evals/narrator_grounding/README.md`.*
