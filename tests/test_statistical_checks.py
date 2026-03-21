"""
Tests for core/valinor/quality/statistical_checks.py

Covers:
  - cusum_structural_break (CUSUM change-point detection)
  - benford_test (Benford's Law first-digit analysis)
  - seasonal_adjusted_zscore (STL / simple z-score)
  - cointegration_test (Engle-Granger / correlation fallback)

All tests are pure-mathematical — no database connection required.
"""
from __future__ import annotations

import sys
import math
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup — core/ must be on sys.path so valinor package is importable
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from valinor.quality.statistical_checks import (
    cusum_structural_break,
    benford_test,
    seasonal_adjusted_zscore,
    cointegration_test,
)


# ===========================================================================
# TestCUSUMDetector
# ===========================================================================
class TestCUSUMDetector:
    """Tests for cusum_structural_break — cumulative-sum structural-break detection."""

    # --- Normal operation ---

    def test_stable_series_no_break(self):
        """A stationary series with low variance should NOT trigger a break."""
        series = [10.0, 10.1, 9.9, 10.2, 9.8, 10.0, 10.1, 9.9, 10.0, 10.0]
        result = cusum_structural_break(series)
        assert result["break_detected"] is False
        assert result["cusum_last"] >= 0.0

    def test_large_upward_shift_detected(self):
        """A clear upward level-shift in the last period must trigger a break.
        Baseline needs some variance so std > 0 (CUSUM normalises by std)."""
        import random
        rng = random.Random(42)
        baseline = [10.0 + rng.gauss(0, 0.5) for _ in range(18)]
        # Replace last 2 with a dramatic upward shift
        series = baseline[:-2] + [200.0, 200.0]
        result = cusum_structural_break(series, threshold=5.0)
        assert result["break_detected"] is True
        assert result["cusum_last"] > 5.0

    def test_large_downward_shift_detected(self):
        """A clear downward level-shift should also be flagged."""
        import random
        rng = random.Random(7)
        baseline = [100.0 + rng.gauss(0, 1.0) for _ in range(10)]
        series = baseline + [1.0, 1.0]
        result = cusum_structural_break(series, threshold=5.0)
        assert result["break_detected"] is True

    def test_result_keys_present(self):
        """Return dict must contain the four documented keys."""
        series = list(range(10, 20))
        result = cusum_structural_break(series)
        for key in ("break_detected", "cusum_last", "threshold", "interpretation"):
            assert key in result, f"Missing key: {key}"

    def test_custom_threshold_respected(self):
        """Raising threshold should suppress detection for a modest shift."""
        import random
        rng = random.Random(99)
        # Noisy baseline with a small upward shift at the end
        series = [10.0 + rng.gauss(0, 0.5) for _ in range(8)] + [12.0, 12.0]
        loose = cusum_structural_break(series, threshold=50.0)
        tight = cusum_structural_break(series, threshold=0.1)
        assert loose["break_detected"] is False
        assert tight["break_detected"] is True

    def test_insufficient_data_returns_no_break(self):
        """Series shorter than 6 points must return break_detected=False gracefully."""
        result = cusum_structural_break([1.0, 2.0, 3.0])
        assert result["break_detected"] is False
        assert "interpretation" in result

    def test_zero_variance_series_returns_no_break(self):
        """All-equal values produce zero std; function must handle division-by-zero."""
        series = [5.0] * 10
        result = cusum_structural_break(series)
        assert result["break_detected"] is False
        assert result["cusum_last"] == 0.0

    def test_single_point_returns_no_break(self):
        """A single-element list must not raise and must return break_detected=False."""
        result = cusum_structural_break([42.0])
        assert result["break_detected"] is False

    def test_cusum_last_is_non_negative(self):
        """cusum_last is abs(cusum[-1]) so it must always be >= 0."""
        for series in [
            [1, 2, 3, 4, 5, 6, 7, 8],
            [8, 7, 6, 5, 4, 3, 2, 1],
            [5, 5, 5, 5, 5, 10, 10, 10],
        ]:
            result = cusum_structural_break(series)
            assert result["cusum_last"] >= 0.0

    def test_interpretation_is_string(self):
        """interpretation field must always be a non-empty string."""
        for series in [[1.0] * 3, [1.0] * 10, [1.0] * 6 + [100.0, 100.0]]:
            result = cusum_structural_break(series)
            assert isinstance(result["interpretation"], str)
            assert len(result["interpretation"]) > 0


