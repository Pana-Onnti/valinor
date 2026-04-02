"""
Pipeline Events — Domain event model and Redis pub/sub helpers.

Provides real-time, per-agent progress tracking for the Valinor analysis
pipeline via Redis pub/sub channels and persistent agent-status hashes.

Usage:
    # Publishing (from orchestrator / task runner)
    await publish_pipeline_event(redis, job_id, PipelineEvent(
        job_id=job_id,
        agent="cartographer",
        status="started",
        message="Mapping business entities...",
    ))

    # Subscribing (from SSE endpoint)
    async for event in subscribe_pipeline_events(redis, job_id):
        yield f"data: {event.model_dump_json()}\\n\\n"
"""

import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
import redis.asyncio as aioredis
import structlog

logger = structlog.get_logger()

# ── Ordered pipeline stages (for progress estimation) ───────────────────────
PIPELINE_STAGES: list[str] = [
    "data_quality_gate",
    "cartographer",
    "query_builder",
    "execute_queries",
    "baseline",
    "analyst",
    "sentinel",
    "hunter",
    "reconciliation",
    "verification",
    "narrators",
    "delivery",
]

# Approximate progress percentage at the *start* of each stage
_STAGE_PROGRESS: dict[str, int] = {
    "data_quality_gate": 5,
    "cartographer": 15,
    "query_builder": 30,
    "execute_queries": 40,
    "baseline": 50,
    "analyst": 55,
    "sentinel": 60,
    "hunter": 65,
    "reconciliation": 70,
    "verification": 75,
    "narrators": 80,
    "delivery": 95,
}

# Redis key helpers
CHANNEL_PREFIX = "pipeline"
AGENT_STATUS_PREFIX = "pipeline"
AGENT_STATUS_TTL = 3600  # 1 hour


def _channel_key(job_id: str) -> str:
    return f"{CHANNEL_PREFIX}:{job_id}:events"


def _agent_status_key(job_id: str) -> str:
    return f"{AGENT_STATUS_PREFIX}:{job_id}:agent_status"


# ── Domain event model ──────────────────────────────────────────────────────

class PipelineEvent(BaseModel):
    """A single pipeline progress event."""

    job_id: str
    agent: str = Field(
        ...,
        description="Pipeline stage/agent name, e.g. 'cartographer', 'analyst'",
    )
    status: Literal["started", "completed", "error"] = Field(
        ...,
        description="Current state of the agent",
    )
    message: str = Field(
        default="",
        description="Human-readable progress message",
    )
    duration_seconds: Optional[float] = Field(
        default=None,
        description="Wall-clock seconds (only on 'completed')",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Arbitrary agent-specific metadata",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    progress: Optional[int] = Field(
        default=None,
        description="Overall pipeline progress 0-100 (auto-calculated if None)",
    )

    def with_progress(self) -> "PipelineEvent":
        """Return a copy with progress auto-filled from stage map."""
        if self.progress is not None:
            return self
        base = _STAGE_PROGRESS.get(self.agent, 0)
        if self.status == "completed":
            # Bump to next stage's start
            idx = PIPELINE_STAGES.index(self.agent) if self.agent in PIPELINE_STAGES else -1
            if idx >= 0 and idx + 1 < len(PIPELINE_STAGES):
                base = _STAGE_PROGRESS.get(PIPELINE_STAGES[idx + 1], base)
            elif self.agent == "delivery":
                base = 100
        return self.model_copy(update={"progress": base})


# ── Pub/Sub helpers ─────────────────────────────────────────────────────────

async def publish_pipeline_event(
    redis_client: aioredis.Redis,
    job_id: str,
    event: PipelineEvent,
) -> None:
    """Publish a pipeline event via Redis pub/sub and persist agent status."""
    enriched = event.with_progress()
    payload = enriched.model_dump_json()

    try:
        # Publish to channel for live subscribers
        await redis_client.publish(_channel_key(job_id), payload)

        # Persist per-agent status in a hash (for reconnect / status endpoint)
        await set_agent_status(redis_client, job_id, enriched)

        logger.debug(
            "pipeline_event_published",
            job_id=job_id,
            agent=enriched.agent,
            status=enriched.status,
        )
    except Exception as exc:
        logger.warning(
            "pipeline_event_publish_failed",
            job_id=job_id,
            agent=enriched.agent,
            error=str(exc),
        )


