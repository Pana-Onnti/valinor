"""
Tests for Pydantic-AI type-safe agent output schemas (VAL-30).

Verifies that CartographerOutput, QueryBuilderOutput, AnalystOutput, and
SentinelOutput are correctly structured and validate properly.
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.valinor.schemas.agent_outputs import (
    AnalystFinding,
    AnalystOutput,
    CartographerOutput,
    CompiledQuery,
    EntityDefinition,
    EntityType,
    QueryBuilderOutput,
    Severity,
    SentinelFinding,
    SentinelOutput,
    SkippedQuery,
    ValueConfidence,
)


# ── Cartographer ──────────────────────────────────────────────────────────────

class TestCartographerOutput:
    def test_empty_cartographer_output(self):
        """CartographerOutput with minimal fields is valid."""
        out = CartographerOutput(client="acme")
        assert out.client == "acme"
        assert out.entities == {}
        assert out.status == "complete"

    def test_entity_definition_valid(self):
        """EntityDefinition with all fields is valid."""
        entity = EntityDefinition(
            table="c_invoice",
            entity_type=EntityType.TRANSACTIONAL,
            row_count=45000,
            key_columns={"invoice_date": "dateacct", "amount_col": "grandtotal"},
            base_filter="AND issotrx = 'Y'",
            confidence=0.95,
        )
        assert entity.table == "c_invoice"
        assert entity.entity_type == EntityType.TRANSACTIONAL
        assert entity.row_count == 45000
        assert entity.confidence == 0.95

    def test_entity_type_enum_values(self):
        """EntityType enum has all expected values."""
        assert EntityType.MASTER == "MASTER"
        assert EntityType.TRANSACTIONAL == "TRANSACTIONAL"
        assert EntityType.CONFIG == "CONFIG"
        assert EntityType.BRIDGE == "BRIDGE"

    def test_confidence_bounds(self):
        """confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            EntityDefinition(table="x", confidence=1.5)
        with pytest.raises(ValidationError):
            EntityDefinition(table="x", confidence=-0.1)

    def test_from_entity_map_dict(self):
        """CartographerOutput.from_entity_map_dict() parses legacy format."""
        legacy = {
            "client": "globex",
            "status": "complete",
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "entity_type": "TRANSACTIONAL",
                    "row_count": 10000,
                    "key_columns": {},
                    "base_filter": "AND issotrx = 'Y'",
                    "confidence": 0.9,
                }
            },
            "relationships": [],
            "_phase1_prescan": {"tables_probed": 3, "retry_attempt": False},
        }
        out = CartographerOutput.from_entity_map_dict(legacy)
        assert out.client == "globex"
        assert "invoices" in out.entities
        assert out.phase1_tables_probed == 3

    def test_to_entity_map_dict_roundtrip(self):
        """to_entity_map_dict() produces a dict that from_entity_map_dict() can parse."""
        original = CartographerOutput(
            client="test",
            entities={
                "invoices": EntityDefinition(
                    table="c_invoice",
                    entity_type=EntityType.TRANSACTIONAL,
                    row_count=100,
                )
            },
        )
        d = original.to_entity_map_dict()
        restored = CartographerOutput.from_entity_map_dict(d)
        assert restored.client == original.client
        assert "invoices" in restored.entities


# ── QueryBuilder ──────────────────────────────────────────────────────────────

class TestQueryBuilderOutput:
    def test_empty_output(self):
        """QueryBuilderOutput with no queries is valid."""
        out = QueryBuilderOutput()
        assert out.queries == []
        assert out.skipped == []
        assert out.query_count == 0

    def test_compiled_query_valid(self):
        """CompiledQuery with all fields is valid."""
        q = CompiledQuery(
            id="revenue_by_period",
            domain="financial",
            description="Monthly revenue",
            sql="SELECT COUNT(*) FROM c_invoice",
            params={"start_date": "2025-01-01"},
        )
        assert q.id == "revenue_by_period"
        assert "SELECT" in q.sql

    def test_compiled_query_empty_sql_raises(self):
        """CompiledQuery with empty SQL raises ValidationError."""
        with pytest.raises(ValidationError):
            CompiledQuery(
                id="bad",
                domain="financial",
                description="test",
                sql="   ",
            )

    def test_from_query_pack_dict(self):
        """from_query_pack_dict() parses legacy dict format."""
        pack = {
            "queries": [
                {
                    "id": "revenue_by_period",
                    "domain": "financial",
                    "description": "Revenue",
                    "sql": "SELECT 1",
                    "params": {},
                }
            ],
            "skipped": [
                {
                    "id": "aging_analysis",
                    "domain": "credit",
                    "reason": "Missing entities: ['payments']",
                }
            ],
        }
        out = QueryBuilderOutput.from_query_pack_dict(pack)
        assert out.query_count == 1
        assert out.skipped_count == 1
        assert out.queries[0].id == "revenue_by_period"

    def test_query_count_property(self):
        """query_count and skipped_count are computed correctly."""
        q1 = CompiledQuery(id="a", domain="d", description="x", sql="SELECT 1")
        q2 = CompiledQuery(id="b", domain="d", description="y", sql="SELECT 2")
        out = QueryBuilderOutput(queries=[q1, q2])
        assert out.query_count == 2
        assert out.skipped_count == 0


