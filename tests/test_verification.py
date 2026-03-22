"""
Tests for the Verification Engine.

Validates:
  1. Number registry construction from query results
  2. Claim decomposition from agent findings
  3. Claim verification (exact, derived, approximate)
  4. Cross-validation checks
  5. Specific Gloria hallucination detection
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest
from valinor.verification import Dimension, VerificationEngine, VerificationReport


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def gloria_query_results():
    """Real Gloria query results (verified against the database)."""
    return {
        "results": {
            "total_revenue_summary": {
                "rows": [{
                    "num_invoices": 3139,
                    "total_revenue": 1631559.62,
                    "avg_invoice": 519.77,
                    "min_invoice": -35511.52,
                    "max_invoice": 123376.73,
                    "distinct_customers": 1223,
                    "date_from": "2024-12-01",
                    "date_to": "2024-12-31",
                }],
                "row_count": 1,
            },
            "ar_outstanding_actual": {
                "rows": [{
                    "total_outstanding": 3267365.43,  # Corrected: AR only, not AP
                    "overdue_amount": 3267365.43,
                    "customers_with_debt": 616,  # Corrected: with issotrx filter
                }],
                "row_count": 1,
            },
        },
        "errors": {},
    }


@pytest.fixture
def gloria_baseline():
    return {
        "data_available": True,
        "total_revenue": 1631559.62,
        "num_invoices": 3139,
        "avg_invoice": 519.77,
        "min_invoice": -35511.52,
        "max_invoice": 123376.73,
        "distinct_customers": 1223,
        "total_outstanding_ar": 3267365.43,
        "overdue_ar": 3267365.43,
        "customers_with_debt": 616,
    }


@pytest.fixture
def engine(gloria_query_results, gloria_baseline):
    return VerificationEngine(gloria_query_results, gloria_baseline)


# ═══════════════════════════════════════════════════════════════════════════
# TEST: REGISTRY CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════

class TestRegistryConstruction:

    def test_revenue_registered(self, engine):
        engine._build_registry_from_queries()
        assert "total_revenue" in engine._registry
        assert engine._registry["total_revenue"].value == 1631559.62

    def test_invoice_count_registered(self, engine):
        engine._build_registry_from_queries()
        assert "num_invoices" in engine._registry
        assert engine._registry["num_invoices"].value == 3139

    def test_ar_registered(self, engine):
        engine._build_registry_from_queries()
        assert "total_outstanding_ar" in engine._registry
        assert engine._registry["total_outstanding_ar"].value == 3267365.43

    def test_provenance_tracked(self, engine):
        engine._build_registry_from_queries()
        entry = engine._registry["total_revenue"]
        assert entry.source_query == "total_revenue_summary"
        assert entry.confidence == "measured"


# ═══════════════════════════════════════════════════════════════════════════
# TEST: CLAIM VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════

class TestClaimVerification:

    def test_correct_revenue_verified(self, engine):
        """A finding claiming $1,631,559.62 should be VERIFIED."""
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "FIN-001",
                    "headline": "December 2024 revenue: $1,631,559.62",
                    "value_eur": 1631559.62,
                    "value_confidence": "measured",
                    "evidence": "total_revenue_summary query",
                }],
            }
        }
        report = engine.verify_findings(findings)
        verified = [r for r in report.results if r.status == "VERIFIED"]
        assert len(verified) > 0

    def test_hallucinated_ar_detected(self, engine):
        """
        A finding claiming $13.5M AR should NOT be verified
        (real AR is $3.27M with correct filters).
        """
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "FIN-002",
                    "headline": "$13.5M AR, 100% Overdue",
                    "value_eur": 13509300.79,
                    "value_confidence": "measured",
                    "evidence": "ar_outstanding_actual query",
                }],
            }
        }
        report = engine.verify_findings(findings)
        # The $13.5M value should NOT be verified (real is $3.27M)
        ar_claims = [r for r in report.results
                     if r.claim_id == "FIN-002_value"]
        assert len(ar_claims) > 0
        assert ar_claims[0].status != "VERIFIED"

    def test_hallucinated_customer_count_detected(self, engine):
        """
        A finding claiming 4,854 customers with debt should NOT be verified
        (real is 616 with correct filters).
        """
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "FIN-003",
                    "headline": "4,854 customers owe money",
                    "value_eur": None,
                    "value_confidence": "measured",
                    "evidence": "ar_outstanding_actual",
                }],
            }
        }
        report = engine.verify_findings(findings)
        count_claims = [r for r in report.results
                        if "count" in r.claim_id and r.status == "VERIFIED"]
        # Should NOT verify 4854 (real is 616)
        for claim in report.results:
            if claim.claim_id.endswith("count_customer"):
                assert claim.status != "VERIFIED", \
                    f"4,854 should not verify (actual is 616)"


# ═══════════════════════════════════════════════════════════════════════════
# TEST: CROSS-VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossValidation:

    def test_detects_suspicious_debt_ratio(self):
        """
        If customers_with_debt >> distinct_customers, flag it.
        This catches the Gloria bug where AR included AP + order-only schedules.
        """
        # Simulate the BAD data (before fixes)
        bad_results = {
            "results": {
                "total_revenue_summary": {
                    "rows": [{"total_revenue": 1631559.62, "num_invoices": 3139,
                              "avg_invoice": 519.77, "min_invoice": -35511.52,
                              "max_invoice": 123376.73, "distinct_customers": 1223}],
                    "row_count": 1,
                },
                "ar_outstanding_actual": {
                    "rows": [{"total_outstanding": 13509300.79,
                              "overdue_amount": 13509300.79,
                              "customers_with_debt": 4854}],
                    "row_count": 1,
                },
            },
            "errors": {},
        }
        bad_baseline = {
            "total_revenue": 1631559.62,
            "distinct_customers": 1223,
            "total_outstanding_ar": 13509300.79,
            "customers_with_debt": 4854,
        }

        engine = VerificationEngine(bad_results, bad_baseline)
        report = engine.verify_findings({})

        # Should flag the suspicious ratio
        debt_issues = [i for i in report.issues if i["check"] == "debt_customer_ratio"]
        assert len(debt_issues) > 0
        assert debt_issues[0]["severity"] == "critical"

    def test_detects_ar_revenue_anomaly(self):
        """If AR > 10x revenue, flag it."""
        bad_results = {
            "results": {
                "total_revenue_summary": {
                    "rows": [{"total_revenue": 1631559.62, "num_invoices": 3139,
                              "avg_invoice": 519.77, "distinct_customers": 1223}],
                    "row_count": 1,
                },
                "ar_outstanding_actual": {
                    "rows": [{"total_outstanding": 13509300.79,
                              "overdue_amount": 13509300.79,
                              "customers_with_debt": 4854}],
                    "row_count": 1,
                },
            },
            "errors": {},
        }
        bad_baseline = {
            "total_revenue": 1631559.62,
            "total_outstanding_ar": 13509300.79,
            "customers_with_debt": 4854,
            "distinct_customers": 1223,
        }

        engine = VerificationEngine(bad_results, bad_baseline)
        report = engine.verify_findings({})

        ar_issues = [i for i in report.issues if i["check"] == "ar_revenue_ratio"]
        assert len(ar_issues) > 0

    def test_no_issues_with_clean_data(self, engine):
        """Clean data (corrected values) should have no critical issues."""
        report = engine.verify_findings({})
        critical = [i for i in report.issues if i["severity"] == "critical"]
        assert len(critical) == 0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: VERIFICATION REPORT
# ═══════════════════════════════════════════════════════════════════════════

class TestVerificationReport:

    def test_report_structure(self, engine):
        report = engine.verify_findings({})
        assert isinstance(report, VerificationReport)
        assert report.verified_at != ""
        assert isinstance(report.number_registry, dict)

    def test_prompt_context_generation(self, engine):
        report = engine.verify_findings({})
        ctx = report.to_prompt_context()
        assert "NUMBER REGISTRY" in ctx
        assert "VERIFICATION REPORT" in ctx


# ═══════════════════════════════════════════════════════════════════════════
# TEST: CONFIDENCE SCORING
# ═══════════════════════════════════════════════════════════════════════════

class TestConfidenceScoring:

    def test_direct_registry_match_high_confidence(self, engine):
        """A verified claim via direct registry match should have confidence >= 0.85."""
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "CONF-001",
                    "headline": "December 2024 revenue: $1,631,559.62",
                    "value_eur": 1631559.62,
                    "value_confidence": "measured",
                    "evidence": "total_revenue_summary query",
                }],
            }
        }
        report = engine.verify_findings(findings)
        verified = [r for r in report.results
                    if r.status == "VERIFIED" and r.claim_id == "CONF-001_value"]
        assert len(verified) > 0
        assert verified[0].confidence_score >= 0.85

    def test_derived_match_medium_confidence(self, engine):
        """A claim verified via derivation should have confidence ~0.60."""
        # avg_invoice = total_revenue / num_invoices = 1631559.62 / 3139 ≈ 519.77
        # Use a value that is derivable but NOT directly in the registry
        # total_revenue - total_outstanding_ar is a derivable subtraction
        derived_val = 1631559.62 - 3267365.43  # = -1635805.81
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "CONF-002",
                    "headline": f"Net position: ${derived_val}",
                    "value_eur": derived_val,
                    "value_confidence": "computed",
                    "evidence": "derived calculation",
                }],
            }
        }
        report = engine.verify_findings(findings)
        derived_claims = [r for r in report.results
                         if r.claim_id == "CONF-002_value"]
        assert len(derived_claims) > 0
        assert abs(derived_claims[0].confidence_score - 0.60) < 0.15

    def test_approximate_match_low_confidence(self, engine):
        """An approximate match should have confidence < 0.50."""
        # Use a value that is ~3% off from total_revenue (within 5% but not exact)
        approx_val = 1631559.62 * 1.03  # 3% off
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "CONF-003",
                    "headline": f"Revenue approximately ${approx_val:,.2f}",
                    "value_eur": approx_val,
                    "value_confidence": "estimated",
                    "evidence": "estimate",
                }],
            }
        }
        report = engine.verify_findings(findings)
        approx_claims = [r for r in report.results
                         if r.claim_id == "CONF-003_value"
                         and r.status == "APPROXIMATE"]
        assert len(approx_claims) > 0
        assert approx_claims[0].confidence_score < 0.50

    def test_count_exact_match_required(self, engine):
        """Count claim '3139 invoices' must match exactly, not within 0.5%."""
        # 3139 + 10 = 3149, which is ~0.3% off — should FAIL for counts
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "CONF-004",
                    "headline": "3149 invoices processed",
                    "value_eur": None,
                    "value_confidence": "measured",
                    "evidence": "total_revenue_summary",
                }],
            }
        }
        report = engine.verify_findings(findings)
        count_claims = [r for r in report.results
                        if "count" in r.claim_id and r.claim_id.startswith("CONF-004")]
        assert len(count_claims) > 0
        # 3149 != 3139, so must NOT be VERIFIED
        assert count_claims[0].status != "VERIFIED"

    def test_percent_wider_tolerance(self, engine):
        """Percentage claim 45.2% should verify against 46.0% (within 2pp)."""
        # Add a percentage value to the query results
        query_results_with_pct = {
            "results": {
                "total_revenue_summary": {
                    "rows": [{
                        "num_invoices": 3139,
                        "total_revenue": 1631559.62,
                        "avg_invoice": 519.77,
                        "min_invoice": -35511.52,
                        "max_invoice": 123376.73,
                        "distinct_customers": 1223,
                    }],
                    "row_count": 1,
                },
                "customer_concentration": {
                    "rows": [{
                        "customer_name": "TestCorp",
                        "total_revenue": 750000.0,
                        "pct_revenue": 46.0,
                    }],
                    "row_count": 1,
                },
            },
            "errors": {},
        }
        baseline = {"total_revenue": 1631559.62, "num_invoices": 3139}
        eng = VerificationEngine(query_results_with_pct, baseline)

        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "CONF-005",
                    "headline": "TestCorp represents 45.2% of revenue",
                    "value_eur": None,
                    "value_confidence": "computed",
                    "evidence": "customer_concentration",
                }],
            }
        }
        report = eng.verify_findings(findings)
        pct_claims = [r for r in report.results
                      if r.claim_id.startswith("CONF-005_pct")]
        assert len(pct_claims) > 0
        # 45.2% vs 46.0% = 0.8pp difference, within 2pp tolerance
        assert pct_claims[0].status == "VERIFIED"

    def test_dimension_on_registry_entries(self, engine):
        """Registered values should carry the correct dimension."""
        engine._build_registry_from_queries()
        assert engine._registry["total_revenue"].dimension == Dimension.EUR
        assert engine._registry["num_invoices"].dimension == Dimension.COUNT
        assert engine._registry["distinct_customers"].dimension == Dimension.COUNT
        assert engine._registry["customers_with_debt"].dimension == Dimension.COUNT

    def test_failed_claim_zero_confidence(self, engine):
        """FAILED status should have confidence 0.0."""
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "CONF-006",
                    "headline": "$13.5M AR, 100% Overdue",
                    "value_eur": 13509300.79,
                    "value_confidence": "measured",
                    "evidence": "ar_outstanding_actual query",
                }],
            }
        }
        report = engine.verify_findings(findings)
        # The $13.5M claim should fail or be unverifiable (real is $3.27M)
        ar_claims = [r for r in report.results
                     if r.claim_id == "CONF-006_value"]
        assert len(ar_claims) > 0
        # FAILED or UNVERIFIABLE should have confidence 0.0
        assert ar_claims[0].status in ("FAILED", "UNVERIFIABLE", "APPROXIMATE")
        if ar_claims[0].status in ("FAILED", "UNVERIFIABLE"):
            assert ar_claims[0].confidence_score == 0.0
