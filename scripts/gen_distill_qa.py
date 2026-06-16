#!/usr/bin/env python3
"""
N6 distillation QA generator (VAL-192).

Generates a synthetic QA dataset from the ERP hint-packs (the distillable moat
knowledge) — the TRAINING data a future LoRA would cache into weights. Each pair
is a SCHEMA / CLASSIFICATION / ONTOLOGY fact derivable deterministically from a
hint-pack — NEVER a client number (distillation is cache, not grounding; the
runtime grounding path is untouched). Every pair carries provenance
``{pack, section, key}`` so it's auditable and staleness is detectable.

Pipeline: load packs → template QA per section → self-consistency FILTER
(reference_answer must contain its required_facts, the layer-0 containment idea)
→ deterministic 70/30 train/test split → write evals/distill/qa_pairs.jsonl +
manifest.json (with per-pack content hashes for the CI staleness gate).

NO GPU, no LLM, pure CPU. The LoRA training step is the operator's (see the N6
runbook): needs GPU + a base model + peft/trl.

Refs: VAL-192 (N6)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from valinor.discovery.erp_hints import load_hint_pack  # noqa: E402

_HINTS_DIR = ROOT / "core" / "valinor" / "discovery" / "erp_hints"
OUT_DIR = ROOT / "evals" / "distill"

# (country, erp_type, yaml_filename, human family label)
PACKS = [
    ("argentina", "gestion", "argentina_gestion.yaml", "un ERP de gestión argentino"),
    ("retail", "pos", "retail_pos.yaml", "un sistema retail/POS"),
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _pair(pack, section, key, question, answer, facts):
    """Build a QA pair dict (split assigned later)."""
    return {
        "question": question,
        "reference_answer": answer,
        "required_facts": facts,
        "provenance": {"pack": pack, "section": section, "key": str(key)},
    }


def _gen_from_pack(pack_id: str, fam: str, hp: dict):
    """Template QA pairs from one hint pack. Schema/ontology facts only."""
    out = []
    tp = hp.get("table_patterns", {})

    # Master / transactional table classification.
    for kind, label in (("master_tables", "MASTER"), ("transactional_tables", "TRANSACTIONAL")):
        for row in tp.get(kind, []):
            if not isinstance(row, dict):
                continue
            pat, ent = row.get("pattern", ""), row.get("entity", "")
            if not pat or not ent:
                continue
            out.append(_pair(
                pack_id, f"table_patterns.{kind}", pat,
                f"En {fam}, ¿qué tipo de entidad es una tabla con nombre `{pat}` y qué representa?",
                f"`{pat}` → entidad {label} ({ent}).",
                [label, ent],
            ))

    # Header/detail document layout.
    hd = tp.get("header_detail", {})
    heads, dets = hd.get("header_suffixes", []), hd.get("detail_suffixes", [])
    if heads and dets:
        out.append(_pair(
            pack_id, "table_patterns.header_detail", dets[0],
            f"En {fam}, una tabla de documento con sufijo `{dets[0]}` (detalle), "
            f"¿con qué sufijo de cabecera se aparea?",
            f"Con `{heads[0]}` (layout header-detail: la cabecera tiene totales/fechas, "
            f"el detalle las líneas).",
            [heads[0]],
        ))

    nc = hp.get("naming_conventions", {})
    # Date columns.
    for col in nc.get("date_patterns", [])[:6]:
        out.append(_pair(
            pack_id, "naming_conventions.date_patterns", col,
            f"En {fam}, ¿qué implica una columna llamada `{col}`?",
            f"`{col}` es una columna temporal (familia de fechas).",
            ["temporal"],
        ))
    # Boolean/status columns.
    for col in nc.get("boolean_patterns", [])[:5]:
        out.append(_pair(
            pack_id, "naming_conventions.boolean_patterns", col,
            f"En {fam}, ¿qué tipo de columna es `{col}`?",
            f"`{col}` es una columna booleana / flag de estado.",
            ["booleana"],
        ))

    # Fiscal document types + IVA condition (value-set facts).
    fp = hp.get("fiscal_patterns", {})
    for key in ("tipo_comprobante", "condicion_iva", "doc_type"):
        node = fp.get(key)
        if isinstance(node, dict) and node.get("values"):
            vals = node["values"]
            out.append(_pair(
                pack_id, f"fiscal_patterns.{key}", key,
                f"En {fam}, ¿qué valores toma `{key}`?",
                f"Valores de `{key}`: {', '.join(map(str, vals))}.",
                [str(vals[0]), str(vals[-1])],
            ))

    # Column semantic class.
    for cat, node in hp.get("column_hints", {}).items():
        if isinstance(node, dict) and node.get("patterns"):
            pat = node["patterns"][0]
            out.append(_pair(
                pack_id, "column_hints", cat,
                f"En {fam}, una columna `{pat}`, ¿qué clase semántica tiene?",
                f"`{pat}` es una columna de clase `{cat}`.",
                [cat],
            ))

    # Business-flow step ordering.
    for flow_name, node in hp.get("business_flows", {}).items():
        steps = [s.get("step") for s in node.get("flow", []) if isinstance(s, dict) and s.get("step")]
        if len(steps) >= 2:
            out.append(_pair(
                pack_id, f"business_flows.{flow_name}", flow_name,
                f"En {fam}, ordená los pasos del flujo `{flow_name}`.",
                " → ".join(steps) + ".",
                [steps[0], steps[-1]],
            ))
    return out


def _self_consistent(pair: dict) -> bool:
    """Filter: the reference_answer must contain every required_fact (the layer-0
    label-containment idea). Drops ambiguous / mis-templated pairs."""
    ans = _norm(pair["reference_answer"])
    return all(_norm(f) in ans for f in pair["required_facts"]) and bool(pair["required_facts"])


def _split(pair_id: str) -> str:
    """Stable 70/30 train/test split by content hash (not Python's salted hash)."""
    h = int(hashlib.sha1(pair_id.encode()).hexdigest(), 16)
    return "test" if (h % 10) < 3 else "train"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pairs, manifest_packs, generated, dropped = [], {}, 0, 0

    for country, erp, fname, fam in PACKS:
        hp = load_hint_pack(country, erp)
        if not hp:
            print(f"⚠ hint pack {fname} empty/missing — skipped", file=sys.stderr)
            continue
        pack_id = fname.replace(".yaml", "")
        manifest_packs[pack_id] = hashlib.sha1(
            (_HINTS_DIR / fname).read_bytes()).hexdigest()[:16]
        for p in _gen_from_pack(pack_id, fam, hp):
            generated += 1
            if not _self_consistent(p):
                dropped += 1
                continue
            pid = f"{pack_id}:{p['provenance']['section']}:{p['provenance']['key']}"
            pairs.append({"id": pid, "split": _split(pid), **p})

    pairs.sort(key=lambda r: r["id"])
    (OUT_DIR / "qa_pairs.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in pairs) + "\n", encoding="utf-8")
    n_train = sum(1 for r in pairs if r["split"] == "train")
    manifest = {
        "n_pairs": len(pairs), "n_train": n_train, "n_test": len(pairs) - n_train,
        "generated": generated, "dropped_inconsistent": dropped,
        "pack_hashes": manifest_packs,
        "note": "Synthetic QA from ERP hint-packs (schema/ontology facts only — NOT "
                "client numbers). Training data for a future LoRA; cache, not grounding.",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
