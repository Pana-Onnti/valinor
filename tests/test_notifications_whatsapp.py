"""
Tests for WhatsAppAdapter + formatter (VAL-130 L3.b).

Uses an injected client_factory so tests don't need the twilio SDK or
real credentials.

Refs: VAL-130
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.notifications import Digest, Severity
from shared.notifications.adapters.whatsapp import (
    WHATSAPP_MAX_CHARS,
    WhatsAppAdapter,
    format_whatsapp_body,
)


# ─────────────────────────────────────────────────────────────────────
# Formatter
# ─────────────────────────────────────────────────────────────────────


class TestFormatter:
    def test_title_only(self):
        body = format_whatsapp_body(Digest(
            client_name="Acme", title="Stock Report", summary="",
        ))
        assert "Stock Report" in body
        # INFO severity gets the info emoji
        assert "ℹ️" in body

    def test_critical_emoji(self):
        body = format_whatsapp_body(Digest(
            client_name="Acme", title="Alerta", summary="",
            severity=Severity.CRITICAL,
        ))
        assert "🚨" in body

    def test_sections_rendered(self):
        digest = Digest(
            client_name="Acme", title="Stock", summary="1 linea",
            sections=[
                {"heading": "URGENTE",
                 "items": [
                     {"text": "TN-324K: 0 uds", "severity": Severity.CRITICAL},
                     {"text": "DR-312: 2 uds", "severity": Severity.HIGH},
                 ]},
                {"heading": "TOP VENDIDO",
                 "items": [{"text": "A4: 45 resmas"}]},
            ],
        )
        body = format_whatsapp_body(digest)
        assert "URGENTE" in body
        assert "TN-324K: 0 uds" in body
        assert "A4: 45 resmas" in body
        assert "🚨" in body

    def test_truncation_respects_max_chars(self):
        long_text = "X" * (WHATSAPP_MAX_CHARS * 2)
        digest = Digest(
            client_name="a", title=long_text, summary="",
        )
        body = format_whatsapp_body(digest)
        assert len(body) <= WHATSAPP_MAX_CHARS
        assert body.endswith("[truncado]")

    def test_custom_max_chars(self):
        body = format_whatsapp_body(
            Digest(client_name="a", title="AAAAAAAAAAA", summary="BBBB"),
            max_chars=10,
        )
        assert len(body) <= 10


# ─────────────────────────────────────────────────────────────────────
# Adapter
# ─────────────────────────────────────────────────────────────────────


class _FakeMessage:
    sid = "SM_test_12345"


class _FakeTwilioClient:
    """Stand-in for twilio.rest.Client."""
    def __init__(self, sid, token):
        self.sid = sid
        self.token = token
        self.messages = self
        self.sent: list[dict] = []

    def create(self, *, body, from_, to):
        self.sent.append({"body": body, "from": from_, "to": to})
        return _FakeMessage()


class TestAdapter:
    async def test_missing_config_fails_cleanly(self):
        adapter = WhatsAppAdapter(
            account_sid="", auth_token="", from_number="",
        )
        result = await adapter.send(
            Digest(client_name="a", title="t", summary="s"), "+123",
        )
        assert result.success is False
        assert "TWILIO" in result.error

    async def test_empty_recipient_rejected(self):
        adapter = WhatsAppAdapter(
            account_sid="sid", auth_token="tok", from_number="+1",
            client_factory=_FakeTwilioClient,
        )
        result = await adapter.send(
            Digest(client_name="a", title="t", summary="s"), "",
        )
        assert result.success is False

    async def test_send_uses_twilio_client(self):
        client = _FakeTwilioClient("sid", "tok")
        adapter = WhatsAppAdapter(
            account_sid="sid", auth_token="tok", from_number="+1555",
            client_factory=lambda s, t: client,
        )
        result = await adapter.send(
            Digest(
                client_name="Acme", title="Stock Report",
                summary="1 urgente", severity=Severity.CRITICAL,
                sections=[{"heading": "URGENTE", "items": [{"text": "TN-324K: 0"}]}],
            ),
            "+543512345678",
        )
        assert result.success is True
        assert "twilio_sid=SM_test_12345" in result.detail

        assert len(client.sent) == 1
        payload = client.sent[0]
        assert payload["from"] == "whatsapp:+1555"
        assert payload["to"] == "whatsapp:+543512345678"
        assert "Stock Report" in payload["body"]
        assert "🚨" in payload["body"]

    async def test_recipient_prefix_preserved_if_present(self):
        client = _FakeTwilioClient("sid", "tok")
        adapter = WhatsAppAdapter(
            account_sid="sid", auth_token="tok", from_number="+1",
            client_factory=lambda s, t: client,
        )
        await adapter.send(
            Digest(client_name="a", title="t", summary="s"),
            "whatsapp:+555",
        )
        assert client.sent[0]["to"] == "whatsapp:+555"

    async def test_twilio_exception_captured(self):
        def _factory(sid, token):
            class _Raiser:
                messages = None
                class _msg:
                    @staticmethod
                    def create(**kwargs):
                        raise RuntimeError("rate limit")
            r = _Raiser()
            r.messages = r._msg()
            return r

        adapter = WhatsAppAdapter(
            account_sid="sid", auth_token="tok", from_number="+1",
            client_factory=_factory,
        )
        result = await adapter.send(
            Digest(client_name="a", title="t", summary="s"), "+555",
        )
        assert result.success is False
        assert "RuntimeError" in result.error
