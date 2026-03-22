"""
Cash Flow Forecaster — VAL-37: Cash flow forecasting from AR aging + revenue trends.

Deterministic Python module (not an LLM agent) that:
  1. Queries accounts receivable aging buckets (0-30, 31-60, 61-90, 90+ days)
  2. Queries revenue trends (monthly totals)
  3. Calculates a simple cash flow forecast (weighted AR collection + trend projection)

Uses entity_map to find the right tables/columns — no hardcoded ERP knowledge.
"""

from __future__ import annotations

import logging
from typing import Any

from valinor.schemas.agent_outputs import (
    AgingBucket,
    CashFlowForecast,
    RevenueTrendPoint,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# COLLECTION PROBABILITY WEIGHTS — industry standard defaults
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_COLLECTION_WEIGHTS = {
    "0-30d": 0.95,
    "31-60d": 0.85,
    "61-90d": 0.70,
    "90+d": 0.40,
}


# ═══════════════════════════════════════════════════════════════════════════
# CASH FLOW FORECASTER
# ═══════════════════════════════════════════════════════════════════════════


class CashFlowForecaster:
    """
    Produces a cash flow forecast from AR aging data and revenue trends.

    Two components:
      1. AR Collection Forecast: weighted sum of aging buckets by collection probability
      2. Revenue Trend Projection: simple linear projection from recent months

    The forecast for each horizon (30d, 60d, 90d) combines both signals.
    """

    def __init__(
        self,
        query_results: dict,
        entity_map: dict,
        baseline: dict,
        collection_weights: dict[str, float] | None = None,
    ) -> None:
        self.query_results = query_results
        self.entity_map = entity_map
        self.baseline = baseline
        self.collection_weights = collection_weights or DEFAULT_COLLECTION_WEIGHTS

    def forecast(self) -> CashFlowForecast:
        """
        Main entry point: compute the cash flow forecast.

        Returns:
            CashFlowForecast with 30/60/90 day projections.
        """
        warnings: list[str] = []

        # Step 1: Extract AR aging buckets from query results
        aging_buckets = self._extract_aging_buckets()
        if not aging_buckets:
            warnings.append(
                "No AR aging data available — forecast relies solely on revenue trend."
            )

        # Step 2: Extract revenue trend from query results
        revenue_trend = self._extract_revenue_trend()
        if not revenue_trend:
            warnings.append(
                "No revenue trend data available — forecast relies solely on AR aging."
            )

        # Step 3: Compute AR-based forecast (weighted collection)
        ar_forecast_30d, ar_forecast_60d, ar_forecast_90d = self._compute_ar_forecast(
            aging_buckets
        )

        # Step 4: Compute trend-based forecast (linear projection)
        trend_forecast_monthly = self._compute_trend_projection(revenue_trend)

        # Step 5: Combine both signals
        forecast_30d, forecast_60d, forecast_90d = self._combine_forecasts(
            ar_forecast_30d,
            ar_forecast_60d,
            ar_forecast_90d,
            trend_forecast_monthly,
            has_ar=bool(aging_buckets),
            has_trend=bool(revenue_trend),
        )

        # Step 6: Compute confidence
        confidence = self._compute_confidence(aging_buckets, revenue_trend)

        logger.info(
            "Cash flow forecast computed",
            forecast_30d=forecast_30d,
            forecast_60d=forecast_60d,
            forecast_90d=forecast_90d,
            confidence=confidence,
            aging_buckets=len(aging_buckets),
            trend_months=len(revenue_trend),
        )

        return CashFlowForecast(
            forecast_30d=round(forecast_30d, 2),
            forecast_60d=round(forecast_60d, 2),
            forecast_90d=round(forecast_90d, 2),
            confidence=confidence,
            aging_buckets=aging_buckets,
            revenue_trend=revenue_trend,
            methodology="weighted_ar_plus_trend",
            warnings=warnings,
        )

    # ── DATA EXTRACTION ───────────────────────────────────────────────

    def _extract_aging_buckets(self) -> list[AgingBucket]:
        """Extract AR aging buckets from query results."""
        results = self.query_results.get("results", {})

        # Try aging_analysis query result first
        aging_data = results.get("aging_analysis", {})
        rows = aging_data.get("rows", [])
        if not rows:
            return []

        buckets: list[AgingBucket] = []
        bucket_mapping = self._build_bucket_mapping()

        for row in rows:
            tramo = str(row.get("tramo", "")).strip()
            amount = row.get("total_amount")
            count = row.get("num_payments", 0)

            if amount is None:
                continue

            try:
                amount_f = float(amount)
            except (TypeError, ValueError):
                continue

            # Map the tramo label to our standard bucket names
            standard_bucket = self._normalize_bucket(tramo, bucket_mapping)
            if standard_bucket == "not_due":
                # Not-due items will be collected naturally; include in 30d
                standard_bucket = "0-30d"

            weight = self.collection_weights.get(standard_bucket, 0.50)

            buckets.append(
                AgingBucket(
                    bucket=standard_bucket,
                    amount=amount_f,
                    count=int(count) if count else 0,
                    collection_probability=weight,
                )
            )

        # Merge duplicate buckets (e.g., 'not_due' merged into '0-30d')
        return self._merge_buckets(buckets)

    def _extract_revenue_trend(self) -> list[RevenueTrendPoint]:
        """Extract monthly revenue trend from query results."""
        results = self.query_results.get("results", {})

        # Try revenue_trend query result
        trend_data = results.get("revenue_trend", {})
        rows = trend_data.get("rows", [])
        if not rows:
            return []

        points: list[RevenueTrendPoint] = []
        for row in rows:
            month_raw = row.get("month", "")
            revenue = row.get("revenue")
            invoice_count = row.get("invoice_count", 0)
            mom_growth = row.get("mom_growth_pct")

            if revenue is None:
                continue

            try:
                revenue_f = float(revenue)
            except (TypeError, ValueError):
                continue

            # Normalize month to YYYY-MM format
            month_str = str(month_raw)[:10]
            if len(month_str) >= 7:
                month_str = month_str[:7]
            else:
                continue

            points.append(
                RevenueTrendPoint(
                    month=month_str,
                    revenue=revenue_f,
                    invoice_count=int(invoice_count) if invoice_count else 0,
                    mom_growth_pct=float(mom_growth) if mom_growth is not None else None,
                )
            )

        return points

    # ── FORECAST COMPUTATION ──────────────────────────────────────────

    def _compute_ar_forecast(
        self, buckets: list[AgingBucket]
    ) -> tuple[float, float, float]:
        """
        Compute AR-based cash forecast for 30/60/90 day horizons.

        Logic:
          - 30d: 0-30d bucket * collection_probability
          - 60d: 30d + 31-60d bucket * collection_probability
          - 90d: 60d + 61-90d bucket * collection_probability
        """
        if not buckets:
            return 0.0, 0.0, 0.0

        bucket_map: dict[str, float] = {}
        for b in buckets:
            weighted = b.amount * b.collection_probability
            bucket_map[b.bucket] = bucket_map.get(b.bucket, 0.0) + weighted

        forecast_30d = bucket_map.get("0-30d", 0.0)
        forecast_60d = forecast_30d + bucket_map.get("31-60d", 0.0)
        forecast_90d = forecast_60d + bucket_map.get("61-90d", 0.0)

        return forecast_30d, forecast_60d, forecast_90d

    def _compute_trend_projection(
        self, trend: list[RevenueTrendPoint]
    ) -> float:
        """
        Compute monthly revenue projection from trend data.

        Uses the average of the last 3 months (or whatever is available)
        as the projected monthly revenue.
        """
        if not trend:
            return 0.0

        # Use last 3 months for projection
        recent = trend[-3:] if len(trend) >= 3 else trend
        avg_revenue = sum(p.revenue for p in recent) / len(recent)

        return avg_revenue

    def _combine_forecasts(
        self,
        ar_30d: float,
        ar_60d: float,
        ar_90d: float,
        trend_monthly: float,
        has_ar: bool,
        has_trend: bool,
    ) -> tuple[float, float, float]:
        """
        Combine AR-based and trend-based forecasts.

        When both signals are available:
          - 30d: 70% AR + 30% trend (AR is more reliable short-term)
          - 60d: 50% AR + 50% trend
          - 90d: 30% AR + 70% trend (trend is more reliable long-term)

        When only one signal is available, use it entirely.
        """
        if has_ar and has_trend:
            trend_30d = trend_monthly * (30 / 30)  # 1 month
            trend_60d = trend_monthly * (60 / 30)  # 2 months
            trend_90d = trend_monthly * (90 / 30)  # 3 months

            combined_30d = ar_30d * 0.70 + trend_30d * 0.30
            combined_60d = ar_60d * 0.50 + trend_60d * 0.50
            combined_90d = ar_90d * 0.30 + trend_90d * 0.70

            return combined_30d, combined_60d, combined_90d

        if has_ar:
            return ar_30d, ar_60d, ar_90d

        if has_trend:
            return (
                trend_monthly * (30 / 30),
                trend_monthly * (60 / 30),
                trend_monthly * (90 / 30),
            )

        return 0.0, 0.0, 0.0

    def _compute_confidence(
        self, buckets: list[AgingBucket], trend: list[RevenueTrendPoint]
    ) -> float:
        """
        Compute overall confidence in the forecast.

        Factors:
          - Has AR data: +0.3
          - Has trend data: +0.3
          - Trend length >= 6 months: +0.2
          - Trend length >= 3 months: +0.1
          - Baseline has data: +0.1
        """
        score = 0.0

        if buckets:
            score += 0.30
        if trend:
            score += 0.30
            if len(trend) >= 6:
                score += 0.20
            elif len(trend) >= 3:
                score += 0.10

        if self.baseline.get("data_available"):
            score += 0.10

        return min(1.0, round(score, 2))

    # ── HELPERS ───────────────────────────────────────────────────────

    @staticmethod
    def _build_bucket_mapping() -> dict[str, str]:
        """Build a mapping from various aging labels to standard bucket names."""
        return {
            "not_due": "not_due",
            "0-30d": "0-30d",
            "0-30": "0-30d",
            "31-60d": "31-60d",
            "31-60": "31-60d",
            "61-90d": "61-90d",
            "61-90": "61-90d",
            "91-180d": "90+d",
            "91-180": "90+d",
            "181-365d": "90+d",
            "181-365": "90+d",
            ">365d": "90+d",
            ">365": "90+d",
        }

    @staticmethod
    def _normalize_bucket(tramo: str, mapping: dict[str, str]) -> str:
        """Normalize an aging bucket label to a standard name."""
        normalized = tramo.strip().lower()
        if normalized in mapping:
            return mapping[normalized]
        # Fallback: try to parse the bucket from the label
        if "30" in normalized and ("0" in normalized or "not" not in normalized):
            return "0-30d"
        if "60" in normalized:
            return "31-60d"
        if "90" in normalized and "+" not in normalized and ">" not in normalized:
            return "61-90d"
        return "90+d"

    @staticmethod
    def _merge_buckets(buckets: list[AgingBucket]) -> list[AgingBucket]:
        """Merge buckets with the same name."""
        merged: dict[str, AgingBucket] = {}
        for b in buckets:
            if b.bucket in merged:
                existing = merged[b.bucket]
                total_amount = existing.amount + b.amount
                total_count = existing.count + b.count
                # Weighted average of collection probability
                if total_amount > 0:
                    weighted_prob = (
                        existing.amount * existing.collection_probability
                        + b.amount * b.collection_probability
                    ) / total_amount
                else:
                    weighted_prob = existing.collection_probability
                merged[b.bucket] = AgingBucket(
                    bucket=b.bucket,
                    amount=total_amount,
                    count=total_count,
                    collection_probability=round(weighted_prob, 4),
                )
            else:
                merged[b.bucket] = b

        # Return in standard order
        order = ["0-30d", "31-60d", "61-90d", "90+d"]
        result = []
        for key in order:
            if key in merged:
                result.append(merged[key])
        # Add any remaining
        for key, bucket in merged.items():
            if key not in order:
                result.append(bucket)
        return result


def run_cash_flow_forecast(
    query_results: dict,
    entity_map: dict,
    baseline: dict,
) -> CashFlowForecast:
    """
    Convenience function: run the cash flow forecaster and return the result.

    This is the pipeline hook point — called after query execution (Stage 2.5)
    and baseline computation.
    """
    forecaster = CashFlowForecaster(query_results, entity_map, baseline)
    return forecaster.forecast()
