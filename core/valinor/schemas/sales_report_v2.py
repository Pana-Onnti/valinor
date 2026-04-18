"""
Sales Report v2 schema — structured JSON output for the sales narrator.

The frontend renders this directly with recharts (no markdown parsing).
Every numeric field carries a ValueConfidence marker so the UI can show
[MEDIDO] / [ESTIMADO] / [INFERIDO] badges next to each value.

Refs: VAL-141
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from valinor.schemas.agent_outputs import ValueConfidence


class RFMSegment(str, Enum):
    """Standard 11-segment RFM taxonomy for B2B distribution."""

    CHAMPIONS = "champions"
    LOYAL = "loyal"
    POTENTIAL_LOYALISTS = "potential_loyalists"
    NEW_CUSTOMERS = "new_customers"
    PROMISING = "promising"
    NEED_ATTENTION = "need_attention"
    ABOUT_TO_SLEEP = "about_to_sleep"
    AT_RISK = "at_risk"
    CANNOT_LOSE = "cannot_lose"
    HIBERNATING = "hibernating"
    LOST = "lost"


class ConcentrationLevel(str, Enum):
    DIVERSIFIED = "diversified"
    MODERATE = "moderate"
    HIGH_RISK = "high_risk"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class KPITile(BaseModel):
    """One tile in the KPI bar header."""

    label: str
    value: str
    sub: Optional[str] = None
    confidence: ValueConfidence = ValueConfidence.MEASURED
    trend_pct: Optional[float] = Field(None, description="MoM % change if applicable")


class RFMSegmentSummary(BaseModel):
    """One row in the RFM segment grid."""

    segment: RFMSegment
    count: int = Field(ge=0)
    revenue_share_pct: float = Field(ge=0, le=100)
    avg_ltv: float = Field(ge=0)
    recommended_action: str
    confidence: ValueConfidence = ValueConfidence.MEASURED


class ConcentrationReport(BaseModel):
    """Herfindahl-Hirschman Index + Concentration Ratios."""

    hhi: float = Field(default=0.0, ge=0, le=10000, description="HHI 0-10000")
    hhi_level: ConcentrationLevel = ConcentrationLevel.DIVERSIFIED
    cr1_pct: float = Field(default=0.0, ge=0, le=100, description="% revenue from top 1")
    cr5_pct: float = Field(default=0.0, ge=0, le=100, description="% revenue from top 5")
    cr10_pct: float = Field(default=0.0, ge=0, le=100, description="% revenue from top 10")
    total_customers: int = Field(default=0, ge=0)
    interpretation: str = Field(default="", description="One-sentence human-readable interpretation")
    confidence: ValueConfidence = ValueConfidence.INFERRED

    @model_validator(mode="before")
    @classmethod
    def _coerce_nulls_to_defaults(cls, data: Any) -> Any:
        """Accept LLM-emitted nulls by dropping them — Pydantic then applies field defaults."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class TopCustomerRow(BaseModel):
    """One row in the top-N customer concentration table."""

    customer_name: str
    customer_id: Optional[str] = None
    ltv_eur: float = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)
    last_purchase: str = Field(description="YYYY-MM-DD or 'N/A'")
    risk: RiskLevel
    confidence: ValueConfidence = ValueConfidence.MEASURED


class MagicMatrixCell(BaseModel):
    """One cell in the RFM segment × category cross-sell matrix."""

    segment: RFMSegment
    category: str
    penetration_pct: float = Field(ge=0, le=100, description="% of segment that buys this category")
    gap_opportunity_eur: float = Field(ge=0, description="Estimated € if gap closed to segment leader")
    confidence: ValueConfidence = ValueConfidence.ESTIMATED


class CallListEntry(BaseModel):
    """One entry in the prioritized call list (for dormants / at-risk)."""

    rank: int = Field(ge=1)
    customer_name: str
    customer_id: Optional[str] = None
    deal_risk_score: float = Field(ge=0, le=100, description="0-100 probability-weighted priority")
    last_purchase: str
    ltv_eur: float = Field(ge=0)
    recovery_potential_eur: float = Field(ge=0)
    recovery_confidence: ValueConfidence = ValueConfidence.ESTIMATED
    reason: str = Field(description="Why they're on the list (one sentence)")
    script_hint: str = Field(description="Talking point for the call")


class CategoryPerformance(BaseModel):
    """Category-level revenue performance with MoM trend."""

    category: str
    revenue_eur: float = Field(ge=0)
    share_pct: float = Field(ge=0, le=100)
    mom_pct: float = Field(description="Month-over-month % change (can be negative)")
    trend: str = Field(description="sube | estable | baja | caida")
    confidence: ValueConfidence = ValueConfidence.MEASURED


class SalesReportV2(BaseModel):
    """
    Complete structured sales report — consumed directly by SalesReportV2.tsx.

    The narrator MUST emit this schema as JSON. No markdown, no prose outside
    the structured fields (titles/descriptions are prose but typed).
    """

    model_config = ConfigDict(use_enum_values=True)

    client_name: str
    period: str = Field(description="e.g. '2025-07 to 2026-06' or 'FY2025'")
    currency: str = Field(default="EUR")
    generated_at: str = Field(description="ISO timestamp")

    kpi_bar: List[KPITile] = Field(description="4-5 header KPIs")
    rfm_segments: List[RFMSegmentSummary] = Field(description="Up to 11 segments")
    concentration: ConcentrationReport
    top_customers: List[TopCustomerRow] = Field(description="Top 7-10 customers")
    category_performance: List[CategoryPerformance]
    magic_matrix: List[MagicMatrixCell] = Field(description="RFM × category cells")
    call_list: List[CallListEntry] = Field(description="Top-N prioritized by deal risk score")

    executive_summary: str = Field(description="3-5 sentence summary for header/email")
    data_caveats: List[str] = Field(
        default_factory=list,
        description="Data freshness, missing queries, low-confidence warnings",
    )
