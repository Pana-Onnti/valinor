"""
Valinor SaaS API — Shared dependencies for routers.

Provides get_redis() and the shared slowapi `limiter` used across all route
modules. The limiter lives here (not in main.py) so routers can import it at
module-import time to apply `@limiter.limit(...)` decorators.
"""

from fastapi import HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address
import redis.asyncio as redis

# Set by main.py during app startup
_redis_client = None


def set_redis_client(client):
    global _redis_client
    _redis_client = client


def get_redis_client():
    return _redis_client


async def get_redis() -> redis.Redis:
    """Get Redis client dependency."""
    if not _redis_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis not available"
        )
    return _redis_client


def _rate_limit_key(request) -> str:
    """Rate-limit bucket key: per-tenant when the X-Tenant-ID header is present,
    otherwise per-client-IP. Lets us throttle each tenant independently without
    requiring a JWT auth layer that does not yet exist."""
    tenant = request.headers.get("X-Tenant-ID")
    if tenant:
        return f"tenant:{tenant}"
    return get_remote_address(request)


# Shared limiter singleton — imported by main.py (wiring) and routers (decorators).
# retry_after="delta-seconds" makes 429 responses carry a Retry-After header.
limiter = Limiter(key_func=_rate_limit_key, retry_after="delta-seconds")


def get_limiter():
    return limiter
