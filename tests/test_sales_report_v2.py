"""
Tests for Sales Report v2 — schema, queries, narrator fallback.

Refs: VAL-141
"""

from __future__ import annotations

import json

import pytest

from valinor.queries.sales_v2 import (
    SALES_V2_QUERY_KEYS,
    append_to_query_pack,
    build_sales_v2_queries,
    hhi_level,
)
from valinor.schemas.sales_report_v2 import (
    ConcentrationReport,
    RFMSegment,
    SalesReportV2,
    ValueConfidence,
)


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def openbravo_entity_map() -> dict:
    """Realistic entity_map for an Openbravo-like schema."""
    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "key_columns": {
                    "invoice_id": "c_invoice_id",
                    "invoice_date": "dateacct",
                    "customer_id": "c_bpartner_id",
                    "total_amount": "grandtotal",
                },
                "base_filter": "AND issotrx = 'Y'",
            },
            "customers": {
                "table": "c_bpartner",
                "key_columns": {
                    "customer_id": "c_bpartner_id",
                    "customer_name": "name",
                },
            },
            "invoice_lines": {
                "table": "c_invoiceline",
                "key_columns": {
                    "invoice_id": "c_invoice_id",
                    "product_id": "m_product_id",
                    "line_amount": "linenetamt",
                },
            },
            "products": {
                "table": "m_product",
                "key_columns": {
                    "product_id": "m_product_id",
                    "category": "m_product_category_id",
                },
            },
        },
    }


@pytest.fixture
def sample_valid_report() -> dict:
    return {
        "client_name": "Gloria",
        "period": "2025-07 to 2026-06",
        "currency": "EUR",
        "generated_at": "2026-04-18T13:00:00+00:00",
        "kpi_bar": [
            {"label": "Clientes activos", "value": "959",
             "confidence": "measured", "sub": None, "trend_pct": None},
        ],
        "rfm_segments": [
            {"segment": "champions", "count": 42, "revenue_share_pct": 28.3,
             "avg_ltv": 54200, "recommended_action": "Programa VIP",
             "confidence": "measured"},
        ],
        "concentration": {
            "hhi": 1820.5, "hhi_level": "moderate",
            "cr1_pct": 14.8, "cr5_pct": 34.2, "cr10_pct": 48.6,
            "total_customers": 959,
            "interpretation": "Cartera moderadamente concentrada.",
            "confidence": "measured",
        },
        "top_customers": [
            {"customer_name": "Cliente A", "customer_id": "BP-001",
             "ltv_eur": 1420000, "share_pct": 14.8,
             "last_purchase": "2026-06-25", "risk": "low",
             "confidence": "measured"},
        ],
        "category_performance": [
            {"category": "Juguetes", "revenue_eur": 312000, "share_pct": 31.4,
             "mom_pct": -12.0, "trend": "baja", "confidence": "measured"},
        ],
        "magic_matrix": [
            {"segment": "champions", "category": "Alimentación",
             "penetration_pct": 89.0, "gap_opportunity_eur": 0,
             "confidence": "measured"},
        ],
        "call_list": [
            {"rank": 1, "customer_name": "Cliente X", "customer_id": "BP-042",
             "deal_risk_score": 87.3, "last_purchase": "2026-02-14",
             "ltv_eur": 54000, "recovery_potential_eur": 16200,
             "recovery_confidence": "estimated",
             "reason": "Sin compras 63 días, LTV top-10",
             "script_hint": "Consultar cambio de contacto o ERP"},
        ],
        "executive_summary": "Cartera saludable con 3 focos críticos.",
        "data_caveats": [],
    }


# ─────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────


