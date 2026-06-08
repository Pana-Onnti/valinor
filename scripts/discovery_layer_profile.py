#!/usr/bin/env python3
"""
Discovery Engine per-layer (L0-L5) latency/cost breakdown (VAL-145, paper §7).

The other VAL-145 artifacts report end-to-end accuracy and the hint-pack ablation.
This one fills the remaining deterministic §7 table: where the wall-clock and the
LLM cost actually go, layer by layer, mapped to the 6-layer pipeline of §4.

Layer mapping (paper §4 → implementation building block):
    L0 Schema extraction       → build_schema_profile_from_sqlite
    L1 Structural profiling     → build_table_profiles_from_sqlite (column stats)
    L2 IND / FK candidates      → StructuralAgent.infer (explicit FK + name patterns)
    L3 ERP Hint Pack            → DomainAgent.infer (header/detail, fiscal patterns)
    L4 Knowledge graph          → OntologyBuilder.build_ontology
    L5 LLM semantic validation  → SemanticAgent.infer + BusinessProcessAgent.infer

DETERMINISM & HONESTY: runs with the MockLLMClient (reproducible, free). Under Mock
the absolute wall-clock is meaningless (sub-millisecond, no network) — what IS citable
is the per-layer *share* of deterministic work and *which layers issue LLM calls* (only
L5). The cost column reports both the measured Mock cost ($0) and the real-LLM
projection (L5 = 2 Haiku calls/variant), mirroring how discovery_eval_report.py flags
real-LLM-dependent numbers. Absolute latency under a real LLM is the remaining step.

Usage:
    python scripts/discovery_layer_profile.py
        [--report docs/experiments/val-145-layer-breakdown.md]
        [--json docs/experiments/val-145-layer-breakdown.json]

Refs: VAL-145 (relates VAL-175, VAL-142)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from valinor.discovery.benchmark import (  # noqa: E402
    build_schema_profile_from_sqlite,
    build_table_profiles_from_sqlite,
    load_golden_hint_pack,
)
from valinor.discovery.fk_discovery import FKCandidate  # noqa: E402
from valinor.discovery.golden_dataset import (  # noqa: E402
    build_golden_sqlite,
    load_golden_dataset,
)
from valinor.discovery.inference_agents import (  # noqa: E402
    BusinessProcessAgent,
    DomainAgent,
    EnsembleEvaluator,
    MockLLMClient,
    SemanticAgent,
    StructuralAgent,
)
from valinor.discovery.ontology_builder import OntologyBuilder  # noqa: E402

_VARIANTS = ("gloria_full", "gloria_no_fks", "gloria_obfuscated")

# Haiku 3.5 approx cost per call — same constant as EnsembleBenchmark, kept local so
# this harness stays decoupled from the benchmark's internals.
_HAIKU_COST_PER_CALL_USD = 0.008

# Per-layer real-LLM call count. Only L5 (semantic + business-process agents) calls out.
_LLM_CALLS_PER_LAYER = {
    "L0": 0, "L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 2,
}

_LAYER_DESC = {
    "L0": "Schema extraction",
    "L1": "Structural profiling",
    "L2": "IND / FK candidates",
    "L3": "ERP Hint Pack",
    "L4": "Knowledge graph",
    "L5": "LLM semantic validation",
}

_MIN_CONFIDENCE = 0.5  # matches EnsembleBenchmark default


def _timed(fn):
    """Run fn(), return (result, elapsed_seconds) with a monotonic high-res clock."""
    t0 = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - t0


async def profile_variant(variant: str, hint_pack: dict) -> dict:
    """Run the 6-layer pipeline for one variant, timing each layer. Deterministic."""
    golden = load_golden_dataset(variant)
    conn = build_golden_sqlite(variant)
    try:
        names = [t.name for t in golden.tables]
        llm = MockLLMClient()
        timings: dict[str, float] = {}

        # L0 — schema extraction
        schema, timings["L0"] = _timed(
            lambda: build_schema_profile_from_sqlite(conn, names))

        # L1 — structural profiling (column-level stats)
        _, timings["L1"] = _timed(
            lambda: build_table_profiles_from_sqlite(conn, names))

        # L2 — IND / FK candidates (deterministic structural agent)
        structural_rel, timings["L2"] = _timed(
            lambda: StructuralAgent().infer(schema))

        # L3 — ERP hint pack (deterministic domain agent)
        domain_rel, timings["L3"] = _timed(
            lambda: DomainAgent().infer(schema, hint_pack))

        # L5 — LLM semantic validation (semantic + business-process agents).
        # Timed before L4 because L4 consumes the merged, thresholded relations.
        t0 = time.perf_counter()
        semantic_rel = await SemanticAgent(llm).infer(schema, None)
        process_rel = await BusinessProcessAgent(llm).infer(schema, {
            "company_name": "Golden PyME",
            "industry": golden.description,
            "country": "AR",
            "erp_type": "gestion_pyme_argentina",
        })
        timings["L5"] = time.perf_counter() - t0

        evaluated = EnsembleEvaluator().evaluate(
            [structural_rel, semantic_rel, domain_rel, process_rel])
        predicted = [r for r in evaluated if r.confidence >= _MIN_CONFIDENCE]
        fk_candidates = [
            FKCandidate(
                source_table=r.source_table, source_column=r.source_column,
                target_table=r.target_table, target_column=r.target_column,
                inclusion_ratio=1.0, orphan_count=0, name_similarity=1.0,
                cardinality_ratio=1.0, score=r.confidence,
            )
            for r in predicted
        ]

        # L4 — knowledge graph / ontology construction
        table_profiles = build_table_profiles_from_sqlite(conn, names)
        _, timings["L4"] = _timed(
            lambda: OntologyBuilder().build_ontology(table_profiles, fk_candidates))

        return {"variant": variant, "tables": len(names), "timings_seconds": timings}
    finally:
        conn.close()


def aggregate(per_variant: list[dict]) -> dict:
    """Mean per-layer latency across variants + LLM-cost model. Pure."""
    order = ["L0", "L1", "L2", "L3", "L4", "L5"]
    means = {
        layer: sum(v["timings_seconds"][layer] for v in per_variant) / len(per_variant)
        for layer in order
    }
    total = sum(means.values()) or 1.0

    layers = []
    for layer in order:
        mock_calls = 0  # MockLLMClient never issues a network call
        real_calls = _LLM_CALLS_PER_LAYER[layer]
        layers.append({
            "layer": layer,
            "description": _LAYER_DESC[layer],
            "mean_latency_ms": round(means[layer] * 1000, 4),
            "share_pct": round(100 * means[layer] / total, 1),
            "llm_calls_mock": mock_calls,
            "llm_calls_real": real_calls,
            "cost_usd_mock": 0.0,
            "cost_usd_real_projected": round(real_calls * _HAIKU_COST_PER_CALL_USD, 4),
        })

    return {
        "determinism": (
            "MockLLMClient (reproducible, $0). Per-layer SHARE and LLM-call placement "
            "are citable; absolute wall-clock and real-LLM latency are pending a live run."
        ),
        "layer_mapping": _LAYER_DESC,
        "variants": [v["variant"] for v in per_variant],
        "per_variant": per_variant,
        "layers": layers,
        "totals": {
            "mean_latency_ms": round(total * 1000, 4),
            "llm_calls_real_per_analysis": sum(_LLM_CALLS_PER_LAYER.values()),
            "cost_usd_real_projected": round(
                sum(layer["cost_usd_real_projected"] for layer in layers), 4),
        },
    }


def _md_table(headers: list, rows: list) -> list:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return out


def render_markdown(report: dict) -> str:
    L = ["# VAL-145 — Discovery Engine per-layer latency/cost breakdown (paper §7)", "",
         f"Determinism: {report['determinism']}", "",
         f"Variants: {', '.join(report['variants'])} (mean across variants).", ""]

    L += ["## Per-layer breakdown (L0-L5)", ""]
    L += _md_table(
        ["Layer", "Stage", "Mean latency (ms)", "Share %", "LLM calls (real)",
         "Cost (USD, real proj.)"],
        [[layer["layer"], layer["description"], layer["mean_latency_ms"],
          f"{layer['share_pct']}%", layer["llm_calls_real"],
          layer["cost_usd_real_projected"]] for layer in report["layers"]])

    t = report["totals"]
    L += ["", "## Totals", "",
          f"- Mean end-to-end (deterministic, MockLLM): **{t['mean_latency_ms']} ms**",
          f"- Real-LLM calls per analysis: **{t['llm_calls_real_per_analysis']}** "
          f"(all in L5)",
          f"- Projected real-LLM cost per analysis: **${t['cost_usd_real_projected']}**",
          ""]

    L += ["## Reading this table", "",
          "- Only **L5** touches the LLM — L0-L4 are deterministic, so the moat work "
          "(structural + hint pack, L2-L3) carries **zero per-call cost**.",
          "- Under MockLLM absolute latency is sub-millisecond and not representative; "
          "the **share %** column is the citable structure. Absolute wall-clock under a "
          "real LLM is the remaining live-run step.", ""]
    return "\n".join(L)


def build_report() -> dict:
    hint_pack = load_golden_hint_pack()
    if not hint_pack:
        raise RuntimeError(
            "discovery_layer_profile: hint pack loaded empty — L3 would be a no-op and "
            "the breakdown misleading. Check erp_hints/argentina_gestion.yaml.")
    per_variant = [
        asyncio.run(profile_variant(v, hint_pack)) for v in _VARIANTS
    ]
    return aggregate(per_variant)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-145 per-layer latency/cost breakdown")
    ap.add_argument("--report", default="docs/experiments/val-145-layer-breakdown.md")
    ap.add_argument("--json", default="docs/experiments/val-145-layer-breakdown.json")
    args = ap.parse_args(argv)

    report = build_report()
    md = render_markdown(report)
    print(md)

    for path, payload in ((args.report, md), (args.json, json.dumps(report, indent=2))):
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + ("\n" if not payload.endswith("\n") else ""),
                       encoding="utf-8")
        print(f"\nwrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
