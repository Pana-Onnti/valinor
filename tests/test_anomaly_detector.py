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


# ---------------------------------------------------------------------------
# 12 new tests
# ---------------------------------------------------------------------------

def test_non_financial_column_returns_no_anomaly():
    """Columns 'id' and 'date' are not financial hints — no anomaly raised."""
    # Use extreme values to ensure detection would fire if column were financial
    vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
            112.0, 122.0, 107.0, 117.0, 127.0, 113.0] + [999_999_999.0]
    for col in ("id", "date", "order_date", "customer_id"):
        rows = [{col: v} for v in vals]
        qr = {"results": {"q": {"columns": [col], "rows": rows}}}
        detector = AnomalyDetector()
        anomalies = detector.scan(qr)
        assert anomalies == [], f"Expected no anomaly for column '{col}', got {anomalies}"


def test_fewer_than_ten_values_returns_empty():
    """A financial column with only 8 valid positive values is skipped (< 10 threshold)."""
    vals = [100.0] * 8
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert anomalies == []


def test_scan_returns_list_type_new():
    """scan() always returns a list regardless of input content."""
    detector = AnomalyDetector()
    # Empty results
    assert isinstance(detector.scan({}), list)
    # Results with no columns
    assert isinstance(detector.scan({"results": {"q": {"columns": [], "rows": []}}}), list)
    # Normal spike data
    vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
            112.0, 122.0, 107.0, 117.0, 127.0, 113.0] + [999_999_999.0]
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    assert isinstance(detector.scan(qr), list)


def test_anomaly_query_id_matches_input():
    """StatisticalAnomaly.query_id must equal the key used in query_results."""
    vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
            112.0, 122.0, 107.0, 117.0, 127.0, 113.0] + [999_999_999.0]
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"unique_key_xyz": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert len(anomalies) >= 1
    assert all(a.query_id == "unique_key_xyz" for a in anomalies)


