"""
EmailAdapter — wraps existing SMTP delivery (`shared.email_digest`).

Accepts a Digest, renders an HTML body if none is pre-rendered, and
sends via the existing `send_digest()` helper. Keeps the SMTP env-var
conventions unchanged so the production deploy doesn't need new config.

Refs: VAL-130 (L3.a)
"""

from __future__ import annotations

import asyncio
import logging

from shared.email_digest import send_digest
from shared.notifications.digest import Digest
from shared.notifications.router import DeliveryResult

logger = logging.getLogger(__name__)


def _render_html(digest: Digest) -> str:
    """Minimal HTML body for an ad-hoc digest that didn't pre-render one."""
    sev = digest.severity.value
    sections_html = ""
    for section in digest.sections:
        heading = section.get("heading", "")
        items = section.get("items", [])
        items_html = "".join(
            f"<li>{item.get('text', '')}</li>" for item in items
        )
        sections_html += f"<h3>{heading}</h3><ul>{items_html}</ul>"
    return (
        "<html><body>"
        f"<h2>{digest.title}</h2>"
        f"<p><strong>Severity:</strong> {sev}</p>"
        f"<p>{digest.summary}</p>"
        f"{sections_html}"
        "</body></html>"
    )


class EmailAdapter:
    """Send a Digest via SMTP."""

    channel = "email"

    def __init__(self, sender=None):
        # sender lets tests inject a no-IO fake; defaults to the real SMTP send_digest
        self._sender = sender or send_digest

    async def send(self, digest: Digest, recipient: str) -> DeliveryResult:
        if not recipient:
            return DeliveryResult(
                channel=self.channel, recipient=recipient,
                success=False, error="empty recipient",
            )

        body = digest.html_body or _render_html(digest)
        subject = digest.title or f"Valinor digest — {digest.client_name}"

        # send_digest is sync + blocking (SMTP); offload to default executor.
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, self._sender, recipient, subject, body)

        return DeliveryResult(
            channel=self.channel, recipient=recipient,
            success=bool(ok),
            detail=f"subject={subject!r}" if ok else "",
            error=None if ok else "SMTP send failed (check logs)",
        )
