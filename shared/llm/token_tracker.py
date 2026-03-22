"""
Token Tracker — VAL-31.

Accumulates LLM token usage per agent and exposes Prometheus metrics.
Tracks regular input/output tokens and Anthropic KV-cache hits/writes.

Usage:
    from shared.llm.token_tracker import TokenTracker

    tracker = TokenTracker.get_instance()
    tracker.record(
        agent="analyst",
        model="claude-3-5-sonnet-20241022",
        input_tokens=1500,
        output_tokens=300,
        cache_read_tokens=1200,   # from usage.cache_read_input_tokens
        cache_creation_tokens=800, # from usage.cache_creation_input_tokens
    )

    # Snapshot for logging / dashboard
    summary = tracker.get_summary()
"""

import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()

# ── Prometheus metrics (optional) ────────────────────────────────────────────

_PROMETHEUS_AVAILABLE = False
_tokens_total = None
_cache_read_total = None
_cache_creation_total = None
_cost_usd_total = None

if os.getenv("ENABLE_TOKEN_TRACKING", "true").lower() in ("true", "1", "yes"):
    try:
        from prometheus_client import Counter

        _tokens_total = Counter(
            "valinor_analysis_tokens_total",
            "Total LLM tokens processed",
            ["agent", "model", "token_type"],
        )
        _cost_usd_total = Counter(
            "valinor_analysis_cost_usd_total",
            "Estimated LLM cost in USD",
            ["agent", "model"],
        )
        _PROMETHEUS_AVAILABLE = True
        logger.info("token_tracker: Prometheus metrics registered")
    except Exception as exc:
        logger.warning("token_tracker: Prometheus unavailable", error=str(exc))


# ── Anthropic pricing (per 1M tokens, 2025) ──────────────────────────────────

ANTHROPIC_PRICING: Dict[str, Dict[str, float]] = {
    "claude-3-5-sonnet-20241022": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,   # slightly more than input
        "cache_read": 0.30,    # ~90% discount
    },
    "claude-3-opus-20240229": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
    "claude-3-haiku-20240307": {
        "input": 0.25,
        "output": 1.25,
        "cache_write": 0.30,
        "cache_read": 0.03,
    },
    "default": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
}


BATCH_DISCOUNT = 0.5  # 50 % off input tokens for Batch API


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    is_batch: bool = False,
) -> float:
    """Estimate USD cost for a single LLM call.

    When *is_batch* is ``True`` the Anthropic Batch API 50 % discount is
    applied to input and output token pricing.
    """
    pricing = ANTHROPIC_PRICING.get(model, ANTHROPIC_PRICING["default"])
    discount = BATCH_DISCOUNT if is_batch else 1.0
    cost = (
        (input_tokens / 1_000_000) * pricing["input"] * discount
        + (output_tokens / 1_000_000) * pricing["output"] * discount
        + (cache_read_tokens / 1_000_000) * pricing["cache_read"] * discount
        + (cache_creation_tokens / 1_000_000) * pricing["cache_write"] * discount
    )
    return round(cost, 8)


# ── Per-agent accumulator ─────────────────────────────────────────────────────

@dataclass
class AgentTokenStats:
    """Accumulated token stats for one agent."""
    agent: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    call_count: int = 0
    total_cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens served from cache (0–1)."""
        denom = self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens
        if denom == 0:
            return 0.0
        return round(self.cache_read_tokens / denom, 4)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "total_tokens": self.total_tokens,
            "call_count": self.call_count,
            "cache_hit_rate": self.cache_hit_rate,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


# ── Singleton tracker ─────────────────────────────────────────────────────────

class TokenTracker:
    """
    Thread-safe singleton accumulator for LLM token usage across agents.

    In production, metrics are also emitted to Prometheus counters.
    The in-memory state is useful for per-analysis cost reports.
    """

    _instance: Optional["TokenTracker"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._stats: Dict[str, AgentTokenStats] = defaultdict(
            lambda: AgentTokenStats(agent="unknown")
        )
        self._global_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "TokenTracker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def record(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        is_batch: bool = False,
    ) -> float:
        """
        Record token usage for one LLM call.

        When *is_batch* is ``True`` the 50 % Batch API discount is applied.

        Returns the estimated USD cost for this call.
        """
        cost = estimate_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            is_batch=is_batch,
        )

        with self._global_lock:
            if agent not in self._stats:
                self._stats[agent] = AgentTokenStats(agent=agent)
            s = self._stats[agent]
            s.input_tokens += input_tokens
            s.output_tokens += output_tokens
            s.cache_read_tokens += cache_read_tokens
            s.cache_creation_tokens += cache_creation_tokens
            s.call_count += 1
            s.total_cost_usd += cost

        # Emit to Prometheus
        if _PROMETHEUS_AVAILABLE and _tokens_total is not None:
            try:
                _tokens_total.labels(agent=agent, model=model, token_type="input").inc(input_tokens)
                _tokens_total.labels(agent=agent, model=model, token_type="output").inc(output_tokens)
                if cache_read_tokens:
                    _tokens_total.labels(agent=agent, model=model, token_type="cache_read").inc(cache_read_tokens)
                if cache_creation_tokens:
                    _tokens_total.labels(agent=agent, model=model, token_type="cache_creation").inc(cache_creation_tokens)
                _cost_usd_total.labels(agent=agent, model=model).inc(cost)
            except Exception as exc:
                logger.warning("token_tracker: prometheus emit failed", error=str(exc))

        logger.info(
            "token.recorded",
            agent=agent,
            model=model,
            input=input_tokens,
            output=output_tokens,
            cache_read=cache_read_tokens,
            cache_write=cache_creation_tokens,
            cost_usd=cost,
        )
        return cost

    def get_stats(self, agent: str) -> AgentTokenStats:
        """Get accumulated stats for a specific agent."""
        with self._global_lock:
            return self._stats.get(agent, AgentTokenStats(agent=agent))

    def get_summary(self) -> Dict[str, dict]:
        """Return a snapshot of all agent stats."""
        with self._global_lock:
            return {name: s.to_dict() for name, s in self._stats.items()}

    def get_total_cost_usd(self) -> float:
        """Sum of all agent costs."""
        with self._global_lock:
            return round(sum(s.total_cost_usd for s in self._stats.values()), 6)

    def reset(self) -> None:
        """Reset all accumulated stats (useful for per-analysis tracking)."""
        with self._global_lock:
            self._stats.clear()
