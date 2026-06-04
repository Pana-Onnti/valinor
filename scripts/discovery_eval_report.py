#!/usr/bin/env python3
"""
Discovery Engine empirical eval report (VAL-145, paper §7).

Consolidates the golden-dataset benchmark (VAL-129/VAL-175) into the evaluation
artifact the paper's §7 consumes: FK inference per baseline, the ERP hint-pack
ablation (the original contribution), entity-classification accuracy, latency/cost,
and a check against the §7 metric targets — written to docs/experiments/.

Baseline mapping (benchmark mode → paper §7 baseline):
    fk_only          → "Structural-only"     (statistical inclusion + name sim)
    ensemble         → "Ours (no hint pack)"  (4-agent ensemble, DomainAgent idle)
    ensemble_hinted  → "Ours (full)"          (4-agent ensemble + ERP hint pack)

DETERMINISM: runs with the MockLLMClient by default (reproducible, free, fast), so
the structural FK numbers, the hint-pack ablation, and entity classification are
REAL and citable. The marginal FK contribution of the semantic/process *LLM* agents
(and a true "LLM-only" baseline) require a real-LLM run — that's the remaining step,
analogous to VAL-163's live capture. Targets that depend on it are flagged.

Usage:
    python scripts/discovery_eval_report.py
        [--report docs/experiments/val-145-discovery-eval.md]
        [--json docs/experiments/val-145-discovery-eval.json]

Refs: VAL-145 (relates VAL-175, VAL-142)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from valinor.discovery.benchmark import (  # noqa: E402
    hint_pack_deltas,
    run_all_variants,
)

# benchmark mode → (paper §7 baseline label, ordering)
_BASELINE = {
    "fk_only": "Structural-only",
    "ensemble": "Ours (no hint pack)",
    "ensemble_hinted": "Ours (full)",
}

# §7 metric targets (VAL-145).
_TARGETS = {
    "fk_recall_no_constraints": 0.85,
    "fk_precision": 0.90,
    "entity_accuracy": 0.90,
    "latency_seconds": 30.0,
    "cost_usd": 0.50,
}

# Variants whose schema has NO declared FK constraints (the hard, real-world case).
_NO_CONSTRAINT_VARIANTS = ("gloria_no_fks", "gloria_obfuscated")


def build_eval_report(results: list) -> dict:
    """Assemble the §7-shaped evaluation report from benchmark results. Pure."""
    rows = [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in results]

    fk_table = [
        {
            "variant": r["variant"],
            "baseline": _BASELINE.get(r["mode"], r["mode"]),
            "mode": r["mode"],
            "fk_recall": r["fk_recall"],
            "fk_precision": r["fk_precision"],
            "fk_f1": r["fk_f1"],
            "predicted": r["total_predicted"],
            "golden": r["total_golden"],
        }
        for r in rows
    ]

    ablation = hint_pack_deltas(results)

    entity_table = [
        {"variant": r["variant"], "entity_accuracy": r["entity_accuracy"]}
        for r in rows if r["mode"] == "ensemble_hinted"
    ]

    cost_latency = [
        {
            "baseline": _BASELINE.get(r["mode"], r["mode"]),
            "variant": r["variant"],
            "latency_seconds": r["elapsed_seconds"],
            "llm_calls": r["llm_calls"],
            "cost_usd": r["llm_cost_usd"],
        }
        for r in rows
    ]

    targets = _check_targets(rows, ablation)

    return {
        "determinism": "MockLLMClient (reproducible); real-LLM agent contribution pending",
        "baselines": _BASELINE,
        "fk_inference": fk_table,
        "hint_pack_ablation": ablation,
        "entity_classification": entity_table,
        "cost_latency": cost_latency,
        "targets": targets,
        "remaining": [
            "Real-LLM run: semantic + business-process agent FK contribution and a "
            "true LLM-only baseline (needs the proxy/API up; the golden set is tiny "
            "so the run is cheap — ~Haiku calls — but non-deterministic).",
            "Scalability sweep (50 / 200 / 500 tables) — needs larger golden schemas.",
            "Cross-pilot generalization — needs a 2nd real ERP family (plug a second "
            "hint pack / golden variant into the VAL-175 ablation mechanism).",
            "Per-layer (L0-L5) latency/cost breakdown — needs pipeline instrumentation.",
        ],
    }


def _check_targets(rows: list, ablation: dict) -> list:
    """Compare measured (deterministic) values against the §7 targets, honestly."""
    full = {r["variant"]: r for r in rows if r["mode"] == "ensemble_hinted"}

    # FK recall on no-constraint variants (the hard case), Ours (full).
    nc = [full[v]["fk_recall"] for v in _NO_CONSTRAINT_VARIANTS if v in full]
    recall_nc = min(nc) if nc else 0.0
    # FK precision: min across Ours (full) variants that predicted anything.
    precs = [full[v]["fk_precision"] for v in full if full[v]["total_predicted"] > 0]
    precision = min(precs) if precs else 0.0
    entity = min((full[v]["entity_accuracy"] for v in full), default=0.0)
    latency = max((full[v]["elapsed_seconds"] for v in full), default=0.0)
    cost = max((full[v]["llm_cost_usd"] for v in full), default=0.0)

    def row(metric, measured, target, op, note=""):
        met = op(measured, target)
        return {"metric": metric, "measured": round(measured, 4),
                "target": target, "met": met, "note": note}

    ge = lambda a, b: a >= b  # noqa: E731
    le = lambda a, b: a <= b  # noqa: E731
    return [
        row("FK recall (no-constraint schemas)", recall_nc,
            _TARGETS["fk_recall_no_constraints"], ge,
            "deterministic structural+hint only — real-LLM agents pending"),
        row("FK precision (Ours full)", precision, _TARGETS["fk_precision"], ge),
        row("Entity classification accuracy", entity,
            _TARGETS["entity_accuracy"], ge,
            "deterministic ontology builder"),
        row("Discovery latency (s)", latency, _TARGETS["latency_seconds"], le,
            "MockLLM; real-LLM adds agent round-trips"),
        row("Cost per analysis (USD)", cost, _TARGETS["cost_usd"], le,
            "MockLLM = $0; real-LLM ensemble ~2 Haiku calls/variant"),
    ]


def _md_table(headers: list, rows: list) -> list:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return out


def render_markdown(report: dict) -> str:
    L = ["# VAL-145 — Discovery Engine empirical eval (paper §7)", "",
         f"Determinism: {report['determinism']}.", "",
         "Baseline mapping: " + ", ".join(
             f"`{m}` → {b}" for m, b in report["baselines"].items()), ""]

    L += ["## FK inference", ""]
    L += _md_table(
        ["Variant", "Baseline", "Recall", "Precision", "F1", "Pred", "Gold"],
        [[r["variant"], r["baseline"], r["fk_recall"], r["fk_precision"],
          r["fk_f1"], r["predicted"], r["golden"]] for r in report["fk_inference"]])

    L += ["", "## ERP hint-pack ablation (Ours full − Ours no-hint) — the contribution", ""]
    L += _md_table(
        ["Variant", "ΔRecall", "ΔPrecision", "ΔF1", "recall (no-hint → hint)"],
        [[v, d["recall_delta"], d["precision_delta"], d["f1_delta"],
          f"{d['ensemble_recall']} → {d['hinted_recall']}"]
         for v, d in sorted(report["hint_pack_ablation"].items())])

    L += ["", "## Entity classification accuracy (Ours full)", ""]
    L += _md_table(["Variant", "Accuracy"],
                   [[r["variant"], r["entity_accuracy"]]
                    for r in report["entity_classification"]])

    L += ["", "## Latency / cost", ""]
    L += _md_table(
        ["Baseline", "Variant", "Latency (s)", "LLM calls", "Cost (USD)"],
        [[r["baseline"], r["variant"], r["latency_seconds"], r["llm_calls"],
          r["cost_usd"]] for r in report["cost_latency"]])

    L += ["", "## Targets (§7)", ""]
    L += _md_table(
        ["Metric", "Measured", "Target", "Met", "Note"],
        [[t["metric"], t["measured"], t["target"], "✅" if t["met"] else "❌",
          t["note"]] for t in report["targets"]])

    L += ["", "## Remaining experiments", ""]
    L += [f"- {item}" for item in report["remaining"]]
    L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-145 Discovery eval report")
    ap.add_argument("--report", default="docs/experiments/val-145-discovery-eval.md")
    ap.add_argument("--json", default="docs/experiments/val-145-discovery-eval.json")
    args = ap.parse_args(argv)

    results = run_all_variants(mode="both")
    report = build_eval_report(results)
    md = render_markdown(report)
    print(md)

    for path, payload in ((args.report, md), (args.json, json.dumps(report, indent=2))):
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8")
        print(f"\nwrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
