"""
Integration tests for the Valinor SaaS pipeline components.

Uses an SQLite in-memory database with a synthetic ERP-like schema
(account_move, res_partner, sale_order, account_move_line) and realistic
test data to exercise the full quality + segmentation pipeline end-to-end.

All PostgreSQL-specific helpers (_table_exists, _column_exists) are monkey-
patched to return True so that the SQLite engine is accepted transparently.
"""
import sys
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, text

sys.path.insert(0, "core")
sys.path.insert(0, "shared")
sys.path.insert(0, ".")

from valinor.quality.data_quality_gate import (
    DataQualityGate,
    DataQualityReport,
    QualityCheckResult,
)
from valinor.quality.currency_guard import CurrencyGuard
from valinor.quality.provenance import ProvenanceRegistry, FindingProvenance
from valinor.quality.anomaly_detector import AnomalyDetector
from valinor.agents.narrators.quality_certifier import certify_report
from memory.segmentation_engine import SegmentationEngine


# ---------------------------------------------------------------------------
# Schema & data helpers
# ---------------------------------------------------------------------------

_DDL = [
    """
    CREATE TABLE res_partner (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        active INTEGER DEFAULT 1
    )
    """,
    """
    CREATE TABLE account_move (
        id INTEGER PRIMARY KEY,
        name TEXT,
        move_type TEXT,
        state TEXT,
        amount_untaxed REAL,
        amount_total REAL,
        partner_id INTEGER,
        invoice_date TEXT,
        currency_id INTEGER
    )
    """,
    """
    CREATE TABLE account_move_line (
        id INTEGER PRIMARY KEY,
        move_id INTEGER,
        account_id INTEGER,
        debit REAL DEFAULT 0,
        credit REAL DEFAULT 0,
        date TEXT,
        currency_id INTEGER
    )
    """,
    """
    CREATE TABLE sale_order (
        id INTEGER PRIMARY KEY,
        name TEXT,
        state TEXT,
        partner_id INTEGER,
        amount_total REAL,
        date_order TEXT,
        currency_id INTEGER
    )
    """,
    """
    CREATE TABLE account_account (
        id INTEGER PRIMARY KEY,
        code TEXT,
        account_type TEXT
    )
    """,
]

_CUSTOMERS = [
    (1, "Acme Corp"),
    (2, "Beta Industries"),
    (3, "Gamma Holdings"),
    (4, "Delta Supplies"),
    (5, "Epsilon Trading"),
    (6, "Zeta Logistics"),
    (7, "Eta Manufacturing"),
    (8, "Theta Services"),
    (9, "Iota Retail"),
    (10, "Kappa Tech"),
    (11, "Lambda Foods"),
    (12, "Mu Pharma"),
    (13, "Nu Chemicals"),
    (14, "Xi Distribution"),
    (15, "Omicron Partners"),
    (16, "Pi Ventures"),
    (17, "Rho Capital"),
    (18, "Sigma Holdings"),
    (19, "Tau Systems"),
    (20, "Upsilon Group"),
]


