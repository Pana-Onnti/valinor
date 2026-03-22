"""
Tests for temporal claim verification (VAL-38) and negative claim verification (VAL-39).

Validates:
  1. Temporal claim detection (YoY, QoQ, MoM patterns)
  2. Temporal claim verification against query results
  3. Negative claim detection ("no", "none", "zero", "never", "no hay")
  4. Negative claim verification against query results
  5. Integration with the main verify_findings() flow
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest

from valinor.verification import AtomicClaim, VerificationEngine, VerificationReport


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def query_results_with_yoy():
    """Query results including YoY comparison data."""
    return {
        "results": {
            "total_revenue_summary": {
                "rows": [{
                    "num_invoices": 3139,
                    "total_revenue": 1631559.62,
                    "avg_invoice": 519.77,
                    "distinct_customers": 1223,
                }],
                "row_count": 1,
            },
            "yoy_comparison": {
                "rows": [
                    {"year": 2023, "month": 12, "current_revenue": 130000, "prior_year_revenue": 120000, "yoy_growth_pct": 8.33},
                    {"year": 2024, "month": 1, "current_revenue": 140000, "prior_year_revenue": 125000, "yoy_growth_pct": 12.0},
                    {"year": 2024, "month": 12, "current_revenue": 150000, "prior_year_revenue": 130000, "yoy_growth_pct": 15.38},
                ],
                "row_count": 3,
            },
            "revenue_trend": {
                "rows": [
                    {"month": "2024-10-01", "revenue": 128000, "invoice_count": 315, "mom_growth_pct": -1.54},
                    {"month": "2024-11-01", "revenue": 135000, "invoice_count": 330, "mom_growth_pct": 5.47},
                    {"month": "2024-12-01", "revenue": 140000, "invoice_count": 340, "mom_growth_pct": 3.70},
                ],
                "row_count": 3,
            },
        },
        "errors": {},
    }


@pytest.fixture
def query_results_with_aging():
    """Query results with aging analysis (for negative claim tests)."""
    return {
        "results": {
            "total_revenue_summary": {
                "rows": [{
                    "num_invoices": 3139,
                    "total_revenue": 1631559.62,
                    "avg_invoice": 519.77,
                    "distinct_customers": 1223,
                }],
                "row_count": 1,
            },
            "aging_analysis": {
                "rows": [
                    {"tramo": "not_due", "num_payments": 50, "total_amount": 100000},
                    {"tramo": "0-30d", "num_payments": 30, "total_amount": 80000},
                    {"tramo": "31-60d", "num_payments": 20, "total_amount": 50000},
                    {"tramo": "61-90d", "num_payments": 10, "total_amount": 30000},
                    {"tramo": "91-180d", "num_payments": 5, "total_amount": 15000},
                ],
                "row_count": 5,
            },
        },
        "errors": {},
    }


@pytest.fixture
def query_results_no_overdue():
    """Query results with aging analysis showing zero overdue items."""
    return {
        "results": {
            "total_revenue_summary": {
                "rows": [{
                    "num_invoices": 100,
                    "total_revenue": 50000.0,
                    "avg_invoice": 500.0,
                    "distinct_customers": 20,
                }],
                "row_count": 1,
            },
            "aging_analysis": {
                "rows": [
                    {"tramo": "not_due", "num_payments": 50, "total_amount": 50000},
                ],
                "row_count": 1,
            },
        },
        "errors": {},
    }


@pytest.fixture
def baseline():
    return {
        "data_available": True,
        "total_revenue": 1631559.62,
        "num_invoices": 3139,
    }


# ═══════════════════════════════════════════════════════════════════════════
# TEST: VAL-38 — TEMPORAL CLAIM DETECTION
# ═══════════════════════════════════════════════════════════════════════════


class TestTemporalClaimDetection:

    def test_detects_yoy_growth(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        finding = {
            "id": "FIN-001",
            "headline": "Revenue grew 15% year-over-year in December",
            "evidence": "Based on yoy_comparison query",
        }
        claims = engine._detect_temporal_claims(finding, "analyst")
        assert len(claims) == 1
        assert claims[0].claim_type == "temporal"
        assert claims[0].temporal_type == "yoy"
        assert claims[0].claimed_growth_pct == 15.0

    def test_detects_yoy_decline(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        finding = {
            "id": "FIN-002",
            "headline": "Revenue declined 8.5% YoY",
            "evidence": "Revenue decreased significantly",
        }
        claims = engine._detect_temporal_claims(finding, "analyst")
        assert len(claims) == 1
        assert claims[0].claimed_growth_pct == -8.5

    def test_detects_qoq_pattern(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        finding = {
            "id": "FIN-003",
            "headline": "QoQ growth of 12% in Q4",
            "evidence": "Quarter-over-quarter improvement",
        }
        claims = engine._detect_temporal_claims(finding, "analyst")
        assert len(claims) == 1
        assert claims[0].temporal_type == "qoq"
        assert claims[0].claimed_growth_pct == 12.0

    def test_detects_mom_pattern(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        finding = {
            "id": "FIN-004",
            "headline": "Month-over-month increase of 3.7%",
            "evidence": "MoM trend",
        }
        claims = engine._detect_temporal_claims(finding, "analyst")
        assert len(claims) == 1
        assert claims[0].temporal_type == "mom"

    def test_no_temporal_in_plain_finding(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        finding = {
            "id": "FIN-005",
            "headline": "Total revenue is 1.6M EUR",
            "evidence": "From revenue summary",
        }
        claims = engine._detect_temporal_claims(finding, "analyst")
        assert len(claims) == 0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: VAL-38 — TEMPORAL CLAIM VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════


class TestTemporalClaimVerification:

    def test_verifies_yoy_claim_from_results(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        claim = AtomicClaim(
            claim_id="FIN-001_temporal_yoy",
            finding_id="FIN-001",
            claim_text="YoY growth: 15%",
            claim_type="temporal",
            claimed_value=15.0,
            claimed_unit="percent",
            temporal_type="yoy",
            claimed_growth_pct=15.0,
        )
        result = engine._verify_temporal_claim(claim)
        # Actual is 15.38%, claimed is 15% — within 2pp tolerance
        assert result.status == "VERIFIED"
        assert result.actual_value == 15.38

    def test_refutes_wrong_yoy_claim(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        claim = AtomicClaim(
            claim_id="FIN-001_temporal_yoy",
            finding_id="FIN-001",
            claim_text="YoY growth: 30%",
            claim_type="temporal",
            claimed_value=30.0,
            claimed_unit="percent",
            temporal_type="yoy",
            claimed_growth_pct=30.0,
        )
        result = engine._verify_temporal_claim(claim)
        # Actual is 15.38%, claimed is 30% — deviation >5pp
        assert result.status == "FAILED"

    def test_approximate_yoy_claim(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        claim = AtomicClaim(
            claim_id="FIN-001_temporal_yoy",
            finding_id="FIN-001",
            claim_text="YoY growth: 19%",
            claim_type="temporal",
            claimed_value=19.0,
            claimed_unit="percent",
            temporal_type="yoy",
            claimed_growth_pct=19.0,
        )
        result = engine._verify_temporal_claim(claim)
        # Actual is 15.38%, claimed is 19% — deviation ~3.6pp, within 5pp
        assert result.status == "APPROXIMATE"

    def test_verifies_mom_claim_from_trend(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        claim = AtomicClaim(
            claim_id="FIN-004_temporal_mom",
            finding_id="FIN-004",
            claim_text="MoM growth: 3.7%",
            claim_type="temporal",
            claimed_value=3.7,
            claimed_unit="percent",
            temporal_type="mom",
            claimed_growth_pct=3.7,
        )
        result = engine._verify_temporal_claim(claim)
        # Actual is 3.70%, claimed is 3.7% — exact match
        assert result.status == "VERIFIED"
        assert result.actual_value == 3.70

    def test_unverifiable_without_data(self, baseline):
        engine = VerificationEngine({"results": {}}, baseline)
        claim = AtomicClaim(
            claim_id="FIN-001_temporal_yoy",
            finding_id="FIN-001",
            claim_text="YoY growth: 15%",
            claim_type="temporal",
            claimed_value=15.0,
            claimed_unit="percent",
            temporal_type="yoy",
            claimed_growth_pct=15.0,
        )
        result = engine._verify_temporal_claim(claim)
        assert result.status == "UNVERIFIABLE"

    def test_unverifiable_without_growth_pct(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        claim = AtomicClaim(
            claim_id="FIN-001_temporal_yoy",
            finding_id="FIN-001",
            claim_text="YoY growth mentioned",
            claim_type="temporal",
            claimed_value=None,
            temporal_type="yoy",
            claimed_growth_pct=None,
        )
        result = engine._verify_temporal_claim(claim)
        assert result.status == "UNVERIFIABLE"


# ═══════════════════════════════════════════════════════════════════════════
# TEST: VAL-39 — NEGATIVE CLAIM DETECTION
# ═══════════════════════════════════════════════════════════════════════════


class TestNegativeClaimDetection:

    def test_detects_no_pattern(self, query_results_with_aging, baseline):
        engine = VerificationEngine(query_results_with_aging, baseline)
        finding = {
            "id": "FIN-010",
            "headline": "No invoices overdue beyond 90 days",
            "evidence": "Based on aging analysis",
        }
        claims = engine._detect_negative_claims(finding, "analyst")
        assert len(claims) == 1
        assert claims[0].claim_type == "negative"
        assert claims[0].is_negative_claim is True

    def test_detects_zero_pattern(self, query_results_with_aging, baseline):
        engine = VerificationEngine(query_results_with_aging, baseline)
        finding = {
            "id": "FIN-011",
            "headline": "Zero customers with outstanding debt over 90 days",
            "evidence": "",
        }
        claims = engine._detect_negative_claims(finding, "analyst")
        assert len(claims) == 1
        assert claims[0].is_negative_claim is True

    def test_detects_none_pattern(self, query_results_with_aging, baseline):
        engine = VerificationEngine(query_results_with_aging, baseline)
        finding = {
            "id": "FIN-012",
            "headline": "None of the invoices are past due",
            "evidence": "",
        }
        claims = engine._detect_negative_claims(finding, "analyst")
        assert len(claims) == 1

    def test_detects_spanish_no_hay(self, query_results_with_aging, baseline):
        engine = VerificationEngine(query_results_with_aging, baseline)
        finding = {
            "id": "FIN-013",
            "headline": "No hay facturas vencidas mayores a 90 dias",
            "evidence": "",
        }
        claims = engine._detect_negative_claims(finding, "analyst")
        assert len(claims) == 1

    def test_no_negative_in_positive_finding(self, query_results_with_aging, baseline):
        engine = VerificationEngine(query_results_with_aging, baseline)
        finding = {
            "id": "FIN-014",
            "headline": "Revenue grew 15% this quarter",
            "evidence": "Strong growth in Q4",
        }
        claims = engine._detect_negative_claims(finding, "analyst")
        assert len(claims) == 0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: VAL-39 — NEGATIVE CLAIM VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════


class TestNegativeClaimVerification:

    def test_refutes_false_overdue_claim(self, query_results_with_aging, baseline):
        """Claim says 'no overdue >90d' but aging data shows 5 items in 91-180d."""
        engine = VerificationEngine(query_results_with_aging, baseline)
        claim = AtomicClaim(
            claim_id="FIN-010_negative",
            finding_id="FIN-010",
            claim_text="No invoices overdue beyond 90 days",
            claim_type="negative",
            claimed_value=0.0,
            claimed_unit="count",
            is_negative_claim=True,
        )
        result = engine._verify_negative_claim(claim)
        assert result.status == "FAILED"
        assert result.actual_value > 0

    def test_verifies_true_negative_claim(self, query_results_no_overdue, baseline):
        """Claim says 'no overdue' and aging only shows not_due items."""
        engine = VerificationEngine(query_results_no_overdue, baseline)
        claim = AtomicClaim(
            claim_id="FIN-010_negative",
            finding_id="FIN-010",
            claim_text="No overdue invoices past due",
            claim_type="negative",
            claimed_value=0.0,
            claimed_unit="count",
            is_negative_claim=True,
        )
        result = engine._verify_negative_claim(claim)
        assert result.status == "VERIFIED"
        assert result.actual_value == 0.0

    def test_unverifiable_without_relevant_data(self, baseline):
        """No aging or AR data available — cannot verify."""
        engine = VerificationEngine(
            {"results": {"total_revenue_summary": {"rows": [{"total_revenue": 100}], "row_count": 1}}},
            baseline,
        )
        claim = AtomicClaim(
            claim_id="FIN-010_negative",
            finding_id="FIN-010",
            claim_text="No invoices overdue beyond 90 days",
            claim_type="negative",
            claimed_value=0.0,
            claimed_unit="count",
            is_negative_claim=True,
        )
        result = engine._verify_negative_claim(claim)
        assert result.status == "UNVERIFIABLE"


# ═══════════════════════════════════════════════════════════════════════════
# TEST: INTEGRATION — verify_findings() includes temporal & negative
# ═══════════════════════════════════════════════════════════════════════════


class TestVerifyFindingsIntegration:

    def test_temporal_claim_in_verify_findings(self, query_results_with_yoy, baseline):
        engine = VerificationEngine(query_results_with_yoy, baseline)
        findings = {
            "analyst": {
                "agent": "analyst",
                "findings": [
                    {
                        "id": "FIN-001",
                        "severity": "opportunity",
                        "headline": "Revenue grew 15% year-over-year in December",
                        "evidence": "Based on yoy_comparison data",
                        "value_eur": None,
                        "value_confidence": "measured",
                        "action": "Sustain growth trajectory",
                        "domain": "financial",
                    }
                ],
            },
        }
        report = engine.verify_findings(findings)
        assert isinstance(report, VerificationReport)
        # Should have at least the temporal claim
        temporal_results = [r for r in report.results if "temporal" in r.claim_id]
        assert len(temporal_results) >= 1
        assert temporal_results[0].status == "VERIFIED"

    def test_negative_claim_in_verify_findings(self, query_results_with_aging, baseline):
        engine = VerificationEngine(query_results_with_aging, baseline)
        findings = {
            "analyst": {
                "agent": "analyst",
                "findings": [
                    {
                        "id": "FIN-010",
                        "severity": "info",
                        "headline": "No invoices overdue beyond 90 days",
                        "evidence": "Aging analysis shows clean AR",
                        "value_eur": None,
                        "value_confidence": "measured",
                        "action": "Continue monitoring",
                        "domain": "credit",
                    }
                ],
            },
        }
        report = engine.verify_findings(findings)
        negative_results = [r for r in report.results if "negative" in r.claim_id]
        assert len(negative_results) >= 1
        # This claim is FALSE — there ARE items in 91-180d bucket
        assert negative_results[0].status == "FAILED"
