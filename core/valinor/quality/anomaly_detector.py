"""
AnomalyDetector — applies statistical tests to query results to flag suspicious data.
Complements the rule-based sentinel patterns with quantitative methods.
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class StatisticalAnomaly:
    query_id: str
    column: str
    method: str           # "iqr", "zscore", "benford"
    severity: str         # "HIGH" | "MEDIUM" | "LOW"
    description: str
    outlier_values: List  # top 3 outlier values
    outlier_count: int
    value_share: float    # fraction of total value in outliers


class AnomalyDetector:
    """
    Runs statistical anomaly detection on raw query results.
    Called after execute_queries() before agents see the data.
    """

    def scan(self, query_results: Dict[str, Any]) -> List[StatisticalAnomaly]:
        """Scan all query results for statistical anomalies."""
        anomalies = []
        for qid, result in query_results.get("results", {}).items():
            rows = result.get("rows", [])
            if len(rows) < 5:
                continue
            cols = result.get("columns", [])
            for col in cols:
                anomaly = self._check_column(qid, col, rows)
                if anomaly:
                    anomalies.append(anomaly)
        return anomalies

    def _check_column(self, qid: str, col: str, rows: List[Dict]) -> Optional[StatisticalAnomaly]:
        """Check a single column for anomalies."""
        # Only check numeric columns with "amount", "total", "price", "revenue" hints
        col_lower = col.lower()
        is_financial = any(
            h in col_lower
            for h in ['amount', 'total', 'price', 'revenue', 'importe', 'monto', 'grandtotal']
        )
        if not is_financial:
            return None

        values = []
        for row in rows:
            if isinstance(row, dict):
                v = row.get(col)
                try:
                    if v is not None and float(v) > 0:
                        values.append(float(v))
                except (ValueError, TypeError):
                    pass

        if len(values) < 10:
            return None

        arr = np.array(values)
        log_arr = np.log(arr)

        # 3x IQR fence on log-transformed values
        q1, q3 = np.percentile(log_arr, [25, 75])
        iqr = q3 - q1
        if iqr == 0:
            return None

        upper = q3 + 3 * iqr
        lower = q1 - 3 * iqr
        outlier_mask = (log_arr > upper) | (log_arr < lower)

        outlier_count = int(outlier_mask.sum())
        if outlier_count == 0:
            return None

        outlier_values = sorted(arr[outlier_mask].tolist(), reverse=True)[:3]
        value_share = float(arr[outlier_mask].sum() / arr.sum())

        if value_share > 0.20:
            severity = "HIGH"
        elif value_share > 0.05:
            severity = "MEDIUM"
        else:
            severity = "LOW"

        return StatisticalAnomaly(
            query_id=qid,
            column=col,
            method="iqr_3x_log",
            severity=severity,
            description=f"{outlier_count} outlier(s) en {col} representan {value_share:.1%} del total",
            outlier_values=outlier_values,
            outlier_count=outlier_count,
            value_share=value_share,
        )

    def format_for_agent(self, anomalies: List[StatisticalAnomaly]) -> str:
        """Format anomalies for injection into agent memory."""
        if not anomalies:
            return "Sin anomalías estadísticas detectadas en los datos."

        lines = [f"ANOMALÍAS ESTADÍSTICAS DETECTADAS ({len(anomalies)}):"]
        for a in sorted(anomalies, key=lambda x: x.value_share, reverse=True)[:5]:
            lines.append(
                f"  [{a.severity}] {a.query_id}/{a.column}: {a.description} "
                f"(valores atípicos: {[round(v, 0) for v in a.outlier_values]})"
            )
        return "\n".join(lines)


_detector: Optional[AnomalyDetector] = None


def get_anomaly_detector() -> AnomalyDetector:
    global _detector
    if _detector is None:
        _detector = AnomalyDetector()
    return _detector
