"""
SegmentationEngine — detects and labels customer segments from query results.

For B2B distributors (the primary use case):
  Champions:   top 20% revenue customers (typically >€50K/yr)
  Growth:      middle 60%
  Maintenance: bottom 20% (at-risk, low engagement)

For other industries, uses equivalent tiers.
Segments are stored in ClientProfile and injected into agent context.
"""
from __future__ import annotations
import json
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass, asdict
from datetime import datetime

import structlog

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile

logger = structlog.get_logger()


@dataclass
class CustomerSegment:
    name: str           # "Champions", "Growth", "Maintenance"
    count: int
    total_revenue: float
    revenue_share: float  # 0.0 - 1.0
    avg_revenue: float
    top_customers: List[str]  # top 3 customer names
    currency: str = "USD"
    description: str = ""


@dataclass
class SegmentationResult:
    method: str           # "rfm_revenue", "percentile", "heuristic"
    segments: List[CustomerSegment]
    total_customers: int
    total_revenue: float
    computed_at: str
    industry: str
    thresholds: Dict[str, float]  # {"champion": 50000, "growth": 10000}


# ── Industry-specific segment names ──────────────────────────────────────────
SEGMENT_NAMES = {
    "distribución mayorista": {
        "top": "Champions",
        "mid": "Growth",
        "low": "Maintenance",
        "description_top": "Clientes con mayor volumen — proteger y profundizar",
        "description_mid": "Potencial de crecimiento — activar upsell",
        "description_low": "Clientes en riesgo — retención o salida",
    },
    "retail / punto de venta": {
        "top": "VIP",
        "mid": "Regulares",
        "low": "Ocasionales",
        "description_top": "Compradores frecuentes de alto ticket",
        "description_mid": "Base de clientes estable",
        "description_low": "Compradores esporádicos",
    },
    "servicios profesionales": {
        "top": "Cuentas Clave",
        "mid": "Cuentas Activas",
        "low": "Cuentas Latentes",
        "description_top": "Contratos de mayor valor anual",
        "description_mid": "Proyectos en curso",
        "description_low": "Sin actividad reciente",
    },
    "default": {
        "top": "Tier 1",
        "mid": "Tier 2",
        "low": "Tier 3",
        "description_top": "Clientes de alto valor",
        "description_mid": "Clientes de valor medio",
        "description_low": "Clientes de bajo valor",
    },
}


