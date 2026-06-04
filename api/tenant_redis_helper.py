"""Tenant-scoped Redis key helpers (VAL-176 / VAL-174·B).

Pure, I/O-free builders for *namespaced* job keys so each tenant's jobs live
under their own prefix (``tenant:{tenant_id}:job:{job_id}``), closing the IDOR
hole on the legacy bare ``job:{job_id}`` keys.

Every builder runs the candidate ``tenant_id`` through ``_validate_tenant_uuid``
first, which rejects anything that is not a canonical UUID — that prevents
Redis-key injection / traversal (a ``tenant_id`` of ``*`` or ``a:job:x`` can
never be spliced into a key).

Purely additive: nothing imports this yet. Wiring the routers/writers to use
these keys is a later, live-verified step.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status


def _validate_tenant_uuid(tenant_id: str) -> str:
    """Return *tenant_id* iff it is a canonical UUID; else raise HTTP 400.

    ``DEFAULT_TENANT_ID`` passes. Empty string, ``*``, or any value containing
    ``:`` / ``job:`` / path separators is rejected before it can reach a key.
    """
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant identifier")
    try:
        parsed = uuid.UUID(tenant_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant identifier")
    # Require the canonical form to match exactly (rejects urn:/brace/garbage forms).
    if str(parsed) != tenant_id.lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant identifier")
    return tenant_id


def tenant_job_key(tenant_id: str, job_id: str) -> str:
    """Namespaced key for a job's metadata hash."""
    _validate_tenant_uuid(tenant_id)
    return f"tenant:{tenant_id}:job:{job_id}"


def tenant_job_results_key(tenant_id: str, job_id: str) -> str:
    """Namespaced key for a job's serialized results string."""
    _validate_tenant_uuid(tenant_id)
    return f"tenant:{tenant_id}:job:{job_id}:results"


def tenant_job_pattern(tenant_id: str) -> str:
    """``scan_iter`` glob for every job hash of *tenant_id* (filter ``:results`` like legacy)."""
    _validate_tenant_uuid(tenant_id)
    return f"tenant:{tenant_id}:job:*"
