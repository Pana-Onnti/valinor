"""
N4 memory write-path — propose → review → merge + provenance (VAL-192).

The hito, demonstrated offline (no LLM, no DB):
  1. A learning is STAGED as a pending proposal with provenance, NOT activated.
  2. Approve → it MERGES into the active refinement, stamped + audited.
  3. Reject → archived with reason, never merged.
  4. Provenance is mandatory (the CI linter fails otherwise).
  5. The whole path is gated by VALINOR_MEMORY_REVIEW (default off = legacy
     auto-write, prod unchanged).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from shared.memory.client_profile import (
    ClientProfile,
    ClientRefinement,
    build_pending_refinement,
    extract_finding_ids,
    has_provenance,
    memory_review_enabled,
)

_ROOT = Path(__file__).resolve().parent.parent


def _proposal(**over):
    base = dict(
        refinement={"table_weights": {"ventas": 2.0}, "query_hints": ["focus AR"],
                    "focus_areas": [], "suppress_ids": [], "context_block": "ctx",
                    "generated_at": "2026-06-14T00:00:00"},
        run_id="job_42", client_tag="Gloria_SA",
        source_findings_ids=["f1", "f2"], confidence=0.91, confidence_label="CONFIRMED",
        proposal_id="pr_test1", generated_at="2026-06-14T00:00:00",
    )
    base.update(over)
    return build_pending_refinement(**base)


# ── 1. stage does NOT activate ────────────────────────────────────────────────

def test_stage_does_not_activate_refinement():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    assert p.refinement is None                      # active refinement untouched
    assert len(p.get_pending_refinements()) == 1
    assert p.get_pending_refinements()[0]["status"] == "pending"


# ── 2. approve merges; 3. reject archives ─────────────────────────────────────

def test_approve_merges_into_active_refinement():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    rec = p.approve_pending_refinement("pr_test1", reviewed_by="loren")
    assert rec is not None
    assert rec["status"] == "approved"
    assert rec["reviewed_by"] == "loren"
    assert rec["reviewed_at"]
    # MERGED into active refinement
    assert p.refinement["table_weights"] == {"ventas": 2.0}
    assert p.get_pending_refinements(status="pending") == []
    assert len(p.get_pending_refinements(status="approved")) == 1


def test_reject_archives_without_merge():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    rec = p.reject_pending_refinement("pr_test1", reason="hallucinated table weight")
    assert rec["status"] == "rejected"
    assert rec["review_reason"] == "hallucinated table weight"
    assert p.refinement is None                      # never merged
    assert p.get_pending_refinements(status="pending") == []


def test_approve_unknown_proposal_returns_none():
    p = ClientProfile.new("Gloria_SA")
    assert p.approve_pending_refinement("nope") is None
    assert p.reject_pending_refinement("nope") is None


def test_cannot_double_review():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    assert p.approve_pending_refinement("pr_test1") is not None
    # already approved → no longer pending
    assert p.approve_pending_refinement("pr_test1") is None
    assert p.reject_pending_refinement("pr_test1") is None


# ── 4. provenance is mandatory ────────────────────────────────────────────────

def test_build_pending_carries_full_provenance():
    rec = _proposal()
    assert has_provenance(rec)
    for key in ("run_id", "client_tag", "generated_at"):
        assert rec[key]
    assert rec["confidence"] == 0.91
    assert rec["source_findings_ids"] == ["f1", "f2"]


@pytest.mark.parametrize("missing", ["run_id", "client_tag", "generated_at"])
def test_has_provenance_rejects_missing_field(missing):
    rec = _proposal()
    rec[missing] = ""
    assert has_provenance(rec) is False


def test_has_provenance_rejects_missing_confidence():
    rec = _proposal(confidence=None)
    assert has_provenance(rec) is False


def test_extract_finding_ids_from_swarm_output():
    findings = {
        "analyst": {"findings": [{"id": "a1"}, {"id": "a2"}]},
        "sentinel": {"findings": [{"id": "s1"}]},
        "_reconciliation": {"conflicts": 0},          # metadata skipped
        "hunter": {"error": "timeout"},               # no findings key
    }
    assert sorted(extract_finding_ids(findings)) == ["a1", "a2", "s1"]


# ── 5. flag gating + round-trip ───────────────────────────────────────────────

def test_memory_review_flag(monkeypatch):
    # Flipped 2026-06-14: review is the DEFAULT; only "0" disables it.
    monkeypatch.delenv("VALINOR_MEMORY_REVIEW", raising=False)
    assert memory_review_enabled() is True
    monkeypatch.setenv("VALINOR_MEMORY_REVIEW", "1")
    assert memory_review_enabled() is True
    monkeypatch.setenv("VALINOR_MEMORY_REVIEW", "0")
    assert memory_review_enabled() is False


def test_pending_refinements_survive_round_trip():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    restored = ClientProfile.from_dict(p.to_dict())
    assert len(restored.get_pending_refinements()) == 1
    assert restored.get_pending_refinements()[0]["proposal_id"] == "pr_test1"


def test_old_profile_without_field_defaults_empty():
    # A pre-N4 profile dict has no pending_refinements key.
    old = {"client_name": "Legacy", "refinement": {"table_weights": {}}}
    restored = ClientProfile.from_dict(old)
    assert restored.get_pending_refinements() == []


# ── the CI provenance linter ──────────────────────────────────────────────────

_LINT_SPEC = importlib.util.spec_from_file_location(
    "provenance_linter", _ROOT / "scripts" / "provenance_linter.py")
_LINT = importlib.util.module_from_spec(_LINT_SPEC)
_LINT_SPEC.loader.exec_module(_LINT)


def test_linter_passes_well_formed_profile():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    assert _LINT.lint_profile(p.to_dict()) == []


def test_linter_catches_missing_provenance():
    p = ClientProfile.new("Gloria_SA")
    bad = _proposal()
    bad["run_id"] = ""               # strip provenance
    p.add_pending_refinement(bad)
    violations = _LINT.lint_profile(p.to_dict())
    assert len(violations) == 1 and "missing provenance" in violations[0]


# ── adapter interception (offline: fake store + fake RefinementAgent) ──────────
# Capture the REAL coroutine at import time so the test is immune to other suites
# leaking a Mock onto valinor_adapter.ValinorAdapter (order-independence). We call
# it as an unbound function with a SimpleNamespace `self` — no adapter __init__.
import types  # noqa: E402
from core.adapters import valinor_adapter as _VA  # noqa: E402
_RUN_REFINEMENT_BG = _VA.ValinorAdapter._run_refinement_background


def _make_adapter():
    saved = {}

    class _FakeStore:
        async def save(self, profile):
            saved["profile"] = profile
            return True

    return types.SimpleNamespace(profile_store=_FakeStore()), saved


def _patch_refinement_agent(monkeypatch):
    class _FakeAgent:
        async def analyze_run(self, profile, findings, entity_map, reports, period, run_delta):
            return ClientRefinement(table_weights={"ventas": 3.0},
                                    query_hints=["AR"], generated_at="2026-06-14T01:00:00")
    monkeypatch.setattr(_VA, "RefinementAgent", _FakeAgent)


class _FakeProvenance:
    def run_confidence(self):
        return 0.88, "CONFIRMED"


async def test_adapter_stages_pending_when_flag_on(monkeypatch):
    monkeypatch.setenv("VALINOR_MEMORY_REVIEW", "1")
    adapter, saved = _make_adapter()
    _patch_refinement_agent(monkeypatch)
    profile = ClientProfile.new("Gloria_SA")
    findings = {"analyst": {"findings": [{"id": "a1"}]}}

    await _RUN_REFINEMENT_BG(
        adapter, profile, findings, {}, {}, "Q2-2025", {},
        job_id="job_99", provenance=_FakeProvenance())

    assert profile.refinement is None                       # NOT auto-written
    pend = profile.get_pending_refinements()
    assert len(pend) == 1
    assert pend[0]["run_id"] == "job_99"
    assert pend[0]["client_tag"] == "Gloria_SA"
    assert pend[0]["confidence"] == 0.88
    assert pend[0]["source_findings_ids"] == ["a1"]
    assert has_provenance(pend[0])


async def test_adapter_auto_writes_when_flag_off(monkeypatch):
    monkeypatch.setenv("VALINOR_MEMORY_REVIEW", "0")   # explicit legacy auto-write
    adapter, saved = _make_adapter()
    _patch_refinement_agent(monkeypatch)
    profile = ClientProfile.new("Gloria_SA")

    await _RUN_REFINEMENT_BG(
        adapter, profile, {}, {}, {}, "Q2-2025", {}, job_id="job_99", provenance=_FakeProvenance())

    assert profile.refinement is not None                   # legacy auto-write
    assert profile.refinement["table_weights"] == {"ventas": 3.0}
    assert profile.get_pending_refinements() == []


async def test_adapter_falls_back_to_autowrite_when_provenance_none(monkeypatch):
    # Review ON but provenance unavailable → staging would fail the linter, so
    # the adapter falls back to legacy auto-write rather than stage garbage.
    monkeypatch.setenv("VALINOR_MEMORY_REVIEW", "1")
    adapter, _ = _make_adapter()
    _patch_refinement_agent(monkeypatch)
    profile = ClientProfile.new("Gloria_SA")

    await _RUN_REFINEMENT_BG(
        adapter, profile, {}, {}, {}, "Q2-2025", {}, job_id="job_99", provenance=None)

    assert profile.get_pending_refinements() == []
    assert profile.refinement is not None


# ── hardening: corrupt/legacy serialization + review state transitions ────────

def test_from_dict_with_pending_refinements_none():
    # A corrupt/legacy dict carrying an explicit null must not leave the field
    # None (which would crash every write-path method).
    p = ClientProfile.from_dict({"client_name": "C", "pending_refinements": None})
    assert p.pending_refinements == []
    assert p.get_pending_refinements() == []
    p.add_pending_refinement(_proposal())              # must not crash
    assert len(p.get_pending_refinements()) == 1


def test_reject_then_approve_returns_none():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    assert p.reject_pending_refinement("pr_test1", reason="bad") is not None
    assert p.approve_pending_refinement("pr_test1") is None   # no longer pending
    assert p.refinement is None                              # never merged


def test_reviewed_proposals_survive_round_trip():
    p = ClientProfile.new("Gloria_SA")
    p.add_pending_refinement(_proposal())
    p.approve_pending_refinement("pr_test1", reviewed_by="loren")
    restored = ClientProfile.from_dict(p.to_dict())
    rec = restored.get_pending_refinements(status="approved")[0]
    assert rec["reviewed_by"] == "loren" and rec["reviewed_at"]
    assert restored.refinement is not None                  # active after round-trip


def test_extract_finding_ids_tolerates_malformed():
    assert extract_finding_ids(None) == []
    assert extract_finding_ids("not a dict") == []
    assert extract_finding_ids({"analyst": None}) == []
    assert extract_finding_ids({"analyst": {"findings": None}}) == []
    assert extract_finding_ids({"analyst": {"findings": "weird"}}) == []
    assert extract_finding_ids({"analyst": {"findings": [{"no_id": 1}, {"id": "a1"}]}}) == ["a1"]


def test_provenanceless_pending_is_not_approvable():
    # The approve endpoint refuses (400) a pending proposal lacking provenance;
    # this is the predicate it checks.
    p = ClientProfile.new("Gloria_SA")
    bad = _proposal(client_tag="")           # strip provenance
    p.add_pending_refinement(bad)
    target = next(x for x in p.get_pending_refinements("pending")
                  if x["proposal_id"] == "pr_test1")
    assert has_provenance(target) is False


def test_linter_main_exit_codes(tmp_path):
    import json as _json
    good = ClientProfile.new("Good"); good.add_pending_refinement(_proposal())
    bad = ClientProfile.new("Bad")
    b = _proposal(client_tag="")             # strip provenance
    bad.add_pending_refinement(b)
    gp = tmp_path / "good.json"; gp.write_text(_json.dumps(good.to_dict()))
    bp = tmp_path / "bad.json"; bp.write_text(_json.dumps(bad.to_dict()))
    assert _LINT.main([str(gp)]) == 0
    assert _LINT.main([str(bp)]) == 1
