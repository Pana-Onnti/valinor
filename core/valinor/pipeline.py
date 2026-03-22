"""
Pipeline — Master orchestrator for Valinor stages.

This module re-exports all pipeline functions from their decomposed modules
to maintain backward compatibility. All public API remains the same.

Modules:
  - pipeline_stages.py         Stages 1.5, 2.5, post-2.5: queries, calibration, baseline, deltas
  - pipeline_reconciliation.py Stage 3.5: swarm conflict detection & resolution
  - pipeline_narrator.py       Stages 3.75, 4: verification-aware prep & narrator orchestration

Key patterns implemented:
  - Deterministic Guard Rail   (gate_calibration — no LLM, cheap SQL assertions)
  - Frozen Brief w/ provenance (compute_baseline — every metric carries its source)
  - Reconciliation Node        (reconcile_swarm — Haiku arbiter on >2x conflicts)
"""

import asyncio
from typing import Any

from valinor.agents.analyst import run_analyst
from valinor.agents.sentinel import run_sentinel
from valinor.agents.hunter import run_hunter
from valinor.knowledge_graph import build_knowledge_graph
from valinor.verification import VerificationEngine

# ── Re-export pipeline stages ──────────────────────────────────────
from valinor.pipeline_stages import (
    execute_queries,
    gate_calibration,
    compute_baseline,
    compute_degradation_level,
    compute_mom_delta,
)

# ── Re-export reconciliation ──────────────────────────────────────
from valinor.pipeline_reconciliation import (
    reconcile_swarm,
    _parse_findings_from_output,
)

# ── Re-export narrator orchestration ──────────────────────────────
from valinor.pipeline_narrator import (
    prepare_narrator_context,
    run_narrators,
)


# ═══════════════════════════════════════════════════════════════
# STAGE 3 — PARALLEL ANALYSIS AGENTS
# ═══════════════════════════════════════════════════════════════

async def run_analysis_agents(
    query_results: dict, entity_map: dict, memory: dict | None, baseline: dict,
    kg: Any = None,
) -> dict:
    """Run Analyst, Sentinel, Hunter in parallel. All receive the frozen brief + KG context."""
    analyst_task  = run_analyst( query_results, entity_map, memory, baseline, kg=kg)
    sentinel_task = run_sentinel(query_results, entity_map, memory, baseline, kg=kg)
    hunter_task   = run_hunter(  query_results, entity_map, memory, baseline, kg=kg)

    raw = await asyncio.gather(analyst_task, sentinel_task, hunter_task, return_exceptions=True)

    findings: dict[str, Any] = {}
    for result in raw:
        if isinstance(result, Exception):
            findings[f"error_{type(result).__name__}"] = {
                "agent": "unknown", "output": str(result), "error": True,
            }
        elif isinstance(result, dict):
            findings[result.get("agent", "unknown")] = result
        else:
            findings["unknown"] = {"agent": "unknown", "output": str(result)}

    return findings


# ── Public API (for wildcard imports) ─────────────────────────────
__all__ = [
    "execute_queries",
    "gate_calibration",
    "compute_baseline",
    "compute_degradation_level",
    "compute_mom_delta",
    "run_analysis_agents",
    "reconcile_swarm",
    "prepare_narrator_context",
    "run_narrators",
]
