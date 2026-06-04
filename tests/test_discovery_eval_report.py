"""
Unit tests for the discovery eval report builder (VAL-145).

Pure: feeds hand-built BenchmarkResults to the §7 report assembly — no benchmark
run, no LLM — so it stays in the default (fast) suite.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from valinor.discovery.benchmark import BenchmarkResult

# The generator lives in scripts/ (not a package); load it by path.
_SPEC = importlib.util.spec_from_file_location(
    "discovery_eval_report",
    Path(__file__).resolve().parent.parent / "scripts" / "discovery_eval_report.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
build_eval_report = _MOD.build_eval_report
render_markdown = _MOD.render_markdown


def _results():
    return [
        BenchmarkResult(variant="gloria_no_fks", mode="fk_only",
                        fk_recall=1.0, fk_precision=0.11, fk_f1=0.2,
                        total_predicted=71, total_golden=8, elapsed_seconds=0.1),
        BenchmarkResult(variant="gloria_no_fks", mode="ensemble",
                        fk_recall=0.0, fk_precision=0.0, fk_f1=0.0,
                        total_predicted=0, total_golden=8, entity_accuracy=0.4),
        BenchmarkResult(variant="gloria_no_fks", mode="ensemble_hinted",
                        hint_pack_name="argentina_gestion",
                        fk_recall=0.5, fk_precision=1.0, fk_f1=0.66,
                        total_predicted=4, total_golden=8, entity_accuracy=0.4,
                        llm_calls=0, llm_cost_usd=0.0, elapsed_seconds=0.01),
    ]


def test_report_has_section7_structure():
    report = build_eval_report(_results())
    assert set(report) >= {
        "fk_inference", "hint_pack_ablation", "entity_classification",
        "cost_latency", "targets", "remaining",
    }


def test_baseline_mapping_applied():
    report = build_eval_report(_results())
    baselines = {r["baseline"] for r in report["fk_inference"]}
    assert baselines == {"Structural-only", "Ours (no hint pack)", "Ours (full)"}


def test_ablation_delta_computed():
    report = build_eval_report(_results())
    delta = report["hint_pack_ablation"]["gloria_no_fks"]
    # hinted recall 0.5 − no-hint recall 0.0
    assert delta["recall_delta"] == 0.5


def test_targets_checked_honestly():
    report = build_eval_report(_results())
    by_metric = {t["metric"]: t for t in report["targets"]}
    # recall on no-constraint variant = 0.5 < 0.85 → not met (honest)
    assert by_metric["FK recall (no-constraint schemas)"]["met"] is False
    # precision 1.0 ≥ 0.90 → met
    assert by_metric["FK precision (Ours full)"]["met"] is True


def test_markdown_renders():
    md = render_markdown(build_eval_report(_results()))
    assert "# VAL-145" in md
    assert "hint-pack ablation" in md
    assert "Targets" in md