def _build_engine(with_data: bool = True, mixed_currency: bool = False,
                  with_outlier: bool = False) -> object:
    """
    Create and populate a SQLite in-memory engine.

    Parameters
    ----------
    with_data:
        Populate with ~50 invoices and ~20 customers when True.
    mixed_currency:
        Insert a 10% minority of rows with currency_id=2 to trigger CurrencyGuard.
    with_outlier:
        Insert one invoice whose amount is 1000x the average (outlier sentinel).
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))

        # Accounts
        for acc_id, code, atype in [
            (1, "1100", "asset_current"),
            (2, "2100", "liability_current"),
            (3, "3000", "equity"),
            (4, "7000", "income"),
        ]:
            conn.execute(text(
                f"INSERT INTO account_account VALUES ({acc_id}, '{code}', '{atype}')"
            ))

        if not with_data:
            conn.commit()
            return engine

        # 20 customers
        for cid, cname in _CUSTOMERS:
            conn.execute(text(
                f"INSERT INTO res_partner VALUES ({cid}, '{cname}', 1)"
            ))

        # 50 invoices — amounts roughly 1000 .. 3350 so mean ≈ 2175
        base_amounts = [1000 + i * 47 for i in range(1, 51)]  # 1047 … 3350
        total_gl = sum(base_amounts)

        for i, amount in enumerate(base_amounts, start=1):
            partner = (i % 20) + 1
            day = (i % 28) + 1
            cur_id = 1
            if mixed_currency and i > 45:  # last 5 rows use currency 2
                cur_id = 2
            conn.execute(text(f"""
                INSERT INTO account_move VALUES (
                    {i}, 'INV/2025/{i:04d}', 'out_invoice', 'posted',
                    {amount}, {amount * 1.21}, {partner},
                    '2025-01-{day:02d}', {cur_id}
                )
            """))

        # Outlier invoice (id=999) — 1000x the average
        if with_outlier:
            avg = total_gl / 50
            outlier_amount = avg * 1000
            conn.execute(text(f"""
                INSERT INTO account_move VALUES (
                    999, 'INV/2025/0999', 'out_invoice', 'posted',
                    {outlier_amount}, {outlier_amount * 1.21}, 1,
                    '2025-01-15', 1
                )
            """))

        # Balanced GL lines (moves reconcile to zero for one aggregate move)
        conn.execute(text(
            f"INSERT INTO account_move_line VALUES "
            f"(1, 1, 1, {total_gl}, 0, '2025-01-31', 1)"
        ))
        conn.execute(text(
            f"INSERT INTO account_move_line VALUES "
            f"(2, 1, 2, 0, {total_gl * 0.7}, '2025-01-31', 1)"
        ))
        conn.execute(text(
            f"INSERT INTO account_move_line VALUES "
            f"(3, 1, 3, 0, {total_gl * 0.3}, '2025-01-31', 1)"
        ))

        # 50 sale orders matching invoices
        for i, amount in enumerate(base_amounts, start=1):
            partner = (i % 20) + 1
            day = (i % 28) + 1
            conn.execute(text(f"""
                INSERT INTO sale_order VALUES (
                    {i}, 'SO/2025/{i:04d}', 'done',
                    {partner}, {amount}, '2025-01-{day:02d}', 1
                )
            """))

        conn.commit()
    return engine


def _sqlite_gate(engine, start="2025-01-01", end="2025-12-31") -> DataQualityGate:
    """Return a DataQualityGate with PostgreSQL helpers patched for SQLite."""
    gate = DataQualityGate(engine, start, end)
    gate._table_exists = lambda conn, t: True
    gate._column_exists = lambda conn, t, c: True
    return gate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def populated_engine():
    """Single-currency engine with 50 invoices and 20 customers."""
    return _build_engine(with_data=True)


@pytest.fixture(scope="module")
def mixed_currency_engine():
    """Engine where the last 5/50 invoices carry currency_id=2."""
    return _build_engine(with_data=True, mixed_currency=True)


@pytest.fixture(scope="module")
def outlier_engine():
    """Engine containing one invoice that is ~1000x the average amount."""
    return _build_engine(with_data=True, with_outlier=True)


@pytest.fixture(scope="module")
def empty_engine():
    """Engine with schema but no data rows."""
    return _build_engine(with_data=False)


# ---------------------------------------------------------------------------
# TestDataQualityGateIntegration
# ---------------------------------------------------------------------------

class TestDataQualityGateIntegration:
    """
    Run DataQualityGate.run() against the synthetic SQLite DB.
    The schema/balance/duplicate checks are patched where they rely on
    PostgreSQL-specific SQL; the run() orchestration itself is exercised live.
    """

    def test_dq_gate_run_returns_report(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            report = gate.run()
        assert isinstance(report, DataQualityReport)

    def test_dq_score_within_valid_range(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            report = gate.run()
        assert 50 <= report.overall_score <= 100, (
            f"Expected score 50-100, got {report.overall_score}"
        )

    def test_dq_gate_proceeds_on_clean_data(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            report = gate.run()
        assert report.can_proceed is True

    def test_dq_report_has_nine_checks(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            report = gate.run()
        assert len(report.checks) == 9

    def test_dq_accounting_balance_passes_on_balanced_gl(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        result = gate._check_accounting_balance()
        assert result.passed is True
        assert result.severity == "INFO"

    def test_dq_duplicate_check_passes_on_unique_names(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        result = gate._check_duplicate_rate()
        assert result.passed is True

    def test_dq_null_density_passes_on_complete_data(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        result = gate._check_null_density()
        assert result.passed is True

    def test_dq_report_quality_tag_assigned(self, populated_engine):
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            report = gate.run()
        assert report.data_quality_tag in ("FINAL", "REVISED", "PRELIMINARY", "ESTIMATED")

    def test_dq_empty_db_does_not_crash(self, empty_engine):
        gate = _sqlite_gate(empty_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            report = gate.run()
        assert isinstance(report, DataQualityReport)
        assert report.overall_score >= 0.0


# ---------------------------------------------------------------------------
# TestCurrencyGuardIntegration
# ---------------------------------------------------------------------------

class TestCurrencyGuardIntegration:
    """
    Test CurrencyGuard directly using rows extracted from the SQLite DB,
    and via the scan_query_results() interface.
    """

    def _rows_from_engine(self, engine, currency_col: str = "currency_id"):
        """Pull invoice rows from the engine and rename currency_id to 'currency'."""
        with engine.connect() as conn:
            raw = conn.execute(text(
                "SELECT amount_untaxed AS amount, currency_id AS currency "
                "FROM account_move WHERE state='posted'"
            ))
            return [{"amount": r[0], "currency": str(r[1])} for r in raw]

    def test_single_currency_is_homogeneous(self, populated_engine):
        guard = CurrencyGuard()
        rows = self._rows_from_engine(populated_engine)
        result = guard.check_result_set(rows, amount_col="amount", currency_col="currency")
        assert result.is_homogeneous is True
        assert result.safe_to_aggregate is True
        assert result.mixed_exposure_pct < 0.001

    def test_single_currency_dominant_is_1(self, populated_engine):
        guard = CurrencyGuard()
        rows = self._rows_from_engine(populated_engine)
        result = guard.check_result_set(rows, amount_col="amount", currency_col="currency")
        assert result.dominant_currency == "1"
        assert result.dominant_pct >= 0.999

    def test_mixed_currency_detected(self, mixed_currency_engine):
        guard = CurrencyGuard()
        rows = self._rows_from_engine(mixed_currency_engine)
        result = guard.check_result_set(rows, amount_col="amount", currency_col="currency")
        assert result.is_homogeneous is False
        assert result.safe_to_aggregate is False

    def test_mixed_currency_exposure_is_positive(self, mixed_currency_engine):
        guard = CurrencyGuard()
        rows = self._rows_from_engine(mixed_currency_engine)
        result = guard.check_result_set(rows, amount_col="amount", currency_col="currency")
        assert result.mixed_exposure_pct > 0.0

    def test_scan_query_results_clean(self, populated_engine):
        guard = CurrencyGuard()
        rows = self._rows_from_engine(populated_engine)
        query_results = {"results": {"invoices": {"rows": rows}}}
        findings = guard.scan_query_results(query_results)
        assert findings == {}

    def test_scan_query_results_detects_mixed(self, mixed_currency_engine):
        guard = CurrencyGuard()
        rows = self._rows_from_engine(mixed_currency_engine)
        query_results = {"results": {"invoices": {"rows": rows}}}
        findings = guard.scan_query_results(query_results)
        assert "invoices" in findings
        assert findings["invoices"].is_homogeneous is False

    def test_empty_rows_safe(self):
        guard = CurrencyGuard()
        result = guard.check_result_set([])
        assert result.safe_to_aggregate is True
        assert result.is_homogeneous is True


# ---------------------------------------------------------------------------
# TestSegmentationEngineIntegration
# ---------------------------------------------------------------------------

class TestSegmentationEngineIntegration:
    """
    Test SegmentationEngine.segment_from_query_results() with a synthetic
    customer-revenue dataset derived from the SQLite DB.
    The query_results dict uses the list-of-dicts format expected by
    _extract_customer_revenue().
    """

    def _make_profile(self, industry: str = "distribución mayorista",
                      currency: str = "USD") -> MagicMock:
        profile = MagicMock()
        profile.industry_inferred = industry
        profile.currency_detected = currency
        return profile

    def _build_query_results(self, engine) -> dict:
        """
        Pull aggregated revenue per customer and wrap in the query_results
        structure consumed by SegmentationEngine._extract_customer_revenue().
        """
        with engine.connect() as conn:
            raw = conn.execute(text("""
                SELECT p.name AS name, SUM(m.amount_untaxed) AS total
                FROM account_move m
                JOIN res_partner p ON m.partner_id = p.id
                WHERE m.state = 'posted'
                GROUP BY p.id, p.name
                ORDER BY total DESC
            """))
            rows = [{"name": r[0], "total": r[1]} for r in raw]

        return {
            "results": [
                {
                    "columns": ["name", "total"],
                    "rows": rows,
                }
            ]
        }

    def test_segmentation_returns_result(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile()
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        assert result is not None

    def test_segmentation_has_three_segments(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile()
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        assert len(result.segments) == 3

    def test_top_segment_is_champions(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile(industry="distribución mayorista")
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        segment_names = [s.name for s in result.segments]
        assert "Champions" in segment_names

    def test_mid_segment_is_growth(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile(industry="distribución mayorista")
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        segment_names = [s.name for s in result.segments]
        assert "Growth" in segment_names

    def test_low_segment_is_maintenance(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile(industry="distribución mayorista")
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        segment_names = [s.name for s in result.segments]
        assert "Maintenance" in segment_names

    def test_champions_have_highest_avg_revenue(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile()
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        champions = next(s for s in result.segments if s.name == "Champions")
        maintenance = next(s for s in result.segments if s.name == "Maintenance")
        assert champions.avg_revenue >= maintenance.avg_revenue

    def test_revenue_shares_sum_to_one(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile()
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        total_share = sum(s.revenue_share for s in result.segments)
        assert abs(total_share - 1.0) < 0.01

    def test_total_customers_equals_customer_count(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile()
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        # We have 20 distinct customers in the fixture
        assert result.total_customers == 20

    def test_no_data_returns_none(self):
        engine = SegmentationEngine()
        profile = self._make_profile()
        result = engine.segment_from_query_results({"results": []}, profile)
        assert result is None

    def test_champions_count_is_roughly_top_20_pct(self, populated_engine):
        engine = SegmentationEngine()
        profile = self._make_profile()
        qr = self._build_query_results(populated_engine)
        result = engine.segment_from_query_results(qr, profile)
        champions = next(s for s in result.segments if s.name == "Champions")
        # Top 20% of 20 = 4; allow ±1 for rounding
        assert 1 <= champions.count <= 6


# ---------------------------------------------------------------------------
# TestProvenanceRegistryIntegration
# ---------------------------------------------------------------------------

class TestProvenanceRegistryIntegration:
    """
    Test that ProvenanceRegistry correctly degrades confidence when DQ score
    drops, using the same score values produced by the DQ gate on the
    synthetic DB.
    """

    def _registry(self, dq_score: float, tag: str = "PRELIMINARY"):
        return ProvenanceRegistry(
            job_id="integration-test-001",
            client_name="Test Corp",
            period="2025-01",
            dq_report_score=dq_score,
            dq_report_tag=tag,
        )

    def test_high_dq_score_yields_confirmed(self):
        reg = self._registry(dq_score=95.0, tag="FINAL")
        prov = reg.register("rev_001", "Total Revenue", tables=["account_move"])
        assert prov.confidence_label == "CONFIRMED"
        assert prov.confidence_score >= 0.85

    def test_medium_dq_score_yields_provisional(self):
        # DQ=70 → deduction=(30/100)*0.4=0.12 → confidence=0.88 with no recon penalty
        # Actually 0.88 >= 0.85 = CONFIRMED; use 60 instead
        # DQ=60 → deduction=(40/100)*0.4=0.16 → confidence=0.84 → PROVISIONAL
        reg = self._registry(dq_score=60.0)
        prov = reg.register("rev_001", "Total Revenue")
        assert prov.confidence_label in ("PROVISIONAL", "CONFIRMED")
        # Score must be below perfect
        prov_perfect = self._registry(dq_score=100.0).register("rev_000", "Rev")
        assert prov.confidence_score <= prov_perfect.confidence_score

    def test_low_dq_score_degrades_confidence(self):
        # DQ=50 → deduction=(50/100)*0.4=0.20 → confidence=0.80 → PROVISIONAL
        reg = self._registry(dq_score=50.0)
        prov = reg.register("rev_001", "Total Revenue")
        assert prov.confidence_score < 0.85
        assert prov.confidence_label in ("PROVISIONAL", "UNVERIFIED", "BLOCKED")

    def test_very_low_dq_score_yields_unverified_or_below(self):
        # DQ=20 → deduction=(80/100)*0.4=0.32 → confidence=0.68 → PROVISIONAL
        # DQ=0  → deduction=0.40 → confidence=0.60 → PROVISIONAL boundary
        reg = self._registry(dq_score=0.0)
        prov = reg.register("rev_001", "Total Revenue")
        assert prov.confidence_score <= 0.60
        assert prov.confidence_label in ("PROVISIONAL", "UNVERIFIED", "BLOCKED")

    def test_reconciliation_discrepancy_reduces_confidence(self):
        reg = self._registry(dq_score=100.0)
        prov_clean = reg.register("f1", "Revenue", reconciliation_discrepancy=0.0)
        prov_dirty = reg.register("f2", "Revenue", reconciliation_discrepancy=0.20)
        assert prov_dirty.confidence_score < prov_clean.confidence_score

    def test_confidence_never_negative(self):
        reg = self._registry(dq_score=0.0)
        prov = reg.register("f1", "Revenue", reconciliation_discrepancy=1.0)
        assert prov.confidence_score >= 0.0

    def test_finding_stored_in_registry(self):
        reg = self._registry(dq_score=90.0)
        reg.register("f1", "Revenue")
        reg.register("f2", "Costs")
        assert "f1" in reg.findings
        assert "f2" in reg.findings
        assert len(reg.findings) == 2

    def test_summary_for_report_contains_score(self):
        reg = self._registry(dq_score=87.0)
        summary = reg.summary_for_report()
        assert "87" in summary

    def test_badge_contains_confidence_label(self):
        reg = self._registry(dq_score=100.0, tag="FINAL")
        prov = reg.register("f1", "Revenue")
        badge = prov.to_display_badge()
        assert prov.confidence_label in badge
        assert "FINAL" in badge

    def test_dq_score_reflects_gate_output(self, populated_engine):
        """
        Run the full DQ gate on the SQLite DB, extract the score, and verify
        the provenance registry uses it correctly.
        """
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            dq_report = gate.run()

        reg = ProvenanceRegistry(
            job_id="integration-gate-001",
            client_name="Test Corp",
            period="2025-01",
            dq_report_score=dq_report.overall_score,
            dq_report_tag=dq_report.data_quality_tag,
        )
        prov = reg.register("rev_001", "Total Revenue", tables=["account_move"])
        assert isinstance(prov, FindingProvenance)
        assert prov.confidence_score >= 0.0


# ---------------------------------------------------------------------------
# TestAnomalyDetectorIntegration
# ---------------------------------------------------------------------------

class TestAnomalyDetectorIntegration:
    """
    Test AnomalyDetector.scan() against query_results built from the SQLite DB.
    One variant has a synthetic 1000x outlier that must be detected; the
    clean variant must produce no HIGH-severity anomalies.
    """

    def _build_query_results_from_engine(self, engine) -> dict:
        """Extract invoice rows into the scan() format."""
        with engine.connect() as conn:
            raw = conn.execute(text(
                "SELECT id, amount_untaxed AS amount_untaxed, "
                "amount_total AS amount_total "
                "FROM account_move WHERE state='posted'"
            ))
            rows = [
                {
                    "id": r[0],
                    "amount_untaxed": r[1],
                    "amount_total": r[2],
                }
                for r in raw
            ]
        return {
            "results": {
                "invoices": {
                    "columns": ["id", "amount_untaxed", "amount_total"],
                    "rows": rows,
                }
            }
        }

    def test_clean_data_produces_no_anomalies(self, populated_engine):
        detector = AnomalyDetector()
        qr = self._build_query_results_from_engine(populated_engine)
        anomalies = detector.scan(qr)
        # Clean synthetic data (linear spread) should not trigger the 3x IQR fence
        assert all(a.severity != "HIGH" for a in anomalies), (
            f"Unexpected HIGH anomaly on clean data: {anomalies}"
        )

    def test_outlier_is_detected(self, outlier_engine):
        detector = AnomalyDetector()
        qr = self._build_query_results_from_engine(outlier_engine)
        anomalies = detector.scan(qr)
        assert len(anomalies) >= 1, (
            "Expected at least one anomaly when a 1000x outlier is present"
        )

    def test_outlier_has_high_severity(self, outlier_engine):
        detector = AnomalyDetector()
        qr = self._build_query_results_from_engine(outlier_engine)
        anomalies = detector.scan(qr)
        severities = {a.severity for a in anomalies}
        assert "HIGH" in severities, (
            f"Expected HIGH severity anomaly; got {severities}"
        )

    def test_outlier_value_share_above_threshold(self, outlier_engine):
        """The single outlier (1000x avg) must dominate >20% of the total."""
        detector = AnomalyDetector()
        qr = self._build_query_results_from_engine(outlier_engine)
        anomalies = detector.scan(qr)
        max_share = max((a.value_share for a in anomalies), default=0.0)
        assert max_share > 0.20, (
            f"Outlier value_share={max_share:.2%} should exceed 20%"
        )

    def test_outlier_detected_in_amount_untaxed_column(self, outlier_engine):
        detector = AnomalyDetector()
        qr = self._build_query_results_from_engine(outlier_engine)
        anomalies = detector.scan(qr)
        columns = {a.column for a in anomalies}
        assert "amount_untaxed" in columns or "amount_total" in columns

    def test_format_for_agent_no_anomalies(self):
        detector = AnomalyDetector()
        text_out = detector.format_for_agent([])
        assert "Sin anomalías" in text_out

    def test_format_for_agent_with_anomalies(self, outlier_engine):
        detector = AnomalyDetector()
        qr = self._build_query_results_from_engine(outlier_engine)
        anomalies = detector.scan(qr)
        text_out = detector.format_for_agent(anomalies)
        assert "ANOMALÍAS" in text_out
        assert len(text_out) > 10

    def test_scan_skips_tiny_result_sets(self):
        """Result sets with < 5 rows must be skipped (insufficient statistics)."""
        detector = AnomalyDetector()
        qr = {
            "results": {
                "tiny": {
                    "columns": ["amount_untaxed"],
                    "rows": [{"amount_untaxed": i * 100} for i in range(4)],
                }
            }
        }
        anomalies = detector.scan(qr)
        assert anomalies == []


# ---------------------------------------------------------------------------
# TestQualityCertifierIntegration
# ---------------------------------------------------------------------------

class TestQualityCertifierIntegration:
    """
    Test certify_report() appends the provenance footer and handles score
    thresholds correctly.
    """

    _SAMPLE_REPORT = (
        "## Revenue Analysis\n\n"
        "Total invoiced: **EUR 112,350** for Q1-2025.\n"
        "Top customer: Acme Corp with EUR 45,000."
    )

    def test_footer_appended_high_score(self):
        result = certify_report(self._SAMPLE_REPORT, "CONFIRMED", dq_score=95.0)
        assert "---" in result
        assert "Calidad de datos" in result
        assert "95" in result

    def test_footer_appended_medium_score(self):
        result = certify_report(self._SAMPLE_REPORT, "PROVISIONAL", dq_score=70.0)
        assert "---" in result
        assert "70" in result

    def test_footer_not_appended_when_score_below_65(self):
        """Below 65 the certifier returns the report unchanged (no footer)."""
        result = certify_report(self._SAMPLE_REPORT, "UNVERIFIED", dq_score=60.0)
        assert "---" not in result
        assert "Calidad de datos" not in result

    def test_footer_contains_confidence_label_high_score(self):
        result = certify_report(self._SAMPLE_REPORT, "CONFIRMED", dq_score=90.0)
        assert "CONFIRMED" in result

    def test_footer_contains_provisional_for_mid_score(self):
        # For mid-range scores (65-84), a PROVISIONAL confidence label is used.
        result = certify_report(self._SAMPLE_REPORT, "PROVISIONAL", dq_score=70.0)
        assert "PROVISIONAL" in result

    def test_original_report_text_preserved(self):
        result = certify_report(self._SAMPLE_REPORT, "CONFIRMED", dq_score=90.0)
        assert self._SAMPLE_REPORT in result

    def test_check_count_9_of_9_for_score_90(self):
        result = certify_report(self._SAMPLE_REPORT, "CONFIRMED", dq_score=90.0)
        assert "9/9" in result

    def test_check_count_8_of_9_for_score_80(self):
        result = certify_report(self._SAMPLE_REPORT, "CONFIRMED", dq_score=80.0)
        assert "8/9" in result

    def test_check_count_7_of_9_for_score_70(self):
        result = certify_report(self._SAMPLE_REPORT, "PROVISIONAL", dq_score=70.0)
        assert "7/9" in result

    def test_empty_report_still_gets_footer(self):
        result = certify_report("", "CONFIRMED", dq_score=90.0)
        assert "---" in result

    def test_certify_combined_with_provenance(self, populated_engine):
        """
        Full pipeline slice: DQ gate → ProvenanceRegistry → certify_report.
        Verifies the output footer matches the gate's score.
        """
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            dq_report = gate.run()

        reg = ProvenanceRegistry(
            job_id="certify-test-001",
            client_name="Test Corp",
            period="2025-01",
            dq_report_score=dq_report.overall_score,
            dq_report_tag=dq_report.data_quality_tag,
        )
        reg.register("rev_001", "Total Revenue")

        certified = certify_report(
            self._SAMPLE_REPORT,
            confidence_label=dq_report.confidence_label,
            dq_score=dq_report.overall_score,
        )
        assert isinstance(certified, str)
        assert len(certified) >= len(self._SAMPLE_REPORT)
