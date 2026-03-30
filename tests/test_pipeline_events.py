"""
Tests for shared/events/pipeline_events.py — Redis pub/sub pipeline events.

Covers:
  - PipelineEvent model creation and progress auto-fill
  - publish / subscribe round-trip via Redis pub/sub
  - Agent status persistence and retrieval
  - Late subscriber reconnection (snapshot from hash)
  - SSE endpoint integration with mock events
  - Remaining time estimation

Refs: VAL-105
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
for _p in (str(ROOT / "core"), str(ROOT / "shared"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Force-load the real module (avoid pollution from test_api_endpoints stubs)
import importlib
_events_path = ROOT / "shared" / "events" / "pipeline_events.py"
_spec = importlib.util.spec_from_file_location("shared.events.pipeline_events", str(_events_path))
_real_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_real_module)

PIPELINE_STAGES = _real_module.PIPELINE_STAGES
PipelineEvent = _real_module.PipelineEvent
_agent_status_key = _real_module._agent_status_key
_channel_key = _real_module._channel_key
estimate_remaining_seconds = _real_module.estimate_remaining_seconds
get_agent_statuses = _real_module.get_agent_statuses
publish_pipeline_event = _real_module.publish_pipeline_event
set_agent_status = _real_module.set_agent_status
subscribe_pipeline_events = _real_module.subscribe_pipeline_events


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_event(
    job_id: str = "test-job-1",
    agent: str = "cartographer",
    status: str = "started",
    message: str = "Mapping entities...",
    duration_seconds: float | None = None,
    metadata: dict | None = None,
) -> PipelineEvent:
    return PipelineEvent(
        job_id=job_id,
        agent=agent,
        status=status,
        message=message,
        duration_seconds=duration_seconds,
        metadata=metadata,
    )


class FakeRedis:
    """Minimal async Redis mock that supports pub/sub and hashes."""

    def __init__(self):
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._channels: Dict[str, List[AsyncMock]] = {}
        self._published: List[tuple] = []  # (channel, data)
        self._expiry: Dict[str, int] = {}

    async def publish(self, channel: str, data: str) -> int:
        self._published.append((channel, data))
        # Deliver to subscribed pubsubs
        for ps in self._channels.get(channel, []):
            await ps._messages.put({
                "type": "message",
                "channel": channel,
                "data": data.encode() if isinstance(data, str) else data,
            })
        return len(self._channels.get(channel, []))

    async def hset(self, key: str, field: str = None, value: str = None, mapping: Dict[str, str] = None) -> int:
        if key not in self._hashes:
            self._hashes[key] = {}
        if mapping:
            for k, v in mapping.items():
                self._hashes[key][k] = str(v) if v is not None else ""
            return len(mapping)
        if field is not None:
            self._hashes[key][field] = value
        return 1

    async def hgetall(self, key: str) -> Dict[str, str]:
        return dict(self._hashes.get(key, {}))

    async def expire(self, key: str, ttl: int) -> bool:
        self._expiry[key] = ttl
        return True

    def pubsub(self):
        return FakePubSub(self)


class FakePubSub:
    """Minimal async pubsub mock with proper async waiting."""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._subscribed: List[str] = []
        self._messages: asyncio.Queue = asyncio.Queue()

    async def subscribe(self, channel: str):
        self._subscribed.append(channel)
        if channel not in self._redis._channels:
            self._redis._channels[channel] = []
        self._redis._channels[channel].append(self)

    async def unsubscribe(self, channel: str):
        if channel in self._subscribed:
            self._subscribed.remove(channel)
        if channel in self._redis._channels:
            self._redis._channels[channel] = [
                ps for ps in self._redis._channels[channel] if ps is not self
            ]

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 1.0):
        try:
            return await asyncio.wait_for(self._messages.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def aclose(self):
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineEventModel:
    """Tests for the PipelineEvent Pydantic model."""

    def test_basic_creation(self):
        event = _make_event()
        assert event.job_id == "test-job-1"
        assert event.agent == "cartographer"
        assert event.status == "started"
        assert event.timestamp is not None

    def test_with_progress_auto_fill_started(self):
        event = _make_event(agent="cartographer", status="started")
        enriched = event.with_progress()
        assert enriched.progress == 15  # cartographer starts at 15%

    def test_with_progress_auto_fill_completed(self):
        event = _make_event(agent="cartographer", status="completed")
        enriched = event.with_progress()
        # Should jump to next stage's start (query_builder = 30%)
        assert enriched.progress == 30

    def test_with_progress_delivery_completed(self):
        event = _make_event(agent="delivery", status="completed")
        enriched = event.with_progress()
        assert enriched.progress == 100

    def test_with_progress_preserves_explicit(self):
        event = _make_event(agent="cartographer", status="started")
        event = event.model_copy(update={"progress": 42})
        enriched = event.with_progress()
        assert enriched.progress == 42  # not overwritten

    def test_serialization_round_trip(self):
        event = _make_event(
            duration_seconds=3.14,
            metadata={"entities_found": 47},
        )
        json_str = event.model_dump_json()
        restored = PipelineEvent.model_validate_json(json_str)
        assert restored.agent == event.agent
        assert restored.duration_seconds == 3.14
        assert restored.metadata == {"entities_found": 47}

    def test_all_pipeline_stages_have_progress(self):
        """Every stage in PIPELINE_STAGES should have a progress entry."""
        _STAGE_PROGRESS = _real_module._STAGE_PROGRESS
        for stage in PIPELINE_STAGES:
            assert stage in _STAGE_PROGRESS, f"Missing progress for {stage}"


class TestRedisHelpers:
    """Tests for publish, set/get agent status."""

    @pytest.mark.asyncio
    async def test_publish_pipeline_event(self):
        redis = FakeRedis()
        event = _make_event()
        await publish_pipeline_event(redis, "job-1", event)

        # Should have published to channel
        assert len(redis._published) == 1
        channel, data = redis._published[0]
        assert channel == _channel_key("job-1")
        parsed = json.loads(data)
        assert parsed["agent"] == "cartographer"

        # Should have persisted in hash
        agent_hash = redis._hashes.get(_agent_status_key("job-1"), {})
        assert "cartographer" in agent_hash

    @pytest.mark.asyncio
    async def test_set_and_get_agent_statuses(self):
        redis = FakeRedis()

        events = [
            _make_event(agent="data_quality_gate", status="completed", duration_seconds=1.2),
            _make_event(agent="cartographer", status="started"),
        ]
        for e in events:
            await set_agent_status(redis, "job-1", e)

        statuses = await get_agent_statuses(redis, "job-1")
        assert len(statuses) == 2

        # Should be sorted by pipeline order
        assert statuses[0]["agent"] == "data_quality_gate"
        assert statuses[1]["agent"] == "cartographer"
        assert statuses[0]["duration_seconds"] == 1.2

    @pytest.mark.asyncio
    async def test_get_agent_statuses_empty(self):
        redis = FakeRedis()
        statuses = await get_agent_statuses(redis, "nonexistent-job")
        assert statuses == []

    @pytest.mark.asyncio
    async def test_agent_status_with_metadata(self):
        redis = FakeRedis()
        event = _make_event(
            agent="cartographer",
            status="completed",
            metadata={"entities_found": 47, "tables_scanned": 12},
        )
        await set_agent_status(redis, "job-1", event)

        statuses = await get_agent_statuses(redis, "job-1")
        assert len(statuses) == 1
        assert statuses[0]["metadata"]["entities_found"] == 47


class TestSubscribePipelineEvents:
    """Tests for the pub/sub subscription async generator."""

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        redis = FakeRedis()

        # Pre-publish an event (simulating it arrives after subscribe)
        event = _make_event(agent="cartographer", status="started")
        enriched = event.with_progress()

        # We need to publish after subscribing, so use a task
        received = []

        async def collect():
            async for evt in subscribe_pipeline_events(redis, "job-1", timeout=0.5):
                received.append(evt)

        # Publish event after a tiny delay
        async def publish_delayed():
            await asyncio.sleep(0.05)
            await redis.publish(
                _channel_key("job-1"),
                enriched.model_dump_json(),
            )
            # Then publish terminal
            await asyncio.sleep(0.05)
            terminal = _make_event(agent="delivery", status="completed").with_progress()
            await redis.publish(
                _channel_key("job-1"),
                terminal.model_dump_json(),
            )

        await asyncio.gather(collect(), publish_delayed())

        assert len(received) == 2
        assert received[0].agent == "cartographer"
        assert received[1].agent == "delivery"

    @pytest.mark.asyncio
    async def test_subscribe_terminates_on_error(self):
        redis = FakeRedis()
        received = []

        async def collect():
            async for evt in subscribe_pipeline_events(redis, "job-1", timeout=0.5):
                received.append(evt)

        async def publish_error():
            await asyncio.sleep(0.05)
            error_event = _make_event(agent="analyst", status="error", message="LLM timeout")
            await redis.publish(
                _channel_key("job-1"),
                error_event.with_progress().model_dump_json(),
            )

        await asyncio.gather(collect(), publish_error())

        assert len(received) == 1
        assert received[0].status == "error"

    @pytest.mark.asyncio
    async def test_subscribe_timeout_no_messages(self):
        redis = FakeRedis()
        received = []

        async for evt in subscribe_pipeline_events(redis, "job-1", timeout=0.1):
            received.append(evt)

        assert received == []


class TestEstimateRemainingSeconds:
    """Tests for the remaining time estimator."""

    @pytest.mark.asyncio
    async def test_estimate_with_completed_stages(self):
        redis = FakeRedis()

        # Simulate 3 completed stages averaging 10s each
        for agent in ["data_quality_gate", "cartographer", "query_builder"]:
            event = _make_event(agent=agent, status="completed", duration_seconds=10.0)
            await set_agent_status(redis, "job-1", event)

        remaining = await estimate_remaining_seconds(redis, "job-1")
        assert remaining is not None
        # 3 completed, 9 remaining, avg 10s = 90s
        assert remaining == 90.0

    @pytest.mark.asyncio
    async def test_estimate_no_data(self):
        redis = FakeRedis()
        remaining = await estimate_remaining_seconds(redis, "nonexistent")
        assert remaining is None

    @pytest.mark.asyncio
    async def test_estimate_no_completed(self):
        redis = FakeRedis()
        event = _make_event(agent="cartographer", status="started")
        await set_agent_status(redis, "job-1", event)

        remaining = await estimate_remaining_seconds(redis, "job-1")
        assert remaining is None


class TestChannelKeys:
    """Test Redis key generation."""

    def test_channel_key(self):
        assert _channel_key("abc-123") == "pipeline:abc-123:events"

    def test_agent_status_key(self):
        assert _agent_status_key("abc-123") == "pipeline:abc-123:agent_status"


class TestProgressCallbackIntegration:
    """Test that the task progress_callback emits events correctly."""

    @pytest.mark.asyncio
    async def test_progress_callback_emits_started_event(self):
        """
        Verify that the first call to progress_callback for a stage emits a started event.

        Since api.tasks may be loaded with stubbed shared.events.pipeline_events
        (from test_api_endpoints), we patch the task module's publish function
        with the real one from our force-loaded module.
        """
        # api.tasks imports adapters.valinor_adapter which requires heavy deps.
        api_path = str(ROOT / "api")
        if api_path not in sys.path:
            sys.path.insert(0, api_path)

        # Stub the heavy adapter import
        if "adapters" not in sys.modules:
            sys.modules["adapters"] = types.ModuleType("adapters")
        if "adapters.valinor_adapter" not in sys.modules:
            _adapter_mod = types.ModuleType("adapters.valinor_adapter")
            _adapter_mod.ValinorAdapter = MagicMock  # type: ignore
            sys.modules["adapters.valinor_adapter"] = _adapter_mod

        import api.tasks as tasks_module

        fake_redis = FakeRedis()

        # Patch with real functions from our force-loaded module
        real_publish = _real_module.publish_pipeline_event
        real_stage_progress = _real_module._STAGE_PROGRESS

        with patch.object(tasks_module, "get_redis", return_value=fake_redis), \
             patch.object(tasks_module, "publish_pipeline_event", real_publish), \
             patch.object(tasks_module, "PipelineEvent", _real_module.PipelineEvent):
            # Clean state
            tasks_module._agent_start_times.clear()

            await tasks_module.progress_callback("test-job", "cartographer", 15, "Mapping...")

            # Should have published at least one event
            assert len(fake_redis._published) >= 1
            channel, data = fake_redis._published[0]
            parsed = json.loads(data)
            assert parsed["agent"] == "cartographer"
            assert parsed["status"] == "started"

            # Clean up
            tasks_module._agent_start_times.clear()