class SegmentationEngine:
    """
    Segments customers from query_results data.
    Uses revenue-based percentile segmentation (Pareto principle).
    """

    def segment_from_query_results(
        self,
        query_results: Dict[str, Any],
        profile: "ClientProfile",
    ) -> Optional[SegmentationResult]:
        """
        Extract customer revenue data from query results and compute segments.
        Returns None if insufficient data.
        """
        industry = profile.industry_inferred or "default"
        currency = profile.currency_detected or "USD"
        names = SEGMENT_NAMES.get(industry, SEGMENT_NAMES["default"])

        # Try to find customer revenue data in query results
        customer_revenue = self._extract_customer_revenue(query_results)
        if not customer_revenue:
            logger.info("SegmentationEngine: no customer revenue data found")
            return None

        return self._compute_segments(customer_revenue, names, currency, industry)

    def _extract_customer_revenue(self, query_results: Dict[str, Any]) -> List[Tuple[str, float]]:
        """
        Extract (customer_name, total_revenue) pairs from query results.
        Looks for common patterns in result sets.
        """
        pairs = []
        for result in query_results.get("results", {}).values():
            rows = result.get("rows", [])
            if not rows:
                continue

            columns = result.get("columns", [])
            if not columns and rows:
                columns = list(rows[0].keys()) if isinstance(rows[0], dict) else []

            # Look for customer name + revenue pattern
            name_col = self._find_column(columns, ["name", "nombre", "customer", "bpartner", "cliente", "partner"])
            rev_col = self._find_column(columns, ["grandtotal", "total", "revenue", "amount", "importe", "facturacion", "ventas"])

            if name_col and rev_col:
                for row in rows:
                    if isinstance(row, dict):
                        name = str(row.get(name_col, ""))
                        try:
                            rev = float(row.get(rev_col, 0) or 0)
                            if name and rev > 0:
                                pairs.append((name, rev))
                        except (ValueError, TypeError):
                            pass

        # Sort by revenue descending
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:500]  # cap at 500 customers

    def _find_column(self, columns: List[str], hints: List[str]) -> Optional[str]:
        """Find a column name that matches any hint."""
        for hint in hints:
            for col in columns:
                if hint.lower() in col.lower():
                    return col
        return None

    def _compute_segments(
        self,
        customer_revenue: List[Tuple[str, float]],
        names: Dict[str, str],
        currency: str,
        industry: str,
    ) -> SegmentationResult:
        """
        Segment using Pareto-based percentile method.
        Top 20% customers → Champions
        Next 60% → Growth
        Bottom 20% → Maintenance
        """
        if not customer_revenue:
            return SegmentationResult(
                method="empty", segments=[], total_customers=0,
                total_revenue=0, computed_at=datetime.utcnow().isoformat(),
                industry=industry, thresholds={}
            )

        total_revenue = sum(r for _, r in customer_revenue)
        n = len(customer_revenue)

        # Percentile thresholds
        top_n = max(1, int(n * 0.2))
        mid_n = max(1, int(n * 0.6))

        top_customers = customer_revenue[:top_n]
        mid_customers = customer_revenue[top_n:top_n + mid_n]
        low_customers = customer_revenue[top_n + mid_n:]

        def make_segment(name: str, customers: List, desc: str) -> CustomerSegment:
            rev = sum(r for _, r in customers)
            return CustomerSegment(
                name=name,
                count=len(customers),
                total_revenue=rev,
                revenue_share=rev / total_revenue if total_revenue > 0 else 0,
                avg_revenue=rev / len(customers) if customers else 0,
                top_customers=[c[0] for c in customers[:3]],
                currency=currency,
                description=desc,
            )

        segments = [
            make_segment(names["top"], top_customers, names["description_top"]),
            make_segment(names["mid"], mid_customers, names["description_mid"]),
            make_segment(names["low"], low_customers, names["description_low"]),
        ]

        # Compute thresholds
        champion_threshold = top_customers[-1][1] if top_customers else 0
        growth_threshold = mid_customers[-1][1] if mid_customers else 0

        logger.info(
            "Segmentation computed",
            industry=industry,
            total_customers=n,
            segments={s.name: s.count for s in segments},
        )

        return SegmentationResult(
            method="pareto_percentile",
            segments=segments,
            total_customers=n,
            total_revenue=total_revenue,
            computed_at=datetime.utcnow().isoformat(),
            industry=industry,
            thresholds={
                names["top"]: champion_threshold,
                names["mid"]: growth_threshold,
            },
        )

    def build_context_block(self, result: SegmentationResult, currency: str = "USD") -> str:
        """
        Build a context block for injection into agent prompts.
        Example:
          SEGMENTACIÓN DE CLIENTES:
          - Champions (42 clientes, 78% del revenue): Nexum SL, Distribuciones Pepe...
          - Growth (156 clientes, 18% del revenue): ...
          - Maintenance (89 clientes, 4% del revenue): en riesgo
        """
        if not result.segments:
            return ""

        lines = ["SEGMENTACIÓN DE CLIENTES (análisis actual):"]
        for seg in result.segments:
            top_str = ", ".join(seg.top_customers[:2]) if seg.top_customers else "—"
            lines.append(
                f"  - {seg.name}: {seg.count} clientes, "
                f"{seg.revenue_share*100:.0f}% del revenue "
                f"({currency} {seg.total_revenue:,.0f} total). "
                f"Top: {top_str}. {seg.description}"
            )

        lines.append(f"  Umbral {result.segments[0].name}: {currency} {list(result.thresholds.values())[0]:,.0f}/período")
        return "\n".join(lines)

    def update_profile_segments(
        self,
        profile: "ClientProfile",
        result: SegmentationResult,
    ):
        """Store segmentation result in profile for historical tracking."""
        if not hasattr(profile, 'segmentation_history'):
            profile.__dict__['segmentation_history'] = []

        history = profile.__dict__.get('segmentation_history', [])
        history.append({
            "computed_at": result.computed_at,
            "total_customers": result.total_customers,
            "total_revenue": result.total_revenue,
            "segments": {s.name: {"count": s.count, "revenue_share": s.revenue_share} for s in result.segments},
        })
        profile.__dict__['segmentation_history'] = history[-12:]  # last 12 periods


# Module singleton
_engine: Optional[SegmentationEngine] = None

def get_segmentation_engine() -> SegmentationEngine:
    global _engine
    if _engine is None:
        _engine = SegmentationEngine()
    return _engine