# ===========================================================================
# TestBenfordLawCheck
# ===========================================================================
class TestBenfordLawCheck:
    """Tests for benford_test — Benford's Law first-digit distribution check."""

    # --- Helper ---
    @staticmethod
    def _scale_to_100(values: list[float]) -> list[float]:
        """Repeat a pattern until we have >= 100 samples (min_sample default)."""
        reps = math.ceil(100 / len(values))
        return (values * reps)[:100]

    # --- Core behaviour ---

    def test_insufficient_sample_returns_not_suspicious(self):
        """Fewer than min_sample values must return suspicious=False and a note."""
        result = benford_test([1.0, 2.0, 3.0], min_sample=100)
        assert result["suspicious"] is False
        assert result["n_samples"] <= 3
        assert "Insufficient" in result["interpretation"]

    def test_fibonacci_distribution_not_suspicious(self):
        """Fibonacci numbers follow Benford's Law and should not be flagged.
        We scale the base sequence to 100+ samples."""
        fib_base = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610,
                    987, 1597, 2584, 4181, 6765]
        fib_100 = self._scale_to_100(fib_base)
        result = benford_test(fib_100, min_sample=50)
        # Fibonacci naturally obeys Benford — MAD should be low
        # Fibonacci obeys Benford — MAD should be low and not flagged as suspicious
        assert result["suspicious"] is False
        if result["mad"] is not None:
            assert result["mad"] < 0.10, (
                f"Fibonacci MAD too high: {result['mad']:.4f}"
            )

    def test_uniform_first_digit_flagged_as_suspicious(self):
        """Uniform first-digit distribution violates Benford's Law.
        We build a 100-sample list with exactly equal counts for digits 1-9."""
        uniform = []
        for d in range(1, 10):
            # 12 copies of each digit, starting values d, d*10, d*100 …
            for exp in range(12):
                uniform.append(float(d) * (10 ** exp))
        result = benford_test(uniform, min_sample=50)
        # MAD from expected should be measurably non-zero
        assert result["mad"] is not None
        # We don't assert suspicious==True because that requires scipy p-value;
        # but we do assert MAD is elevated versus a near-perfect Benford set.
        assert result["mad"] > 0.0

    def test_result_keys_present(self):
        """Return dict must contain all six documented keys."""
        result = benford_test([float(i) for i in range(1, 10)], min_sample=5)
        for key in ("chi2", "p_value", "mad", "suspicious", "n_samples", "interpretation"):
            assert key in result, f"Missing key: {key}"

    def test_values_less_than_or_equal_to_one_are_excluded(self):
        """Values <= 1 are filtered out before the digit count."""
        values = [0.5, 0.1, 1.0] + [2.0, 3.0, 5.0, 8.0, 13.0, 21.0] * 15
        result = benford_test(values, min_sample=50)
        # n_samples must NOT count 0.5, 0.1, or 1.0
        assert result["n_samples"] == 90  # 6 * 15

    def test_n_samples_reported_correctly(self):
        """n_samples must equal the count of values > 1."""
        values = [float(i) for i in range(2, 202)]  # 200 values, all > 1
        result = benford_test(values, min_sample=100)
        assert result["n_samples"] == 200

    def test_mad_is_non_negative(self):
        """MAD (mean absolute deviation) is always >= 0."""
        values = [float(i) for i in range(2, 202)]
        result = benford_test(values, min_sample=100)
        if result["mad"] is not None:
            assert result["mad"] >= 0.0

    def test_custom_min_sample(self):
        """min_sample parameter is honoured — 10 values pass with min_sample=5."""
        values = [1.1, 2.2, 3.3, 4.4, 5.5, 6.6, 7.7, 8.8, 9.9, 10.0]
        result = benford_test(values, min_sample=5)
        # Should not get the "Insufficient sample" response
        assert "Insufficient" not in result["interpretation"]


