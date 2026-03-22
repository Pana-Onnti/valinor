"""
Tests for the Calibration subsystem (Phase 6 — self-calibration loop).

Validates:
  1. CalibrationEvaluator — deterministic scoring 0-100
  2. CalibrationMemory — persistence, regression detection, trends
  3. CalibrationAdjuster — generic suggestions, overfitting detection
"""
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest
from valinor.calibration.evaluator import CalibrationEvaluator, CalibrationScore, CheckResult
from valinor.calibration.memory import CalibrationMemory
from valinor.calibration.adjuster import CalibrationAdjuster, AdjustmentReport


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def perfect_query_results():
    """Query results with all expected queries present and no errors."""
    return {
        "results": {
            "total_revenue_summary": {
                "rows": [{
                    "num_invoices": 1000,
                    "total_revenue": 500000.00,
                    "avg_invoice": 500.00,
                    "distinct_customers": 200,
                }],
                "row_count": 1,
            },
            "ar_outstanding_actual": {
                "rows": [{"total_outstanding": 150000.00, "customers_with_debt": 80}],
                "row_count": 1,
            },
            "aging_buckets": {
                "rows": [
                    {"bucket": "0-30", "amount": 50000.00},
                    {"bucket": "31-60", "amount": 40000.00},
                    {"bucket": "61-90", "amount": 35000.00},
                    {"bucket": "90+", "amount": 25000.00},
                ],
                "row_count": 4,
            },
            "top_customers": {
                "rows": [
                    {"customer": "A", "revenue": 50000.00},
                    {"customer": "B", "revenue": 30000.00},
                ],
                "row_count": 2,
            },
            "monthly_trend": {
                "rows": [{"month": "2024-12", "revenue": 500000.00}],
                "row_count": 1,
            },
        },
        "errors": {},
    }


@pytest.fixture
def perfect_baseline():
    """Baseline with all critical fields populated and consistent values."""
    return {
        "total_revenue": 500000.00,
        "num_invoices": 1000,
        "distinct_customers": 200,
        "total_outstanding": 150000.00,
        "avg_invoice": 500.00,
        "customers_with_debt": 80,
    }


@pytest.fixture
def verification_report_good():
    """Verification report with high coverage."""
    return {"total_claims": 20, "verified_claims": 18}


@pytest.fixture
def tmp_storage(tmp_path):
    """Temporary directory for calibration memory storage."""
    return str(tmp_path / "calibration")


@pytest.fixture
def memory(tmp_storage):
    return CalibrationMemory(storage_dir=tmp_storage)


def _make_score(overall: float, **kwargs) -> CalibrationScore:
    """Helper to create a CalibrationScore with defaults."""
    return CalibrationScore(
        overall_score=overall,
        checks=kwargs.get("checks", []),
        query_coverage_pct=kwargs.get("query_coverage_pct", 1.0),
        baseline_completeness_pct=kwargs.get("baseline_completeness_pct", 1.0),
        verification_rate=kwargs.get("verification_rate", 0.9),
        error_rate=kwargs.get("error_rate", 0.0),
        timestamp=kwargs.get("timestamp", "2026-03-21T22:00:00Z"),
        recommendations=kwargs.get("recommendations", []),
    )


