"""
Centralized test configuration and shared fixtures for Valinor SaaS.

Provides:
  - sys.path setup for core/, shared/, and project root
  - claude_agent_sdk stub (avoids import errors in test environment)
  - structlog stub (for tests that don't need real structured logging)
  - Common entity_map fixtures (Gloria-like and generic)
  - Shared mock helpers (MagicMock-based client configs, baselines)
  - Async run helper

Refs: VAL-54
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ── sys.path setup ────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
for _p in (str(ROOT / "core"), str(ROOT / "shared"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── claude_agent_sdk stub ─────────────────────────────────────────────────────
# Many core modules import from claude_agent_sdk at module level.
# In test environments the real SDK is not installed, so we stub it.

if "claude_agent_sdk" not in sys.modules:
    _sdk = types.ModuleType("claude_agent_sdk")
    _sdk.__spec__ = None

    def _tool_stub(*args, **kwargs):
        """Passthrough decorator: @tool or @tool(...)."""
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f

    async def _query_stub(*args, **kwargs):
        """Async generator that yields nothing (no SDK in tests)."""
        return
        yield  # make it an async generator

    class _ClaudeAgentOptions:
        def __init__(self, model="sonnet", system_prompt="", max_turns=20, **kwargs):
            self.model = model
            self.system_prompt = system_prompt
            self.max_turns = max_turns

    class _TextBlock:
        def __init__(self, text: str = ""):
            self.text = text

    class _AssistantMessage:
        def __init__(self, content=None):
            self.content = content or []

    _sdk.tool = _tool_stub
    _sdk.query = _query_stub
    _sdk.ClaudeAgentOptions = _ClaudeAgentOptions
    _sdk.AssistantMessage = _AssistantMessage
    _sdk.TextBlock = _TextBlock
    _sdk.create_sdk_mcp_server = MagicMock(return_value=MagicMock())
    sys.modules["claude_agent_sdk"] = _sdk


# ── structlog ─────────────────────────────────────────────────────────────────
# Import the real module so submodules (contextvars, stdlib, processors, dev)
# are available when api/logging_config.py calls setup_logging().
import structlog  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════════
# SHARED FIXTURES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def gloria_entity_map():
    """Entity map matching the real Gloria Openbravo schema.
    Re-usable across knowledge_graph, verification, pipeline, and calibration tests.
    """
    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "type": "TRANSACTIONAL",
                "row_count": 4117,
                "confidence": 0.99,
                "key_columns": {
                    "pk": "c_invoice_id",
                    "invoice_date": "dateinvoiced",
                    "amount_col": "grandtotal",
                    "customer_fk": "c_bpartner_id",
                },
                "base_filter": "issotrx='Y' AND docstatus='CO' AND isactive='Y'",
                "probed_values": {
                    "issotrx": {"Y": 2366, "N": 1751},
                    "docstatus": {"CO": 4108, "DR": 9},
                    "isactive": {"Y": 4117},
                },
            },
            "customers": {
                "table": "c_bpartner",
                "type": "MASTER",
                "row_count": 88,
                "confidence": 0.98,
                "key_columns": {
                    "pk": "c_bpartner_id",
                    "customer_name": "name",
                },
                "base_filter": "iscustomer='Y' AND isactive='Y'",
                "probed_values": {
                    "iscustomer": {"Y": 49, "N": 39},
                    "isactive": {"Y": 81, "N": 7},
                },
            },
            "payment_schedule": {
                "table": "fin_payment_schedule",
                "type": "TRANSACTIONAL",
                "row_count": 8019,
                "confidence": 0.97,
                "key_columns": {
                    "pk": "fin_payment_schedule_id",
                    "invoice_fk": "c_invoice_id",
                    "outstanding_amount": "outstandingamt",
                    "due_date": "duedate",
                },
                "base_filter": "isactive='Y'",
                "probed_values": {
                    "isactive": {"Y": 8019},
                },
            },
            "payments": {
                "table": "fin_payment",
                "type": "TRANSACTIONAL",
                "row_count": 5239,
                "confidence": 0.97,
                "key_columns": {
                    "pk": "fin_payment_id",
                    "partner_fk": "c_bpartner_id",
                    "amount": "amount",
                },
                "base_filter": "isreceipt='Y' AND isactive='Y'",
                "probed_values": {
                    "isreceipt": {"Y": 3628, "N": 1611},
                    "isactive": {"Y": 5239},
                },
            },
        },
        "relationships": [
            {"from": "invoices", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
            {"from": "payment_schedule", "to": "invoices", "via": "c_invoice_id", "cardinality": "N:1"},
            {"from": "payments", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
        ],
    }


@pytest.fixture
def generic_entity_map():
    """Schema-agnostic entity_map (not tied to any specific ERP)."""
    return {
        "entities": {
            "invoices": {
                "table": "t_invoice",
                "type": "TRANSACTIONAL",
                "row_count": 5000,
                "confidence": 0.95,
                "base_filter": "is_sales='Y' AND doc_status='CO'",
                "key_columns": {
                    "pk": "invoice_id",
                    "amount_col": "grand_total",
                    "customer_fk": "bp_id",
                    "date_col": "invoice_date",
                },
                "probed_values": {
                    "is_sales": {"Y": 3000, "N": 2000},
                    "doc_status": {"CO": 4500, "DR": 500},
                },
            },
            "customers": {
                "table": "t_customer",
                "type": "MASTER",
                "row_count": 1500,
                "confidence": 0.98,
                "base_filter": "",
                "key_columns": {
                    "pk": "customer_id",
                    "name": "full_name",
                },
                "probed_values": {},
            },
        },
        "relationships": [
            {"from": "invoices", "to": "customers", "via": "bp_id", "cardinality": "N:1"},
        ],
    }


@pytest.fixture
def minimal_client_config():
    """Minimal client configuration dict used by narrator and pipeline tests."""
    return {
        "name": "Test Client",
        "display_name": "Test Client S.A.",
        "sector": "distribucion",
        "currency": "EUR",
        "language": "es",
    }


@pytest.fixture
def minimal_baseline():
    """Minimal baseline dict (no data available)."""
    return {
        "data_available": False,
        "total_revenue": None,
        "_provenance": {},
    }


@pytest.fixture
def populated_baseline():
    """Baseline with realistic measured values."""
    return {
        "data_available": True,
        "total_revenue": 1_600_000.0,
        "num_invoices": 3139,
        "avg_invoice": 509.72,
        "min_invoice": 0.50,
        "max_invoice": 125_000.0,
        "date_from": "2025-01-01",
        "date_to": "2025-12-31",
        "data_freshness_days": 3,
        "distinct_customers": 88,
        "total_outstanding_ar": 864_000.0,
        "overdue_ar": 320_000.0,
        "customers_with_debt": 42,
        "source_queries": ["total_revenue_summary", "ar_outstanding_actual"],
        "warning": None,
        "_provenance": {
            "total_revenue": {
                "source_query": "total_revenue_summary",
                "row_count": 1,
                "confidence": "measured",
            },
        },
    }


@pytest.fixture
def empty_query_results():
    """Query results dict with no data."""
    return {"results": {}, "errors": {}}


@pytest.fixture
def mock_profile():
    """MagicMock ClientProfile with common attributes."""
    profile = MagicMock()
    profile.industry_inferred = "distribucion mayorista"
    profile.currency_detected = "USD"
    profile.focus_tables = []
    profile.metadata = {}
    profile.alert_thresholds = []
    profile.triggered_alerts = []
    return profile


# ── Async helper ──────────────────────────────────────────────────────────────

def run_async(coro):
    """Run a coroutine synchronously. Convenience for non-asyncio test classes."""
    return asyncio.get_event_loop().run_until_complete(coro)
