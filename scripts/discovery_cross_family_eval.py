#!/usr/bin/env python3
"""
Cross-family (cross-pilot) generalization eval (VAL-145 §7).

Runs the hint-pack ablation (VAL-175 mechanism) across TWO ERP families — the
Argentine gestión family (golden_dataset.py) and the Retail POS family
(golden_dataset_retail.py) — to answer the §7 generalization question:

  * Does deterministic structural inference generalize across families?
    → measured on the *_full variants (ensemble, no hint pack).
  * Does each family's hint pack help on its OWN no-FK schema? (per-family curation)
    → the diagonal of the ablation matrix should be POSITIVE.
  * Does a family's hint pack leak onto the OTHER family? (specificity)
    → the off-diagonal should be ~0.

Deterministic (MockLLMClient): reproducible, free, fast — no live LLM.

Usage:
    python scripts/discovery_cross_family_eval.py
        [--report docs/experiments/val-145-cross-family-generalization.md]
        [--json   docs/experiments/val-145-cross-family-generalization.json]

Refs: VAL-145 (relates VAL-175)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from valinor.discovery.benchmark import EnsembleBenchmark  # noqa: E402
from valinor.discovery.erp_hints import load_hint_pack  # noqa: E402
from valinor.discovery.golden_dataset import (  # noqa: E402
    build_golden_sqlite,
    load_golden_dataset,
)

FAMILIES = [
    {"key": "gestion", "label": "Argentine gestión", "own_hint": "gestion",
     "no_fks": "gloria_no_fks", "full": "gloria_full"},
    {"key": "retail", "label": "Retail POS", "own_hint": "retail",
     "no_fks": "retail_no_fks", "full": "retail_full"},
]

# hint key → (country, erp_type, registry name) for load_hint_pack
_HINT_KEYS = {
    "gestion": ("argentina", "gestion", "argentina_gestion"),
    "retail": ("retail", "pos", "retail_pos"),
}


def _hint(hint_key: str):
    """Return (hint_pack_dict_or_None, hint_pack_name)."""
    if hint_key == "none":
        return None, ""
    country, erp, name = _HINT_KEYS[hint_key]
    return load_hint_pack(country, erp), name


def _recall(variant: str, hint_key: str) -> float:
    hp, name = _hint(hint_key)
    conn = build_golden_sqlite(variant)
    try:
        golden = load_golden_dataset(variant)
        return EnsembleBenchmark(golden, conn, hint_pack=hp, hint_pack_name=name).run().fk_recall
    finally:
        conn.close()


def build_cross_family_matrix() -> dict:
    """Compute the cross-family ablation matrix + structural generalization. Pure."""
    hint_cols = ["none"] + list(_HINT_KEYS)  # none, gestion, retail
    ablation = {}
    for fam in FAMILIES:
        cells = {hk: round(_recall(fam["no_fks"], hk), 4) for hk in hint_cols}
        base = cells["none"]
        own = fam["own_hint"]
        cross = [hk for hk in _HINT_KEYS if hk != own]
        ablation[fam["key"]] = {
            "recall": cells,
            "own_delta": round(cells[own] - base, 4),
            "cross_delta_max": round(max((cells[hk] for hk in cross), default=0.0) - base, 4),
        }

    structural = {
        fam["key"]: round(
            EnsembleBenchmark(
                load_golden_dataset(fam["full"]),
                build_golden_sqlite(fam["full"]),
            ).run().fk_recall, 4)
        for fam in FAMILIES
    }

    # Honest verdicts derived from the numbers.
    own_positive = all(a["own_delta"] > 0 for a in ablation.values())
    cross_zero = all(a["cross_delta_max"] <= 1e-9 for a in ablation.values())
    structural_generalizes = all(v >= 0.8 for v in structural.values())

    return {
        "determinism": "MockLLMClient (reproducible)",
        "hint_columns": hint_cols,
        "families": [{"key": f["key"], "label": f["label"], "own_hint": f["own_hint"]}
                     for f in FAMILIES],
        "ablation_no_fks": ablation,
        "structural_full_recall": structural,
        "verdicts": {
            "per_family_curation_works": own_positive,
            "hint_packs_are_specific": cross_zero,
            "structural_inference_generalizes": structural_generalizes,
        },
    }


def render_markdown(m: dict) -> str:
    fams = m["families"]
    L = ["# VAL-145 — Cross-family generalization (paper §7)", "",
         f"Determinism: {m['determinism']}.", "",
         "Two ERP families, deliberately disjoint in naming "
         "(gestión: `Cod*`/`Nro*` + `Cab`/`Det`; retail: `Id`-suffix + `Header`/`Lines`).", "",
         "## Hint-pack ablation on no-FK schemas (FK recall)", "",
         "Rows = data family; columns = hint pack applied. **Diagonal** = own hint, "
         "**off-diagonal** = other family's hint.", ""]

    headers = ["Data family \\ hint"] + [hk for hk in m["hint_columns"]]
    rows = []
    for f in fams:
        cells = m["ablation_no_fks"][f["key"]]["recall"]
        marked = []
        for hk in m["hint_columns"]:
            v = cells[hk]
            if hk == f["own_hint"]:
                marked.append(f"**{v}** (own)")
            elif hk != "none":
                marked.append(f"{v} (cross)")
            else:
                marked.append(str(v))
        rows.append([f["label"]] + marked)
    L += ["| " + " | ".join(headers) + " |",
          "|" + "|".join("---" for _ in headers) + "|"]
    L += ["| " + " | ".join(r) + " |" for r in rows]

    L += ["", "## Deltas vs no-hint", "",
          "| Data family | own-hint Δrecall | best cross-hint Δrecall |",
          "|---|---|---|"]
    for f in fams:
        a = m["ablation_no_fks"][f["key"]]
        L.append(f"| {f['label']} | **{a['own_delta']:+}** | {a['cross_delta_max']:+} |")

    L += ["", "## Structural inference on full schemas (ensemble, no hint)", "",
          "| Data family | FK recall |", "|---|---|"]
    for f in fams:
        L.append(f"| {f['label']} | {m['structural_full_recall'][f['key']]} |")

    v = m["verdicts"]
    L += ["", "## Verdicts (from the numbers)", "",
          f"- Per-family hint-pack curation works (own Δ > 0): **{v['per_family_curation_works']}**",
          f"- Hint packs are family-specific (cross Δ ≈ 0): **{v['hint_packs_are_specific']}**",
          f"- Structural inference generalizes across families: **{v['structural_inference_generalizes']}**",
          ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-145 cross-family generalization eval")
    ap.add_argument("--report",
                    default="docs/experiments/val-145-cross-family-generalization.md")
    ap.add_argument("--json",
                    default="docs/experiments/val-145-cross-family-generalization.json")
    args = ap.parse_args(argv)

    matrix = build_cross_family_matrix()
    md = render_markdown(matrix)
    print(md)
    for path, payload in ((args.report, md), (args.json, json.dumps(matrix, indent=2))):
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8")
        print(f"\nwrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
