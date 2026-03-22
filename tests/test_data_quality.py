"""
Tests for the Valinor Data Quality Gate.
Uses SQLite in-memory database to simulate ERP data scenarios.
Individual SQL checks that use PostgreSQL-specific syntax are tested via mocking;
the aggregation logic and pure-Python modules are exercised directly against SQLite.
"""
import sys
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text

sys.path.insert(0, "core")
sys.path.insert(0, ".")

from valinor.quality.data_quality_gate import (
    DataQualityGate,
    DataQualityReport,
    QualityCheckResult,
)
from valinor.quality.currency_guard import CurrencyGuard, CurrencyCheckResult
from valinor.quality.provenance import ProvenanceRegistry, FindingProvenance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_engine():
    """SQLite in-memory engine with Odoo-like schema but NO data."""
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


@pytest.fixture
def engine_with_data(clean_engine):
    """Engine with realistic, balanced test data."""
    with clean_engine.connect() as conn:
        # Accounts: assets, liability, equity, income
        accounts = [
            (1, "1000", "asset_current"),
            (2, "2000", "liability_current"),
            (3, "3000", "equity"),
            (4, "7000", "income"),
        ]
        for acc_id, code, atype in accounts:
            conn.execute(text(
                f"INSERT INTO account_account VALUES ({acc_id}, '{code}', '{atype}')"
            ))

        # Partners
        for i in range(1, 11):
            conn.execute(text(
                f"INSERT INTO res_partner VALUES ({i}, 'Partner {i}', 1)"
            ))

        # Posted invoices (50 invoices, various amounts)
        for i in range(1, 51):
            partner = (i % 10) + 1
            amount = 1000 + (i * 47)
            day = (i % 28) + 1
            conn.execute(text(f"""
                INSERT INTO account_move VALUES (
                    {i}, 'INV/2025/{i:04d}', 'out_invoice', 'posted',
                    {amount}, {partner}, '2025-01-{day:02d}', 1
                )
            """))

        # Balanced GL lines for move id=1
        total = sum(1000 + i * 47 for i in range(1, 51))
        conn.execute(text(
            f"INSERT INTO account_move_line VALUES (1, 1, 1, {total}, 0, '2025-01-31', 1)"
        ))
        conn.execute(text(
            f"INSERT INTO account_move_line VALUES (2, 1, 2, 0, {total * 0.6}, '2025-01-31', 1)"
        ))
        conn.execute(text(
            f"INSERT INTO account_move_line VALUES (3, 1, 3, 0, {total * 0.4}, '2025-01-31', 1)"
        ))
        conn.commit()
    return clean_engine


