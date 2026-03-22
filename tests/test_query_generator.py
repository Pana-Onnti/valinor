"""
Tests for the KG-guided Query Generator.

Validates:
  1. SQLBuilder fluent API with KG-guided JOINs and filters
  2. QueryGenerator with Gloria (Openbravo) schema
  3. QueryGenerator with Odoo schema (different table/column names)
  4. Fallback to static templates when KG is unavailable
  5. Integration test against Gloria DB (skipped if no DB)

Anti-overfitting: tests use TWO different schemas to ensure no
hardcoded table/column names leak through.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest

from valinor.knowledge_graph import SchemaKnowledgeGraph, build_knowledge_graph
from valinor.agents.query_generator import QueryGenerator, SQLBuilder
from valinor.agents.query_builder import build_queries, build_queries_adaptive


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES — Two different schemas to prevent overfitting
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def gloria_entity_map():
    """Gloria Openbravo schema — the original production schema."""
    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "type": "TRANSACTIONAL",
                "row_count": 4117,
                "key_columns": {
                    "pk": "c_invoice_id",
                    "invoice_date": "dateinvoiced",
                    "amount_col": "grandtotal",
                    "customer_fk": "c_bpartner_id",
                },
                "base_filter": "issotrx='Y' AND docstatus='CO' AND isactive='Y'",
                "probed_values": {
                    "issotrx": {"Y": 2366, "N": 1751},
                    "docstatus": {"CO": 4108, "DR": 9},
                    "isactive": {"Y": 4117},
                },
            },
            "customers": {
                "table": "c_bpartner",
                "type": "MASTER",
                "row_count": 88,
                "key_columns": {
                    "pk": "c_bpartner_id",
                    "customer_name": "name",
                },
                "base_filter": "iscustomer='Y' AND isactive='Y'",
                "probed_values": {
                    "iscustomer": {"Y": 49, "N": 39},
                    "isactive": {"Y": 81, "N": 7},
                },
            },
            "payment_schedule": {
                "table": "fin_payment_schedule",
                "type": "TRANSACTIONAL",
                "row_count": 8019,
                "key_columns": {
                    "pk": "fin_payment_schedule_id",
                    "invoice_fk": "c_invoice_id",
                    "outstanding_amount": "outstandingamt",
                    "due_date": "duedate",
                },
                "base_filter": "isactive='Y'",
                "probed_values": {
                    "isactive": {"Y": 8019},
                },
            },
        },
        "relationships": [
            {"from": "invoices", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
            {"from": "payment_schedule", "to": "invoices", "via": "c_invoice_id", "cardinality": "N:1"},
        ],
    }


@pytest.fixture
def odoo_entity_map():
    """Odoo schema — completely different table/column names."""
    return {
        "entities": {
            "invoices": {
                "table": "account_move",
                "type": "TRANSACTIONAL",
                "row_count": 7300,
                "key_columns": {
                    "pk": "id",
                    "invoice_date": "invoice_date",
                    "amount_col": "amount_total",
                    "customer_fk": "partner_id",
                },
                "base_filter": "move_type IN ('out_invoice','out_refund') AND state='posted'",
                "probed_values": {
                    "move_type": {"out_invoice": 5000, "in_invoice": 2000, "out_refund": 300},
                    "state": {"posted": 6800, "draft": 500},
                },
            },
            "partners": {
                "table": "res_partner",
                "type": "MASTER",
                "row_count": 950,
                "key_columns": {
                    "pk": "id",
                    "customer_name": "name",
                },
                "base_filter": "active=true AND is_company=true",
                "probed_values": {
                    "active": {"True": 900, "False": 50},
                },
            },
            "payment_lines": {
                "table": "account_move_line",
                "type": "TRANSACTIONAL",
                "row_count": 15000,
                "key_columns": {
                    "pk": "id",
                    "invoice_fk": "move_id",
                    "outstanding_amount": "amount_residual",
                    "due_date": "date_maturity",
                },
                "base_filter": "parent_state='posted'",
                "probed_values": {
                    "parent_state": {"posted": 14000, "draft": 1000},
                },
            },
        },
        "relationships": [
            {"from": "invoices", "to": "partners", "via": "partner_id", "cardinality": "N:1"},
            {"from": "payment_lines", "to": "invoices", "via": "move_id", "cardinality": "N:1"},
        ],
    }


@pytest.fixture
def gloria_kg(gloria_entity_map):
    return build_knowledge_graph(gloria_entity_map)


@pytest.fixture
def odoo_kg(odoo_entity_map):
    return build_knowledge_graph(odoo_entity_map)


@pytest.fixture
def period():
    return {"start": "2025-01-01", "end": "2025-12-31", "label": "FY2025"}


# ═══════════════════════════════════════════════════════════════════════════
# TEST: SQLBuilder
# ═══════════════════════════════════════════════════════════════════════════


class TestSQLBuilder:

    def test_simple_select(self, gloria_kg):
        """SELECT col FROM table produces valid SQL."""
        builder = SQLBuilder(gloria_kg)
        sql = (
            builder.from_table("c_invoice")
            .select("COUNT(*)", "cnt")
            .build()
        )
        assert "SELECT" in sql
        assert "COUNT(*) AS cnt" in sql
        assert "FROM c_invoice" in sql

    def test_join_uses_kg(self, gloria_kg):
        """join_to() asks KG, gets correct JOIN path."""
        builder = SQLBuilder(gloria_kg)
        sql = (
            builder.from_table("c_invoice", "inv")
            .select("inv.grandtotal")
            .join_to("c_bpartner", "cust")
            .build()
        )
        assert "JOIN c_bpartner cust ON" in sql
        assert "c_bpartner_id" in sql

    def test_multi_hop_join(self, gloria_kg):
        """join_to() through intermediate table generates two JOINs."""
        builder = SQLBuilder(gloria_kg)
        sql = (
            builder.from_table("fin_payment_schedule", "pay")
            .select("pay.outstandingamt")
            .join_to("c_invoice", "inv")
            .join_to("c_bpartner", "cust")
            .build()
        )
        assert "JOIN c_invoice inv ON" in sql
        assert "JOIN c_bpartner cust ON" in sql

    def test_where_filters_from_kg(self, gloria_kg):
        """where_filters() injects base_filter from KG."""
        builder = SQLBuilder(gloria_kg)
        sql = (
            builder.from_table("c_invoice")
            .select("COUNT(*)")
            .where_filters("c_invoice")
            .build()
        )
        sql_lower = sql.lower()
        assert "issotrx" in sql_lower
        assert "docstatus" in sql_lower

    def test_where_period(self, gloria_kg, period):
        """where_period() adds date range conditions."""
        builder = SQLBuilder(gloria_kg)
        sql = (
            builder.from_table("c_invoice")
            .select("COUNT(*)")
            .where_period("dateinvoiced", period)
            .build()
        )
        assert "2025-01-01" in sql
        assert "2025-12-31" in sql

    def test_group_by_having_order_limit(self, gloria_kg):
        """All SQL clauses are correctly assembled."""
        builder = SQLBuilder(gloria_kg)
        sql = (
            builder.from_table("c_invoice")
            .select("c_bpartner_id")
            .select("SUM(grandtotal)", "total")
            .group_by("c_bpartner_id")
            .having("SUM(grandtotal) > 1000")
            .order_by("total")
            .limit(10)
            .build()
        )
        assert "GROUP BY c_bpartner_id" in sql
        assert "HAVING SUM(grandtotal) > 1000" in sql
        assert "ORDER BY total DESC" in sql
        assert "LIMIT 10" in sql

    def test_no_join_path_raises_error(self, gloria_kg):
        """join_to() raises ValueError when no path exists."""
        builder = SQLBuilder(gloria_kg)
        builder.from_table("c_invoice")
        with pytest.raises(ValueError, match="No JOIN path found"):
            builder.join_to("nonexistent_table")

    def test_no_from_raises_error(self, gloria_kg):
        """join_to() raises ValueError when from_table not called."""
        builder = SQLBuilder(gloria_kg)
        with pytest.raises(ValueError, match="Must call from_table"):
            builder.join_to("c_bpartner")


# ═══════════════════════════════════════════════════════════════════════════
# TEST: QueryGenerator with Gloria (Openbravo) schema
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryGeneratorGloria:

    def test_revenue_summary_generated(self, gloria_kg, gloria_entity_map, period):
        """Produces valid SELECT SUM/COUNT."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_revenue_summary()
        assert result is not None
        sql = result["sql"].upper()
        assert "SUM" in sql
        assert "COUNT" in sql
        assert "FROM C_INVOICE" in sql
        assert "grandtotal" in result["sql"]

    def test_ar_joins_through_invoice(self, gloria_kg, gloria_entity_map, period):
        """AR query JOINs through invoice (not direct to customer)."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_ar_outstanding()
        assert result is not None
        sql = result["sql"]
        assert "JOIN c_invoice" in sql
        assert "outstandingamt" in sql

    def test_aging_analysis_generated(self, gloria_kg, gloria_entity_map, period):
        """Aging query has CASE buckets and GROUP BY."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_aging_analysis()
        assert result is not None
        sql = result["sql"]
        assert "CASE" in sql
        assert "GROUP BY" in sql
        assert "0-30d" in sql

    def test_customer_concentration_has_subquery(self, gloria_kg, gloria_entity_map, period):
        """pct_revenue computed correctly with subquery."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_customer_concentration()
        assert result is not None
        sql = result["sql"]
        assert "pct_revenue" in sql
        assert "NULLIF" in sql
        # Should have a subquery for total
        assert sql.count("SELECT") >= 2

    def test_top_debtors_joins_through_invoice(self, gloria_kg, gloria_entity_map, period):
        """Top debtors JOINs pay->inv->cust (not pay->cust directly)."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_top_debtors()
        assert result is not None
        sql = result["sql"]
        assert "JOIN c_invoice" in sql
        assert "JOIN c_bpartner" in sql
        assert "LIMIT 20" in sql

    def test_dormant_has_having_clause(self, gloria_kg, gloria_entity_map, period):
        """HAVING MAX(date) < threshold for dormant detection."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_dormant_customers()
        assert result is not None
        sql = result["sql"]
        assert "HAVING" in sql
        assert "90 days" in sql

    def test_generate_all_produces_queries(self, gloria_kg, gloria_entity_map, period):
        """generate_all() returns a dict with queries list."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_all()
        assert "queries" in result
        assert len(result["queries"]) >= 4  # at least revenue, ar, aging, concentration
        for q in result["queries"]:
            assert "id" in q
            assert "sql" in q
            assert q["source"] == "kg_generator"

    def test_filters_injected_in_revenue(self, gloria_kg, gloria_entity_map, period):
        """Revenue query must include Cartographer's base_filter."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_revenue_summary()
        sql = result["sql"].lower()
        assert "issotrx" in sql
        assert "docstatus" in sql

    def test_no_hardcoded_openbravo_in_generator(self, gloria_kg, gloria_entity_map, period):
        """No hardcoded c_invoice, c_bpartner checks in QueryGenerator logic."""
        # This is verified by the Odoo tests passing with the same code
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_all()
        assert len(result["queries"]) > 0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: QueryGenerator with Odoo schema (different table/column names)
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryGeneratorOdoo:

    def test_revenue_summary_odoo(self, odoo_kg, odoo_entity_map, period):
        """Revenue summary works with Odoo table/column names."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_revenue_summary()
        assert result is not None
        sql = result["sql"]
        assert "account_move" in sql
        assert "amount_total" in sql
        # No Openbravo references
        assert "c_invoice" not in sql
        assert "grandtotal" not in sql

    def test_ar_outstanding_odoo(self, odoo_kg, odoo_entity_map, period):
        """AR outstanding works with Odoo schema."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_ar_outstanding()
        assert result is not None
        sql = result["sql"]
        assert "account_move_line" in sql
        assert "amount_residual" in sql
        assert "JOIN account_move" in sql

    def test_aging_analysis_odoo(self, odoo_kg, odoo_entity_map, period):
        """Aging works with Odoo date_maturity column."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_aging_analysis()
        assert result is not None
        sql = result["sql"]
        assert "date_maturity" in sql
        assert "amount_residual" in sql

    def test_customer_concentration_odoo(self, odoo_kg, odoo_entity_map, period):
        """Customer concentration works with Odoo res_partner."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_customer_concentration()
        assert result is not None
        sql = result["sql"]
        assert "res_partner" in sql
        assert "account_move" in sql

    def test_dormant_customers_odoo(self, odoo_kg, odoo_entity_map, period):
        """Dormant customers works with Odoo schema."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_dormant_customers()
        assert result is not None
        sql = result["sql"]
        assert "res_partner" in sql
        assert "HAVING" in sql

    def test_top_debtors_odoo(self, odoo_kg, odoo_entity_map, period):
        """Top debtors works with Odoo schema, JOINs correctly."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_top_debtors()
        assert result is not None
        sql = result["sql"]
        assert "account_move_line" in sql
        assert "JOIN account_move" in sql
        assert "JOIN res_partner" in sql

    def test_generate_all_odoo(self, odoo_kg, odoo_entity_map, period):
        """generate_all() produces queries for Odoo schema too."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_all()
        assert len(result["queries"]) >= 4
        # Verify NO Openbravo references in any query
        for q in result["queries"]:
            assert "c_invoice" not in q["sql"]
            assert "c_bpartner" not in q["sql"]
            assert "fin_payment" not in q["sql"]

    def test_odoo_filters_injected(self, odoo_kg, odoo_entity_map, period):
        """Odoo filters (move_type, state) are injected, not Openbravo filters."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_revenue_summary()
        sql = result["sql"].lower()
        assert "move_type" in sql
        assert "state" in sql
        # No Openbravo filter references
        assert "issotrx" not in sql
        assert "docstatus" not in sql


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Fallback to static templates
# ═══════════════════════════════════════════════════════════════════════════


class TestFallback:

    def test_falls_back_to_static_templates(self, gloria_entity_map, period):
        """When KG is None, uses build_queries() static templates."""
        result = build_queries_adaptive(gloria_entity_map, period, kg=None)
        assert "queries" in result
        # Should produce queries from static templates
        assert len(result["queries"]) > 0
        # Verify they come from templates (no "source": "kg_generator")
        for q in result["queries"]:
            assert q.get("source") != "kg_generator"

    def test_adaptive_uses_kg_when_available(self, gloria_kg, gloria_entity_map, period):
        """When KG is provided, uses QueryGenerator."""
        result = build_queries_adaptive(gloria_entity_map, period, kg=gloria_kg)
        assert "queries" in result
        assert len(result["queries"]) > 0
        # All queries should come from KG generator
        for q in result["queries"]:
            assert q["source"] == "kg_generator"

    def test_adaptive_falls_back_on_error(self, gloria_entity_map, period):
        """When KG generation raises, falls back to static templates."""
        # Pass a broken KG (not built from entity_map)
        broken_kg = SchemaKnowledgeGraph()
        # Empty KG will produce no queries from generator, triggering fallback
        result = build_queries_adaptive(gloria_entity_map, period, kg=broken_kg)
        assert "queries" in result
        assert len(result["queries"]) > 0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Entity detection logic
# ═══════════════════════════════════════════════════════════════════════════


class TestEntityDetection:

    def test_find_revenue_entity_gloria(self, gloria_kg, gloria_entity_map, period):
        """Finds invoices as revenue entity in Gloria schema."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        entity = gen._find_revenue_entity()
        assert entity is not None
        assert entity["table"] == "c_invoice"

    def test_find_revenue_entity_odoo(self, odoo_kg, odoo_entity_map, period):
        """Finds account_move as revenue entity in Odoo schema."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        entity = gen._find_revenue_entity()
        assert entity is not None
        assert entity["table"] == "account_move"

    def test_find_customer_entity_gloria(self, gloria_kg, gloria_entity_map, period):
        """Finds c_bpartner as customer entity in Gloria schema."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        entity = gen._find_customer_entity()
        assert entity is not None
        assert entity["table"] == "c_bpartner"

    def test_find_customer_entity_odoo(self, odoo_kg, odoo_entity_map, period):
        """Finds res_partner as customer entity in Odoo schema."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        entity = gen._find_customer_entity()
        assert entity is not None
        assert entity["table"] == "res_partner"

    def test_find_payment_entity_gloria(self, gloria_kg, gloria_entity_map, period):
        """Finds fin_payment_schedule as payment entity in Gloria schema."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        entity = gen._find_payment_entity()
        assert entity is not None
        assert entity["table"] == "fin_payment_schedule"

    def test_find_payment_entity_odoo(self, odoo_kg, odoo_entity_map, period):
        """Finds account_move_line as payment entity in Odoo schema."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        entity = gen._find_payment_entity()
        assert entity is not None
        assert entity["table"] == "account_move_line"

    def test_find_key_column_tries_multiple_keys(self, gloria_kg, gloria_entity_map, period):
        """_find_key_column tries semantic keys in order."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        kc = {"amount_col": "grandtotal", "pk": "c_invoice_id"}
        assert gen._find_key_column(kc, "amount_col", "amount", "amount_total") == "grandtotal"
        assert gen._find_key_column(kc, "nonexistent", "amount_col") == "grandtotal"
        assert gen._find_key_column(kc, "nonexistent1", "nonexistent2") is None


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Integration against Gloria DB (skip if no DB)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(
    not os.environ.get("GLORIA_DB_URL"),
    reason="GLORIA_DB_URL not set — skip integration test",
)
class TestIntegrationGloriaDB:

    def test_generated_queries_execute(self, gloria_kg, gloria_entity_map, period):
        """Generated queries execute without SQL errors against the real DB."""
        import sqlalchemy

        engine = sqlalchemy.create_engine(os.environ["GLORIA_DB_URL"])
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_all()

        for q in result["queries"]:
            with engine.connect() as conn:
                try:
                    conn.execute(sqlalchemy.text(q["sql"]))
                except Exception as e:
                    pytest.fail(f"Query {q['id']} failed: {e}\nSQL: {q['sql']}")


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Window function queries (revenue trend, YoY comparison)
# ═══════════════════════════════════════════════════════════════════════════


