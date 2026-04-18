"""
VerticalConfig — schema for a composable per-vertical pipeline.

Refs: VAL-130 (L1.a)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class AgentSpec:
    """One agent in a vertical pipeline."""
    name: str                   # logical name, e.g. "inventory_analyzer"
    runner: Callable[..., Any]  # async callable: run(context) -> dict
    model: str = "haiku"        # "haiku" | "sonnet" | specific model id
    prompt_file: Optional[str] = None   # path under core/valinor/prompts/
    required_inputs: tuple[str, ...] = ()  # keys the agent needs from context

    def __post_init__(self):
        if not callable(self.runner):
            raise TypeError(f"AgentSpec.runner must be callable, got {type(self.runner)}")


@dataclass
class VerticalConfig:
    """
    One vertical pipeline configuration.

    A vertical is run via `run_vertical(config, client_config)`. Agents in
    `agents` are invoked sequentially (in order). Queries listed in `queries`
    are executed before any agent runs; results are placed in the context
    passed to each agent.

    Output format is a plain dict built by agents + an optional post-processing
    hook (`output_builder`) that produces the final digest/report.
    """
    name: str                                    # "inventory", "financial"
    description: str = ""
    agents: list[AgentSpec] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)   # query identifiers (resolved elsewhere)
    output_format: str = "digest"                # "digest" | "ko_report" | "raw"
    output_builder: Optional[Callable[[dict], dict]] = None  # optional post-process
    estimated_cost_usd: float = 0.0              # informational
    estimated_duration_seconds: float = 0.0      # informational


@dataclass
class VerticalOutput:
    """Return value of run_vertical()."""
    vertical: str
    findings: dict[str, Any]     # keyed by agent name
    digest: dict[str, Any]       # final formatted output
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
