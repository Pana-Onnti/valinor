"""
Tests for confidence metadata schemas and collector (VAL-97).

Three scenarios:
  1. High confidence: all findings verified, high DQ score
  2. Mixed confidence: some estimated, some verified
  3. Degraded data: low DQ score, many NULLs, low confidence
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.valinor.schemas.confidence import (
    AnalysisConfidenceMetadata,
    FindingConfidence,
    TrustScoreBreakdown,
)
from core.valinor.confidence_collector import (
    collect_confidence_metadata,
    compute_trust_score,
    _map_confidence_level,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_dq_data(score: float, null_passed: bool = True, schema_passed: bool = True) -> dict:
    """Build a DQ data dict matching what the adapter stores in results."""
    return {
        "score": score,
        "confidence_label": "CONFIRMED" if score >= 85 else "PROVISIONAL",
        "tag": "FINAL" if score >= 85 else "PRELIMINARY",
        "gate_decision": "PROCEED" if score >= 50 else "HALT",
        "checks": [
            {"name": "schema_integrity", "passed": schema_passed, "severity": "CRITICAL", "score_impact": 0 if schema_passed else 15},
            {"name": "null_density", "passed": null_passed, "severity": "WARNING", "score_impact": 0 if null_passed else 15},
            {"name": "duplicate_rate", "passed": True, "severity": "WARNING", "score_impact": 0},
            {"name": "accounting_balance", "passed": True, "severity": "CRITICAL", "score_impact": 0},
        ],
        "warnings": [],
        "blocking_issues": [],
    }


def _make_findings(findings_list: list) -> dict:
    """Build a findings dict with an analyst agent containing given findings."""
    return {
        "analyst": {
            "agent": "analyst",
            "output": "",
            "findings": findings_list,
        },
    }


def _make_query_results(num_queries: int = 5, row_count: int = 1000) -> dict:
    """Build a query_results dict."""
    results = {}
    for i in range(num_queries):
        results[f"q_{i}"] = {
            "domain": "financial",
            "row_count": row_count,
            "sql": f"SELECT * FROM invoices LIMIT {row_count}",
        }
    return {"results": results, "errors": {}}


# ── Schema validation tests ──────────────────────────────────────────────────

class TestSchemaValidation:
    def test_trust_score_breakdown_valid(self):
        ts = TrustScoreBreakdown(
            overall=80,
            dq_component=25.0,
            verification_component=20.0,
            null_density_component=12.0,
            schema_coverage_component=12.0,
            reconciliation_component=11.0,
        )
        assert ts.overall == 80

    def test_trust_score_breakdown_bounds(self):
        with pytest.raises(Exception):
            TrustScoreBreakdown(overall=101)  # exceeds max

    def test_finding_confidence_valid(self):
        fc = FindingConfidence(
            level="verified",
            source_tables=["c_invoice"],
            source_columns=["grandtotal"],
            record_count=500,
            null_rate=0.05,
            dq_score=9.2,
            verification_method="direct_query",
            sql_query="SELECT SUM(grandtotal) FROM c_invoice",
            degradation_applied=False,
        )
        assert fc.level == "verified"
        assert fc.record_count == 500

    def test_analysis_confidence_metadata_roundtrip(self):
        """Validate that the model serializes and deserializes correctly."""
        meta = AnalysisConfidenceMetadata(
            trust_score=TrustScoreBreakdown(
                overall=75,
                dq_component=22.5,
                verification_component=18.75,
                null_density_component=11.25,
                schema_coverage_component=11.25,
                reconciliation_component=11.25,
            ),
            findings_confidence={
                "FIN-001": FindingConfidence(
                    level="verified",
                    record_count=100,
                    dq_score=7.5,
                ),
            },
            kpi_confidence={},
            analysis_timestamp=datetime(2026, 3, 30, 12, 0, 0),
            total_queries_executed=10,
            total_records_processed=5000,
            pipeline_duration_seconds=120.5,
        )
        dumped = meta.model_dump(mode="json")
        restored = AnalysisConfidenceMetadata.model_validate(dumped)
        assert restored.trust_score.overall == 75
        assert "FIN-001" in restored.findings_confidence


# ── Scenario 1: High confidence ──────────────────────────────────────────────

class TestHighConfidenceScenario:
    def test_high_dq_all_verified(self):
        """All findings are measured, DQ score is high, no conflicts."""
        dq_data = _make_dq_data(score=95.0)
        findings = _make_findings([
            {"id": "FIN-001", "severity": "critical", "headline": "Revenue up 15%",
             "evidence": "c_invoice", "value_eur": 500000, "value_confidence": "measured",
             "action": "Confirm trend", "domain": "financial"},
            {"id": "FIN-002", "severity": "warning", "headline": "AR aging spike",
             "evidence": "c_invoice", "value_eur": 120000, "value_confidence": "measured",
             "action": "Review AR", "domain": "financial"},
        ])
        query_results = _make_query_results(num_queries=8, row_count=2000)

        meta = collect_confidence_metadata(
            dq_data=dq_data,
            findings=findings,
            query_results=query_results,
            reconciliation={"conflicts_found": 0},
        )

        assert meta.trust_score.overall >= 80
        assert meta.trust_score.dq_component >= 25
        assert meta.trust_score.verification_component >= 20
        assert meta.trust_score.reconciliation_component == 15.0
        assert len(meta.findings_confidence) == 2
        assert meta.findings_confidence["FIN-001"].level == "verified"
        assert meta.findings_confidence["FIN-002"].level == "verified"
        assert not meta.findings_confidence["FIN-001"].degradation_applied
        assert meta.total_queries_executed == 8

    def test_trust_score_computation_high(self):
        ts = compute_trust_score(
            dq_score=95.0,
            verification_rate=1.0,
            null_density_score=1.0,
            schema_coverage_score=1.0,
            reconciliation_conflicts=0,
            total_findings=5,
        )
        assert ts.overall >= 90


# ── Scenario 2: Mixed confidence ─────────────────────────────────────────────

class TestMixedConfidenceScenario:
    def test_mixed_verified_and_estimated(self):
        """Mix of measured and estimated findings, moderate DQ."""
        dq_data = _make_dq_data(score=72.0)
        findings = _make_findings([
            {"id": "FIN-001", "severity": "critical", "headline": "Revenue decline",
             "evidence": "invoices table", "value_eur": 300000, "value_confidence": "measured",
             "action": "Investigate", "domain": "financial"},
            {"id": "FIN-002", "severity": "warning", "headline": "Margin erosion",
             "evidence": "estimates", "value_eur": 50000, "value_confidence": "estimated",
             "action": "Monitor", "domain": "financial"},
            {"id": "FIN-003", "severity": "opportunity", "headline": "Cost savings",
             "evidence": "indirect calculation", "value_eur": 20000, "value_confidence": "inferred",
             "action": "Explore", "domain": "financial"},
        ])
        query_results = _make_query_results(num_queries=5, row_count=500)
        reconciliation = {"conflicts_found": 1}

        meta = collect_confidence_metadata(
            dq_data=dq_data,
            findings=findings,
            query_results=query_results,
            reconciliation=reconciliation,
        )

        assert 40 <= meta.trust_score.overall <= 80
        assert meta.findings_confidence["FIN-001"].level == "verified"
        assert meta.findings_confidence["FIN-002"].level == "estimated"
        assert meta.findings_confidence["FIN-003"].level == "low_confidence"
        assert meta.findings_confidence["FIN-003"].degradation_applied

    def test_partial_verification_rate(self):
        ts = compute_trust_score(
            dq_score=70.0,
            verification_rate=0.5,
            null_density_score=0.7,
            schema_coverage_score=0.8,
            reconciliation_conflicts=1,
            total_findings=4,
        )
        assert 40 <= ts.overall <= 75


# ── Scenario 3: Degraded data ────────────────────────────────────────────────

class TestDegradedDataScenario:
    def test_low_dq_high_nulls(self):
        """Low DQ score, null check failed, all inferred findings."""
        dq_data = _make_dq_data(score=35.0, null_passed=False, schema_passed=False)
        findings = _make_findings([
            {"id": "FIN-001", "severity": "warning", "headline": "Revenue estimate",
             "evidence": "partial data", "value_eur": 100000, "value_confidence": "inferred",
             "action": "Validate", "domain": "financial"},
            {"id": "FIN-002", "severity": "info", "headline": "Data gap detected",
             "evidence": "missing tables", "value_eur": None, "value_confidence": "inferred",
             "action": "Fix data", "domain": "data_quality"},
        ])
        query_results = _make_query_results(num_queries=2, row_count=50)
        reconciliation = {"conflicts_found": 2}

        meta = collect_confidence_metadata(
            dq_data=dq_data,
            findings=findings,
            query_results=query_results,
            reconciliation=reconciliation,
        )

        assert meta.trust_score.overall <= 45
        assert meta.trust_score.dq_component <= 12
        assert all(
            fc.level == "low_confidence"
            for fc in meta.findings_confidence.values()
        )
        assert all(
            fc.degradation_applied
            for fc in meta.findings_confidence.values()
        )
        assert meta.total_queries_executed == 2

    def test_empty_inputs_conservative(self):
        """No DQ data, no findings: should produce conservative low scores."""
        meta = collect_confidence_metadata()
        assert meta.trust_score.overall >= 0
        assert meta.trust_score.overall <= 100
        assert meta.findings_confidence == {}
        assert meta.total_queries_executed == 0


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_confidence_level_mapping(self):
        assert _map_confidence_level("measured") == "verified"
        assert _map_confidence_level("estimated") == "estimated"
        assert _map_confidence_level("inferred") == "low_confidence"
        assert _map_confidence_level("MEASURED") == "verified"
        assert _map_confidence_level("unknown") == "low_confidence"

    def test_backward_compatible_no_confidence_key(self):
        """Calling with None args doesn't crash."""
        meta = collect_confidence_metadata(
            dq_data=None,
            findings=None,
            query_results=None,
            reconciliation=None,
        )
        assert isinstance(meta, AnalysisConfidenceMetadata)
        assert meta.trust_score.overall >= 0

    def test_findings_with_underscore_agents_ignored(self):
        """Agent entries starting with _ (like _reconciliation) are skipped."""
        findings = {
            "_reconciliation": {"conflicts_found": 1, "message": "test"},
            "analyst": {
                "agent": "analyst",
                "output": "",
                "findings": [
                    {"id": "FIN-001", "severity": "critical", "headline": "Test",
                     "evidence": "test", "value_eur": 100, "value_confidence": "measured",
                     "action": "test", "domain": "financial"},
                ],
            },
        }
        meta = collect_confidence_metadata(findings=findings)
        assert "FIN-001" in meta.findings_confidence
        assert len(meta.findings_confidence) == 1

    def test_model_dump_json_serializable(self):
        """Ensure model_dump(mode='json') produces JSON-serializable dict."""
        import json

        meta = collect_confidence_metadata(
            dq_data=_make_dq_data(80.0),
            findings=_make_findings([
                {"id": "FIN-001", "severity": "critical", "headline": "Test",
                 "evidence": "test", "value_eur": 100, "value_confidence": "measured",
                 "action": "test", "domain": "financial"},
            ]),
        )
        dumped = meta.model_dump(mode="json")
        serialized = json.dumps(dumped)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert "trust_score" in parsed
        assert "findings_confidence" in parsed
