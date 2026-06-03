"""Per-tenant API credential helpers — hash, generate, constant-time verify.

Used by the auth layer and the tenant-registration scripts. Lives in shared/ so
it is importable from both the API and worker images (both COPY shared/).

Keys are opaque random tokens; only their SHA-256 hash is ever stored. Comparison
is constant-time to avoid timing oracles.

Refs: VAL-174
"""
from __future__ import annotations

import hashlib
import secrets

_KEY_PREFIX = "vk"


def hash_api_key(key: str) -> str:
    """Return the SHA-256 hex digest of an API key, for at-rest storage."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = _KEY_PREFIX) -> str:
    """Generate a new opaque API key of the form '{prefix}_<64 hex chars>'."""
    return f"{prefix}_{secrets.token_hex(32)}"


def keys_match(presented_key: str, stored_hash: str) -> bool:
    """Constant-time check that *presented_key* hashes to *stored_hash*."""
    return secrets.compare_digest(hash_api_key(presented_key), stored_hash)