async def set_agent_status(
    redis_client: aioredis.Redis,
    job_id: str,
    event: PipelineEvent,
) -> None:
    """Persist agent status in a Redis hash for fallback / reconnect."""
    key = _agent_status_key(job_id)
    agent_data = {
        "status": event.status,
        "message": event.message,
        "timestamp": event.timestamp.isoformat(),
    }
    if event.duration_seconds is not None:
        agent_data["duration_seconds"] = str(event.duration_seconds)
    if event.metadata:
        agent_data["metadata"] = json.dumps(event.metadata)
    if event.progress is not None:
        agent_data["progress"] = str(event.progress)

    await redis_client.hset(key, event.agent, json.dumps(agent_data))
    await redis_client.expire(key, AGENT_STATUS_TTL)


async def get_agent_statuses(
    redis_client: aioredis.Redis,
    job_id: str,
) -> List[Dict[str, Any]]:
    """Read all persisted agent statuses for a job (for status endpoint / reconnect)."""
    key = _agent_status_key(job_id)
    raw = await redis_client.hgetall(key)
    if not raw:
        return []

    agents: list[dict[str, Any]] = []
    for agent_name, data_str in raw.items():
        if isinstance(agent_name, bytes):
            agent_name = agent_name.decode()
        if isinstance(data_str, bytes):
            data_str = data_str.decode()
        try:
            data = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            continue
        entry: dict[str, Any] = {
            "agent": agent_name,
            "status": data.get("status", "unknown"),
            "message": data.get("message", ""),
            "timestamp": data.get("timestamp"),
        }
        if "duration_seconds" in data:
            entry["duration_seconds"] = float(data["duration_seconds"])
        if "metadata" in data:
            try:
                entry["metadata"] = json.loads(data["metadata"])
            except (json.JSONDecodeError, TypeError):
                entry["metadata"] = data["metadata"]
        if "progress" in data:
            entry["progress"] = int(data["progress"])
        agents.append(entry)

    # Sort by pipeline stage order
    order = {s: i for i, s in enumerate(PIPELINE_STAGES)}
    agents.sort(key=lambda a: order.get(a["agent"], 999))
    return agents


async def subscribe_pipeline_events(
    redis_client: aioredis.Redis,
    job_id: str,
    timeout: float = 1800,  # 30 minutes max
) -> AsyncIterator[PipelineEvent]:
    """
    Async generator that yields PipelineEvents from Redis pub/sub.

    Terminates when a terminal event (delivery completed, or error on any agent)
    is received, or after *timeout* seconds of inactivity.
    """
    pubsub = redis_client.pubsub()
    channel = _channel_key(job_id)

    try:
        await pubsub.subscribe(channel)

        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=timeout,
            )
            if msg is None:
                # Timeout — no message received
                break

            if msg["type"] != "message":
                continue

            data = msg["data"]
            if isinstance(data, bytes):
                data = data.decode()

            try:
                event = PipelineEvent.model_validate_json(data)
            except Exception:
                logger.warning("pipeline_event_parse_failed", raw=data[:200])
                continue

            yield event

            # Terminal conditions
            if event.agent == "delivery" and event.status == "completed":
                break
            if event.status == "error":
                break

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


async def estimate_remaining_seconds(
    redis_client: aioredis.Redis,
    job_id: str,
) -> Optional[float]:
    """
    Estimate remaining pipeline time based on completed agent durations.

    Uses a simple heuristic: measures elapsed time for completed stages,
    then extrapolates based on remaining stage count.
    """
    agents = await get_agent_statuses(redis_client, job_id)
    if not agents:
        return None

    completed = [a for a in agents if a["status"] == "completed"]
    if not completed:
        return None

    total_duration = sum(a.get("duration_seconds", 0) for a in completed)
    completed_stages = len(completed)
    total_stages = len(PIPELINE_STAGES)
    remaining_stages = total_stages - completed_stages

    if completed_stages == 0:
        return None

    avg_per_stage = total_duration / completed_stages
    return round(avg_per_stage * remaining_stages, 1)
