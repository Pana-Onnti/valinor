#!/usr/bin/env python3
"""
A/B Number Registry experiment — scoring harness (VAL-163).

Measures the anti-hallucination delta of the Number Registry by scoring narrator
outputs from two branches against the run's ground-truth numbers:

  * control   — narrators ran with verification_report=None (pre-VAL-161 state)
  * treatment — narrators ran with a populated verification_report (post-VAL-161)

This script is the OFFLINE half: pure, deterministic, no LLM. It consumes already
captured narrator text and emits the comparison report (markdown + optional CSV)
using core/valinor/quality/narrator_metrics.py.

Capturing the two branches (the expensive, LLM half — gated by VAL-162 timeouts)
is done by running the real narrators twice, e.g.:

    from valinor.pipeline_narrator import run_narrators
    from valinor.verification import VerificationEngine
    # control:
    ctrl = await run_narrators(findings, entity_map, mem, cfg, baseline, qr,
                               verification_report=None)
    # treatment:
    vr = VerificationEngine(qr, baseline, kg).verify_findings(findings)
    trt = await run_narrators(findings, entity_map, mem, cfg, baseline, qr,
                              verification_report=vr)
    # then dump {narrator: text} to control.json / treatment.json and the
    # ground truth (findings/query_results/registry) to dataset.json.

Usage:
    python scripts/ab_test_number_registry.py \
        --control control.json --treatment treatment.json --dataset dataset.json \
        [--report docs/experiments/val-163-number-registry-ab.md] [--csv out.csv]

control.json / treatment.json : {"<narrator>": "<text>", ...}
dataset.json                  : {"findings": {...}, "query_results": {...},
                                 "number_registry": {"<label>": {"value": <n>}, ...}}

Refs: VAL-163
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from valinor.quality.narrator_metrics import (  # noqa: E402
    collect_ground_truth,
    score_narrator_output,
)


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _score_branch(outputs: dict, dataset: dict) -> dict:
    """Score every narrator in one branch. Returns {narrator: metrics_dict}."""
    findings = dataset.get("findings")
    query_results = dataset.get("query_results")
    registry = {"number_registry": dataset.get("number_registry", {})}
    # Pre-compute the ground truth once for visibility / determinism.
    _ = collect_ground_truth(registry, findings, query_results)
    scored = {}
    for narrator, text in outputs.items():
        m = score_narrator_output(text, registry, findings, query_results)
        scored[narrator] = m.to_dict()
    return scored


def _aggregate(scored: dict) -> dict:
    """Mean grounded-rate / hedging and total hallucinated across narrators."""
    n = len(scored) or 1
    g = sum(s["grounded_rate"] for s in scored.values()) / n
    h = sum(s["hallucinated_rate"] for s in scored.values()) / n
    hedge = sum(s["hedging_per_100_words"] for s in scored.values()) / n
    halluc = sum(s["numbers_ungrounded"] for s in scored.values())
    return {
        "mean_grounded_rate": round(g, 4),
        "mean_hallucinated_rate": round(h, 4),
        "total_hallucinated_numbers": halluc,
        "mean_hedging_per_100_words": round(hedge, 4),
    }


def _build_report(control: dict, treatment: dict, agg_c: dict, agg_t: dict) -> str:
    def delta(a, b):
        return f"{b - a:+.4f}"

    lines = [
        "# VAL-163 — Number Registry A/B (control vs treatment)",
        "",
        "Deterministic scoring of captured narrator outputs "
        "(`scripts/ab_test_number_registry.py`).",
        "",
        "## Aggregate",
        "",
        "| Metric | Control | Treatment | Δ (treat − ctrl) |",
        "|---|---|---|---|",
        f"| Mean grounded rate | {agg_c['mean_grounded_rate']} | "
        f"{agg_t['mean_grounded_rate']} | "
        f"{delta(agg_c['mean_grounded_rate'], agg_t['mean_grounded_rate'])} |",
        f"| Mean hallucinated rate | {agg_c['mean_hallucinated_rate']} | "
        f"{agg_t['mean_hallucinated_rate']} | "
        f"{delta(agg_c['mean_hallucinated_rate'], agg_t['mean_hallucinated_rate'])} |",
        f"| Total hallucinated numbers | {agg_c['total_hallucinated_numbers']} | "
        f"{agg_t['total_hallucinated_numbers']} | "
        f"{agg_t['total_hallucinated_numbers'] - agg_c['total_hallucinated_numbers']:+d} |",
        f"| Mean hedging / 100 words | {agg_c['mean_hedging_per_100_words']} | "
        f"{agg_t['mean_hedging_per_100_words']} | "
        f"{delta(agg_c['mean_hedging_per_100_words'], agg_t['mean_hedging_per_100_words'])} |",
        "",
        "## Per narrator (grounded rate)",
        "",
        "| Narrator | Control | Treatment | Δ |",
        "|---|---|---|---|",
    ]
    for narrator in sorted(set(control) | set(treatment)):
        c = control.get(narrator, {}).get("grounded_rate", 0.0)
        t = treatment.get(narrator, {}).get("grounded_rate", 0.0)
        lines.append(f"| {narrator} | {c} | {t} | {delta(c, t)} |")
    lines.append("")
    return "\n".join(lines)


def _write_csv(path: str, control: dict, treatment: dict) -> None:
    rows = []
    for branch, scored in (("control", control), ("treatment", treatment)):
        for narrator, m in scored.items():
            rows.append({"branch": branch, "narrator": narrator, **m})
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-163 Number Registry A/B scorer")
    ap.add_argument("--control", required=True, help="captured control narrator outputs (json)")
    ap.add_argument("--treatment", required=True, help="captured treatment narrator outputs (json)")
    ap.add_argument("--dataset", required=True, help="ground truth: findings/query_results/registry (json)")
    ap.add_argument("--report", default=None, help="write markdown report to this path")
    ap.add_argument("--csv", default=None, help="write per-narrator metrics CSV to this path")
    args = ap.parse_args(argv)

    dataset = _load(args.dataset)
    control = _score_branch(_load(args.control), dataset)
    treatment = _score_branch(_load(args.treatment), dataset)
    agg_c, agg_t = _aggregate(control), _aggregate(treatment)

    report = _build_report(control, treatment, agg_c, agg_t)
    print(report)

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n", encoding="utf-8")
        print(f"\nReport written to {out}", file=sys.stderr)
    if args.csv:
        _write_csv(args.csv, control, treatment)
        print(f"CSV written to {args.csv}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
