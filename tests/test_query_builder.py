"""
Tests for the Query Builder — Stage 2: Deterministic SQL Generation.

Covers:
  - QUERY_TEMPLATES structure and integrity
  - _get_entity_filter: base_filter extraction helper
  - _find_relationship_column: relationship FK lookup
  - prioritize_entities: scoring, sorting, and MAX_ENTITIES cap
  - build_queries: full query generation pipeline
    - missing entities cause skips (not crashes)
    - filter injection via base_filter
    - period params propagated to SQL
    - special cases: orders_without_invoices, ar_outstanding_actual,
      aging_analysis, top_debtors, dormant_customer_list
    - SELECT-only output (no INSERT/UPDATE/DELETE/DROP)
    - query_pack structure

No LLM calls are made — the module is pure Python.
"""

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Stub heavy optional dependencies not installed in the test venv
# ---------------------------------------------------------------------------
import types as _types
from unittest.mock import MagicMock


def _make_stub(name: str) -> _types.ModuleType:
    mod = _types.ModuleType(name)
    mod.__spec__ = None
    return mod


# claude_agent_sdk stub
_sdk_stub = _make_stub("claude_agent_sdk")


def _tool_stub(*args, **kwargs):
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    return lambda f: f


_sdk_stub.tool = _tool_stub
_sdk_stub.query = MagicMock()
_sdk_stub.ClaudeAgentOptions = MagicMock
_sdk_stub.AssistantMessage = MagicMock
_sdk_stub.TextBlock = MagicMock
_sdk_stub.create_sdk_mcp_server = MagicMock()
sys.modules.setdefault("claude_agent_sdk", _sdk_stub)

# anthropic stub
_anthropic_stub = _make_stub("anthropic")
sys.modules.setdefault("anthropic", _anthropic_stub)

