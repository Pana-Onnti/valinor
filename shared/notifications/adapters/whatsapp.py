"""
WhatsAppAdapter — send a Digest via Twilio WhatsApp Business API.

Twilio API is sync — we offload it to a worker thread so the adapter
stays compatible with the async router.

The WhatsApp Business API caps messages at ~4096 chars; we format and
truncate the Digest into a compact text body with emoji severity markers.

Config (env vars):
  TWILIO_ACCOUNT_SID
  TWILIO_AUTH_TOKEN
  TWILIO_WHATSAPP_FROM   e.g. "+14155238886" (the sandbox or the verified number)

Refs: VAL-130 (L3.b)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

from shared.notifications.digest import Digest, Severity
from shared.notifications.router import DeliveryResult

logger = logging.getLogger(__name__)


WHATSAPP_MAX_CHARS = 4096
_TRUNCATE_SUFFIX = "\n…[truncado]"


_SEVERITY_EMOJI: dict[Severity, str] = {
    Severity.CRITICAL: "🚨",
    Severity.HIGH:     "⚠️",
    Severity.MEDIUM:   "🟡",
    Severity.LOW:      "🔵",
    Severity.INFO:     "ℹ️",
}


def format_whatsapp_body(digest: Digest, max_chars: int = WHATSAPP_MAX_CHARS) -> str:
    """Render a Digest as a compact, emoji-prefixed WhatsApp body."""
    emoji = _SEVERITY_EMOJI.get(digest.severity, "")
    parts: list[str] = [f"{emoji} *{digest.title}*".strip()]
    if digest.summary:
        parts.append(digest.summary)
    for section in digest.sections:
        heading = section.get("heading", "")
        if heading:
            parts.append(f"\n*{heading}*")
        for item in section.get("items", []):
            sev = item.get("severity")
            item_emoji = _SEVERITY_EMOJI.get(sev, "") if isinstance(sev, Severity) else ""
            prefix = f"{item_emoji} " if item_emoji else "- "
            parts.append(f"{prefix}{item.get('text', '')}")
    body = "\n".join(parts)
    if len(body) > max_chars:
        budget = max_chars - len(_TRUNCATE_SUFFIX)
        if budget <= 0:
            # max_chars tighter than the suffix itself — just hard-clip.
            body = body[:max_chars]
        else:
            body = body[:budget].rstrip() + _TRUNCATE_SUFFIX
    return body


def _normalize_whatsapp_recipient(recipient: str) -> str:
    """Add the 'whatsapp:' prefix if missing."""
    if recipient.startswith("whatsapp:"):
        return recipient
    return f"whatsapp:{recipient}"


class WhatsAppAdapter:
    """Send a Digest via Twilio WhatsApp."""

    channel = "whatsapp"

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        client_factory: Optional[Callable[[str, str], object]] = None,
    ):
        self._sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        self._token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        self._from = from_number or os.environ.get("TWILIO_WHATSAPP_FROM", "").strip()
        # client_factory lets tests inject a fake twilio.rest.Client
        self._client_factory = client_factory

    def _build_client(self):
        if self._client_factory is not None:
            return self._client_factory(self._sid, self._token)
        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise RuntimeError(
                "twilio SDK not installed — add 'twilio' to deps or pass client_factory",
            ) from exc
        return Client(self._sid, self._token)

    async def send(self, digest: Digest, recipient: str) -> DeliveryResult:
        missing = [k for k, v in (
            ("TWILIO_ACCOUNT_SID", self._sid),
            ("TWILIO_AUTH_TOKEN", self._token),
            ("TWILIO_WHATSAPP_FROM", self._from),
        ) if not v]
        if missing:
            return DeliveryResult(
                channel=self.channel, recipient=recipient,
                success=False, error=f"missing Twilio config: {missing}",
            )
        if not recipient:
            return DeliveryResult(
                channel=self.channel, recipient=recipient,
                success=False, error="empty recipient",
            )

        body = format_whatsapp_body(digest)
        dest = _normalize_whatsapp_recipient(recipient)
        sender = _normalize_whatsapp_recipient(self._from)

        def _do_send():
            client = self._build_client()
            return client.messages.create(body=body, from_=sender, to=dest)

        try:
            loop = asyncio.get_running_loop()
            message = await loop.run_in_executor(None, _do_send)
        except Exception as exc:
            return DeliveryResult(
                channel=self.channel, recipient=recipient,
                success=False, error=f"{type(exc).__name__}: {exc}",
            )

        sid = getattr(message, "sid", "unknown")
        return DeliveryResult(
            channel=self.channel, recipient=recipient,
            success=True, detail=f"twilio_sid={sid}, len={len(body)}",
        )
