"""
Tests for the shared observability layer (VAL-29).

All tests run without a real LMNR_API_KEY — verifies no-op mode works
correctly and that the decorator/tracer are usable.
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_observability():
    """Reload shared.observability to pick up env-var changes."""
    import importlib
    import shared.observability as obs
    importlib.reload(obs)
    return obs


# ---------------------------------------------------------------------------
# Test 1: Module imports without LMNR_API_KEY (no-op mode)
# ---------------------------------------------------------------------------

class TestNoopMode:
    def test_module_imports(self):
        """shared.observability imports cleanly without LMNR_API_KEY."""
        with patch.dict(os.environ, {"LMNR_API_KEY": ""}):
            obs = _reload_observability()
            assert obs is not None

    def test_swarm_agents_list(self):
        """SWARM_AGENTS lists all 8 expected agents."""
        from shared.observability import SWARM_AGENTS

        expected = {
            "data_quality_gate", "cartographer", "query_evolver",
            "query_builder", "analyst", "sentinel", "hunter", "narrator",
        }
        assert set(SWARM_AGENTS) == expected

    def test_get_tracer_returns_noop(self):
        """get_tracer() returns a usable tracer in no-op mode."""
        with patch.dict(os.environ, {"LMNR_API_KEY": ""}):
            obs = _reload_observability()
            tracer = obs.get_tracer()
            assert tracer is not None

    def test_noop_span_context_manager(self):
        """Noop tracer span is usable as context manager."""
        with patch.dict(os.environ, {"LMNR_API_KEY": ""}):
            obs = _reload_observability()
            tracer = obs.get_tracer()
            with tracer.start_as_current_span("test-span") as span:
                span.set_attribute("key", "value")  # should not raise


# ---------------------------------------------------------------------------
# Test 2: observe_agent decorator — sync function
# ---------------------------------------------------------------------------

class TestObserveAgentSync:
    def test_sync_function_wraps_correctly(self):
        """observe_agent wraps a sync function and returns its result."""
        from shared.observability import observe_agent

        @observe_agent("test_sync_agent")
        def sample_fn(x: int) -> int:
            return x * 2

        assert sample_fn(5) == 10

    def test_sync_function_propagates_exception(self):
        """observe_agent re-raises exceptions from the wrapped function."""
        from shared.observability import observe_agent

        @observe_agent("test_sync_error")
        def failing_fn():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_fn()

    def test_sync_wrapper_preserves_name(self):
        """Decorated sync function preserves __name__."""
        from shared.observability import observe_agent

        @observe_agent("test_agent")
        def my_function():
            pass

        assert my_function.__name__ == "my_function"


# ---------------------------------------------------------------------------
# Test 3: observe_agent decorator — async function
# ---------------------------------------------------------------------------

class TestObserveAgentAsync:
    async def test_async_function_wraps_correctly(self):
        """observe_agent wraps an async function and returns its result."""
        from shared.observability import observe_agent

        @observe_agent("test_async_agent")
        async def async_fn(x: int) -> int:
            return x + 10

        result = await async_fn(5)
        assert result == 15

    async def test_async_function_propagates_exception(self):
        """observe_agent re-raises exceptions from async functions."""
        from shared.observability import observe_agent

        @observe_agent("test_async_error")
        async def failing_async():
            raise RuntimeError("async failure")

        with pytest.raises(RuntimeError, match="async failure"):
            await failing_async()

    async def test_async_wrapper_preserves_name(self):
        """Decorated async function preserves __name__."""
        from shared.observability import observe_agent

        @observe_agent("cartographer")
        async def run_cartographer():
            pass

        assert run_cartographer.__name__ == "run_cartographer"


# ---------------------------------------------------------------------------
# Test 4: record_token_usage — does not raise
# ---------------------------------------------------------------------------

class TestRecordTokenUsage:
    def test_record_token_usage_no_raise(self):
        """record_token_usage should not raise even without lmnr."""
        from shared.observability import record_token_usage

        # Should complete without exception
        record_token_usage("analyst", input_tokens=1500, output_tokens=300)

    def test_record_token_usage_zero(self):
        """record_token_usage handles zero tokens."""
        from shared.observability import record_token_usage

        record_token_usage("cartographer", input_tokens=0, output_tokens=0)


# ---------------------------------------------------------------------------
# Test 5: observe_agent on all 8 swarm agents (smoke test)
# ---------------------------------------------------------------------------

class TestAllSwarmAgentsSmoke:
    @pytest.mark.parametrize("agent_name", [
        "data_quality_gate",
        "cartographer",
        "query_evolver",
        "query_builder",
        "analyst",
        "sentinel",
        "hunter",
        "narrator",
    ])
    async def test_agent_decorator_applies(self, agent_name):
        """observe_agent decorator applies to each of the 8 swarm agents."""
        from shared.observability import observe_agent

        @observe_agent(agent_name)
        async def mock_agent_run(**kwargs):
            return {"agent": agent_name, "status": "ok"}

        result = await mock_agent_run()
        assert result["agent"] == agent_name
        assert result["status"] == "ok"
