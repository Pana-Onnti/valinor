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
    CustomerProfile,
    NextAction,
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
                    "pk": "c_invoice_id",
                    "invoice_date": "dateacct",
                    "customer_fk": "c_bpartner_id",
                    "amount_col": "grandtotal",
                },
                "base_filter": "issotrx = 'Y'",
            },
            "customers": {
                "table": "c_bpartner",
                "key_columns": {
                    "pk": "c_bpartner_id",
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

    def test_base_filter_injected_with_and_prefix(self, openbravo_entity_map):
        """Cartographer emits bare predicates — we must prepend AND to append to WHERE."""
        queries = build_sales_v2_queries(openbravo_entity_map)
        # Every query with a WHERE must contain " AND issotrx = 'Y'", never naked.
        for qid in ("concentration_hhi", "concentration_top_customers",
                    "cross_sell_matrix", "churn_risk_scoring"):
            sql = queries[qid]
            assert " AND issotrx = 'Y'" in sql, f"{qid} missing AND prefix"
            # Guard against double-AND regression
            assert "AND AND" not in sql, f"{qid} has double AND"

    def test_base_filter_accepts_legacy_and_prefix(self):
        """If a legacy entity_map already prefixed the filter with AND, don't double it."""
        legacy_map = {
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "key_columns": {
                        "pk": "c_invoice_id", "invoice_date": "dateacct",
                        "customer_fk": "c_bpartner_id", "amount_col": "grandtotal",
                    },
                    "base_filter": "AND issotrx = 'Y'",
                },
                "customers": {
                    "table": "c_bpartner",
                    "key_columns": {"pk": "c_bpartner_id", "customer_name": "name"},
                },
            },
        }
        sql = build_sales_v2_queries(legacy_map)["concentration_hhi"]
        assert "AND AND" not in sql
        assert " AND issotrx = 'Y'" in sql

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

    def test_fallback_includes_hero_defaults(self):
        from valinor.agents.narrators.sales import _fallback_report

        parsed = json.loads(_fallback_report({"display_name": "X"}, reason="r"))
        assert parsed["hero_loss_eur"] == 0.0
        assert parsed["hero_loss_headline"] == ""
        assert parsed["next_actions"] == []


# ─────────────────────────────────────────────────────────────────────
# Refactor fixes: loss framing, profiles, MoM null, UUID cleanup
# ─────────────────────────────────────────────────────────────────────


