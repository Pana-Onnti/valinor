# Informe Final — Máquina de Conocimiento Valinor (VAL-192, N1→N7)

**Período:** 2026-06-09 → 2026-06-16 · **Estado:** arco N1→N7 completo en todo lo accionable sin infra del operador · **verificado con tests reales el 2026-06-16** (pipeline E2E 3/3 períodos PASSED, suite higienizada 188→1, gates 8/8 — ver §4).
**Tesis de la épica:** *sin eval, cada cambio es un refactor a ciegas; con eval, cada cambio tiene veredicto.* Aplicada literalmente en los 7 niveles.

---

## 1 · Resumen ejecutivo

| Nivel | Qué | Veredicto medido | Estado |
|---|---|---|---|
| **N1** | Instrumento + golden + gate | 3 bugs del instrumento arreglados; VAL-163 re-emitido | ✅ cerrado |
| **N2** | Grounding 2 etapas (enrichment + rerank) | grounded 0.920 vs 0.936 (peor), hedging baja → **NO wirea** | ⚖️ medido, gate honesto |
| **N3** | GraphRAG (preguntas globales) | 6 rondas: wins 0→3→4→7→10→**15**; **gate v6 CERTIFICADO** (test virgen 3/3, forbidden 0) | ✅ certificado + wireado opt-in |
| **N4** | Write-path con revisión humana | 5 slices, ciclo cerrado **validado en vivo** | ✅ cerrado |
| **N5** | Citación (toda afirmación cita o marca inferencia) | instrumento gobernado; **active re-query = el lever**, wireado gated | ✅ instrumento + lever |
| **N6** | Destilación (hint-packs → pesos) | precursores (dataset 72 QA + barra); training → operador | ✅ precursores |
| **N7** | Flywheel (conocimiento que compone) | instrumentado + ratchet (145 eval cases, 4 gates) | ✅ instrumentado |

**Claim defendible del producto:** el modo GraphRAG responde las 15 preguntas globales del golden que el análisis plano falla estructuralmente (0.00–0.50 → community 1.00, **0 alucinaciones de granularidad** en el test virgen certificado). El claim *"el registry mejora la grounded-rate"* queda **prohibido** (refutado n=3). El aprendizaje entre runs ya **no compone con autoridad sin revisión humana** (N4). Toda afirmación de agente se **mide** contra su citación (N5).

---

## 2 · El track record del método (el valor real)

**33 commits, ~100 tests nuevos en suites dedicadas, 145 casos de eval gobernados, 8 runbooks por nivel.** Pero lo que da credibilidad son los **veredictos negativos honestos** — el método atrapó lo que un "ship and claim" hubiera vendido mal:

- **N2**: el enrichment 6→79 entradas **no mejora la tasa** (0.920 vs 0.936) → no se wireó. Gate honesto.
- **N3 v5**: 10 wins, pero el test virgen oficial dio 1/2 por **2 falsos positivos del juez** (forense: 11.07% vs 11.08% con ±2pp). No se certificó hasta v6 con par virgen nuevo bajo juez calibrado (3/3).
- **N5 slice 3**: la directiva de citación dio **−37pp en la rep 1** — pero la mediana de 3 reps fue −6.7pp con una rep *peor*. **Era ruido de muestreo del LLM.** Reportar 1 rep hubiera sido un falso-win de 37 puntos.
- **N5 slice 4**: el lever de resolución de citas **no existe** (diagnosticado: `claim.source_query` es código muerto en `_verify_claim`; los uncited son agregados computados ausentes de los datos raw).
- **VAL-162 (bonus)**: el overclaim de la causa del misterio de sales, corregido tras replay.

**Bugs de instrumento que los propios experimentos encontraron (8):** numéricos string como alucinación; intervalos Postgres como fechas; el grafo N3 corrigió la referencia que no leía `recency_days` (convergencia al centavo); share de segmento internamente inconsistente; listas leídas como rankings; el `setdefault` que creaba keys de columnas no-numéricas en el diagnóstico N5; etc.

**Gotcha operativo recurrente:** el auto-updater de Claude Code dejó el symlink del CLI en `claude.exe` (binario Windows) a mitad de un juicio → scores 0.00 espurios. Detectado por el patrón todo-cero; fix = binario nativo Linux v2.1.177 a ruta estable + `DISABLE_AUTOUPDATER=1`.

---

## 3 · Por nivel

**N1 — el instrumento.** `narrator_metrics.py` v2: parsea numéricos string e intervalos, enmascara fechas/Q/rank-labels, bucket de estimados declarados, frontera por evidencia. Golden 39 casos (26/13, verificados adversarialmente, 0 flags), gate en CI. Re-emitió VAL-163: **claim de tasa refutado** (Δ≈0); registry keep always-on por comportamiento (−40% números no citables, −36% largo, +58% hedging honesto).

