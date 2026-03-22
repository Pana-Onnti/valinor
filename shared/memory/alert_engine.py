"""
AlertEngine — checks ClientProfile alert thresholds after each run.
Supports five condition types:
  - pct_change_below   : period-over-period % change < value  (e.g. revenue drop)
  - pct_change_above   : period-over-period % change > value  (e.g. receivables spike)
  - absolute_below     : current value < threshold
  - absolute_above     : current value > threshold
  - z_score_above      : rolling z-score over full history > N  (anomaly detection)

Stores triggered alerts in profile.triggered_alerts (capped at 20).
"""
from __future__ import annotations
import re
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime

import numpy as np

try:
    import structlog
    logger = structlog.get_logger()
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile

# ---------------------------------------------------------------------------
# Condition evaluators
# ---------------------------------------------------------------------------


def _pct_change(prev: float, curr: float) -> Optional[float]:
    """Returns period-over-period percentage change, or None if prev is ~zero."""
    if abs(prev) < 1e-9:
        return None
    return (curr - prev) / abs(prev) * 100.0


def _z_score(series: List[float]) -> Optional[float]:
    """Returns z-score of the last element against the full series, or None."""
    if len(series) < 3:
        return None
    arr = np.array(series, dtype=float)
    mean = float(arr[:-1].mean())
    std = float(arr[:-1].std(ddof=1)) if len(arr) > 2 else float(arr.std())
    if std < 1e-9:
        return None
    return float((arr[-1] - mean) / std)


def _evaluate_condition(
    condition: str,
    threshold_value: float,
    history_values: List[float],
) -> tuple[bool, Optional[float]]:
    """
    Evaluate a single threshold condition.
    Returns (triggered: bool, computed_value: float | None).
    computed_value is what was actually compared (pct change, z-score, or raw value).
    """
    if not history_values:
        return False, None

    current = history_values[-1]

    if condition == "absolute_below":
        return current < threshold_value, current

    if condition == "absolute_above":
        return current > threshold_value, current

    if condition in ("pct_change_below", "pct_change_above"):
        if len(history_values) < 2:
            return False, None
        prev = history_values[-2]
        pct = _pct_change(prev, current)
        if pct is None:
            return False, None
        if condition == "pct_change_below":
            return pct < threshold_value, pct
        return pct > threshold_value, pct

    if condition == "z_score_above":
        z = _z_score(history_values)
        if z is None:
            return False, None
        return abs(z) > threshold_value, z

    # Unknown condition — never trigger
    return False, None


# ---------------------------------------------------------------------------
# AlertEngine
# ---------------------------------------------------------------------------

class AlertEngine:

    def check_thresholds(
        self,
        profile: "ClientProfile",
        baseline_history: Dict[str, List[Dict]],
        findings: Dict[str, Any],
    ) -> List[Dict]:
        """
        Check all alert thresholds for the current run.
        Returns list of triggered alerts.

        Each threshold in profile.alert_thresholds must have:
            label     : str   — human-readable identifier
            metric    : str   — key in baseline_history
            condition : str   — one of the 5 condition types
            value     : float — threshold value
            severity  : str   — "CRITICAL" | "HIGH" | "MEDIUM"
            message   : str   — human-readable template (informational)
        """
        triggered = []

        for threshold in (profile.alert_thresholds or []):
            metric_key = threshold.get("metric", "")
            condition = threshold.get("condition", "")
            thr_value = float(threshold.get("value", 0))

            # Resolve history for this metric
            history_entries = baseline_history.get(metric_key, [])
            if not history_entries:
                continue

            history_values = self._extract_numeric_series(history_entries)
            if not history_values:
                continue

            fired, computed = _evaluate_condition(condition, thr_value, history_values)

            latest = history_entries[-1]

            if fired:
                alert = {
                    "threshold_label": threshold.get("label", metric_key),
                    "metric":          metric_key,
                    "condition":       condition,
                    "computed_value":  computed,
                    "threshold_value": thr_value,
                    "severity":        threshold.get("severity", "MEDIUM"),
                    "message":         threshold.get("message", ""),
                    "triggered_at":    datetime.utcnow().isoformat(),
                    "period":          latest.get("period", ""),
                }
                triggered.append(alert)
                threshold["triggered"] = True
                threshold["last_triggered"] = datetime.utcnow().isoformat()
                logger.info("Alert threshold triggered", **{
                    k: v for k, v in alert.items() if k != "message"
                })
            else:
                threshold["triggered"] = False

        # Implicit alerts from CRITICAL agent findings
        for agent_result in findings.values():
            if not isinstance(agent_result, dict):
                continue
            for f in agent_result.get("findings", []):
                if f.get("severity", "").upper() == "CRITICAL":
                    triggered.append({
                        "threshold_label": f"Hallazgo crítico: {f.get('title', f.get('id', ''))}",
                        "metric":          "finding_severity",
                        "condition":       "implicit",
                        "computed_value":  "CRITICAL",
                        "threshold_value": None,
                        "severity":        "CRITICAL",
                        "triggered_at":    datetime.utcnow().isoformat(),
                        "finding_id":      f.get("id", ""),
                    })

        # Store in profile — cap at 20
        existing = profile.triggered_alerts or []
        profile.triggered_alerts = (existing + triggered)[-20:]
        return triggered

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _extract_numeric_series(self, entries: List[Dict]) -> List[float]:
        """Extract an ordered list of numeric values from baseline_history entries."""
        values: List[float] = []
        for entry in entries:
            v = entry.get("numeric_value")
            if v is None:
                v = self._extract_numeric(entry.get("value", ""))
            if v is not None:
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    pass
        return values

    def _extract_numeric(self, value_str: str) -> Optional[float]:
        nums = re.findall(r'[\d.,]+', str(value_str).replace(',', ''))
        for n in nums:
            try:
                return float(n)
            except ValueError:
                pass
        return None


# ---------------------------------------------------------------------------
# Default threshold factory
# ---------------------------------------------------------------------------

def create_default_thresholds(profile: "ClientProfile") -> List[Dict]:
    """
    Create sensible default alert thresholds for a new client based on their
    industry (profile.industry).

    Always added (all industries):
      - consecutive_zero_revenue : absolute_below 100

    Added for "distribución mayorista":
      - revenue_drop             : pct_change_below -15%
      - receivables_spike        : pct_change_above +25%
    """
    thresholds: List[Dict] = [
        {
            "label":     "consecutive_zero_revenue",
            "metric":    "total_revenue",
            "condition": "absolute_below",
            "value":     100.0,
            "severity":  "CRITICAL",
            "message":   "Revenue is near zero — possible data ingestion failure or genuine business halt.",
        },
    ]

    industry = (getattr(profile, "industry_inferred", None) or getattr(profile, "industry", None) or "").lower().strip()

    if industry == "distribución mayorista":
        thresholds += [
            {
                "label": "revenue_drop",
                "metric": "total_revenue",
                "condition": "pct_change_below",
                "value": -15.0,
                "severity": "HIGH",
                "message": "Revenue dropped more than 15% period-over-period.",
            },
            {
                "label":     "receivables_spike",
                "metric":    "total_receivables",
                "condition": "pct_change_above",
                "value":     25.0,
                "severity":  "HIGH",
                "message":   "Receivables grew more than 25% period-over-period — collection risk.",
            },
        ]

    return thresholds
