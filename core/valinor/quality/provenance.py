"""
FindingProvenance — attaches data lineage to every LLM-generated finding.
Every number that appears in an executive report carries this metadata.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any
from decimal import Decimal


@dataclass
class FindingProvenance:
    finding_id: str
    metric_name: str

    # Quality metadata
    data_quality_tag: str = "PRELIMINARY"
    confidence_score: float = 1.0
    confidence_label: str = "PROVISIONAL"

    # Lineage
    tables_accessed: List[str] = field(default_factory=list)
    row_counts: Dict[str, int] = field(default_factory=dict)
    analysis_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Reconciliation
    reconciliation_discrepancy_pct: float = 0.0

    # DQ gate context
    dq_score: float = 100.0
    dq_warnings: List[str] = field(default_factory=list)

    def to_display_badge(self) -> str:
        """Returns a short inline badge for report display."""
        score = round(self.confidence_score * 100)
        return f"[{self.confidence_label} · {score}/100 · {self.data_quality_tag}]"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProvenanceRegistry:
    """Accumulates provenance for all findings in a single analysis run."""
    job_id: str
    client_name: str
    period: str
    dq_report_score: float = 100.0
    dq_report_tag: str = "PRELIMINARY"
    findings: Dict[str, FindingProvenance] = field(default_factory=dict)

    def register(
        self,
        finding_id: str,
        metric_name: str,
        tables: List[str] = None,
        reconciliation_discrepancy: float = 0.0,
    ) -> FindingProvenance:
        """Register a finding and assign confidence based on DQ context."""
        # Confidence degraded by DQ score
        dq_deduction = (100 - self.dq_report_score) / 100 * 0.4
        recon_penalty = min(reconciliation_discrepancy / 0.10, 1.0) * 0.20
        confidence = max(0.0, 1.0 - dq_deduction - recon_penalty)

        if confidence >= 0.85:
            label = "CONFIRMED"
        elif confidence >= 0.65:
            label = "PROVISIONAL"
        elif confidence >= 0.45:
            label = "UNVERIFIED"
        else:
            label = "BLOCKED"

        prov = FindingProvenance(
            finding_id=finding_id,
            metric_name=metric_name,
            data_quality_tag=self.dq_report_tag,
            confidence_score=confidence,
            confidence_label=label,
            tables_accessed=tables or [],
            dq_score=self.dq_report_score,
        )
        self.findings[finding_id] = prov
        return prov

    def summary_for_report(self) -> str:
        """Build provenance summary block for executive report footer."""
        lines = [
            "━━━ DATA QUALITY ━━━",
            f"DQ Score: {self.dq_report_score:.0f}/100 · Tag: {self.dq_report_tag}",
            f"Analysis: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            (
                f"Findings certified: "
                f"{sum(1 for f in self.findings.values() if f.confidence_label == 'CONFIRMED')}"
                f"/{len(self.findings)}"
            ),
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "client_name": self.client_name,
            "period": self.period,
            "dq_report_score": self.dq_report_score,
            "dq_report_tag": self.dq_report_tag,
            "findings": {k: v.to_dict() for k, v in self.findings.items()},
        }