# ── Analyst ───────────────────────────────────────────────────────────────────

class TestAnalystOutput:
    def test_empty_analyst_output(self):
        """AnalystOutput with no findings is valid."""
        out = AnalystOutput()
        assert out.findings == []
        assert out.agent == "analyst"

    def test_analyst_finding_valid(self):
        """AnalystFinding with all fields is valid."""
        f = AnalystFinding(
            id="FIN-001",
            severity=Severity.CRITICAL,
            headline="Revenue fell 30% YoY to €1.2M",
            evidence="revenue_yoy query: 2025 total=1200000, 2024 total=1714286",
            value_eur=1_200_000.0,
            value_confidence=ValueConfidence.MEASURED,
            action="Investigate top 5 churned customers from 2024",
        )
        assert f.id == "FIN-001"
        assert f.value_eur == 1_200_000.0

    def test_critical_findings_filter(self):
        """critical_findings returns only CRITICAL severity findings."""
        out = AnalystOutput(
            findings=[
                AnalystFinding(
                    id="F1", severity=Severity.CRITICAL, headline="x", evidence="y", action="z"
                ),
                AnalystFinding(
                    id="F2", severity=Severity.WARNING, headline="a", evidence="b", action="c"
                ),
            ]
        )
        assert len(out.critical_findings) == 1
        assert out.critical_findings[0].id == "F1"

    def test_total_value_eur(self):
        """total_value_eur sums measured EUR values."""
        out = AnalystOutput(
            findings=[
                AnalystFinding(
                    id="F1", severity=Severity.CRITICAL, headline="x", evidence="y",
                    action="z", value_eur=500_000.0,
                ),
                AnalystFinding(
                    id="F2", severity=Severity.WARNING, headline="a", evidence="b",
                    action="c", value_eur=200_000.0,
                ),
            ]
        )
        assert out.total_value_eur == 700_000.0

    def test_from_agent_dict_parses_json(self):
        """from_agent_dict() parses JSON array from raw output."""
        raw = """
        Some preamble text.
        [
          {"id": "FIN-001", "severity": "critical", "headline": "Test", "evidence": "data",
           "action": "do it", "domain": "financial", "value_eur": null, "value_confidence": "estimated"}
        ]
        """
        out = AnalystOutput.from_agent_dict({"agent": "analyst", "output": raw})
        assert len(out.findings) == 1
        assert out.findings[0].id == "FIN-001"

    def test_from_agent_dict_no_json(self):
        """from_agent_dict() handles output with no JSON array gracefully."""
        out = AnalystOutput.from_agent_dict({"agent": "analyst", "output": "no json here"})
        assert out.findings == []


# ── Sentinel ──────────────────────────────────────────────────────────────────

class TestSentinelOutput:
    def test_empty_sentinel_output(self):
        """SentinelOutput with no findings is valid."""
        out = SentinelOutput()
        assert out.findings == []
        assert out.agent == "sentinel"

    def test_sentinel_finding_valid(self):
        """SentinelFinding with all fields is valid."""
        f = SentinelFinding(
            id="DQ-001",
            severity=Severity.CRITICAL,
            headline="15% null rate in dateacct column",
            evidence="c_invoice: 6750/45000 rows have null dateacct",
            action="Exclude null-date rows from all financial aggregates",
            table="c_invoice",
            column="dateacct",
        )
        assert f.table == "c_invoice"
        assert f.column == "dateacct"

    def test_has_multi_tenant_risk_positive(self):
        """has_multi_tenant_risk returns True when tenant contamination detected."""
        out = SentinelOutput(
            findings=[
                SentinelFinding(
                    id="DQ-001",
                    severity=Severity.CRITICAL,
                    headline="multi-tenant contamination",
                    evidence="multiple ad_client_id values found: 1000000, 1000001",
                    action="Add ad_client_id filter",
                )
            ]
        )
        assert out.has_multi_tenant_risk is True

    def test_has_multi_tenant_risk_negative(self):
        """has_multi_tenant_risk returns False when no tenant issue."""
        out = SentinelOutput(
            findings=[
                SentinelFinding(
                    id="DQ-001",
                    severity=Severity.WARNING,
                    headline="minor issue",
                    evidence="some other evidence",
                    action="fix it",
                )
            ]
        )
        assert out.has_multi_tenant_risk is False

    def test_from_agent_dict_parses_json(self):
        """from_agent_dict() parses JSON array from raw Sentinel output."""
        raw = """
        [
          {"id": "DQ-001", "severity": "critical", "headline": "Duplicate invoices",
           "evidence": "3 duplicate groups found", "action": "Deduplicate",
           "domain": "data_quality", "value_eur": 50000, "value_confidence": "estimated"}
        ]
        """
        out = SentinelOutput.from_agent_dict({"agent": "sentinel", "output": raw})
        assert len(out.findings) == 1
        assert out.findings[0].id == "DQ-001"
        assert out.findings[0].value_eur == 50000.0