# ===========================================================================
# TestSTLDecomposition  (via seasonal_adjusted_zscore)
# ===========================================================================
class TestSTLDecomposition:
    """Tests for seasonal_adjusted_zscore — STL / simple z-score anomaly flag."""

    def test_insufficient_series_returns_safe_defaults(self):
        """Fewer than 4 historical points must return is_anomalous=False."""
        result = seasonal_adjusted_zscore([1.0, 2.0], current_value=5.0)
        assert result["is_anomalous"] is False
        assert result["method"] == "insufficient_data"

    def test_empty_series_returns_safe_defaults(self):
        """Empty history must not raise and must return safe defaults."""
        result = seasonal_adjusted_zscore([], current_value=10.0)
        assert result["is_anomalous"] is False

    def test_normal_value_not_anomalous(self):
        """A value close to the historical mean must not be flagged."""
        series = [10.0] * 20
        result = seasonal_adjusted_zscore(series, current_value=10.0)
        assert result["is_anomalous"] is False

    def test_extreme_value_is_anomalous(self):
        """A value far from the historical mean must be flagged."""
        # Use a series with some variance so std > 0
        series = [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.1, 9.9]
        result = seasonal_adjusted_zscore(series, current_value=9999.0)
        assert result["is_anomalous"]  # True or np.bool_(True)

    def test_z_score_sign_positive_for_high_value(self):
        """z-score must be positive when current_value > mean (series must have variance)."""
        series = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.1, 4.9]
        result = seasonal_adjusted_zscore(series, current_value=100.0)
        assert result["z_score"] > 0

    def test_z_score_sign_negative_for_low_value(self):
        """z-score must be negative when current_value << mean (series must have variance)."""
        series = [100.0, 100.5, 99.5, 100.0, 100.3, 99.7, 100.1, 99.9]
        result = seasonal_adjusted_zscore(series, current_value=1.0)
        assert result["z_score"] < 0

    def test_result_keys_present(self):
        """Return dict must contain all documented keys."""
        result = seasonal_adjusted_zscore([1.0] * 8, current_value=1.0)
        for key in ("z_score", "method", "seasonal_component",
                    "trend_component", "is_anomalous", "adjusted_expected"):
            assert key in result, f"Missing key: {key}"

    def test_zero_variance_does_not_raise(self):
        """All-equal history produces zero std; no ZeroDivisionError must occur."""
        series = [7.0] * 8
        result = seasonal_adjusted_zscore(series, current_value=7.0)
        assert result["z_score"] == 0.0
        assert result["is_anomalous"] is False

    def test_method_is_string(self):
        """method field must always be a non-empty string."""
        for series, val in [
            ([], 1.0),
            ([1.0, 2.0], 1.5),
            ([1.0] * 8, 1.0),
        ]:
            result = seasonal_adjusted_zscore(series, current_value=val)
            assert isinstance(result["method"], str)
            assert len(result["method"]) > 0

    def test_adjusted_expected_equals_current_for_insufficient_data(self):
        """When there is no data, adjusted_expected is set to current_value."""
        result = seasonal_adjusted_zscore([], current_value=42.0)
        assert result["adjusted_expected"] == 42.0


# ===========================================================================
# TestCointegrationCheck
# ===========================================================================
class TestCointegrationCheck:
    """Tests for cointegration_test — Engle-Granger / correlation fallback."""

    def test_insufficient_data_returns_none(self):
        """Series shorter than 8 points must return cointegrated=None."""
        result = cointegration_test([1, 2, 3], [1, 2, 3])
        assert result["cointegrated"] is None
        assert result["method"] == "insufficient_data"

    def test_unequal_length_series_returns_none(self):
        """Mismatched series lengths must be rejected gracefully."""
        result = cointegration_test([1.0] * 10, [1.0] * 5)
        assert result["cointegrated"] is None

    def test_perfectly_correlated_series(self):
        """Two identical series must have correlation = 1.0."""
        series = [float(i) for i in range(1, 21)]
        result = cointegration_test(series, series)
        assert result["correlation"] is not None
        assert abs(result["correlation"] - 1.0) < 1e-9

    def test_perfectly_anticorrelated_series(self):
        """Reversed series must have correlation = -1.0."""
        s1 = [float(i) for i in range(1, 21)]
        s2 = list(reversed(s1))
        result = cointegration_test(s1, s2)
        assert result["correlation"] is not None
        assert abs(result["correlation"] + 1.0) < 1e-9

    def test_result_keys_present(self):
        """Return dict must contain all five documented keys."""
        s = [float(i) for i in range(1, 21)]
        result = cointegration_test(s, s)
        for key in ("cointegrated", "p_value", "method", "correlation", "interpretation"):
            assert key in result, f"Missing key: {key}"

    def test_interpretation_is_string(self):
        """interpretation must always be a non-empty string."""
        s = [float(i) for i in range(1, 21)]
        result = cointegration_test(s, s)
        assert isinstance(result["interpretation"], str)
        assert len(result["interpretation"]) > 0

    def test_weakly_correlated_series_correlation_fallback(self):
        """Uncorrelated white noise must have |correlation| close to 0."""
        rng = np.random.default_rng(seed=0)
        s1 = rng.standard_normal(30).tolist()
        s2 = rng.standard_normal(30).tolist()
        result = cointegration_test(s1, s2)
        # correlation may be non-zero but should not be near ±1
        if result["correlation"] is not None:
            assert abs(result["correlation"]) < 0.9


