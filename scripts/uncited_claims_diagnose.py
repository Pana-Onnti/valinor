#!/usr/bin/env python3
"""
N5 uncited-claims diagnostic (VAL-192).

The uncited_rate (N5 instrument) says HOW MANY measured claims lack a citation.
This says WHY — turning the metric into an actionable diagnosis. For a captured
run it categorizes each uncited MEASURED claim:

  - value_zero        — |value| < 1 (matches any zero cell; a spurious citation,
                        not a real grounding gap).
  - in_raw_missed     — the value IS a raw cell the verifier's _search_raw_results
                        missed (a real verifier bug → fixable lever).
  - column_aggregate  — the value matches a column sum/count/max (a derivation the
                        verifier could compute → derivation lever).
  - computed_absent   — the value is absent from ALL query_results: a multi-step
                        aggregate the agent computed (segment sums, shares). Offline
                        static verification cannot cite these — needs active
                        re-query (DB) or the N3 deterministic-aggregate library.

The key finding this surfaces (Gloria): the uncited measured claims are almost
all `computed_absent` — so there is NO cheap deterministic resolution lever; and
`AtomicClaim.source_query` (set by `_extract_query_ref`) is DEAD in `_verify_claim`.

Pure offline. Only aggregate counts + value magnitudes are printed (no client rows).

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


def _column_aggregates(query_results: dict) -> list:
    """All column sum/count/max across every query (value, qid, col, kind)."""
    aggs = []
    for qid, res in query_results.get("results", {}).items():
        cols: dict = {}
        for row in res.get("rows", []):
            for col, v in row.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue  # don't create a column key for non-numeric cells
                cols.setdefault(col, []).append(fv)
        for col, vals in cols.items():
            aggs.append((sum(vals), qid, col, "sum"))
            aggs.append((float(len(vals)), qid, col, "count"))
            if vals:
                aggs.append((max(vals), qid, col, "max"))
    return aggs


def _raw_floats(query_results: dict) -> list:
    out = []
    for res in query_results.get("results", {}).values():
        for row in res.get("rows", []):
            for v in row.values():
                try:
                    out.append(float(v))
                except (TypeError, ValueError):
                    continue
    return out


def _near(val: float, pool, tol: float = 0.005) -> bool:
    return any(abs(p - val) <= abs(val) * tol + 0.01 for p in pool)


def diagnose(state_path: Path) -> dict:
    from valinor.knowledge_graph import build_knowledge_graph
    from valinor.verification import VerificationEngine
    from valinor.quality.agent_grounding_metrics import score_agent_claims, _value_confidence_by_finding

    state = json.loads(state_path.read_text(encoding="utf-8"))
    qr, em, bl, findings = state["query_results"], state["entity_map"], state["baseline"], state["findings"]
    eng = VerificationEngine(qr, bl, build_knowledge_graph(em))
    report = eng.verify_findings(findings)
    vc = _value_confidence_by_finding(findings)

    claims = {}
    for agent, data in findings.items():
        if str(agent).startswith("_") or not isinstance(data, dict):
            continue
        for f in eng._parse_agent_findings(data):
            for c in eng._decompose_finding(f, agent):
                claims[c.claim_id] = c

    raw = _raw_floats(qr)
    aggs = _column_aggregates(qr)
    agg_vals = [a[0] for a in aggs]

    cats = {"value_zero": 0, "in_raw_missed": 0, "column_aggregate": 0, "computed_absent": 0}
    for r in report.results:
        if r.status != "UNVERIFIABLE" or r.verification_query is not None:
            continue
        c = claims.get(r.claim_id)
        if not c or c.claimed_value is None:
            continue
        if vc.get(c.finding_id) not in (None, "measured"):
            continue  # only MEASURED claims (declared inferences are out of scope)
        val = c.claimed_value
        if abs(val) < 1:
            cats["value_zero"] += 1
        elif _near(val, raw):
            cats["in_raw_missed"] += 1
        elif _near(val, agg_vals):
            cats["column_aggregate"] += 1
        else:
            cats["computed_absent"] += 1

    audit = score_agent_claims(report.results, list(claims.values()), findings=findings)
    return {"audit": audit.to_dict(), "uncited_measured_breakdown": cats}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 N5 uncited-claims diagnostic")
    ap.add_argument("--state", required=True, help="captured pipeline state.json")
    args = ap.parse_args(argv)
    print(json.dumps(diagnose(Path(args.state)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
