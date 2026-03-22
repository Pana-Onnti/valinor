"""
Integration tests for grounded/v2 — KG + Verification wiring into pipeline.

Tests the integration points WITHOUT requiring claude_agent_sdk:
  1. build_knowledge_graph() with realistic entity_map
  2. VerificationEngine on realistic query results
  3. gate_verification() pass/warn behavior
  4. Verification report JSON serialization
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest
from valinor.knowledge_graph import build_knowledge_graph, SchemaKnowledgeGraph
from valinor.verification import VerificationEngine, VerificationReport
from valinor.gates import gate_verification


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def realistic_entity_map():
    """A realistic entity_map as the Cartographer would produce."""
    return {
        "entities": {
            "invoices": {
                "table": "account_move",
                "type": "TRANSACTIONAL",
                "confidence": 0.95,
                "row_count": 5000,
                "base_filter": "move_type IN ('out_invoice') AND state='posted'",
                "key_columns": {
                    "pk": "id",
                    "amount_col": "amount_total",
                    "date_col": "invoice_date",
                },
                "probed_values": {
                    "move_type": {"out_invoice": 3139, "out_refund": 200, "in_invoice": 1500},
                    "state": {"posted": 4500, "draft": 300, "cancel": 200},
                },
            },
            "customers": {
                "table": "res_partner",
                "type": "MASTER",
                "confidence": 0.90,
                "row_count": 2000,
                "base_filter": "customer_rank > 0",
                "key_columns": {
                    "pk": "id",
                    "name_col": "name",
                },
                "probed_values": {
                    "customer_rank": {"1": 1500, "2": 300, "0": 200},
                },
            },
            "payments": {
                "table": "account_payment",
                "type": "TRANSACTIONAL",
                "confidence": 0.85,
                "row_count": 3000,
                "base_filter": "payment_type='inbound'",
                "key_columns": {
                    "pk": "id",
                    "amount_col": "amount",
                },
                "probed_values": {
                    "payment_type": {"inbound": 2500, "outbound": 500},
                },
            },
        },
        "relationships": [
            {
                "from": "invoices",
                "to": "customers",
                "via": "partner_id",
                "cardinality": "N:1",
            },
            {
                "from": "payments",
                "to": "customers",
                "via": "partner_id",
                "cardinality": "N:1",
            },
        ],
    }


@pytest.fixture
def realistic_query_results():
    """Realistic query results from Stage 2.5."""
    return {
        "results": {
            "total_revenue_summary": {
                "rows": [{
                    "num_invoices": 3139,
                    "total_revenue": 1631559.62,
                    "avg_invoice": 519.77,
                    "min_invoice": -35511.52,
                    "max_invoice": 123376.73,
                    "distinct_customers": 1223,
                    "date_from": "2024-12-01",
                    "date_to": "2024-12-31",
                }],
                "row_count": 1,
            },
            "ar_outstanding_actual": {
                "rows": [{
                    "total_outstanding": 3267365.43,
                    "overdue_amount": 3267365.43,
                    "customers_with_debt": 616,
                }],
                "row_count": 1,
            },
            "data_freshness": {
                "rows": [{
                    "days_since_latest": 5,
                    "total_records": 3139,
                    "distinct_customers": 1223,
                }],
                "row_count": 1,
            },
        },
    }


@pytest.fixture
def realistic_baseline():
    """Baseline as compute_baseline() would produce."""
    return {
        "data_available": True,
        "total_revenue": 1631559.62,
        "num_invoices": 3139,
        "avg_invoice": 519.77,
        "distinct_customers": 1223,
        "total_outstanding_ar": 3267365.43,
        "overdue_ar": 3267365.43,
        "customers_with_debt": 616,
        "data_freshness_days": 5,
        "_provenance": {},
    }


@pytest.fixture
def realistic_findings():
    """Findings as agents would produce, with structured data."""
    return {
        "analyst": {
            "agent": "analyst",
            "findings": [
                {
                    "id": "FIN-001",
                    "severity": "warning",
                    "headline": "Total revenue is €1,631,559.62 for December 2024",
                    "evidence": "From total_revenue_summary query",
                    "value_eur": 1631559.62,
                    "value_confidence": "measured",
                    "domain": "financial",
                },
                {
                    "id": "FIN-002",
                    "severity": "opportunity",
                    "headline": "Average invoice €519.77 — top customer pays €123,376.73",
                    "evidence": "From total_revenue_summary query",
                    "value_eur": 519.77,
                    "value_confidence": "measured",
                    "domain": "financial",
                },
            ],
        },
        "sentinel": {
            "agent": "sentinel",
            "findings": [
                {
                    "id": "DQ-001",
                    "severity": "warning",
                    "headline": "616 customers with debt vs 1223 active — 50% have outstanding balance",
                    "evidence": "ar_outstanding_actual vs total_revenue_summary",
                    "value_eur": 3267365.43,
                    "value_confidence": "measured",
                    "domain": "data_quality",
                },
            ],
        },
        "hunter": {
            "agent": "hunter",
            "findings": [
                {
                    "id": "HUNT-001",
                    "severity": "opportunity",
                    "headline": "AR outstanding €3,267,365.43 — recovery opportunity",
                    "evidence": "From ar_outstanding_actual query",
                    "value_eur": 3267365.43,
                    "value_confidence": "measured",
                    "domain": "sales",
                },
            ],
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# TEST: build_knowledge_graph with realistic entity_map
# ═══════════════════════════════════════════════════════════════════════════


class TestKnowledgeGraphIntegration:
    """Test that build_knowledge_graph works with a realistic entity_map."""

    def test_builds_from_realistic_entity_map(self, realistic_entity_map):
        kg = build_knowledge_graph(realistic_entity_map)
        assert isinstance(kg, SchemaKnowledgeGraph)
        assert len(kg.tables) == 3
        assert "account_move" in kg.tables
        assert "res_partner" in kg.tables
        assert "account_payment" in kg.tables

    def test_edges_created_from_relationships(self, realistic_entity_map):
        kg = build_knowledge_graph(realistic_entity_map)
        assert len(kg.edges) == 2

    def test_join_path_invoices_to_customers(self, realistic_entity_map):
        kg = build_knowledge_graph(realistic_entity_map)
        path = kg.find_join_path("account_move", "res_partner")
        assert path is not None
        assert path.hop_count == 1

    def test_prompt_context_is_nonempty(self, realistic_entity_map):
        kg = build_knowledge_graph(realistic_entity_map)
        ctx = kg.to_prompt_context()
        assert len(ctx) > 100
        assert "account_move" in ctx
        assert "FILTER" in ctx

    def test_business_concepts_generated(self, realistic_entity_map):
        kg = build_knowledge_graph(realistic_entity_map)
        assert len(kg.concepts) > 0
        # invoices has base_filter + TRANSACTIONAL + amount_col → at least 2 concepts
        invoice_concepts = [c for c in kg.concepts if "invoices" in c]
        assert len(invoice_concepts) >= 2

    def test_filter_columns_detected(self, realistic_entity_map):
        kg = build_knowledge_graph(realistic_entity_map)
        node = kg.tables["account_move"]
        assert "move_type" in node.filter_columns
        assert "state" in node.filter_columns


# ═══════════════════════════════════════════════════════════════════════════
# TEST: VerificationEngine on realistic data
# ═══════════════════════════════════════════════════════════════════════════


class TestVerificationEngineIntegration:
    """Test VerificationEngine with realistic query results and findings."""

    def test_verify_findings_produces_report(
        self, realistic_query_results, realistic_baseline, realistic_findings
    ):
        kg = None  # KG is optional for verification
        verifier = VerificationEngine(realistic_query_results, realistic_baseline, kg)
        report = verifier.verify_findings(realistic_findings)

        assert isinstance(report, VerificationReport)
        assert report.total_claims > 0
        assert report.verified_claims > 0
        assert report.verification_rate > 0

    def test_number_registry_populated(
        self, realistic_query_results, realistic_baseline, realistic_findings
    ):
        verifier = VerificationEngine(realistic_query_results, realistic_baseline)
        report = verifier.verify_findings(realistic_findings)

        assert "total_revenue" in report.number_registry
        assert "num_invoices" in report.number_registry
        assert report.number_registry["total_revenue"].value == 1631559.62

    def test_measured_values_are_verified(
        self, realistic_query_results, realistic_baseline, realistic_findings
    ):
        """Findings that use exact values from query_results should be VERIFIED."""
        verifier = VerificationEngine(realistic_query_results, realistic_baseline)
        report = verifier.verify_findings(realistic_findings)

        verified = [r for r in report.results if r.status == "VERIFIED"]
        assert len(verified) >= 2  # At least total_revenue and AR values

    def test_verification_with_kg(
        self, realistic_entity_map, realistic_query_results, realistic_baseline, realistic_findings
    ):
        """Verification should work with a KG passed in."""
        kg = build_knowledge_graph(realistic_entity_map)
        verifier = VerificationEngine(realistic_query_results, realistic_baseline, kg)
        report = verifier.verify_findings(realistic_findings)

        assert isinstance(report, VerificationReport)
        assert report.total_claims > 0

    def test_prompt_context_includes_registry(
        self, realistic_query_results, realistic_baseline, realistic_findings
    ):
        verifier = VerificationEngine(realistic_query_results, realistic_baseline)
        report = verifier.verify_findings(realistic_findings)

        ctx = report.to_prompt_context()
        assert "NUMBER REGISTRY" in ctx
        assert "total_revenue" in ctx


# ═══════════════════════════════════════════════════════════════════════════
# TEST: gate_verification
# ═══════════════════════════════════════════════════════════════════════════


class TestGateVerification:
    """Test gate_verification pass/warn behavior."""

    def test_passes_with_good_data(
        self, realistic_query_results, realistic_baseline, realistic_findings
    ):
        verifier = VerificationEngine(realistic_query_results, realistic_baseline)
        report = verifier.verify_findings(realistic_findings)

        gate = gate_verification(report)
        assert gate["total_claims"] > 0
        assert gate["verification_rate"] > 0

    def test_warns_with_no_report(self):
        gate = gate_verification(None)
        assert gate["passed"] is False
        assert gate["verification_rate"] == 0
        assert gate["total_claims"] == 0

    def test_warns_with_low_verification_rate(self):
        """A report with all claims UNVERIFIABLE should not pass."""
        report = VerificationReport(
            total_claims=10,
            verified_claims=2,
            failed_claims=0,
            unverifiable_claims=8,
            verification_rate=0.2,
        )
        gate = gate_verification(report)
        assert gate["passed"] is False
        assert gate["verification_rate"] == 0.2

    def test_warns_with_critical_issues(self):
        """Critical issues should cause gate to not pass even with high rate."""
        report = VerificationReport(
            total_claims=10,
            verified_claims=9,
            failed_claims=1,
            verification_rate=0.9,
            issues=[{"severity": "critical", "description": "overdue > total AR"}],
        )
        gate = gate_verification(report)
        assert gate["passed"] is False
        assert gate["critical_issues"] == 1

    def test_passes_with_high_rate_no_critical(self):
        """High verification rate and no critical issues should pass."""
        report = VerificationReport(
            total_claims=10,
            verified_claims=9,
            failed_claims=0,
            unverifiable_claims=1,
            verification_rate=0.9,
            issues=[{"severity": "warning", "description": "minor inconsistency"}],
        )
        gate = gate_verification(report)
        assert gate["passed"] is True


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Verification report JSON serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestVerificationReportSerialization:
    """Test that verification report serializes correctly to JSON."""

    def test_serializes_to_json(
        self, realistic_query_results, realistic_baseline, realistic_findings
    ):
        verifier = VerificationEngine(realistic_query_results, realistic_baseline)
        report = verifier.verify_findings(realistic_findings)

        # Serialize exactly as deliver.py does
        vr_data = {
            "total_claims": report.total_claims,
            "verified_claims": report.verified_claims,
            "failed_claims": report.failed_claims,
            "verification_rate": report.verification_rate,
            "issues": report.issues,
            "number_registry": {
                k: {"value": v.value, "source": v.source_query, "confidence": v.confidence}
                for k, v in report.number_registry.items()
            },
        }

        json_str = json.dumps(vr_data, indent=2, ensure_ascii=False, default=str)

        # Verify it roundtrips
        parsed = json.loads(json_str)
        assert parsed["total_claims"] == report.total_claims
        assert parsed["verified_claims"] == report.verified_claims
        assert parsed["verification_rate"] == report.verification_rate
        assert "total_revenue" in parsed["number_registry"]
        assert parsed["number_registry"]["total_revenue"]["value"] == 1631559.62

    def test_writes_to_file(
        self, tmp_path, realistic_query_results, realistic_baseline, realistic_findings
    ):
        verifier = VerificationEngine(realistic_query_results, realistic_baseline)
        report = verifier.verify_findings(realistic_findings)

        vr_data = {
            "total_claims": report.total_claims,
            "verified_claims": report.verified_claims,
            "failed_claims": report.failed_claims,
            "verification_rate": report.verification_rate,
            "issues": report.issues,
            "number_registry": {
                k: {"value": v.value, "source": v.source_query, "confidence": v.confidence}
                for k, v in report.number_registry.items()
            },
        }

        vr_path = tmp_path / "verification_report.json"
        vr_path.write_text(
            json.dumps(vr_data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        assert vr_path.exists()
        loaded = json.loads(vr_path.read_text(encoding="utf-8"))
        assert loaded["total_claims"] > 0
        assert "number_registry" in loaded
