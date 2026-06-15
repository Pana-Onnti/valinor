#!/usr/bin/env python3
"""
N5 agent-claims grounding baseline (VAL-192).

Measures the uncited-claims rate over a run's atomic claims. Two inputs:

  --report verification_report.json   # the saved artifact (post deliver.py N5 fix)
  --state  state.json                 # a captured pipeline state → run the REAL
                                       # VerificationEngine offline and score it

The --state path re-derives the same AtomicClaims the engine decomposes (so the
declared-inference detection has claim text) and runs verify_findings WITHOUT a
DB — active re-query falls back to UNVERIFIABLE, so this is a conservative
baseline of citation coverage from the static captured data (documented).

Prints the AgentClaimsAudit as JSON. Only the aggregate numbers are emitted —
no client rows — so the rate is safe to record even when the state is gitignored.

Refs: VAL-192 (N5)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))

from valinor.quality.agent_grounding_metrics import score_agent_claims  # noqa: E402


def _claims_from_state(eng, findings: dict) -> list:
    """Re-derive the atomic claims the engine decomposes (for declared detection)."""
    claims = []
    for agent_name, agent_data in findings.items():
        if agent_name.startswith("_") or not isinstance(agent_data, dict):
            continue
        for f in eng._parse_agent_findings(agent_data):
            claims += eng._decompose_finding(f, agent_name)
            claims += eng._detect_temporal_claims(f, agent_name)
            claims += eng._detect_negative_claims(f, agent_name)
    return claims


def from_state(state_path: Path, connection_string: str = "") -> dict:
    from valinor.knowledge_graph import build_knowledge_graph
    from valinor.verification import VerificationEngine

    state = json.loads(state_path.read_text(encoding="utf-8"))
    kg = build_knowledge_graph(state["entity_map"])
    # With a connection_string, verification strategy 4 (active re-query) fires —
    # computed aggregates absent from the raw rows get re-computed against the DB
    # and cited. Without it, this is the conservative offline baseline.
    eng = VerificationEngine(
        state["query_results"], state["baseline"], kg,
        connection_string=connection_string or None,
        entity_map=state["entity_map"],
    )
    report = eng.verify_findings(state["findings"])
    claims = _claims_from_state(eng, state["findings"])
    audit = score_agent_claims(report.results, claims, findings=state["findings"])
    return audit.to_dict()


def from_report(report_path: Path) -> dict:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    results = data.get("results", [])
    if not results:
        print("⚠ verification_report.json has no results[] — re-run with the "
              "deliver.py N5 serialization fix.", file=sys.stderr)
    # No claim text available from the artifact → declared detection skipped.
    audit = score_agent_claims(results)
    return audit.to_dict()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 N5 agent-grounding baseline")
    ap.add_argument("--state", help="captured pipeline state.json (runs verification offline)")
    ap.add_argument("--report", help="saved verification_report.json with results[]")
    ap.add_argument("--connection-string", default="",
                    help="DB connection (with --state) → enables active re-query "
                         "strategy 4: the full-pipeline-with-DB baseline")
    args = ap.parse_args(argv)

    if not args.state and not args.report:
        ap.error("pass --state or --report")

    audit = (from_state(Path(args.state), args.connection_string)
             if args.state else from_report(Path(args.report)))
    print(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
