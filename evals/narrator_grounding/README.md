# Narrator grounding eval — N1 de la Máquina de Conocimiento (VAL-192)

> *Sin eval, cada cambio es un refactor a ciegas; con eval, cada cambio tiene
> veredicto.* Este directorio es el gobernador: el instrumento que mide
> grounding de narrators se valida acá antes de creerle a cualquier número.

## Qué hay acá

| Archivo | Qué es |
|---|---|
| `golden.yaml` | Golden set versionado: ~40 casos `texto + contexto → clasificación esperada por número`. **Todo sintético — nunca datos de cliente.** |
| `baseline.json` | Métrica de gate committeada (`case_accuracy/test/default`). |
| `README.md` | Este doc: las decisiones de frontera y su evidencia. |

```bash
venv/bin/python scripts/eval.py golden            # tabla por config × split
venv/bin/python scripts/eval.py golden --gate     # regression gate (CI: tests/test_eval_gate.py)
venv/bin/python scripts/eval.py golden --update-baseline   # tras un cambio DELIBERADO
```

## Train/test split (no negociable)

~30% de los casos son `split: test`. **Nadie tunea el instrumento mirando los
casos de test** — se tunea contra train, el gate corre contra test. Mover un
caso de split o cambiar un label de test es un cambio de spec, se hace explícito
en el commit.

## Los tres bugs del instrumento (2026-06-09) y sus fixes

El primer datapoint real del A/B VAL-163 (briefing_ceo sobre datos reales)
reveló que el instrumento medía ruido:

- **Bug-1 — numéricos string**: los drivers serializan NUMERIC como string
  (`"364517.30"`) e intervalos como `"147 days, 0:00:00"`. El instrumento los
  salteaba → números reales marcados como alucinados (caso ancla: ltv de un
  cliente top marcado hallucinated siendo grounded). Fix: `_parse_string_numeric`
  (numéricos puros e intervalos sí; fechas/UUIDs no).
- **Bug-2 — fechas como claims**: "10 mayo 2026", "2025-01-02" (→ "01"/"02"),
  "14:05:56", "Q1", "top-50" contaban como números citados. Fix: máscara de
  spans (fechas/horas/rank-labels) + lookbehind/boundary en el regex
  (también arreglla "### 2. Base" → 2MM millones y "€183.906 bajo" → billones).
  Las duraciones ("147 días") SÍ son claims — y groundean vía Bug-1.
- **Bug-3 — derivados legítimos**: la frontera se decidió **con evidencia**
  (medido sobre los narrators reales del run 2026-05-08):
  1. **Prosa de findings es input**: si Sentinel escribió "doble conteo de
     €20,520–€51,300", el narrator que lo repite es fiel a su input, no
     fabrica → esos números entran al ground truth.
  2. **Estimaciones declaradas** (`[ESTIMADO]`, `[INFERIDO]`, `~`, `(estimado)`)
     siguen el protocolo de honestidad del pipeline → bucket `declared`,
     fuera del denominador verificable. Las palabras de hedging
     ("aproximadamente") NO son marcadores — el caso canónico €13.5M sigue
     contando como alucinación.
  3. **Derivados within-column** (Δ MoM, share-of-total, suma de columna):
     config opt-in `derived`, OFF por defecto. El crediting pairwise
     cross-corpus quedó **refutado**: con ~600 valores de truth acredita
     números arbitrarios de planes de acción ("Top 200", "Siguientes 500") —
     cegaría la métrica.

## Limitaciones documentadas (honestas, no TODOs vergonzantes)

- **Números de plan de acción** ("llamar a 200 cuentas", "3–5 cuentas medianas")
  cuentan como ungrounded: son propuestas del narrator, no datos. Separar
  "claim de dato" vs "propuesta" requiere clasificación semántica (LLM-judge,
  llega con N3).
- **Utilidad** no se mide acá — necesita LLM-as-judge (N3).
- **Tolerancia 10K–1M = 0.1%** (espejo de `_values_match`): citar €412.881,55
  como "€410K" (0.7% off) cuenta ungrounded. Si esto duele en la práctica, el
  cambio se hace en `VerificationEngine._values_match` y acá en espejo, con
  labels actualizados deliberadamente.
- El gate corre el config `default`; `derived` se reporta como dimensión
  comparativa (eso pide el hito N1: tabla por configuración).

## Relación con VAL-163

El A/B del Number Registry se scorea con este instrumento ya arreglado:
`scripts/eval.py ab --dir docs/experiments/val-163` (multi-rep, mean ± std,
detección de capturas corruptas). El veredicto vive en
`docs/experiments/val-163-number-registry-ab.md`.

Refs: VAL-192 (N1), VAL-163
