# VAL-145 — Cross-family generalization (paper §7)

Determinism: MockLLMClient (reproducible).

Two ERP families, deliberately disjoint in naming (gestión: `Cod*`/`Nro*` + `Cab`/`Det`; retail: `Id`-suffix + `Header`/`Lines`).

## Hint-pack ablation on no-FK schemas (FK recall)

Rows = data family; columns = hint pack applied. **Diagonal** = own hint, **off-diagonal** = other family's hint.

| Data family \ hint | none | gestion | retail |
|---|---|---|---|
| Argentine gestión | 0.0 | **0.125** (own) | 0.0 (cross) |
| Retail POS | 0.0 | 0.0 (cross) | **0.75** (own) |

## Deltas vs no-hint

| Data family | own-hint Δrecall | best cross-hint Δrecall |
|---|---|---|
| Argentine gestión | **+0.125** | +0.0 |
| Retail POS | **+0.75** | +0.0 |

## Structural inference on full schemas (ensemble, no hint)

| Data family | FK recall |
|---|---|
| Argentine gestión | 0.875 |
| Retail POS | 0.875 |

## Verdicts (from the numbers)

- Per-family hint-pack curation works (own Δ > 0): **True**
- Hint packs are family-specific (cross Δ ≈ 0): **True**
- Structural inference generalizes across families: **True**
