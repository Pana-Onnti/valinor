"""
Unit tests for the Number Registry A/B capture harness (VAL-163).

Validates the orchestration offline (no LLM, no DB) by injecting a fake narrator
runner and a fake verification-report builder: control must run blind to the
registry, treatment must run with it, and the emitted dataset must carry the
serialized registry. The real narrators/verifier path is the live-run step.
"""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass
from pathlib import Path

# The harness lives in scripts/ (not a package); load it by path.
_SPEC = importlib.util.spec_from_file_location(
    "capture_narrator_ab",
    Path(__file__).resolve().parent.parent / "scripts" / "capture_narrator_ab.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
capture_ab = _MOD.capture_ab
serialize_registry = _MOD.serialize_registry


@dataclass
class _Entry:
    value: float
    unit: str = "EUR"
    dimension: str = "currency"
    source_query: str = "q_rev"


class _FakeVR:
    def __init__(self):
        self.number_registry = {"total_revenue": _Entry(123456.0)}


def _state():
    return {
        "entity_map": {"tables": {}},
        "query_results": {"results": {}},
        "baseline": {"data_available": True, "total_revenue": 123456.0},
        "findings": {"executive": {"summary": "rev 123456"}},
        "memory": None,
        "client_config": {"name": "Golden PyME"},
    }


def _capture(only=None):
    """Run capture_ab with a fake narrator runner + fake VR builder. Records calls."""
    calls = []

    async def fake_run_narrators(**kwargs):
        calls.append(kwargs.get("verification_report"))
        vr = kwargs.get("verification_report")
        tag = "treat" if vr is not None else "ctrl"
        return {
            "briefing_ceo": f"# ceo {tag} 123456",
            "reporte_ejecutivo": f"# exec {tag} 999",
        }

    control, treatment, dataset = asyncio.run(
        capture_ab(_state(), only=only,
                   run_narrators_fn=fake_run_narrators,
                   build_vr_fn=lambda s: _FakeVR()))
    return control, treatment, dataset, calls


def test_control_runs_without_registry_treatment_with_it():
    _, _, _, calls = _capture()
    # First call (control) gets verification_report=None; second (treatment) gets the VR.
    assert calls[0] is None
    assert isinstance(calls[1], _FakeVR)


def test_dataset_carries_serialized_registry():
    _, _, dataset, _ = _capture()
    assert dataset["number_registry"]["total_revenue"]["value"] == 123456.0
    assert "findings" in dataset and "query_results" in dataset


def test_branches_are_distinct():
    control, treatment, _, _ = _capture()
    assert "ctrl" in control["briefing_ceo"]
    assert "treat" in treatment["briefing_ceo"]


def test_only_filter_subsets_both_branches():
    control, treatment, _, _ = _capture(only={"briefing_ceo"})
    assert set(control) == {"briefing_ceo"}
    assert set(treatment) == {"briefing_ceo"}


def test_serialize_registry_handles_dict_entries():
    class _VR:
        number_registry = {"ar": {"value": 50.0}}
    out = serialize_registry(_VR())
    assert out["ar"]["value"] == 50.0
