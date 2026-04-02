"""
Playground Swarm — Base agent abstractions.

Defines the abstract PlaygroundAgent, shared context, and result types
used by every concrete agent in the swarm.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List
import asyncio
import logging
import json
from datetime import datetime


@dataclass
class DatasetRecord:
    """Metadata for a generated dataset."""

    name: str
    path: str  # path to .db file
    source_agent: str
    tier: str
    created_at: str
    row_counts: Dict[str, int]  # table_name -> row_count
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlaygroundContext:
    """Shared context for all playground agents."""

    datasets_dir: Path
    reports_dir: Path
    api_base_url: str
    db_config: Dict[str, Any]
    generated_datasets: asyncio.Queue  # type: ignore[type-arg]
    stop_event: asyncio.Event
    logger: logging.Logger


class AgentResult:
    """Outcome of a single agent cycle."""

    def __init__(
        self,
        agent_name: str,
        success: bool,
        datasets: Optional[List[DatasetRecord]] = None,
        errors: Optional[List[str]] = None,
        stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.agent_name = agent_name
        self.success = success
        self.datasets: List[DatasetRecord] = datasets or []
        self.errors: List[str] = errors or []
        self.stats: Dict[str, Any] = stats or {}
        self.timestamp: str = datetime.utcnow().isoformat()


class PlaygroundAgent(ABC):
    """Base class for all playground agents."""

    name: str = "unnamed"
    tier: str = "unknown"  # hunter | generator | bootstrapper | tester

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"playground.{self.name}")
        self._datasets_produced: int = 0

    @abstractmethod
    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        """Execute one cycle. Returns result with generated datasets."""
        ...

    async def run_continuous(self, ctx: PlaygroundContext) -> None:
        """For testers: infinite loop with backoff. Override *interval* in subclass."""
        interval: int = getattr(self, "interval", 60)
        while not ctx.stop_event.is_set():
            try:
                result = await self.run(ctx)
                if result.datasets:
                    for ds in result.datasets:
                        await ctx.generated_datasets.put(ds)
                if not result.success:
                    self.logger.warning("Cycle failed: %s", result.errors)
            except Exception as exc:
                self.logger.error("Error in continuous loop: %s", exc)
            try:
                await asyncio.wait_for(ctx.stop_event.wait(), timeout=interval)
                break  # stop_event was set
            except asyncio.TimeoutError:
                pass  # continue loop

    def _save_report(
        self, ctx: PlaygroundContext, data: Dict[str, Any], prefix: str
    ) -> Path:
        """Save a JSON report to the reports directory."""
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        path = ctx.reports_dir / f"{prefix}_{ts}.json"
        path.write_text(json.dumps(data, indent=2, default=str))
        return path
