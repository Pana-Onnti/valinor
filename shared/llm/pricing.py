"""
Anthropic model pricing — single source of truth.

All prices are per 1M tokens (USD, 2025).
Used by :mod:`shared.llm.token_tracker` and
:mod:`shared.llm.providers.anthropic_provider`.

Refs: VAL-79
"""

from typing import Dict


# ── Anthropic pricing (per 1M tokens, 2025) ──────────────────────────────────

ANTHROPIC_PRICING: Dict[str, Dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,   # slightly more than input
        "cache_read": 0.30,    # ~90% discount
    },
    "claude-opus-4-6": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
    "claude-haiku-4-5": {
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

BATCH_DISCOUNT = 0.5  # 50 % off for Batch API
