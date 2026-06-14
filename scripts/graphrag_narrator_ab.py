#!/usr/bin/env python3
"""
N3 GraphRAG → narrator A/B — capture harness (VAL-192).

The eval-first gate BEFORE turning N3 on in prod. Mirrors the VAL-163 capture
(scripts/capture_narrator_ab.py): runs the REAL narrators twice over the SAME
captured pipeline state and dumps the three JSON files the scorer reads. The
ONLY difference between the two arms is the GraphRAG global-aggregate context:

  * control   — run_narrators(..., graph_context=None)   (current prod behavior)
  * treatment — run_narrators(..., graph_context=<block>) (VALINOR_GRAPHRAG=1)

BOTH arms carry the Number Registry (post-VAL-161 prod baseline) so the A/B
isolates exactly the N3 contribution. The verification report and the graph
context are both built OFFLINE from the captured run — no DB, no re-query; only
the narrators touch the LLM.

Measurement fairness: the dataset's number_registry is the legacy registry
UNION the graph's deterministic aggregate numbers. Without the union, treatment
would be penalized for citing CORRECT graph aggregates (exposure totals,
group-by) the 5-query registry never knew about — a measurement artifact, not a
regression. See core/valinor/graphrag_context.graph_aggregate_numbers.

Input — the SAME captured state fixture as VAL-163 (state.json):
    {entity_map, query_results, baseline, findings, memory, client_config,
     narrator_timeout?}

Usage:
    python scripts/graphrag_narrator_ab.py --state state.json --out-dir docs/experiments/val-192-n3/narrator-ab
    python scripts/ab_test_number_registry.py \
        --control   docs/experiments/val-192-n3/narrator-ab/control.json \
        --treatment docs/experiments/val-192-n3/narrator-ab/treatment.json \
        --dataset   docs/experiments/val-192-n3/narrator-ab/dataset.json \
        --report    docs/experiments/val-192-n3-narrator-ab.md

Refs: VAL-192 (N3 wiring). Relates VAL-163 (the registry A/B this mirrors).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for capture_narrator_ab reuse


def _filter_outputs(reports: dict, only: Optional[set]) -> dict:
    if not only:
        return reports
    return {k: v for k, v in reports.items() if k in only}


async def capture_graphrag_ab(
    state: dict,
    only: Optional[set] = None,
    run_narrators_fn: Optional[Callable[..., Awaitable[dict]]] = None,
    build_vr_fn: Optional[Callable[[dict], Any]] = None,
    build_ctx_fn: Optional[Callable[..., Optional[str]]] = None,
    aggregate_numbers_fn: Optional[Callable[..., dict]] = None,
) -> tuple[dict, dict, dict]:
    """Run control (graph off) vs treatment (graph on) narrators over `state`.

    All collaborators are injectable so the orchestration is unit-testable
    offline (no LLM, no DB). Defaults wire the real pipeline + N3 bridge.
    """
    if run_narrators_fn is None:
        from valinor.pipeline_narrator import run_narrators as run_narrators_fn  # type: ignore
    if build_vr_fn is None:
        from capture_narrator_ab import build_treatment_report as build_vr_fn  # type: ignore
    if build_ctx_fn is None:
        from valinor.graphrag_context import build_narrator_graph_context as build_ctx_fn  # type: ignore
    if aggregate_numbers_fn is None:
        from valinor.graphrag_context import graph_aggregate_numbers as aggregate_numbers_fn  # type: ignore

    timeout = state.get("narrator_timeout", 60)
    vr = build_vr_fn(state)
    registry = getattr(vr, "number_registry", None)

    common = dict(
        findings=state["findings"],
        entity_map=state["entity_map"],
        memory=state.get("memory"),
        client_config=state["client_config"],
        baseline=state["baseline"],
        query_results=state["query_results"],
        narrator_timeout=timeout,
        verification_report=vr,
    )

    graph_context = build_ctx_fn(
        state["entity_map"], state["query_results"], state["baseline"],
        state["findings"], number_registry=registry,
    )

    # control — narrators blind to the graph (current prod).
    control = await run_narrators_fn(**common, graph_context=None)
    # treatment — narrators with the deterministic N3 aggregate block.
    treatment = await run_narrators_fn(**common, graph_context=graph_context)

    control = _filter_outputs(control, only)
    treatment = _filter_outputs(treatment, only)

    # dataset ground-truth = legacy registry ∪ deterministic graph aggregates.
    from capture_narrator_ab import serialize_registry  # type: ignore
    ground_truth = serialize_registry(vr)
    ground_truth.update(aggregate_numbers_fn(
        state["entity_map"], state["query_results"], state["baseline"],
        state["findings"], number_registry=registry,
    ))

    dataset = {
        "findings": state["findings"],
        "query_results": state["query_results"],
        "number_registry": ground_truth,
        "graph_context_chars": len(graph_context or ""),
        "graph_context_injected": graph_context is not None,
    }
    return control, treatment, dataset


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 N3 GraphRAG narrator A/B capture")
    ap.add_argument("--state", required=True,
                    help="captured pipeline-state fixture (json) — same shape as VAL-163")
    ap.add_argument("--out-dir", required=True,
                    help="directory to write control.json / treatment.json / dataset.json")
    ap.add_argument("--only", default=None,
                    help="comma-separated narrator names to keep (VAL-162 workaround), "
                         "e.g. briefing_ceo,reporte_ejecutivo")
    args = ap.parse_args(argv)

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    control, treatment, dataset = asyncio.run(capture_graphrag_ab(state, only=only))

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("control.json", control),
        ("treatment.json", treatment),
        ("dataset.json", dataset),
    ):
        (out / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"wrote {out / name}", file=sys.stderr)

    print(
        f"\ngraph context: {dataset['graph_context_chars']} chars "
        f"({'injected' if dataset['graph_context_injected'] else 'EMPTY — treatment == control'})\n"
        "Now score the captured branches:\n"
        f"  python scripts/ab_test_number_registry.py \\\n"
        f"      --control {out / 'control.json'} \\\n"
        f"      --treatment {out / 'treatment.json'} \\\n"
        f"      --dataset {out / 'dataset.json'} \\\n"
        f"      --report docs/experiments/val-192-n3-narrator-ab.md",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
