"""
run_vertical — orchestrate a composable vertical pipeline.

Entry point that accepts a VerticalConfig + client context, executes the
configured queries, and runs each agent in sequence. Keeps the existing
swarm pipeline (`valinor.pipeline`) untouched — verticals are a parallel
execution path.

Refs: VAL-130 (L1.a)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Protocol

from valinor.verticals.config import VerticalConfig, VerticalOutput

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Query resolver — pluggable so verticals don't import connectors directly
# ─────────────────────────────────────────────────────────────────────


class QueryExecutor(Protocol):
    """Resolves query identifiers to actual SQL + returns results."""
    async def execute(self, query_name: str, client_config: dict[str, Any]) -> Any: ...


class _StubQueryExecutor:
    """Default when none is provided — returns empty dicts. For testing / demos."""
    async def execute(self, query_name: str, client_config: dict[str, Any]) -> Any:
        logger.debug("stub_query_executor: returning empty dict for %s", query_name)
        return {}


# ─────────────────────────────────────────────────────────────────────
# Default output builders by format
# ─────────────────────────────────────────────────────────────────────


def _digest_output_builder(findings: dict[str, Any]) -> dict[str, Any]:
    """Default builder for 'digest' output_format: flatten single-agent findings."""
    # If there's only one agent, use its output directly as the digest
    if len(findings) == 1:
        [(_, single)] = findings.items()
        return single.get("output", {}) if isinstance(single, dict) else {}
    return {name: f.get("output", {}) for name, f in findings.items()}


_OUTPUT_BUILDERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "digest": _digest_output_builder,
    "raw":    lambda findings: findings,
}


# ─────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────


async def run_vertical(
    config: VerticalConfig,
    client_config: dict[str, Any],
    query_executor: QueryExecutor | None = None,
    extra_context: dict[str, Any] | None = None,
) -> VerticalOutput:
    """
    Execute a vertical pipeline.

    Args:
        config: VerticalConfig — which agents, which queries, output format.
        client_config: per-client dict (must include 'name'; connection string etc. are read by the query executor).
        query_executor: pluggable. Uses _StubQueryExecutor when None (useful for tests).
        extra_context: optional extra keys injected into the per-agent context (e.g. llm_client for tests).

    Returns:
        VerticalOutput with findings, digest, cost, duration, errors.
    """
    t0 = time.monotonic()
    errors: list[str] = []
    executor = query_executor or _StubQueryExecutor()
    extra = extra_context or {}

    # 1. Execute queries
    query_results: dict[str, Any] = {}
    for q in config.queries:
        try:
            query_results[q] = await executor.execute(q, client_config)
        except Exception as exc:
            errors.append(f"query {q}: {type(exc).__name__}: {exc}")
            query_results[q] = None
            logger.warning("run_vertical: query %s failed: %s", q, exc)

    # 2. Build context shared across agents
    context: dict[str, Any] = {
        "client_name": client_config.get("name", "unknown"),
        "client_config": client_config,
        "query_results": query_results,
        "vertical": config.name,
    }
    context.update(extra)

    # 3. Run agents sequentially (vertical is intentionally serial — one agent per vertical is common)
    findings: dict[str, Any] = {}
    for spec in config.agents:
        missing = [k for k in spec.required_inputs if k not in context]
        if missing:
            errors.append(f"agent {spec.name}: missing inputs {missing}")
            logger.warning("run_vertical: agent %s missing inputs %s", spec.name, missing)
            continue
        try:
            result = await spec.runner(context)
            if not isinstance(result, dict):
                result = {"agent": spec.name, "output": result}
            findings[spec.name] = result
            # Make agent output available to downstream agents under its name
            context[spec.name] = result
        except Exception as exc:
            errors.append(f"agent {spec.name}: {type(exc).__name__}: {exc}")
            findings[spec.name] = {"agent": spec.name, "output": {}, "error": str(exc)}
            logger.exception("run_vertical: agent %s raised", spec.name)

    # 4. Build final digest
    builder = config.output_builder or _OUTPUT_BUILDERS.get(
        config.output_format, _digest_output_builder,
    )
    try:
        digest = builder(findings)
    except Exception as exc:
        errors.append(f"output_builder: {type(exc).__name__}: {exc}")
        digest = {"_error": str(exc), "_findings_keys": list(findings)}
        logger.exception("run_vertical: output_builder raised")

    return VerticalOutput(
        vertical=config.name,
        findings=findings,
        digest=digest,
        cost_usd=config.estimated_cost_usd,  # real cost tracking comes later
        duration_seconds=round(time.monotonic() - t0, 3),
        errors=errors,
    )
