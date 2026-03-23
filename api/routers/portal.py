"""
Client Portal API — authenticated endpoints for client-facing portal.

Provides:
  - POST /portal/verify     — verify access token, return JWT + client info
  - POST /portal/magic-link — send magic link email (stub)
  - GET  /portal/reports    — list client's reports
  - GET  /portal/reports/{id} — get report detail with findings
  - GET  /portal/status     — client connection/config status

All endpoints require Bearer token auth (portal JWT).

Refs: VAL-13
"""

import os
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/portal", tags=["portal"])

_bearer = HTTPBearer(auto_error=False)


# ── Models ────────────────────────────────────────────────────────────────────

class TokenVerifyRequest(BaseModel):
    token: str


class MagicLinkRequest(BaseModel):
    email: str


class PortalClient(BaseModel):
    id: str
    name: str
    email: str


class VerifyResponse(BaseModel):
    token: str
    client: PortalClient


class ReportSummary(BaseModel):
    id: str
    date: str
    period: str
    findings_count: int
    critical: int
    warnings: int
    opportunities: int
    status: str


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_portal_tokens() -> dict:
    """
    Read portal access tokens from env.
    Format: VALINOR_PORTAL_TOKENS="token1:client_name:email,token2:name2:email2"
    """
    raw = os.getenv("VALINOR_PORTAL_TOKENS", "")
    tokens = {}
    for entry in raw.split(","):
        parts = entry.strip().split(":")
        if len(parts) >= 3:
            tok, name, email = parts[0], parts[1], parts[2]
            tokens[tok] = {"name": name, "email": email}
    return tokens


async def _get_portal_client(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> PortalClient:
    """Validate portal Bearer token and return client info."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    token = credentials.credentials

    # Try JWT decode first
    try:
        from api.auth import decode_jwt_token
        payload = decode_jwt_token(token)
        return PortalClient(
            id=payload.get("sub", ""),
            name=payload.get("client_name", ""),
            email=payload.get("email", ""),
        )
    except Exception:
        pass

    # Fall back to static token lookup
    tokens = _get_portal_tokens()
    if token in tokens:
        info = tokens[token]
        return PortalClient(id=token[:8], name=info["name"], email=info["email"])

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/verify", response_model=VerifyResponse)
async def verify_token(req: TokenVerifyRequest):
    """Verify an access token and return a JWT + client info."""
    tokens = _get_portal_tokens()

    if req.token not in tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")

    info = tokens[req.token]
    client = PortalClient(id=req.token[:8], name=info["name"], email=info["email"])

    # Issue a JWT for subsequent requests
    try:
        from api.auth import create_jwt_token
        jwt_token = create_jwt_token(
            subject=client.id,
            expires_minutes=24 * 60,  # 24 hours
            extra_claims={"client_name": client.name, "email": client.email, "type": "portal"},
        )
    except RuntimeError:
        # JWT secret not configured — return the raw token
        jwt_token = req.token

    logger.info("portal.login", client_name=client.name)
    return VerifyResponse(token=jwt_token, client=client)


@router.post("/magic-link")
async def send_magic_link(req: MagicLinkRequest):
    """Send a magic link email. (Stub — returns success without sending.)"""
    logger.info("portal.magic_link_requested", email=req.email)
    # TODO: implement actual email sending
    return {"status": "ok", "message": "Si el email esta registrado, recibiras un link de acceso."}


@router.get("/reports")
async def list_reports(client: PortalClient = Depends(_get_portal_client)):
    """List all reports for the authenticated client."""
    # TODO: query from database when storage is ready
    # For now return empty list — the portal shell will show empty state
    logger.info("portal.list_reports", client_name=client.name)
    return {"reports": []}


@router.get("/reports/{report_id}")
async def get_report(report_id: str, client: PortalClient = Depends(_get_portal_client)):
    """Get a specific report with findings."""
    # TODO: query from database, verify ownership via tenant_id
    logger.info("portal.get_report", client_name=client.name, report_id=report_id)
    raise HTTPException(status_code=404, detail="Reporte no encontrado")


@router.get("/status")
async def get_status(client: PortalClient = Depends(_get_portal_client)):
    """Get client connection and configuration status."""
    logger.info("portal.get_status", client_name=client.name)
    return {
        "db_connected": False,
        "frequency": "monthly",
        "email_digest": True,
        "client_name": client.name,
    }
