"""
WebhookAdapter — HTTP POST a Digest to a webhook URL.

Lightweight adapter that does NOT require a ClientProfile (unlike the
existing WebhookDispatcher, which iterates a profile's webhook list).
The router already knows the target URL; this adapter just POSTs.

Uses the same HMAC-SHA256 signing scheme as WebhookDispatcher when a
secret is provided via `signing_secret`.

Refs: VAL-130 (L3.a)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Optional

import aiohttp

from shared.notifications.digest import Digest
from shared.notifications.router import DeliveryResult

logger = logging.getLogger(__name__)

# Unused import clean-up


_TIMEOUT = aiohttp.ClientTimeout(total=5)


def _compute_hmac(payload_bytes: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def _digest_to_payload(digest: Digest) -> dict:
    """Shape a webhook-friendly JSON body for downstream consumers."""
    return {
        "client_name": digest.client_name,
        "title": digest.title,
        "summary": digest.summary,
        "vertical": digest.vertical,
        "severity": digest.severity.value,
        "sections": digest.sections,
        "metadata": digest.metadata,
    }


class WebhookAdapter:
    """Send a Digest via HTTP POST to a URL."""

    channel = "webhook"

    def __init__(self, signing_secret: Optional[str] = None, session=None):
        self._secret = signing_secret
        self._session = session  # allow tests to inject fake session

    async def send(self, digest: Digest, recipient: str) -> DeliveryResult:
        if not recipient or not recipient.startswith(("http://", "https://")):
            return DeliveryResult(
                channel=self.channel, recipient=recipient,
                success=False, error="recipient must be an http(s) URL",
            )

        payload = digest.raw_payload or _digest_to_payload(digest)
        body_bytes = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._secret:
            headers["X-Valinor-Signature"] = _compute_hmac(body_bytes, self._secret)

        session = self._session or aiohttp.ClientSession(timeout=_TIMEOUT)
        owns_session = self._session is None
        try:
            async with session.post(recipient, data=body_bytes, headers=headers) as resp:
                status = resp.status
                ok = 200 <= status < 300
                return DeliveryResult(
                    channel=self.channel, recipient=recipient,
                    success=ok,
                    detail=f"http {status}",
                    error=None if ok else f"http {status}",
                )
        finally:
            if owns_session:
                await session.close()
