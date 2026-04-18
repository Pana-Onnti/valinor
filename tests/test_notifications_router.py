"""
Tests for NotificationRouter + email/webhook adapters (VAL-130 L3.a).

Refs: VAL-130
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.notifications import (
    Adapter,
    Digest,
    DeliveryResult,
    NotificationRouter,
    Severity,
)
from shared.notifications.adapters.email import EmailAdapter
from shared.notifications.adapters.webhook import WebhookAdapter


# ─────────────────────────────────────────────────────────────────────
# Digest
# ─────────────────────────────────────────────────────────────────────


def test_digest_minimal():
    d = Digest(client_name="acme", title="report", summary="1 line")
    assert d.severity == Severity.INFO
    assert d.vertical == "generic"
    assert d.sections == []


# ─────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────


class _FakeAdapter:
    """Adapter protocol fake."""
    def __init__(self, channel: str, ok: bool = True, raise_exc: Exception | None = None):
        self.channel = channel
        self._ok = ok
        self._raise = raise_exc
        self.calls: list[tuple[Digest, str]] = []

    async def send(self, digest: Digest, recipient: str) -> DeliveryResult:
        self.calls.append((digest, recipient))
        if self._raise:
            raise self._raise
        return DeliveryResult(
            channel=self.channel, recipient=recipient,
            success=self._ok,
            detail="ok" if self._ok else "",
            error=None if self._ok else "boom",
        )


class TestRouter:
    def test_register_and_channels(self):
        r = NotificationRouter()
        r.register(_FakeAdapter("email"))
        r.register(_FakeAdapter("webhook"))
        assert r.channels == ["email", "webhook"]

    def test_unregister(self):
        r = NotificationRouter()
        r.register(_FakeAdapter("email"))
        r.unregister("email")
        assert r.channels == []

    async def test_send_dispatches_to_matching_adapter(self):
        r = NotificationRouter()
        email = _FakeAdapter("email")
        webhook = _FakeAdapter("webhook")
        r.register(email)
        r.register(webhook)

        digest = Digest(client_name="acme", title="t", summary="s")
        results = await r.send(
            digest,
            targets=[("email", "a@b"), ("webhook", "https://x")],
        )
        assert len(results) == 2
        assert all(res.success for res in results)
        assert len(email.calls) == 1
        assert email.calls[0][1] == "a@b"

    async def test_send_unknown_channel_captured_as_failure(self):
        r = NotificationRouter()
        r.register(_FakeAdapter("email"))
        results = await r.send(
            Digest(client_name="acme", title="t", summary="s"),
            targets=[("slack", "@me")],
        )
        assert len(results) == 1
        assert results[0].success is False
        assert "no adapter" in results[0].error

    async def test_send_adapter_exception_captured(self):
        r = NotificationRouter()
        r.register(_FakeAdapter("email", raise_exc=RuntimeError("boom")))
        results = await r.send(
            Digest(client_name="acme", title="t", summary="s"),
            targets=[("email", "a@b")],
        )
        assert results[0].success is False
        assert "RuntimeError: boom" in results[0].error

    async def test_send_partial_failure(self):
        r = NotificationRouter()
        r.register(_FakeAdapter("email", ok=False))
        r.register(_FakeAdapter("webhook", ok=True))
        results = await r.send(
            Digest(client_name="acme", title="t", summary="s"),
            targets=[("email", "a@b"), ("webhook", "https://x")],
        )
        by_channel = {r.channel: r for r in results}
        assert by_channel["email"].success is False
        assert by_channel["webhook"].success is True


# ─────────────────────────────────────────────────────────────────────
# EmailAdapter
# ─────────────────────────────────────────────────────────────────────


class TestEmailAdapter:
    async def test_rejects_empty_recipient(self):
        adapter = EmailAdapter(sender=lambda *a, **k: True)
        result = await adapter.send(Digest(client_name="a", title="t", summary="s"), "")
        assert not result.success
        assert result.error == "empty recipient"

    async def test_uses_pre_rendered_html_when_present(self):
        captured = {}

        def fake_send(to, subject, body):
            captured["to"] = to
            captured["subject"] = subject
            captured["body"] = body
            return True

        adapter = EmailAdapter(sender=fake_send)
        digest = Digest(
            client_name="a", title="Weekly", summary="1 line",
            html_body="<html>CUSTOM</html>",
        )
        result = await adapter.send(digest, "me@a.com")
        assert result.success is True
        assert captured["body"] == "<html>CUSTOM</html>"
        assert captured["subject"] == "Weekly"

    async def test_renders_sections_when_no_html(self):
        captured = {}

        def fake_send(to, subject, body):
            captured["body"] = body
            return True

        adapter = EmailAdapter(sender=fake_send)
        digest = Digest(
            client_name="a", title="t", summary="s",
            sections=[{"heading": "URGENT", "items": [{"text": "item1"}]}],
        )
        await adapter.send(digest, "me@a.com")
        assert "URGENT" in captured["body"]
        assert "item1" in captured["body"]

    async def test_smtp_failure_propagated(self):
        adapter = EmailAdapter(sender=lambda *a, **k: False)
        result = await adapter.send(Digest(client_name="a", title="t", summary="s"), "x@y")
        assert result.success is False
        assert "SMTP" in result.error


# ─────────────────────────────────────────────────────────────────────
# WebhookAdapter
# ─────────────────────────────────────────────────────────────────────


class _FakeCtxManager:
    def __init__(self, status: int):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


class _FakeSession:
    """aiohttp.ClientSession stand-in that records posts."""

    def __init__(self, status: int = 200):
        self.posts: list[dict] = []
        self._status = status

    def post(self, url, *, data, headers):
        self.posts.append({"url": url, "data": data, "headers": headers})
        return _FakeCtxManager(self._status)

    async def close(self):
        pass


class TestWebhookAdapter:
    async def test_rejects_non_http_recipient(self):
        adapter = WebhookAdapter(session=_FakeSession())
        result = await adapter.send(
            Digest(client_name="a", title="t", summary="s"), "not-a-url",
        )
        assert not result.success

    async def test_posts_json_payload(self):
        session = _FakeSession(status=201)
        adapter = WebhookAdapter(session=session)
        digest = Digest(
            client_name="acme", title="T", summary="S",
            vertical="inventory", severity=Severity.CRITICAL,
            sections=[{"heading": "URGENT", "items": [{"text": "stock zero"}]}],
        )
        result = await adapter.send(digest, "https://hooks.example.com/x")
        assert result.success is True

        assert len(session.posts) == 1
        post = session.posts[0]
        assert post["url"] == "https://hooks.example.com/x"
        assert post["headers"]["Content-Type"] == "application/json"
        # no secret → no signature header
        assert "X-Valinor-Signature" not in post["headers"]
        import json
        body = json.loads(post["data"])
        assert body["client_name"] == "acme"
        assert body["severity"] == "CRITICAL"
        assert body["vertical"] == "inventory"

    async def test_hmac_header_when_secret_set(self):
        session = _FakeSession(status=200)
        adapter = WebhookAdapter(signing_secret="topsecret", session=session)
        await adapter.send(
            Digest(client_name="a", title="t", summary="s"),
            "https://hooks.example.com/x",
        )
        headers = session.posts[0]["headers"]
        assert "X-Valinor-Signature" in headers
        assert len(headers["X-Valinor-Signature"]) == 64  # hex sha256

    async def test_non_2xx_marks_failure(self):
        session = _FakeSession(status=500)
        adapter = WebhookAdapter(session=session)
        result = await adapter.send(
            Digest(client_name="a", title="t", summary="s"),
            "https://hooks.example.com/x",
        )
        assert result.success is False
        assert "http 500" in result.error