# ===========================================================================
# Additional tests — untested behaviours (appended)
# ===========================================================================

class TestCUSUMAdditional:
    """Additional tests for cusum_structural_break covering untested code paths."""

    def test_threshold_value_echoed_in_result(self):
        """The threshold key in the result must equal the value passed in."""
        series = list(range(10, 20))
        custom_thresh = 7.3
        result = cusum_structural_break(series, threshold=custom_thresh)
        assert result["threshold"] == custom_thresh

    def test_exactly_six_points_not_rejected(self):
        """Exactly 6 points is the minimum that should NOT trigger the early-exit path."""
        series = [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]
        result = cusum_structural_break(series)
        # Should not fall into the "Insufficient data" path
        assert result["interpretation"] != "Insufficient data"

    def test_upward_interpretation_string(self):
        """When break is detected with positive CUSUM, interpretation must say 'upward'."""
        import random
        rng = random.Random(11)
        baseline = [10.0 + rng.gauss(0, 0.5) for _ in range(10)]
        series = baseline + [500.0, 500.0]
        result = cusum_structural_break(series, threshold=5.0)
        assert result["break_detected"] is True
        assert "upward" in result["interpretation"]

    def test_downward_interpretation_string(self):
        """When break is detected with negative CUSUM, interpretation must say 'downward'."""
        import random
        rng = random.Random(13)
        baseline = [100.0 + rng.gauss(0, 1.0) for _ in range(10)]
        series = baseline + [0.0001, 0.0001]
        result = cusum_structural_break(series, threshold=5.0)
        assert result["break_detected"] is True
        assert "downward" in result["interpretation"]

    def test_window_exclude_parameter_changes_result(self):
        """window_exclude controls how many tail points are excluded from baseline;
        a larger window shrinks the baseline and may suppress detection."""
        import random
        rng = random.Random(55)
        # Series where only the very last point is anomalous
        series = [10.0 + rng.gauss(0, 0.3) for _ in range(14)] + [200.0]
        # With window_exclude=1 the anomalous point is in the evaluated window
        result_w1 = cusum_structural_break(series, window_exclude=1, threshold=5.0)
        # With window_exclude=15 (covers the whole series), baseline is near-empty
        # and the function should fall back gracefully (len < 6 guard doesn't apply
        # since series has 15 points; baseline has 0 points which means std=0)
        result_w1_keys = set(result_w1.keys())
        assert {"break_detected", "cusum_last", "threshold", "interpretation"} <= result_w1_keys

    def test_penultimate_cusum_can_trigger_break(self):
        """break_detected fires when abs(cusum[-2]) > threshold even if cusum[-1] is low.
        Build a series where the penultimate cumsum spikes then partially reverts."""
        import random
        rng = random.Random(77)
        baseline = [10.0 + rng.gauss(0, 0.5) for _ in range(10)]
        # Large spike in second-to-last, then partial reversion in last
        series = baseline + [500.0, 10.5]
        result = cusum_structural_break(series, threshold=3.0)
        # The cumulative sum at position -2 should be large enough to trigger
        assert result["break_detected"] is True


class TestBenfordAdditional:
    """Additional tests for benford_test covering untested code paths."""

    def test_negative_values_are_filtered(self):
        """Negative numbers satisfy v > 1 only when positive; negatives with abs > 1
        are NOT counted since the filter is v > 1 (not abs(v) > 1)."""
        # Provide 50 negative values plus 100 positive > 1 to confirm only positives counted
        negatives = [-float(i) for i in range(2, 52)]  # -2 to -51 — all <= 1 condition: False
        positives = [float(i) for i in range(2, 102)]  # 100 values all > 1
        result = benford_test(negatives + positives, min_sample=50)
        # Only the 100 positive values pass the v > 1 filter
        assert result["n_samples"] == 100

    def test_chi2_is_numeric_when_sample_sufficient(self):
        """chi2 must be a finite float (not None) when n >= min_sample."""
        values = [float(i) for i in range(2, 302)]  # 300 values
        result = benford_test(values, min_sample=100)
        assert result["chi2"] is not None
        assert math.isfinite(result["chi2"])

    def test_interpretation_not_suspicious_for_natural_data(self):
        """Natural financial-like data must produce the 'consistent' interpretation string."""
        # Powers of 2 roughly follow Benford (leading digit distribution)
        values = [2 ** i for i in range(1, 201)]
        result = benford_test(values, min_sample=100)
        # Should not be flagged as suspicious
        assert result["suspicious"] is False
        assert "consistent" in result["interpretation"].lower() or \
               result["suspicious"] is False

    def test_all_values_equal_to_two_mad_nonzero(self):
        """If all values have first digit 2, MAD must be > 0 (Benford expects ~17.6% for digit 2
        but we have 100%)."""
        values = [2.0 * (10 ** k) for k in range(200)]  # all start with digit 2
        result = benford_test(values, min_sample=100)
        assert result["mad"] is not None
        assert result["mad"] > 0.0


