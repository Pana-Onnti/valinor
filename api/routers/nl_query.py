"""
NL→SQL Router — VAL-32.

Endpoint: POST /api/v1/nl-query

Accepts a natural language question and optional tenant_id.
Returns the generated SQL, query result, and a plain-language explanation.

This endpoint complements the QueryBuilder pipeline — it does NOT replace it.
Use this for ad-hoc questions. Use the analysis pipeline for scheduled reports.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1", tags=["nl-query"])


# ── Request / Response models ─────────────────────────────────────────────────

class NLQueryRequest(BaseModel):
    """Natural language query request."""

    question: str = Field(
        description="Natural language question about the data",
        min_length=3,
        max_length=500,
        examples=["What are my top 10 customers by revenue?"],
    )
    tenant_id: str = Field(
        description="Tenant identifier used to load the correct schema",
        examples=["acme-corp"],
    )
    connection_string: Optional[str] = Field(
        default=None,
        description=(
            "Optional SQLAlchemy connection string. "
            "If provided, the SQL will be executed and results returned. "
            "If omitted, only the SQL is returned."
        ),
    )
    entity_map: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional entity_map from the Cartographer. "
            "When provided, Vanna is trained with this schema for better accuracy."
        ),
    )
    max_rows: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum rows to return when executing the query",
    )


class NLQueryResponse(BaseModel):
    """Natural language query response."""

    sql: Optional[str] = Field(default=None, description="Generated SQL")
    result: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Query result rows (empty if connection_string not provided)",
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Plain-language explanation of the generated SQL",
    )
    error: Optional[str] = Field(default=None, description="Error message if generation failed")
    tenant_id: str = Field(description="Echo of the request tenant_id")
    rows_returned: int = Field(default=0)


# ── Per-tenant adapter cache (bounded) ────────────────────────────────────────

_ADAPTER_CACHE_MAXSIZE = 128
_ADAPTER_CACHE_TTL_SECONDS = 3600  # 1 hour


class _BoundedAdapterCache:
    """LRU cache with TTL and max size for per-tenant VannaAdapters."""

    def __init__(self, maxsize: int = _ADAPTER_CACHE_MAXSIZE, ttl: int = _ADAPTER_CACHE_TTL_SECONDS):
        self._maxsize = maxsize
        self._ttl = ttl
        # OrderedDict: key → (adapter, created_at)
        self._store: OrderedDict[str, Tuple[Any, float]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        if key in self._store:
            adapter, created_at = self._store[key]
            if time.monotonic() - created_at > self._ttl:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return adapter
        return None

    def put(self, key: str, adapter: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (adapter, time.monotonic())
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)


_adapter_cache = _BoundedAdapterCache()


def _get_adapter(tenant_id: str, entity_map: Optional[Dict[str, Any]] = None):
    """
    Get or create a VannaAdapter for the given tenant.

    When entity_map is provided, the adapter is (re)trained with the new schema.
    """
    from core.valinor.nl.vanna_adapter import VannaAdapter

    adapter = _adapter_cache.get(tenant_id)
    if adapter is None:
        adapter = VannaAdapter()
        _adapter_cache.put(tenant_id, adapter)
        logger.info("nl_query: created new adapter", tenant_id=tenant_id)

    if entity_map:
        adapter.train_from_entity_map(entity_map)

    return adapter


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/nl-query", response_model=NLQueryResponse, summary="Natural Language → SQL")
async def nl_query(request: NLQueryRequest) -> NLQueryResponse:
    """
    Convert a natural language question to SQL and optionally execute it.

    **When to use this endpoint:**
    - Ad-hoc questions not covered by the standard analysis pipeline
    - Interactive exploration via the NLQueryWidget
    - Prototype queries before formalising them in the QueryBuilder

    **When NOT to use this:**
    - Scheduled analysis runs → use the pipeline endpoint instead
    - Bulk data exports → use the query execution endpoint directly
    """
    logger.info(
        "nl_query.request",
        tenant_id=request.tenant_id,
        question=request.question[:80],
        has_entity_map=bool(request.entity_map),
        has_connection=bool(request.connection_string),
    )

    try:
        adapter = _get_adapter(request.tenant_id, request.entity_map)

        if not adapter.is_ready:
            raise HTTPException(
                status_code=503,
                detail=(
                    "NL→SQL adapter not available. "
                    "Ensure ANTHROPIC_API_KEY is configured."
                ),
            )

        if request.connection_string:
            result = adapter.ask_and_run(
                question=request.question,
                connection_string=request.connection_string,
                max_rows=request.max_rows,
            )
        else:
            result = adapter.ask(question=request.question)
            result["result"] = []

        return NLQueryResponse(
            sql=result.get("sql"),
            result=result.get("result", []),
            explanation=result.get("explanation"),
            error=result.get("error"),
            tenant_id=request.tenant_id,
            rows_returned=len(result.get("result", [])),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("nl_query.error", tenant_id=request.tenant_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
