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

__all__ = [
    "AgentSpec",
    "VerticalConfig",
    "VerticalOutput",
    "AGENT_REGISTRY",
    "get_agent",
    "register_agent",
    "QueryExecutor",
    "run_vertical",
]