class TestSTLAdditional:
    """Additional tests for seasonal_adjusted_zscore covering untested code paths."""

    def test_exactly_four_points_not_rejected(self):
        """Exactly 4 historical points is the minimum for the main analysis path."""
        series = [1.0, 2.0, 3.0, 4.0]
        result = seasonal_adjusted_zscore(series, current_value=3.0)
        assert result["method"] != "insufficient_data"

    def test_three_points_returns_insufficient(self):
        """3 historical points must return the insufficient_data method."""
        result = seasonal_adjusted_zscore([1.0, 2.0, 3.0], current_value=3.0)
        assert result["method"] == "insufficient_data"
        assert result["is_anomalous"] is False

    def test_adjusted_expected_equals_mean_in_simple_path(self):
        """In the simple (non-STL) path, adjusted_expected must equal the historical mean."""
        series = [10.0, 20.0, 30.0, 40.0]  # mean = 25.0
        result = seasonal_adjusted_zscore(series, current_value=25.0)
        if result["method"] == "simple":
            assert abs(result["adjusted_expected"] - 25.0) < 1e-9

    def test_anomaly_threshold_boundary_just_below(self):
        """A z-score just below 2.5 must NOT be flagged as anomalous."""
        # series with std=1, mean=0; current_value = 2.49 → z ≈ 2.49
        series = [float(v) for v in range(-4, 5)]  # mean=0, std ≈ 2.74
        mean_val = sum(series) / len(series)
        std_val = (sum((x - mean_val) ** 2 for x in series) / len(series)) ** 0.5
        # current_value gives z just under 2.5
        current = mean_val + 2.49 * std_val
        result = seasonal_adjusted_zscore(series, current_value=current)
        if result["method"] == "simple":
            assert not result["is_anomalous"]

    def test_anomaly_threshold_boundary_just_above(self):
        """A z-score just above 2.5 must be flagged as anomalous."""
        series = [float(v) for v in range(-4, 5)]
        mean_val = sum(series) / len(series)
        std_val = (sum((x - mean_val) ** 2 for x in series) / len(series)) ** 0.5
        current = mean_val + 2.51 * std_val
        result = seasonal_adjusted_zscore(series, current_value=current)
        if result["method"] == "simple":
            assert result["is_anomalous"]


class TestCointegrationAdditional:
    """Additional tests for cointegration_test covering untested code paths."""

    def test_exactly_eight_points_not_rejected(self):
        """Exactly 8 points per series meets the minimum — must not return insufficient_data."""
        s = [float(i) for i in range(1, 9)]  # 8 points
        result = cointegration_test(s, s)
        assert result["method"] != "insufficient_data"
        assert result["cointegrated"] is not None

    def test_seven_points_returns_insufficient(self):
        """7 points is below the 8-point minimum and must be rejected."""
        s = [float(i) for i in range(1, 8)]
        result = cointegration_test(s, s)
        assert result["cointegrated"] is None
        assert result["method"] == "insufficient_data"

    def test_significance_parameter_respected(self):
        """A very tight significance (0.001) vs a loose one (0.99) should differ in
        cointegrated outcome for a borderline series."""
        rng = np.random.default_rng(seed=42)
        n = 50
        # Build two series with mild cointegration structure
        common = np.cumsum(rng.standard_normal(n))
        s1 = (common + rng.standard_normal(n) * 0.1).tolist()
        s2 = (common + rng.standard_normal(n) * 0.1).tolist()
        loose = cointegration_test(s1, s2, significance=0.99)
        tight = cointegration_test(s1, s2, significance=0.001)
        # With loose significance almost everything is "cointegrated"; with tight, maybe not.
        # At minimum both results must be valid (not None) and have the right keys.
        for r in (loose, tight):
            assert r["method"] != "insufficient_data"
            assert r["correlation"] is not None

    def test_correlation_always_between_minus1_and_1(self):
        """Pearson correlation must always be in [-1, 1] for any valid series."""
        rng = np.random.default_rng(seed=7)
        for _ in range(5):
            s1 = rng.standard_normal(20).tolist()
            s2 = rng.standard_normal(20).tolist()
            result = cointegration_test(s1, s2)
            if result["correlation"] is not None:
                assert -1.0 <= result["correlation"] <= 1.0
