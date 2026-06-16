# VAL-192 N6 — Destilación (hornear hint-packs en pesos)

**Fecha:** 2026-06-15 · **Estado:** precursores eval-first shippeados (dataset + filtro + subconjunto frecuente + gate CI). **Training del LoRA deferido al operador (necesita GPU + base model + peft/trl).**

## El método (y por qué los precursores primero)

N6: generar QA sintético desde el conocimiento de discovery/hint-packs, filtrarlo con el eval harness, entrenar un LoRA chico que responda lo frecuente sin retrieval. **Restricción de feasibility:** este entorno no tiene GPU ni stack de training. Igual que el número real-Gloria de N5 necesita la DB del operador, el training de N6 necesita su GPU. Lo autónomo + eval-first son los **precursores** (dataset + filtro + barra), que son prerequisitos reales del training, no busy-work.

**Anti-patrón headline (la épica lo advierte):** *destilación es CACHÉ, no grounding* — pierde procedencia, se desactualiza. El primer slice NO toca el runtime path y NO destila números de cliente; solo facts de schema/ontología derivables de los hint-packs, con procedencia.

## Lo construido (sin GPU)

**1. Generador** — `scripts/gen_distill_qa.py` → `evals/distill/qa_pairs.jsonl`. Templa QA determinístico desde los 2 hint-packs (`argentina_gestion.yaml`, `retail_pos.yaml`) por sección: clasificación master/transactional, header-detail, columnas de fecha/booleanas, tipos fiscales (TipoComprobante/CondIVA/doc_type), clase semántica de columnas, orden de los business-flows. **72 pares (57 train / 15 test)**, 0 inconsistentes. Cada par lleva `provenance:{pack, section, key}`.

**2. Filtro de auto-consistencia** (la idea de containment de layer-0): cada `reference_answer` debe contener todos sus `required_facts`; los ambiguos/mal-templados se descartan. (72/72 pasaron.)

**3. Subconjunto frecuente** — `scripts/define_frequent_subset.py` → `evals/distill/frequent_subset.json`. Definición determinista desde `seed_entities` del golden (recurrencia = proxy de frecuencia): top-8 entidades (segmento 9, churn 7, riesgo 5, …) → **7 preguntas frecuentes** (q1/q9/q10/q14/q16/q18/q25). Es la barra que el LoRA debe igualar.

**4. Gate CI** — `tests/test_distill_qa.py` (6 tests): auto-consistencia, procedencia, **anti-números-de-cliente** (sin `€`/`$`, sin facts numéricos puros), **staleness** (hash de contenido de cada pack en el manifest — si un pack cambia sin regenerar, falla), split train/test, determinismo.

## La barra (baseline que el LoRA debe igualar)

El subconjunto frecuente (7 preguntas globales) ya tiene baseline medido por el sistema actual: el **brazo community de N3 (gloria-v6)** las responde mayormente **1.00** (clases de agregados servidos, certificadas en el gate v6). La claim falsable del LoRA: *"LoRA-sin-retrieval ≥ baseline en el test del subconjunto frecuente"*. Medible con el harness N3 existente (`eval.py graphrag --split test --csv`) filtrado a esos ids — sin training.

## Runbook de training (el paso del operador)

Turnkey: el dataset + la barra ya están. El operador (con GPU) corre:

1. **Infra**: GPU ≥16-24 GB VRAM; instalar `transformers` + `peft` + `trl` + `bitsandbytes` + `accelerate` (no están en deps — dead weight sin GPU).
2. **Base model**: elegir un instruct open de 7-8B (decisión deliberada de modelo + licencia, no un default).
3. **Train**: QLoRA 4-bit sobre `evals/distill/qa_pairs.jsonl` **split train** (las preguntas → reference_answer). Held-out = split test.
4. **Validar la claim**: correr el adapter por el MISMO harness (`eval.py graphrag`/`distill`) sobre el subconjunto frecuente **test** → comparar contra la barra. Documentar dónde pierde (la épica lo exige).

## Riesgos / cómo el slice evita overclaim

- **Caché ≠ grounding**: el LoRA memoriza conocimiento estático (familias de nombres, códigos fiscales, orden de flujos), NUNCA números de cliente (gate `test_no_client_numbers_distilled`). El artefacto vive en `evals/distill/`, fuera del runtime narrator path.
- **Staleness**: hash de packs en el manifest + gate CI → si un pack cambia sin regenerar, falla en CI (no en prod).
- **Independencia del eval**: los golden sets (N1/N3/N5) son el *instrumento*, NO el training set; la QA sintética es un dataset *separado* filtrado *con* ellos. No colapsar (eval circular).
- **Sin overclaim**: este slice shippea **cero pesos** y **cero claims de capacidad** del LoRA. Entregable honesto: dataset frozen + filtrado + procedencia + barra + gate + runbook. Veredicto: *precursores shippeados, training deferido (GPU del operador)* — direccional, no "N6 done" (como N2 fue "medido y NO wireado", no oversold).

## Estado / próximo

Precursores ✅ (dataset 72 pares, filtro, subconjunto frecuente, gate). **Pendiente del operador:** GPU + base model + QLoRA + validar la claim vs la barra. Después N7 (el flywheel).

*Refs: VAL-192 (N6). Substrato: `core/valinor/discovery/erp_hints/`. Método eval-gated como N1-N5.*
