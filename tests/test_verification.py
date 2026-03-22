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
from valinor.verification import VerificationEngine, VerificationReport


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
