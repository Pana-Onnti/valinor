"""
FactorModel — decomposes revenue into observable business drivers.

Revenue_t = client_count_t × avg_ticket_t × transaction_frequency_t × seasonality_t × trend_t + residual_t

If residual > 2σ, the revenue figure is anomalous conditional on known factors.
This is more powerful than a simple z-score because it accounts for growth.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass
class FactorDecomposition:
    period: str

    # Observed values
    total_revenue: float
    client_count: int
    avg_ticket: float
    transaction_count: int

    # Factor model components
    expected_revenue: float      # from factor model
    residual: float              # total_revenue - expected_revenue
    residual_z_score: float      # z-score of residual vs historical

    # Factor contributions (% change YoY or QoQ)
    client_count_contribution: float   # how much of revenue change is due to client count
    avg_ticket_contribution: float     # how much is due to pricing
    frequency_contribution: float      # how much is due to transaction frequency

    # Interpretation
    primary_driver: str                # "client_count" | "avg_ticket" | "frequency" | "residual"
    anomaly_detected: bool
    anomaly_description: str = ""


class RevenueFactorModel:
    """
    Decomposes revenue changes into business factor contributions.
    Uses simple multiplicative decomposition:
    Revenue = client_count × avg_ticket × transactions_per_client
    """

    def __init__(self, engine):
        self.engine = engine

    def compute_decomposition(self, period_start: str, period_end: str,
                               prior_period_start: str, prior_period_end: str) -> Optional[FactorDecomposition]:
        """
        Compute factor decomposition for current period vs prior period.
        Returns None if insufficient data.
        """
        current = self._get_period_metrics(period_start, period_end)
        prior = self._get_period_metrics(prior_period_start, prior_period_end)

        if not current or not prior or prior["client_count"] == 0:
            return None

        # Factor model: Revenue = clients × avg_ticket × transactions_per_client
        expected_revenue = (
            prior["total_revenue"] *
            (current["client_count"] / max(prior["client_count"], 1)) *
            (current["avg_ticket"] / max(prior["avg_ticket"], 0.01)) *
            (current["transactions_per_client"] / max(prior["transactions_per_client"], 0.01))
        )

        residual = current["total_revenue"] - expected_revenue

        # Factor contributions (Shapley-like attribution)
        # How much of the revenue change is explained by each factor?
        rev_change = current["total_revenue"] - prior["total_revenue"]
        if abs(rev_change) < 0.001:
            client_contrib = avg_ticket_contrib = freq_contrib = 0.0
        else:
            client_factor = (current["client_count"] - prior["client_count"]) / prior["client_count"]
            ticket_factor = (current["avg_ticket"] - prior["avg_ticket"]) / prior["avg_ticket"]
            freq_factor = (current["transactions_per_client"] - prior["transactions_per_client"]) / prior["transactions_per_client"]
            total_factor = abs(client_factor) + abs(ticket_factor) + abs(freq_factor)
            if total_factor > 0:
                client_contrib = client_factor / total_factor
                avg_ticket_contrib = ticket_factor / total_factor
                freq_contrib = freq_factor / total_factor
            else:
                client_contrib = avg_ticket_contrib = freq_contrib = 0.0

        # Determine primary driver
        contributions = {
            "client_count": abs(client_contrib),
            "avg_ticket": abs(avg_ticket_contrib),
            "frequency": abs(freq_contrib),
        }
        primary_driver = max(contributions, key=contributions.get)

        # Residual z-score (simplified — in production use historical residuals)
        # For now: residual > 15% of expected revenue is anomalous
        residual_pct = abs(residual) / max(abs(expected_revenue), 1)
        residual_z = residual_pct / 0.05  # assume 5% std for residuals
        anomaly = residual_pct > 0.15

        description = ""
        if anomaly:
            direction = "mayor" if residual > 0 else "menor"
            description = (
                f"Revenue {direction} de lo esperado por factores conocidos en {residual_pct:.1%}. "
                f"Factor principal: {primary_driver}. Investigar causas externas al modelo."
            )

        logger.info(
            "Factor decomposition computed",
            expected=f"{expected_revenue:,.0f}",
            actual=f"{current['total_revenue']:,.0f}",
            residual_pct=f"{residual_pct:.1%}",
            primary_driver=primary_driver,
        )

        return FactorDecomposition(
            period=f"{period_start}/{period_end}",
            total_revenue=current["total_revenue"],
            client_count=current["client_count"],
            avg_ticket=current["avg_ticket"],
            transaction_count=current["transaction_count"],
            expected_revenue=expected_revenue,
            residual=residual,
            residual_z_score=residual_z,
            client_count_contribution=client_contrib,
            avg_ticket_contribution=avg_ticket_contrib,
            frequency_contribution=freq_contrib,
            primary_driver=primary_driver,
            anomaly_detected=anomaly,
            anomaly_description=description,
        )

    def _get_period_metrics(self, start: str, end: str) -> Optional[Dict]:
        """Extract factor metrics for a period."""
        from sqlalchemy import text
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT
                        COALESCE(SUM(am.amount_untaxed), 0) as total_revenue,
                        COUNT(DISTINCT am.partner_id) as client_count,
                        COUNT(*) as transaction_count,
                        CASE WHEN COUNT(*) > 0
                             THEN COALESCE(SUM(am.amount_untaxed), 0) / COUNT(*)
                             ELSE 0 END as avg_ticket,
                        CASE WHEN COUNT(DISTINCT am.partner_id) > 0
                             THEN COUNT(*)::float / COUNT(DISTINCT am.partner_id)
                             ELSE 0 END as transactions_per_client
                    FROM account_move am
                    WHERE am.move_type = 'out_invoice'
                    AND am.state = 'posted'
                    AND am.invoice_date BETWEEN :start AND :end
                """), {"start": start, "end": end}).fetchone()

                if result:
                    return {
                        "total_revenue": float(result[0] or 0),
                        "client_count": int(result[1] or 0),
                        "transaction_count": int(result[2] or 0),
                        "avg_ticket": float(result[3] or 0),
                        "transactions_per_client": float(result[4] or 0),
                    }
        except Exception as e:
            logger.warning("Factor model query failed", error=str(e))
        return None

    def format_context_block(self, decomp: FactorDecomposition) -> str:
        """Format factor decomposition for injection into agent memory."""
        lines = [
            "DESCOMPOSICION POR FACTORES (vs periodo anterior):",
            f"  Revenue esperado (modelo): {decomp.expected_revenue:,.0f}",
            f"  Revenue real: {decomp.total_revenue:,.0f}",
            f"  Residual: {decomp.residual:+,.0f} ({decomp.residual / max(abs(decomp.expected_revenue),1)*100:+.1f}%)",
            f"  Factor dominante: {decomp.primary_driver}",
            f"  Clientes: {decomp.client_count} ({decomp.client_count_contribution*100:+.0f}% del cambio)",
            f"  Ticket promedio: {decomp.avg_ticket:,.0f} ({decomp.avg_ticket_contribution*100:+.0f}% del cambio)",
        ]
        if decomp.anomaly_detected:
            lines.append(f"  ANOMALIA: {decomp.anomaly_description}")
        return "\n".join(lines)
