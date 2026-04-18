"""
Notifications — pluggable delivery for digests/reports across channels.

Entry point: `NotificationRouter`. It wraps the existing SMTP delivery
(`shared.email_digest`) and webhook delivery (`shared.webhook_dispatcher`)
behind a common adapter interface so a vertical can produce a `Digest`
once and have it routed to email / webhook / WhatsApp / etc. based on
per-client channel preferences.

Refs: VAL-130 (L3.a)
"""

from shared.notifications.digest import Digest, Severity
from shared.notifications.router import (
    Adapter,
    DeliveryResult,
    NotificationRouter,
)

__all__ = [
    "Digest",
    "Severity",
    "Adapter",
    "DeliveryResult",
    "NotificationRouter",
]
