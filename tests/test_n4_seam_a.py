"""
N4 seam A — findings provenance + gated auto-escalation (VAL-192).

The seam-A motion, offline (no LLM, no DB):
  1. New findings are stamped with provenance (run_id, source query, confidence)
     — the legacy record dropped these even though they were available.
  2. Auto-escalation (a finding bumped a severity level purely for surviving 5+
     runs — authority without basis) is STAGED for review when
     VALINOR_MEMORY_REVIEW=1, and only applied to the live finding on approval.
  3. Routine tracking stays automatic (default off = legacy behavior).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from shared.memory.client_profile import (
    ClientProfile, build_pending_escalation, has_provenance,
)
from shared.memory.profile_extractor import ProfileExtractor

_ROOT = Path(__file__).resolve().parent.parent
_EXT = ProfileExtractor()


class _FakeProvenance:
    def run_confidence(self):
        return 0.8, "PROVISIONAL"


def _profile_with_finding(runs_open=5, severity="MEDIUM", fid="f1"):
    p = ClientProfile.new("Gloria_SA")
    p.known_findings[fid] = {
        "id": fid, "title": "t", "severity": severity, "agent": "analyst",
        "first_seen": "2026-01-01", "last_seen": "2026-01-01", "runs_open": runs_open,
    }
    return p


# ── 1. provenance stamp on new findings ───────────────────────────────────────

def test_new_finding_gets_provenance_stamp():
    p = ClientProfile.new("Gloria_SA")
    findings = {"analyst": {"findings": [
        {"id": "f1", "title": "T", "severity": "HIGH", "sql": "SELECT * FROM ventas"},
    ]}}
    _EXT.update_from_run(p, findings, {"entities": {}}, {}, "Q2",
                         run_id="job7", provenance=_FakeProvenance())
    rec = p.known_findings["f1"]
    assert rec["run_id"] == "job7"
    assert rec["source_query"] == "SELECT * FROM ventas"
    assert rec["confidence"] == 0.8


# ── 2. auto-escalation: staged vs applied ─────────────────────────────────────

def test_escalation_staged_when_flag_on():
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, run_id="job1", confidence=0.8,
                                   confidence_label="PROVISIONAL", stage=True)
    assert p.known_findings["f1"]["severity"] == "MEDIUM"        # NOT applied
    pend = p.get_pending_escalations()
    assert len(pend) == 1
    assert pend[0]["from_severity"] == "MEDIUM" and pend[0]["to_severity"] == "HIGH"
    assert pend[0]["run_id"] == "job1" and pend[0]["confidence"] == 0.8
    assert has_provenance(pend[0])


def test_escalation_applied_when_flag_off():
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, stage=False)
    assert p.known_findings["f1"]["severity"] == "HIGH"          # legacy mutate
    assert p.known_findings["f1"]["auto_escalated"] is True
    assert p.get_pending_escalations() == []


def test_below_threshold_no_escalation():
    p = _profile_with_finding(runs_open=4, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, stage=False)
    assert p.known_findings["f1"]["severity"] == "MEDIUM"
    assert p.get_pending_escalations() == []


def test_escalation_dedup_does_not_restage():
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, run_id="j", confidence=0.8, stage=True)
    _EXT._auto_escalate_persistent(p, run_id="j", confidence=0.8, stage=True)
    assert len(p.get_pending_escalations()) == 1                 # not 2


# ── 3. approve applies; reject keeps ──────────────────────────────────────────

def test_approve_escalation_applies_severity():
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, run_id="j", confidence=0.8, stage=True)
    pid = p.get_pending_escalations()[0]["proposal_id"]
    rec = p.approve_pending_escalation(pid, reviewed_by="loren")
    assert rec["status"] == "approved" and rec["reviewed_by"] == "loren"
    assert p.known_findings["f1"]["severity"] == "HIGH"         # applied on approval
    assert p.known_findings["f1"]["auto_escalated"] is True


def test_reject_escalation_keeps_severity():
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, run_id="j", confidence=0.8, stage=True)
    pid = p.get_pending_escalations()[0]["proposal_id"]
    assert p.reject_pending_escalation(pid, reason="false alarm")["status"] == "rejected"
    assert p.known_findings["f1"]["severity"] == "MEDIUM"       # unchanged


def test_approve_escalation_for_resolved_finding_is_safe():
    # If the finding vanished from known_findings before approval, approve must
    # not crash — it just records the decision.
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, run_id="j", confidence=0.8, stage=True)
    pid = p.get_pending_escalations()[0]["proposal_id"]
    p.known_findings.pop("f1")
    rec = p.approve_pending_escalation(pid)
    assert rec is not None and rec["status"] == "approved"


# ── integration via update_from_run ───────────────────────────────────────────

def test_update_from_run_stages_escalation_when_flag_on(monkeypatch):
    monkeypatch.setenv("VALINOR_MEMORY_REVIEW", "1")
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    findings = {"analyst": {"findings": [{"id": "f1", "title": "t", "severity": "MEDIUM"}]}}
    _EXT.update_from_run(p, findings, {"entities": {}}, {}, "Q2",
                         run_id="job7", provenance=_FakeProvenance())
    assert p.known_findings["f1"]["severity"] == "MEDIUM"       # not applied
    assert len(p.get_pending_escalations()) == 1


def test_update_from_run_autoescalates_when_flag_off(monkeypatch):
    monkeypatch.delenv("VALINOR_MEMORY_REVIEW", raising=False)
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    findings = {"analyst": {"findings": [{"id": "f1", "title": "t", "severity": "MEDIUM"}]}}
    _EXT.update_from_run(p, findings, {"entities": {}}, {}, "Q2",
                         run_id="job7", provenance=_FakeProvenance())
    assert p.known_findings["f1"]["severity"] == "HIGH"         # legacy mutate
    assert p.get_pending_escalations() == []


def test_update_from_run_falls_back_when_no_provenance(monkeypatch):
    # Review on but provenance missing → legacy auto-escalate (don't stage a
    # provenance-less proposal the linter would reject).
    monkeypatch.setenv("VALINOR_MEMORY_REVIEW", "1")
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    findings = {"analyst": {"findings": [{"id": "f1", "title": "t", "severity": "MEDIUM"}]}}
    _EXT.update_from_run(p, findings, {"entities": {}}, {}, "Q2",
                         run_id="job7", provenance=None)
    assert p.known_findings["f1"]["severity"] == "HIGH"
    assert p.get_pending_escalations() == []


# ── round-trip + linter ───────────────────────────────────────────────────────

def test_pending_escalations_round_trip():
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, run_id="j", confidence=0.8, stage=True)
    restored = ClientProfile.from_dict(p.to_dict())
    assert len(restored.get_pending_escalations()) == 1
    assert restored.get_pending_escalations()[0]["to_severity"] == "HIGH"


def test_from_dict_with_pending_escalations_none():
    p = ClientProfile.from_dict({"client_name": "C", "pending_escalations": None})
    assert p.pending_escalations == []
    assert p.get_pending_escalations() == []


_LINT_SPEC = importlib.util.spec_from_file_location(
    "provenance_linter", _ROOT / "scripts" / "provenance_linter.py")
_LINT = importlib.util.module_from_spec(_LINT_SPEC)
_LINT_SPEC.loader.exec_module(_LINT)


def test_linter_catches_escalation_missing_provenance():
    p = ClientProfile.new("Bad")
    bad = build_pending_escalation("f1", "MEDIUM", "HIGH", 5,
                                   run_id="", client_tag="Bad", confidence=0.8)  # no run_id
    p.add_pending_escalation(bad)
    violations = _LINT.lint_profile(p.to_dict())
    assert any("pending_escalations" in v for v in violations)


def test_linter_passes_well_formed_escalation():
    p = _profile_with_finding(runs_open=5, severity="MEDIUM")
    _EXT._auto_escalate_persistent(p, run_id="j", confidence=0.8, stage=True)
    assert _LINT.lint_profile(p.to_dict()) == []
