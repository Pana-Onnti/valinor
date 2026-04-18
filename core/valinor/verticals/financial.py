"""
Financial vertical — full swarm wired behind the composable registry.

Wraps the existing analyst/sentinel/hunter agents (signature:
query_results, entity_map, memory, baseline, kg) in context-aware adapters
so they can be invoked by the generic `run_vertical` orchestrator.

This is backward-compatible: the existing `pipeline.run_analysis_agents`
keeps working untouched. This module adds a parallel entry point.

Refs: VAL-130 (L1.b)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from valinor.agents.analyst import run_analyst
from valinor.agents.hunter import run_hunter
from valinor.agents.sentinel import run_sentinel
from valinor.verticals.config import AgentSpec, VerticalConfig
from valinor.verticals.registry import register_agent

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Context → legacy signature adapters
# ─────────────────────────────────────────────────────────────────────


def _extract_legacy_inputs(context: dict[str, Any]) -> tuple[dict, dict, Any, dict, Any]:
    """Pull the classic (query_results, entity_map, memory, baseline, kg) tuple from context."""
    return (
        context.get("query_results", {}),
        context.get("entity_map", {}),
        context.get("memory"),
        context.get("baseline", {}),
        context.get("kg"),
    )


async def _analyst_adapter(context: dict[str, Any]) -> dict[str, Any]:
    qr, em, mem, base, kg = _extract_legacy_inputs(context)
    result = await run_analyst(qr, em, mem, base, kg=kg)
    return result if isinstance(result, dict) else {"agent": "analyst", "output": result}


async def _sentinel_adapter(context: dict[str, Any]) -> dict[str, Any]:
    qr, em, mem, base, kg = _extract_legacy_inputs(context)
    result = await run_sentinel(qr, em, mem, base, kg=kg)
    return result if isinstance(result, dict) else {"agent": "sentinel", "output": result}


async def _hunter_adapter(context: dict[str, Any]) -> dict[str, Any]:
    qr, em, mem, base, kg = _extract_legacy_inputs(context)
    result = await run_hunter(qr, em, mem, base, kg=kg)
    return result if isinstance(result, dict) else {"agent": "hunter", "output": result}


# ─────────────────────────────────────────────────────────────────────
# Registry entries
# ─────────────────────────────────────────────────────────────────────


ANALYST_AGENT = register_agent(AgentSpec(
    name="analyst",
    runner=_analyst_adapter,
    model="sonnet",
    required_inputs=("query_results", "entity_map", "baseline"),
))

SENTINEL_AGENT = register_agent(AgentSpec(
    name="sentinel",
    runner=_sentinel_adapter,
    model="sonnet",
    required_inputs=("query_results", "entity_map", "baseline"),
))

HUNTER_AGENT = register_agent(AgentSpec(
    name="hunter",
    runner=_hunter_adapter,
    model="sonnet",
    required_inputs=("query_results", "entity_map", "baseline"),
))


# ─────────────────────────────────────────────────────────────────────
# Parallel-execution meta-agent (matches the current swarm behavior)
# ─────────────────────────────────────────────────────────────────────


async def _swarm_parallel(context: dict[str, Any]) -> dict[str, Any]:
    """
    Run analyst/sentinel/hunter in parallel — mirrors the current
    `pipeline.run_analysis_agents`. Returns a dict of findings keyed by agent.
    """
    analyst, sentinel, hunter = await asyncio.gather(
        _analyst_adapter(context),
        _sentinel_adapter(context),
        _hunter_adapter(context),
        return_exceptions=True,
    )
    findings: dict[str, Any] = {}
    for result in (analyst, sentinel, hunter):
        if isinstance(result, Exception):
            findings[f"error_{type(result).__name__}"] = {
                "agent": "unknown", "output": str(result), "error": True,
            }
        elif isinstance(result, dict):
            findings[result.get("agent", "unknown")] = result
    return {"agent": "financial_swarm", "output": findings}


SWARM_AGENT = register_agent(AgentSpec(
    name="financial_swarm",
    runner=_swarm_parallel,
    model="sonnet",
    required_inputs=("query_results", "entity_map", "baseline"),
))


# ─────────────────────────────────────────────────────────────────────
# Financial vertical config
# ─────────────────────────────────────────────────────────────────────


def _financial_digest_builder(findings: dict[str, Any]) -> dict[str, Any]:
    """Expose the inner swarm findings (flatten the single meta-agent wrapper)."""
    if "financial_swarm" in findings:
        return findings["financial_swarm"].get("output", {})
    return findings


FINANCIAL_VERTICAL = VerticalConfig(
    name="financial",
    description="Full swarm: analyst + sentinel + hunter in parallel (legacy pipeline).",
    agents=[SWARM_AGENT],
    queries=[],  # financial pipeline receives pre-computed query_results via extra_context today
    output_format="digest",
    output_builder=_financial_digest_builder,
    estimated_cost_usd=0.15,
    estimated_duration_seconds=180.0,
)
