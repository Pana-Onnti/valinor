#!/usr/bin/env python3
"""
A/B Number Registry experiment — capture harness (VAL-163).

The companion to scripts/ab_test_number_registry.py (the offline scorer). This is
the half that PRODUCES the scorer's inputs: it runs the real narrators twice over
the SAME captured pipeline state and dumps the three JSON files the scorer reads.

  * control   — run_narrators(..., verification_report=None)   (pre-VAL-161 state)
  * treatment — run_narrators(..., verification_report=<vr>)   (post-VAL-161 state)

Key property (VAL-163 "out of scope"): the treatment verification_report is built
OFFLINE from the captured run — build_knowledge_graph(entity_map) + VerificationEngine
over query_results/baseline/findings. The engine does NOT re-query the DB, so the only
thing that needs the LLM (and the proxy / VAL-162 timeout budget) is the narrators
themselves. Everything else is pure and deterministic.

Input — a captured pipeline-state fixture (one real Gloria run, saved once):

    state.json = {
        "entity_map":    {...},   # Cartographer schema map  (→ KG)
        "query_results": {...},   # executed query rows       (→ verifier + ground truth)
        "baseline":      {...},   # compute_baseline output   (→ verifier)
        "findings":      {...},   # reconciled swarm output   (→ verifier + narrators)
        "memory":        {...} | null,
        "client_config": {...},
        "narrator_timeout": 60     # optional
    }

Output (into --out-dir): control.json, treatment.json, dataset.json — exactly the
shapes scripts/ab_test_number_registry.py consumes. Then run the scorer:

    python scripts/capture_narrator_ab.py --state state.json --out-dir docs/experiments/val-163
    python scripts/ab_test_number_registry.py \
        --control   docs/experiments/val-163/control.json \
        --treatment docs/experiments/val-163/treatment.json \
        --dataset   docs/experiments/val-163/dataset.json \
        --report    docs/experiments/val-163-number-registry-ab.md

VAL-162 workaround: pass --only briefing_ceo,reporte_ejecutivo to capture just the
narrators that close, avoiding the timeout-prone ones until VAL-162 fully lands.

Refs: VAL-163 (relates VAL-161, VAL-162)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))


def build_treatment_report(state: dict) -> Any:
    """Build the post-VAL-161 VerificationReport offline (KG + VerificationEngine).

    Pure: no DB, no LLM. Mirrors core/valinor/run.py (build_knowledge_graph →
    VerificationEngine(query_results, baseline, kg).verify_findings(findings)).
    """
    from valinor.knowledge_graph import build_knowledge_graph
    from valinor.verification import VerificationEngine

    kg = build_knowledge_graph(state["entity_map"])
    verifier = VerificationEngine(state["query_results"], state["baseline"], kg)
    return verifier.verify_findings(state["findings"])


def serialize_registry(verification_report: Any) -> dict:
    """Flatten a VerificationReport's number_registry to the scorer's dataset shape.

    {label: {"value", "unit", "dimension", "source_query"}}. The scorer only needs
    "value"; the rest is kept for human readability of dataset.json.
    """
    registry = getattr(verification_report, "number_registry", {}) or {}

    def _g(entry, attr, default=""):
        val = getattr(entry, attr, entry.get(attr) if isinstance(entry, dict) else default)
        # Coerce enum-valued fields (e.g. dimension: Dimension.EUR) to a plain string.
        return getattr(val, "value", val) if val is not None else default

    out: dict = {}
    for label, entry in registry.items():
        out[label] = {
            "value": _g(entry, "value", None),
            "unit": _g(entry, "unit"),
            "dimension": _g(entry, "dimension"),
            "source_query": _g(entry, "source_query"),
        }
    return out


def _filter_outputs(outputs: dict, only: Optional[set]) -> dict:
    if not only:
        return outputs
    return {k: v for k, v in outputs.items() if k in only}


async def capture_ab(
    state: dict,
    *,
    only: Optional[set] = None,
    run_narrators_fn: Optional[Callable[..., Awaitable[dict]]] = None,
    build_vr_fn: Callable[[dict], Any] = build_treatment_report,
) -> tuple[dict, dict, dict]:
    """Run both branches over one captured state; return (control, treatment, dataset).

    run_narrators_fn / build_vr_fn are injectable so the orchestration is testable
    offline (no LLM, no DB). Defaults wire the real pipeline narrators + verifier.
    """
    if run_narrators_fn is None:
        from valinor.pipeline_narrator import run_narrators as run_narrators_fn  # type: ignore

    timeout = state.get("narrator_timeout", 60)
    common = dict(
        findings=state["findings"],
        entity_map=state["entity_map"],
        memory=state.get("memory"),
        client_config=state["client_config"],
        baseline=state["baseline"],
        query_results=state["query_results"],
        narrator_timeout=timeout,
    )

    # control — narrators blind to the registry (pre-VAL-161).
    control = await run_narrators_fn(**common, verification_report=None)

    # treatment — registry-anchored narrators (post-VAL-161). VR built offline.
    vr = build_vr_fn(state)
    treatment = await run_narrators_fn(**common, verification_report=vr)

    control = _filter_outputs(control, only)
    treatment = _filter_outputs(treatment, only)

    dataset = {
        "findings": state["findings"],
        "query_results": state["query_results"],
        "number_registry": serialize_registry(vr),
    }
    return control, treatment, dataset


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-163 Number Registry A/B capture")
    ap.add_argument("--state", required=True,
                    help="captured pipeline-state fixture (json) — see module docstring")
    ap.add_argument("--out-dir", required=True,
                    help="directory to write control.json / treatment.json / dataset.json")
    ap.add_argument("--only", default=None,
                    help="comma-separated narrator names to keep (VAL-162 workaround), "
                         "e.g. briefing_ceo,reporte_ejecutivo")
    args = ap.parse_args(argv)

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    control, treatment, dataset = asyncio.run(capture_ab(state, only=only))

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
        "\nNow score the captured branches:\n"
        f"  python scripts/ab_test_number_registry.py \\\n"
        f"      --control {out / 'control.json'} \\\n"
        f"      --treatment {out / 'treatment.json'} \\\n"
        f"      --dataset {out / 'dataset.json'} \\\n"
        f"      --report docs/experiments/val-163-number-registry-ab.md",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