**N2 — grounding 2 etapas.** Enrichment genérico del registry (5 queries legacy → 79 entradas) + rerank LLM-propone/código-confirma. A/B: grounded 0.920 (enriquecido) vs 0.936 (registry chico de VAL-163) vs 0.932 (control) — el enriquecido es **peor** + hedging baja (confianza sin grounding) → **gate falla, prod intacto, queda opt-in**. Lección de prompt: pedir derivación semántica, el código hace la aritmética.

**N3 — GraphRAG.** Grafo de entidades determinista a nivel instancia (resolución cross-query, hub-detach + CNM + refinement "Leiden-equivalente a n<500", PPR numpy) + **biblioteca de agregados servidos** + LLM que narra y nunca calcula + juez de 2 capas con referencias por joins independientes verificadas adversarialmente. **6 rondas eval-gated** (v1 0 → v6 15 wins). **v6 CERTIFICADO**: par virgen q22/q24/q25, community 1.00/1.00/1.00, forbidden 0, gate (≥5 ∧ ≥2 test) passed, auditoría adversarial de 9 escépticos superada. Conclusión arquitectural (4 rondas): el techo de capacidad ES la biblioteca de agregados. **Wireado** detrás de `VALINOR_GRAPHRAG=1` (A/B del wiring: grounded-rate plana → opt-in, el valor está en cobertura de preguntas globales).

**N4 — write-path.** El refinement y la auto-escalación dejaban de ser write-directo. **5 slices**: (B) refinement → propose/review/merge con procedencia; (A) findings con procedencia + auto-escalación gateada; audit trail (`/api/audit`); consumidor frontend (página de revisión, brand D4C); **flip del default + validación en vivo** (stack real: escalación MEDIUM→HIGH estacionada → approve por HTTP → severidad aplicada+persistida → evento en Redis). Gateado por `VALINOR_MEMORY_REVIEW` (review-on por defecto tras la validación). **El loop cierra**: pipeline propone con procedencia → operador revisa en UI → approve aplica / reject archiva → audit log.

**N5 — citación.** Instrumento `agent_grounding_metrics.py` (uncited_rate sobre claims atómicos: cited/failed/unresolvable/uncited/declared) + golden gate CI. Wireó `value_confidence` typed (el agente ya marca inferencias). **Baseline Gloria: de 30 claims MEASURED, 16 (53%) sin cita.** Enforcement diagnosticado a fondo: prompt-side **ruidoso** (slice 3), resolución-de-cita **inexistente** (slice 4), **active re-query = EL lever** (slices 5-6, probado: offline uncited → con-DB cited; wireado gated por `VALINOR_ACTIVE_REQUERY`). Baseline con-DB demostrado (0.50 → 0.00 sobre SQLite consistente); número real-Gloria = comando del operador.

**N6 — destilación.** Sin GPU/stack de training → precursores eval-first. `gen_distill_qa.py`: **72 QA sintéticos** desde los 2 hint-packs (schema/ontología, NUNCA números de cliente, con procedencia + filtro de auto-consistencia + staleness por hash). Subconjunto frecuente (7 preguntas) = la barra. Anti-patrón guard: destilación es caché, no grounding. Training del LoRA = runbook turnkey del operador (GPU + base model + QLoRA + validar vs barra).

**N7 — flywheel.** `flywheel_scorecard.py` mide los 4 ejes de "la máquina viva": eval crece (145, N1 empezó en 39), grounding se sostiene (4 gated suites), conocimiento compone (2 hint-packs + 72 QA), costo marginal baja (entity_map cache → skip de cartographer). **Ratchet en CI**: el eval corpus nunca encoge. La tendencia longitudinal (costo↓/cliente) necesita data de producción multi-cliente.

---

## 4 · Antes vs ahora — verificación con tests reales (2026-06-16)

El cierre se cerró midiendo, no afirmando. Cada fila es *"el supuesto/claim era X → el test real dio Y"*. Recetas: E2E real `tests/test_pipeline_periods.py --run-slow` vía bridge `console_cli` + CLI estable v2.1.177 + `VALINOR_NARRATOR_MODEL=haiku` (SQLite sintético, sin proxy ni Gloria-PG); suite con `pytest -q`.

