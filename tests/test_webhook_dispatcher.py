"""
Unit tests for WebhookDispatcher.

All HTTP interactions are mocked via unittest.mock — no real network calls.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.memory.client_profile import ClientProfile
from shared.webhook_dispatcher import WebhookDispatcher, create_webhook_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_profile(webhooks=None) -> ClientProfile:
    profile = ClientProfile(client_name="Acme Corp")
    profile.webhooks = webhooks or []
    return profile


def make_webhook(url="https://example.com/hook", events=None, secret=""):
    return {"url": url, "events": events or ["analysis_completed"], "secret": secret}


def _expected_hmac(payload: dict, secret: str) -> str:
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    key = secret.encode("utf-8") if secret else b""
    return hmac.new(key, payload_bytes, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def dispatcher() -> WebhookDispatcher:
    return WebhookDispatcher()


@pytest.fixture
def sample_payload() -> dict:
    return create_webhook_payload(
        "analysis_completed",
        {"job_id": "job-123", "findings_count": 5},
        "Acme Corp",
    )


# ---------------------------------------------------------------------------
# Test: dispatch sends POST to matching webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_sends_to_matching_webhook(dispatcher, sample_payload):
    """A webhook subscribed to analysis_completed receives a POST with correct URL and headers."""
    profile = make_profile(webhooks=[make_webhook(url="https://hooks.example.com/valinor")])

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)

    assert len(results) == 1
    result = results[0]
    assert result["url"] == "https://hooks.example.com/valinor"
    assert result["status"] == 200
    assert result["success"] is True

    # Verify POST was called
    mock_session.post.assert_called_once()
    call_kwargs = mock_session.post.call_args

    # URL is the first positional argument
    called_url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("url")
    assert called_url == "https://hooks.example.com/valinor"

    # Check headers
    headers = call_kwargs[1].get("headers") or {}
    assert headers.get("X-Valinor-Event") == "analysis_completed"
    assert "X-Valinor-Signature" in headers
    assert headers.get("Content-Type") == "application/json"


# ---------------------------------------------------------------------------
# Test: dispatch skips non-matching event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_skips_non_matching_event(dispatcher, sample_payload):
    """A webhook subscribed only to dq_gate_failed must not be called for analysis_completed."""
    profile = make_profile(webhooks=[
        make_webhook(url="https://hooks.example.com/dq", events=["dq_gate_failed"])
    ])

    with patch("aiohttp.ClientSession") as mock_cls:
        results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)

    # No delivery attempted
    assert results == []
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Test: wildcard subscription receives all events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_wildcard_subscription(dispatcher):
    """A webhook with events=["*"] receives every event type."""
    profile = make_profile(webhooks=[
        make_webhook(url="https://hooks.example.com/all", events=["*"])
    ])

    for event_type in ["analysis_completed", "finding_critical", "dq_gate_failed", "alert_triggered"]:
        payload = create_webhook_payload(event_type, {"detail": "test"}, "Acme Corp")

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            results = await dispatcher.dispatch(profile, event_type, payload)

        assert len(results) == 1, f"Wildcard webhook should fire for event '{event_type}'"
        assert results[0]["success"] is True


# ---------------------------------------------------------------------------
# Test: HMAC signature is correct
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hmac_signature_correct(dispatcher):
    """X-Valinor-Signature must be the HMAC-SHA256 of the JSON payload using the webhook secret."""
    secret = "super-secret-key"
    profile = make_profile(webhooks=[
        make_webhook(url="https://hooks.example.com/signed", events=["finding_critical"], secret=secret)
    ])
    payload = create_webhook_payload("finding_critical", {"severity": "CRITICAL"}, "Acme Corp")

    captured_headers: dict = {}

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()

    def _capture_post(url, data=None, headers=None, **kwargs):
        captured_headers.update(headers or {})
        # Also capture the raw payload bytes so we can verify the HMAC
        captured_headers["_raw_data"] = data
        return mock_response

    mock_session.post = MagicMock(side_effect=_capture_post)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "finding_critical", payload)

    assert len(results) == 1
    assert results[0]["success"] is True

    delivered_bytes: bytes = captured_headers["_raw_data"]
    delivered_payload = json.loads(delivered_bytes.decode("utf-8"))

    expected_sig = _expected_hmac(delivered_payload, secret)
    actual_sig = captured_headers.get("X-Valinor-Signature", "")
    assert actual_sig == expected_sig, (
        f"HMAC mismatch: expected {expected_sig}, got {actual_sig}"
    )


# ---------------------------------------------------------------------------
# Test: timeout handled gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_timeout_handled_gracefully(dispatcher, sample_payload):
    """When aiohttp raises asyncio.TimeoutError the result must have success=False, not raise."""
    profile = make_profile(webhooks=[
        make_webhook(url="https://slow.example.com/hook", events=["analysis_completed"])
    ])

    mock_response = MagicMock()
    mock_response.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)

    assert len(results) == 1
    result = results[0]
    assert result["success"] is False
    assert result["status"] is None
    assert result["error"] is not None