class TestSchema:
    def test_valid_report_passes_validation(self, sample_valid_report: dict):
        report = SalesReportV2.model_validate(sample_valid_report)
        assert report.client_name == "Gloria"
        assert report.concentration.hhi_level == "moderate"
        assert report.rfm_segments[0].segment == RFMSegment.CHAMPIONS.value

    def test_confidence_enum_rejects_unknown(self, sample_valid_report: dict):
        sample_valid_report["kpi_bar"][0]["confidence"] = "bogus"
        with pytest.raises(Exception):
            SalesReportV2.model_validate(sample_valid_report)

    def test_risk_enum_rejects_unknown(self, sample_valid_report: dict):
        sample_valid_report["top_customers"][0]["risk"] = "critical"
        with pytest.raises(Exception):
            SalesReportV2.model_validate(sample_valid_report)

    def test_percentages_bounded(self, sample_valid_report: dict):
        sample_valid_report["concentration"]["cr1_pct"] = 150.0
        with pytest.raises(Exception):
            SalesReportV2.model_validate(sample_valid_report)

    def test_hhi_bounded_0_to_10000(self):
        with pytest.raises(Exception):
            ConcentrationReport(
                hhi=15000, hhi_level="high_risk",
                cr1_pct=10, cr5_pct=20, cr10_pct=30,
                total_customers=100, interpretation="x",
                confidence=ValueConfidence.MEASURED,
            )

    def test_minimal_empty_report_valid(self):
        """Fallback path must be schema-valid."""
        report = SalesReportV2(
            client_name="Unknown", period="N/A", currency="EUR",
            generated_at="2026-04-18T00:00:00+00:00",
            kpi_bar=[], rfm_segments=[],
            concentration=ConcentrationReport(
                hhi=0, hhi_level="diversified",
                cr1_pct=0, cr5_pct=0, cr10_pct=0,
                total_customers=0, interpretation="n/a",
                confidence=ValueConfidence.INFERRED,
            ),
            top_customers=[], category_performance=[],
            magic_matrix=[], call_list=[],
            executive_summary="empty", data_caveats=["test"],
        )
        assert report.data_caveats == ["test"]


# ─────────────────────────────────────────────────────────────────────
# Queries
# ─────────────────────────────────────────────────────────────────────


class TestQueries:
    def test_all_5_queries_built(self, openbravo_entity_map):
        queries = build_sales_v2_queries(openbravo_entity_map)
        assert set(queries.keys()) == set(SALES_V2_QUERY_KEYS)
        for sql in queries.values():
            assert "SELECT" in sql.upper()

    def test_queries_use_cartographer_column_names(self, openbravo_entity_map):
        queries = build_sales_v2_queries(openbravo_entity_map)
        # Should use openbravo semantic mapping, not hardcoded fallbacks
        assert "c_invoice" in queries["rfm_segmentation"]
        assert "grandtotal" in queries["rfm_segmentation"]
        assert "c_bpartner_id" in queries["concentration_hhi"]
        # base_filter is injected
        assert "issotrx = 'Y'" in queries["concentration_hhi"]

    def test_queries_fallback_when_entity_map_empty(self):
        queries = build_sales_v2_queries({})
        # Should not raise; uses fallback table names
        assert "invoices" in queries["rfm_segmentation"]
        assert "customers" in queries["concentration_top_customers"]

    def test_hhi_level_thresholds(self):
        assert hhi_level(100) == "diversified"
        assert hhi_level(1499) == "diversified"
        assert hhi_level(1500) == "moderate"
        assert hhi_level(2499) == "moderate"
        assert hhi_level(2500) == "high_risk"
        assert hhi_level(10000) == "high_risk"

    def test_append_to_query_pack_adds_5_entries(self, openbravo_entity_map):
        pack = {"queries": [{"id": "existing", "sql": "SELECT 1", "domain": "test"}]}
        result = append_to_query_pack(pack, openbravo_entity_map)
        assert len(result["queries"]) == 6  # 1 existing + 5 new
        new_ids = {q["id"] for q in result["queries"][1:]}
        assert new_ids == set(SALES_V2_QUERY_KEYS)
        # All new queries tagged with sales domain
        assert all(q["domain"] == "sales" for q in result["queries"][1:])

    def test_append_creates_queries_key_if_missing(self, openbravo_entity_map):
        pack: dict = {}
        result = append_to_query_pack(pack, openbravo_entity_map)
        assert "queries" in result
        assert len(result["queries"]) == 5


# ─────────────────────────────────────────────────────────────────────
# Narrator fallback (no LLM)
# ─────────────────────────────────────────────────────────────────────


class TestNarratorFallback:
    def test_fallback_returns_schema_valid_json(self):
        from valinor.agents.narrators.sales import _fallback_report

        raw = _fallback_report({"display_name": "Test"}, reason="synthetic")
        assert isinstance(raw, str)
        parsed = json.loads(raw)
        # Must round-trip through the schema
        validated = SalesReportV2.model_validate(parsed)
        assert validated.client_name == "Test"
        assert validated.data_caveats == ["synthetic"]
