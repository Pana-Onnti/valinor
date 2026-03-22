"""
Valinor SaaS API — Shared dependencies for routers.

Provides get_redis() and get_limiter() used across all route modules.
"""

from fastapi import HTTPException, status
import redis.asyncio as redis

# These are set by main.py during app startup
_redis_client = None
_limiter = None


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


def set_limiter(limiter):
    global _limiter
    _limiter = limiter


def get_limiter():
    return _limiter
