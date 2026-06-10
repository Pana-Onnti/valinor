#!/usr/bin/env python3
"""
Build a VAL-163 A/B state.json from a saved production-test output (VAL-192 N1).

The capture harness (scripts/capture_narrator_ab.py) needs the exact pipeline
state that feeds the narrators. Two ways to get it:

  1. Live tap: run the pipeline with VALINOR_AB_CAPTURE=<path> (core/valinor/run.py).
  2. THIS SCRIPT: reconstruct it from a saved production-test output
     (tests/output/production/gloria_*.json) — zero swarm/LLM cost.

The saved outputs hold the same objects the tap dumps (entity_map, query_results,
baseline, findings); `client` maps to client_config and memory is not persisted
(narrators accept memory=None — "first run" framing, identical across branches).

Usage:
    python scripts/build_ab_state.py \
        --output tests/output/production/gloria_Q1-2025_2026-05-08_11-19-49.json \
        --state docs/experiments/val-163/state.json [--narrator-timeout 300]

The state file contains client data → keep it under docs/experiments/val-163/
(gitignored). Refs: VAL-163, VAL-192
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED = ("entity_map", "query_results", "baseline", "findings")


def build_state(output: dict, narrator_timeout: int) -> dict:
    missing = [k for k in REQUIRED if k not in output]
    if missing:
        raise SystemExit(f"saved output is missing keys: {missing}")
    # Production shape (run.py): query_results = {"results": {...}, "errors": {...}}.
    # The saved test outputs flatten it — re-wrap, or VerificationEngine reads
    # query_results["results"] as {} and the registry starves (verified live:
    # plain shape → registry=4 baseline-only entries vs the wired pipeline).
    qr = output["query_results"]
    if "results" not in qr:
        qr = {"results": qr, "errors": output.get("query_errors", {})}
    return {
        "entity_map": output["entity_map"],
        "query_results": qr,
        "baseline": output["baseline"],
        "findings": output["findings"],
        "memory": output.get("memory"),
        "client_config": output.get("client_config") or output.get("client") or {},
        "narrator_timeout": narrator_timeout,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-163 state.json builder")
    ap.add_argument("--output", required=True, help="saved production output json")
    ap.add_argument("--state", required=True, help="where to write state.json")
    ap.add_argument("--narrator-timeout", type=int, default=300)
    args = ap.parse_args(argv)

    output = json.loads(Path(args.output).read_text(encoding="utf-8"))
    state = build_state(output, args.narrator_timeout)

    dest = Path(args.state)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")

    qr = state["query_results"]
    print(
        f"wrote {dest}\n"
        f"  queries={len(qr)} findings_agents={list(state['findings'].keys())}\n"
        f"  client={state['client_config'].get('name')} "
        f"narrator_timeout={state['narrator_timeout']}s",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
