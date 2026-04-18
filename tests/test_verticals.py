"""
Tests for the composable vertical pipeline (VAL-130 L1.a).

Covers:
  - AgentSpec / VerticalConfig validation
  - AGENT_REGISTRY register/get
  - run_vertical orchestrator: happy path, missing inputs, agent errors,
    query executor errors, output builder errors, extra_context injection
  - Inventory vertical config + inventory_analyzer agent with mock LLM

Refs: VAL-130
"""

from __future__ import annotations

import json

import pytest

from valinor.verticals import (
    AGENT_REGISTRY,
    AgentSpec,
    VerticalConfig,
    VerticalOutput,
    get_agent,
    register_agent,
    run_vertical,
)
from valinor.verticals.inventory import (
    INVENTORY_VERTICAL,
    run_inventory_analyzer,
)


# ─────────────────────────────────────────────────────────────────────
# AgentSpec / VerticalConfig
# ─────────────────────────────────────────────────────────────────────


class TestAgentSpec:
    def test_minimal_spec(self):
        async def _noop(ctx):
            return {"agent": "x", "output": {}}

        spec = AgentSpec(name="x", runner=_noop)
        assert spec.name == "x"
        assert spec.model == "haiku"
        assert spec.required_inputs == ()

    def test_non_callable_runner_raises(self):
        with pytest.raises(TypeError):
            AgentSpec(name="bad", runner="not-callable")


class TestRegistry:
    def test_register_and_get(self):
        async def _a(ctx):
            return {}

        spec = register_agent(AgentSpec(name="_test_x", runner=_a))
        assert get_agent("_test_x") is spec
        assert "_test_x" in AGENT_REGISTRY
        del AGENT_REGISTRY["_test_x"]

    def test_unknown_agent_raises(self):
        with pytest.raises(KeyError, match="Unknown agent"):
            get_agent("nonexistent_agent_zzz")


# ─────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────


class _RecordingExecutor:
    """Fakes a query executor and records which queries were asked."""

    def __init__(self, results=None, raise_on=None):
        self.results = results or {}
        self.raise_on = raise_on or set()
        self.calls: list[str] = []

    async def execute(self, query_name, client_config):
        self.calls.append(query_name)
        if query_name in self.raise_on:
            raise RuntimeError(f"boom: {query_name}")
        return self.results.get(query_name, {})


async def _agent_echo(context):
    """Agent that returns the context query_results as its output."""
    return {
        "agent": "echo",
        "output": context["query_results"],
    }


async def _agent_raises(context):
    raise ValueError("explode")


class TestRunVertical:
    async def test_happy_path_with_single_agent(self):
        spec = AgentSpec(name="echo", runner=_agent_echo, required_inputs=("query_results",))
        config = VerticalConfig(name="test", agents=[spec], queries=["q1", "q2"])
        executor = _RecordingExecutor(results={"q1": [1, 2], "q2": [3]})

        output = await run_vertical(config, {"name": "acme"}, query_executor=executor)

        assert isinstance(output, VerticalOutput)
        assert output.vertical == "test"
        assert executor.calls == ["q1", "q2"]
        assert output.findings["echo"]["output"] == {"q1": [1, 2], "q2": [3]}
        # digest builder for single-agent flattens to the agent output
        assert output.digest == {"q1": [1, 2], "q2": [3]}
        assert output.errors == []
        assert output.duration_seconds >= 0.0

    async def test_query_error_recorded_but_continues(self):
        spec = AgentSpec(name="echo", runner=_agent_echo, required_inputs=("query_results",))
        config = VerticalConfig(name="test", agents=[spec], queries=["ok", "fail"])
        executor = _RecordingExecutor(results={"ok": [1]}, raise_on={"fail"})

        output = await run_vertical(config, {"name": "acme"}, query_executor=executor)

        assert "query fail" in output.errors[0]
        assert output.findings["echo"]["output"]["ok"] == [1]
        assert output.findings["echo"]["output"]["fail"] is None

    async def test_missing_input_skips_agent(self):
        spec = AgentSpec(
            name="needs_missing", runner=_agent_echo,
            required_inputs=("not_in_context",),
        )
        config = VerticalConfig(name="test", agents=[spec])

        output = await run_vertical(config, {"name": "acme"})

        assert any("not_in_context" in e for e in output.errors)
        assert "needs_missing" not in output.findings

    async def test_agent_exception_captured(self):
        spec = AgentSpec(name="bad", runner=_agent_raises)
        config = VerticalConfig(name="test", agents=[spec])

        output = await run_vertical(config, {"name": "acme"})

        assert output.findings["bad"]["error"] == "explode"
        assert any("bad: ValueError: explode" in e for e in output.errors)

    async def test_extra_context_injected(self):
        observed = {}

        async def _observer(context):
            observed.update(context)
            return {"agent": "observer", "output": {}}

        spec = AgentSpec(name="observer", runner=_observer)
        config = VerticalConfig(name="test", agents=[spec])

        await run_vertical(
            config, {"name": "acme"},
            extra_context={"llm_client": "injected"},
        )

        assert observed.get("llm_client") == "injected"
        assert observed.get("vertical") == "test"
        assert observed.get("client_name") == "acme"

    async def test_custom_output_builder(self):
        spec = AgentSpec(name="echo", runner=_agent_echo, required_inputs=("query_results",))
        config = VerticalConfig(
            name="test", agents=[spec], queries=["q"],
            output_builder=lambda findings: {"flat": "custom"},
        )
        output = await run_vertical(
            config, {"name": "acme"},
            query_executor=_RecordingExecutor(results={"q": 1}),
        )
        assert output.digest == {"flat": "custom"}

    async def test_output_builder_error_captured(self):
        spec = AgentSpec(name="echo", runner=_agent_echo, required_inputs=("query_results",))

        def _bad_builder(findings):
            raise RuntimeError("builder failed")

        config = VerticalConfig(
            name="test", agents=[spec], queries=["q"],
            output_builder=_bad_builder,
        )
        output = await run_vertical(config, {"name": "acme"})
        assert any("output_builder" in e for e in output.errors)
        assert output.digest["_error"] == "builder failed"


