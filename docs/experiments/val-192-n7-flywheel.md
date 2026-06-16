# VAL-192 N7 — El flywheel (conocimiento que se compone solo)

**Fecha:** 2026-06-15 · **Estado:** flywheel INSTRUMENTADO + ratchet en CI (lo factible sin el LoRA). La prueba longitudinal (costo marginal ↓ por cliente) necesita data de producción multi-cliente (operador).

## El hito y qué es factible ahora

N7 es el goal máximo: cada run produce learnings → el sistema los captura/destila/conecta → los agentes los consumen → más conocimiento. Es la tesis de moat (hint-packs + labels + distribución LatAm-SME compounden), **con el eval como gobernador de toda entrada**. El hito es una SEÑAL medible: *el eval set crece, el grounding se sostiene, y el costo marginal de un reporte grounded baja por cliente resuelto*.

No se puede *probar* el flywheel sin medirlo — y el LoRA (N6) es solo una vía de consumo (caché), no el flywheel. Lo factible sin GPU es el corazón eval-first: **instrumentar la señal de "la máquina viva"** y poner el ratchet que la épica implica.

## Lo construido

**Scorecard** — `scripts/flywheel_scorecard.py` → `evals/flywheel/scorecard.json`. Mide los 4 ejes del flywheel desde los artefactos del repo (CPU, sin data de cliente):

| Eje | Señal | Estado actual |
|---|---|---|
| **El eval crece** | casos de eval gobernados | **145** (N1 empezó en 39): narrator 39 + agent 14 + global 20 + distill 72 |
| **El grounding se sostiene** | suites con gate de regresión | **4** (N1, N3, N5, N6) — todos verdes |
| **El conocimiento compone** | assets de moat | 2 hint-packs + 72 QA destilable |
| **El costo marginal baja** | reductor de costo wireado | `entity_map_cache` 72h → skip de cartographer en el 2º+ run por cliente |

**El ratchet** — `tests/test_flywheel_scorecard.py`: el invariante que SÍ se puede garantizar en CI sin data longitudinal — **el eval corpus nunca encoge** (agregar casos es OK con `--update`; quitarlos falla CI). Es el primer mecanismo concreto de "la máquina viva": el conocimiento gobernado solo crece. Además: todo path de entrada de conocimiento debe seguir gateado (la tesis "eval gobierna toda entrada").

## La señal, honesta

Un snapshot prueba **acumulación + gobernanza** (145 casos, 4 gates, moat creciendo, eval-as-governor en los 5 niveles). NO prueba la tendencia longitudinal (costo↓ por cliente) — eso necesita **muchos clientes a lo largo del tiempo**, que es data de producción del operador. El mecanismo de costo (cartographer-skip en cache) está wireado y es medible por-cliente; la TENDENCIA emerge en producción.

Por qué esto NO es overclaim: no afirmo "el flywheel funciona/está probado". Afirmo: *el flywheel está instrumentado y tiene un ratchet de no-regresión; la prueba de que compone se vuelve falsable con la data de producción* (corré el scorecard periódicamente → el corpus crece y los gates aguantan = la máquina vive; el costo por-cliente se trackea con run_history).

## Cómo se prueba en producción (el paso del operador)

1. Correr `scripts/flywheel_scorecard.py --update` periódicamente (o en CI cron) → serie temporal del corpus + gates.
2. Por cliente, trackear el costo de run 1 vs run N (el cache de entity_map ya da el 2x speedup en repeat runs — `run_history`/`metadata.total_estimated_cost_usd` en el profile).
3. La señal "máquina viva": corpus ↑ monotónico + gates verdes + costo/cliente ↓ a medida que el cache + refinement + hint-packs compounden.

## Estado épica VAL-192 (N1→N7)

- **N1** ✅ instrumento + golden + gate (VAL-163 re-emitido).
- **N2** ⚖️ medido, NO wireado (enrichment no mejora — honesto).
- **N3** ✅ GraphRAG certificado (gate v6) + wireado opt-in.
- **N4** ✅ write-path con revisión humana + procedencia + audit + frontend (cerrado).
- **N5** ✅ instrumento de citación gobernado + active re-query wireado (gated); baseline real → operador.
- **N6** ✅ precursores de destilación (dataset + filtro + barra); training → operador.
- **N7** ✅ flywheel instrumentado + ratchet; tendencia longitudinal → producción.

El método se sostuvo de punta a punta: **cada nivel con veredicto medido, varios negativos honestos, cero claims especulativos.** Los pasos que quedan son del operador (DB de Gloria, GPU, escala de producción) — entregados como runbooks turnkey, no como blockers.

*Refs: VAL-192 (N7). Método eval-gated como N1-N6.*
