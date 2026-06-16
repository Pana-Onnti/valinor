"""
N7 flywheel ratchet (VAL-192).

The one compounding invariant we CAN enforce in CI without longitudinal
production data: the governed eval corpus never shrinks (the flywheel ratchet).
`pytest` fails if someone removes eval cases below the committed snapshot, or if
a knowledge-entry path loses its gate. Pure CPU, offline.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORECARD = ROOT / "evals" / "flywheel" / "scorecard.json"

_SPEC = importlib.util.spec_from_file_location(
    "flywheel_scorecard", ROOT / "scripts" / "flywheel_scorecard.py")
_SC = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SC)


def test_scorecard_computes():
    sc = _SC.compute()
    assert sc["eval_corpus"]["total"] > 0
    assert set(sc) >= {"eval_corpus", "ci_gates", "knowledge_assets", "cost_mechanisms"}


def test_eval_corpus_ratchet():
    """The flywheel ratchet: the governed eval corpus must never shrink below the
    committed snapshot. Adding cases is fine (run --update); removing fails CI."""
    committed = json.loads(SCORECARD.read_text(encoding="utf-8"))["eval_corpus"]["total"]
    current = _SC.compute()["eval_corpus"]["total"]
    assert current >= committed, (
        f"eval corpus shrank ({current} < committed {committed}) — the flywheel "
        f"ratchet broke. The eval set must only grow.")


def test_all_knowledge_entry_paths_gated():
    # The N7 thesis: the eval governs every entry. Every gated suite must hold.
    sc = _SC.compute()
    assert sc["ci_gates"]["gated_suites"] >= 4
    assert all(sc["ci_gates"]["suites"].values())


def test_marginal_cost_mechanism_wired():
    # The concrete cost↓ reducer must stay wired (cartographer skip on cache).
    sc = _SC.compute()
    assert sc["cost_mechanisms"]["cartographer_skip_on_fresh_cache"] is True