# ─────────────────────────────────────────────────────────────────────
# Inventory vertical
# ─────────────────────────────────────────────────────────────────────


class _MockLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    async def complete(self, system: str, prompt: str) -> str:
        self.calls.append({"system": system, "prompt": prompt})
        return self.response


class TestInventoryVertical:
    def test_inventory_config_shape(self):
        assert INVENTORY_VERTICAL.name == "inventory"
        assert INVENTORY_VERTICAL.output_format == "digest"
        assert len(INVENTORY_VERTICAL.agents) == 1
        assert INVENTORY_VERTICAL.agents[0].name == "inventory_analyzer"
        assert "bajo_minimo" in INVENTORY_VERTICAL.queries
        assert INVENTORY_VERTICAL.estimated_cost_usd < 0.01

    async def test_inventory_analyzer_happy_path(self):
        llm = _MockLLM(json.dumps({
            "urgent":     [{"sku": "TN-324K", "stock": 0, "recommend": 15, "reason": "stock 0"}],
            "low_stock":  [{"sku": "DR-312", "stock": 2, "recommend": 8, "reason": "bajo minimo"}],
            "top_selling": [{"sku": "A4-75",  "units": 45}],
            "summary": "1 urgent, 1 low, top A4",
        }))
        context = {
            "query_results": {"bajo_minimo": [{"sku": "TN-324K", "stock": 0}]},
            "client_name": "SYSCOP",
            "llm_client": llm,
        }
        result = await run_inventory_analyzer(context)

        assert result["agent"] == "inventory_analyzer"
        assert result["output"]["summary"] == "1 urgent, 1 low, top A4"
        assert len(result["output"]["urgent"]) == 1
        assert len(llm.calls) == 1

    async def test_inventory_analyzer_handles_bad_json(self):
        llm = _MockLLM("not json at all")
        context = {
            "query_results": {},
            "client_name": "SYSCOP",
            "llm_client": llm,
        }
        result = await run_inventory_analyzer(context)
        assert result["output"]["summary"] == "parse_error"

    async def test_inventory_via_run_vertical(self):
        llm = _MockLLM(json.dumps({
            "urgent": [],
            "low_stock": [],
            "top_selling": [],
            "summary": "all good",
        }))
        executor = _RecordingExecutor(results={q: [] for q in INVENTORY_VERTICAL.queries})
        output = await run_vertical(
            INVENTORY_VERTICAL, {"name": "SYSCOP"},
            query_executor=executor,
            extra_context={"llm_client": llm},
        )
        assert executor.calls == INVENTORY_VERTICAL.queries
        assert output.digest["summary"] == "all good"
        assert output.errors == []
