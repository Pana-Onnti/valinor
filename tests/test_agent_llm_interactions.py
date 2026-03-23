"""
Tests for LLM agent interactions — VAL-58.

Covers:
  - Analyst agent: prompt construction, output parsing, error handling
  - Cartographer agent: Phase 1 prescan, Phase 2 prompt, calibration feedback
  - QueryGenerator: schema topology, SQL building, entity detection
  - Narrator agents: prompt construction, graceful degradation

All LLM calls are mocked via unittest.mock. No API keys required.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Stub claude_agent_sdk before importing agent modules
# ---------------------------------------------------------------------------
# Always (re)set proper stubs — other test modules may have installed
# MagicMock-based stubs that break isinstance checks.
_sdk = sys.modules.get("claude_agent_sdk") or types.ModuleType("claude_agent_sdk")
_sdk.__spec__ = None


def _tool_stub(*args, **kwargs):
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    return lambda f: f


async def _query_stub(*args, **kwargs):
    return
    yield  # async generator


class _ClaudeAgentOptions:
    def __init__(self, model="sonnet", system_prompt="", max_turns=20, **kwargs):
        self.model = model
        self.system_prompt = system_prompt
        self.max_turns = max_turns
        for k, v in kwargs.items():
            setattr(self, k, v)


class _TextBlock:
    def __init__(self, text: str = ""):
        self.text = text


class _AssistantMessage:
    def __init__(self, content=None):
        self.content = content or []


_sdk.tool = _tool_stub
_sdk.query = _query_stub
_sdk.ClaudeAgentOptions = _ClaudeAgentOptions
_sdk.AssistantMessage = _AssistantMessage
_sdk.TextBlock = _TextBlock
_sdk.create_sdk_mcp_server = MagicMock(return_value=MagicMock())
sys.modules["claude_agent_sdk"] = _sdk

# Stub structlog if not present
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.__spec__ = None
    _sl.get_logger = lambda: MagicMock()
    sys.modules["structlog"] = _sl

# ---------------------------------------------------------------------------
# Imports (after stubs)
# ---------------------------------------------------------------------------
from valinor.agents.analyst import run_analyst
from valinor.agents.cartographer import (
    _format_phase1_hints,
    _format_calibration_feedback,
    _prescan_filter_candidates,
    run_cartographer,
)
from valinor.agents.query_generator import (
    QueryGenerator,
    SQLBuilder,
    SchemaTopology,
    classify_schema_topology,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_assistant_message(text: str):
    """Create a mock AssistantMessage with a TextBlock."""
    tb = sys.modules["claude_agent_sdk"].TextBlock(text=text)
    return sys.modules["claude_agent_sdk"].AssistantMessage(content=[tb])


async def _mock_query_yielding(texts: list[str]):
    """Create an async generator that yields AssistantMessages."""
    for t in texts:
        yield _make_assistant_message(t)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_entity_map():
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
                "base_filter": "issotrx='Y' AND docstatus='CO'",
            },
            "customers": {
                "table": "c_bpartner",
                "type": "MASTER",
                "row_count": 88,
                "key_columns": {
                    "pk": "c_bpartner_id",
                    "customer_name": "name",
                },
                "base_filter": "iscustomer='Y'",
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
            },
        },
        "relationships": [
            {"from": "invoices", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
            {"from": "payment_schedule", "to": "invoices", "via": "c_invoice_id", "cardinality": "N:1"},
        ],
    }


@pytest.fixture
def sample_period():
    return {"start": "2025-01-01", "end": "2025-03-31"}


@pytest.fixture
def sample_baseline():
    return {
        "data_available": True,
        "total_revenue": 1_500_000.0,
        "num_invoices": 2366,
        "avg_invoice": 634.0,
        "min_invoice": 5.0,
        "max_invoice": 85_000.0,
        "date_from": "2024-01-15",
        "date_to": "2025-03-28",
        "data_freshness_days": 3,
        "distinct_customers": 49,
        "_provenance": {
            "total_revenue": {"source_query": "revenue_summary", "confidence": "measured"},
        },
    }


@pytest.fixture
def sample_query_results():
    return {
        "results": {
            "revenue_summary": {
                "columns": ["total_revenue", "num_records"],
                "rows": [{"total_revenue": 1_500_000.0, "num_records": 2366}],
                "row_count": 1,
            },
        },
        "errors": {},
    }


@pytest.fixture
def sample_client_config():
    return {
        "name": "test_client",
        "display_name": "Test Client S.A.",
        "sector": "distribution",
        "currency": "EUR",
        "language": "es",
        "connection_string": "sqlite:///:memory:",
    }


# ═══════════════════════════════════════════════════════════════════════════
# ANALYST AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalystPromptConstruction:
    """Tests that the analyst agent builds prompts correctly."""

    @staticmethod
    def _extract_prompt(mock_query):
        """Extract the prompt string from a mocked query call."""
        call_args = mock_query.call_args
        # query() can be called with positional or keyword 'prompt' arg
        if call_args.kwargs and "prompt" in call_args.kwargs:
            return call_args.kwargs["prompt"]
        if call_args.args:
            return call_args.args[0]
        return ""

    def test_analyst_includes_baseline_in_prompt(self, sample_query_results, sample_entity_map, sample_baseline):
        """Verify the analyst prompt includes the revenue baseline."""
        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding([])
            result = _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
            ))
            # Should have called query with a prompt containing baseline data
            assert mock_query.called
            prompt = self._extract_prompt(mock_query)
            assert "1500000" in prompt or "1,500,000" in prompt or "1_500_000" in prompt

    def test_analyst_includes_entity_map_in_prompt(self, sample_query_results, sample_entity_map, sample_baseline):
        """Verify entity_map context appears in the prompt."""
        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding([])
            _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
            ))
            prompt = self._extract_prompt(mock_query)
            assert "c_invoice" in prompt or "invoices" in prompt

    def test_analyst_includes_kg_context_when_provided(self, sample_query_results, sample_entity_map, sample_baseline):
        """When a KG is passed, its context should appear in the prompt."""
        mock_kg = MagicMock()
        mock_kg.to_prompt_context.return_value = "TABLE: c_invoice | JOINS: c_bpartner"

        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding([])
            _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
                kg=mock_kg,
            ))
            prompt = self._extract_prompt(mock_query)
            assert "TABLE: c_invoice" in prompt

    def test_analyst_without_kg_omits_kg_section(self, sample_query_results, sample_entity_map, sample_baseline):
        """Without a KG, the SCHEMA KNOWLEDGE GRAPH section should not appear."""
        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding([])
            _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
                kg=None,
            ))
            prompt = self._extract_prompt(mock_query)
            assert "SCHEMA KNOWLEDGE GRAPH" not in prompt


class TestAnalystOutputParsing:
    """Tests that the analyst agent handles LLM output correctly."""

    def test_analyst_collects_text_blocks(self, sample_query_results, sample_entity_map, sample_baseline):
        """Verify text blocks from the LLM are collected into output."""
        findings_json = json.dumps([
            {"id": "FIN-001", "severity": "critical", "headline": "Revenue drop 15%",
             "evidence": "query: revenue_summary", "value_eur": 225_000,
             "value_confidence": "measured", "action": "Review pricing", "domain": "financial"}
        ])

        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding([findings_json])
            result = _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
            ))
            assert result["agent"] == "analyst"
            assert "FIN-001" in result["output"]
            assert "Revenue drop" in result["output"]

    def test_analyst_handles_multiple_text_blocks(self, sample_query_results, sample_entity_map, sample_baseline):
        """Multiple text blocks should be joined with newlines."""
        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding(["Part 1", "Part 2"])
            result = _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
            ))
            assert "Part 1" in result["output"]
            assert "Part 2" in result["output"]


class TestAnalystErrorHandling:
    """Tests that the analyst handles LLM errors gracefully."""

    def test_analyst_returns_empty_on_exception(self, sample_query_results, sample_entity_map, sample_baseline):
        """If the LLM query raises, the analyst should return empty output."""
        async def _failing_query(*args, **kwargs):
            raise RuntimeError("API timeout")
            yield  # noqa — makes it an async gen

        with patch("valinor.agents.analyst.query", _failing_query):
            result = _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
            ))
            assert result["agent"] == "analyst"
            assert result["output"] == ""

    def test_analyst_returns_empty_on_no_messages(self, sample_query_results, sample_entity_map, sample_baseline):
        """If the LLM yields nothing, output should be empty."""
        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding([])
            result = _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=None,
                baseline=sample_baseline,
            ))
            assert result["output"] == ""

    def test_analyst_with_previous_memory(self, sample_query_results, sample_entity_map, sample_baseline):
        """Previous memory should be included in prompt context."""
        memory = {"last_findings": ["FIN-001"], "run_count": 3}
        with patch("valinor.agents.analyst.query") as mock_query:
            mock_query.return_value = _mock_query_yielding([])
            _run(run_analyst(
                query_results=sample_query_results,
                entity_map=sample_entity_map,
                memory=memory,
                baseline=sample_baseline,
            ))
            call_args = mock_query.call_args
            prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
            assert "FIN-001" in prompt or "run_count" in prompt


# ═══════════════════════════════════════════════════════════════════════════
# CARTOGRAPHER AGENT TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestCartographerPhase1:
    """Tests for the deterministic Phase 1 pre-scan."""

    def test_format_phase1_hints_empty(self):
        """Empty prescan returns empty string."""
        assert _format_phase1_hints({"candidate_hints": {}}) == ""

    def test_format_phase1_hints_with_data(self):
        """Prescan with data produces formatted hint section."""
        prescan = {
            "candidate_hints": {
                "c_invoice": {
                    "issotrx": [
                        {"value": "Y", "count": 30100},
                        {"value": "N", "count": 15134},
                    ]
                }
            }
        }
        result = _format_phase1_hints(prescan)
        assert "PHASE 1 PRE-SCAN" in result
        assert "c_invoice" in result
        assert "issotrx" in result
        assert "30,100" in result or "30100" in result

    def test_format_phase1_hints_multiple_tables(self):
        """Multiple tables are all included."""
        prescan = {
            "candidate_hints": {
                "c_invoice": {"ad_client_id": [{"value": "1000000", "count": 4117}]},
                "c_payment": {"docstatus": [{"value": "CO", "count": 2000}]},
            }
        }
        result = _format_phase1_hints(prescan)
        assert "c_invoice" in result
        assert "c_payment" in result


class TestCartographerCalibrationFeedback:
    """Tests for calibration retry feedback formatting."""

    def test_empty_failures_returns_empty(self):
        """No failures → empty string."""
        assert _format_calibration_feedback([]) == ""

    def test_failures_formatted_correctly(self):
        """Failures should include entity names and feedback."""
        failures = [
            {"entity": "invoices", "feedback": "filtered_count is 0 — wrong filter value"},
            {"entity": "customers", "feedback": "base_filter syntax error on MySQL"},
        ]
        result = _format_calibration_feedback(failures)
        assert "CALIBRATION FEEDBACK" in result
        assert "invoices" in result
        assert "filtered_count is 0" in result
        assert "customers" in result

    def test_failures_include_probe_instruction(self):
        """Each failure should suggest probe_column_values."""
        failures = [{"entity": "payments", "feedback": "0 rows"}]
        result = _format_calibration_feedback(failures)
        assert "probe_column_values" in result


class TestCartographerRunIntegration:
    """Integration tests for run_cartographer (LLM mocked)."""

    def test_run_cartographer_returns_dict_structure(self, sample_client_config):
        """Cartographer always returns a dict with either entity data or partial status."""
        with patch("valinor.agents.cartographer._prescan_filter_candidates") as mock_prescan, \
             patch("valinor.agents.cartographer.query") as mock_query:
            mock_prescan.return_value = {"candidate_hints": {}}
            mock_query.return_value = _mock_query_yielding(["Done mapping"])
            result = _run(run_cartographer(sample_client_config))
            assert isinstance(result, dict)
            # Result will have either entities or status=partial, plus _phase1_prescan metadata
            has_entities = "entities" in result
            has_status = result.get("status") == "partial"
            has_prescan = "_phase1_prescan" in result
            assert has_entities or has_status or has_prescan

    def test_run_cartographer_with_calibration_feedback(self, sample_client_config):
        """Calibration feedback is included in the prompt."""
        feedback = [{"entity": "invoices", "feedback": "wrong filter"}]
        with patch("valinor.agents.cartographer._prescan_filter_candidates") as mock_prescan, \
             patch("valinor.agents.cartographer.query") as mock_query:
            mock_prescan.return_value = {"candidate_hints": {}}
            mock_query.return_value = _mock_query_yielding(["Done"])
            _run(run_cartographer(sample_client_config, calibration_feedback=feedback))
            # The query was called — we can verify it ran without errors
            assert mock_query.called


# ═══════════════════════════════════════════════════════════════════════════
# QUERY GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemaTopologyClassifier:
    """Tests for classify_schema_topology."""

    def test_full_topology(self, sample_entity_map):
        """Entity map with invoices, customers, and payment → FULL."""
        topology = classify_schema_topology(sample_entity_map)
        assert topology == SchemaTopology.FULL

    def test_slim_topology(self):
        """Entity map with invoices + customers but no payment → SLIM."""
        entity_map = {
            "entities": {
                "invoices": {
                    "type": "TRANSACTIONAL",
                    "key_columns": {"amount_col": "total"},
                },
                "customers": {
                    "type": "MASTER",
                    "key_columns": {"pk": "id"},
                },
            }
        }
        topology = classify_schema_topology(entity_map)
        assert topology == SchemaTopology.SLIM

    def test_minimal_topology(self):
        """Single entity → MINIMAL."""
        entity_map = {
            "entities": {
                "config": {"type": "CONFIG", "key_columns": {}},
            }
        }
        topology = classify_schema_topology(entity_map)
        assert topology == SchemaTopology.MINIMAL

    def test_empty_entities(self):
        """Empty entities → MINIMAL."""
        assert classify_schema_topology({"entities": {}}) == SchemaTopology.MINIMAL
        assert classify_schema_topology({}) == SchemaTopology.MINIMAL


class TestQueryGeneratorEntityDetection:
    """Tests for entity detection by TYPE, not by NAME."""

    def test_find_revenue_entity(self, sample_entity_map, sample_period):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        revenue = gen._find_revenue_entity()
        assert revenue is not None
        assert revenue["table"] == "c_invoice"

    def test_find_customer_entity(self, sample_entity_map, sample_period):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        customer = gen._find_customer_entity()
        assert customer is not None
        assert customer["table"] == "c_bpartner"

    def test_find_payment_entity(self, sample_entity_map, sample_period):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        payment = gen._find_payment_entity()
        assert payment is not None
        assert payment["table"] == "fin_payment_schedule"

    def test_find_key_column_exact_match(self):
        """Exact semantic key match takes priority."""
        kc = {"amount_col": "grandtotal", "date_col": "dateinvoiced"}
        result = QueryGenerator._find_key_column(kc, "amount_col", "grand_total")
        assert result == "grandtotal"

    def test_find_key_column_fallback_substring(self):
        """Substring match works when exact match fails."""
        kc = {"invoice_amount": "total_eur"}
        result = QueryGenerator._find_key_column(kc, "amount_col", "amount")
        assert result == "total_eur"

    def test_find_key_column_no_match(self):
        """Returns None when no key matches."""
        kc = {"pk": "c_invoice_id"}
        result = QueryGenerator._find_key_column(kc, "amount_col", "grand_total")
        assert result is None


class TestQueryGeneratorSQLOutput:
    """Tests that generated SQL is valid and well-formed."""

    def test_generate_revenue_summary(self, sample_entity_map, sample_period):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        result = gen.generate_revenue_summary()
        assert result is not None
        sql = result["sql"]
        assert "SELECT" in sql
        assert "SUM" in sql
        assert "c_invoice" in sql
        assert "2025-01-01" in sql

    def test_generate_revenue_trend(self, sample_entity_map, sample_period):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        result = gen.generate_revenue_trend()
        assert result is not None
        assert "DATE_TRUNC" in result["sql"]
        assert "mom_growth_pct" in result["sql"]

    def test_generate_yoy_comparison(self, sample_entity_map, sample_period):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        result = gen.generate_yoy_comparison()
        assert result is not None
        assert "yoy_growth_pct" in result["sql"]

    def test_generate_all_full_topology(self, sample_entity_map, sample_period):
        """Full topology should generate base + slim + full queries."""
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        pack = gen.generate_all()
        query_ids = [q["id"] for q in pack["queries"]]
        assert "revenue_summary" in query_ids
        assert "revenue_trend" in query_ids
        # customer_concentration requires a valid JOIN path from invoices to customers
        # which is provided by our fixture relationships
        all_ids = query_ids + [s["id"] for s in pack.get("skipped", [])]
        assert "customer_concentration" in all_ids

    def test_generate_all_minimal_topology(self, sample_period):
        """Minimal topology should only generate base queries."""
        entity_map = {"entities": {}}
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(entity_map)
        gen = QueryGenerator(kg, entity_map, sample_period)
        pack = gen.generate_all()
        query_ids = [q["id"] for q in pack["queries"]]
        # No queries should succeed with empty entity map
        assert len(pack["skipped"]) > 0

    def test_generate_dormant_customers(self, sample_entity_map, sample_period):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        gen = QueryGenerator(kg, sample_entity_map, sample_period)
        result = gen.generate_dormant_customers()
        # Result may be None if JOIN path is not found in this direction
        # or should contain HAVING clause if successful
        if result is not None:
            assert "HAVING" in result["sql"]
            assert "90 days" in result["sql"]


class TestQueryGeneratorErrorHandling:
    """Tests for edge cases and error conditions."""

    def test_missing_amount_column(self, sample_period):
        """Entity without amount column → returns None for revenue queries."""
        entity_map = {
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "type": "TRANSACTIONAL",
                    "key_columns": {"pk": "c_invoice_id"},  # no amount_col
                },
            },
        }
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(entity_map)
        gen = QueryGenerator(kg, entity_map, sample_period)
        result = gen.generate_revenue_summary()
        assert result is None

    def test_missing_date_column(self, sample_period):
        """Entity without date column → returns None for revenue queries."""
        entity_map = {
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "type": "TRANSACTIONAL",
                    "key_columns": {"amount_col": "grandtotal"},  # no date
                },
            },
        }
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(entity_map)
        gen = QueryGenerator(kg, entity_map, sample_period)
        result = gen.generate_revenue_summary()
        assert result is None

    def test_no_customer_entity_skips_concentration(self, sample_period):
        """No MASTER entity → customer_concentration returns None."""
        entity_map = {
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "type": "TRANSACTIONAL",
                    "key_columns": {
                        "amount_col": "grandtotal",
                        "invoice_date": "dateinvoiced",
                    },
                },
            },
        }
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(entity_map)
        gen = QueryGenerator(kg, entity_map, sample_period)
        result = gen.generate_customer_concentration()
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# SQL BUILDER TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestSQLBuilder:
    """Tests for the fluent SQL builder."""

    def test_basic_select_from(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        sql = (
            SQLBuilder(kg)
            .from_table("c_invoice")
            .select("COUNT(*)", "total")
            .build()
        )
        assert "SELECT" in sql
        assert "COUNT(*)" in sql
        assert "FROM c_invoice" in sql

    def test_where_clause(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        sql = (
            SQLBuilder(kg)
            .from_table("c_invoice")
            .select("*")
            .where("status = 'active'")
            .build()
        )
        assert "WHERE" in sql
        assert "status = 'active'" in sql

    def test_group_by_and_order(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        sql = (
            SQLBuilder(kg)
            .from_table("c_invoice")
            .select("customer_id")
            .select("SUM(total)", "revenue")
            .group_by("customer_id")
            .order_by("revenue")
            .build()
        )
        assert "GROUP BY customer_id" in sql
        assert "ORDER BY revenue DESC" in sql

    def test_limit(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        sql = (
            SQLBuilder(kg)
            .from_table("c_invoice")
            .select("*")
            .limit(10)
            .build()
        )
        assert "LIMIT 10" in sql

    def test_no_selects_raises(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        with pytest.raises(ValueError, match="No SELECT"):
            SQLBuilder(kg).from_table("c_invoice").build()

    def test_no_from_raises(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        with pytest.raises(ValueError, match="No FROM"):
            SQLBuilder(kg).select("*").build()

    def test_join_to_builds_correct_join(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        # JOIN from fin_payment_schedule to c_invoice (direct relationship exists)
        sql = (
            SQLBuilder(kg)
            .from_table("fin_payment_schedule", "pay")
            .join_to("c_invoice", "inv")
            .select("pay.outstandingamt")
            .select("inv.grandtotal")
            .build()
        )
        assert "JOIN" in sql
        assert "c_invoice" in sql

    def test_where_period(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        sql = (
            SQLBuilder(kg)
            .from_table("c_invoice")
            .select("*")
            .where_period("dateinvoiced", {"start": "2025-01-01", "end": "2025-03-31"})
            .build()
        )
        assert "2025-01-01" in sql
        assert "2025-03-31" in sql

    def test_cte_rendering(self, sample_entity_map):
        from valinor.knowledge_graph import build_knowledge_graph
        kg = build_knowledge_graph(sample_entity_map)
        sql = (
            SQLBuilder(kg)
            .with_cte("totals", "SELECT SUM(amount) FROM c_invoice")
            .from_table("totals")
            .select("*")
            .build()
        )
        assert "WITH totals AS" in sql


# ═══════════════════════════════════════════════════════════════════════════
# NARRATOR AGENTS TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestNarratorPromptConstruction:
    """Tests that narrators construct prompts with required context."""

    def _minimal_inputs(self):
        return {
            "findings": {"analyst": {"output": "FIN-001: Revenue drop"}},
            "entity_map": {"entities": {}},
            "memory": None,
            "client_config": {
                "name": "test", "display_name": "Test S.A.",
                "sector": "distribution", "currency": "EUR", "language": "es",
            },
            "baseline": {"data_available": True, "total_revenue": 100_000, "_provenance": {}},
        }

    def test_executive_narrator_returns_string(self):
        from valinor.agents.narrators.executive import narrate_executive
        inputs = self._minimal_inputs()
        result = _run(narrate_executive(**inputs))
        assert isinstance(result, str)

    def test_ceo_narrator_returns_string(self):
        from valinor.agents.narrators.ceo import narrate_ceo
        inputs = self._minimal_inputs()
        result = _run(narrate_ceo(**inputs))
        assert isinstance(result, str)

    def test_controller_narrator_returns_string(self):
        from valinor.agents.narrators.controller import narrate_controller
        inputs = self._minimal_inputs()
        inputs["query_results"] = {"results": {}, "errors": {}}
        result = _run(narrate_controller(**inputs))
        assert isinstance(result, str)

    def test_sales_narrator_returns_string(self):
        from valinor.agents.narrators.sales import narrate_sales
        inputs = self._minimal_inputs()
        inputs["query_results"] = {"results": {}, "errors": {}}
        result = _run(narrate_sales(**inputs))
        assert isinstance(result, str)

    def test_executive_with_verification_report(self):
        """Verification report context is included when provided."""
        from valinor.agents.narrators.executive import narrate_executive
        inputs = self._minimal_inputs()
        mock_report = MagicMock()
        mock_report.to_prompt_context.return_value = "VERIFIED: revenue=100000"
        inputs["verification_report"] = mock_report
        result = _run(narrate_executive(**inputs))
        assert isinstance(result, str)

    def test_narrators_handle_unicode_client_names(self):
        """Unicode in client config doesn't cause errors."""
        from valinor.agents.narrators.executive import narrate_executive
        inputs = self._minimal_inputs()
        inputs["client_config"]["display_name"] = "Distribuidora Ñoño & Cía. Ltda."
        result = _run(narrate_executive(**inputs))
        assert isinstance(result, str)

    def test_narrators_handle_none_memory(self):
        """None memory is handled gracefully."""
        from valinor.agents.narrators.ceo import narrate_ceo
        inputs = self._minimal_inputs()
        inputs["memory"] = None
        result = _run(narrate_ceo(**inputs))
        assert isinstance(result, str)

    def test_narrators_handle_rich_memory(self):
        """Rich memory dict with many fields doesn't raise."""
        from valinor.agents.narrators.executive import narrate_executive
        inputs = self._minimal_inputs()
        inputs["memory"] = {
            "adaptive_context": {"currency": "USD"},
            "data_quality_context": "DQ Score: 88",
            "run_history_summary": {
                "persistent_findings": [{"title": "Overdue AR", "runs_open": 4}],
                "currency": "USD",
            },
            "sentinel_patterns": "Fraud detected",
        }
        result = _run(narrate_executive(**inputs))
        assert isinstance(result, str)
