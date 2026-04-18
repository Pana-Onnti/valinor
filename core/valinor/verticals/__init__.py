"""
Verticals — Composable pipelines per business vertical.

A "vertical" is a reusable pipeline config: which agents run, what queries they
need, and what output shape they produce. Examples:

  - inventory: 1 Haiku agent, ~$0.002/run, ~10s. Inputs: stock + sales queries.
  - financial: full swarm (analyst/sentinel/hunter + 4 narrators), ~$0.15/run.

This module does NOT replace the existing swarm pipeline. It adds a
configuration layer on top so a client can opt into lighter pipelines
for specific verticals without running the full financial swarm.

Refs: VAL-130 (L1.a)
"""

from valinor.verticals.config import AgentSpec, VerticalConfig, VerticalOutput
from valinor.verticals.registry import AGENT_REGISTRY, get_agent, register_agent
from valinor.verticals.runner import QueryExecutor, run_vertical

# Import built-in verticals at package load time so they register in AGENT_REGISTRY.
# `financial` depends on claude_agent_sdk (stubbed in tests, real in production).
# Skip it silently when the SDK isn't installed so the inventory vertical keeps working.
from valinor.verticals.inventory import INVENTORY_VERTICAL  # noqa: F401

BUILTIN_VERTICALS: dict[str, VerticalConfig] = {
    "inventory": INVENTORY_VERTICAL,
}

try:
    from valinor.verticals.financial import FINANCIAL_VERTICAL  # noqa: F401
    BUILTIN_VERTICALS["financial"] = FINANCIAL_VERTICAL
except ImportError:
    FINANCIAL_VERTICAL = None  # type: ignore[assignment]


def get_vertical(name: str) -> VerticalConfig:
    """Look up a built-in vertical by name."""
    if name not in BUILTIN_VERTICALS:
        raise KeyError(f"Unknown vertical '{name}'. Known: {sorted(BUILTIN_VERTICALS)}")
    return BUILTIN_VERTICALS[name]


__all__ = [
    "AgentSpec",
    "VerticalConfig",
    "VerticalOutput",
    "AGENT_REGISTRY",
    "BUILTIN_VERTICALS",
    "get_agent",
    "get_vertical",
    "register_agent",
    "QueryExecutor",
    "run_vertical",
    "INVENTORY_VERTICAL",
    "FINANCIAL_VERTICAL",
]
