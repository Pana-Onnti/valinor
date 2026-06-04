"""Tenant-aware job-fetch dependency (VAL-176 / VAL-174·B).

``get_job_for_tenant`` loads a job hash from Redis scoped to the caller's tenant
and refuses to return jobs owned by a different tenant — closing the IDOR hole on
the bare ``job:{job_id}`` keys.

Read strategy (transitional, while writers still emit legacy bare keys):
  1. Read the namespaced key ``tenant:{tenant_id}:job:{job_id}`` first.
  2. If empty, DUAL-READ the legacy bare ``job:{job_id}`` key so in-flight jobs
     created before the cut-over stay visible.
  3. Ownership check: legacy jobs have NO ``tenant_id`` field, so they belong to
     ``DEFAULT_TENANT_ID``. We compute ``effective_tenant = stored or DEFAULT``
     and 404 unless it equals the caller — so only the default tenant can
     dual-read legacy data, and a second tenant can NEVER read pre-migration
     jobs it does not own (the IDOR the adversarial review caught and reproduced).

Purely additive: no router imports it yet. Wiring is a later, live-verified step.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import Depends, HTTPException, status

from api.deps import get_redis
from api.tenant import DEFAULT_TENANT_ID, get_tenant_id
from api.tenant_redis_helper import tenant_job_key


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _decode_hash(raw: Dict[Any, Any]) -> Dict[str, Any]:
    """Normalize an ``hgetall`` result to ``str`` keys/values (client may or may not decode)."""
    return {_decode(k): _decode(v) for k, v in raw.items()}


async def get_job_for_tenant(
    job_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> Dict[str, Any]:
    """Return the decoded job hash for *job_id* owned by *tenant_id*, else 404."""
    redis = await get_redis()

    # tenant_job_key validates tenant_id (UUID) and raises 400 on injection.
    raw = await redis.hgetall(tenant_job_key(tenant_id, job_id))
    if not raw:
        # Transitional dual-read of the legacy bare key.
        raw = await redis.hgetall(f"job:{job_id}")

    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    job = _decode_hash(raw)

    # Ownership: missing tenant_id => legacy => belongs to DEFAULT_TENANT_ID only.
    # A mismatch is indistinguishable from "not found" (never leak existence).
    effective_tenant = job.get("tenant_id") or DEFAULT_TENANT_ID
    if effective_tenant != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return job
