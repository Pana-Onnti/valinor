"""
Pydantic-AI type-safe output schemas for Valinor swarm agents (VAL-30).

These models are the canonical output types for the 4 core agents.
All agents MUST return these types — callers can rely on .model_validate()
or isinstance() checks instead of dict key access.

Pydantic v2 models (compatible with pydantic-ai >=1.0).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Shared enums / primitives
# ═══════════════════════════════════════════════════════════════════════════


class EntityType(str, Enum):
    MASTER = "MASTER"
    TRANSACTIONAL = "TRANSACTIONAL"
    CONFIG = "CONFIG"
    BRIDGE = "BRIDGE"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    OPPORTUNITY = "opportunity"
    INFO = "info"


class ValueConfidence(str, Enum):
    MEASURED = "measured"
    ESTIMATED = "estimated"
    INFERRED = "inferred"


# ═══════════════════════════════════════════════════════════════════════════
# CartographerOutput — Stage 1: Schema Discovery
# ═══════════════════════════════════════════════════════════════════════════


class EntityDefinition(BaseModel):
    """Single entity (table) discovered by the Cartographer."""

    table: str = Field(description="Actual table name in the database")
    entity_type: EntityType = Field(
        default=EntityType.UNKNOWN,
        description="Classification of the table: MASTER / TRANSACTIONAL / CONFIG / BRIDGE",
    )
    row_count: int = Field(default=0, ge=0, description="Approximate row count")
    key_columns: Dict[str, str] = Field(
        default_factory=dict,
        description="Semantic column mapping, e.g. {'invoice_date': 'dateacct', ...}",
    )
    base_filter: str = Field(
        default="",
        description="SQL fragment to filter to the correct tenant/direction, e.g. \"AND issotrx = 'Y'\"",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence that this entity was correctly identified (0–1)",
    )

    @field_validator("base_filter")
    @classmethod
    def strip_base_filter(cls, v: str) -> str:
        return v.strip()


class CartographerOutput(BaseModel):
    """
    Output of the Cartographer agent (Stage 1).

    Contains the complete entity map: all discovered entities, their relationships,
    and metadata about the discovery run.
    """

    client: str = Field(description="Client/tenant identifier")
    status: str = Field(
        default="complete",
        description="Discovery status: 'complete' | 'partial' | 'failed'",
    )
    entities: Dict[str, EntityDefinition] = Field(
        default_factory=dict,
        description="Discovered entities keyed by semantic name (e.g. 'invoices', 'customers')",
    )
    relationships: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of {from, to, via} relationship dicts",
    )
    phase1_tables_probed: int = Field(
        default=0,
        ge=0,
        description="Number of tables probed in Phase 1 deterministic prescan",
    )
    is_retry: bool = Field(
        default=False,
        description="True if this was a retry after calibration feedback",
    )
    raw_output: Optional[str] = Field(
        default=None,
        description="Raw LLM text output (for debugging)",
    )

    @classmethod
    def from_entity_map_dict(cls, d: Dict[str, Any]) -> "CartographerOutput":
        """
        Build a CartographerOutput from the legacy entity_map dict format.
        Backward-compatible factory method.
        """
        entities = {}
        for name, cfg in d.get("entities", {}).items():
            entities[name] = EntityDefinition(
                table=cfg.get("table", name),
                entity_type=EntityType(cfg.get("entity_type", EntityType.UNKNOWN)),
                row_count=int(cfg.get("row_count", 0)),
                key_columns=cfg.get("key_columns", {}),
                base_filter=cfg.get("base_filter", ""),
                confidence=float(cfg.get("confidence", 0.0)),
            )

        prescan = d.get("_phase1_prescan", {})
        return cls(
            client=d.get("client", "unknown"),
            status=d.get("status", "complete"),
            entities=entities,
            relationships=d.get("relationships", []),
            phase1_tables_probed=int(prescan.get("tables_probed", 0)),
            is_retry=bool(prescan.get("retry_attempt", False)),
        )

    def to_entity_map_dict(self) -> Dict[str, Any]:
        """Convert back to the legacy entity_map dict format for downstream agents."""
        return {
            "client": self.client,
            "status": self.status,
            "entities": {
                name: {
                    "table": e.table,
                    "entity_type": e.entity_type.value,
                    "row_count": e.row_count,
                    "key_columns": e.key_columns,
                    "base_filter": e.base_filter,
                    "confidence": e.confidence,
                }
                for name, e in self.entities.items()
            },
            "relationships": self.relationships,
            "_phase1_prescan": {
                "tables_probed": self.phase1_tables_probed,
                "retry_attempt": self.is_retry,
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
# QueryBuilderOutput — Stage 2: SQL Generation
# ═══════════════════════════════════════════════════════════════════════════


class CompiledQuery(BaseModel):
    """A single compiled, ready-to-run SQL query."""

    id: str = Field(description="Template ID, e.g. 'revenue_by_period'")
    domain: str = Field(description="Domain: financial | credit | sales | data_quality")
    description: str = Field(description="Human-readable description of what this query computes")
    sql: str = Field(description="Final parameterized SQL ready to execute")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Resolved parameters used in this query",
    )

    @field_validator("sql")
    @classmethod
    def sql_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("SQL cannot be empty")
        return v.strip()


class SkippedQuery(BaseModel):
    """A query that was skipped and why."""

    id: str
    domain: str
    reason: str


class QueryBuilderOutput(BaseModel):
    """
    Output of the QueryBuilder (Stage 2).

    Deterministic Python — not an LLM agent — but uses the same output schema
    convention for pipeline uniformity.
    """

    queries: List[CompiledQuery] = Field(
        default_factory=list,
        description="Compiled queries ready to execute",
    )
    skipped: List[SkippedQuery] = Field(
        default_factory=list,
        description="Queries skipped due to missing entities or params",
    )

    @property
    def query_count(self) -> int:
        return len(self.queries)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @classmethod
    def from_query_pack_dict(cls, d: Dict[str, Any]) -> "QueryBuilderOutput":
        """Build from the legacy query_pack dict format."""
        queries = [CompiledQuery(**q) for q in d.get("queries", [])]
        skipped = [SkippedQuery(**s) for s in d.get("skipped", [])]
        return cls(queries=queries, skipped=skipped)


# ═══════════════════════════════════════════════════════════════════════════
# AnalystOutput — Stage 3a: Financial Intelligence
# ═══════════════════════════════════════════════════════════════════════════


class AnalystFinding(BaseModel):
    """A single financial finding from the Analyst agent."""

    id: str = Field(description="Finding ID, e.g. 'FIN-001'")
    severity: Severity = Field(description="critical | warning | opportunity")
    headline: str = Field(description="One sentence headline with specific number")
    evidence: str = Field(description="Data-backed evidence referencing query or table")
    value_eur: Optional[float] = Field(
        default=None,
        description="EUR value if applicable (null if genuinely unknown)",
    )
    value_confidence: ValueConfidence = Field(
        default=ValueConfidence.INFERRED,
        description="How confident we are in the EUR value",
    )
    action: str = Field(description="Specific, actionable recommendation")
    domain: str = Field(default="financial", description="Analysis domain")


class AnalystOutput(BaseModel):
    """
    Output of the Analyst agent (Stage 3a).

    Contains financial findings: revenue trends, customer concentration,
    seasonality, margin analysis, etc.
    """

    agent: str = Field(default="analyst")
    findings: List[AnalystFinding] = Field(default_factory=list)
    raw_output: Optional[str] = Field(
        default=None,
        description="Raw LLM text (for debugging when structured parsing fails)",
    )
    parse_error: Optional[str] = Field(
        default=None,
        description="Set if structured parsing failed; raw_output still available",
    )

    @property
    def critical_findings(self) -> List[AnalystFinding]:
        return [f for f in self.findings if f.severity == Severity.CRITICAL]

    @property
    def total_value_eur(self) -> Optional[float]:
        """Sum of all measured EUR values, or None if none are available."""
        values = [f.value_eur for f in self.findings if f.value_eur is not None]
        return sum(values) if values else None

    @classmethod
    def from_agent_dict(cls, d: Dict[str, Any]) -> "AnalystOutput":
        """Build from the legacy {'agent': ..., 'output': ...} dict."""
        import json

        raw = d.get("output", "")
        findings = []
        parse_error = None

        # Try to parse JSON array from the raw output
        try:
            # Find JSON array in output
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
                for item in parsed:
                    try:
                        findings.append(AnalystFinding(**item))
                    except (TypeError, ValueError, KeyError) as exc:
                        logger.warning("Failed to parse AnalystFinding item: %s", exc)
        except (json.JSONDecodeError, ValueError) as e:
            parse_error = str(e)

        return cls(
            agent=d.get("agent", "analyst"),
            findings=findings,
            raw_output=raw,
            parse_error=parse_error,
        )


# ═══════════════════════════════════════════════════════════════════════════
# SentinelOutput — Stage 3b: Data Quality & Anomaly Detection
# ═══════════════════════════════════════════════════════════════════════════


class SentinelFinding(BaseModel):
    """A single data quality or anomaly finding from the Sentinel agent."""

    id: str = Field(description="Finding ID, e.g. 'DQ-001'")
    severity: Severity = Field(description="critical | warning | info")
    headline: str = Field(description="One sentence headline with specific numbers")
    evidence: str = Field(
        description="Table name, column, actual counts or rates"
    )
    value_eur: Optional[float] = Field(
        default=None,
        description="EUR impact if applicable",
    )
    value_confidence: ValueConfidence = Field(default=ValueConfidence.INFERRED)
    action: str = Field(
        description="Specific action: exclude, fix, investigate, add filter"
    )
    domain: str = Field(default="data_quality")
    table: Optional[str] = Field(default=None, description="Affected table")
    column: Optional[str] = Field(default=None, description="Affected column")


class SentinelOutput(BaseModel):
    """
    Output of the Sentinel agent (Stage 3b).

    Contains data quality issues and anomaly/fraud pattern detections.
    """

    agent: str = Field(default="sentinel")
    findings: List[SentinelFinding] = Field(default_factory=list)
    raw_output: Optional[str] = Field(default=None)
    parse_error: Optional[str] = Field(default=None)

    @property
    def critical_findings(self) -> List[SentinelFinding]:
        return [f for f in self.findings if f.severity == Severity.CRITICAL]

    @property
    def has_multi_tenant_risk(self) -> bool:
        """True if any critical finding mentions multi-tenant contamination."""
        return any(
            "tenant" in f.evidence.lower() or "ad_client_id" in f.evidence.lower()
            for f in self.critical_findings
        )

    @classmethod
    def from_agent_dict(cls, d: Dict[str, Any]) -> "SentinelOutput":
        """Build from the legacy {'agent': ..., 'output': ...} dict."""
        import json

        raw = d.get("output", "")
        findings = []
        parse_error = None

        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
                for item in parsed:
                    try:
                        findings.append(SentinelFinding(**item))
                    except (TypeError, ValueError, KeyError) as exc:
                        logger.warning("Failed to parse SentinelFinding item: %s", exc)
        except (json.JSONDecodeError, ValueError) as e:
            parse_error = str(e)

        return cls(
            agent=d.get("agent", "sentinel"),
            findings=findings,
            raw_output=raw,
            parse_error=parse_error,
        )


# ═══════════════════════════════════════════════════════════════════════════
# AnomalyExplanation — VAL-40: Anomaly explanation schemas
# ═══════════════════════════════════════════════════════════════════════════


class HypothesisType(str, Enum):
    TEMPORAL = "temporal"
    ENTITY = "entity"
    CATEGORY = "category"
    DATA_QUALITY = "data_quality"


class HypothesisStatus(str, Enum):
    UNTESTED = "untested"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class AnomalyInput(BaseModel):
    """Input describing an anomaly to explain."""

    metric: str = Field(description="Name of the anomalous metric")
    expected: float = Field(description="Expected value")
    actual: float = Field(description="Actual observed value")
    deviation_pct: float = Field(description="Percentage deviation from expected")
    table: Optional[str] = Field(default=None, description="Source table")
    column: Optional[str] = Field(default=None, description="Source column")
    period: Optional[str] = Field(default=None, description="Time period of anomaly")


class HypothesisResult(BaseModel):
    """A hypothesis and its evaluation result."""

    hypothesis_id: str = Field(description="Unique hypothesis identifier")
    hypothesis_type: HypothesisType
    description: str = Field(description="Human-readable hypothesis")
    status: HypothesisStatus = Field(default=HypothesisStatus.UNTESTED)
    evidence: str = Field(default="", description="Evidence for/against the hypothesis")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    drill_down_sql: Optional[str] = Field(
        default=None, description="SQL query to test this hypothesis",
    )


class AnomalyExplanationOutput(BaseModel):
    """
    Output of anomaly explanation (VAL-40).

    Contains the anomaly details, generated hypotheses, and the best
    explanation with supporting evidence.
    """

    anomaly: AnomalyInput
    hypotheses: List[HypothesisResult] = Field(default_factory=list)
    best_hypothesis_id: Optional[str] = Field(
        default=None, description="ID of the most likely hypothesis",
    )
    summary: str = Field(default="", description="Human-readable summary")
    explained: bool = Field(
        default=False,
        description="True if at least one hypothesis is supported",
    )

    @property
    def supported_hypotheses(self) -> List[HypothesisResult]:
        return [h for h in self.hypotheses if h.status == HypothesisStatus.SUPPORTED]


# ═══════════════════════════════════════════════════════════════════════════
# QuorumResult — VAL-41: Quorum voting schemas
# ═══════════════════════════════════════════════════════════════════════════


class VoteValue(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    ABSTAIN = "abstain"


class QuorumFindingResult(BaseModel):
    """Result of quorum voting on a single finding."""

    finding_id: str
    accepted: bool
    agreement_ratio: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    votes: str = Field(description="Vote tally, e.g. '2A/1D/0X'")
    dissenting_reasons: List[str] = Field(default_factory=list)


class QuorumReportOutput(BaseModel):
    """Output of quorum-based reconciliation (VAL-41)."""

    ran: bool = True
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    total_findings: int = Field(default=0, ge=0)
    accepted: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)
    acceptance_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    summary: str = ""
    results: List[QuorumFindingResult] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# CashFlowForecast — VAL-37: Cash Flow Forecasting
# ═══════════════════════════════════════════════════════════════════════════


class AgingBucket(BaseModel):
    """A single AR aging bucket with collection probability."""

    bucket: str = Field(description="Aging range, e.g. '0-30d', '31-60d', '61-90d', '90+d'")
    amount: float = Field(description="Total outstanding amount in this bucket")
    count: int = Field(default=0, description="Number of items in this bucket")
    collection_probability: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Estimated probability of collection (0–1)",
    )


class RevenueTrendPoint(BaseModel):
    """A single month's revenue data for trend analysis."""

    month: str = Field(description="Month in YYYY-MM format")
    revenue: float = Field(description="Total revenue for this month")
    invoice_count: int = Field(default=0, description="Number of invoices")
    mom_growth_pct: Optional[float] = Field(
        default=None,
        description="Month-over-month growth percentage",
    )


class CashFlowForecast(BaseModel):
    """
    Output of the Cash Flow Forecaster (VAL-37).

    Combines AR aging analysis with revenue trend projection to produce
    a simple cash flow forecast for the next 30/60/90 days.
    """

    forecast_30d: float = Field(
        description="Projected cash inflow for next 30 days (EUR)",
    )
    forecast_60d: float = Field(
        description="Projected cash inflow for next 60 days (EUR)",
    )
    forecast_90d: float = Field(
        description="Projected cash inflow for next 90 days (EUR)",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall confidence in the forecast (0–1)",
    )
    aging_buckets: List[AgingBucket] = Field(
        default_factory=list,
        description="AR aging buckets used for the forecast",
    )
    revenue_trend: List[RevenueTrendPoint] = Field(
        default_factory=list,
        description="Monthly revenue trend used for projection",
    )
    methodology: str = Field(
        default="weighted_ar_plus_trend",
        description="Forecasting methodology used",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Warnings about data quality or assumptions",
    )
