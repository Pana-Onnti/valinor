"""
Tests for the financial vertical (VAL-130 L1.b).

Verifies that analyst/sentinel/hunter are wrapped by the registry-backed
adapters and can be invoked via the same `run_vertical` entry point as
the inventory vertical. Uses mocks of `run_analyst/sentinel/hunter`
because they normally call the real Claude SDK.

Refs: VAL-130
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest

# conftest.py stubs claude_agent_sdk for the entire test run so we can
# import valinor.verticals.financial safely here.

from valinor.verticals import (
    AGENT_REGISTRY,
    BUILTIN_VERTICALS,
    FINANCIAL_VERTICAL,
    get_agent,
    get_vertical,
    run_vertical,
)
from valinor.verticals.financial import (
    _analyst_adapter,
    _hunter_adapter,
    _sentinel_adapter,
    _swarm_parallel,
)


# ─────────────────────────────────────────────────────────────────────
# Registry & config
# ─────────────────────────────────────────────────────────────────────


class TestRegistryRegistration:
    def test_financial_agents_registered(self):
        assert "analyst" in AGENT_REGISTRY
        assert "sentinel" in AGENT_REGISTRY
        assert "hunter" in AGENT_REGISTRY
        assert "financial_swarm" in AGENT_REGISTRY

    def test_financial_swarm_spec(self):
        spec = get_agent("financial_swarm")
        assert spec.model == "sonnet"
        assert "query_results" in spec.required_inputs
        assert "entity_map" in spec.required_inputs
        assert "baseline" in spec.required_inputs

    def test_financial_vertical_in_builtins(self):
        assert "financial" in BUILTIN_VERTICALS
        assert get_vertical("financial") is FINANCIAL_VERTICAL

    def test_financial_config_shape(self):
        assert FINANCIAL_VERTICAL.name == "financial"
        assert FINANCIAL_VERTICAL.output_format == "digest"
        assert FINANCIAL_VERTICAL.estimated_cost_usd > 0.0
        assert len(FINANCIAL_VERTICAL.agents) == 1  # single swarm meta-agent
        assert FINANCIAL_VERTICAL.agents[0].name == "financial_swarm"


# ─────────────────────────────────────────────────────────────────────
# Adapters extract legacy inputs correctly
# ─────────────────────────────────────────────────────────────────────


class TestLegacyAdapters:
    async def test_analyst_adapter_passes_legacy_args(self):
        mock = AsyncMock(return_value={"agent": "analyst", "output": "ok"})
        with patch("valinor.verticals.financial.run_analyst", mock):
            context = {
                "query_results": {"q": 1},
                "entity_map": {"tables": ["t1"]},
                "memory": {"prev": True},
                "baseline": {"revenue": 100},
                "kg": "kg_obj",
            }
            result = await _analyst_adapter(context)
            assert result == {"agent": "analyst", "output": "ok"}
            mock.assert_awaited_once_with(
                {"q": 1}, {"tables": ["t1"]}, {"prev": True}, {"revenue": 100},
                kg="kg_obj",
            )

    async def test_sentinel_adapter_defaults_when_missing_keys(self):
        mock = AsyncMock(return_value={"agent": "sentinel", "output": {}})
        with patch("valinor.verticals.financial.run_sentinel", mock):
            await _sentinel_adapter({"query_results": {}})
            args, kwargs = mock.call_args
            assert args[0] == {}           # query_results
            assert args[1] == {}           # entity_map default
            assert args[2] is None          # memory default
            assert args[3] == {}           # baseline default
            assert kwargs["kg"] is None    # kg default

    async def test_hunter_adapter_wraps_non_dict_result(self):
        mock = AsyncMock(return_value="raw string")
        with patch("valinor.verticals.financial.run_hunter", mock):
            result = await _hunter_adapter({})
            assert result == {"agent": "hunter", "output": "raw string"}


# ─────────────────────────────────────────────────────────────────────
# Parallel swarm meta-agent
# ─────────────────────────────────────────────────────────────────────


class TestSwarmParallel:
    async def test_all_three_findings_collected(self):
        a = AsyncMock(return_value={"agent": "analyst", "output": {"f": 1}})
        s = AsyncMock(return_value={"agent": "sentinel", "output": {"f": 2}})
        h = AsyncMock(return_value={"agent": "hunter", "output": {"f": 3}})
        with patch("valinor.verticals.financial.run_analyst", a), \
             patch("valinor.verticals.financial.run_sentinel", s), \
             patch("valinor.verticals.financial.run_hunter", h):
            result = await _swarm_parallel({
                "query_results": {},
                "entity_map": {},
                "baseline": {},
            })
            assert result["agent"] == "financial_swarm"
            findings = result["output"]
            assert set(findings) == {"analyst", "sentinel", "hunter"}
            assert findings["analyst"]["output"] == {"f": 1}

    async def test_exception_captured_not_fatal(self):
        a = AsyncMock(return_value={"agent": "analyst", "output": {}})
        s = AsyncMock(side_effect=RuntimeError("boom"))
        h = AsyncMock(return_value={"agent": "hunter", "output": {}})
        with patch("valinor.verticals.financial.run_analyst", a), \
             patch("valinor.verticals.financial.run_sentinel", s), \
             patch("valinor.verticals.financial.run_hunter", h):
            result = await _swarm_parallel({
                "query_results": {},
                "entity_map": {},
                "baseline": {},
            })
            findings = result["output"]
            # analyst + hunter succeed, sentinel error captured
            assert "analyst" in findings
            assert "hunter" in findings
            error_key = next((k for k in findings if k.startswith("error_")), None)
            assert error_key is not None
            assert findings[error_key]["error"] is True


# ─────────────────────────────────────────────────────────────────────
# End-to-end: run_vertical("financial") mirrors pipeline behavior
# ─────────────────────────────────────────────────────────────────────


class TestFinancialViaRunVertical:
    async def test_run_vertical_financial_dispatches_swarm(self):
        a = AsyncMock(return_value={"agent": "analyst", "output": {"rev": 100}})
        s = AsyncMock(return_value={"agent": "sentinel", "output": {"alerts": 0}})
        h = AsyncMock(return_value={"agent": "hunter", "output": {"dq": "ok"}})
        with patch("valinor.verticals.financial.run_analyst", a), \
             patch("valinor.verticals.financial.run_sentinel", s), \
             patch("valinor.verticals.financial.run_hunter", h):
            output = await run_vertical(
                FINANCIAL_VERTICAL,
                {"name": "acme"},
                extra_context={
                    "query_results": {"orders": 50},
                    "entity_map": {"tables": []},
                    "baseline": {"revenue": 1000},
                },
            )
            assert output.vertical == "financial"
            assert output.errors == []
            # digest_builder flattens the swarm meta-agent to inner findings
            assert "analyst" in output.digest
            assert "sentinel" in output.digest
            assert "hunter" in output.digest

    async def test_run_vertical_financial_missing_inputs_skipped(self):
        """If required inputs missing, agent is skipped (run_vertical semantics)."""
        output = await run_vertical(
            FINANCIAL_VERTICAL,
            {"name": "acme"},
            # No extra_context: missing query_results/entity_map/baseline
        )
        # swarm meta-agent should be skipped -> errors recorded, no findings
        assert any("financial_swarm" in e for e in output.errors)
        assert "financial_swarm" not in output.findings