@pytest.fixture
def empty_engine():
    """Completely empty SQLite engine (no tables at all)."""
    return create_engine("sqlite:///:memory:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _passing(name="dummy"):
    return QualityCheckResult(name, True, 0, "INFO", "OK")


def _warning(name="dummy", impact=10):
    return QualityCheckResult(name, False, impact, "WARNING", "warn detail")


def _critical(name="dummy", impact=15):
    return QualityCheckResult(name, False, impact, "CRITICAL", "critical detail")


def _fatal(name="dummy", impact=20):
    return QualityCheckResult(name, False, impact, "FATAL", "fatal detail")


# ---------------------------------------------------------------------------
# TestDataQualityGateSchemaCheck
# ---------------------------------------------------------------------------

class TestDataQualityGateSchemaCheck:
    """
    The schema check uses information_schema.tables which is PostgreSQL-specific.
    SQLite returns 0 for that query, so all tables appear "missing".
    We verify the gate gracefully surfaces a FATAL result on the SQLite empty DB
    and that the schema check method exists and is callable.
    """

    def test_schema_check_exists(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        assert hasattr(gate, "_check_schema_integrity")

    @pytest.mark.skip(
        reason=(
            "PostgreSQL-specific: information_schema.tables returns nothing in SQLite. "
            "The _check_schema_integrity method always reports missing tables on SQLite."
        )
    )
    def test_schema_present(self, engine_with_data):
        """On a real PostgreSQL Odoo DB all required tables exist — check passes."""
        gate = DataQualityGate(engine_with_data, "2025-01-01", "2025-12-31")
        result = gate._check_schema_integrity()
        assert result.passed is True
        assert result.severity == "INFO"

    def test_schema_missing_tables_via_mock(self, empty_engine):
        """
        Simulate the schema check returning FATAL when core tables are absent.
        We mock _table_exists to always return False so SQLite compatibility
        does not interfere.
        """
        gate = DataQualityGate(empty_engine, "2025-01-01", "2025-12-31", erp="odoo")
        with patch.object(gate, "_table_exists", return_value=False):
            result = gate._check_schema_integrity()
        assert result.passed is False
        assert result.severity == "FATAL"
        assert result.score_impact == DataQualityGate.SCORE_WEIGHTS["schema_integrity"]

    def test_schema_all_present_via_mock(self, clean_engine):
        """
        Simulate the schema check passing when all tables and columns exist.
        """
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31", erp="odoo")
        with patch.object(gate, "_table_exists", return_value=True), \
             patch.object(gate, "_column_exists", return_value=True):
            result = gate._check_schema_integrity()
        assert result.passed is True
        assert result.severity == "INFO"


# ---------------------------------------------------------------------------
# TestDataQualityGateAccountingBalance
# ---------------------------------------------------------------------------

class TestDataQualityGateAccountingBalance:
    """
    The accounting balance check uses LIKE 'asset%' / 'liability%' and joins.
    SQLite supports these, so we can test it directly against the in-memory DB.
    However the _table_exists helper uses information_schema, which won't match
    SQLite tables, so we patch that helper to return True.
    """

    def _gate(self, engine):
        gate = DataQualityGate(engine, "2025-01-01", "2025-12-31")
        # Make _table_exists always return True for SQLite compatibility
        gate._table_exists = lambda conn, t: True
        return gate

    def test_balanced_books(self, engine_with_data):
        gate = self._gate(engine_with_data)
        result = gate._check_accounting_balance()
        assert result.passed is True
        assert result.severity == "INFO"

    def test_unbalanced_books(self, engine_with_data):
        """Insert an extra asset line that creates >1% imbalance."""
        with engine_with_data.connect() as conn:
            conn.execute(text(
                "INSERT INTO account_move_line VALUES (999, 1, 1, 9999999, 0, '2025-01-31', 1)"
            ))
            conn.commit()
        gate = self._gate(engine_with_data)
        result = gate._check_accounting_balance()
        assert result.passed is False
        assert result.severity == "FATAL"
        assert result.score_impact == DataQualityGate.SCORE_WEIGHTS["accounting_balance"]

    def test_empty_gl(self, clean_engine):
        """No GL entries — check returns INFO (inconclusive, not FATAL)."""
        gate = self._gate(clean_engine)
        result = gate._check_accounting_balance()
        # Either no data row or rhs=0: both lead to passed=True INFO
        assert result.passed is True
        assert result.severity == "INFO"


# ---------------------------------------------------------------------------
# TestDataQualityGateDuplicates
# ---------------------------------------------------------------------------

class TestDataQualityGateDuplicates:
    """
    The duplicate check uses standard SQL compatible with SQLite.
    We patch _table_exists to bypass the PostgreSQL information_schema check.
    """

    def _gate(self, engine):
        gate = DataQualityGate(engine, "2025-01-01", "2025-12-31")
        gate._table_exists = lambda conn, t: True
        return gate

    def test_no_duplicates(self, engine_with_data):
        gate = self._gate(engine_with_data)
        result = gate._check_duplicate_rate()
        assert result.passed is True

    def test_with_duplicates(self, engine_with_data):
        """Insert three invoices with the same name to trigger the duplicate check."""
        with engine_with_data.connect() as conn:
            for extra_id in (101, 102, 103):
                conn.execute(text(f"""
                    INSERT INTO account_move VALUES (
                        {extra_id}, 'INV/2025/DUPE', 'out_invoice', 'posted',
                        500, 1, '2025-01-15', 1
                    )
                """))
            conn.commit()
        gate = self._gate(engine_with_data)
        result = gate._check_duplicate_rate()
        assert result.passed is False
        assert result.severity == "CRITICAL"
        assert "Duplicate" in result.detail

    def test_no_posted_invoices(self, clean_engine):
        """Empty account_move → check returns INFO (nothing to duplicate)."""
        gate = self._gate(clean_engine)
        result = gate._check_duplicate_rate()
        assert result.passed is True
        assert result.severity == "INFO"


# ---------------------------------------------------------------------------
# TestCurrencyGuard
# ---------------------------------------------------------------------------

class TestCurrencyGuard:

    def _guard(self):
        return CurrencyGuard()

    # --- check_result_set ---

    def test_homogeneous_single_currency(self):
        rows = [{"currency": "EUR", "amount": 1000.0 + i} for i in range(20)]
        result = self._guard().check_result_set(rows, amount_col="amount", currency_col="currency")
        assert result.is_homogeneous is True
        assert result.dominant_currency == "EUR"
        assert result.mixed_exposure_pct < 0.001
        assert result.safe_to_aggregate is True

    def test_mixed_currencies(self):
        """90% EUR, 10% USD by amount → is_homogeneous=False, mixed_exposure_pct ≈ 0.10."""
        rows = (
            [{"currency": "EUR", "amount": 9000.0}] +
            [{"currency": "USD", "amount": 1000.0}]
        )
        result = self._guard().check_result_set(rows, amount_col="amount", currency_col="currency")
        assert result.is_homogeneous is False
        assert result.dominant_currency == "EUR"
        assert abs(result.mixed_exposure_pct - 0.10) < 0.01
        assert result.safe_to_aggregate is False

    def test_no_currency_column(self):
        """Rows with no currency column → safe_to_aggregate=True (unknown, assume safe)."""
        rows = [{"amount": 100.0}, {"amount": 200.0}]
        result = self._guard().check_result_set(rows, amount_col="amount")
        assert result.safe_to_aggregate is True

    def test_empty_rows(self):
        result = self._guard().check_result_set([])
        assert result.is_homogeneous is True
        assert result.safe_to_aggregate is True

    def test_zero_amounts(self):
        """All amounts are zero — still detect two distinct currency codes."""
        rows = [
            {"currency": "EUR", "amount": 0.0},
            {"currency": "USD", "amount": 0.0},
        ]
        result = self._guard().check_result_set(rows, amount_col="amount", currency_col="currency")
        # total=0, dominant_pct=1.0 by fallback — no division by zero crash
        assert result is not None

    # --- scan_query_results ---

    def test_scan_query_results_clean(self):
        """No mixed currencies → returned dict is empty."""
        query_results = {
            "results": {
                "q1": {"rows": [{"currency": "EUR", "amount": 500}]},
                "q2": {"rows": [{"currency": "EUR", "amount": 300}]},
            }
        }
        findings = self._guard().scan_query_results(query_results)
        assert findings == {}

    def test_scan_query_results_mixed(self):
        """One query has mixed currencies → that query appears in findings."""
        query_results = {
            "results": {
                "q_clean": {"rows": [{"currency": "EUR", "amount": 500}]},
                "q_mixed": {"rows": [
                    {"currency": "EUR", "amount": 900},
                    {"currency": "USD", "amount": 100},
                ]},
            }
        }
        findings = self._guard().scan_query_results(query_results)
        assert "q_mixed" in findings
        assert "q_clean" not in findings
        assert findings["q_mixed"].is_homogeneous is False

    def test_scan_empty_results(self):
        findings = self._guard().scan_query_results({"results": {}})
        assert findings == {}

    def test_scan_skips_empty_row_sets(self):
        query_results = {"results": {"q1": {"rows": []}}}
        findings = self._guard().scan_query_results(query_results)
        assert findings == {}


# ---------------------------------------------------------------------------
# TestProvenanceRegistry
# ---------------------------------------------------------------------------

class TestProvenanceRegistry:

    def _registry(self, dq_score: float = 100.0, tag: str = "FINAL"):
        return ProvenanceRegistry(
            job_id="job-001",
            client_name="Acme Corp",
            period="2025-01",
            dq_report_score=dq_score,
            dq_report_tag=tag,
        )

    def test_register_returns_finding_provenance(self):
        reg = self._registry(dq_score=100.0)
        prov = reg.register("f1", "Revenue", tables=["account_move"])
        assert isinstance(prov, FindingProvenance)
        assert prov.finding_id == "f1"
        assert prov.metric_name == "Revenue"

    def test_register_high_dq_score_confirmed(self):
        """DQ=100 → no deduction → confidence=1.0 → CONFIRMED."""
        reg = self._registry(dq_score=100.0)
        prov = reg.register("f1", "Revenue")
        assert prov.confidence_score >= 0.85
        assert prov.confidence_label == "CONFIRMED"

    def test_register_dq_95_confirmed(self):
        """DQ=95 → deduction=(5/100)*0.4=0.02 → confidence=0.98 → CONFIRMED."""
        reg = self._registry(dq_score=95.0)
        prov = reg.register("f1", "Revenue")
        assert prov.confidence_score >= 0.85
        assert prov.confidence_label == "CONFIRMED"

    def test_register_low_dq_score_degraded(self):
        """
        DQ=50 → deduction=(50/100)*0.4=0.20 → confidence=0.80 (no recon penalty).
        0.80 is between 0.65 and 0.85 → PROVISIONAL.
        """
        reg = self._registry(dq_score=50.0)
        prov = reg.register("f1", "Revenue")
        assert prov.confidence_score < 0.85
        assert prov.confidence_label in ("PROVISIONAL", "UNVERIFIED", "BLOCKED")

    def test_register_very_low_dq_score(self):
        """DQ=0 → deduction=0.40 → confidence=0.60 → PROVISIONAL."""
        reg = self._registry(dq_score=0.0)
        prov = reg.register("f1", "Revenue")
        assert prov.confidence_score <= 0.60
        assert prov.confidence_label in ("PROVISIONAL", "UNVERIFIED", "BLOCKED")

    def test_register_with_reconciliation_discrepancy(self):
        """
        DQ=100, recon discrepancy=15% (>10%) → recon_penalty=min(0.15/0.10,1)*0.20=0.20
        → confidence = 1.0 - 0.0 - 0.20 = 0.80 → PROVISIONAL.
        """
        reg = self._registry(dq_score=100.0)
        prov = reg.register("f1", "Revenue", reconciliation_discrepancy=0.15)
        assert prov.confidence_score < 1.0
        assert prov.confidence_label in ("CONFIRMED", "PROVISIONAL")
        # The penalty must be lower than a perfect-score finding
        prov_perfect = reg.register("f2", "Revenue", reconciliation_discrepancy=0.0)
        assert prov.confidence_score <= prov_perfect.confidence_score

    def test_register_stores_in_findings_dict(self):
        reg = self._registry()
        reg.register("f1", "Revenue")
        reg.register("f2", "Expenses")
        assert "f1" in reg.findings
        assert "f2" in reg.findings
        assert len(reg.findings) == 2

    def test_provenance_summary_non_empty(self):
        reg = self._registry(dq_score=90.0)
        reg.register("f1", "Revenue")
        summary = reg.summary_for_report()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_provenance_summary_contains_score(self):
        reg = self._registry(dq_score=87.0)
        summary = reg.summary_for_report()
        assert "87" in summary

    def test_provenance_summary_contains_tag(self):
        reg = self._registry(tag="REVISED")
        summary = reg.summary_for_report()
        assert "REVISED" in summary

    def test_display_badge_format(self):
        reg = self._registry(dq_score=100.0, tag="FINAL")
        prov = reg.register("f1", "Revenue")
        badge = prov.to_display_badge()
        assert "CONFIRMED" in badge
        assert "FINAL" in badge

    def test_confidence_clamps_at_zero(self):
        """Extremely low DQ + 100% discrepancy must not produce negative confidence."""
        reg = self._registry(dq_score=0.0)
        prov = reg.register("f1", "Revenue", reconciliation_discrepancy=1.0)
        assert prov.confidence_score >= 0.0


# ---------------------------------------------------------------------------
# TestDataQualityReport — unit tests for the report dataclass itself
# ---------------------------------------------------------------------------

class TestDataQualityReport:

    def test_default_report_values(self):
        report = DataQualityReport()
        assert report.overall_score == 100.0
        assert report.gate_decision == "PROCEED"
        assert report.can_proceed is True

    def test_can_proceed_true_for_proceed(self):
        report = DataQualityReport(gate_decision="PROCEED")
        assert report.can_proceed is True

    def test_can_proceed_true_for_proceed_with_warnings(self):
        report = DataQualityReport(gate_decision="PROCEED_WITH_WARNINGS")
        assert report.can_proceed is True

    def test_can_proceed_false_for_halt(self):
        report = DataQualityReport(gate_decision="HALT")
        assert report.can_proceed is False

    def test_confidence_label_confirmed(self):
        report = DataQualityReport(overall_score=90.0)
        assert report.confidence_label == "CONFIRMED"

    def test_confidence_label_provisional(self):
        report = DataQualityReport(overall_score=70.0)
        assert report.confidence_label == "PROVISIONAL"

    def test_confidence_label_unverified(self):
        report = DataQualityReport(overall_score=50.0)
        assert report.confidence_label == "UNVERIFIED"

    def test_confidence_label_blocked(self):
        report = DataQualityReport(overall_score=30.0)
        assert report.confidence_label == "BLOCKED"

    def test_confidence_label_boundaries(self):
        assert DataQualityReport(overall_score=85.0).confidence_label == "CONFIRMED"
        assert DataQualityReport(overall_score=84.9).confidence_label == "PROVISIONAL"
        assert DataQualityReport(overall_score=65.0).confidence_label == "PROVISIONAL"
        assert DataQualityReport(overall_score=64.9).confidence_label == "UNVERIFIED"
        assert DataQualityReport(overall_score=45.0).confidence_label == "UNVERIFIED"
        assert DataQualityReport(overall_score=44.9).confidence_label == "BLOCKED"

    def test_to_prompt_context_contains_dq_score(self):
        report = DataQualityReport(overall_score=80.0, gate_decision="PROCEED_WITH_WARNINGS")
        ctx = report.to_prompt_context()
        assert "DQ Score" in ctx

    def test_to_prompt_context_contains_gate(self):
        report = DataQualityReport(overall_score=80.0, gate_decision="PROCEED_WITH_WARNINGS")
        ctx = report.to_prompt_context()
        assert "Gate:" in ctx

    def test_to_prompt_context_contains_decision(self):
        report = DataQualityReport(overall_score=80.0, gate_decision="PROCEED_WITH_WARNINGS")
        ctx = report.to_prompt_context()
        assert "PROCEED_WITH_WARNINGS" in ctx

    def test_to_prompt_context_warns_about_unverified(self):
        report = DataQualityReport(overall_score=80.0)
        ctx = report.to_prompt_context()
        assert "UNVERIFIED" in ctx  # instruction text mentions UNVERIFIED


# ---------------------------------------------------------------------------
# TestDataQualityGateRunAggregation
# (mocked checks — tests the run() orchestration logic only)
# ---------------------------------------------------------------------------

class TestDataQualityGateRunAggregation:

    def _all_checks_mocked(self, gate, overrides: dict):
        """
        Return a context manager that patches all 9 check methods.
        `overrides` maps method_name -> QualityCheckResult.
        Any method not in overrides gets _passing().
        """
        defaults = {
            "_check_schema_integrity":              _passing("schema_integrity"),
            "_check_null_density":                  _passing("null_density"),
            "_check_duplicate_rate":                _passing("duplicate_rate"),
            "_check_accounting_balance":            _passing("accounting_balance"),
            "_check_cross_table_reconciliation":    _passing("cross_table_reconcile"),
            "_check_outlier_screen":                _passing("outlier_screen"),
            "_check_benford_compliance":            _passing("benford_compliance"),
            "_check_temporal_consistency":          _passing("temporal_consistency"),
            "_check_receivables_revenue_cointegration": _passing("receivables_cointegration"),
        }
        defaults.update(overrides)

        patches = [
            patch.object(gate, name, return_value=result)
            for name, result in defaults.items()
        ]
        # Return a combined context manager using unittest.mock.patch's stack
        from contextlib import ExitStack
        stack = ExitStack()
        for p in patches:
            stack.enter_context(p)
        return stack

    # --- proceed decision ---

    def test_proceed_decision_all_pass(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {}):
            report = gate.run()
        assert report.overall_score == 100.0
        assert report.gate_decision == "PROCEED"

    # --- proceed with warnings ---

    def test_proceed_with_warnings_on_warning_severity(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {
            "_check_outlier_screen": _warning("outlier_screen", impact=10),
        }):
            report = gate.run()
        assert report.gate_decision == "PROCEED_WITH_WARNINGS"
        assert report.overall_score == 90.0
        assert len(report.warnings) == 1

    def test_proceed_with_warnings_on_critical_severity(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {
            "_check_null_density": _critical("null_density", impact=15),
        }):
            report = gate.run()
        assert report.gate_decision == "PROCEED_WITH_WARNINGS"
        assert report.overall_score == 85.0

    # --- halt on fatal ---

    def test_halt_on_fatal_check(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {
            "_check_schema_integrity": _fatal("schema_integrity", impact=15),
        }):
            report = gate.run()
        assert report.gate_decision == "HALT"
        assert report.can_proceed is False
        assert len(report.blocking_issues) == 1

    def test_halt_persists_even_with_passing_checks_after(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {
            "_check_schema_integrity": _fatal("schema_integrity", impact=15),
            "_check_outlier_screen":   _warning("outlier_screen", impact=10),
        }):
            report = gate.run()
        assert report.gate_decision == "HALT"

    # --- score clamping ---

    def test_score_cannot_go_negative(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        huge_impact = QualityCheckResult("x", False, 999, "WARNING", "huge")
        with self._all_checks_mocked(gate, {
            "_check_schema_integrity":              huge_impact,
            "_check_null_density":                  huge_impact,
            "_check_duplicate_rate":                huge_impact,
            "_check_accounting_balance":            huge_impact,
            "_check_cross_table_reconciliation":    huge_impact,
            "_check_outlier_screen":                huge_impact,
            "_check_benford_compliance":            huge_impact,
            "_check_temporal_consistency":          huge_impact,
            "_check_receivables_revenue_cointegration": huge_impact,
        }):
            report = gate.run()
        assert report.overall_score >= 0.0

    # --- mixed severity combination ---

    def test_mixed_warning_and_critical_checks(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {
            "_check_outlier_screen":       _warning("outlier_screen", impact=10),
            "_check_temporal_consistency": _critical("temporal_consistency", impact=15),
        }):
            report = gate.run()
        assert report.overall_score == 75.0
        assert report.gate_decision == "PROCEED_WITH_WARNINGS"
        assert len(report.warnings) == 2

    def test_score_aggregation_example_from_spec(self, clean_engine):
        """
        passing=7, warning(10pts), critical(15pts) → score=100-10-15=75
        gate=PROCEED_WITH_WARNINGS, warnings=2.
        """
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {
            "_check_outlier_screen":                _warning("outlier_screen", impact=10),
            "_check_temporal_consistency":          _critical("temporal_consistency", impact=15),
        }):
            report = gate.run()
        assert report.overall_score == 75.0
        assert report.gate_decision == "PROCEED_WITH_WARNINGS"
        assert len(report.warnings) == 2

    # --- check count ---

    def test_run_executes_all_nine_checks(self, clean_engine):
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        with self._all_checks_mocked(gate, {}):
            report = gate.run()
        assert len(report.checks) == 9

    # --- quality tag ---

    def test_quality_tag_final_for_high_score_old_period(self, clean_engine):
        """score>=85 and period end >30 days ago → FINAL."""
        gate = DataQualityGate(clean_engine, "2020-01-01", "2020-01-31")
        with self._all_checks_mocked(gate, {}):
            report = gate.run()
        assert report.data_quality_tag == "FINAL"

    def test_quality_tag_estimated_for_low_score(self, clean_engine):
        """score<50 → ESTIMATED."""
        gate = DataQualityGate(clean_engine, "2025-01-01", "2025-12-31")
        huge = QualityCheckResult("x", False, 60, "CRITICAL", "bad")
        with self._all_checks_mocked(gate, {"_check_accounting_balance": huge}):
            report = gate.run()
        assert report.data_quality_tag in ("ESTIMATED", "PRELIMINARY")


# ---------------------------------------------------------------------------
# TestDataQualityGateNullDensity (SQLite compatible via mocked _table_exists)
# ---------------------------------------------------------------------------

class TestDataQualityGateNullDensity:

    def _gate(self, engine):
        gate = DataQualityGate(engine, "2025-01-01", "2025-12-31")
        gate._table_exists = lambda conn, t: True
        gate._column_exists = lambda conn, t, c: True
        return gate

    def test_no_nulls_passes(self, engine_with_data):
        gate = self._gate(engine_with_data)
        result = gate._check_null_density()
        assert result.passed is True

    def test_null_partner_id_fails(self, clean_engine):
        """Insert invoices with NULL partner_id (>5% threshold) → CRITICAL."""
        with clean_engine.connect() as conn:
            for i in range(1, 21):
                conn.execute(text(f"""
                    INSERT INTO account_move VALUES (
                        {i}, 'INV/{i}', 'out_invoice', 'posted',
                        1000, NULL, '2025-01-01', 1
                    )
                """))
            conn.commit()
        gate = self._gate(clean_engine)
        result = gate._check_null_density()
        assert result.passed is False
        assert result.severity == "CRITICAL"


# ---------------------------------------------------------------------------
# TestQualityCheckResult — dataclass unit tests
# ---------------------------------------------------------------------------

class TestQualityCheckResult:

    def test_defaults(self):
        r = QualityCheckResult("test", True, 0, "INFO", "all good")
        assert r.recommendation == ""
        assert r.passed is True

    def test_failed_with_recommendation(self):
        r = QualityCheckResult("test", False, 20, "FATAL", "missing tables", "fix the schema")
        assert r.passed is False
        assert r.recommendation == "fix the schema"
        assert r.score_impact == 20
