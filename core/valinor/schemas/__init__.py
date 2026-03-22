"""
Valinor swarm — type-safe output schemas (VAL-30).

All agent output models live here.  They use Pydantic v2 directly
(pydantic-ai is a dependency but the models can be used standalone).
"""

from .agent_outputs import (
    CartographerOutput,
    QueryBuilderOutput,
    Relationship,
    AnalystOutput,
    SentinelOutput,
)

__all__ = [
    "CartographerOutput",
    "QueryBuilderOutput",
    "Relationship",
    "AnalystOutput",
    "SentinelOutput",
]
