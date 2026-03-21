"""
Comprehensive tests for the API refinement layer:
  - api/refinement/prompt_tuner.py    (PromptTuner)
  - api/refinement/focus_ranker.py    (FocusRanker)
  - api/refinement/query_evolver.py   (QueryEvolver)
  - api/refinement/refinement_agent.py (RefinementAgent._heuristic_analyze, analyze_run fallback)

All tests are pure-logic — no database, LLM, or filesystem calls required.
LLM-dependent code paths (RefinementAgent._llm_analyze) are tested only via the
heuristic fallback, triggered by stubbing the LLM to raise.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub claude_agent_sdk before any project imports
# ---------------------------------------------------------------------------
if "claude_agent_sdk" not in sys.modules:
    _sdk = types.ModuleType("claude_agent_sdk")
    _sdk.__spec__ = None

    def _tool_stub(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f

    _sdk.tool = _tool_stub
    _sdk.query = AsyncMock()
    _sdk.ClaudeAgentOptions = MagicMock
    _sdk.AssistantMessage = MagicMock
    _sdk.TextBlock = MagicMock
    _sdk.create_sdk_mcp_server = MagicMock(return_value=MagicMock())
    sys.modules["claude_agent_sdk"] = _sdk

# Stub structlog
if "structlog" not in sys.modules:
    _sl = types.ModuleType("structlog")
    _sl.__spec__ = None
    _sl.get_logger = lambda *a, **kw: MagicMock()
    sys.modules["structlog"] = _sl
else:
    sys.modules["structlog"].get_logger = lambda *a, **kw: MagicMock()

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "api"))
sys.path.insert(0, str(_ROOT / "shared"))

from refinement.prompt_tuner import PromptTuner
from refinement.focus_ranker import FocusRanker
from refinement.query_evolver import QueryEvolver
from refinement.refinement_agent import RefinementAgent
from memory.client_profile import ClientProfile, ClientRefinement


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _profile(name: str = "TestCo", run_count: int = 0, **kwargs) -> ClientProfile:
    p = ClientProfile.new(name)
    p.run_count = run_count
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def _profile_with_weights(weights: dict, focus_tables=None) -> ClientProfile:
    p = _profile(run_count=1)
    p.table_weights = weights
    if focus_tables:
        p.focus_tables = focus_tables
    return p


def _entity_map(*entries) -> dict:
    """Build an entity_map dict. Each entry is (entity_key, table_name)."""
    return {
        "entities": {
            key: {"table": table}
            for key, table in entries
        }
    }


def _findings_dict(table_sql_pairs) -> dict:
    """Build a findings dict whose finding SQLs reference specific tables."""
    items = [
        {"id": f"F{i:03d}", "severity": "HIGH", "sql": sql, "title": f"Finding {i}"}
        for i, (_, sql) in enumerate(table_sql_pairs, start=1)
    ]
    return {"analyst": {"findings": items}}


def _qr(*entries) -> dict:
    """Build a query_results dict from (name, rows) pairs."""
    return {"results": [{"name": n, "rows": r} for n, r in entries]}


# ===========================================================================
# PromptTuner
# ===========================================================================

class TestPromptTuner:

    # 1. First run → empty string
    def test_first_run_returns_empty_string(self):
        tuner = PromptTuner()
        p = _profile(run_count=0)
        assert tuner.build_context_block(p) == ""

    # 2. Non-zero run_count → non-empty block
    def test_subsequent_run_returns_non_empty_block(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        block = tuner.build_context_block(p)
        assert isinstance(block, str) and len(block) > 0

    # 3. Block contains client name
    def test_block_contains_client_name(self):
        tuner = PromptTuner()
        p = _profile("Gloria S.A.", run_count=2)
        block = tuner.build_context_block(p)
        assert "Gloria S.A." in block

    # 4. Block contains run number (run_count + 1)
    def test_block_shows_next_run_number(self):
        tuner = PromptTuner()
        p = _profile(run_count=3)
        block = tuner.build_context_block(p)
        assert "Run #4" in block

    # 5. Industry line present when set
    def test_industry_included_when_set(self):
        tuner = PromptTuner()
        p = _profile(run_count=1, industry_inferred="retail")
        block = tuner.build_context_block(p)
        assert "retail" in block

    # 6. Industry line absent when not set
    def test_industry_absent_when_none(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.industry_inferred = None
        block = tuner.build_context_block(p)
        assert "Industria" not in block

    # 7. Currency included when set
    def test_currency_included_when_set(self):
        tuner = PromptTuner()
        p = _profile(run_count=1, currency_detected="USD")
        block = tuner.build_context_block(p)
        assert "USD" in block

    # 8. Focus tables listed (capped at 5)
    def test_focus_tables_listed(self):
        tuner = PromptTuner()
        p = _profile(run_count=1, focus_tables=["c_invoice", "c_payment"])
        block = tuner.build_context_block(p)
        assert "c_invoice" in block

    # 9. Persistent findings (runs_open >= 3) appear in block
    def test_persistent_findings_appear(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.known_findings["CRIT-1"] = {
            "id": "CRIT-1", "title": "Facturas vencidas", "severity": "CRITICAL",
            "agent": "analyst", "first_seen": "2026-01-01", "last_seen": "2026-03-01",
            "runs_open": 4,
        }
        block = tuner.build_context_block(p)
        assert "CRIT-1" in block

    # 10. Non-persistent findings (runs_open < 3) do NOT appear in persistent section
    def test_non_persistent_finding_not_in_persistent_section(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.known_findings["LOW-1"] = {
            "id": "LOW-1", "title": "Minor issue", "severity": "LOW",
            "agent": "analyst", "first_seen": "2026-01-01", "last_seen": "2026-03-01",
            "runs_open": 1,
        }
        block = tuner.build_context_block(p)
        # LOW-1 should NOT appear under persistent findings
        assert "Hallazgos persistentes" not in block or "LOW-1" not in block

    # 11. Resolved findings listed
    def test_resolved_findings_listed(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.resolved_findings["SENT-2"] = {"id": "SENT-2", "title": "done"}
        block = tuner.build_context_block(p)
        assert "SENT-2" in block

    # 12. Query hints from refinement appear in block
    def test_query_hints_appear(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.refinement = {
            "table_weights": {},
            "query_hints": ["filtrar DocStatus='CO'"],
            "focus_areas": [],
            "suppress_ids": [],
            "context_block": "",
            "generated_at": "",
        }
        block = tuner.build_context_block(p)
        assert "filtrar DocStatus='CO'" in block

    # 13. inject_into_memory adds adaptive_context and client_profile_summary
    def test_inject_into_memory_adds_keys(self):
        tuner = PromptTuner()
        p = _profile(run_count=1, focus_tables=["c_invoice"])
        memory = {"run_id": "abc"}
        enhanced = tuner.inject_into_memory(memory, p)
        assert "adaptive_context" in enhanced
        assert "client_profile_summary" in enhanced

    # 14. inject_into_memory is no-op on first run
    def test_inject_into_memory_noop_on_first_run(self):
        tuner = PromptTuner()
        p = _profile(run_count=0)
        memory = {"run_id": "abc"}
        enhanced = tuner.inject_into_memory(memory, p)
        assert enhanced == memory

    # 15. inject_into_memory does not mutate original memory dict
    def test_inject_into_memory_does_not_mutate_original(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        memory = {"run_id": "abc"}
        original_keys = set(memory.keys())
        tuner.inject_into_memory(memory, p)
        assert set(memory.keys()) == original_keys

    # 16. client_profile_summary contains expected sub-keys
    def test_profile_summary_has_expected_keys(self):
        tuner = PromptTuner()
        p = _profile(run_count=2, focus_tables=["t1", "t2"])
        p.known_findings["X-1"] = {"runs_open": 1}
        enhanced = tuner.inject_into_memory({}, p)
        summary = enhanced["client_profile_summary"]
        assert "run_count" in summary
        assert "focus_tables" in summary
        assert "table_weights" in summary

    # 17. focus_areas from refinement appear in block
    def test_focus_areas_appear_in_block(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.refinement = {
            "table_weights": {},
            "query_hints": [],
            "focus_areas": ["cobranzas", "inventario"],
            "suppress_ids": [],
            "context_block": "",
            "generated_at": "",
        }
        block = tuner.build_context_block(p)
        assert "cobranzas" in block

    # 18. suppress_ids from refinement appear in block
    def test_suppress_ids_appear_in_block(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.refinement = {
            "table_weights": {},
            "query_hints": [],
            "focus_areas": [],
            "suppress_ids": ["HUNT-001"],
            "context_block": "",
            "generated_at": "",
        }
        block = tuner.build_context_block(p)
        assert "HUNT-001" in block


# ===========================================================================
# FocusRanker
# ===========================================================================

class TestFocusRanker:

    # 19. No weights → returns original entity_map unchanged
    def test_no_weights_returns_unchanged(self):
        ranker = FocusRanker()
        p = _profile()
        em = _entity_map(("orders", "sale_order"))
        assert ranker.rerank_entity_map(em, p) == em

    # 20. Empty entities → returns original entity_map unchanged
    def test_empty_entities_returns_unchanged(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"sale_order": 0.9})
        em = {"entities": {}}
        assert ranker.rerank_entity_map(em, p) == em

    # 21. High-weight table moves to front
    def test_high_weight_entity_comes_first(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"invoices": 0.9, "config": 0.1})
        em = _entity_map(("cfg", "config"), ("inv", "invoices"))
        result = ranker.rerank_entity_map(em, p)
        assert list(result["entities"].keys())[0] == "inv"

    # 22. _focus_ranked flag is set
    def test_focus_ranked_flag_set(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"x": 0.8})
        em = _entity_map(("x_entity", "x"))
        result = ranker.rerank_entity_map(em, p)
        assert result.get("_focus_ranked") is True

    # 23. Other entity_map keys are preserved
    def test_extra_keys_preserved(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"t1": 0.9})
        em = {"entities": {"e1": {"table": "t1"}}, "schema_version": 2}
        result = ranker.rerank_entity_map(em, p)
        assert result["schema_version"] == 2

    # 24. Unknown tables get default weight 0.5 — ranked between high and low
    def test_unknown_table_gets_default_weight(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"hi": 1.0, "lo": 0.0})
        em = _entity_map(("lo_e", "lo"), ("mid_e", "mystery"), ("hi_e", "hi"))
        result = ranker.rerank_entity_map(em, p)
        keys = list(result["entities"].keys())
        assert keys[0] == "hi_e"
        assert keys[-1] == "lo_e"

    # 25. All entities at same weight — order is stable (no crash)
    def test_equal_weights_no_crash(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"a": 0.5, "b": 0.5, "c": 0.5})
        em = _entity_map(("e_a", "a"), ("e_b", "b"), ("e_c", "c"))
        result = ranker.rerank_entity_map(em, p)
        assert set(result["entities"].keys()) == {"e_a", "e_b", "e_c"}


# ===========================================================================
# QueryEvolver (additional tests beyond test_query_evolver.py)
# ===========================================================================

class TestQueryEvolverAdditional:

    # 26. format_context header always present
    def test_format_context_header(self):
        evolver = QueryEvolver()
        p = _profile()
        ctx = evolver.format_context(p)
        assert "Query Evolution Context" in ctx

    # 27. Chronic empty threshold: query with count=1 does NOT appear
    def test_query_with_count_1_not_chronic(self):
        evolver = QueryEvolver()
        p = _profile()
        p.metadata["empty_query_counts"] = {"single_empty": 1}
        ctx = evolver.format_context(p)
        assert "single_empty" not in ctx

    # 28. Chronic empty threshold: query with count=2 DOES appear
    def test_query_with_count_2_is_chronic(self):
        evolver = QueryEvolver()
        p = _profile()
        p.metadata["empty_query_counts"] = {"repeat_empty": 2}
        ctx = evolver.format_context(p)
        assert "repeat_empty" in ctx

    # 29. preferred_queries with string entries handled in format_context
    def test_format_context_handles_string_preferred_queries(self):
        evolver = QueryEvolver()
        p = _profile()
        p.preferred_queries = ["string_hint_table"]
        ctx = evolver.format_context(p)
        assert "string_hint_table" in ctx

    # 30. Multiple empty queries all tracked in one call
    def test_multiple_empty_queries_tracked(self):
        evolver = QueryEvolver()
        p = _profile()
        qr = _qr(("q1", []), ("q2", []), ("q3", [{"id": 1}]))
        result = evolver.analyze_query_results(qr, {}, p)
        assert "q1" in result["empty_queries"]
        assert "q2" in result["empty_queries"]
        assert "q3" not in result["empty_queries"]

    # 31. analyze_query_results initialises empty_query_counts when not present
    def test_empty_query_counts_initialized_automatically(self):
        evolver = QueryEvolver()
        p = _profile()
        assert "empty_query_counts" not in p.metadata
        evolver.analyze_query_results(_qr(("q", [])), {}, p)
        assert isinstance(p.metadata.get("empty_query_counts"), dict)

    # 32. Findings with no SQL field do not crash
    def test_findings_without_sql_no_crash(self):
        evolver = QueryEvolver()
        p = _profile(focus_tables=["orders"])
        findings = {"analyst": {"findings": [{"id": "F001", "title": "No SQL here"}]}}
        result = evolver.analyze_query_results(_qr(), findings, p)
        assert result["high_value_tables"] == []


# ===========================================================================
# RefinementAgent._heuristic_analyze
# ===========================================================================

class TestRefinementAgentHeuristic:

    def _agent(self) -> RefinementAgent:
        return RefinementAgent()

    # 33. Returns a ClientRefinement instance (checked by class name to avoid dual-import issues)
    def test_returns_client_refinement(self):
        agent = self._agent()
        p = _profile(run_count=1)
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert type(result).__name__ == "ClientRefinement"

    # 34. Resolved findings from run_delta → suppress_ids
    def test_resolved_findings_in_suppress_ids(self):
        agent = self._agent()
        p = _profile(run_count=1)
        run_delta = {"new": [], "resolved": ["LOW-001", "INFO-002"], "worsened": [], "improved": []}
        result = agent._heuristic_analyze(p, {}, {}, run_delta)
        assert "LOW-001" in result.suppress_ids
        assert "INFO-002" in result.suppress_ids

    # 35. suppress_ids capped at 5
    def test_suppress_ids_capped_at_5(self):
        agent = self._agent()
        p = _profile(run_count=1)
        run_delta = {"resolved": [f"ID-{i}" for i in range(10)]}
        result = agent._heuristic_analyze(p, {}, {}, run_delta)
        assert len(result.suppress_ids) <= 5

    # 36. None run_delta → empty suppress_ids (no crash)
    def test_none_run_delta_no_crash(self):
        agent = self._agent()
        p = _profile(run_count=1)
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert result.suppress_ids == []

    # 37. focus_areas taken from profile.focus_tables (up to 3)
    def test_focus_areas_from_profile_tables(self):
        agent = self._agent()
        p = _profile(run_count=1, focus_tables=["t1", "t2", "t3", "t4"])
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert result.focus_areas == ["t1", "t2", "t3"]

    # 38. c_invoice in focus_tables → DocStatus hint added
    def test_c_invoice_triggers_docstatus_hint(self):
        agent = self._agent()
        p = _profile(run_count=1, focus_tables=["c_invoice", "c_payment"])
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert any("DocStatus" in h for h in result.query_hints)

    # 39. c_bpartner in focus_tables → iscustomer hint added
    def test_c_bpartner_triggers_iscustomer_hint(self):
        agent = self._agent()
        p = _profile(run_count=1, focus_tables=["c_bpartner"])
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert any("iscustomer" in h for h in result.query_hints)

    # 40. table_weights copied from profile
    def test_table_weights_copied_from_profile(self):
        agent = self._agent()
        p = _profile(run_count=1)
        p.table_weights = {"c_invoice": 0.9, "c_payment": 0.6}
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert result.table_weights == {"c_invoice": 0.9, "c_payment": 0.6}

    # 41. No focus_tables → empty focus_areas and no hints
    def test_no_focus_tables_empty_hints(self):
        agent = self._agent()
        p = _profile(run_count=1, focus_tables=[])
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert result.focus_areas == []
        assert result.query_hints == []

    # 42. analyze_run falls back to heuristics when LLM raises
    def test_analyze_run_falls_back_to_heuristics(self):
        """
        Stub _llm_analyze to raise, confirm analyze_run returns a valid
        ClientRefinement produced by _heuristic_analyze and sets generated_at.
        """
        import asyncio

        agent = self._agent()

        async def _raising_llm(*args, **kwargs):
            raise RuntimeError("LLM unavailable")

        agent._llm_analyze = _raising_llm

        p = _profile(run_count=1, focus_tables=["c_invoice"])
        run_delta = {"new": [], "resolved": ["X-1"], "worsened": [], "improved": []}

        result = asyncio.get_event_loop().run_until_complete(
            agent.analyze_run(p, {}, {}, {}, "2026-03", run_delta)
        )

        assert type(result).__name__ == "ClientRefinement"
        assert result.generated_at  # must be set
        assert "X-1" in result.suppress_ids

    # 43. analyze_run sets generated_at on the refinement object
    def test_analyze_run_sets_generated_at(self):
        import asyncio

        agent = self._agent()

        async def _raising_llm(*args, **kwargs):
            raise RuntimeError("LLM unavailable")

        agent._llm_analyze = _raising_llm

        p = _profile(run_count=2, focus_tables=[])

        result = asyncio.get_event_loop().run_until_complete(
            agent.analyze_run(p, {}, {}, {}, "2026-03", None)
        )

        assert isinstance(result.generated_at, str)
        assert len(result.generated_at) > 0


# ===========================================================================
# Additional tests (44-56)
# ===========================================================================

# ---------------------------------------------------------------------------
# PromptTuner — extended edge cases
# ---------------------------------------------------------------------------

class TestPromptTunerExtended:

    # 44. focus_tables capped at 5 in block
    def test_focus_tables_capped_at_5_in_block(self):
        tuner = PromptTuner()
        p = _profile(run_count=1, focus_tables=[f"t{i}" for i in range(8)])
        block = tuner.build_context_block(p)
        # Only up to 5 tables should appear in the tables line
        # t5, t6, t7 (indices 5-7) must NOT be present beyond the cap
        for t in ["t5", "t6", "t7"]:
            assert t not in block

    # 45. Multiple persistent findings (runs_open >= 3) all appear in block
    def test_multiple_persistent_findings_appear(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.known_findings["A-1"] = {
            "id": "A-1", "title": "issue A", "severity": "CRITICAL",
            "agent": "analyst", "first_seen": "2026-01-01", "last_seen": "2026-03-01",
            "runs_open": 5,
        }
        p.known_findings["B-2"] = {
            "id": "B-2", "title": "issue B", "severity": "HIGH",
            "agent": "analyst", "first_seen": "2026-01-01", "last_seen": "2026-03-01",
            "runs_open": 3,
        }
        block = tuner.build_context_block(p)
        assert "A-1" in block
        assert "B-2" in block

    # 46. inject_into_memory: known_findings_count matches profile
    def test_inject_into_memory_known_findings_count(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.known_findings["X-1"] = {"runs_open": 1}
        p.known_findings["X-2"] = {"runs_open": 2}
        enhanced = tuner.inject_into_memory({}, p)
        assert enhanced["client_profile_summary"]["known_findings_count"] == 2

    # 47. inject_into_memory: resolved_findings_count matches profile
    def test_inject_into_memory_resolved_findings_count(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.resolved_findings["R-1"] = {"id": "R-1", "title": "done"}
        enhanced = tuner.inject_into_memory({}, p)
        assert enhanced["client_profile_summary"]["resolved_findings_count"] == 1

    # 48. build_context_block: both focus_areas AND query_hints in same block
    def test_block_contains_both_hints_and_focus_areas(self):
        tuner = PromptTuner()
        p = _profile(run_count=1)
        p.refinement = {
            "table_weights": {},
            "query_hints": ["use index on date_col"],
            "focus_areas": ["ventas"],
            "suppress_ids": [],
            "context_block": "",
            "generated_at": "",
        }
        block = tuner.build_context_block(p)
        assert "use index on date_col" in block
        assert "ventas" in block


# ---------------------------------------------------------------------------
# FocusRanker — extended edge cases
# ---------------------------------------------------------------------------

class TestFocusRankerExtended:

    # 49. Single entity — no crash, still gets _focus_ranked flag
    def test_single_entity_ranked(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"only_table": 0.7})
        em = _entity_map(("only_e", "only_table"))
        result = ranker.rerank_entity_map(em, p)
        assert result.get("_focus_ranked") is True
        assert list(result["entities"].keys()) == ["only_e"]

    # 50. entity without 'table' key falls back to entity key for weight lookup
    def test_entity_without_table_key_uses_entity_key(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"hi_key": 1.0, "lo_key": 0.0})
        em = {
            "entities": {
                "lo_key": {},          # no 'table' key — uses entity key "lo_key"
                "hi_key": {},          # no 'table' key — uses entity key "hi_key"
            }
        }
        result = ranker.rerank_entity_map(em, p)
        keys = list(result["entities"].keys())
        assert keys[0] == "hi_key"
        assert keys[-1] == "lo_key"

    # 51. rerank_entity_map returns a NEW dict (does not mutate input)
    def test_rerank_does_not_mutate_original(self):
        ranker = FocusRanker()
        p = _profile_with_weights({"t1": 0.9, "t2": 0.1})
        em = _entity_map(("e2", "t2"), ("e1", "t1"))
        original_keys = list(em["entities"].keys())
        ranker.rerank_entity_map(em, p)
        # Original order must be intact
        assert list(em["entities"].keys()) == original_keys


# ---------------------------------------------------------------------------
# QueryEvolver — extended edge cases
# ---------------------------------------------------------------------------

class TestQueryEvolverExtended:

    # 52. analyze_query_results: high_value table only added once to preferred_queries
    def test_high_value_table_added_once_to_preferred_queries(self):
        evolver = QueryEvolver()
        p = _profile(focus_tables=["c_invoice"])
        findings = _findings_dict([("c_invoice", "SELECT * FROM c_invoice")])
        evolver.analyze_query_results(_qr(), findings, p)
        evolver.analyze_query_results(_qr(), findings, p)  # second call
        hints = [
            pq if isinstance(pq, str) else pq.get("hint", "")
            for pq in p.preferred_queries
        ]
        assert hints.count("priorizar tabla: c_invoice") == 1

    # 53. format_context: high-value tables from preferred_queries appear
    def test_format_context_shows_high_value_tables(self):
        evolver = QueryEvolver()
        p = _profile(focus_tables=["orders"])
        findings = _findings_dict([("orders", "SELECT id FROM orders WHERE status='open'")])
        evolver.analyze_query_results(_qr(), findings, p)
        ctx = evolver.format_context(p)
        assert "orders" in ctx

    # 54. analyze_query_results with empty query_results dict — no crash
    def test_empty_query_results_no_crash(self):
        evolver = QueryEvolver()
        p = _profile()
        result = evolver.analyze_query_results({}, {}, p)
        assert result["empty_queries"] == []
        assert result["high_value_tables"] == []

    # 55. preferred_queries capped at 10 hints
    def test_preferred_queries_capped_at_10(self):
        evolver = QueryEvolver()
        tables = [f"t{i}" for i in range(12)]
        p = _profile(focus_tables=tables)
        for tbl in tables:
            findings = _findings_dict([(tbl, f"SELECT * FROM {tbl}")])
            evolver.analyze_query_results(_qr(), findings, p)
        assert len(p.preferred_queries) <= 10


# ---------------------------------------------------------------------------
# RefinementAgent._heuristic_analyze — extended edge cases
# ---------------------------------------------------------------------------

class TestRefinementAgentHeuristicExtended:

    def _agent(self) -> RefinementAgent:
        return RefinementAgent()

    # 56. Both c_invoice AND c_bpartner in focus_tables — both hints added
    def test_both_hints_added_when_both_tables_present(self):
        agent = self._agent()
        p = _profile(run_count=1, focus_tables=["c_invoice", "c_bpartner", "c_payment"])
        result = agent._heuristic_analyze(p, {}, {}, None)
        assert any("DocStatus" in h for h in result.query_hints)
        assert any("iscustomer" in h for h in result.query_hints)
