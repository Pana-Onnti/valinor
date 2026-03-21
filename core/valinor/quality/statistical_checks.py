"""
Statistical checks library for Valinor data quality.
Implements econometric and quant finance data verification methods.
"""
from __future__ import annotations
from typing import Optional, List, Tuple, Dict
import numpy as np
import structlog

logger = structlog.get_logger()

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    from statsmodels.tsa.seasonal import STL
    from statsmodels.tsa.stattools import adfuller, coint
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False


def seasonal_adjusted_zscore(
    series: List[float],
    current_value: float,
    period: int = 12,
) -> Dict:
    """
    Compute z-score of current_value against seasonally-adjusted historical series.

    Uses STL decomposition if statsmodels available and len(series) >= 12.
    Falls back to simple rolling z-score otherwise.

    Returns:
        {
            "z_score": float,
            "method": "stl" | "simple",
            "seasonal_component": float | None,
            "trend_component": float | None,
            "is_anomalous": bool,    # |z| > 2.5
            "adjusted_expected": float,
        }
    """
    if not series or len(series) < 4:
        return {"z_score": 0.0, "method": "insufficient_data", "is_anomalous": False, "adjusted_expected": current_value}

    arr = np.array(series, dtype=float)

    if HAS_STATSMODELS and HAS_PANDAS and len(series) >= 12:
        try:
            # Add current value to the end for decomposition context
            full_series = np.append(arr, current_value)
            stl = STL(full_series, period=period, robust=True)
            result = stl.fit()

            # Residual of the current value vs seasonal+trend
            residuals = result.resid
            # Use all but last as baseline for std (last = current period)
            baseline_resid = residuals[:-1]
            resid_std = np.std(baseline_resid)
            resid_mean = np.mean(baseline_resid)

            current_resid = residuals[-1]
            z_score = (current_resid - resid_mean) / resid_std if resid_std > 0 else 0.0

            # Adjusted expected = trend + seasonal for current period
            adjusted_expected = result.trend[-1] + result.seasonal[-1]

            return {
                "z_score": float(z_score),
                "method": "stl",
                "seasonal_component": float(result.seasonal[-1]),
                "trend_component": float(result.trend[-1]),
                "is_anomalous": abs(z_score) > 2.5,
                "adjusted_expected": float(adjusted_expected),
            }
        except Exception as e:
            logger.warning("STL decomposition failed, using simple z-score", error=str(e))

    # Fallback: simple z-score
    mean = arr.mean()
    std = arr.std()
    z_score = (current_value - mean) / std if std > 0 else 0.0

    return {
        "z_score": float(z_score),
        "method": "simple",
        "seasonal_component": None,
        "trend_component": None,
        "is_anomalous": abs(z_score) > 2.5,
        "adjusted_expected": float(mean),
    }


def cointegration_test(
    series1: List[float],
    series2: List[float],
    significance: float = 0.10,
) -> Dict:
    """
    Engle-Granger cointegration test between two financial series.

    Used to detect if two series that SHOULD move together (e.g., revenue & receivables)
    are diverging — either a business problem or data quality issue.

    Returns:
        {
            "cointegrated": bool,
            "p_value": float,
            "method": "engle_granger" | "correlation",
            "correlation": float,
            "interpretation": str,
        }
    """
    if len(series1) != len(series2) or len(series1) < 8:
        return {
            "cointegrated": None,
            "p_value": None,
            "method": "insufficient_data",
            "correlation": None,
            "interpretation": "Insufficient data for cointegration test"
        }

    arr1 = np.array(series1, dtype=float)
    arr2 = np.array(series2, dtype=float)

    # Always compute correlation as baseline
    correlation = float(np.corrcoef(arr1, arr2)[0, 1])

    if HAS_STATSMODELS:
        try:
            score, p_value, critical_values = coint(arr1, arr2)
            cointegrated = p_value < significance

            if cointegrated:
                interpretation = f"Series cointegrated (p={p_value:.3f}) — normal co-movement"
            else:
                interpretation = (
                    f"Series NOT cointegrated (p={p_value:.3f}) — unusual divergence detected. "
                    f"Possible collection problem or data quality issue."
                )

            return {
                "cointegrated": cointegrated,
                "p_value": float(p_value),
                "method": "engle_granger",
                "correlation": correlation,
                "interpretation": interpretation,
            }
        except Exception as e:
            logger.warning("Cointegration test failed, using correlation", error=str(e))

    # Fallback: Pearson correlation
    cointegrated_approx = correlation > 0.5
    return {
        "cointegrated": cointegrated_approx,
        "p_value": None,
        "method": "correlation",
        "correlation": correlation,
        "interpretation": (
            f"Correlation: {correlation:.3f} — {'acceptable' if cointegrated_approx else 'weak, possible divergence'}"
        ),
    }


