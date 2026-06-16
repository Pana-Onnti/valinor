#!/usr/bin/env python3
"""
N7 flywheel scorecard (VAL-192).

The N7 hito is a SIGNAL that the machine is alive: the eval set GROWS, grounding
HOLDS, and the marginal cost of a grounded report DROPS per client resolved. You
can't claim a flywheel without measuring it — this instrument snapshots the
compounding signals from the repo's eval + knowledge artifacts (the eval as
governor of every entry: index/graph/prompts/weights).

What it measures (all CPU, no client data):
  - eval_corpus     — governed eval cases across all golden sets (the "grows" axis;
                      N1 started at 39, now 145).
  - ci_gates        — eval suites with a regression gate (grounding "holds").
  - knowledge_assets— hint-packs + distilled QA (the moat that compounds).
  - cost_mechanisms — the wired marginal-cost reducers (entity_map cache →
                      cartographer skip on repeat runs).

A SINGLE snapshot proves accumulation + governance, NOT the longitudinal cost↓
trend (that needs multi-client production data over time — the operator's). The
ratchet gate (tests/test_flywheel_scorecard.py) enforces the one thing we CAN
guarantee in CI: the eval corpus never shrinks.

Refs: VAL-192 (N7)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "evals" / "flywheel" / "scorecard.json"


def _yaml_len(path: Path, key: str, filt=None) -> int:
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    items = data.get(key, []) if isinstance(data, dict) else data
    if filt:
        items = [x for x in items if filt(x)]
    return len(items)


def compute() -> dict:
    ev = ROOT / "evals"
    corpus = {
        "narrator_grounding": _yaml_len(ev / "narrator_grounding" / "golden.yaml", "cases"),
        "agent_grounding": _yaml_len(ev / "agent_grounding" / "golden.yaml", "cases"),
        "global_questions": _yaml_len(
            ev / "golden" / "global_questions.yaml", "questions",
            lambda q: q.get("split") in ("train", "test")),
        "distill_qa": sum(1 for line in (ev / "distill" / "qa_pairs.jsonl").read_text().splitlines() if line.strip()),
    }
    corpus["total"] = sum(corpus.values())

    # Eval suites with a committed regression gate (grounding "holds" as corpus grows).
    gates = {
        "narrator_grounding (N1)": (ev / "narrator_grounding" / "baseline.json").exists(),
        "agent_grounding (N5)": (ev / "agent_grounding" / "baseline.json").exists(),
        "global_questions (N3, eval.py graphrag --gate)": (ev / "golden" / "global_questions.yaml").exists(),
        "distill_qa (N6, test_distill_qa.py)": (ROOT / "tests" / "test_distill_qa.py").exists(),
    }

    hint_packs = sorted(p.stem for p in (ROOT / "core" / "valinor" / "discovery" / "erp_hints").glob("*.yaml"))

    return {
        "eval_corpus": corpus,
        "ci_gates": {"gated_suites": sum(1 for v in gates.values() if v), "suites": gates},
        "knowledge_assets": {
            "hint_packs": len(hint_packs),
            "hint_pack_families": hint_packs,
            "distill_qa_pairs": corpus["distill_qa"],
        },
        # The wired marginal-cost reducer: a repeat run within the TTL skips the
        # (expensive) LLM cartographer — cost drops on the 2nd+ run per client.
        "cost_mechanisms": {
            "entity_map_cache_ttl_h": 72,
            "cartographer_skip_on_fresh_cache": True,
            "ref": "shared/memory/client_profile.is_entity_map_fresh",
        },
        "governor_coverage": [
            "N1 narrator grounding instrument + CI gate",
            "N3 global-question gate (community arm certified v6)",
            "N4 write-path: review + provenance + audit before memory entry",
            "N5 agent-claims uncited gate + active re-query lever",
            "N6 distill QA: provenance + staleness gate",
        ],
        "note": "Snapshot of flywheel accumulation + governance. The longitudinal "
                "marginal-cost↓ trend needs multi-client production data over time "
                "(operator). The committed eval_corpus.total is a CI RATCHET: it "
                "must never shrink (tests/test_flywheel_scorecard.py).",
    }


def main(argv=None) -> int:
    sc = compute()
    update = "--update" in (argv if argv is not None else sys.argv[1:])
    if update:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(sc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"scorecard written → {OUT}")
    print(json.dumps(sc, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
