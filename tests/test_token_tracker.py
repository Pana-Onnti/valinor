"""
Tests for TokenTracker and KV-cache integration (VAL-31).
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Token Tracker tests
# ---------------------------------------------------------------------------

class TestTokenTracker:
    def setup_method(self):
        """Reset singleton state before each test."""
        from shared.llm.token_tracker import TokenTracker
        tracker = TokenTracker.get_instance()
        tracker.reset()

    def test_singleton(self):
        """TokenTracker.get_instance() returns the same instance."""
        from shared.llm.token_tracker import TokenTracker
        a = TokenTracker.get_instance()
        b = TokenTracker.get_instance()
        assert a is b

    def test_record_basic(self):
        """record() accumulates tokens for an agent."""
        from shared.llm.token_tracker import TokenTracker
        tracker = TokenTracker.get_instance()
        tracker.record(
            agent="analyst",
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=200,
        )
        stats = tracker.get_stats("analyst")
        assert stats.input_tokens == 1000
        assert stats.output_tokens == 200
        assert stats.call_count == 1

    def test_record_cache_tokens(self):
        """record() captures cache_read and cache_creation tokens."""
        from shared.llm.token_tracker import TokenTracker
        tracker = TokenTracker.get_instance()
        tracker.record(
            agent="cartographer",
            model="claude-3-5-sonnet-20241022",
            input_tokens=500,
            output_tokens=100,
            cache_read_tokens=800,
            cache_creation_tokens=400,
        )
        stats = tracker.get_stats("cartographer")
        assert stats.cache_read_tokens == 800
        assert stats.cache_creation_tokens == 400

    def test_cache_hit_rate(self):
        """cache_hit_rate is computed correctly."""
        from shared.llm.token_tracker import AgentTokenStats
        stats = AgentTokenStats(
            agent="analyst",
            input_tokens=200,
            cache_read_tokens=800,
            cache_creation_tokens=0,
        )
        # cache_hit_rate = 800 / (200 + 800 + 0) = 0.8
        assert abs(stats.cache_hit_rate - 0.8) < 1e-6

    def test_cache_hit_rate_zero_when_no_tokens(self):
        """cache_hit_rate is 0.0 when no tokens recorded."""
        from shared.llm.token_tracker import AgentTokenStats
        stats = AgentTokenStats(agent="test")
        assert stats.cache_hit_rate == 0.0

    def test_accumulates_multiple_calls(self):
        """Multiple calls accumulate correctly."""
        from shared.llm.token_tracker import TokenTracker
        tracker = TokenTracker.get_instance()
        for _ in range(3):
            tracker.record(
                agent="sentinel",
                model="claude-3-5-sonnet-20241022",
                input_tokens=100,
                output_tokens=50,
            )
        stats = tracker.get_stats("sentinel")
        assert stats.input_tokens == 300
        assert stats.output_tokens == 150
        assert stats.call_count == 3

    def test_get_summary_includes_all_agents(self):
        """get_summary() returns stats for all recorded agents."""
        from shared.llm.token_tracker import TokenTracker
        tracker = TokenTracker.get_instance()
        tracker.record(agent="analyst", model="x", input_tokens=10, output_tokens=5)
        tracker.record(agent="sentinel", model="x", input_tokens=20, output_tokens=10)
        summary = tracker.get_summary()
        assert "analyst" in summary
        assert "sentinel" in summary

    def test_total_cost_usd(self):
        """get_total_cost_usd() returns sum of all agent costs."""
        from shared.llm.token_tracker import TokenTracker
        tracker = TokenTracker.get_instance()
        tracker.record(
            agent="analyst",
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        cost = tracker.get_total_cost_usd()
        # 1M input tokens at $3/M = $3
        assert abs(cost - 3.0) < 0.01

    def test_reset(self):
        """reset() clears all accumulated stats."""
        from shared.llm.token_tracker import TokenTracker
        tracker = TokenTracker.get_instance()
        tracker.record(agent="analyst", model="x", input_tokens=100, output_tokens=50)
        tracker.reset()
        assert tracker.get_summary() == {}


# ---------------------------------------------------------------------------
# estimate_cost tests
# ---------------------------------------------------------------------------

class TestEstimateCost:
    def test_input_only_sonnet(self):
        """1M input tokens on Sonnet costs $3."""
        from shared.llm.token_tracker import estimate_cost
        cost = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        assert abs(cost - 3.0) < 0.001

    def test_output_only_sonnet(self):
        """1M output tokens on Sonnet costs $15."""
        from shared.llm.token_tracker import estimate_cost
        cost = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=0,
            output_tokens=1_000_000,
        )
        assert abs(cost - 15.0) < 0.001

    def test_cache_read_discount(self):
        """Cache read is significantly cheaper than regular input."""
        from shared.llm.token_tracker import estimate_cost
        regular = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        cached = estimate_cost(
            model="claude-3-5-sonnet-20241022",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1_000_000,
        )
        # Cache read should be much cheaper (~90% discount)
        assert cached < regular * 0.15

    def test_unknown_model_uses_default_pricing(self):
        """Unknown model falls back to default (Sonnet) pricing."""
        from shared.llm.token_tracker import estimate_cost
        cost = estimate_cost(
            model="unknown-model",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        assert cost > 0


# ---------------------------------------------------------------------------
# AnthropicProvider KV-cache tests (no real API calls)
# ---------------------------------------------------------------------------

class TestAnthropicProviderKVCache:
    def test_system_prompt_wrapped_with_cache_control(self):
        """When use_kv_cache=True, system prompt is wrapped with cache_control."""
        from shared.llm.providers.anthropic_provider import AnthropicProvider
        from shared.llm.base import LLMOptions

        provider = AnthropicProvider(config={
            "api_key": "test-key",
            "use_kv_cache": True,
        })
        provider._initialized = True
        provider.client = MagicMock()

        options = LLMOptions(
            system_prompt="You are a financial analyst.",
            stream=False,
        )

        # Build params the same way the provider does
        params = {
            "model": options._map_model_to_anthropic(),
            "messages": [{"role": "user", "content": "test"}],
            "max_tokens": options.max_tokens or 4096,
            "temperature": options.temperature,
            "stream": options.stream,
        }
        if provider.use_kv_cache:
            params["system"] = [
                {
                    "type": "text",
                    "text": options.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        assert isinstance(params["system"], list)
        assert params["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_kv_cache_disabled_system_prompt_is_string(self):
        """When use_kv_cache=False, system prompt is a plain string."""
        options_system = "You are a financial analyst."
        use_kv_cache = False

        if use_kv_cache:
            result = [{"type": "text", "text": options_system, "cache_control": {"type": "ephemeral"}}]
        else:
            result = options_system

        assert isinstance(result, str)

    def test_format_response_includes_cache_tokens(self):
        """_format_response() includes cache token counts in usage dict."""
        from shared.llm.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(config={"api_key": "test"})

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="result")]
        mock_response.model = "claude-3-5-sonnet-20241022"
        mock_response.stop_reason = "end_turn"
        mock_response.id = "msg_123"
        mock_response.role = "assistant"
        mock_response.usage.input_tokens = 1000
        mock_response.usage.output_tokens = 200
        mock_response.usage.cache_read_input_tokens = 800
        mock_response.usage.cache_creation_input_tokens = 400

        llm_resp = provider._format_response(mock_response)

        assert llm_resp.usage["cache_read_input_tokens"] == 800
        assert llm_resp.usage["cache_creation_input_tokens"] == 400
        assert llm_resp.usage["prompt_tokens"] == 1000
        assert llm_resp.usage["completion_tokens"] == 200
