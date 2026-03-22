"""
API authentication — MVP API key validation + optional JWT support.

VAL-48: Implement basic authentication (JWT/API keys) in API.

Usage:
    from api.auth import verify_api_key
    @app.get("/secure", dependencies=[Depends(verify_api_key)])
    async def secure_endpoint(): ...
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger()

# ── Security scheme ───────────────────────────────────────────────────────────
_bearer_scheme = HTTPBearer(auto_error=False)


def _get_api_key() -> Optional[str]:
    """Read the API key from environment. Returns None if not configured."""
    return os.getenv("VALINOR_API_KEY")


async def verify_api_key(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency — validates Bearer token against VALINOR_API_KEY.

    If VALINOR_API_KEY is not set, auth is disabled (dev mode).
    Returns the validated key or "dev-mode" if auth is disabled.

    VAL-48
    """
    expected_key = _get_api_key()

    # Dev mode: no key configured → allow all requests
    if not expected_key:
        return "dev-mode"

    if not credentials:
        logger.warning(
            "auth.missing_credentials",
            path=request.url.path,
            client=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != expected_key:
        logger.warning(
            "auth.invalid_key",
            path=request.url.path,
            client=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


# ── Optional JWT helpers (for future use) ─────────────────────────────────────
# Uses PyJWT (not python-jose) — VAL-50

def create_jwt_token(
    subject: str,
    expires_minutes: int = 60,
    extra_claims: Optional[dict] = None,
) -> str:
    """
    Create a signed JWT token. Requires VALINOR_JWT_SECRET env var.

    Parameters
    ----------
    subject : str
        The 'sub' claim (e.g., user ID or API client name).
    expires_minutes : int
        Token lifetime in minutes.
    extra_claims : dict, optional
        Additional claims to include.

    Returns
    -------
    str
        Encoded JWT token.
    """
    try:
        import jwt  # PyJWT — VAL-50
    except ImportError:
        raise RuntimeError("PyJWT is required for JWT support. Install with: pip install PyJWT")

    secret = os.getenv("VALINOR_JWT_SECRET")
    if not secret:
        raise RuntimeError("VALINOR_JWT_SECRET environment variable is required for JWT tokens")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        **(extra_claims or {}),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt_token(token: str) -> dict:
    """
    Decode and validate a JWT token. Requires VALINOR_JWT_SECRET env var.

    Returns the decoded payload dict.
    Raises HTTPException on invalid/expired tokens.
    """
    try:
        import jwt  # PyJWT — VAL-50
    except ImportError:
        raise RuntimeError("PyJWT is required for JWT support. Install with: pip install PyJWT")

    secret = os.getenv("VALINOR_JWT_SECRET")
    if not secret:
        raise RuntimeError("VALINOR_JWT_SECRET environment variable is required for JWT tokens")

    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )
