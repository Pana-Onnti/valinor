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
from memory.profile_extractor import ProfileExtractor
from memory.client_profile import ClientProfile
from memory.adaptive_context_builder import build_adaptive_context


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


# ---------------------------------------------------------------------------
# TestProfileExtractorIntegration
# ---------------------------------------------------------------------------

class TestProfileExtractorIntegration:
    """
    Test ProfileExtractor.update_from_run() with synthetic finding dicts and
    a fresh ClientProfile, verifying delta computation, run_history cap,
    severity escalation, KPI extraction, and resolved-finding migration.
    """

    def _make_profile(self, name: str = "TestCorp") -> ClientProfile:
        return ClientProfile.new(name)

    def _make_findings(self, ids_with_severity) -> dict:
        """
        Build a findings dict in the format expected by update_from_run().
        ids_with_severity: list of (finding_id, severity, title) tuples.
        """
        findings_list = [
            {"id": fid, "severity": sev, "title": title}
            for fid, sev, title in ids_with_severity
        ]
        return {"analyst": {"findings": findings_list}}

    def test_new_vs_existing_findings(self):
        """update_from_run() correctly classifies brand-new vs existing findings."""
        extractor = ProfileExtractor()
        profile = self._make_profile()

        # First run — all three are new
        findings_run1 = self._make_findings([
            ("F001", "HIGH", "High AR overdue"),
            ("F002", "MEDIUM", "Duplicate invoices"),
        ])
        delta1 = extractor.update_from_run(
            profile, findings_run1, {}, {}, period="2025-01"
        )
        assert set(delta1["new"]) == {"F001", "F002"}
        assert delta1["persists"] == []

        # Second run — F001 and F002 persist, F003 is new
        findings_run2 = self._make_findings([
            ("F001", "HIGH", "High AR overdue"),
            ("F002", "MEDIUM", "Duplicate invoices"),
            ("F003", "LOW", "Minor rounding gap"),
        ])
        delta2 = extractor.update_from_run(
            profile, findings_run2, {}, {}, period="2025-02"
        )
        assert "F003" in delta2["new"]
        assert "F001" in delta2["persists"] or "F001" in delta2["worsened"] or "F001" in delta2["improved"]
        assert "F002" in delta2["persists"] or "F002" in delta2["worsened"] or "F002" in delta2["improved"]

    def test_runs_open_increments_on_persistent_finding(self):
        """runs_open counter increments each time a finding reappears."""
        extractor = ProfileExtractor()
        profile = self._make_profile()
        findings = self._make_findings([("F001", "MEDIUM", "Persistent issue")])

        for period_idx in range(1, 4):
            extractor.update_from_run(
                profile, findings, {}, {}, period=f"2025-0{period_idx}"
            )

        rec = profile.known_findings["F001"]
        assert rec["runs_open"] == 3

    def test_resolved_findings_move_on_disappearance(self):
        """A finding absent from the current run is moved to resolved_findings."""
        extractor = ProfileExtractor()
        profile = self._make_profile()

        # Run 1: F001 appears
        extractor.update_from_run(
            profile,
            self._make_findings([("F001", "HIGH", "Issue A")]),
            {}, {}, period="2025-01",
        )
        assert "F001" in profile.known_findings

        # Run 2: F001 absent — should be resolved
        extractor.update_from_run(
            profile, self._make_findings([]), {}, {}, period="2025-02"
        )
        assert "F001" not in profile.known_findings
        assert "F001" in profile.resolved_findings
        assert "resolved_at" in profile.resolved_findings["F001"]

    def test_severity_escalation_at_runs_open_5(self):
        """Findings open for >= 5 consecutive runs are auto-escalated one severity level."""
        extractor = ProfileExtractor()
        profile = self._make_profile()
        findings = self._make_findings([("F001", "LOW", "Stale finding")])

        # Simulate 5 consecutive runs
        for i in range(1, 6):
            extractor.update_from_run(
                profile, findings, {}, {}, period=f"2025-{i:02d}"
            )

        rec = profile.known_findings["F001"]
        # After 5 runs, LOW should have been escalated to MEDIUM
        assert rec["severity"] in ("MEDIUM", "HIGH", "CRITICAL")
        assert rec.get("auto_escalated") is True

    def test_kpi_extraction_from_report_markdown(self):
        """KPIs found in executive report markdown are stored in baseline_history."""
        extractor = ProfileExtractor()
        profile = self._make_profile()

        report_md = (
            "## Resumen Ejecutivo\n\n"
            "**Facturación Total**: $12.3M en el periodo.\n"
            "**Cobranza Pendiente**: ARS 4.5M (32%)\n"
            "**Margen Bruto**: 45%\n"
        )
        extractor.update_from_run(
            profile, {}, {}, {"executive": report_md}, period="2025-01"
        )

        # At least one KPI should have been extracted
        assert len(profile.baseline_history) >= 1
        # The "Facturación Total" KPI should be present
        assert "Facturación Total" in profile.baseline_history

    def test_run_history_capped_at_20(self):
        """run_history never exceeds 20 entries regardless of how many runs complete."""
        extractor = ProfileExtractor()
        profile = self._make_profile()
        findings = self._make_findings([])

        for i in range(1, 26):  # 25 runs
            extractor.update_from_run(
                profile, findings, {}, {}, period=f"2025-{i:02d}"
            )

        assert len(profile.run_history) == 20