class TestWindowFunctionQueries:

    def test_revenue_trend_generated(self, gloria_kg, gloria_entity_map, period):
        """Revenue trend SQL contains LAG, OVER, and moving_avg_3m."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_revenue_trend()
        assert result is not None
        sql = result["sql"]
        assert "LAG" in sql
        assert "OVER" in sql
        assert "moving_avg_3m" in sql

    def test_revenue_trend_has_cte(self, gloria_kg, gloria_entity_map, period):
        """Revenue trend SQL starts with WITH monthly_agg."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_revenue_trend()
        assert result is not None
        assert result["sql"].strip().startswith("WITH monthly_agg")

    def test_yoy_comparison_generated(self, gloria_kg, gloria_entity_map, period):
        """YoY comparison SQL contains yoy_growth_pct and prior_year_revenue."""
        gen = QueryGenerator(gloria_kg, gloria_entity_map, period)
        result = gen.generate_yoy_comparison()
        assert result is not None
        sql = result["sql"]
        assert "yoy_growth_pct" in sql
        assert "prior_year_revenue" in sql

    def test_revenue_trend_with_odoo_schema(self, odoo_kg, odoo_entity_map, period):
        """Revenue trend with Odoo schema uses amount_total and invoice_date."""
        gen = QueryGenerator(odoo_kg, odoo_entity_map, period)
        result = gen.generate_revenue_trend()
        assert result is not None
        sql = result["sql"]
        assert "amount_total" in sql
        assert "invoice_date" in sql

    def test_revenue_trend_returns_none_without_date_col(self, gloria_kg, period):
        """Entity without date_col should return None for revenue trend."""
        entity_map = {
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "type": "TRANSACTIONAL",
                    "key_columns": {
                        "pk": "c_invoice_id",
                        "amount_col": "grandtotal",
                        # no date_col / invoice_date
                    },
                },
            },
            "relationships": [],
        }
        gen = QueryGenerator(gloria_kg, entity_map, period)
        result = gen.generate_revenue_trend()
        assert result is None

    def test_cte_build_method(self, gloria_kg):
        """SQLBuilder.with_cte() and build() produce valid WITH clause."""
        builder = SQLBuilder(gloria_kg)
        sql = (
            builder
            .with_cte("totals", "SELECT SUM(x) AS s FROM t")
            .from_table("totals")
            .select("s")
            .build()
        )
        assert sql.strip().startswith("WITH totals AS")
        assert "SELECT SUM(x) AS s FROM t" in sql
        assert "FROM totals" in sql
