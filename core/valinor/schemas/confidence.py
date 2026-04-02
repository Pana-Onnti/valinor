"""
Confidence metadata schemas for Valinor analysis API response (VAL-97).

These Pydantic models capture trust scores and per-finding confidence
derived from the DataQualityGate, VerificationEngine, and query execution
metadata. They are included as an optional field in the API results JSON
for full transparency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class FindingConfidence(BaseModel):
    """Confidence metadata for a single finding or KPI."""

    level: Literal["verified", "estimated", "low_confidence"] = Field(
        description="Confidence tier derived from value_confidence + DQ score",
    )
    source_tables: List[str] = Field(
        default_factory=list,
        description="Tables that contributed data to this finding",
    )
    source_columns: List[str] = Field(
        default_factory=list,
        description="Key columns used in the finding's evidence",
    )
    record_count: int = Field(
        default=0,
        ge=0,
        description="Number of records backing this finding",
    )
    null_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of NULL values in source columns (0.0-1.0)",
    )
    dq_score: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Scaled DQ contribution (0.0-10.0) for this finding",
    )
    verification_method: str = Field(
        default="direct_query",
        description="How the finding was verified: direct_query, cross_agent, interpolation",
    )
    sql_query: str = Field(
        default="",
        description="The SQL query that produced the underlying data",
    )
    degradation_applied: bool = Field(
        default=False,
        description="True if the finding was degraded due to data quality issues",
    )
    degradation_reason: Optional[str] = Field(
        default=None,
        description="Why degradation was applied, if any",
    )


class TrustScoreBreakdown(BaseModel):
    """
    Weighted trust score computed from multiple quality dimensions.

    Component weights (total = 100):
      - dq_component: 0-30 (from DataQualityGate overall_score)
      - verification_component: 0-25 (from verification rate)
      - null_density_component: 0-15 (inverse of null density)
      - schema_coverage_component: 0-15 (entity coverage)
      - reconciliation_component: 0-15 (from swarm reconciliation)
    """

    overall: int = Field(
        ge=0,
        le=100,
        description="Aggregate trust score (0-100)",
    )
    dq_component: float = Field(
        default=0.0,
        ge=0.0,
        le=30.0,
        description="DQ gate contribution (0-30)",
    )
    verification_component: float = Field(
        default=0.0,
        ge=0.0,
        le=25.0,
        description="Verification engine contribution (0-25)",
    )
    null_density_component: float = Field(
        default=0.0,
        ge=0.0,
        le=15.0,
        description="Null density contribution (0-15, higher is better)",
    )
    schema_coverage_component: float = Field(
        default=0.0,
        ge=0.0,
        le=15.0,
        description="Schema/entity coverage contribution (0-15)",
    )
    reconciliation_component: float = Field(
        default=0.0,
        ge=0.0,
        le=15.0,
        description="Cross-agent reconciliation contribution (0-15)",
    )


class AnalysisConfidenceMetadata(BaseModel):
    """
    Top-level confidence metadata included in the API response.

    Backward-compatible: this is added as an optional field to results JSON.
    """

    trust_score: TrustScoreBreakdown = Field(
        description="Weighted trust score with component breakdown",
    )
    findings_confidence: Dict[str, FindingConfidence] = Field(
        default_factory=dict,
        description="Per-finding confidence keyed by finding ID (e.g. FIN-001)",
    )
    kpi_confidence: Dict[str, FindingConfidence] = Field(
        default_factory=dict,
        description="Per-KPI confidence keyed by KPI name",
    )
    analysis_timestamp: datetime = Field(
        description="When the analysis was completed",
    )
    total_queries_executed: int = Field(
        default=0,
        ge=0,
        description="Total number of SQL queries executed during the pipeline",
    )
    total_records_processed: int = Field(
        default=0,
        ge=0,
        description="Approximate total records processed across all queries",
    )
    pipeline_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Total pipeline wall-clock time in seconds",
    )