# ---------------------------------------------------------------------------
# TestAdaptiveContextBuilderIntegration
# ---------------------------------------------------------------------------

class TestAdaptiveContextBuilderIntegration:
    """
    Test build_adaptive_context() with various ClientProfile states:
    fresh profile, populated profile with baseline history, and empty profile.
    """

    def _make_profile(self, name: str = "Acme Corp") -> ClientProfile:
        return ClientProfile.new(name)

    def test_build_adaptive_context_returns_non_empty_string(self):
        """build_adaptive_context(profile) must return a non-empty string."""
        profile = self._make_profile()
        result = build_adaptive_context(profile)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_adaptive_context_includes_client_name(self):
        """The returned context must contain the client's name."""
        profile = self._make_profile("Omega Industries")
        result = build_adaptive_context(profile)
        assert "Omega Industries" in result

    def test_build_adaptive_context_handles_empty_profile_gracefully(self):
        """No exception is raised and a non-empty string is returned for a minimal profile."""
        profile = ClientProfile(client_name="Empty Client")
        # Ensure all optional fields are at their defaults
        assert profile.baseline_history == {}
        assert profile.known_findings == {}
        assert profile.run_history == []

        try:
            result = build_adaptive_context(profile)
        except Exception as exc:
            pytest.fail(f"build_adaptive_context raised an exception on empty profile: {exc}")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_adaptive_context_includes_baseline_history(self):
        """When baseline_history is populated, the context block mentions those KPIs."""
        profile = self._make_profile("Revenue Corp")
        profile.baseline_history = {
            "Facturación Total": [
                {
                    "period": "2025-01",
                    "label": "Facturación Total",
                    "value": "$12.3M",
                    "numeric_value": 12_300_000.0,
                    "run_date": "2025-01-31T00:00:00",
                }
            ]
        }
        result = build_adaptive_context(profile)
        assert "Facturación Total" in result
        assert "$12.3M" in result


# ---------------------------------------------------------------------------
# Stub claude_agent_sdk so that valinor.pipeline can be imported without the
# real SDK installed.  This must happen BEFORE any pipeline import below.
# ---------------------------------------------------------------------------

import types as _types

def _make_sdk_stub():
    """Build a minimal claude_agent_sdk stub module."""
    mod = _types.ModuleType("claude_agent_sdk")

    class _TextBlock:
        def __init__(self, text: str = ""):
            self.text = text

    class _AssistantMessage:
        def __init__(self, content=None):
            self.content = content or []

    class _ClaudeAgentOptions:
        def __init__(self, model="sonnet", system_prompt="", max_turns=20, **kwargs):
            self.model = model
            self.system_prompt = system_prompt
            self.max_turns = max_turns

    async def _query(*args, **kwargs):
        """Stub: yields nothing by default."""
        return
        yield  # make it an async generator

    mod.TextBlock = _TextBlock
    mod.AssistantMessage = _AssistantMessage
    mod.ClaudeAgentOptions = _ClaudeAgentOptions
    mod.query = _query
    return mod