| Dimensión | Supuesto / claim ANTES | Medido AHORA (test real) | Veredicto |
|---|---|---|---|
| **Pipeline E2E real** | Los tests reales necesitan Gloria-PG + `claude_proxy` → deferidos al operador, no corribles localmente | Corrió de verdad vía `console_cli` + CLI estable + haiku: **3/3 períodos PASSED en 503s** — 1-month (18 facturas/€749k, 22 findings), 1-quarter (59/€2.29M, 20), 1-year (227/€9.07M, 23); **3/3 agentes, 0 conflicts, reconciliación ran=True** en los tres | Supuesto **corregido**: el path SQLite+`console_cli` SÍ corre local con el binario estable; solo el path Gloria-PG (`test_pipeline_production`) queda al operador |
| **Salud de la suite (higiene)** | ~51–61 fallos pre-existentes de order-pollution (VAL-193), magnitud asumida, "se convive" | Causa raíz aislada: **187 de 188** fallos eran **un solo mecanismo** (`asyncio.run()` deja el current loop en `None`, py3.10 → los tests sync posteriores con `get_event_loop()` crashean por orden). Fixture autouse en conftest → **188 → 1 fallo** | Supuesto **subestimaba**: era 187 (no ~51) y arreglable con 1 cambio central; el 1 restante es un test de Benford de **marzo, pre-épica** (no relacionado) |
| **Inertness del wiring (N3/N4/N5)** | Prod byte-idéntico con flags off (afirmado) | El E2E corrió **sin** `VALINOR_GRAPHRAG`/`VALINOR_ACTIVE_REQUERY` (off) y dio 3/3 verde → el default de prod quedó intacto bajo carga real | **Confirmado en vivo** |
| **Gates de eval (regresión)** | "4 suites con gate, verdes" (afirmado) | `test_eval_gate.py` (4) + `test_flywheel_scorecard.py` (4) = **8 passed** | Claim **confirmado empíricamente** |

**Lo que esto agrega al track record del método:** el cierre mismo produjo 2 correcciones de supuesto (el E2E real era corrible local; la pollution era 187 no ~51) y 1 fix de regresión que el sprint había introducido sin notar (N5 slice 6 rompió 2 asserts literales de `test_anti_hallucination_wiring` al envolver la llamada `VerificationEngine(...)` — arreglado asertando el invariante, no el one-liner). Misma disciplina que los 7 niveles: medir antes de afirmar.

## 5 · Shippeado vs deferido (todo lo deferido es del operador, turnkey)

**Shippeado y verde en CI:** los 7 instrumentos/gates, el GraphRAG certificado + wireado, el write-path completo (incl. frontend) validado en vivo, el lever de citación wireado gated, los datasets sintéticos de destilación, el scorecard del flywheel. Prod **inerte por defecto** en todo lo gateado (N3/N4/N5 opt-in por flag).

**Deferido al operador (runbooks listos, no blockers):**
1. **N5**: prender `VALINOR_ACTIVE_REQUERY=1` (tradeoff latencia) + baseline real con la DB de Gloria.
2. **N6**: GPU + base model + QLoRA sobre `qa_pairs.jsonl` + validar la claim vs la barra.
3. **N7**: correr el scorecard periódicamente en producción → la tendencia que prueba que la máquina vive.

---

## 6 · Inventario de artefactos

- **Docs por nivel:** `val-192-n2-grounding.md` · `val-192-n3-graphrag.md` (6 rondas) · `val-192-n3-narrator-ab.md` · `val-192-n4-writepath.md` · `val-192-n5-citations.md` · `val-192-n6-distillation.md` · `val-192-n7-flywheel.md` · este informe.
- **Instrumentos:** `narrator_metrics.py` (N1) · `graphrag.py` + `global_judge.py` (N3, congelados v6) · `agent_grounding_metrics.py` (N5) · `flywheel_scorecard.py` (N7).
- **Eval corpus (145):** narrator_grounding 39 · global_questions 20 · agent_grounding 14 · distill 72. Gates: N1, N3, N5, N6 + el ratchet N7.
- **Datasets sintéticos (sin data de cliente):** `evals/distill/qa_pairs.jsonl`, `evals/fixtures/references_demo.json`, los golden.
- **Runbooks reproducibles:** `agent_grounding_baseline.py` (--connection-string), `agent_citation_ab.py`, `uncited_claims_diagnose.py`, `gen_distill_qa.py`, `define_frequent_subset.py`.

---

## 7 · Cierre

La Máquina de Conocimiento no es un modelo más grande: es **el eval como gobernador de toda entrada** (índice/grafo/prompts/pesos), con cada nivel cerrado por su hito medible. El moat — hint-packs de ERP + labels confirmados + distribución LatAm-SME — está ahora **instrumentado** para componer: el eval crece, el grounding se sostiene, y el costo marginal tiene su reductor wireado. Lo que falta para *probar* que el flywheel gira es escala de producción, no más código.

El logro central no es ningún nivel individual sino el **método sostenido de punta a punta**: 7 niveles, varios veredictos negativos honestos, cero claims especulativos. Eso es lo que hace defendible cada "sí".

*Refs: VAL-192, VAL-163, VAL-161, VAL-162, VAL-145, VAL-175. Detalle por nivel en los runbooks citados.*
