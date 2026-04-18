"""
AGENT_REGISTRY — name -> AgentSpec lookup for vertical configs.

Agents register themselves (or are registered at import time). A vertical
config references agents by name so configs can be serialized or overridden
per client without pulling in agent runners.

Refs: VAL-130 (L1.a)
"""

from __future__ import annotations

from typing import Dict

from valinor.verticals.config import AgentSpec

AGENT_REGISTRY: Dict[str, AgentSpec] = {}


def register_agent(spec: AgentSpec) -> AgentSpec:
    """Register an AgentSpec under its name. Overwrites on duplicate."""
    AGENT_REGISTRY[spec.name] = spec
    return spec


def get_agent(name: str) -> AgentSpec:
    """Look up an agent by name. Raises KeyError if unknown."""
    if name not in AGENT_REGISTRY:
        available = sorted(AGENT_REGISTRY)
        raise KeyError(f"Unknown agent '{name}'. Registered: {available}")
    return AGENT_REGISTRY[name]