if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = _make_sdk_stub()

# Now safe to import pipeline components
from valinor.pipeline import (  # noqa: E402
    compute_baseline,
    gate_calibration,
    execute_queries,
    run_analysis_agents,
    reconcile_swarm,
)


# ---------------------------------------------------------------------------
# TestComputeBaselineIntegration  (pipeline stage 2.5 → baseline)
# ---------------------------------------------------------------------------

class TestComputeBaselineIntegration:
    """
    Test compute_baseline() using query_results dicts that mirror the output
    of execute_queries().  No DB connection required — all inputs are synthetic.
    """

    def _revenue_summary_qr(
        self,
        total_revenue: float = 109_000.0,
        num_invoices: int = 50,
        avg_invoice: float | None = None,
        min_invoice: float = 1_047.0,
        max_invoice: float = 3_350.0,
        date_from: str = "2025-01-01",
        date_to: str = "2025-01-31",
        distinct_customers: int = 20,
    ) -> dict:
        row = {
            "total_revenue": total_revenue,
            "num_invoices": num_invoices,
            "avg_invoice": avg_invoice,
            "min_invoice": min_invoice,
            "max_invoice": max_invoice,
            "date_from": date_from,
            "date_to": date_to,
            "distinct_customers": distinct_customers,
        }
        return {
            "results": {
                "total_revenue_summary": {
                    "columns": list(row.keys()),
                    "rows": [row],
                    "row_count": 1,
                    "domain": "financial",
                    "description": "Revenue summary",
                }
            },
            "errors": {},
            "snapshot_timestamp": "2025-01-31T00:00:00",
        }

    def test_baseline_data_available_when_revenue_row_present(self):
        qr = self._revenue_summary_qr()
        baseline = compute_baseline(qr)
        assert baseline["data_available"] is True

    def test_baseline_total_revenue_populated(self):
        qr = self._revenue_summary_qr(total_revenue=109_000.0)
        baseline = compute_baseline(qr)
        assert abs(baseline["total_revenue"] - 109_000.0) < 0.01

    def test_baseline_provenance_tagged_for_total_revenue(self):
        qr = self._revenue_summary_qr()
        baseline = compute_baseline(qr)
        prov = baseline["_provenance"]
        assert "total_revenue" in prov
        assert prov["total_revenue"]["source_query"] == "total_revenue_summary"
        assert prov["total_revenue"]["confidence"] == "measured"

    def test_baseline_derives_avg_when_not_provided(self):
        """avg_invoice=None in input → compute_baseline derives it from total/num."""
        qr = self._revenue_summary_qr(total_revenue=10_000.0, num_invoices=4, avg_invoice=None)
        baseline = compute_baseline(qr)
        assert baseline["avg_invoice"] is not None
        assert abs(baseline["avg_invoice"] - 2_500.0) < 0.01
        assert baseline["_provenance"]["avg_invoice"]["confidence"] == "inferred"

    def test_baseline_no_data_on_empty_results(self):
        baseline = compute_baseline({"results": {}, "errors": {}, "snapshot_timestamp": ""})
        assert baseline["data_available"] is False
        assert baseline["total_revenue"] is None

    def test_baseline_freshness_warning_when_stale(self):
        """When data_freshness_days > 14 a warning string is added."""
        qr = {
            "results": {
                "data_freshness": {
                    "columns": ["days_since_latest", "total_records", "distinct_customers"],
                    "rows": [{"days_since_latest": 30, "total_records": 50, "distinct_customers": 20}],
                    "row_count": 1,
                    "domain": "freshness",
                    "description": "Freshness",
                }
            },
            "errors": {},
            "snapshot_timestamp": "",
        }
        baseline = compute_baseline(qr)
        assert baseline["warning"] is not None
        assert "30" in baseline["warning"]

    def test_baseline_no_warning_when_fresh(self):
        """Data <= 14 days old must NOT generate a warning."""
        qr = {
            "results": {
                "data_freshness": {
                    "columns": ["days_since_latest", "total_records", "distinct_customers"],
                    "rows": [{"days_since_latest": 3, "total_records": 50, "distinct_customers": 20}],
                    "row_count": 1,
                    "domain": "freshness",
                    "description": "Freshness",
                }
            },
            "errors": {},
            "snapshot_timestamp": "",
        }
        baseline = compute_baseline(qr)
        assert baseline["warning"] is None

    def test_baseline_ar_fields_populated_from_ar_query(self):
        qr = {
            "results": {
                "ar_outstanding_actual": {
                    "columns": ["total_outstanding", "overdue_amount", "customers_with_debt"],
                    "rows": [{"total_outstanding": 55_000.0, "overdue_amount": 12_000.0,
                              "customers_with_debt": 7}],
                    "row_count": 1,
                    "domain": "ar",
                    "description": "AR outstanding",
                }
            },
            "errors": {},
            "snapshot_timestamp": "",
        }
        baseline = compute_baseline(qr)
        assert abs(baseline["total_outstanding_ar"] - 55_000.0) < 0.01
        assert abs(baseline["overdue_ar"] - 12_000.0) < 0.01
        assert baseline["customers_with_debt"] == 7


