"""
AlertEngine — checks ClientProfile alert thresholds after each run.
Compares baseline KPIs against user-defined thresholds.
Stores triggered alerts in profile.triggered_alerts.
"""
from __future__ import annotations
import re
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime

import structlog

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile

logger = structlog.get_logger()


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
        """
        triggered = []

        for threshold in (profile.alert_thresholds or []):
            metric_label = threshold.get("metric", "")
            operator = threshold.get("operator", ">")
            threshold_value = threshold.get("value", 0)

            # Find current value in baseline_history
            history = baseline_history.get(metric_label, [])
            if not history:
                continue

            latest = history[-1]
            current_value = latest.get("numeric_value")
            if current_value is None:
                # Try to extract from string value
                current_value = self._extract_numeric(latest.get("value", ""))

            if current_value is None:
                continue

            # Check condition
            triggered_now = self._evaluate(current_value, operator, threshold_value)

            if triggered_now:
                alert = {
                    "threshold_label": threshold.get("label", metric_label),
                    "metric": metric_label,
                    "current_value": current_value,
                    "threshold_value": threshold_value,
                    "operator": operator,
                    "triggered_at": datetime.utcnow().isoformat(),
                    "period": latest.get("period", ""),
                }
                triggered.append(alert)
                threshold["triggered"] = True
                threshold["last_triggered"] = datetime.utcnow().isoformat()
                logger.info("Alert threshold triggered", **alert)
            else:
                threshold["triggered"] = False

        # Also check for CRITICAL findings as implicit alerts
        for agent_result in findings.values():
            if not isinstance(agent_result, dict):
                continue
            for f in agent_result.get("findings", []):
                if f.get("severity", "").upper() == "CRITICAL":
                    triggered.append({
                        "threshold_label": f"Hallazgo crítico: {f.get('title', f.get('id', ''))}",
                        "metric": "finding_severity",
                        "current_value": "CRITICAL",
                        "threshold_value": None,
                        "operator": "==",
                        "triggered_at": datetime.utcnow().isoformat(),
                        "finding_id": f.get("id", ""),
                    })

        # Store in profile (last 20)
        profile.triggered_alerts = (profile.triggered_alerts or [])[-19:] + triggered
        return triggered

    def _evaluate(self, current: float, operator: str, threshold: float) -> bool:
        ops = {
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: abs(a - b) < 1e-9,
        }
        fn = ops.get(operator)
        return fn(current, threshold) if fn else False

    def _extract_numeric(self, value_str: str) -> Optional[float]:
        nums = re.findall(r'[\d.,]+', str(value_str).replace(',', ''))
        for n in nums:
            try:
                return float(n)
            except ValueError:
                pass
        return None
