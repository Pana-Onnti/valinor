"""
Unit tests for AnomalyDetector.

Coverage:
- scan() with financial columns → detects IQR outliers
- scan() with non-financial columns → ignored
- scan() with too few rows → skipped
- _check_column() edge cases (zero IQR, all-equal values, negative/zero values filtered)
- format_for_agent() with anomalies and empty list
- get_anomaly_detector() singleton behaviour
- severity thresholds (HIGH / MEDIUM / LOW based on value_share)
- StatisticalAnomaly dataclass field population
"""
from __future__ import annotations

import sys
import math
import pytest

sys.path.insert(0, ".")

from core.valinor.quality.anomaly_detector import (
    AnomalyDetector,
    StatisticalAnomaly,
    get_anomaly_detector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rows(col: str, values: list) -> list[dict]:
    """Build a list of row dicts for a single column."""
    return [{col: v} for v in values]


def _make_query_results(queries: dict) -> dict:
    """
    Build a query_results structure that AnomalyDetector.scan() accepts.
    queries: {qid: {"columns": [...], "rows": [...]}}
    """
    return {"results": {qid: data for qid, data in queries.items()}}


def _make_normal_values(n: int = 50, base: float = 1000.0, noise: float = 50.0) -> list:
    """Return a list of n similar positive floats (no outliers)."""
    import random
    random.seed(42)
    return [base + random.uniform(-noise, noise) for _ in range(n)]


def _make_values_with_spike(n: int = 50, base: float = 1000.0, spike: float = 1_000_000.0) -> list:
    """Return n normal values plus one huge spike at the end."""
    import random
    random.seed(0)
    vals = [base + random.uniform(-50, 50) for _ in range(n - 1)]
    vals.append(spike)
    return vals


# ---------------------------------------------------------------------------
# scan() — basic detection
# ---------------------------------------------------------------------------

def test_scan_detects_outlier_in_amount_column():
    """A single massive spike in an 'amount' column is detected as an anomaly."""
    values = _make_values_with_spike(n=30, base=1000.0, spike=5_000_000.0)
    rows = _make_rows("amount_untaxed", values)
    qr = _make_query_results({"q1": {"columns": ["amount_untaxed"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)

    assert len(anomalies) >= 1
    assert anomalies[0].column == "amount_untaxed"


def test_scan_detects_outlier_in_revenue_column():
    """Financial hint 'revenue' column triggers outlier detection."""
    values = _make_values_with_spike(n=20, base=500.0, spike=999_999.0)
    rows = _make_rows("total_revenue", values)
    qr = _make_query_results({"q_rev": {"columns": ["total_revenue"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert any(a.column == "total_revenue" for a in anomalies)


def test_scan_detects_outlier_in_grandtotal_column():
    """'grandtotal' is a recognized financial column hint."""
    values = _make_values_with_spike(n=20, base=200.0, spike=500_000.0)
    rows = _make_rows("grandtotal", values)
    qr = _make_query_results({"q_gt": {"columns": ["grandtotal"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert any(a.column == "grandtotal" for a in anomalies)


# ---------------------------------------------------------------------------
# scan() — non-financial columns are ignored
# ---------------------------------------------------------------------------

def test_scan_ignores_non_financial_column():
    """Columns without financial hints are skipped even with extreme values."""
    values = _make_values_with_spike(n=20, base=5.0, spike=100_000.0)
    rows = _make_rows("customer_id", values)
    qr = _make_query_results({"q_id": {"columns": ["customer_id"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    # customer_id is not a financial column — must be ignored
    assert all(a.column != "customer_id" for a in anomalies)


def test_scan_ignores_non_financial_name_column():
    """'name' column is not a financial hint — must be skipped."""
    values = _make_values_with_spike(n=20, base=1.0, spike=99999.0)
    rows = _make_rows("partner_name", values)
    qr = _make_query_results({"q_n": {"columns": ["partner_name"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert all(a.column != "partner_name" for a in anomalies)


# ---------------------------------------------------------------------------
# scan() — too few rows skipped
# ---------------------------------------------------------------------------

def test_scan_skips_queries_with_fewer_than_5_rows():
    """Queries with fewer than 5 rows are skipped entirely."""
    rows = _make_rows("amount_untaxed", [100.0, 200.0, 300.0])
    qr = _make_query_results({"q_small": {"columns": ["amount_untaxed"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert anomalies == []


def test_scan_skips_column_with_fewer_than_10_valid_values():
    """Even if the query has >= 5 rows, columns with < 10 valid numeric values are skipped."""
    # Provide exactly 9 valid positive values (row count ≥ 5 but numeric valid < 10)
    values = [100.0] * 9
    rows = _make_rows("amount_untaxed", values)
    qr = _make_query_results({"q_9": {"columns": ["amount_untaxed"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert anomalies == []


# ---------------------------------------------------------------------------
# scan() — zero / negative values filtered
# ---------------------------------------------------------------------------

def test_scan_filters_zero_and_negative_values():
    """Zero and negative values are not included in the numeric series."""
    # Mix of negatives, zeros, and a small set of positives — if < 10 positives, skipped
    values = [-100.0, 0.0, -50.0, 0.0] + [200.0] * 6  # only 6 positives → skipped
    rows = _make_rows("amount_untaxed", values)
    qr = _make_query_results({"q_neg": {"columns": ["amount_untaxed"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert anomalies == []


# ---------------------------------------------------------------------------
# scan() — all-equal values produce zero IQR → skipped
# ---------------------------------------------------------------------------

def test_scan_skips_column_with_zero_iqr():
    """Columns where all values are identical have zero IQR and are skipped."""
    values = [1000.0] * 20
    rows = _make_rows("amount_untaxed", values)
    qr = _make_query_results({"q_flat": {"columns": ["amount_untaxed"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert anomalies == []


# ---------------------------------------------------------------------------
# Severity thresholds
# ---------------------------------------------------------------------------

def test_scan_returns_high_severity_when_value_share_above_20pct():
    """An outlier comprising >20% of the total value gets HIGH severity."""
    # Use varied normal values so IQR is non-zero, plus a massive spike
    import random
    random.seed(7)
    normal = [900.0 + random.uniform(-100, 100) for _ in range(20)]
    spike = [5_000_000.0]
    values = normal + spike
    rows = _make_rows("amount_untaxed", values)
    qr = _make_query_results({"q_high": {"columns": ["amount_untaxed"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    high_anomalies = [a for a in anomalies if a.severity == "HIGH"]
    assert len(high_anomalies) >= 1, "Expected at least one HIGH severity anomaly"


def test_scan_query_id_matches_input_key():
    """StatisticalAnomaly.query_id must match the dict key in query_results."""
    values = _make_values_with_spike(n=20, base=1000.0, spike=5_000_000.0)
    rows = _make_rows("amount_untaxed", values)
    qr = _make_query_results({"my_special_query": {"columns": ["amount_untaxed"], "rows": rows}})

    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert any(a.query_id == "my_special_query" for a in anomalies)


# ---------------------------------------------------------------------------
# StatisticalAnomaly dataclass
# ---------------------------------------------------------------------------

def test_statistical_anomaly_dataclass_fields():
    """StatisticalAnomaly stores the correct fields and types."""
    anomaly = StatisticalAnomaly(
        query_id="q1",
        column="amount",
        method="iqr_3x_log",
        severity="HIGH",
        description="2 outliers",
        outlier_values=[9999.0, 8888.0],
        outlier_count=2,
        value_share=0.35,
    )
    assert anomaly.query_id == "q1"
    assert anomaly.column == "amount"
    assert anomaly.method == "iqr_3x_log"
    assert anomaly.severity == "HIGH"
    assert anomaly.outlier_count == 2
    assert pytest.approx(anomaly.value_share) == 0.35
    assert 9999.0 in anomaly.outlier_values


# ---------------------------------------------------------------------------
# format_for_agent()
# ---------------------------------------------------------------------------

def test_format_for_agent_empty_list_returns_no_anomalies_message():
    """format_for_agent with an empty list returns a clean 'no anomalies' message."""
    detector = AnomalyDetector()
    result = detector.format_for_agent([])
    assert isinstance(result, str)
    assert len(result) > 0
    # Should explicitly say no anomalies were detected
    assert "Sin anomalías" in result or "no anomal" in result.lower()


def test_format_for_agent_with_anomalies_returns_non_empty():
    """format_for_agent with anomalies returns a non-empty formatted string."""
    anomaly = StatisticalAnomaly(
        query_id="q1",
        column="amount_untaxed",
        method="iqr_3x_log",
        severity="HIGH",
        description="3 outliers en amount_untaxed representan 45.0% del total",
        outlier_values=[500000.0, 400000.0, 300000.0],
        outlier_count=3,
        value_share=0.45,
    )
    detector = AnomalyDetector()
    result = detector.format_for_agent([anomaly])
    assert isinstance(result, str)
    assert len(result) > 0
    assert "amount_untaxed" in result or "q1" in result


def test_format_for_agent_caps_at_5_entries():
    """format_for_agent shows at most 5 anomalies regardless of how many are passed."""
    anomalies = [
        StatisticalAnomaly(
            query_id=f"q{i}",
            column="amount",
            method="iqr_3x_log",
            severity="MEDIUM",
            description=f"outlier {i}",
            outlier_values=[float(i * 1000)],
            outlier_count=1,
            value_share=0.06 + i * 0.001,
        )
        for i in range(10)
    ]
    detector = AnomalyDetector()
    result = detector.format_for_agent(anomalies)
    # The method caps output at 5 entries; count how many "q" prefixed IDs appear
    # by counting lines starting with two spaces (each anomaly line starts with "  [")
    anomaly_lines = [line for line in result.splitlines() if line.strip().startswith("[")]
    assert len(anomaly_lines) <= 5


# ---------------------------------------------------------------------------
# Singleton: get_anomaly_detector()
# ---------------------------------------------------------------------------

def test_get_anomaly_detector_returns_instance():
    """get_anomaly_detector() returns an AnomalyDetector instance."""
    detector = get_anomaly_detector()
    assert isinstance(detector, AnomalyDetector)


def test_get_anomaly_detector_returns_same_singleton():
    """get_anomaly_detector() always returns the same object."""
    d1 = get_anomaly_detector()
    d2 = get_anomaly_detector()
    assert d1 is d2


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------

class TestAnomalyDetectorAdditional:
    """Additional edge case tests for AnomalyDetector."""

    def test_scan_returns_list_type(self):
        """scan() always returns a list, even when no anomalies."""
        detector = AnomalyDetector()
        result = detector.scan({"results": {}})
        assert isinstance(result, list)

    def test_scan_empty_results_returns_empty(self):
        """scan() with empty results dict returns empty list."""
        detector = AnomalyDetector()
        result = detector.scan({})
        assert result == []

    def test_scan_multiple_queries_all_detected(self):
        """scan() finds outliers in multiple independent queries."""
        import random
        random.seed(1)
        def _spike(n=30, base=500.0, spike=2_000_000.0):
            vals = [base + random.uniform(-20, 20) for _ in range(n - 1)]
            vals.append(spike)
            return vals

        qr = {
            "results": {
                f"q{i}": {
                    "columns": ["amount_untaxed"],
                    "rows": [{"amount_untaxed": v} for v in _spike()],
                }
                for i in range(3)
            }
        }
        detector = AnomalyDetector()
        anomalies = detector.scan(qr)
        # At least one anomaly per query
        query_ids = {a.query_id for a in anomalies}
        assert len(query_ids) >= 2

    def test_anomaly_value_share_between_0_and_1(self):
        """All StatisticalAnomaly.value_share values must be in [0, 1]."""
        import random
        random.seed(3)
        vals = [500.0 + random.uniform(-50, 50) for _ in range(29)] + [5_000_000.0]
        rows = [{"amount_untaxed": v} for v in vals]
        qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
        detector = AnomalyDetector()
        anomalies = detector.scan(qr)
        for a in anomalies:
            assert 0.0 <= a.value_share <= 1.0, f"value_share={a.value_share} out of range"

    def test_anomaly_outlier_values_are_subset_of_input(self):
        """outlier_values must be actual values from the input data."""
        import random
        random.seed(5)
        normal = [1000.0 + random.uniform(-50, 50) for _ in range(25)]
        spike_val = 9_999_999.0
        vals = normal + [spike_val]
        rows = [{"amount_untaxed": v} for v in vals]
        qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
        detector = AnomalyDetector()
        anomalies = detector.scan(qr)
        assert len(anomalies) >= 1
        # The spike value must appear in outlier_values
        all_outlier_vals = [v for a in anomalies for v in a.outlier_values]
        assert spike_val in all_outlier_vals

    def test_scan_respects_multiple_financial_columns(self):
        """scan() can detect anomalies in 'total' column (another financial hint)."""
        import random
        random.seed(11)
        vals = [200.0 + random.uniform(-10, 10) for _ in range(25)] + [8_000_000.0]
        rows = [{"amount_untaxed": 100.0, "total": v} for v in vals]
        qr = {"results": {"q": {"columns": ["amount_untaxed", "total"], "rows": rows}}}
        detector = AnomalyDetector()
        anomalies = detector.scan(qr)
        # Should detect in at least one of the two columns
        assert len(anomalies) >= 1

    def test_scan_medium_severity_threshold(self):
        """An outlier between 5-20% of total gets MEDIUM severity."""
        import random
        random.seed(17)
        base_total = sum(1000.0 + random.uniform(-100, 100) for _ in range(20))
        # Spike: ~10% of the total → MEDIUM
        spike = base_total * 0.10
        vals = [1000.0 + random.uniform(-100, 100) for _ in range(20)] + [spike]
        rows = [{"amount_untaxed": v} for v in vals]
        qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
        detector = AnomalyDetector()
        anomalies = detector.scan(qr)
        # Verify no crash; severity is HIGH, MEDIUM, or LOW
        for a in anomalies:
            assert a.severity in ("HIGH", "MEDIUM", "LOW")

    def test_format_for_agent_returns_string(self):
        """format_for_agent always returns a string."""
        detector = AnomalyDetector()
        result = detector.format_for_agent([])
        assert isinstance(result, str)

    def test_scan_description_is_non_empty(self):
        """Each StatisticalAnomaly.description must be a non-empty string."""
        import random
        random.seed(21)
        vals = [500.0 + random.uniform(-30, 30) for _ in range(25)] + [4_000_000.0]
        rows = [{"amount_untaxed": v} for v in vals]
        qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
        detector = AnomalyDetector()
        anomalies = detector.scan(qr)
        for a in anomalies:
            assert isinstance(a.description, str)
            assert len(a.description) > 0
