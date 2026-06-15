"""
N5 agent-claims grounding instrument (VAL-192).

Verifies the uncited-claims audit classifies each atomic claim into the right
bucket (cited / failed / unresolvable / uncited / declared) and computes the
rate over the declared-excluded denominator — mirroring the N1 instrument tests.
"""

from __future__ import annotations

from valinor.verification import VerificationResult, AtomicClaim
from valinor.quality.agent_grounding_metrics import (
    score_agent_claims, AgentClaimsAudit, _claim_is_declared,
)


def _r(cid, status, vq=None):
    return VerificationResult(claim_id=cid, status=status, verification_query=vq)


def _c(cid, text):
    return AtomicClaim(claim_id=cid, finding_id="f", claim_text=text, claim_type="numeric")


# ── bucket classification ─────────────────────────────────────────────────────

def test_cited_verified_and_approximate():
    res = [_r("a", "VERIFIED", "total_revenue_summary"),
           _r("b", "APPROXIMATE", "ar_outstanding_actual")]
    audit = score_agent_claims(res)
    assert audit.cited == 2
    assert audit.uncited == 0 and audit.failed == 0


def test_failed_is_its_own_bucket():
    audit = score_agent_claims([_r("a", "FAILED", "some_query")])
    assert audit.failed == 1
    assert audit.cited == 0 and audit.uncited == 0


def test_unresolvable_vs_uncited_split_on_query():
    res = [
        _r("a", "UNVERIFIABLE", "attempted_query"),   # query tried, no match → unresolvable
        _r("b", "UNVERIFIABLE", None),                # never cited → uncited
    ]
    audit = score_agent_claims(res)
    assert audit.unresolvable == 1
    assert audit.uncited == 1


def test_verified_without_query_counts_uncited():
    # Strict definition: a citation requires a non-null verification_query.
    audit = score_agent_claims([_r("a", "VERIFIED", None)])
    assert audit.uncited == 1 and audit.cited == 0


# ── declared inferences excluded from the denominator ─────────────────────────

def test_declared_bracket_marker_excluded():
    res = [_r("a", "UNVERIFIABLE", None)]
    claims = [_c("a", "Proyección de caja [ESTIMADO] para Q3")]
    audit = score_agent_claims(res, claims)
    assert audit.declared_inference == 1
    assert audit.uncited == 0
    assert audit.verifiable == 0


def test_declared_tilde_marker_excluded():
    res = [_r("a", "UNVERIFIABLE", None)]
    claims = [_c("a", "ingresos ~450000 aprox")]
    audit = score_agent_claims(res, claims)
    assert audit.declared_inference == 1
    assert audit.uncited == 0


def test_declared_takes_precedence_over_status():
    # Even a would-be-cited claim, if declared, leaves the denominator.
    res = [_r("a", "VERIFIED", "q")]
    claims = [_c("a", "valor [INFERIDO] de tendencia")]
    audit = score_agent_claims(res, claims)
    assert audit.declared_inference == 1
    assert audit.cited == 0


def test_hedging_word_is_not_a_declared_marker():
    # "aproximadamente" is hedging, not the honesty protocol marker → still counts.
    assert _claim_is_declared("aproximadamente 13.5M en ventas") is False
    assert _claim_is_declared("13.5M [ESTIMADO]") is True


# ── value_confidence (typed inference marker) ─────────────────────────────────

def _c_fid(cid, fid, text=""):
    return AtomicClaim(claim_id=cid, finding_id=fid, claim_text=text, claim_type="numeric")


def _findings(*pairs):
    return {"analyst": {"findings": [{"id": fid, "value_confidence": vc} for fid, vc in pairs]}}


def test_inferred_finding_makes_claim_declared():
    res = [_r("c1", "UNVERIFIABLE", None)]
    claims = [_c_fid("c1", "FIN-1")]
    audit = score_agent_claims(res, claims, _findings(("FIN-1", "inferred")))
    assert audit.declared_inference == 1 and audit.uncited == 0