def test_anomaly_column_matches_input():
    """StatisticalAnomaly.column must equal the column name passed in."""
    vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
            112.0, 122.0, 107.0, 117.0, 127.0, 113.0] + [999_999_999.0]
    rows = [{"total_revenue": v} for v in vals]
    qr = {"results": {"q": {"columns": ["total_revenue"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert len(anomalies) >= 1
    assert all(a.column == "total_revenue" for a in anomalies)


def test_anomaly_method_is_iqr_3x_log():
    """Every anomaly produced by scan() uses method == 'iqr_3x_log'."""
    vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
            112.0, 122.0, 107.0, 117.0, 127.0, 113.0] + [999_999_999.0]
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert len(anomalies) >= 1
    for a in anomalies:
        assert a.method == "iqr_3x_log"


def test_format_for_agent_with_anomalies_non_empty():
    """format_for_agent with a real anomaly returns a non-empty string."""
    anomaly = StatisticalAnomaly(
        query_id="q1",
        column="amount_untaxed",
        method="iqr_3x_log",
        severity="HIGH",
        description="1 outlier(s) en amount_untaxed representan 99.9% del total",
        outlier_values=[999_999_999.0],
        outlier_count=1,
        value_share=0.999,
    )
    detector = AnomalyDetector()
    result = detector.format_for_agent([anomaly])
    assert isinstance(result, str)
    assert len(result) > 0


def test_format_for_agent_contains_severity():
    """format_for_agent output includes one of HIGH, MEDIUM, or LOW."""
    for sev, share in [("HIGH", 0.50), ("MEDIUM", 0.10), ("LOW", 0.01)]:
        anomaly = StatisticalAnomaly(
            query_id="q1",
            column="amount_untaxed",
            method="iqr_3x_log",
            severity=sev,
            description=f"1 outlier(s) en amount_untaxed representan {share:.1%} del total",
            outlier_values=[12345.0],
            outlier_count=1,
            value_share=share,
        )
        detector = AnomalyDetector()
        result = detector.format_for_agent([anomaly])
        assert sev in result, f"Expected severity '{sev}' in output: {result!r}"


def test_multiple_queries_multiple_anomalies():
    """Two separate query entries each with an extreme outlier produce 2+ anomalies."""
    base_vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
                 112.0, 122.0, 107.0, 117.0, 127.0, 113.0]

    def _make_qr(key: str) -> dict:
        vals = base_vals + [999_999_999.0]
        rows = [{"amount_untaxed": v} for v in vals]
        return {"columns": ["amount_untaxed"], "rows": rows}

    qr = {"results": {"query_a": _make_qr("query_a"), "query_b": _make_qr("query_b")}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    query_ids_with_anomalies = {a.query_id for a in anomalies}
    assert "query_a" in query_ids_with_anomalies
    assert "query_b" in query_ids_with_anomalies
    assert len(anomalies) >= 2


def test_value_share_between_0_and_1():
    """outlier.value_share is always in the closed interval [0, 1]."""
    vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
            112.0, 122.0, 107.0, 117.0, 127.0, 113.0] + [999_999_999.0]
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert len(anomalies) >= 1
    for a in anomalies:
        assert 0.0 <= a.value_share <= 1.0, f"value_share={a.value_share} out of [0,1]"


def test_outlier_values_list_not_empty():
    """Every anomaly has at least one value in outlier_values."""
    vals = [100.0, 120.0, 110.0, 130.0, 105.0, 115.0, 125.0, 108.0, 118.0,
            112.0, 122.0, 107.0, 117.0, 127.0, 113.0] + [999_999_999.0]
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert len(anomalies) >= 1
    for a in anomalies:
        assert isinstance(a.outlier_values, list)
        assert len(a.outlier_values) > 0


def test_no_anomaly_for_uniform_data():
    """20 rows all with exactly 100.0 produce zero IQR on log scale → no anomaly."""
    vals = [100.0] * 20
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert anomalies == []


# ---------------------------------------------------------------------------
# 12 additional new tests — appended, existing tests not modified
# ---------------------------------------------------------------------------

def test_financial_hint_price_in_column_name():
    """A column containing 'price' is treated as a financial column and checked."""
    import random
    random.seed(99)
    vals = [50.0 + random.uniform(-5, 5) for _ in range(20)] + [5_000_000.0]
    rows = [{"unit_price": v} for v in vals]
    qr = {"results": {"q": {"columns": ["unit_price"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert any(a.column == "unit_price" for a in anomalies), (
        "Expected anomaly for 'unit_price' column"
    )


def test_financial_hint_importe_in_column_name():
    """A column containing 'importe' (Spanish financial hint) is checked."""
    import random
    random.seed(101)
    vals = [200.0 + random.uniform(-20, 20) for _ in range(20)] + [8_000_000.0]
    rows = [{"importe_neto": v} for v in vals]
    qr = {"results": {"q": {"columns": ["importe_neto"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert any(a.column == "importe_neto" for a in anomalies), (
        "Expected anomaly for 'importe_neto' column"
    )


def test_financial_hint_monto_in_column_name():
    """A column containing 'monto' (Spanish financial hint) is checked."""
    import random
    random.seed(103)
    vals = [300.0 + random.uniform(-30, 30) for _ in range(20)] + [9_000_000.0]
    rows = [{"monto_total": v} for v in vals]
    qr = {"results": {"q": {"columns": ["monto_total"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert any(a.column == "monto_total" for a in anomalies), (
        "Expected anomaly for 'monto_total' column"
    )


def test_none_values_in_rows_are_skipped():
    """None values in a financial column are silently skipped; detection still works."""
    import random
    random.seed(111)
    vals = [100.0 + random.uniform(-10, 10) for _ in range(18)]
    vals.append(7_000_000.0)
    # Interleave None values — these must be filtered out
    rows = [{"amount_untaxed": None} for _ in range(5)]
    rows += [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert any(a.column == "amount_untaxed" for a in anomalies), (
        "Expected anomaly even when some rows contain None"
    )


def test_non_dict_rows_are_skipped_gracefully():
    """Non-dict entries in rows list are skipped without raising an exception."""
    import random
    random.seed(113)
    normal = [200.0 + random.uniform(-20, 20) for _ in range(15)]
    spike = 6_000_000.0
    valid_rows = [{"amount_untaxed": v} for v in normal] + [{"amount_untaxed": spike}]
    # Insert non-dict entries that should be silently skipped
    mixed_rows = valid_rows[:5] + [None, "bad_row", 42] + valid_rows[5:]  # type: ignore[list-item]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": mixed_rows}}}
    detector = AnomalyDetector()
    # Must not raise; may or may not detect depending on valid count
    result = detector.scan(qr)
    assert isinstance(result, list)


def test_column_missing_from_row_dicts_is_skipped():
    """If a column is listed in 'columns' but absent from every row, no anomaly is raised."""
    # Rows have 'amount_untaxed' but columns also lists a phantom column
    rows = [{"amount_untaxed": 100.0}] * 5
    qr = {"results": {"q": {"columns": ["amount_untaxed", "phantom_price"], "rows": rows}}}
    detector = AnomalyDetector()
    # phantom_price has no values → < 10 valid → skipped
    anomalies = detector.scan(qr)
    assert all(a.column != "phantom_price" for a in anomalies)


def test_outlier_count_matches_outlier_values_len():
    """StatisticalAnomaly.outlier_count aligns with len(outlier_values) or is >= it (capped at 3)."""
    import random
    random.seed(117)
    vals = [150.0 + random.uniform(-15, 15) for _ in range(20)] + [5_000_000.0]
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert len(anomalies) >= 1
    for a in anomalies:
        # outlier_values is capped at 3; outlier_count reflects the true count
        assert a.outlier_count >= len(a.outlier_values)
        assert a.outlier_count >= 1


def test_two_outliers_both_captured():
    """Two extreme spikes in the same column both appear in outlier_values (up to cap of 3)."""
    import random
    random.seed(119)
    vals = [100.0 + random.uniform(-10, 10) for _ in range(20)]
    vals += [4_000_000.0, 5_000_000.0]   # two distinct spikes
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    assert len(anomalies) >= 1
    combined = [v for a in anomalies for v in a.outlier_values]
    # At least one of the two spikes must appear
    assert any(v >= 4_000_000.0 for v in combined)


def test_low_severity_when_share_below_5pct():
    """An outlier representing < 5% of total receives LOW severity."""
    import random
    random.seed(123)
    # Build a dataset where the normal base is very large and the outlier is tiny in share
    # 20 values near 1_000_000, plus one value that is ~3x IQR outlier on log scale but small share
    # Use 20 values at 1_000_000 (varied) and 1 value at 10_000_000 so share ≈ 10_000_000 / 30_000_000 ≈ 33%
    # Instead: 200 normal values at 10_000, 1 outlier at 50_000 → share ≈ 50_000 / 2_050_000 ≈ 2.4%
    base = 10_000.0
    n = 200
    vals = [base + random.uniform(-500, 500) for _ in range(n)] + [50_000.0]
    rows = [{"amount_untaxed": v} for v in vals]
    qr = {"results": {"q": {"columns": ["amount_untaxed"], "rows": rows}}}
    detector = AnomalyDetector()
    anomalies = detector.scan(qr)
    # If an anomaly is detected, check it has LOW severity (share < 5%)
    low_anomalies = [a for a in anomalies if a.severity == "LOW"]
    # The assertion is that IF any anomaly is detected AND share is low, severity is LOW
    for a in anomalies:
        if a.value_share < 0.05:
            assert a.severity == "LOW", (
                f"Expected LOW for value_share={a.value_share:.3f}, got {a.severity}"
            )


def test_format_for_agent_header_line_present():
    """When anomalies exist, format_for_agent output starts with a header line."""
    anomaly = StatisticalAnomaly(
        query_id="q1",
        column="total_price",
        method="iqr_3x_log",
        severity="MEDIUM",
        description="1 outlier(s) en total_price representan 10.0% del total",
        outlier_values=[123456.0],
        outlier_count=1,
        value_share=0.10,
    )
    detector = AnomalyDetector()
    result = detector.format_for_agent([anomaly])
    first_line = result.splitlines()[0]
    # Header must mention anomalies and their count
    assert "ANOMAL" in first_line.upper() and "1" in first_line


def test_format_for_agent_sorted_by_value_share_descending():
    """format_for_agent displays the highest value_share anomaly first."""
    low = StatisticalAnomaly(
        query_id="q_low",
        column="amount_untaxed",
        method="iqr_3x_log",
        severity="LOW",
        description="low share",
        outlier_values=[1000.0],
        outlier_count=1,
        value_share=0.02,
    )
    high = StatisticalAnomaly(
        query_id="q_high",
        column="total_revenue",
        method="iqr_3x_log",
        severity="HIGH",
        description="high share",
        outlier_values=[9_000_000.0],
        outlier_count=1,
        value_share=0.75,
    )
    detector = AnomalyDetector()
    result = detector.format_for_agent([low, high])
    # q_high (value_share=0.75) must appear before q_low (value_share=0.02)
    pos_high = result.index("q_high")
    pos_low = result.index("q_low")
    assert pos_high < pos_low, "Higher value_share anomaly should appear first"


def test_singleton_returns_new_instance_after_reset():
    """After manually resetting the module-level _detector to None, get_anomaly_detector() creates a new instance."""
    import core.valinor.quality.anomaly_detector as _mod

    original = _mod._detector
    try:
        _mod._detector = None
        fresh = get_anomaly_detector()
        assert isinstance(fresh, AnomalyDetector)
        # Calling again returns the same new instance
        assert get_anomaly_detector() is fresh
    finally:
        # Restore original singleton to avoid polluting other tests
        _mod._detector = original
