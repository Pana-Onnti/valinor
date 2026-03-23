"""
Agent Observability Layer — VAL-29.

Provides a unified tracing abstraction for all Valinor swarm agents.
Uses lmnr (Laminar) when LMNR_API_KEY is configured, falls back to
a no-op tracer that is safe in development environments without the key.

Usage:
    from shared.observability import observe_agent, get_tracer

    @observe_agent("cartographer")
    async def run_cartographer(client_config, ...):
        ...

    # Manual span (inside an agent function)
    with get_tracer().start_as_current_span("phase1_prescan") as span:
        span.set_attribute("tables_probed", 5)
        ...
"""

import os
import time
import functools
from contextlib import contextmanager
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger()

# ── Laminar / lmnr bootstrap ─────────────────────────────────────────────────

_LMNR_ENABLED: bool = False
_observe_fn: Optional[Callable] = None


def _try_init_lmnr() -> None:
    """
    Attempt to initialize lmnr if LMNR_API_KEY is set.
    If unavailable or key missing, falls back silently.
    """
    global _LMNR_ENABLED, _observe_fn

    api_key = os.getenv("LMNR_API_KEY", "")
    if not api_key:
        logger.info("observability: LMNR_API_KEY not set — using no-op tracer")
        return

    try:
        from lmnr import Laminar, observe

        Laminar.initialize(project_api_key=api_key)
        _observe_fn = observe
        _LMNR_ENABLED = True
        logger.info("observability: lmnr initialized", project_api_key=api_key[:8] + "...")
    except Exception as exc:
        logger.warning("observability: lmnr init failed, using no-op", error=str(exc))


_try_init_lmnr()


# ── No-op fallback tracer ─────────────────────────────────────────────────────

class _NoopSpan:
    """Minimal span-like object for the no-op path."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoopTracer:
    """Minimal OpenTelemetry-compatible tracer for the no-op path."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        yield _NoopSpan()


_noop_tracer = _NoopTracer()


def get_tracer() -> Any:
    """
    Return the active tracer.
    - If lmnr is enabled, returns the lmnr OTel tracer provider's tracer.
    - Otherwise returns a no-op tracer.
    """
    if _LMNR_ENABLED:
        try:
            from lmnr import get_tracer as lmnr_get_tracer
            return lmnr_get_tracer("valinor-swarm")
        except (ImportError, RuntimeError) as exc:
            logger.warning("observability: lmnr get_tracer failed, using no-op", error=str(exc))
    return _noop_tracer


# ── High-level decorator ──────────────────────────────────────────────────────

def _get_current_tenant_id() -> Optional[str]:
    """Extract tenant_id from structlog contextvars (set by TenantMiddleware)."""
    try:
        ctx = structlog.contextvars.get_contextvars()
        return ctx.get("tenant_id")
    except Exception:
        return None


def observe_agent(agent_name: str):
    """
    Decorator that wraps an agent function with observability tracing.

    Works for both sync and async functions.
    Captures:
    - Wall-clock duration
    - Exception if raised
    - agent_name attribute for filtering in lmnr dashboard
    - tenant_id from request context (VAL-21)

    Example:
        @observe_agent("cartographer")
        async def run_cartographer(client_config, ...):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        if _LMNR_ENABLED and _observe_fn is not None:
            # Wrap with lmnr's @observe decorator, adding agent_name
            wrapped = _observe_fn(name=agent_name)(fn)
        else:
            wrapped = fn  # passthrough, manual timing below

        if _LMNR_ENABLED:
            # lmnr handles the rest
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                return await wrapped(*args, **kwargs)

            @functools.wraps(fn)
            def sync_wrapper(*args, **kwargs):
                return wrapped(*args, **kwargs)
        else:
            # No-op: just add structured log timing
            import inspect

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                tenant_id = _get_current_tenant_id()
                start = time.perf_counter()
                try:
                    result = await fn(*args, **kwargs)
                    duration = time.perf_counter() - start
                    logger.info(
                        "agent.finished",
                        agent=agent_name,
                        tenant_id=tenant_id,
                        duration_s=round(duration, 3),
                    )
                    return result
                except Exception as exc:
                    duration = time.perf_counter() - start
                    logger.error(
                        "agent.error",
                        agent=agent_name,
                        tenant_id=tenant_id,
                        duration_s=round(duration, 3),
                        error=str(exc),
                    )
                    raise

            @functools.wraps(fn)
            def sync_wrapper(*args, **kwargs):
                tenant_id = _get_current_tenant_id()
                start = time.perf_counter()
                try:
                    result = fn(*args, **kwargs)
                    duration = time.perf_counter() - start
                    logger.info(
                        "agent.finished",
                        agent=agent_name,
                        tenant_id=tenant_id,
                        duration_s=round(duration, 3),
                    )
                    return result
                except Exception as exc:
                    duration = time.perf_counter() - start
                    logger.error(
                        "agent.error",
                        agent=agent_name,
                        tenant_id=tenant_id,
                        duration_s=round(duration, 3),
                        error=str(exc),
                    )
                    raise

        import inspect as _inspect  # noqa: F811
        if _inspect.iscoroutinefunction(fn):
            return async_wrapper
        return sync_wrapper

    return decorator


def record_token_usage(agent_name: str, input_tokens: int, output_tokens: int) -> None:
    """
    Record LLM token usage for an agent step.

    Emits a structured log line always.
    When lmnr is enabled, attaches the attributes to the active span.
    """
    logger.info(
        "agent.tokens",
        agent=agent_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )

    if _LMNR_ENABLED:
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            span.set_attribute(f"{agent_name}.input_tokens", input_tokens)
            span.set_attribute(f"{agent_name}.output_tokens", output_tokens)
            tenant_id = _get_current_tenant_id()
            if tenant_id:
                span.set_attribute("tenant_id", tenant_id)
        except (ImportError, RuntimeError, AttributeError) as exc:
            logger.warning("observability: failed to record token usage span", error=str(exc))


# ── Agent list (for documentation / dashboards) ───────────────────────────────

SWARM_AGENTS = [
    "data_quality_gate",
    "cartographer",
    "query_evolver",
    "query_builder",
    "analyst",
    "sentinel",
    "hunter",
    "narrator",
]