def test_estimated_finding_makes_claim_declared():
    res = [_r("c1", "UNVERIFIABLE", None)]
    claims = [_c_fid("c1", "FIN-1")]
    audit = score_agent_claims(res, claims, _findings(("FIN-1", "estimated")))
    assert audit.declared_inference == 1 and audit.uncited == 0


def test_measured_finding_claim_must_be_cited():
    # A "measured" claim with no citation is a genuine uncited authoring failure.
    res = [_r("c1", "UNVERIFIABLE", None)]
    claims = [_c_fid("c1", "FIN-1")]
    audit = score_agent_claims(res, claims, _findings(("FIN-1", "measured")))
    assert audit.declared_inference == 0 and audit.uncited == 1


def test_value_confidence_precedence_over_cited_status():
    # An inferred finding's claim leaves the denominator even if it would be cited.
    res = [_r("c1", "VERIFIED", "q")]
    claims = [_c_fid("c1", "FIN-1")]
    audit = score_agent_claims(res, claims, _findings(("FIN-1", "inferred")))
    assert audit.declared_inference == 1 and audit.cited == 0


def test_value_confidence_mixed_run():
    res = [
        _r("c1", "VERIFIED", "q1"),       # measured → cited
        _r("c2", "UNVERIFIABLE", None),   # measured → uncited
        _r("c3", "UNVERIFIABLE", None),   # inferred → declared
        _r("c4", "FAILED", "q2"),         # estimated → declared
    ]
    claims = [_c_fid("c1", "M1"), _c_fid("c2", "M1"), _c_fid("c3", "I1"), _c_fid("c4", "E1")]
    findings = _findings(("M1", "measured"), ("I1", "inferred"), ("E1", "estimated"))
    audit = score_agent_claims(res, claims, findings)
    assert audit.declared_inference == 2     # c3, c4
    assert audit.verifiable == 2             # c1, c2
    assert audit.cited == 1 and audit.uncited == 1
    assert round(audit.uncited_rate, 4) == 0.5


# ── rate computation ──────────────────────────────────────────────────────────

def test_uncited_rate_over_verifiable_denominator():
    res = [
        _r("a", "VERIFIED", "q1"),          # cited
        _r("b", "APPROXIMATE", "q2"),       # cited
        _r("c", "UNVERIFIABLE", None),      # uncited
        _r("d", "UNVERIFIABLE", None),      # uncited
        _r("e", "UNVERIFIABLE", "q3"),      # unresolvable
        _r("f", "FAILED", "q4"),            # failed
        _r("g", "UNVERIFIABLE", None),      # declared → excluded
    ]
    claims = [_c("g", "~estimado")]
    audit = score_agent_claims(res, claims)
    assert audit.total_claims == 7
    assert audit.declared_inference == 1
    assert audit.verifiable == 6
    assert audit.cited == 2 and audit.uncited == 2
    assert audit.unresolvable == 1 and audit.failed == 1
    assert round(audit.uncited_rate, 4) == round(2 / 6, 4)
    assert round(audit.cited_rate, 4) == round(2 / 6, 4)


def test_empty_results_zero_rates():
    audit = score_agent_claims([])
    assert audit.total_claims == 0
    assert audit.uncited_rate == 0.0 and audit.cited_rate == 0.0


# ── dict compatibility (the serialized on-disk form) ──────────────────────────

def test_accepts_dict_results_and_claims():
    res = [
        {"claim_id": "a", "status": "VERIFIED", "verification_query": "q1"},
        {"claim_id": "b", "status": "UNVERIFIABLE", "verification_query": None},
    ]
    claims = [{"claim_id": "a", "claim_text": "plain claim"}]
    audit = score_agent_claims(res, claims)
    assert audit.cited == 1 and audit.uncited == 1
    assert audit.declared_inference == 0


def test_to_dict_shape():
    audit = score_agent_claims([_r("a", "VERIFIED", "q")])
    d = audit.to_dict()
    assert set(d) == {
        "total_claims", "cited", "failed", "unresolvable", "uncited",
        "declared_inference", "verifiable", "uncited_rate", "cited_rate",
    }
    assert d["cited"] == 1 and d["uncited_rate"] == 0.0