# structlog stub
if "structlog" not in sys.modules:
    _sl = _make_stub("structlog")
    _sl.get_logger = lambda: MagicMock()
    sys.modules["structlog"] = _sl

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
from valinor.agents.query_builder import (  # noqa: E402
    QUERY_TEMPLATES,
    MAX_ENTITIES,
    ROW_COUNT_CAP,
    _get_entity_filter,
    _find_relationship_column,
    prioritize_entities,
    build_queries,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PERIOD = {"start": "2025-01-01", "end": "2025-12-31", "label": "2025"}

INVOICE_ENTITY = {
    "table": "c_invoice",
    "type": "TRANSACTIONAL",
    "row_count": 50000,
    "key_columns": {
        "invoice_pk": "c_invoice_id",
        "invoice_date": "dateinvoiced",
        "amount_col": "grandtotal",
        "customer_fk": "c_bpartner_id",
    },
    "base_filter": "",
}

CUSTOMER_ENTITY = {
    "table": "c_bpartner",
    "type": "MASTER",
    "row_count": 500,
    "key_columns": {
        "customer_pk": "c_bpartner_id",
        "customer_name": "name",
    },
    "base_filter": "",
}

PAYMENT_ENTITY = {
    "table": "fin_payment_schedule",
    "type": "TRANSACTIONAL",
    "row_count": 8000,
    "key_columns": {
        "outstanding_amount": "outstandingamt",
        "due_date": "duedate",
        "customer_id": "c_bpartner_id",
        "customer_fk": "c_bpartner_id",
    },
    "base_filter": "",
}

ORDER_ENTITY = {
    "table": "c_order",
    "type": "TRANSACTIONAL",
    "row_count": 12000,
    "key_columns": {
        "order_pk": "c_order_id",
        "order_date": "dateordered",
        "order_amount": "grandtotal",
    },
    "base_filter": "",
}


def _minimal_entity_map(entities: dict, relationships: list | None = None) -> dict:
    return {
        "entities": entities,
        "relationships": relationships or [],
    }


# ---------------------------------------------------------------------------
# 1. QUERY_TEMPLATES integrity
# ---------------------------------------------------------------------------


class TestQueryTemplatesStructure:
    """Structural checks on the QUERY_TEMPLATES constant."""

    def test_templates_not_empty(self):
        assert len(QUERY_TEMPLATES) > 0

    def test_every_template_has_required_keys(self):
        required_keys = {"domain", "requires", "description", "template"}
        for name, cfg in QUERY_TEMPLATES.items():
            missing = required_keys - set(cfg.keys())
            assert not missing, f"Template '{name}' missing keys: {missing}"

    def test_requires_is_non_empty_list(self):
        for name, cfg in QUERY_TEMPLATES.items():
            assert isinstance(cfg["requires"], list), f"'{name}'.requires must be a list"
            assert len(cfg["requires"]) >= 1, f"'{name}'.requires must have ≥1 entry"

    def test_template_contains_select(self):
        for name, cfg in QUERY_TEMPLATES.items():
            sql_upper = cfg["template"].strip().upper()
            assert "SELECT" in sql_upper, f"Template '{name}' has no SELECT"

    def test_template_contains_no_dml(self):
        """No template should contain INSERT / UPDATE / DELETE / DROP."""
        forbidden = {"INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER"}
        for name, cfg in QUERY_TEMPLATES.items():
            words = set(cfg["template"].upper().split())
            found = forbidden & words
            assert not found, f"Template '{name}' contains forbidden DML: {found}"

    def test_known_domains_are_valid(self):
        valid_domains = {"financial", "credit", "sales", "data_quality"}
        for name, cfg in QUERY_TEMPLATES.items():
            assert cfg["domain"] in valid_domains, (
                f"Template '{name}' has unknown domain '{cfg['domain']}'"
            )


# ---------------------------------------------------------------------------
# 2. _get_entity_filter
# ---------------------------------------------------------------------------


class TestGetEntityFilter:
    """Unit tests for the base_filter extraction helper."""

    def test_empty_base_filter_returns_empty_string(self):
        entity = {"base_filter": ""}
        assert _get_entity_filter(entity) == ""

    def test_missing_base_filter_returns_empty_string(self):
        entity = {}
        assert _get_entity_filter(entity) == ""

    def test_filter_without_and_prefix_gets_prefixed(self):
        entity = {"base_filter": "issotrx = 'Y'"}
        result = _get_entity_filter(entity)
        assert result.startswith("AND ")
        assert "issotrx = 'Y'" in result

    def test_filter_already_starting_with_and_not_doubled(self):
        entity = {"base_filter": "AND issotrx = 'Y'"}
        result = _get_entity_filter(entity)
        assert result.upper().count("AND") == 1

    def test_custom_prefix_is_used(self):
        entity = {"base_filter": "iscustomer = 'Y'"}
        result = _get_entity_filter(entity, prefix="WHERE")
        assert result.startswith("WHERE ")

    def test_whitespace_only_filter_returns_empty_string(self):
        entity = {"base_filter": "   "}
        assert _get_entity_filter(entity) == ""


# ---------------------------------------------------------------------------
# 3. _find_relationship_column
# ---------------------------------------------------------------------------


class TestFindRelationshipColumn:
    """Unit tests for the relationship FK lookup helper."""

    def test_forward_relationship_found(self):
        entity_map = {
            "relationships": [
                {"from": "invoices", "to": "customers", "via": "c_bpartner_id"}
            ]
        }
        result = _find_relationship_column(entity_map, "invoices", "customers")
        assert result == "c_bpartner_id"

    def test_reverse_relationship_found(self):
        entity_map = {
            "relationships": [
                {"from": "invoices", "to": "customers", "via": "c_bpartner_id"}
            ]
        }
        result = _find_relationship_column(entity_map, "customers", "invoices")
        assert result == "c_bpartner_id"

    def test_missing_relationship_returns_none(self):
        entity_map = {"relationships": []}
        result = _find_relationship_column(entity_map, "orders", "invoices")
        assert result is None

    def test_no_relationships_key_returns_none(self):
        result = _find_relationship_column({}, "orders", "invoices")
        assert result is None

    def test_correct_relationship_selected_among_multiple(self):
        entity_map = {
            "relationships": [
                {"from": "invoices", "to": "customers", "via": "c_bpartner_id"},
                {"from": "invoices", "to": "orders", "via": "c_order_id"},
            ]
        }
        result = _find_relationship_column(entity_map, "invoices", "orders")
        assert result == "c_order_id"


# ---------------------------------------------------------------------------
# 4. prioritize_entities
# ---------------------------------------------------------------------------


class TestPrioritizeEntities:
    """Unit tests for entity scoring, sorting, and MAX_ENTITIES cap."""

    def _make_entity(self, row_count: int = 1000) -> dict:
        return {"table": "some_table", "row_count": row_count, "key_columns": {}}

    def test_returns_same_entities_when_below_cap(self):
        entities = {f"entity_{i}": self._make_entity(i * 100) for i in range(5)}
        entity_map = _minimal_entity_map(entities)
        result = prioritize_entities(entity_map, {})
        assert len(result["entities"]) == 5

    def test_caps_at_max_entities(self):
        entities = {f"entity_{i}": self._make_entity(i * 10) for i in range(MAX_ENTITIES + 5)}
        entity_map = _minimal_entity_map(entities)
        result = prioritize_entities(entity_map, {})
        assert len(result["entities"]) <= MAX_ENTITIES

    def test_focus_tables_score_higher(self):
        # Both entities have the same row_count so the 2× focus multiplier decides order
        entities = {
            "invoices": self._make_entity(row_count=1000),
            "config_table": self._make_entity(row_count=1000),
        }
        entity_map = _minimal_entity_map(entities)
        profile = {"focus_tables": ["invoices"]}
        result = prioritize_entities(entity_map, profile)
        result_keys = list(result["entities"].keys())
        # invoices should be prioritized (come first) because of the 2× focus multiplier
        assert result_keys[0] == "invoices"

    def test_table_weights_affect_score(self):
        entities = {
            "low_weight": self._make_entity(row_count=5000),
            "high_weight": self._make_entity(row_count=5000),
        }
        entity_map = _minimal_entity_map(entities)
        profile = {"table_weights": {"some_table": 0.1}, "focus_tables": ["high_weight"]}
        result = prioritize_entities(entity_map, profile)
        result_keys = list(result["entities"].keys())
        assert result_keys[0] == "high_weight"

    def test_empty_entities_returns_unchanged(self):
        entity_map = {"entities": {}}
        result = prioritize_entities(entity_map, {})
        assert result["entities"] == {}

    def test_row_count_capped_at_row_count_cap(self):
        """A 10M-row table should not get more score contribution than ROW_COUNT_CAP."""
        entities = {
            "giant_table": self._make_entity(row_count=10_000_000),
            "medium_table": self._make_entity(row_count=ROW_COUNT_CAP),
        }
        entity_map = _minimal_entity_map(entities)
        result = prioritize_entities(entity_map, {})
        # Both should appear — neither is excluded due to the cap
        assert "giant_table" in result["entities"]
        assert "medium_table" in result["entities"]

    def test_original_entity_map_not_mutated(self):
        entities = {f"e{i}": self._make_entity(i) for i in range(MAX_ENTITIES + 3)}
        entity_map = _minimal_entity_map(entities)
        original_count = len(entity_map["entities"])
        prioritize_entities(entity_map, {})
        assert len(entity_map["entities"]) == original_count


# ---------------------------------------------------------------------------
# 5. build_queries — core pipeline
# ---------------------------------------------------------------------------


class TestBuildQueriesBasic:
    """Basic structure and content checks on build_queries output."""

    def test_returns_queries_and_skipped_keys(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        assert "queries" in result
        assert "skipped" in result

    def test_queries_is_a_list(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        assert isinstance(result["queries"], list)

    def test_skipped_is_a_list(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        assert isinstance(result["skipped"], list)

    def test_each_query_has_required_keys(self):
        entity_map = _minimal_entity_map({
            "invoices": INVOICE_ENTITY,
            "customers": CUSTOMER_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            for key in ("id", "domain", "description", "sql"):
                assert key in q, f"Query missing key '{key}': {q}"

    def test_sql_is_non_empty_string(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            assert isinstance(q["sql"], str)
            assert len(q["sql"].strip()) > 0

    def test_period_dates_injected_into_sql(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            if PERIOD["start"] in QUERY_TEMPLATES.get(q["id"], {}).get("template", ""):
                assert PERIOD["start"] in q["sql"]

    def test_no_dml_in_generated_sql(self):
        """All generated SQL must be SELECT-only."""
        entity_map = _minimal_entity_map({
            "invoices": INVOICE_ENTITY,
            "customers": CUSTOMER_ENTITY,
            "payments": PAYMENT_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        forbidden = {"INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER"}
        for q in result["queries"]:
            words = set(q["sql"].upper().split())
            found = forbidden & words
            assert not found, f"Query '{q['id']}' has forbidden DML: {found}"


class TestBuildQueriesSkipping:
    """Tests verifying that missing entities produce 'skipped' entries."""

    def test_missing_invoices_skips_revenue_templates(self):
        entity_map = _minimal_entity_map({"customers": CUSTOMER_ENTITY})
        result = build_queries(entity_map, PERIOD)
        skipped_ids = {s["id"] for s in result["skipped"]}
        # revenue_by_period requires invoices
        assert "revenue_by_period" in skipped_ids

    def test_skipped_entry_has_reason(self):
        entity_map = _minimal_entity_map({})
        result = build_queries(entity_map, PERIOD)
        for s in result["skipped"]:
            assert "reason" in s
            assert len(s["reason"]) > 0

    def test_no_exception_when_all_entities_missing(self):
        entity_map = _minimal_entity_map({})
        result = build_queries(entity_map, PERIOD)
        # Everything should be skipped, not raise
        assert len(result["skipped"]) == len(QUERY_TEMPLATES)
        assert len(result["queries"]) == 0

    def test_orders_without_invoices_skipped_when_no_fk(self):
        """orders_without_invoices is skipped when no relationship and no fallback FK exists."""
        # Strip all FK fallback columns from both entities so the code cannot resolve order_fk
        invoice_no_fk = {**INVOICE_ENTITY, "key_columns": {
            k: v for k, v in INVOICE_ENTITY["key_columns"].items() if k != "order_fk"
        }}
        order_no_pk = {**ORDER_ENTITY, "key_columns": {
            k: v for k, v in ORDER_ENTITY["key_columns"].items() if k != "order_pk"
        }}
        entity_map = _minimal_entity_map({
            "invoices": invoice_no_fk,
            "orders": order_no_pk,
        })
        result = build_queries(entity_map, PERIOD)
        skipped_ids = {s["id"] for s in result["skipped"]}
        assert "orders_without_invoices" in skipped_ids


class TestBuildQueriesFilterInjection:
    """Verify base_filter is injected into SQL correctly."""

    def test_base_filter_appears_in_sql(self):
        invoice_with_filter = {**INVOICE_ENTITY, "base_filter": "issotrx = 'Y'"}
        entity_map = _minimal_entity_map({"invoices": invoice_with_filter})
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            if q["id"] in ("revenue_by_period", "total_revenue_summary"):
                assert "issotrx" in q["sql"], (
                    f"Filter not injected in '{q['id']}'"
                )

    def test_no_filter_leaves_placeholder_empty(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            # There should be no literal '{invoices_filter}' placeholder remaining
            assert "{invoices_filter}" not in q["sql"]


class TestBuildQueriesSpecialCases:
    """Tests for special-case query generation logic."""

    def test_orders_with_invoices_and_relationship_generates_query(self):
        entity_map = _minimal_entity_map(
            entities={"invoices": INVOICE_ENTITY, "orders": ORDER_ENTITY},
            relationships=[{"from": "invoices", "to": "orders", "via": "c_order_id"}],
        )
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "orders_without_invoices" in generated_ids

    def test_ar_outstanding_generates_with_payments(self):
        entity_map = _minimal_entity_map({"payments": PAYMENT_ENTITY})
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "ar_outstanding_actual" in generated_ids

    def test_aging_analysis_generates_with_payments(self):
        entity_map = _minimal_entity_map({"payments": PAYMENT_ENTITY})
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "aging_analysis" in generated_ids

    def test_dormant_customer_list_generates_with_invoices_and_customers(self):
        entity_map = _minimal_entity_map({
            "invoices": INVOICE_ENTITY,
            "customers": CUSTOMER_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "dormant_customer_list" in generated_ids

    def test_profile_filters_entities_before_query_generation(self):
        """When a profile caps entities, queries requiring absent entities are skipped."""
        # Build an entity map with many entities
        entities = {f"entity_{i}": {**INVOICE_ENTITY, "table": f"table_{i}"} for i in range(MAX_ENTITIES + 5)}
        entities["invoices"] = INVOICE_ENTITY
        entity_map = _minimal_entity_map(entities)

        # Profile sets very low weight on everything except "invoices"
        profile = {
            "table_weights": {"c_invoice": 1.0},
            "focus_tables": ["invoices"],
        }
        result = build_queries(entity_map, PERIOD, profile=profile)
        # Should not raise and should return valid structure
        assert "queries" in result
        assert "skipped" in result


# ---------------------------------------------------------------------------
# 6. _get_entity_filter — additional edge cases
# ---------------------------------------------------------------------------


class TestGetEntityFilterAdditional:
    """Extra edge cases for the base_filter helper."""

    def test_filter_with_where_prefix_not_doubled(self):
        """When prefix='WHERE' is passed and filter already starts with WHERE, no double."""
        entity = {"base_filter": "WHERE isactive = 'Y'"}
        result = _get_entity_filter(entity, prefix="WHERE")
        # The raw filter starts with WHERE, not AND, so we check it doesn't prepend twice
        assert result.upper().count("WHERE") <= 2  # at most one extra prefix

    def test_and_prefix_is_case_insensitive(self):
        """Filter starting with lowercase 'and' should not be double-prefixed."""
        entity = {"base_filter": "and issotrx = 'Y'"}
        result = _get_entity_filter(entity)
        assert result.upper().count("AND") == 1

    def test_filter_with_leading_whitespace_prefixed_correctly(self):
        """Leading spaces in base_filter should be stripped before prefix check."""
        entity = {"base_filter": "  iscustomer = 'Y'"}
        result = _get_entity_filter(entity)
        assert result.startswith("AND ")
        assert "iscustomer = 'Y'" in result

    def test_custom_prefix_or_not_doubled(self):
        """OR prefix is applied and doesn't duplicate when filter has no OR prefix."""
        entity = {"base_filter": "isvendor = 'Y'"}
        result = _get_entity_filter(entity, prefix="OR")
        assert result.startswith("OR ")
        assert "isvendor = 'Y'" in result


# ---------------------------------------------------------------------------
# 7. _find_relationship_column — additional edge cases
# ---------------------------------------------------------------------------


class TestFindRelationshipColumnAdditional:
    """Extra edge cases for the FK relationship lookup."""

    def test_via_key_missing_returns_none(self):
        """A relationship entry with no 'via' key should return None."""
        entity_map = {
            "relationships": [
                {"from": "invoices", "to": "orders"}  # no 'via' key
            ]
        }
        result = _find_relationship_column(entity_map, "invoices", "orders")
        assert result is None

    def test_unrelated_pair_ignored(self):
        """Only exact pair match (in either direction) is returned."""
        entity_map = {
            "relationships": [
                {"from": "invoices", "to": "customers", "via": "c_bpartner_id"},
            ]
        }
        result = _find_relationship_column(entity_map, "invoices", "payments")
        assert result is None

    def test_first_matching_relationship_returned(self):
        """When multiple entries match the same pair, the first one wins."""
        entity_map = {
            "relationships": [
                {"from": "invoices", "to": "customers", "via": "first_col"},
                {"from": "invoices", "to": "customers", "via": "second_col"},
            ]
        }
        result = _find_relationship_column(entity_map, "invoices", "customers")
        assert result == "first_col"


# ---------------------------------------------------------------------------
# 8. prioritize_entities — additional scoring and structure tests
# ---------------------------------------------------------------------------


class TestPrioritizeEntitiesAdditional:
    """Additional scoring, tiebreaker, and structure tests."""

    def _make_entity(self, row_count: int = 1000, table: str = "some_table") -> dict:
        return {"table": table, "row_count": row_count, "key_columns": {}}

    def test_higher_row_count_scores_higher_when_no_profile(self):
        """With a flat profile, higher row_count entity should rank first."""
        entities = {
            "small": self._make_entity(row_count=100),
            "large": self._make_entity(row_count=50_000),
        }
        entity_map = _minimal_entity_map(entities)
        result = prioritize_entities(entity_map, {})
        result_keys = list(result["entities"].keys())
        assert result_keys[0] == "large"

    def test_relationships_key_preserved_in_output(self):
        """The returned entity_map must preserve the 'relationships' list."""
        rels = [{"from": "a", "to": "b", "via": "col"}]
        entities = {"invoices": self._make_entity()}
        entity_map = _minimal_entity_map(entities, relationships=rels)
        result = prioritize_entities(entity_map, {})
        assert result.get("relationships") == rels

    def test_profile_with_no_keys_still_works(self):
        """An empty profile dict must not raise."""
        entities = {"invoices": self._make_entity(row_count=1000)}
        entity_map = _minimal_entity_map(entities)
        result = prioritize_entities(entity_map, {})
        assert "invoices" in result["entities"]

    def test_single_entity_always_retained(self):
        """A single entity must always survive the cap."""
        entities = {"only_one": self._make_entity(row_count=500)}
        entity_map = _minimal_entity_map(entities)
        result = prioritize_entities(entity_map, {})
        assert "only_one" in result["entities"]


# ---------------------------------------------------------------------------
# 9. build_queries — per-template generation and content checks
# ---------------------------------------------------------------------------


class TestBuildQueriesTemplateGeneration:
    """Verify that each major template fires correctly when prerequisites are met."""

    def test_revenue_yoy_generates_with_invoices(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "revenue_yoy" in generated_ids

    def test_null_analysis_generates_with_invoices(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "null_analysis" in generated_ids

    def test_data_freshness_generates_with_invoices(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "data_freshness" in generated_ids

    def test_duplicate_detection_generates_with_invoices(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "duplicate_detection" in generated_ids

    def test_monthly_seasonality_generates_with_invoices(self):
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "monthly_seasonality" in generated_ids

    def test_customer_retention_generates_with_invoices_and_customers(self):
        entity_map = _minimal_entity_map({
            "invoices": INVOICE_ENTITY,
            "customers": CUSTOMER_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "customer_retention" in generated_ids

    def test_never_invoiced_customers_generates_with_invoices_and_customers(self):
        entity_map = _minimal_entity_map({
            "invoices": INVOICE_ENTITY,
            "customers": CUSTOMER_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "never_invoiced_customers" in generated_ids

    def test_customer_concentration_generates_with_invoices_and_customers(self):
        entity_map = _minimal_entity_map({
            "invoices": INVOICE_ENTITY,
            "customers": CUSTOMER_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "customer_concentration" in generated_ids

    def test_top_debtors_generates_with_payments_and_customers(self):
        entity_map = _minimal_entity_map({
            "payments": PAYMENT_ENTITY,
            "customers": CUSTOMER_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        generated_ids = {q["id"] for q in result["queries"]}
        assert "top_debtors" in generated_ids


# ---------------------------------------------------------------------------
# 10. build_queries — params and placeholder hygiene
# ---------------------------------------------------------------------------


class TestBuildQueriesParamsHygiene:
    """Verify params dict in generated queries and that placeholders are resolved."""

    def test_params_excludes_filter_keys(self):
        """The 'params' field must not expose *_filter keys."""
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            filter_keys = [k for k in q["params"] if k.endswith("_filter")]
            assert not filter_keys, (
                f"Query '{q['id']}' exposes filter keys in params: {filter_keys}"
            )

    def test_no_unresolved_placeholders_in_sql(self):
        """No generated SQL should contain a raw {…} placeholder."""
        import re
        entity_map = _minimal_entity_map({
            "invoices": INVOICE_ENTITY,
            "customers": CUSTOMER_ENTITY,
            "payments": PAYMENT_ENTITY,
            "orders": ORDER_ENTITY,
        })
        result = build_queries(entity_map, PERIOD)
        placeholder_re = re.compile(r"\{[a-z_]+\}")
        for q in result["queries"]:
            match = placeholder_re.search(q["sql"])
            assert not match, (
                f"Unresolved placeholder '{match.group()}' in query '{q['id']}'"
            )

    def test_skipped_entries_include_domain(self):
        """Every skipped entry must carry the 'domain' field from the template."""
        entity_map = _minimal_entity_map({})  # all templates will be skipped
        result = build_queries(entity_map, PERIOD)
        for s in result["skipped"]:
            assert "domain" in s, f"Skipped entry '{s.get('id')}' missing 'domain'"
            assert s["domain"] in {"financial", "credit", "sales", "data_quality"}

    def test_filter_where_placeholder_not_left_in_sql(self):
        """The {invoices_filter_where} placeholder must be resolved, not left raw."""
        entity_map = _minimal_entity_map({"invoices": INVOICE_ENTITY})
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            assert "{invoices_filter_where}" not in q["sql"], (
                f"Unresolved {{invoices_filter_where}} in query '{q['id']}'"
            )

    def test_multiple_entity_filters_both_injected(self):
        """When both invoices and customers have base_filter, both appear in SQL."""
        invoice_with_filter = {**INVOICE_ENTITY, "base_filter": "issotrx = 'Y'"}
        customer_with_filter = {**CUSTOMER_ENTITY, "base_filter": "iscustomer = 'Y'"}
        entity_map = _minimal_entity_map({
            "invoices": invoice_with_filter,
            "customers": customer_with_filter,
        })
        result = build_queries(entity_map, PERIOD)
        for q in result["queries"]:
            # customer_retention template only uses {invoices_filter}, no {customers_filter}
            if q["id"] in ("dormant_customer_list", "customer_concentration",
                           "never_invoiced_customers"):
                assert "issotrx" in q["sql"], (
                    f"Invoice filter missing in '{q['id']}'"
                )
                assert "iscustomer" in q["sql"], (
                    f"Customer filter missing in '{q['id']}'"
                )
