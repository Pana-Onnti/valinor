"""
NotificationRouter — dispatches a Digest to one or more channel adapters.

Adapters are registered by channel name. Routing is driven by a list of
`(channel, recipient)` pairs so clients can send the same digest to
different destinations per channel. Adapter failures are captured as
DeliveryResult.error but never raise — one broken channel does not
abort the others.

Refs: VAL-130 (L3.a)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

from shared.notifications.digest import Digest

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    channel: str
    recipient: str
    success: bool
    detail: str = ""
    error: Optional[str] = None


class Adapter(Protocol):
    """Adapter contract — send a Digest to one recipient. Never raises."""
    channel: str

    async def send(self, digest: Digest, recipient: str) -> DeliveryResult: ...


class NotificationRouter:
    """
    Registers channel adapters and dispatches a Digest to configured targets.

    Usage:
        router = NotificationRouter()
        router.register(EmailAdapter())
        router.register(WebhookAdapter(profile=client_profile))
        results = await router.send(
            digest,
            targets=[("email", "buyer@syscop.com.ar"), ("webhook", "https://..."), ],
        )
    """

    def __init__(self):
        self._adapters: dict[str, Adapter] = {}

    def register(self, adapter: Adapter) -> None:
        self._adapters[adapter.channel] = adapter

    def unregister(self, channel: str) -> None:
        self._adapters.pop(channel, None)

    @property
    def channels(self) -> list[str]:
        return sorted(self._adapters)

    async def send(
        self,
        digest: Digest,
        targets: list[tuple[str, str]],
    ) -> list[DeliveryResult]:
        """
        Send `digest` to every (channel, recipient) pair in `targets`.

        Unknown channels produce a failure DeliveryResult but don't raise.
        Adapter exceptions are converted to failure results too.
        """
        async def _one(channel: str, recipient: str) -> DeliveryResult:
            adapter = self._adapters.get(channel)
            if adapter is None:
                return DeliveryResult(
                    channel=channel, recipient=recipient,
                    success=False, error=f"no adapter registered for '{channel}'",
                )
            try:
                return await adapter.send(digest, recipient)
            except Exception as exc:
                logger.exception("router: adapter %s raised", channel)
                return DeliveryResult(
                    channel=channel, recipient=recipient,
                    success=False, error=f"{type(exc).__name__}: {exc}",
                )

        tasks = [_one(ch, r) for ch, r in targets]
        return await asyncio.gather(*tasks)
