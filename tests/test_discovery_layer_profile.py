"""
Unit tests for the discovery per-layer latency/cost breakdown (VAL-145).

Pure: feeds hand-built per-variant timings to the aggregation + markdown render —
no pipeline run, no LLM — so it stays in the default (fast) suite. The end-to-end
pipeline path is exercised by the script itself (and the benchmark's own tests).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# The harness lives in scripts/ (not a package); load it by path.
_SPEC = importlib.util.spec_from_file_location(
    "discovery_layer_profile",
    Path(__file__).resolve().parent.parent / "scripts" / "discovery_layer_profile.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
aggregate = _MOD.aggregate
render_markdown = _MOD.render_markdown


def _per_variant():
    def v(name, t):
        return {"variant": name, "tables": 10,
                "timings_seconds": dict(zip("L0 L1 L2 L3 L4 L5".split(), t))}
    return [
        v("gloria_full", [0.004, 0.002, 0.001, 0.0003, 0.0001, 0.0002]),
        v("gloria_no_fks", [0.003, 0.002, 0.0008, 0.0002, 0.0001, 0.0001]),
        v("gloria_obfuscated", [0.003, 0.0024, 0.0009, 0.00025, 0.00012, 0.00015]),
    ]


def test_aggregate_has_six_layers():
    report = aggregate(_per_variant())
    assert [layer["layer"] for layer in report["layers"]] == \
        ["L0", "L1", "L2", "L3", "L4", "L5"]


def test_shares_sum_to_about_100():
    report = aggregate(_per_variant())
    total = sum(layer["share_pct"] for layer in report["layers"])
    assert abs(total - 100.0) < 0.5


def test_only_l5_issues_llm_calls():
    report = aggregate(_per_variant())
    by_layer = {layer["layer"]: layer for layer in report["layers"]}
    assert by_layer["L5"]["llm_calls_real"] == 2
    assert all(by_layer[layer]["llm_calls_real"] == 0
               for layer in ["L0", "L1", "L2", "L3", "L4"])


def test_cost_is_l5_only_and_mock_is_free():
    report = aggregate(_per_variant())
    by_layer = {layer["layer"]: layer for layer in report["layers"]}
    # L5 = 2 Haiku calls * $0.008 projected; Mock cost always $0.
    assert by_layer["L5"]["cost_usd_real_projected"] == 0.016
    assert all(layer["cost_usd_mock"] == 0.0 for layer in report["layers"])
    assert report["totals"]["cost_usd_real_projected"] == 0.016


def test_markdown_renders():
    md = render_markdown(aggregate(_per_variant()))
    assert "# VAL-145" in md
    assert "Per-layer breakdown" in md
    assert "L5" in md
