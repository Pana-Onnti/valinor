# VAL-192 N3 — A/B de narrators con GraphRAG (eval-first del wiring)

**Fecha:** 2026-06-14 · **Estado:** N3 wireado detrás de `VALINOR_GRAPHRAG=1` (inerte por defecto) · **Veredicto del A/B: tasa PLANA → queda OPT-IN, no on-by-default.**

## Qué mide

El gate de "prender N3 por defecto" para los reportes estándar. Calca el A/B de VAL-163 (`scripts/run_capture_ab_live.py --graphrag` → `ab_test_number_registry.py`): los 4 narrators reales corren 2× sobre el MISMO estado capturado de Gloria, **ambos brazos con el Number Registry** (baseline de prod), difiriendo SOLO en el contexto del grafo:

- **control** — `run_narrators(..., graph_context=None)` (comportamiento actual de prod)
- **treatment** — `run_narrators(..., graph_context=<bloque determinista de agregados>)` (`VALINOR_GRAPHRAG=1`)

Ground-truth = registry legacy ∪ agregados deterministas del grafo (333 entradas) — sin la unión, el treatment quedaría penalizado por citar agregados CORRECTOS que el registry de 5 queries no conocía (artefacto de medición, no regresión). Modelo haiku vía CLI local, sales stubeado (VAL-162), 2 reps.

## Resultado (2 reps, briefing_ceo + reporte_ejecutivo)

| Métrica | Control | Treatment | Δ (treat−ctrl) |
|---|---|---|---|
| Grounded rate — rep 1 | 0.9066 | 0.8954 | **−0.011** |
| Grounded rate — rep 2 | 0.9147 | 0.9127 | **−0.002** |
| Números alucinados (abs) — rep 1 | 35 | 34 | −1 |
| Números alucinados (abs) — rep 2 | 37 | 34 | −3 |
| Hedging /100 palabras — rep 1 | 0.587 | 0.282 | −0.305 |
| Hedging /100 palabras — rep 2 | 0.364 | 0.466 | +0.102 |

Contexto del grafo inyectado: 2962 chars (`graph_context_injected: True`). Por-narrator: deltas mixtos y chicos (±0.05), dentro del ruido de muestreo a n=2.

## Veredicto

**La grounded-rate queda PLANA** (Δ dentro del ruido). Los números alucinados bajan marginalmente; el hedging es ruidoso sin dirección. **No hay mejora medible de la tasa por inyectar el contexto del grafo en los reportes estándar.**

Es el resultado correcto y esperable: la grounded-rate mide si los números del reporte trazan al ground-truth, y los narrators ya estaban ~0.91 grounded sobre el registry. El **valor de N3 es la cobertura de PREGUNTAS GLOBALES** que el análisis plano falla estructuralmente — eso ya está **CERTIFICADO** en el gate v6 (flat 0.00 → community 1.00, test virgen 3/3, ver `val-192-n3-graphrag.md` §v6). Este A/B mide algo distinto (¿el contexto del grafo hace MÁS grounded los reportes de audiencia?) y la respuesta honesta es **no, a tasa constante**.

**Decisión (eval-first, mismo patrón que N2):** N3 queda **OFF por defecto** (`VALINOR_GRAPHRAG` sin setear → pipeline byte-idéntico). La capacidad está **wireada y disponible opt-in** para el caso de preguntas globales, donde SÍ está certificada. El gate de on-by-default no se cumple sobre la grounded-rate.

## Reproducir

```bash
DISABLE_AUTOUPDATER=1 venv/bin/python scripts/run_capture_ab_live.py --graphrag \
  --state docs/experiments/val-163/state.json \
  --out-dir docs/experiments/val-192-n3/narrator-ab \
  --reps 2 --model haiku --cli-path /tmp/claude-stable-v2 \
  --only briefing_ceo,reporte_ejecutivo
# luego: scripts/ab_test_number_registry.py --control … --treatment … --dataset … por rep
```

Harness offline (unit-tested, sin LLM): `scripts/graphrag_narrator_ab.py` · `core/valinor/graphrag_context.py` · `tests/test_graphrag_wiring.py`. Outputs con texto de cliente: gitignored bajo `docs/experiments/val-192-n3/narrator-ab/`.

*Refs: VAL-192 (N3 wiring). Relaciona VAL-163 (el A/B que calca), VAL-162 (stub de sales).*
