"""
ConfidenceCollector — assembles AnalysisConfidenceMetadata from pipeline
artifacts (VAL-97).

Pure domain logic: takes DQ report, findings, query results, and
reconciliation data; produces a validated AnalysisConfidenceMetadata.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.valinor.schemas.confidence import (
    AnalysisConfidenceMetadata,
    FindingConfidence,
    TrustScoreBreakdown,
)

logger = logging.getLogger(__name__)


# Mapping from agent ValueConfidence enum values to confidence levels
_CONFIDENCE_LEVEL_MAP = {
    "measured": "verified",
    "estimated": "estimated",
    "inferred": "low_confidence",
}


def _map_confidence_level(value_confidence: str) -> str:
    """Map a ValueConfidence string to a FindingConfidence level."""
    return _CONFIDENCE_LEVEL_MAP.get(value_confidence.lower(), "low_confidence")


def _extract_null_check_score(dq_checks: List[Dict[str, Any]]) -> float:
    """Extract null density score from DQ checks (0.0 = all nulls, 1.0 = no nulls)."""
    for check in dq_checks:
        name = check.get("name", "")
        if "null" in name.lower():
            # If check passed, null density is low
            if check.get("passed", False):
                return 1.0
            # Use score_impact to estimate severity
            impact = check.get("score_impact", 0)
            return max(0.0, 1.0 - (impact / 15.0))
    return 0.7  # default: assume moderate null density


def _extract_schema_check_score(dq_checks: List[Dict[str, Any]]) -> float:
    """Extract schema integrity score from DQ checks (0.0-1.0)."""
    for check in dq_checks:
        name = check.get("name", "")
        if "schema" in name.lower():
            if check.get("passed", False):
                return 1.0
            impact = check.get("score_impact", 0)
            return max(0.0, 1.0 - (impact / 15.0))
    return 0.7  # default


def compute_trust_score(
    dq_score: float,
    verification_rate: float,
    null_density_score: float,
    schema_coverage_score: float,
    reconciliation_conflicts: int,
    total_findings: int,
) -> TrustScoreBreakdown:
    """
    Compute a weighted trust score from quality dimensions.

    Args:
        dq_score: DataQualityGate overall score (0-100).
        verification_rate: Fraction of claims verified (0.0-1.0).
        null_density_score: Inverse null density (0.0-1.0, higher = fewer nulls).
        schema_coverage_score: Entity/schema coverage (0.0-1.0).
        reconciliation_conflicts: Number of cross-agent conflicts found.
        total_findings: Total findings produced by agents.
    """
    # Scale each dimension to its max component weight
    dq_component = round((dq_score / 100.0) * 30.0, 2)
    verification_component = round(verification_rate * 25.0, 2)
    null_component = round(null_density_score * 15.0, 2)
    schema_component = round(schema_coverage_score * 15.0, 2)

    # Reconciliation: fewer conflicts = higher score
    if total_findings > 0:
        conflict_rate = min(reconciliation_conflicts / max(total_findings, 1), 1.0)
        recon_component = round((1.0 - conflict_rate) * 15.0, 2)
    else:
        recon_component = 15.0  # no findings = no conflicts

    overall = int(round(
        dq_component + verification_component + null_component
        + schema_component + recon_component
    ))
    overall = max(0, min(100, overall))

    return TrustScoreBreakdown(
        overall=overall,
        dq_component=dq_component,
        verification_component=verification_component,
        null_density_component=null_component,
        schema_coverage_component=schema_component,
        reconciliation_component=recon_component,
    )


def _build_finding_confidence(
    finding: Dict[str, Any],
    dq_score: float,
    query_results: Dict[str, Any],
) -> FindingConfidence:
    """Build FindingConfidence for a single finding dict."""
    value_confidence = finding.get("value_confidence", "inferred")
    level = _map_confidence_level(value_confidence)

    # Extract source info from evidence
    evidence = finding.get("evidence", "")
    table = finding.get("table", "")
    column = finding.get("column", "")
    domain = finding.get("domain", "")

    source_tables: List[str] = []
    source_columns: List[str] = []
    if table:
        source_tables.append(table)
    if column:
        source_columns.append(column)

    # Try to find matching query result for record count / SQL
    record_count = 0
    sql_query = ""
    results_dict = query_results.get("results", {})
    finding_id = finding.get("id", "")

    # Match by domain
    for qid, qresult in results_dict.items():
        if isinstance(qresult, dict):
            q_domain = qresult.get("domain", "")
            if q_domain == domain or domain in qid:
                row_count = qresult.get("row_count", 0)
                if isinstance(row_count, int):
                    record_count = max(record_count, row_count)
                q_sql = qresult.get("sql", "")
                if q_sql and not sql_query:
                    sql_query = q_sql

    # Scaled DQ contribution (0-10 scale from 0-100 overall)
    finding_dq = round(dq_score / 10.0, 2)

    # Determine degradation
    degradation_applied = False
    degradation_reason = None
    if dq_score < 50:
        degradation_applied = True
        degradation_reason = f"Low DQ score ({dq_score:.0f}/100)"
    if level == "low_confidence":
        degradation_applied = True
        degradation_reason = degradation_reason or f"Value confidence: {value_confidence}"

    return FindingConfidence(
        level=level,
        source_tables=source_tables,
        source_columns=source_columns,
        record_count=record_count,
        null_rate=0.0,  # Would need per-column null data; default to 0.0
        dq_score=finding_dq,
        verification_method="direct_query" if level == "verified" else "cross_agent",
        sql_query=sql_query,
        degradation_applied=degradation_applied,
        degradation_reason=degradation_reason,
    )


def collect_confidence_metadata(
    *,
    dq_data: Optional[Dict[str, Any]] = None,
    findings: Optional[Dict[str, Any]] = None,
    query_results: Optional[Dict[str, Any]] = None,
    reconciliation: Optional[Dict[str, Any]] = None,
    pipeline_start_time: Optional[float] = None,
    pipeline_end_time: Optional[float] = None,
) -> AnalysisConfidenceMetadata:
    """
    Assemble AnalysisConfidenceMetadata from pipeline artifacts.

    All parameters are optional for robustness: missing data yields
    conservative (lower) confidence scores rather than errors.

    Args:
        dq_data: The data_quality dict from results (score, checks, etc.).
        findings: The findings dict keyed by agent name.
        query_results: The query execution results dict.
        reconciliation: The _reconciliation dict from findings.
        pipeline_start_time: Pipeline start timestamp (time.time()).
        pipeline_end_time: Pipeline end timestamp (time.time()).

    Returns:
        Validated AnalysisConfidenceMetadata instance.
    """
    dq_data = dq_data or {}
    findings = findings or {}
    query_results = query_results or {}
    reconciliation = reconciliation or {}

    # ── Extract DQ metrics ────────────────────────────────────────────────
    dq_score = dq_data.get("score", 50.0)
    dq_checks = dq_data.get("checks", [])
    null_density_score = _extract_null_check_score(dq_checks)
    schema_coverage_score = _extract_schema_check_score(dq_checks)

    # ── Compute verification rate from findings ───────────────────────────
    all_findings_list: List[Dict[str, Any]] = []
    for agent_name, agent_data in findings.items():
        if agent_name.startswith("_"):
            continue
        if isinstance(agent_data, dict):
            agent_findings = agent_data.get("findings", [])
            if isinstance(agent_findings, list):
                all_findings_list.extend(agent_findings)

    verified_count = sum(
        1 for f in all_findings_list
        if f.get("value_confidence", "").lower() == "measured"
    )
    total_finding_count = len(all_findings_list)
    verification_rate = (
        verified_count / total_finding_count if total_finding_count > 0 else 0.0
    )

    # ── Reconciliation conflicts ──────────────────────────────────────────
    recon_conflicts = reconciliation.get("conflicts_found", 0)

    # ── Trust score ───────────────────────────────────────────────────────
    trust_score = compute_trust_score(
        dq_score=dq_score,
        verification_rate=verification_rate,
        null_density_score=null_density_score,
        schema_coverage_score=schema_coverage_score,
        reconciliation_conflicts=recon_conflicts,
        total_findings=total_finding_count,
    )

    # ── Per-finding confidence ────────────────────────────────────────────
    findings_confidence: Dict[str, FindingConfidence] = {}
    kpi_confidence: Dict[str, FindingConfidence] = {}

    for finding in all_findings_list:
        fid = finding.get("id", "")
        if not fid:
            continue
        fc = _build_finding_confidence(finding, dq_score, query_results)
        findings_confidence[fid] = fc

        # KPIs: findings with value_eur are treated as KPI data points
        headline = finding.get("headline", "")
        if finding.get("value_eur") is not None and headline:
            # Use finding ID as KPI key for uniqueness
            kpi_confidence[fid] = fc

    # ── Query execution stats ─────────────────────────────────────────────
    results_dict = query_results.get("results", {})
    errors_dict = query_results.get("errors", {})
    total_queries = len(results_dict) + len(errors_dict)

    total_records = 0
    for qresult in results_dict.values():
        if isinstance(qresult, dict):
            rc = qresult.get("row_count", 0)
            if isinstance(rc, int):
                total_records += rc

    # ── Pipeline duration ─────────────────────────────────────────────────
    duration = 0.0
    if pipeline_start_time and pipeline_end_time:
        duration = round(pipeline_end_time - pipeline_start_time, 2)

    return AnalysisConfidenceMetadata(
        trust_score=trust_score,
        findings_confidence=findings_confidence,
        kpi_confidence=kpi_confidence,
        analysis_timestamp=datetime.utcnow(),
        total_queries_executed=total_queries,
        total_records_processed=total_records,
        pipeline_duration_seconds=duration,
    )
