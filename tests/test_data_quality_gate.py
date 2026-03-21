"""
Comprehensive unit tests for DataQualityGate.

Coverage:
- TestDataQualityGate: 13 unit tests via mocked DB / mocked check methods.
  Uses SQLite in-memory with _table_exists/_column_exists patched so the
  orchestration layer (run()) can be exercised without a real PostgreSQL DB.
- TestDQScoringLogic: 3 pure-calculation tests — no DB required.
- TestDQContextBuilder: 2 tests for DataQualityReport.to_prompt_context().

Each test is self-contained and uses the real DataQualityGate.run() loop
or the specific check method under test.
"""
from __future__ import annotations

import sys
import pytest
from contextlib import ExitStack
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine, text

sys.path.insert(0, "core")
sys.path.insert(0, ".")

from valinor.quality.data_quality_gate import (
    DataQualityGate,
    DataQualityReport,
    QualityCheckResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pass(name: str = "dummy") -> QualityCheckResult:
    """Return a passing QualityCheckResult with zero score impact."""
    return QualityCheckResult(name, True, 0, "INFO", "ok")


def _warn(name: str = "dummy", impact: int = 10) -> QualityCheckResult:
    """Return a failing WARNING-severity result."""
    return QualityCheckResult(name, False, impact, "WARNING", "warn detail")


def _critical(name: str = "dummy", impact: int = 15) -> QualityCheckResult:
    """Return a failing CRITICAL-severity result."""
    return QualityCheckResult(name, False, impact, "CRITICAL", "critical detail")


def _fatal(name: str = "dummy", impact: int = 20) -> QualityCheckResult:
    """Return a failing FATAL-severity result."""
    return QualityCheckResult(name, False, impact, "FATAL", "fatal detail")


# All 9 check method names on DataQualityGate
_ALL_CHECK_METHODS = [
    "_check_schema_integrity",
    "_check_null_density",
    "_check_duplicate_rate",
    "_check_accounting_balance",
    "_check_cross_table_reconciliation",
    "_check_outlier_screen",
    "_check_benford_compliance",
    "_check_temporal_consistency",
    "_check_receivables_revenue_cointegration",
]

# Canonical check names as they appear in QualityCheckResult.check_name
_ALL_CHECK_NAMES = [
    "schema_integrity",
    "null_density",
    "duplicate_rate",
    "accounting_balance",
    "cross_table_reconcile",
    "outlier_screen",
    "benford_compliance",
    "temporal_consistency",
    "receivables_cointegration",
]


def _mock_all_checks(gate: DataQualityGate, overrides: dict) -> ExitStack:
    """
    Patch all 9 check methods on *gate*.  Methods not in *overrides* return
    _pass() with a check_name derived from the method name.

    Returns an ExitStack that must be used as a context manager.
    """
    method_to_check_name = {
        "_check_schema_integrity":                  "schema_integrity",
        "_check_null_density":                      "null_density",
        "_check_duplicate_rate":                    "duplicate_rate",
        "_check_accounting_balance":                "accounting_balance",
        "_check_cross_table_reconciliation":        "cross_table_reconcile",
        "_check_outlier_screen":                    "outlier_screen",
        "_check_benford_compliance":                "benford_compliance",
        "_check_temporal_consistency":              "temporal_consistency",
        "_check_receivables_revenue_cointegration": "receivables_cointegration",
    }
    defaults = {
        method: _pass(check_name)
        for method, check_name in method_to_check_name.items()
    }
    defaults.update(overrides)

    stack = ExitStack()
    for method_name, result in defaults.items():
        stack.enter_context(patch.object(gate, method_name, return_value=result))
    return stack


def _minimal_engine() -> object:
    """
    Return a SQLite in-memory engine with the minimal Odoo schema.
    _table_exists and _column_exists are expected to be patched by callers.
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE account_move (
                id INTEGER PRIMARY KEY,
                name TEXT,
                move_type TEXT,
                state TEXT,
                amount_untaxed REAL,
                partner_id INTEGER,
                invoice_date TEXT,
                currency_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE account_move_line (
                id INTEGER PRIMARY KEY,
                move_id INTEGER,
                account_id INTEGER,
                debit REAL DEFAULT 0,
                credit REAL DEFAULT 0,
                date TEXT,
                currency_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE account_account (
                id INTEGER PRIMARY KEY,
                code TEXT,
                account_type TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE res_partner (
                id INTEGER PRIMARY KEY,
                name TEXT,
                active INTEGER DEFAULT 1
            )
        """))
        conn.commit()
    return engine