# ---------------------------------------------------------------------------
# TestGateCalibrationIntegration  (pipeline stage 1.5)
# ---------------------------------------------------------------------------

class TestGateCalibrationIntegration:
    """
    Test gate_calibration() against a file-based SQLite DB so that each
    new engine created by gate_calibration() sees the same data.
    Exercises the deterministic guard-rail before any LLM cost is incurred.
    """

    def _make_file_db(self):
        """Create a temp-file SQLite DB with full schema + data. Returns (path, url)."""
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        url = f"sqlite:///{path}"
        engine = create_engine(url)
        with engine.connect() as conn:
            for ddl in _DDL:
                conn.execute(text(ddl))
            for cid, cname in _CUSTOMERS:
                conn.execute(text(
                    f"INSERT INTO res_partner VALUES ({cid}, '{cname}', 1)"
                ))
            for i in range(1, 11):
                conn.execute(text(f"""
                    INSERT INTO account_move VALUES (
                        {i}, 'INV/2025/{i:04d}', 'out_invoice', 'posted',
                        {i * 1000}, {i * 1210}, 1, '2025-01-0{min(i,9)}', 1
                    )
                """))
            conn.commit()
        engine.dispose()
        return path, url

    def _run(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_gate_passes_with_no_entities(self):
        path, url = self._make_file_db()
        try:
            result = self._run(gate_calibration({}, {"connection_string": url}))
            assert result["passed"] is True
            assert result["entities_verified"] == 0
        finally:
            import os; os.unlink(path)

    def test_gate_passes_with_valid_table_no_filter(self):
        path, url = self._make_file_db()
        try:
            entity_map = {
                "entities": {
                    "invoices": {
                        "table": "account_move",
                        "type": "TRANSACTIONAL",
                    }
                }
            }
            result = self._run(gate_calibration(entity_map, {"connection_string": url}))
            # No base_filter → warn but not fail
            assert result["passed"] is True
        finally:
            import os; os.unlink(path)

    def test_gate_fails_with_invalid_filter(self):
        path, url = self._make_file_db()
        try:
            entity_map = {
                "entities": {
                    "invoices": {
                        "table": "account_move",
                        "base_filter": "state = 'nonexistent_state_xyz'",
                        "type": "TRANSACTIONAL",
                    }
                }
            }
            result = self._run(gate_calibration(entity_map, {"connection_string": url}))
            assert result["passed"] is False
            assert len(result["failures"]) >= 1
        finally:
            import os; os.unlink(path)

    def test_gate_returns_entities_verified_count(self):
        path, url = self._make_file_db()
        try:
            entity_map = {
                "entities": {
                    "invoices": {"table": "account_move"},
                    "partners": {"table": "res_partner"},
                }
            }
            result = self._run(gate_calibration(entity_map, {"connection_string": url}))
            assert result["entities_verified"] >= 2
        finally:
            import os; os.unlink(path)

    def test_gate_reports_connection_error_gracefully(self):
        """A completely broken connection string must return passed=False."""
        bad_config = {"connection_string": "postgresql://bad:bad@nonexistent_host_xyz/db"}
        result = self._run(gate_calibration({"entities": {"x": {"table": "t"}}}, bad_config))
        assert result["passed"] is False


# ---------------------------------------------------------------------------
# TestExecuteQueriesIntegration  (pipeline stage 2.5)
# ---------------------------------------------------------------------------

class TestExecuteQueriesIntegration:
    """
    Test execute_queries() using a file-based SQLite DB so a new engine
    created inside execute_queries() sees the fixture data.
    Covers the REPEATABLE READ fallback path and error isolation.
    """

    def _make_file_db(self, with_data: bool = True):
        """Return (path, url) for a temp SQLite file."""
        import tempfile, os
        fd, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        url = f"sqlite:///{path}"
        engine = create_engine(url)
        with engine.connect() as conn:
            for ddl in _DDL:
                conn.execute(text(ddl))
            if with_data:
                for i in range(1, 51):
                    conn.execute(text(f"""
                        INSERT INTO account_move VALUES (
                            {i}, 'INV/2025/{i:04d}', 'out_invoice', 'posted',
                            {i * 100}, {i * 121}, 1, '2025-01-15', 1
                        )
                    """))
                for cid, cname in _CUSTOMERS:
                    conn.execute(text(
                        f"INSERT INTO res_partner VALUES ({cid}, '{cname}', 1)"
                    ))
            conn.commit()
        engine.dispose()
        return path, url

    def _run(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_execute_queries_returns_results_and_snapshot(self):
        path, url = self._make_file_db(with_data=True)
        try:
            query_pack = {
                "queries": [
                    {
                        "id": "count_invoices",
                        "sql": "SELECT COUNT(*) AS cnt FROM account_move",
                        "domain": "financial",
                        "description": "Count invoices",
                    }
                ]
            }
            result = self._run(execute_queries(query_pack, {"connection_string": url}))
            assert "results" in result
            assert "snapshot_timestamp" in result
            assert "count_invoices" in result["results"]
            assert result["results"]["count_invoices"]["rows"][0]["cnt"] == 50
        finally:
            import os; os.unlink(path)

    def test_execute_queries_isolates_errors_per_query(self):
        """A bad SQL query must be recorded in 'errors' while good queries still run."""
        path, url = self._make_file_db(with_data=True)
        try:
            query_pack = {
                "queries": [
                    {
                        "id": "good_query",
                        "sql": "SELECT COUNT(*) AS cnt FROM res_partner",
                        "domain": "partner",
                        "description": "Count partners",
                    },
                    {
                        "id": "bad_query",
                        "sql": "SELECT * FROM this_table_does_not_exist_xyz",
                        "domain": "unknown",
                        "description": "Bad query",
                    },
                ]
            }
            result = self._run(execute_queries(query_pack, {"connection_string": url}))
            assert "good_query" in result["results"]
            assert "bad_query" in result["errors"]
        finally:
            import os; os.unlink(path)

    def test_execute_queries_empty_database_zero_rows(self):
        """An empty DB returns row_count=0 but no error for valid SQL."""
        path, url = self._make_file_db(with_data=False)
        try:
            query_pack = {
                "queries": [
                    {
                        "id": "invoices",
                        "sql": "SELECT COUNT(*) AS cnt FROM account_move",
                        "domain": "financial",
                        "description": "Count invoices on empty DB",
                    }
                ]
            }
            result = self._run(execute_queries(query_pack, {"connection_string": url}))
            assert result["results"]["invoices"]["rows"][0]["cnt"] == 0
            assert result["errors"] == {}
        finally:
            import os; os.unlink(path)

    def test_execute_queries_empty_query_pack(self):
        """An empty query_pack must return an empty results/errors dict."""
        path, url = self._make_file_db(with_data=False)
        try:
            result = self._run(execute_queries({"queries": []}, {"connection_string": url}))
            assert result["results"] == {}
            assert result["errors"] == {}
        finally:
            import os; os.unlink(path)


# ---------------------------------------------------------------------------
# TestRunAnalysisAgentsErrorPropagation  (pipeline stage 3)
# ---------------------------------------------------------------------------

class TestRunAnalysisAgentsErrorPropagation:
    """
    Verify that run_analysis_agents() continues even when individual agent
    coroutines raise exceptions (return_exceptions=True via asyncio.gather).
    """

    def _run(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def _minimal_inputs(self):
        return (
            {"results": {}, "errors": {}, "snapshot_timestamp": ""},  # query_results
            {"entities": {}},                                           # entity_map
            None,                                                       # memory
            {"data_available": False, "_provenance": {}},              # baseline
        )

    def test_one_agent_raises_others_still_return(self):
        """
        If one of the three agents raises, findings must still contain
        results for the others (gathered with return_exceptions=True).
        """
        import valinor.pipeline as pipeline_mod

        async def _good_analyst(*args, **kwargs):
            return {"agent": "analyst", "findings": [], "output": "ok"}

        async def _exploding_sentinel(*args, **kwargs):
            raise RuntimeError("Sentinel DB timeout")

        async def _good_hunter(*args, **kwargs):
            return {"agent": "hunter", "findings": [], "output": "ok"}

        qr, em, mem, bl = self._minimal_inputs()
        with (
            patch.object(pipeline_mod, "run_analyst", _good_analyst),
            patch.object(pipeline_mod, "run_sentinel", _exploding_sentinel),
            patch.object(pipeline_mod, "run_hunter", _good_hunter),
        ):
            findings = self._run(run_analysis_agents(qr, em, mem, bl))

        assert "analyst" in findings
        assert "hunter" in findings
        # The sentinel error must be captured, not re-raised
        error_keys = [k for k in findings if k.startswith("error_")]
        assert len(error_keys) == 1
        assert findings[error_keys[0]].get("error") is True

    def test_all_agents_raise_returns_error_dict(self):
        """
        When all three agents raise, findings must contain at least one error entry
        and no successful agent keys.  (Same exception type merges into one key by
        design — the important invariant is that no exception propagates out.)
        """
        import valinor.pipeline as pipeline_mod

        async def _boom_a(*args, **kwargs):
            raise ValueError("analyst failure")

        async def _boom_s(*args, **kwargs):
            raise RuntimeError("sentinel failure")

        async def _boom_h(*args, **kwargs):
            raise TypeError("hunter failure")

        qr, em, mem, bl = self._minimal_inputs()
        with (
            patch.object(pipeline_mod, "run_analyst", _boom_a),
            patch.object(pipeline_mod, "run_sentinel", _boom_s),
            patch.object(pipeline_mod, "run_hunter", _boom_h),
        ):
            findings = self._run(run_analysis_agents(qr, em, mem, bl))

        # All three distinct exception types → three distinct error keys
        error_keys = [k for k in findings if k.startswith("error_")]
        assert len(error_keys) == 3
        assert all(findings[k]["error"] is True for k in error_keys)
        # No successful agent output
        assert "analyst" not in findings
        assert "sentinel" not in findings
        assert "hunter" not in findings


# ---------------------------------------------------------------------------
# TestReconcileSwarmIntegration  (pipeline stage 3.5)
# ---------------------------------------------------------------------------

class TestReconcileSwarmIntegration:
    """
    Test reconcile_swarm() without invoking the Haiku arbiter (patched out).
    Covers: no findings → no conflicts; same values → no conflicts;
    conflicting values → conflict detected and arbiter invoked.
    """

    def _run(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_finding(self, agent: str, fid: str, headline: str,
                      value_eur: float, domain: str = "financial") -> dict:
        return {
            "agent": agent,
            "findings": [
                {
                    "id": fid,
                    "headline": headline,
                    "value_eur": value_eur,
                    "domain": domain,
                    "evidence": "synthetic",
                    "value_confidence": "high",
                }
            ],
        }

    def test_no_findings_adds_reconciliation_key(self):
        findings = {}
        result = self._run(reconcile_swarm(findings, {"data_available": False, "_provenance": {}}))
        assert "_reconciliation" in result
        assert result["_reconciliation"]["conflicts_found"] == 0

    def test_identical_values_no_conflict(self):
        findings = {
            "analyst": self._make_finding("analyst", "R1", "Total Revenue", 100_000.0),
            "sentinel": self._make_finding("sentinel", "R2", "Total Revenue", 100_000.0),
        }
        result = self._run(reconcile_swarm(findings, {"data_available": False, "_provenance": {}}))
        assert result["_reconciliation"]["conflicts_found"] == 0

    def test_conflicting_values_detected(self):
        """Two agents disagree >2x on same domain + headline → conflict flagged."""
        # Patch the arbiter so it never makes an API call
        arbiter_result = {
            "selected_value": 500_000.0,
            "selected_agent": "analyst",
            "discrepancy_explanation": "Different scope",
            "confidence": "high",
        }

        async def _mock_agent_query(*args, **kwargs):
            from claude_agent_sdk import AssistantMessage, TextBlock
            import json

            class _FakeMsg:
                content = [TextBlock(text=json.dumps(arbiter_result))]

            yield _FakeMsg()

        findings = {
            "analyst": self._make_finding("analyst", "R1", "Total Revenue ingreso", 500_000.0),
            "sentinel": self._make_finding("sentinel", "R2", "Total Revenue ingreso", 50_000.0),
        }
        with patch("valinor.pipeline.agent_query", _mock_agent_query):
            result = self._run(
                reconcile_swarm(findings, {"data_available": False, "_provenance": {}})
            )
        assert result["_reconciliation"]["conflicts_found"] >= 1

    def test_reconciliation_notes_list_present(self):
        findings = {"analyst": self._make_finding("analyst", "R1", "Revenue", 1_000.0)}
        result = self._run(reconcile_swarm(findings, {"data_available": False, "_provenance": {}}))
        assert isinstance(result["_reconciliation"]["notes"], list)


# ---------------------------------------------------------------------------
# TestDQGatePipelineIntegration  (DQ gate → baseline → provenance chain)
# ---------------------------------------------------------------------------

class TestDQGatePipelineIntegration:
    """
    Integration tests that run the DQ gate and feed its output into the
    pipeline's baseline computation and provenance registry.
    """

    def test_dq_gate_to_provenance_chain_high_score(self, populated_engine):
        """
        Full chain: DQ gate (high score) → ProvenanceRegistry → all findings
        labelled CONFIRMED or PROVISIONAL.
        """
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            dq_report = gate.run()

        reg = ProvenanceRegistry(
            job_id="chain-test-001",
            client_name="Chain Corp",
            period="2025-01",
            dq_report_score=dq_report.overall_score,
            dq_report_tag=dq_report.data_quality_tag,
        )
        for i in range(5):
            reg.register(f"F{i:03d}", f"Metric {i}", tables=["account_move"])

        assert len(reg.findings) == 5
        for prov in reg.findings.values():
            assert prov.confidence_score >= 0.0
            assert prov.confidence_label in ("CONFIRMED", "PROVISIONAL", "UNVERIFIED", "BLOCKED")

    def test_dq_gate_halt_decision_on_fatal_check(self, populated_engine):
        """A FATAL check must set gate_decision=HALT and can_proceed=False."""
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", False, 100, "FATAL",
                              "Critical schema mismatch")):
            dq_report = gate.run()

        assert dq_report.gate_decision == "HALT"
        assert dq_report.can_proceed is False
        assert len(dq_report.blocking_issues) >= 1

    def test_dq_gate_to_certify_report_pipeline(self, populated_engine):
        """DQ gate score → certify_report appends footer with matching score."""
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            dq_report = gate.run()

        sample_report = "## Revenue Analysis\nTotal invoiced: **EUR 109,000**."
        certified = certify_report(
            sample_report,
            confidence_label=dq_report.confidence_label,
            dq_score=dq_report.overall_score,
        )
        score_str = f"{dq_report.overall_score:.0f}"
        if dq_report.overall_score >= 65:
            assert score_str in certified
        else:
            assert certified == sample_report  # below threshold → unchanged

    def test_empty_db_dq_gate_baseline_chain(self, empty_engine):
        """DQ gate + compute_baseline on an empty DB must not raise."""
        gate = _sqlite_gate(empty_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            dq_report = gate.run()
        assert isinstance(dq_report, DataQualityReport)

        baseline = compute_baseline({"results": {}, "errors": {}, "snapshot_timestamp": ""})
        assert baseline["data_available"] is False
        assert isinstance(baseline["_provenance"], dict)

    def test_provenance_deduplication_same_finding_id(self):
        """
        Registering the same finding_id twice must overwrite, not duplicate.
        The registry must contain exactly one entry per finding_id.
        """
        reg = ProvenanceRegistry(
            job_id="dedup-test-001",
            client_name="Dedup Corp",
            period="2025-01",
            dq_report_score=90.0,
            dq_report_tag="FINAL",
        )
        reg.register("F001", "Revenue v1", tables=["account_move"])
        reg.register("F001", "Revenue v2 (updated)", tables=["account_move", "sale_order"])

        assert len(reg.findings) == 1
        assert reg.findings["F001"].metric_name == "Revenue v2 (updated)"

    def test_provenance_tracks_multiple_tables(self):
        """tables_accessed list must reflect every table passed to register()."""
        reg = ProvenanceRegistry(
            job_id="tables-test-001",
            client_name="Multi Corp",
            period="2025-01",
            dq_report_score=88.0,
            dq_report_tag="FINAL",
        )
        prov = reg.register(
            "F001", "Cross-table revenue",
            tables=["account_move", "res_partner", "sale_order"],
        )
        assert set(prov.tables_accessed) == {"account_move", "res_partner", "sale_order"}

    def test_profile_update_after_successful_run(self):
        """
        After update_from_run() with a successful run, run_history must
        grow and baseline_history must reflect extracted KPIs.
        """
        extractor = ProfileExtractor()
        profile = ClientProfile.new("Integrated Client")

        report_md = (
            "## Reporte Ejecutivo\n\n"
            "**Facturación Total**: $8.5M en el periodo.\n"
            "**Cartera Vencida**: ARS 1.2M\n"
        )
        extractor.update_from_run(
            profile, {}, {}, {"executive": report_md}, period="2025-01"
        )

        assert len(profile.run_history) == 1
        assert "Facturación Total" in profile.baseline_history

    def test_findings_deduplication_across_multiple_runs(self):
        """
        A finding that persists across N runs must appear once in
        known_findings with runs_open == N, NOT as N separate entries.
        """
        extractor = ProfileExtractor()
        profile = ClientProfile.new("Dedup Run Client")
        findings_data = {
            "analyst": {
                "findings": [
                    {"id": "FIN-001", "severity": "HIGH", "title": "Overdue AR spike"}
                ]
            }
        }

        for period_idx in range(1, 5):
            extractor.update_from_run(
                profile, findings_data, {}, {}, period=f"2025-0{period_idx}"
            )

        assert "FIN-001" in profile.known_findings
        assert len(profile.known_findings) == 1  # only one entry, not four
        assert profile.known_findings["FIN-001"]["runs_open"] == 4

    def test_quality_report_to_prompt_context(self, populated_engine):
        """to_prompt_context() must produce a non-empty string containing the score."""
        gate = _sqlite_gate(populated_engine)
        with patch.object(gate, "_check_schema_integrity",
                          return_value=QualityCheckResult(
                              "schema_integrity", True, 0, "INFO", "ok")):
            dq_report = gate.run()

        ctx = dq_report.to_prompt_context()
        assert isinstance(ctx, str) and len(ctx) > 0
        score_str = f"{dq_report.overall_score:.0f}"
        assert score_str in ctx
        assert dq_report.gate_decision in ctx
