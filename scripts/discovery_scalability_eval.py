#!/usr/bin/env python3
"""
Discovery Engine scalability sweep (VAL-145 §7).

Profiles deterministic structural FK discovery (latency + FK precision/recall) as a
function of schema size N, over synthetic star schemas (synthetic_schema.py). Answers
§7's "Discovery latency < 30s" target and shows how the O(N²) structural matching
scales with table count.

Deterministic, no LLM. The default sweep (50/200/500) profiles the structural path
(DiscoveryBenchmark); the LLM ensemble adds a roughly constant per-run overhead on
top and is out of scope for the scaling curve.

Usage:
    python scripts/discovery_scalability_eval.py [--sizes 50,200,500]
        [--report docs/experiments/val-145-scalability.md]
        [--json   docs/experiments/val-145-scalability.json]

Refs: VAL-145 (relates VAL-175, VAL-129)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from valinor.discovery.benchmark import DiscoveryBenchmark  # noqa: E402
from valinor.discovery.synthetic_schema import build_synthetic_dataset  # noqa: E402

_LATENCY_TARGET_S = 30.0


def run_scalability_sweep(sizes: list[int], seed: int = 13) -> list[dict]:
    """Run structural FK discovery at each N and record latency + accuracy. Pure."""
    out = []
    for n in sizes:
        dataset, conn = build_synthetic_dataset(n, with_fks=False, seed=seed)
        try:
            r = DiscoveryBenchmark(dataset, conn).run()
            out.append({
                "n_tables": n,
                "golden_fks": r.total_golden,
                "predicted": r.total_predicted,
                "fk_recall": round(r.fk_recall, 4),
                "fk_precision": round(r.fk_precision, 4),
                "fk_f1": round(r.fk_f1, 4),
                "latency_seconds": round(r.elapsed_seconds, 3),
                "latency_under_target": r.elapsed_seconds < _LATENCY_TARGET_S,
            })
        finally:
            conn.close()
    return out


def _scaling_note(rows: list[dict]) -> list[str]:
    """Describe how latency grows relative to table count between consecutive sizes."""
    notes = []
    for a, b in zip(rows, rows[1:]):
        if a["latency_seconds"] <= 0 or a["n_tables"] <= 0:
            continue
        table_factor = b["n_tables"] / a["n_tables"]
        lat_factor = (b["latency_seconds"] / a["latency_seconds"]
                      if a["latency_seconds"] > 0 else float("inf"))
        shape = ("~linear" if lat_factor <= table_factor * 1.3
                 else "super-linear" if lat_factor <= table_factor ** 2 * 1.3
                 else "≥quadratic")
        notes.append(
            f"- {a['n_tables']}→{b['n_tables']} tables (×{table_factor:.1f}): "
            f"latency ×{lat_factor:.1f} ({shape})"
        )
    return notes


def render_markdown(rows: list[dict]) -> str:
    L = ["# VAL-145 — Discovery scalability sweep (paper §7)", "",
         "Structural FK discovery (deterministic, no LLM) over synthetic star schemas; "
         f"latency target < {_LATENCY_TARGET_S:g}s.", "",
         "| N tables | Golden FKs | Predicted | Recall | Precision | F1 | Latency (s) | < target |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(
            f"| {r['n_tables']} | {r['golden_fks']} | {r['predicted']} | {r['fk_recall']} | "
            f"{r['fk_precision']} | {r['fk_f1']} | {r['latency_seconds']} | "
            f"{'✅' if r['latency_under_target'] else '❌'} |"
        )
    L += ["", "## Scaling behavior", ""]
    L += _scaling_note(rows) or ["- (single data point)"]
    L += ["", "## Notes", "",
          "- Precision is decoupled from synthetic naming by disjoint PK value ranges, "
          "so an inclusion dependency holds only for the true target.",
          "- The dominant cost is the O(N²) structural candidate matching "
          "(name similarity + inclusion checks), not data volume (rows per table are small "
          "and constant).", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-145 discovery scalability sweep")
    ap.add_argument("--sizes", default="50,200,500", help="comma-separated table counts")
    ap.add_argument("--report", default="docs/experiments/val-145-scalability.md")
    ap.add_argument("--json", default="docs/experiments/val-145-scalability.json")
    args = ap.parse_args(argv)

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    rows = run_scalability_sweep(sizes)
    md = render_markdown(rows)
    print(md)
    for path, payload in ((args.report, md), (args.json, json.dumps(rows, indent=2))):
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload + ("\n" if not payload.endswith("\n") else ""), encoding="utf-8")
        print(f"\nwrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
