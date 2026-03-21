"""
WebhookDispatcher — delivers event notifications to client-registered webhook URLs.

Supported event types:
  - analysis_completed
  - finding_critical
  - dq_gate_failed
  - alert_triggered

Each webhook in ClientProfile.webhooks may subscribe to a subset of events or
use the wildcard ["*"] to receive all events.

Webhook dict schema (stored in ClientProfile.webhooks):
  {
    "url": "https://...",
    "events": ["analysis_completed", "alert_triggered"],  # or ["*"]
    "secret": "optional-hmac-secret"
  }
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import aiohttp

from shared.memory.client_profile import ClientProfile

logger = logging.getLogger(__name__)

# Supported event types
SUPPORTED_EVENTS = frozenset([
    "analysis_completed",
    "finding_critical",
    "dq_gate_failed",
    "alert_triggered",
])

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=5)


def _compute_hmac(payload_bytes: bytes, secret: str) -> str:
    """Return lowercase hex HMAC-SHA256 of payload_bytes using secret."""
    key = secret.encode("utf-8") if secret else b""
    return hmac.new(key, payload_bytes, hashlib.sha256).hexdigest()


def create_webhook_payload(event_type: str, data: dict, client_name: str) -> dict:
    """
    Wrap raw event data in a standard envelope.

    Returns:
        {
            "event_type": str,
            "client_name": str,
            "timestamp": ISO-8601 string (UTC),
            "version": "1.0",
            "data": dict,
        }
    """
    return {
        "event_type": event_type,
        "client_name": client_name,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "version": "1.0",
        "data": data,
    }


class WebhookDispatcher:
    """Delivers webhook events to all matching registered endpoints."""

    async def dispatch(
        self,
        profile: ClientProfile,
        event_type: str,
        payload: dict,
    ) -> List[dict]:
        """
        POST payload to every webhook in profile that subscribes to event_type.

        Args:
            profile:    ClientProfile whose webhooks list is consulted.
            event_type: One of SUPPORTED_EVENTS.
            payload:    Arbitrary dict — will be JSON-serialised for delivery.

        Returns:
            List of delivery result dicts, one per matching webhook:
            [{"url": str, "status": int | None, "success": bool, "error": str | None}, ...]
        """
        webhooks: List[Dict[str, Any]] = getattr(profile, "webhooks", []) or []
        if not webhooks:
            return []

        results: List[dict] = []

        for webhook in webhooks:
            url: str = webhook.get("url", "")
            if not url:
                continue

            subscribed_events: List[str] = webhook.get("events") or []
            # Match if wildcard or explicit subscription
            if "*" not in subscribed_events and event_type not in subscribed_events:
                continue

            secret: str = webhook.get("secret") or ""
            result = await self._deliver(url, event_type, payload, secret)
            results.append(result)

        return results

    async def _deliver(
        self,
        url: str,
        event_type: str,
        payload: dict,
        secret: str,
    ) -> dict:
        """
        Attempt delivery with one retry on connection error.
        Returns a delivery result dict.
        """
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        signature = _compute_hmac(payload_bytes, secret)

        headers = {
            "Content-Type": "application/json",
            "X-Valinor-Event": event_type,
            "X-Valinor-Signature": signature,
        }

        last_error: Optional[str] = None

        for attempt in range(2):  # initial attempt + one retry on connection error
            try:
                async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
                    async with session.post(
                        url,
                        data=payload_bytes,
                        headers=headers,
                    ) as response:
                        status = response.status
                        success = 200 <= status < 300
                        logger.debug(
                            "Webhook delivery",
                            extra={"url": url, "status": status, "event": event_type},
                        )
                        return {
                            "url": url,
                            "status": status,
                            "success": success,
                            "error": None,
                        }

            except asyncio.TimeoutError as exc:
                # Timeout is not a connection error — do not retry
                logger.warning("Webhook delivery timed out", extra={"url": url})
                return {
                    "url": url,
                    "status": None,
                    "success": False,
                    "error": f"TimeoutError: {exc}",
                }

            except aiohttp.ClientConnectionError as exc:
                last_error = str(exc)
                if attempt == 0:
                    logger.warning(
                        "Webhook delivery connection error, retrying once",
                        extra={"url": url, "error": last_error},
                    )
                    continue  # retry
                # Second attempt also failed
                logger.error(
                    "Webhook delivery failed after retry",
                    extra={"url": url, "error": last_error},
                )
                return {
                    "url": url,
                    "status": None,
                    "success": False,
                    "error": f"ConnectionError: {last_error}",
                }

            except Exception as exc:
                logger.error("Webhook delivery unexpected error", extra={"url": url, "error": str(exc)})
                return {
                    "url": url,
                    "status": None,
                    "success": False,
                    "error": str(exc),
                }

        # Should not reach here
        return {
            "url": url,
            "status": None,
            "success": False,
            "error": last_error or "Unknown error",
        }