def benford_test(
    values: List[float],
    min_sample: int = 100,
) -> Dict:
    """
    Benford's Law first-digit test.

    Returns:
        {
            "chi2": float,
            "p_value": float,
            "mad": float,           # Mean Absolute Deviation from expected
            "suspicious": bool,
            "n_samples": int,
            "interpretation": str,
        }
    """
    values_filtered = [v for v in values if v > 1]
    n = len(values_filtered)

    if n < min_sample:
        return {
            "chi2": None, "p_value": None, "mad": None,
            "suspicious": False, "n_samples": n,
            "interpretation": f"Insufficient sample (n={n}, need {min_sample})"
        }

    def first_digit(x):
        s = str(abs(x)).replace('.', '').lstrip('0')
        return int(s[0]) if s else None

    first_digits = [first_digit(v) for v in values_filtered if first_digit(v)]
    if not first_digits:
        return {"suspicious": False, "n_samples": 0, "interpretation": "No valid values"}

    observed = np.array([first_digits.count(d) / len(first_digits) for d in range(1, 10)])
    expected = np.array([np.log10(1 + 1/d) for d in range(1, 10)])

    try:
        from scipy.stats import chisquare
        chi2, p_value = chisquare(
            observed * len(first_digits),
            expected * len(first_digits)
        )
        chi2 = float(chi2)
        p_value = float(p_value)
    except ImportError:
        # Manual chi-square
        chi2 = float(np.sum((observed - expected)**2 / expected * len(first_digits)))
        p_value = None  # Can't compute without scipy

    mad = float(np.mean(np.abs(observed - expected)))
    suspicious = (p_value is not None and p_value < 0.01 and mad > 0.015)

    return {
        "chi2": chi2,
        "p_value": p_value,
        "mad": mad,
        "suspicious": suspicious,
        "n_samples": n,
        "interpretation": (
            "Possible systematic rounding, data manipulation, or non-organic entry patterns"
            if suspicious else "Distribution consistent with natural financial data"
        ),
    }


def cusum_structural_break(
    series: List[float],
    window_exclude: int = 2,
    threshold: float = 5.0,
) -> Dict:
    """
    CUSUM test for structural breaks.

    Used to detect if the last N periods show an unusual cumulative deviation
    from the historical mean — indicating a regime change.

    Returns:
        {
            "break_detected": bool,
            "cusum_last": float,
            "threshold": float,
            "interpretation": str,
        }
    """
    if len(series) < 6:
        return {"break_detected": False, "cusum_last": 0.0, "threshold": threshold,
                "interpretation": "Insufficient data"}

    arr = np.array(series, dtype=float)
    baseline = arr[:-window_exclude]
    mean = baseline.mean()
    std = baseline.std()

    if std == 0:
        return {"break_detected": False, "cusum_last": 0.0, "threshold": threshold,
                "interpretation": "Zero variance in historical series"}

    cusum = np.cumsum((arr - mean) / std)
    cusum_last = float(abs(cusum[-1]))
    break_detected = cusum_last > threshold or float(abs(cusum[-2])) > threshold

    direction = "upward" if cusum[-1] > 0 else "downward"
    return {
        "break_detected": break_detected,
        "cusum_last": cusum_last,
        "threshold": threshold,
        "interpretation": (
            f"Structural {direction} break detected in last {window_exclude} periods (CUSUM={cusum_last:.2f})"
            if break_detected else f"No structural break (CUSUM={cusum_last:.2f})"
        ),
    }