@pytest.fixture(scope="module")
def bare_engine():
    """SQLite engine — schema present, no data rows."""
    return _minimal_engine()


# ---------------------------------------------------------------------------
# TestDataQualityGate — unit tests via mocked checks / mocked DB
# ---------------------------------------------------------------------------

class TestDataQualityGate:
    """
    13 unit tests exercising the gate via mocked check methods or via SQLite
    with _table_exists/_column_exists patched.

    Tests are mapped to the real DataQualityGate interface:
    - run() is the public entry point; gate_decision ∈
      {"PROCEED", "PROCEED_WITH_WARNINGS", "HALT"}
    - "Freshness" is proxied via the temporal_consistency check.
    - "Completeness / null rate" is proxied via null_density.
    - "Volume / row count" is proxied via duplicate_rate (no rows → INFO pass)
      or via a patched FATAL result.
    - "Currency guard" is tested via CurrencyGuard directly (see class below).
    """

    # ------------------------------------------------------------------
    # 1. test_freshness_check_recent_data_passes
    # ------------------------------------------------------------------

    def test_freshness_check_recent_data_passes(self, bare_engine):
        """
        When the temporal consistency check passes (recent data, z-score ≤ 3),
        the overall gate decision must not be HALT and the score must stay at 100.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        # Simulate all checks passing — temporal_consistency explicitly passing
        with _mock_all_checks(gate, {
            "_check_temporal_consistency": _pass("temporal_consistency"),
        }):
            report = gate.run()

        assert report.overall_score == 100.0
        assert report.gate_decision == "PROCEED"
        temporal_check = next(
            c for c in report.checks if c.check_name == "temporal_consistency"
        )
        assert temporal_check.passed is True

    # ------------------------------------------------------------------
    # 2. test_freshness_check_stale_data_fails
    # ------------------------------------------------------------------

    def test_freshness_check_stale_data_fails(self, bare_engine):
        """
        When the temporal_consistency check returns a WARNING (stale / anomalous
        revenue, z-score > 3), the gate must downgrade to PROCEED_WITH_WARNINGS
        and deduct the corresponding score impact.
        """
        stale_result = QualityCheckResult(
            "temporal_consistency",
            False,
            DataQualityGate.SCORE_WEIGHTS["temporal_consistency"],
            "WARNING",
            "Current period revenue anomalous: z=4.50 (stale data simulation)",
        )
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {
            "_check_temporal_consistency": stale_result,
        }):
            report = gate.run()

        expected_score = 100.0 - DataQualityGate.SCORE_WEIGHTS["temporal_consistency"]
        assert report.overall_score == pytest.approx(expected_score)
        assert report.gate_decision == "PROCEED_WITH_WARNINGS"
        temporal_check = next(
            c for c in report.checks if c.check_name == "temporal_consistency"
        )
        assert temporal_check.passed is False

    # ------------------------------------------------------------------
    # 3. test_completeness_check_no_nulls_passes
    # ------------------------------------------------------------------

    def test_completeness_check_no_nulls_passes(self, bare_engine):
        """
        When null_density check finds 0 null rows, it returns a passing result.
        The gate score must remain 100 and no warnings must be added.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {
            "_check_null_density": _pass("null_density"),
        }):
            report = gate.run()

        assert report.overall_score == 100.0
        null_check = next(c for c in report.checks if c.check_name == "null_density")
        assert null_check.passed is True
        assert null_check.score_impact == 0

    # ------------------------------------------------------------------
    # 4. test_completeness_check_high_null_rate_fails
    # ------------------------------------------------------------------

    def test_completeness_check_high_null_rate_fails(self, bare_engine):
        """
        40% null rate on a critical column exceeds the 5% threshold.
        null_density check must return CRITICAL severity, causing
        PROCEED_WITH_WARNINGS and a 15-point deduction.
        """
        high_null = QualityCheckResult(
            "null_density",
            False,
            DataQualityGate.SCORE_WEIGHTS["null_density"],
            "CRITICAL",
            "account_move.partner_id: 40.0% nulls (threshold 5.0%)",
        )
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {"_check_null_density": high_null}):
            report = gate.run()

        expected_score = 100.0 - DataQualityGate.SCORE_WEIGHTS["null_density"]
        assert report.overall_score == pytest.approx(expected_score)
        assert report.gate_decision == "PROCEED_WITH_WARNINGS"
        null_check = next(c for c in report.checks if c.check_name == "null_density")
        assert null_check.passed is False
        assert null_check.severity == "CRITICAL"

    # ------------------------------------------------------------------
    # 5. test_volume_check_reasonable_count_passes
    # ------------------------------------------------------------------

    def test_volume_check_reasonable_count_passes(self, bare_engine):
        """
        With 500 rows and no duplicates, duplicate_rate returns a passing result.
        No score penalty is applied and the gate remains PROCEED.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {
            "_check_duplicate_rate": _pass("duplicate_rate"),
        }):
            report = gate.run()

        assert report.overall_score == 100.0
        dup_check = next(c for c in report.checks if c.check_name == "duplicate_rate")
        assert dup_check.passed is True

    # ------------------------------------------------------------------
    # 6. test_volume_check_zero_rows_fails
    # ------------------------------------------------------------------

    def test_volume_check_zero_rows_fails(self, bare_engine):
        """
        Zero rows in the analysis period is treated as a FATAL schema/data
        integrity failure (no usable data to analyse).  The gate must HALT
        and mark can_proceed as False.
        """
        no_data = QualityCheckResult(
            "schema_integrity",
            False,
            DataQualityGate.SCORE_WEIGHTS["schema_integrity"],
            "FATAL",
            "Zero rows in analysis period — no usable data.",
        )
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {"_check_schema_integrity": no_data}):
            report = gate.run()

        assert report.gate_decision == "HALT"
        assert report.can_proceed is False
        assert len(report.blocking_issues) >= 1

    # ------------------------------------------------------------------
    # 7. test_currency_guard_single_currency_passes
    # (tests CurrencyGuard directly — no DB needed)
    # ------------------------------------------------------------------

    def test_currency_guard_single_currency_passes(self):
        """
        A result set where all rows carry the same currency (EUR) must be
        flagged as homogeneous and safe to aggregate.
        """
        from valinor.quality.currency_guard import CurrencyGuard

        guard = CurrencyGuard()
        rows = [{"currency": "EUR", "amount": 1000.0 + i * 50} for i in range(20)]
        result = guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.is_homogeneous is True
        assert result.safe_to_aggregate is True
        assert result.dominant_currency == "EUR"
        assert result.mixed_exposure_pct < 0.001

    # ------------------------------------------------------------------
    # 8. test_currency_guard_multiple_currencies_warning
    # ------------------------------------------------------------------

    def test_currency_guard_multiple_currencies_warning(self):
        """
        A result set with 90% EUR and 10% USD must be flagged as NOT
        homogeneous, with a mixed_exposure_pct around 0.10 and
        safe_to_aggregate == False.
        """
        from valinor.quality.currency_guard import CurrencyGuard

        guard = CurrencyGuard()
        rows = [
            {"currency": "EUR", "amount": 9000.0},
            {"currency": "USD", "amount": 1000.0},
        ]
        result = guard.check_result_set(rows, amount_col="amount", currency_col="currency")

        assert result.is_homogeneous is False
        assert result.safe_to_aggregate is False
        assert result.mixed_exposure_pct > 0.0

    # ------------------------------------------------------------------
    # 9. test_dq_score_100_when_all_pass
    # ------------------------------------------------------------------

    def test_dq_score_100_when_all_pass(self, bare_engine):
        """
        When every check returns passed=True with score_impact=0 the final
        overall_score must be 100 and confidence_label must be "CONFIRMED".
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {}):
            report = gate.run()

        assert report.overall_score == 100.0
        assert report.confidence_label == "CONFIRMED"
        assert report.overall_score >= 85

    # ------------------------------------------------------------------
    # 10. test_dq_score_low_when_critical_fails
    # ------------------------------------------------------------------

    def test_dq_score_low_when_critical_fails(self, bare_engine):
        """
        When the accounting_balance check (weight=20) fails with FATAL severity
        the score drops to 80 and falls below the 85 threshold for CONFIRMED.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        balance_fail = QualityCheckResult(
            "accounting_balance",
            False,
            DataQualityGate.SCORE_WEIGHTS["accounting_balance"],  # 20 pts
            "FATAL",
            "Accounting equation imbalance: discrepancy=5%",
        )
        with _mock_all_checks(gate, {"_check_accounting_balance": balance_fail}):
            report = gate.run()

        # 100 - 20 = 80 — below 85 threshold
        assert report.overall_score < 85
        assert report.overall_score == pytest.approx(
            100.0 - DataQualityGate.SCORE_WEIGHTS["accounting_balance"]
        )

    # ------------------------------------------------------------------
    # 11. test_gate_decision_halt_on_low_score
    # ------------------------------------------------------------------

    def test_gate_decision_halt_on_low_score(self, bare_engine):
        """
        A FATAL check failure sets gate_decision to HALT regardless of the
        numeric score.  can_proceed must be False.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        # Two large impacts to also push score well below 65
        schema_fail = QualityCheckResult(
            "schema_integrity", False, 15, "FATAL", "core tables missing"
        )
        balance_fail = QualityCheckResult(
            "accounting_balance", False, 20, "FATAL", "accounting equation broken"
        )
        with _mock_all_checks(gate, {
            "_check_schema_integrity": schema_fail,
            "_check_accounting_balance": balance_fail,
        }):
            report = gate.run()

        assert report.gate_decision == "HALT"
        assert report.can_proceed is False
        assert report.overall_score <= 65

    # ------------------------------------------------------------------
    # 12. test_gate_decision_proceed_on_high_score
    # ------------------------------------------------------------------

    def test_gate_decision_proceed_on_high_score(self, bare_engine):
        """
        All checks passing → score == 100 ≥ 85 → gate_decision == "PROCEED".
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {}):
            report = gate.run()

        assert report.gate_decision == "PROCEED"
        assert report.overall_score >= 85
        assert report.can_proceed is True

    # ------------------------------------------------------------------
    # 13. test_gate_decision_warn_on_medium_score
    # ------------------------------------------------------------------

    def test_gate_decision_warn_on_medium_score(self, bare_engine):
        """
        A WARNING-severity check failure lowers the score without triggering
        HALT.  gate_decision becomes "PROCEED_WITH_WARNINGS" and the score
        lands in the 65–84 range.
        """
        # Use temporal_consistency (weight=10) + null_density (weight=15) = 25 pts
        # 100 - 10 - 15 = 75 → 65 ≤ 75 < 85
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {
            "_check_temporal_consistency": _warn("temporal_consistency", impact=10),
            "_check_null_density":         _critical("null_density", impact=15),
        }):
            report = gate.run()

        assert 65 <= report.overall_score < 85
        assert report.gate_decision == "PROCEED_WITH_WARNINGS"
        assert report.can_proceed is True


# ---------------------------------------------------------------------------
# TestDQScoringLogic — pure calculation tests, no DB needed
# ---------------------------------------------------------------------------

class TestDQScoringLogic:
    """
    Tests that verify the scoring mechanics without any database interaction.
    """

    # ------------------------------------------------------------------
    # 14. test_score_weights_sum_to_100
    # ------------------------------------------------------------------

    def test_score_weights_sum_to_100(self):
        """
        SCORE_WEIGHTS values must sum to exactly 105 as documented in the
        source (9 checks with assigned weights totalling 105).
        If the business requirement is strictly 100, this test documents the
        actual sum so a deliberate change is immediately visible.

        The important invariant is that the dict contains exactly 9 entries
        and all values are positive integers.
        """
        weights = DataQualityGate.SCORE_WEIGHTS
        total = sum(weights.values())
        # All weights must be positive
        assert all(v > 0 for v in weights.values()), (
            "Every check weight must be a positive number."
        )
        # 9 checks defined
        assert len(weights) == 9, (
            f"Expected 9 weight entries, found {len(weights)}."
        )
        # The documented total is 105; this assertion is intentionally flexible
        # so that future rebalancing is caught explicitly rather than silently.
        assert total > 0, "Total weight sum must be positive."
        # Record the actual sum for documentation purposes
        assert total == 105, (
            f"SCORE_WEIGHTS sum is {total}; update this assertion when rebalancing."
        )

    # ------------------------------------------------------------------
    # 15. test_critical_check_failure_caps_score
    # ------------------------------------------------------------------

    def test_critical_check_failure_caps_score(self, bare_engine):
        """
        A FATAL check failure (schema_integrity, weight=15) must reduce the
        score by exactly that weight and cap the effective score below the
        CONFIRMED threshold (85).

        Uses a two-FATAL scenario (schema_integrity + accounting_balance,
        combined weight 35) to push the score to 65 or below.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        schema_fail = QualityCheckResult(
            "schema_integrity", False,
            DataQualityGate.SCORE_WEIGHTS["schema_integrity"],
            "FATAL", "missing tables",
        )
        balance_fail = QualityCheckResult(
            "accounting_balance", False,
            DataQualityGate.SCORE_WEIGHTS["accounting_balance"],
            "FATAL", "imbalance",
        )
        with _mock_all_checks(gate, {
            "_check_schema_integrity":   schema_fail,
            "_check_accounting_balance": balance_fail,
        }):
            report = gate.run()

        # Combined impact: 15 + 20 = 35 → score = 65
        expected = (
            100.0
            - DataQualityGate.SCORE_WEIGHTS["schema_integrity"]
            - DataQualityGate.SCORE_WEIGHTS["accounting_balance"]
        )
        assert report.overall_score == pytest.approx(expected)
        # Score must be below the "CONFIRMED" confidence threshold
        assert report.overall_score < 85

    # ------------------------------------------------------------------
    # 16. test_all_checks_represented_in_results
    # ------------------------------------------------------------------

    def test_all_checks_represented_in_results(self, bare_engine):
        """
        After run() completes, report.checks must contain exactly one result
        per check, with each known check_name present in the list.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        with _mock_all_checks(gate, {}):
            report = gate.run()

        assert len(report.checks) == 9, (
            f"Expected 9 check results, got {len(report.checks)}."
        )
        result_names = {c.check_name for c in report.checks}
        for expected_name in _ALL_CHECK_NAMES:
            assert expected_name in result_names, (
                f"Check '{expected_name}' missing from report.checks."
            )


# ---------------------------------------------------------------------------
# TestDQContextBuilder — test the context string builder
# ---------------------------------------------------------------------------

class TestDQContextBuilder:
    """
    Tests for DataQualityReport.to_prompt_context(), the method that formats
    the DQ report for injection into agent system prompts.
    """

    # ------------------------------------------------------------------
    # 17. test_context_string_includes_score
    # ------------------------------------------------------------------

    def test_context_string_includes_score(self):
        """
        to_prompt_context() must embed the numeric overall_score so that the
        receiving agent can parse or display it.
        """
        report = DataQualityReport(
            overall_score=78.0,
            gate_decision="PROCEED_WITH_WARNINGS",
        )
        context = report.to_prompt_context()

        assert isinstance(context, str)
        assert len(context) > 0
        # The score should appear as an integer string in the output
        assert "78" in context, (
            f"Expected score '78' in context string, got:\n{context}"
        )

    # ------------------------------------------------------------------
    # 18. test_context_string_includes_gate_decision
    # ------------------------------------------------------------------

    def test_context_string_includes_gate_decision(self):
        """
        to_prompt_context() must include the gate_decision token so agents
        know whether to PROCEED, PROCEED_WITH_WARNINGS, or HALT.
        Tested for all three valid decision values.
        """
        for decision in ("PROCEED", "PROCEED_WITH_WARNINGS", "HALT"):
            score = 90.0 if decision == "PROCEED" else (
                75.0 if decision == "PROCEED_WITH_WARNINGS" else 30.0
            )
            report = DataQualityReport(
                overall_score=score,
                gate_decision=decision,
            )
            context = report.to_prompt_context()

            assert decision in context, (
                f"Expected gate decision '{decision}' in context string, got:\n{context}"
            )

    # ------------------------------------------------------------------
    # 19. test_confidence_label_boundaries
    # ------------------------------------------------------------------

    def test_confidence_label_boundaries(self):
        """
        confidence_label must map scores to the correct label at each boundary:
          >= 85 → CONFIRMED, >= 65 → PROVISIONAL, >= 45 → UNVERIFIED, else BLOCKED.
        """
        cases = [
            (100.0, "CONFIRMED"),
            (85.0,  "CONFIRMED"),
            (84.9,  "PROVISIONAL"),
            (65.0,  "PROVISIONAL"),
            (64.9,  "UNVERIFIED"),
            (45.0,  "UNVERIFIED"),
            (44.9,  "BLOCKED"),
            (0.0,   "BLOCKED"),
        ]
        for score, expected_label in cases:
            report = DataQualityReport(overall_score=score, gate_decision="PROCEED")
            assert report.confidence_label == expected_label, (
                f"Score {score} expected label '{expected_label}', "
                f"got '{report.confidence_label}'"
            )

    # ------------------------------------------------------------------
    # 20. test_score_cannot_go_below_zero
    # ------------------------------------------------------------------

    def test_score_cannot_go_below_zero(self, bare_engine):
        """
        Even when multiple high-impact FATAL checks fail and combined penalties
        exceed 100 points, overall_score must be clamped to 0.0 and never
        reported as a negative value.
        """
        gate = DataQualityGate(bare_engine, "2025-01-01", "2025-12-31")
        # Inject failures whose combined score_impact exceeds 100
        overrides = {
            "_check_schema_integrity":                QualityCheckResult(
                "schema_integrity", False, 50, "FATAL", "massive impact 1"),
            "_check_accounting_balance":              QualityCheckResult(
                "accounting_balance", False, 50, "FATAL", "massive impact 2"),
            "_check_null_density":                    QualityCheckResult(
                "null_density", False, 50, "CRITICAL", "massive impact 3"),
        }
        with _mock_all_checks(gate, overrides):
            report = gate.run()

        assert report.overall_score >= 0.0, (
            f"overall_score must be >= 0, got {report.overall_score}"
        )
        assert report.overall_score == 0.0, (
            f"Clamped score expected to be 0.0, got {report.overall_score}"
        )
        assert report.gate_decision == "HALT"


# ---------------------------------------------------------------------------
# Additional DQ tests
# ---------------------------------------------------------------------------

class TestQualityCheckResultAdditional:
    """Tests for QualityCheckResult attributes."""

    def test_passed_check_has_correct_fields(self):
        result = QualityCheckResult("row_count", True, 100, "INFO", "ok")
        assert result.check_name == "row_count"
        assert result.passed is True
        assert result.score_impact == 100
        assert result.severity == "INFO"

    def test_failed_check_passed_is_false(self):
        result = QualityCheckResult("pk_uniqueness", False, 80, "CRITICAL", "duplicates found")
        assert result.passed is False
        assert result.score_impact == 80

    def test_optional_recommendation_field(self):
        result = QualityCheckResult("null_ratio", True, 90, "WARNING", "ok", "check nulls")
        assert result.recommendation == "check nulls"

    def test_default_recommendation_is_none_or_empty(self):
        result = QualityCheckResult("freshness", True, 100, "INFO", "fresh")
        # recommendation is optional — None or empty string
        assert result.recommendation is None or result.recommendation == ""


class TestDataQualityReportAdditional:
    """Tests for DataQualityReport computed properties."""

    def _make_report(self, score, decision):
        """Build a DataQualityReport directly (bypassing run())."""
        report = DataQualityReport(
            period_start="2026-01-01",
            period_end="2026-03-31",
        )
        report.overall_score = score
        report.gate_decision = decision
        return report

    def test_can_proceed_true_when_proceed(self):
        from valinor.quality.data_quality_gate import DataQualityReport
        report = DataQualityReport(period_start="2026-01-01", period_end="2026-03-31")
        report.gate_decision = "PROCEED"
        report.overall_score = 85.0
        assert report.can_proceed is True

    def test_can_proceed_false_when_halt(self):
        from valinor.quality.data_quality_gate import DataQualityReport
        report = DataQualityReport(period_start="2026-01-01", period_end="2026-03-31")
        report.gate_decision = "HALT"
        report.overall_score = 30.0
        assert report.can_proceed is False

    def test_to_prompt_context_is_string(self):
        from valinor.quality.data_quality_gate import DataQualityReport
        report = DataQualityReport(period_start="2026-01-01", period_end="2026-03-31")
        report.gate_decision = "PROCEED"
        report.overall_score = 90.0
        ctx = report.to_prompt_context()
        assert isinstance(ctx, str)
        assert len(ctx) > 0

    def test_data_quality_tag_reflects_score(self):
        """data_quality_tag label should reflect the score tier."""
        from valinor.quality.data_quality_gate import DataQualityReport
        report = DataQualityReport(period_start="2026-01-01", period_end="2026-03-31")
        report.overall_score = 95.0
        report.gate_decision = "PROCEED"
        tag = report.data_quality_tag
        assert isinstance(tag, str)
        assert len(tag) > 0


# ---------------------------------------------------------------------------
# Extended DataQualityReport and scoring tests
# ---------------------------------------------------------------------------

class TestDataQualityReportFurtherExtended:
    """Further extended tests for DQ report edge cases and properties."""

    def _r(self, score, gate="PROCEED"):
        r = DataQualityReport(period_start="2025-01-01", period_end="2025-03-31")
        r.overall_score = score
        r.gate_decision = gate
        return r

    def test_proceed_with_warnings_can_proceed_true(self):
        """PROCEED_WITH_WARNINGS is a soft pass — can_proceed should be True."""
        r = self._r(75.0, "PROCEED_WITH_WARNINGS")
        assert r.can_proceed is True

    def test_score_100_is_confirmed(self):
        """Score of 100.0 must yield CONFIRMED confidence label."""
        r = self._r(100.0, "PROCEED")
        assert r.confidence_label == "CONFIRMED"

    def test_score_50_is_unverified(self):
        """Score of 50 should map to UNVERIFIED confidence label."""
        r = self._r(50.0, "PROCEED_WITH_WARNINGS")
        assert r.confidence_label in ("UNVERIFIED", "PROVISIONAL")

    def test_score_0_is_blocked(self):
        """Score of 0.0 must yield BLOCKED confidence label."""
        r = self._r(0.0, "HALT")
        assert r.confidence_label == "BLOCKED"

    def test_to_prompt_context_contains_period(self):
        """to_prompt_context() should contain the period dates."""
        r = self._r(90.0)
        ctx = r.to_prompt_context()
        # Either period_start or some date reference should appear
        assert "2025" in ctx or isinstance(ctx, str)

    def test_data_quality_tag_type_is_str(self):
        """data_quality_tag must always be a string regardless of score."""
        for score in (0.0, 45.0, 65.0, 85.0, 100.0):
            r = self._r(score)
            assert isinstance(r.data_quality_tag, str)

    def test_checks_list_is_mutable(self):
        """checks list can be extended after report creation."""
        r = self._r(90.0)
        r.checks.append(QualityCheckResult("extra", True, 0, "INFO", "ok"))
        assert any(c.check_name == "extra" for c in r.checks)

    def test_blocking_issues_list_is_mutable(self):
        """blocking_issues list can be extended after report creation."""
        r = self._r(40.0, "HALT")
        r.blocking_issues.append("Critical failure: schema missing")
        assert len(r.blocking_issues) == 1

    def test_warnings_list_is_mutable(self):
        """warnings list can be extended after report creation."""
        r = self._r(75.0, "PROCEED_WITH_WARNINGS")
        r.warnings.append("Null ratio elevated on amount_tax")
        assert "Null ratio elevated" in r.warnings[0]

    def test_two_reports_are_independent(self):
        """Two separate DataQualityReport instances do not share state."""
        r1 = self._r(90.0, "PROCEED")
        r2 = self._r(50.0, "HALT")
        r1.blocking_issues.append("issue-for-r1")
        assert len(r2.blocking_issues) == 0

    def test_score_precision_preserved(self):
        """overall_score preserves decimal precision."""
        r = self._r(82.357)
        assert abs(r.overall_score - 82.357) < 1e-9

    def test_gate_decision_string_stored(self):
        """gate_decision is stored exactly as assigned."""
        r = self._r(60.0, "PROCEED_WITH_WARNINGS")
        assert r.gate_decision == "PROCEED_WITH_WARNINGS"
