"""
Tests for the Schema Knowledge Graph.

Validates that the graph is 100% data-driven (from entity_map only):
  1. Graph construction from entity_map
  2. JOIN path reasoning (shortest path)
  3. Filter column awareness (from base_filter, not hardcoded)
  4. Ambiguous column detection
  5. Query anti-pattern detection
  6. Specific Gloria bug prevention (without hardcoded ERP knowledge)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest
from valinor.knowledge_graph import SchemaKnowledgeGraph, build_knowledge_graph


@pytest.fixture
def gloria_entity_map():
    """Entity map matching the real Gloria Openbravo schema.
    All discriminator info comes from Cartographer's probed_values + base_filter."""
    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "type": "TRANSACTIONAL",
                "row_count": 4117,
                "confidence": 0.99,
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
                "confidence": 0.98,
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
                "confidence": 0.97,
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
            "payments": {
                "table": "fin_payment",
                "type": "TRANSACTIONAL",
                "row_count": 5239,
                "confidence": 0.97,
                "key_columns": {
                    "pk": "fin_payment_id",
                    "partner_fk": "c_bpartner_id",
                    "amount": "amount",
                },
                "base_filter": "isreceipt='Y' AND isactive='Y'",
                "probed_values": {
                    "isreceipt": {"Y": 3628, "N": 1611},
                    "isactive": {"Y": 5239},
                },
            },
        },
        "relationships": [
            {"from": "invoices", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
            {"from": "payment_schedule", "to": "invoices", "via": "c_invoice_id", "cardinality": "N:1"},
            {"from": "payments", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
        ],
    }


@pytest.fixture
def kg(gloria_entity_map):
    return build_knowledge_graph(gloria_entity_map)


# ═══════════════════════════════════════════════════════════════════════════
# TEST: GRAPH CONSTRUCTION (data-driven)
# ═══════════════════════════════════════════════════════════════════════════

class TestGraphConstruction:

    def test_tables_created(self, kg):
        assert "c_invoice" in kg.tables
        assert "c_bpartner" in kg.tables
        assert "fin_payment_schedule" in kg.tables
        assert "fin_payment" in kg.tables

    def test_edges_created(self, kg):
        assert len(kg.edges) == 3

    def test_filter_columns_from_base_filter(self, kg):
        """Filter columns are extracted from Cartographer's base_filter, not hardcoded."""
        inv_node = kg.tables["c_invoice"]
        assert "issotrx" in inv_node.filter_columns
        assert "docstatus" in inv_node.filter_columns
        assert "isactive" in inv_node.filter_columns

    def test_probed_values_create_low_cardinality(self, kg):
        """Columns with <=10 distinct values (from probed_values) are flagged."""
        inv_node = kg.tables["c_invoice"]
        low_card = kg.get_low_cardinality_columns("c_invoice")
        low_card_names = [c.name for c in low_card]
        assert "issotrx" in low_card_names  # 2 values → low cardinality
        assert "docstatus" in low_card_names  # 2 values → low cardinality

    def test_no_hardcoded_erp_knowledge(self, kg):
        """The KG should not reference any hardcoded ERP patterns."""
        # If we build from a completely different entity_map (e.g., SAP-like),
        # the KG should still work
        sap_entity_map = {
            "entities": {
                "sales_docs": {
                    "table": "vbak",
                    "type": "TRANSACTIONAL",
                    "key_columns": {"pk": "vbeln", "amount": "netwr"},
                    "base_filter": "auart='ZOR'",
                    "probed_values": {"auart": {"ZOR": 5000, "ZRE": 200}},
                },
            },
            "relationships": [],
        }
        sap_kg = build_knowledge_graph(sap_entity_map)
        assert "vbak" in sap_kg.tables
        assert "auart" in sap_kg.tables["vbak"].filter_columns


# ═══════════════════════════════════════════════════════════════════════════
# TEST: JOIN PATH REASONING
# ═══════════════════════════════════════════════════════════════════════════

class TestJoinPathReasoning:

    def test_direct_join_invoice_to_customer(self, kg):
        path = kg.find_join_path("c_invoice", "c_bpartner")
        assert path is not None
        assert path.hop_count == 1

    def test_payment_schedule_to_customer_via_invoice(self, kg):
        """The EXACT bug that caused $13.5M hallucination: wrong JOIN path."""
        path = kg.find_join_path("fin_payment_schedule", "c_bpartner")
        assert path is not None
        assert path.hop_count == 2
        tables_in_path = path.tables
        assert "c_invoice" in tables_in_path

    def test_self_path(self, kg):
        path = kg.find_join_path("c_invoice", "c_invoice")
        assert path is not None
        assert path.hop_count == 0

    def test_no_path(self, kg):
        path = kg.find_join_path("c_invoice", "nonexistent_table")
        assert path is None


# ═══════════════════════════════════════════════════════════════════════════
# TEST: FILTER REASONING (data-driven)
# ═══════════════════════════════════════════════════════════════════════════

class TestFilterReasoning:

    def test_invoice_filters_from_base_filter(self, kg):
        """Filters come from entity_map.base_filter, not hardcoded."""
        filters = kg.get_required_filters("c_invoice")
        filter_text = " ".join(filters).lower()
        assert "issotrx" in filter_text
        assert "docstatus" in filter_text

    def test_payment_filters(self, kg):
        filters = kg.get_required_filters("fin_payment")
        filter_text = " ".join(filters).lower()
        assert "isreceipt" in filter_text

    def test_no_filters_for_unknown_table(self, kg):
        filters = kg.get_required_filters("nonexistent_table")
        assert filters == []


# ═══════════════════════════════════════════════════════════════════════════
# TEST: AMBIGUOUS COLUMNS
# ═══════════════════════════════════════════════════════════════════════════

class TestAmbiguousColumns:

    def test_isactive_is_ambiguous(self, kg):
        ambiguous = kg.get_ambiguous_columns(["c_invoice", "c_bpartner"])
        assert "isactive" in ambiguous
        assert len(ambiguous["isactive"]) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# TEST: QUERY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

class TestQueryValidation:

    def test_detects_missing_filter_column(self, kg):
        """A query on c_invoice without issotrx should be flagged
        because Cartographer put issotrx in base_filter."""
        bad_sql = "SELECT SUM(grandtotal) FROM c_invoice WHERE isactive = 'Y'"
        issues = kg.validate_query(bad_sql, ["c_invoice"])
        missing = [i for i in issues if i["type"] == "MISSING_FILTER_COLUMN"
                   and i["column"] == "issotrx"]
        assert len(missing) > 0

    def test_no_issue_when_filtered(self, kg):
        good_sql = """
            SELECT SUM(grandtotal) FROM c_invoice
            WHERE c_invoice.issotrx = 'Y'
            AND c_invoice.docstatus = 'CO'
            AND c_invoice.isactive = 'Y'
        """
        issues = kg.validate_query(good_sql, ["c_invoice"])
        missing_filter = [i for i in issues if i["type"] == "MISSING_FILTER_COLUMN"]
        assert len(missing_filter) == 0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: BUSINESS CONCEPTS
# ═══════════════════════════════════════════════════════════════════════════

class TestBusinessConcepts:

    def test_concepts_generated_from_entities(self, kg):
        """Concepts should be auto-generated from entity semantics."""
        assert len(kg.concepts) > 0

    def test_invoice_concept_has_filters(self, kg):
        """Invoice concepts should carry the Cartographer's filter."""
        inv_concepts = [c for c in kg.concepts.values() if "c_invoice" in c.primary_table]
        assert len(inv_concepts) > 0
        # At least one should have filter requirements
        has_filters = any(c.required_filters for c in inv_concepts)
        assert has_filters

    def test_prompt_context_generation(self, kg):
        ctx = kg.to_prompt_context()
        assert "SCHEMA KNOWLEDGE GRAPH" in ctx
        assert "c_invoice" in ctx


# ═══════════════════════════════════════════════════════════════════════════
# TEST: GLORIA BUG PREVENTION (without hardcoded knowledge)
# ═══════════════════════════════════════════════════════════════════════════

class TestGloriaBugPrevention:

    def test_ar_query_must_not_go_directly_to_bpartner(self, kg):
        """Bug F2: fin_payment_schedule → c_bpartner must go through c_invoice."""
        path = kg.find_join_path("fin_payment_schedule", "c_bpartner")
        assert path is not None
        assert "c_invoice" in path.tables

    def test_dormant_customer_query_needs_qualified_isactive(self, kg):
        """Bug F2: isactive is ambiguous in c_invoice + c_bpartner JOIN."""
        ambiguous = kg.get_ambiguous_columns(["c_invoice", "c_bpartner"])
        assert "isactive" in ambiguous

    def test_works_with_non_openbravo_schema(self):
        """The same graph logic works with a completely different schema."""
        odoo_map = {
            "entities": {
                "invoices": {
                    "table": "account_move",
                    "type": "TRANSACTIONAL",
                    "key_columns": {"pk": "id", "amount": "amount_total", "partner_fk": "partner_id"},
                    "base_filter": "move_type IN ('out_invoice','out_refund') AND state='posted'",
                    "probed_values": {
                        "move_type": {"out_invoice": 5000, "in_invoice": 2000, "out_refund": 300},
                        "state": {"posted": 6800, "draft": 500},
                    },
                },
                "partners": {
                    "table": "res_partner",
                    "type": "MASTER",
                    "key_columns": {"pk": "id", "name": "name"},
                    "base_filter": "active=true AND is_company=true",
                    "probed_values": {"active": {"True": 900, "False": 50}},
                },
            },
            "relationships": [
                {"from": "invoices", "to": "partners", "via": "partner_id", "cardinality": "N:1"},
            ],
        }
        kg = build_knowledge_graph(odoo_map)
        assert "account_move" in kg.tables
        assert "res_partner" in kg.tables
        # Filters come from entity_map, not hardcoded
        assert "move_type" in kg.tables["account_move"].filter_columns
        assert "state" in kg.tables["account_move"].filter_columns
        # JOIN path works
        path = kg.find_join_path("account_move", "res_partner")
        assert path is not None
        assert path.hop_count == 1
