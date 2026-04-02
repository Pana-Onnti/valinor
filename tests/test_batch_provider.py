"""
Tests for BatchAnthropicProvider and Batch API integration (VAL-25).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_message(*, custom_id="req-1", text="batch result", model="claude-sonnet-4-6"):
    """Create a mock Anthropic Message for batch results."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.model = model
    msg.stop_reason = "end_turn"
    msg.id = "msg_batch_123"
    msg.role = "assistant"
    msg.usage.input_tokens = 500
    msg.usage.output_tokens = 100
    msg.usage.cache_read_input_tokens = 0
    msg.usage.cache_creation_input_tokens = 0
    return msg


def _make_batch_result_entry(custom_id="req-1", succeeded=True, text="batch result"):
    """Create a mock result entry as returned by batches.results()."""
    entry = MagicMock()
    entry.custom_id = custom_id
    if succeeded:
        entry.result.type = "succeeded"
        entry.result.message = _make_mock_message(custom_id=custom_id, text=text)
    else:
        entry.result.type = "errored"
        entry.result.error = "server_error"
    return entry


# ---------------------------------------------------------------------------
# BatchAnthropicProvider tests
# ---------------------------------------------------------------------------

class TestBatchSubmission:
    """submit_batch() correctly builds and submits batch requests."""

    @pytest.mark.asyncio
    async def test_submit_batch_calls_api(self):
        from shared.llm.providers.batch_provider import (
            BatchAnthropicProvider,
            BatchRequest,
        )

        provider = BatchAnthropicProvider(config={"api_key": "test-key"})
        provider._provider._initialized = True
        provider._provider.client = MagicMock()

        mock_batch = MagicMock()
        mock_batch.id = "batch_abc123"
        mock_batch.processing_status = "in_progress"
        provider._provider.client.messages.batches.create = AsyncMock(
            return_value=mock_batch,
        )

        requests = [
            BatchRequest(custom_id="r1", prompt="Hello"),
            BatchRequest(custom_id="r2", prompt="World"),
        ]

        job = await provider.submit_batch(requests)

        assert job.batch_id == "batch_abc123"
        assert job.total_requests == 2
        assert job.status == "in_progress"

        # Verify API was called with correct structure
        call_kwargs = provider._provider.client.messages.batches.create.call_args
        api_requests = call_kwargs.kwargs["requests"]
        assert len(api_requests) == 2
        assert api_requests[0]["custom_id"] == "r1"
        assert api_requests[0]["params"]["messages"][0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_submit_batch_uses_options(self):
        from shared.llm.providers.batch_provider import (
            BatchAnthropicProvider,
            BatchRequest,
        )
        from shared.llm.base import LLMOptions, ModelType

        provider = BatchAnthropicProvider(config={"api_key": "test-key"})
        provider._provider._initialized = True
        provider._provider.client = MagicMock()

        mock_batch = MagicMock()
        mock_batch.id = "batch_xyz"
        mock_batch.processing_status = "in_progress"
        provider._provider.client.messages.batches.create = AsyncMock(
            return_value=mock_batch,
        )

        opts = LLMOptions(
            model=ModelType.HAIKU,
            temperature=0.2,
            max_tokens=1024,
            system_prompt="Be concise.",
            stream=False,
        )
        requests = [BatchRequest(custom_id="r1", prompt="Test", options=opts)]

        await provider.submit_batch(requests)

        call_kwargs = provider._provider.client.messages.batches.create.call_args
        params = call_kwargs.kwargs["requests"][0]["params"]
        assert params["max_tokens"] == 1024
        assert params["temperature"] == 0.2
        assert params["system"] == "Be concise."


class TestBatchPolling:
    """poll_batch() uses exponential backoff and collects results."""

    @pytest.mark.asyncio
    async def test_poll_waits_until_ended(self):
        from shared.llm.providers.batch_provider import (
            BatchAnthropicProvider,
            BatchJob,
        )

        provider = BatchAnthropicProvider(config={"api_key": "test-key"})
        provider._provider._initialized = True
        provider._provider.client = MagicMock()

        # Simulate: first call → in_progress, second → ended
        batch_in_progress = MagicMock()
        batch_in_progress.processing_status = "in_progress"
        batch_ended = MagicMock()
        batch_ended.processing_status = "ended"

        provider._provider.client.messages.batches.retrieve = AsyncMock(
            side_effect=[batch_in_progress, batch_ended],
        )

        # Mock results collection
        result_entry = _make_batch_result_entry(custom_id="r1")

        async def mock_results(*a, **kw):
            yield result_entry

        provider._provider.client.messages.batches.results = mock_results

        job = BatchJob(batch_id="batch_poll_test", total_requests=1)

        with patch("shared.llm.providers.batch_provider.asyncio.sleep", new_callable=AsyncMock):
            job = await provider.poll_batch(job)

        assert job.status == "ended"
        assert len(job.results) == 1
        assert job.results[0].succeeded is True

    @pytest.mark.asyncio
    async def test_poll_exponential_backoff(self):
        from shared.llm.providers.batch_provider import (
            BatchAnthropicProvider,
            BatchJob,
            _INITIAL_POLL_INTERVAL_S,
            _POLL_BACKOFF_FACTOR,
        )

        provider = BatchAnthropicProvider(config={"api_key": "test-key"})
        provider._provider._initialized = True
        provider._provider.client = MagicMock()

        # Three polls before ended
        statuses = ["in_progress", "in_progress", "in_progress"]
        batch_mocks = []
        for s in statuses:
            m = MagicMock()
            m.processing_status = s
            batch_mocks.append(m)
        ended = MagicMock()
        ended.processing_status = "ended"
        batch_mocks.append(ended)

        provider._provider.client.messages.batches.retrieve = AsyncMock(
            side_effect=batch_mocks,
        )

        async def mock_results(*a, **kw):
            return
            yield  # empty async generator

        provider._provider.client.messages.batches.results = mock_results

        sleep_calls = []
        async def mock_sleep(interval):
            sleep_calls.append(interval)

        job = BatchJob(batch_id="batch_backoff", total_requests=0)

        with patch("shared.llm.providers.batch_provider.asyncio.sleep", side_effect=mock_sleep):
            await provider.poll_batch(job)

        # Expect intervals: 10, 20, 40
        assert sleep_calls[0] == _INITIAL_POLL_INTERVAL_S
        assert sleep_calls[1] == _INITIAL_POLL_INTERVAL_S * _POLL_BACKOFF_FACTOR
        assert sleep_calls[2] == _INITIAL_POLL_INTERVAL_S * _POLL_BACKOFF_FACTOR ** 2


class TestBatchFallback:
    """query_batch() falls back to interactive API on failure."""

    @pytest.mark.asyncio
    async def test_fallback_on_submit_error(self):
        from shared.llm.providers.batch_provider import (
            BatchAnthropicProvider,
            BatchRequest,
        )
        from shared.llm.base import LLMResponse

        provider = BatchAnthropicProvider(config={"api_key": "test-key"})
        provider._provider._initialized = True
        provider._provider.client = MagicMock()

        # Make submit_batch fail
        provider._provider.client.messages.batches.create = AsyncMock(
            side_effect=Exception("batch API unavailable"),
        )

        # Mock the interactive query
        mock_response = LLMResponse(
            content="interactive result",
            model="claude-sonnet-4-6",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        provider._provider.query = AsyncMock(return_value=mock_response)

        requests = [BatchRequest(custom_id="r1", prompt="Test")]
        results = await provider.query_batch(requests, fallback_on_error=True)

        assert len(results) == 1
        assert results[0].succeeded is True
        assert results[0].response.content == "interactive result"
        assert results[0].custom_id == "r1"

    @pytest.mark.asyncio
    async def test_no_fallback_raises(self):
        from shared.llm.providers.batch_provider import (
            BatchAnthropicProvider,
            BatchRequest,
        )

        provider = BatchAnthropicProvider(config={"api_key": "test-key"})
        provider._provider._initialized = True
        provider._provider.client = MagicMock()

        provider._provider.client.messages.batches.create = AsyncMock(
            side_effect=Exception("boom"),
        )

        requests = [BatchRequest(custom_id="r1", prompt="Test")]

        with pytest.raises(Exception, match="boom"):
            await provider.query_batch(requests, fallback_on_error=False)


class TestBatchCostCalculation:
    """Batch API applies 50 % discount to token costs."""

    def test_batch_discount_on_estimate_cost(self):
        from shared.llm.token_tracker import estimate_cost

        regular = estimate_cost(
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        batch = estimate_cost(
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
            is_batch=True,
        )
        # Batch should be exactly 50 % of regular
        assert abs(batch - regular * 0.5) < 1e-6

    def test_batch_discount_on_output_tokens(self):
        from shared.llm.token_tracker import estimate_cost

        regular = estimate_cost(
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=1_000_000,
        )
        batch = estimate_cost(
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=1_000_000,
            is_batch=True,
        )
        assert abs(batch - regular * 0.5) < 1e-6

    def test_batch_discount_full_cost(self):
        """Combined input + output with batch discount."""
        from shared.llm.token_tracker import estimate_cost

        regular = estimate_cost(
            model="claude-sonnet-4-6",
            input_tokens=500_000,
            output_tokens=200_000,
        )
        batch = estimate_cost(
            model="claude-sonnet-4-6",
            input_tokens=500_000,
            output_tokens=200_000,
            is_batch=True,
        )
        assert abs(batch - regular * 0.5) < 1e-6


class TestBatchTokenTracker:
    """TokenTracker.record() honours the is_batch flag."""

    def setup_method(self):
        from shared.llm.token_tracker import TokenTracker
        TokenTracker.get_instance().reset()

    def test_record_with_batch_flag(self):
        from shared.llm.token_tracker import TokenTracker

        tracker = TokenTracker.get_instance()
        cost = tracker.record(
            agent="batch_agent",
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
            is_batch=True,
        )
        # 1M input @ $3/M * 0.5 = $1.50
        assert abs(cost - 1.50) < 0.01

    def test_record_without_batch_flag_unchanged(self):
        from shared.llm.token_tracker import TokenTracker

        tracker = TokenTracker.get_instance()
        cost = tracker.record(
            agent="interactive_agent",
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
            is_batch=False,
        )
        # 1M input @ $3/M = $3.00
        assert abs(cost - 3.00) < 0.01


class TestBatchQueryBatchEndToEnd:
    """End-to-end query_batch flow with mocked API."""

    @pytest.mark.asyncio
    async def test_query_batch_success(self):
        from shared.llm.providers.batch_provider import (
            BatchAnthropicProvider,
            BatchRequest,
        )

        provider = BatchAnthropicProvider(config={"api_key": "test-key"})
        provider._provider._initialized = True
        provider._provider.client = MagicMock()

        # Mock submit
        mock_batch = MagicMock()
        mock_batch.id = "batch_e2e"
        mock_batch.processing_status = "in_progress"
        provider._provider.client.messages.batches.create = AsyncMock(
            return_value=mock_batch,
        )

        # Mock poll — immediately ended
        ended = MagicMock()
        ended.processing_status = "ended"
        provider._provider.client.messages.batches.retrieve = AsyncMock(
            return_value=ended,
        )

        # Mock results
        entries = [
            _make_batch_result_entry("r1", True, "answer 1"),
            _make_batch_result_entry("r2", True, "answer 2"),
            _make_batch_result_entry("r3", False),
        ]

        async def mock_results(*a, **kw):
            for e in entries:
                yield e

        provider._provider.client.messages.batches.results = mock_results

        requests = [
            BatchRequest(custom_id="r1", prompt="Q1"),
            BatchRequest(custom_id="r2", prompt="Q2"),
            BatchRequest(custom_id="r3", prompt="Q3"),
        ]

        results = await provider.query_batch(requests)

        assert len(results) == 3
        assert results[0].succeeded is True
        assert results[0].custom_id == "r1"
        assert results[1].succeeded is True
        assert results[2].succeeded is False
        assert results[2].error is not None


class TestGetBatchProvider:
    """factory.get_batch_provider() honours env var."""

    def test_returns_none_when_disabled(self):
        with patch.dict("os.environ", {"ENABLE_BATCH_API": ""}, clear=False):
            from shared.llm.factory import get_batch_provider
            assert get_batch_provider() is None

    def test_returns_provider_when_enabled(self):
        with patch.dict("os.environ", {"ENABLE_BATCH_API": "true"}, clear=False):
            from shared.llm.factory import get_batch_provider
            from shared.llm.providers.batch_provider import BatchAnthropicProvider
            provider = get_batch_provider()
            assert isinstance(provider, BatchAnthropicProvider)

    def test_returns_provider_when_flag_is_1(self):
        with patch.dict("os.environ", {"ENABLE_BATCH_API": "1"}, clear=False):
            from shared.llm.factory import get_batch_provider
            assert get_batch_provider() is not None
