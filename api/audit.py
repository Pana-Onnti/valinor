"""
Audit log — best-effort append to the Redis FIFO ``audit_log``.

A single source for appending audit events so both the ``/api/audit`` endpoint
and internal callers (the VAL-192 N4 memory-review approve/reject endpoints)
write the same shape. **Best-effort**: a Redis hiccup must never break the
operation being audited — the function returns False and logs, never raises.
"""

from __future__ import annotations

import json
from datetime import datetime

import structlog

logger = structlog.get_logger()

AUDIT_LOG_KEY = "audit_log"
AUDIT_LOG_CAP = 1000


async def emit_audit_event(event: dict, redis_client=None) -> bool:
    """Append ``event`` (stamped with a server ``timestamp``) to the capped Redis
    audit log. Returns True on success. Never raises — audit is observability,
    not on the critical path of the action being audited."""
    try:
        if redis_client is None:
            from api.deps import get_redis
            redis_client = await get_redis()
        payload = json.dumps({**event, "timestamp": datetime.utcnow().isoformat()})
        await redis_client.lpush(AUDIT_LOG_KEY, payload)
        await redis_client.ltrim(AUDIT_LOG_KEY, 0, AUDIT_LOG_CAP - 1)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort, never break the caller
        logger.warning("audit event not logged", error=str(exc),
                       event_type=event.get("event_type"))
        return False
