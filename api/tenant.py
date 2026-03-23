"""
Multi-tenant middleware and dependencies.

Extracts tenant_id from request (X-Tenant-ID header or JWT 'tenant_id' claim),
sets the PostgreSQL session variable for RLS enforcement, and binds tenant
context to structlog for automatic log enrichment.

Usage:
    # As a dependency in routers:
    from api.tenant import get_tenant_id
    @router.get("/jobs")
    async def list_jobs(tenant_id: str = Depends(get_tenant_id)): ...

    # Middleware is registered in api/main.py automatically.

Refs: VAL-21
"""

import os
from typing import Optional

import structlog
from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

_bearer_scheme = HTTPBearer(auto_error=False)

# Header name for explicit tenant ID
TENANT_HEADER = "X-Tenant-ID"

# Default tenant for dev/single-tenant mode
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _is_multi_tenant_enabled() -> bool:
    """Check if multi-tenant mode is enabled via env var."""
    return os.getenv("VALINOR_MULTI_TENANT", "false").lower() in ("true", "1", "yes")


def _extract_tenant_from_jwt(token: str) -> Optional[str]:
    """Extract tenant_id from a JWT token's claims."""
    try:
        from api.auth import decode_jwt_token
        payload = decode_jwt_token(token)
        return payload.get("tenant_id")
    except Exception:
        return None


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts tenant context from each request.

    Resolution order:
    1. X-Tenant-ID header (explicit)
    2. JWT 'tenant_id' claim (from Bearer token)
    3. Default tenant (single-tenant / dev mode)

    Sets:
    - request.state.tenant_id
    - structlog contextvars: tenant_id
    """

    # Paths that don't require tenant context
    _SKIP_PATHS = {"/health", "/healthz", "/metrics", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        # Skip tenant resolution for health/metrics/docs endpoints
        if request.url.path in self._SKIP_PATHS:
            request.state.tenant_id = None
            return await call_next(request)

        tenant_id = None

        # 1. Try explicit header
        tenant_id = request.headers.get(TENANT_HEADER)

        # 2. Try JWT claim
        if not tenant_id:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                tenant_id = _extract_tenant_from_jwt(token)

        # 3. Fall back to default tenant
        if not tenant_id:
            if _is_multi_tenant_enabled():
                # In multi-tenant mode, tenant is required for non-skip paths
                # But allow it for now with a warning — strict enforcement comes later
                logger.warning(
                    "tenant.missing",
                    path=request.url.path,
                    method=request.method,
                )
            tenant_id = DEFAULT_TENANT_ID

        # Set tenant context
        request.state.tenant_id = tenant_id
        structlog.contextvars.bind_contextvars(tenant_id=tenant_id)

        response = await call_next(request)
        response.headers["X-Tenant-ID"] = tenant_id
        return response


async def get_tenant_id(request: Request) -> str:
    """
    FastAPI dependency — returns the tenant_id from request state.

    Use in router endpoints:
        @router.get("/jobs")
        async def list_jobs(tenant_id: str = Depends(get_tenant_id)):
            ...
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant context not available",
        )
    return tenant_id


def set_tenant_db_context(conn, tenant_id: str) -> None:
    """
    Set PostgreSQL session variable for RLS enforcement.

    Call this at the start of each database transaction:
        async with engine.connect() as conn:
            set_tenant_db_context(conn, tenant_id)
            # All queries now filtered by RLS

    Uses parameterized SET to prevent SQL injection.
    """
    from sqlalchemy import text
    # Use SET LOCAL so it only applies to the current transaction
    conn.execute(text("SET LOCAL app.current_tenant = :tenant_id"), {"tenant_id": tenant_id})