class TestRefactorFixes:
    """Covers the 8 critiques that drove the demo-grade refactor."""

    def test_hero_loss_eur_bounded_and_optional(self):
        """hero_loss_eur defaults to 0, must be ≥ 0."""
        r = SalesReportV2(
            client_name="X", period="P", currency="EUR",
            generated_at="2026-04-18T00:00:00+00:00",
            kpi_bar=[], rfm_segments=[],
            concentration={"hhi": 0, "hhi_level": "diversified",
                           "cr1_pct": 0, "cr5_pct": 0, "cr10_pct": 0,
                           "total_customers": 0, "interpretation": "n/a",
                           "confidence": "inferred"},
            top_customers=[], category_performance=[],
            magic_matrix=[], call_list=[], next_actions=[],
            executive_summary="s", data_caveats=[],
        )
        assert r.hero_loss_eur == 0.0
        assert r.hero_loss_headline == ""
        assert r.next_actions == []

    def test_customer_profile_enum(self):
        assert CustomerProfile.ACCOUNT_GRANDE.value == "account_grande"
        assert CustomerProfile.CUENTA_MEDIA.value == "cuenta_media"
        assert CustomerProfile.OUTLIER.value == "outlier"

    def test_category_performance_mom_null_allowed(self, sample_valid_report: dict):
        """MoM stays null when only 1 period is available — don't fake 0."""
        sample_valid_report["category_performance"][0]["mom_pct"] = None
        sample_valid_report["category_performance"][0]["trend"] = None
        report = SalesReportV2.model_validate(sample_valid_report)
        assert report.category_performance[0].mom_pct is None
        assert report.category_performance[0].trend is None

    def test_call_list_entry_requires_profile(self, sample_valid_report: dict):
        """CallListEntry.profile defaults to cuenta_media when not supplied."""
        # Remove profile from sample — should default
        if "profile" in sample_valid_report["call_list"][0]:
            del sample_valid_report["call_list"][0]["profile"]
        report = SalesReportV2.model_validate(sample_valid_report)
        assert report.call_list[0].profile == "cuenta_media"

    def test_call_list_profile_enum_strict(self, sample_valid_report: dict):
        sample_valid_report["call_list"][0]["profile"] = "invalid_profile"
        with pytest.raises(Exception):
            SalesReportV2.model_validate(sample_valid_report)

    def test_next_action_schema(self):
        na = NextAction(
            priority=1, title="Llamar top 5",
            rationale="LTV €1.1M", impact_eur=16000,
            impact_confidence=ValueConfidence.ESTIMATED,
            deadline="Esta semana",
        )
        assert na.priority == 1
        assert na.impact_eur == 16000

    def test_next_action_impact_null_coerces_to_zero(self):
        """LLM sometimes emits impact_eur=null — must coerce to 0.0, not reject."""
        na = NextAction.model_validate({
            "priority": 2, "title": "Revisar", "rationale": "r",
            "impact_eur": None,
        })
        assert na.impact_eur == 0.0

    def test_next_action_impact_missing_defaults_to_zero(self):
        na = NextAction.model_validate({
            "priority": 1, "title": "t", "rationale": "r",
        })
        assert na.impact_eur == 0.0

    def test_concentration_null_coercion(self):
        """LLM emits nulls for concentration → must not reject, must default."""
        report = SalesReportV2.model_validate({
            "client_name": "X", "period": "P", "currency": "EUR",
            "generated_at": "2026-04-18T00:00:00+00:00",
            "kpi_bar": [], "rfm_segments": [],
            "concentration": {
                "hhi": None, "hhi_level": None,
                "cr1_pct": None, "cr5_pct": None, "cr10_pct": None,
            },
            "top_customers": [], "category_performance": [],
            "magic_matrix": [], "call_list": [],
            "executive_summary": "s", "data_caveats": [],
        })
        assert report.concentration.hhi == 0.0
        assert report.concentration.hhi_level == "diversified"


# ─────────────────────────────────────────────────────────────────────
# Query SQL shape — ensures the refactor added new columns
# ─────────────────────────────────────────────────────────────────────


class TestQueryShapeAfterRefactor:
    """SQL-level checks — no DB required, pure string inspection."""

    def test_churn_risk_scoring_emits_profile_and_frequency(self, openbravo_entity_map):
        sql = build_sales_v2_queries(openbravo_entity_map)["churn_risk_scoring"]
        assert "profile" in sql.lower()
        assert "frequency" in sql.lower()
        assert "confidence_factor" in sql.lower() or "CASE" in sql

    def test_churn_risk_scoring_penalizes_small_samples(self, openbravo_entity_map):
        """Confidence factor CASE must penalize freq<=3."""
        sql = build_sales_v2_queries(openbravo_entity_map)["churn_risk_scoring"]
        assert "frequency <= 3" in sql
        assert "0.10" in sql

    def test_cross_sell_matrix_joins_categories(self, openbravo_entity_map):
        sql = build_sales_v2_queries(openbravo_entity_map)["cross_sell_matrix"]
        # Must reference the product_categories lookup (JOIN or COALESCE)
        assert "m_product_category" in sql.lower() or "product_categories" in sql.lower()
        # Must emit category revenue
        assert "category_revenue_eur" in sql.lower() or "segment_spent_eur" in sql.lower()

    def test_all_queries_run_on_entity_map(self, openbravo_entity_map):
        """All 5 queries must be non-empty SQL strings using the mapped tables."""
        queries = build_sales_v2_queries(openbravo_entity_map)
        assert len(queries) == 5
        for qid, sql in queries.items():
            assert sql.strip(), f"{qid} is empty"
            assert "SELECT" in sql.upper(), f"{qid} has no SELECT"