# ═══════════════════════════════════════════════════════════════════════════
# EVALUATOR TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestEvaluator:
    def test_perfect_score(self, perfect_query_results, perfect_baseline, verification_report_good):
        """All queries pass, baseline complete → score near 100."""
        evaluator = CalibrationEvaluator(
            query_results=perfect_query_results,
            baseline=perfect_baseline,
            verification_report=verification_report_good,
        )
        score = evaluator.evaluate()

        assert score.overall_score >= 90.0
        assert score.query_coverage_pct >= 0.8
        assert score.baseline_completeness_pct >= 0.8
        assert score.error_rate == 0.0
        assert all(c.passed for c in score.checks)

    def test_low_score_with_errors(self, perfect_baseline, verification_report_good):
        """50% query errors → score drops significantly."""
        query_results = {
            "results": {
                "total_revenue_summary": {"rows": [{}], "row_count": 1},
                "ar_outstanding_actual": {"rows": [{}], "row_count": 1},
            },
            "errors": {
                "aging_buckets": "SQL syntax error",
                "top_customers": "timeout",
            },
        }
        evaluator = CalibrationEvaluator(
            query_results=query_results,
            baseline=perfect_baseline,
            verification_report=verification_report_good,
        )
        score = evaluator.evaluate()

        assert score.overall_score < 80.0
        assert score.error_rate > 0.0
        error_checks = [c for c in score.checks if c.name == "error_rate"]
        assert len(error_checks) == 1
        assert not error_checks[0].passed

    def test_cross_consistency_catches_mismatch(self, perfect_query_results, verification_report_good):
        """avg != total/count → flagged as inconsistent."""
        bad_baseline = {
            "total_revenue": 500000.00,
            "num_invoices": 1000,
            "distinct_customers": 200,
            "total_outstanding": 150000.00,
            "avg_invoice": 999.99,  # Wrong! Should be 500.00
            "customers_with_debt": 80,
        }
        evaluator = CalibrationEvaluator(
            query_results=perfect_query_results,
            baseline=bad_baseline,
            verification_report=verification_report_good,
        )
        score = evaluator.evaluate()

        consistency_checks = [c for c in score.checks if c.name == "avg_invoice_consistency"]
        assert len(consistency_checks) == 1
        assert not consistency_checks[0].passed
        assert consistency_checks[0].severity == "critical"

    def test_scoring_is_deterministic(self, perfect_query_results, perfect_baseline, verification_report_good):
        """Same input always gives same score."""
        evaluator = CalibrationEvaluator(
            query_results=perfect_query_results,
            baseline=perfect_baseline,
            verification_report=verification_report_good,
        )
        score1 = evaluator.evaluate()
        score2 = evaluator.evaluate()

        assert score1.overall_score == score2.overall_score
        assert len(score1.checks) == len(score2.checks)
        for c1, c2 in zip(score1.checks, score2.checks):
            assert c1.name == c2.name
            assert c1.passed == c2.passed
            assert c1.score_impact == c2.score_impact


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestMemory:
    def test_record_and_retrieve(self, memory):
        """Store a score, get it back."""
        score = _make_score(92.5)
        memory.record("gloria", "2024-12", score)

        history = memory.get_history("gloria")
        assert len(history) == 1
        assert history[0]["overall_score"] == 92.5
        assert history[0]["period"] == "2024-12"

    def test_detect_regression(self, memory):
        """Score drops 10 points → regression detected."""
        score1 = _make_score(90.0)
        memory.record("gloria", "2024-11", score1)

        score2 = _make_score(78.0)
        regression = memory.detect_regression("gloria", score2)

        assert regression is not None
        assert regression["previous_score"] == 90.0
        assert regression["current_score"] == 78.0
        assert regression["delta"] == -12.0

    def test_no_regression_on_improvement(self, memory):
        """Score improves → no regression."""
        score1 = _make_score(85.0)
        memory.record("gloria", "2024-11", score1)

        score2 = _make_score(92.0)
        regression = memory.detect_regression("gloria", score2)

        assert regression is None

    def test_trend_detection(self, memory):
        """5 improving scores → 'improving' trend."""
        for i, score_val in enumerate([70.0, 75.0, 80.0, 85.0, 90.0]):
            score = _make_score(score_val)
            memory.record("gloria", f"2024-{i + 1:02d}", score)

        trend = memory.get_trend("gloria")
        assert trend["trend"] == "improving"

    def test_cross_client_summary(self, memory):
        """3 clients → summary shows all."""
        for client, score_val in [("gloria", 92.0), ("acme", 85.0), ("foxtrot", 78.0)]:
            score = _make_score(score_val)
            memory.record(client, "2024-12", score)

        summary = memory.get_cross_client_summary()
        assert len(summary) == 3
        assert summary["gloria"]["overall_score"] == 92.0
        assert summary["acme"]["overall_score"] == 85.0
        assert summary["foxtrot"]["overall_score"] == 78.0


# ═══════════════════════════════════════════════════════════════════════════
# ADJUSTER TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestAdjuster:
    def test_suggests_query_fixes_on_errors(self, memory):
        """High error rate → suggests query fixes."""
        adjuster = CalibrationAdjuster(memory)
        score = _make_score(60.0, error_rate=0.5, query_coverage_pct=0.6)

        report = adjuster.analyze("test_client", score)
        query_suggestions = [s for s in report.suggestions if s.category == "query"]
        assert len(query_suggestions) >= 1
        assert any("error rate" in s.description.lower() for s in query_suggestions)

    def test_suggests_filter_improvements(self, memory):
        """Failing consistency checks → suggests filter review."""
        adjuster = CalibrationAdjuster(memory)
        score = _make_score(
            70.0,
            verification_rate=0.4,
            checks=[
                CheckResult(
                    name="debt_customers_bounded",
                    passed=False,
                    score_impact=10.0,
                    detail="customers_with_debt > distinct_customers",
                    severity="warning",
                ),
            ],
        )

        report = adjuster.analyze("test_client", score)
        filter_suggestions = [s for s in report.suggestions if s.category == "filter"]
        assert len(filter_suggestions) >= 1

    def test_flags_overfitting(self, memory):
        """Suggestion only helps 1 client while others are fine → flagged."""
        # Record good scores for other clients
        for client in ["acme", "foxtrot"]:
            memory.record(client, "2024-12", _make_score(95.0))

        # Record a poor score for our target client
        memory.record("gloria", "2024-12", _make_score(60.0))

        adjuster = CalibrationAdjuster(memory)
        score = _make_score(
            60.0,
            checks=[
                CheckResult(
                    name="debt_customers_bounded",
                    passed=False,
                    score_impact=10.0,
                    detail="customers_with_debt > distinct_customers",
                    severity="warning",
                ),
            ],
            verification_rate=0.4,
        )

        report = adjuster.analyze("gloria", score)

        # Should have overfitting warnings since other clients are fine
        assert len(report.overfitting_warnings) > 0
        assert any("overfitting" in w.lower() for w in report.overfitting_warnings)
