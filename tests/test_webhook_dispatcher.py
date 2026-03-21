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


# ---------------------------------------------------------------------------
# Test: empty webhooks list returns empty results
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_empty_webhooks_returns_empty(dispatcher, sample_payload):
    """dispatch with no webhooks returns empty list without error."""
    profile = make_profile(webhooks=[])
    results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)
    assert results == []


# ---------------------------------------------------------------------------
# Test: webhook with no URL is skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_skips_webhook_without_url(dispatcher, sample_payload):
    """Webhooks with missing or empty URL are skipped."""
    profile = make_profile(webhooks=[{"url": "", "events": ["analysis_completed"]}])
    results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)
    assert results == []


# ---------------------------------------------------------------------------
# Test: multiple webhooks — only matching ones are called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_multiple_webhooks_only_matching(dispatcher, sample_payload):
    """When multiple webhooks are registered, only the ones matching the event fire."""
    profile = make_profile(webhooks=[
        make_webhook(url="https://a.example.com", events=["analysis_completed"]),
        make_webhook(url="https://b.example.com", events=["dq_gate_failed"]),
        make_webhook(url="https://c.example.com", events=["analysis_completed", "alert_triggered"]),
    ])

    call_urls = []

    def _mock_post(url, data=None, headers=None, **kwargs):
        call_urls.append(url)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=_mock_post)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)

    assert len(results) == 2
    assert all(r["success"] for r in results)
    assert "https://a.example.com" in call_urls
    assert "https://c.example.com" in call_urls
    assert "https://b.example.com" not in call_urls


# ---------------------------------------------------------------------------
# Test: 500 response is not success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_500_response_is_failure(dispatcher, sample_payload):
    """A 500 HTTP response should be reported as success=False."""
    profile = make_profile(webhooks=[make_webhook(events=["analysis_completed"])])

    mock_resp = MagicMock()
    mock_resp.status = 500
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["status"] == 500


# ---------------------------------------------------------------------------
# Test: connection error triggers retry then fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_connection_error_retries_once(dispatcher, sample_payload):
    """ClientConnectionError triggers one retry; after two failures success=False."""
    profile = make_profile(webhooks=[make_webhook(events=["analysis_completed"])])

    call_count = 0

    def _raise_connection_error(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientConnectionError("refused"))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return mock_ctx

    import aiohttp
    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=_raise_connection_error)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert "ConnectionError" in results[0]["error"]
    # Two attempts (initial + 1 retry)
    assert call_count == 2


# ---------------------------------------------------------------------------
# Test: create_webhook_payload structure
# ---------------------------------------------------------------------------

def test_create_webhook_payload_has_required_fields():
    """create_webhook_payload must contain event_type, client_name, timestamp, version, data."""
    payload = create_webhook_payload("analysis_completed", {"job_id": "j1"}, "Acme")
    assert payload["event_type"] == "analysis_completed"
    assert payload["client_name"] == "Acme"
    assert payload["version"] == "1.0"
    assert "timestamp" in payload
    assert payload["data"]["job_id"] == "j1"


def test_create_webhook_payload_data_is_passthrough():
    """The data dict is passed through unchanged."""
    data = {"findings": 3, "severity": "HIGH", "nested": {"x": 1}}
    payload = create_webhook_payload("alert_triggered", data, "Beta")
    assert payload["data"] == data


def test_create_webhook_payload_timestamp_is_iso():
    """Timestamp must be a valid ISO-8601 string."""
    from datetime import datetime
    payload = create_webhook_payload("dq_gate_failed", {}, "Gamma")
    ts = payload["timestamp"]
    # Should be parseable
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert dt is not None


# ---------------------------------------------------------------------------
# Test: compute_hmac helper
# ---------------------------------------------------------------------------

def test_compute_hmac_is_deterministic():
    """_compute_hmac must return the same value for the same inputs."""
    from shared.webhook_dispatcher import _compute_hmac
    data = b'{"test": true}'
    secret = "my-secret"
    h1 = _compute_hmac(data, secret)
    h2 = _compute_hmac(data, secret)
    assert h1 == h2


def test_compute_hmac_changes_with_data():
    """_compute_hmac must differ when data changes."""
    from shared.webhook_dispatcher import _compute_hmac
    h1 = _compute_hmac(b"data1", "secret")
    h2 = _compute_hmac(b"data2", "secret")
    assert h1 != h2


def test_compute_hmac_changes_with_secret():
    """_compute_hmac must differ when secret changes."""
    from shared.webhook_dispatcher import _compute_hmac
    h1 = _compute_hmac(b"data", "secret1")
    h2 = _compute_hmac(b"data", "secret2")
    assert h1 != h2


def test_compute_hmac_empty_secret_still_works():
    """_compute_hmac with empty secret uses empty bytes key and still returns a hex string."""
    from shared.webhook_dispatcher import _compute_hmac
    result = _compute_hmac(b"payload", "")
    assert isinstance(result, str)
    assert len(result) == 64  # SHA256 hex = 64 chars


# ---------------------------------------------------------------------------
# Test: SUPPORTED_EVENTS constant
# ---------------------------------------------------------------------------

def test_supported_events_contains_expected():
    """SUPPORTED_EVENTS must include all documented event types."""
    from shared.webhook_dispatcher import SUPPORTED_EVENTS
    for event in ["analysis_completed", "finding_critical", "dq_gate_failed", "alert_triggered"]:
        assert event in SUPPORTED_EVENTS


# ---------------------------------------------------------------------------
# Test: profile with None webhooks is handled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_none_webhooks_returns_empty(dispatcher, sample_payload):
    """dispatch with webhooks=None on profile should return empty list."""
    profile = make_profile(webhooks=None)
    results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)
    assert results == []


# ---------------------------------------------------------------------------
# Test: 201 response is success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_201_response_is_success(dispatcher, sample_payload):
    """A 201 response (Created) is within the 2xx range and must be success=True."""
    profile = make_profile(webhooks=[make_webhook(events=["analysis_completed"])])

    mock_resp = MagicMock()
    mock_resp.status = 201
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", sample_payload)

    assert results[0]["success"] is True
    assert results[0]["status"] == 201


# ---------------------------------------------------------------------------
# Test 21: payload contains all five required keys
# ---------------------------------------------------------------------------

def test_create_webhook_payload_all_required_keys():
    """create_webhook_payload must include exactly the five required keys."""
    payload = create_webhook_payload("dq_gate_failed", {"score": 42}, "ClientX")
    required = {"event_type", "client_name", "timestamp", "version", "data"}
    assert required.issubset(set(payload.keys()))


# ---------------------------------------------------------------------------
# Test 22: HMAC changes when payload content changes
# ---------------------------------------------------------------------------

def test_compute_hmac_different_payload_different_signature():
    """Two payloads with different data must produce different HMAC signatures."""
    from shared.webhook_dispatcher import _compute_hmac
    secret = "stable-secret"
    sig1 = _compute_hmac(json.dumps({"a": 1}).encode(), secret)
    sig2 = _compute_hmac(json.dumps({"a": 2}).encode(), secret)
    assert sig1 != sig2


# ---------------------------------------------------------------------------
# Test 23: two webhooks subscribed to different events — each fires for its own event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_two_webhooks_different_events(dispatcher):
    """Each webhook fires only when its specific event is dispatched."""
    profile = make_profile(webhooks=[
        make_webhook(url="https://w1.example.com", events=["analysis_completed"]),
        make_webhook(url="https://w2.example.com", events=["dq_gate_failed"]),
    ])

    def _make_mock_session(captured_urls):
        def _mock_post(url, data=None, headers=None, **kwargs):
            captured_urls.append(url)
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
            return mock_resp

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=_mock_post)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    # Fire analysis_completed — only w1 should be called
    urls_for_completed = []
    mock_session_1 = _make_mock_session(urls_for_completed)
    payload_1 = create_webhook_payload("analysis_completed", {}, "X")
    with patch("aiohttp.ClientSession", return_value=mock_session_1):
        results = await dispatcher.dispatch(profile, "analysis_completed", payload_1)
    assert len(results) == 1
    assert "https://w1.example.com" in urls_for_completed
    assert "https://w2.example.com" not in urls_for_completed

    # Fire dq_gate_failed — only w2 should be called
    urls_for_dq = []
    mock_session_2 = _make_mock_session(urls_for_dq)
    payload_2 = create_webhook_payload("dq_gate_failed", {}, "X")
    with patch("aiohttp.ClientSession", return_value=mock_session_2):
        results = await dispatcher.dispatch(profile, "dq_gate_failed", payload_2)
    assert len(results) == 1
    assert "https://w2.example.com" in urls_for_dq
    assert "https://w1.example.com" not in urls_for_dq


# ---------------------------------------------------------------------------
# Test 24: event matching is case-sensitive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_event_matching_is_case_sensitive(dispatcher):
    """Event subscription matching must be case-sensitive."""
    profile = make_profile(webhooks=[
        make_webhook(url="https://cs.example.com", events=["analysis_completed"])
    ])
    payload = create_webhook_payload("Analysis_Completed", {}, "Y")

    with patch("aiohttp.ClientSession") as mock_cls:
        results = await dispatcher.dispatch(profile, "Analysis_Completed", payload)

    assert results == []
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Test 25: webhook with empty URL is skipped even if events match
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_empty_url_skipped_regardless_of_event(dispatcher):
    """A webhook dict with url='' must be skipped no matter which event fires."""
    profile = make_profile(webhooks=[
        {"url": "", "events": ["*"], "secret": ""},
        {"url": "", "events": ["analysis_completed"], "secret": ""},
    ])
    payload = create_webhook_payload("analysis_completed", {}, "Z")

    with patch("aiohttp.ClientSession") as mock_cls:
        results = await dispatcher.dispatch(profile, "analysis_completed", payload)

    assert results == []
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Test 26: aiohttp session raises asyncio.TimeoutError — error field not None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_timeout_error_field_not_none(dispatcher):
    """When aiohttp raises TimeoutError, the result error field must be a non-empty string."""
    profile = make_profile(webhooks=[make_webhook(events=["analysis_completed"])])
    payload = create_webhook_payload("analysis_completed", {}, "Client")

    mock_response = MagicMock()
    mock_response.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError("timed out"))
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", payload)

    assert len(results) == 1
    assert results[0]["success"] is False
    assert results[0]["status"] is None
    assert results[0]["error"] is not None
    assert len(results[0]["error"]) > 0


# ---------------------------------------------------------------------------
# Test 27: mix of success and failure across multiple webhooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_mixed_success_failure(dispatcher):
    """Dispatch to three webhooks where one returns 200 and one returns 500 and one times out."""
    import aiohttp as _aiohttp

    profile = make_profile(webhooks=[
        make_webhook(url="https://ok.example.com", events=["analysis_completed"]),
        make_webhook(url="https://fail.example.com", events=["analysis_completed"]),
        make_webhook(url="https://timeout.example.com", events=["analysis_completed"]),
    ])
    payload = create_webhook_payload("analysis_completed", {}, "Mixed")

    def _mock_post(url, data=None, headers=None, **kwargs):
        mock_resp = MagicMock()
        if "ok" in url:
            mock_resp.status = 200
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
        elif "fail" in url:
            mock_resp.status = 503
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=False)
        else:
            mock_resp.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=_mock_post)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", payload)

    assert len(results) == 3
    by_url = {r["url"]: r for r in results}
    assert by_url["https://ok.example.com"]["success"] is True
    assert by_url["https://fail.example.com"]["success"] is False
    assert by_url["https://fail.example.com"]["status"] == 503
    assert by_url["https://timeout.example.com"]["success"] is False


# ---------------------------------------------------------------------------
# Test 28: connection error triggers exactly two attempts (one retry)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_connection_error_exactly_two_attempts(dispatcher):
    """ClientConnectionError causes exactly 2 attempts (initial + one retry)."""
    import aiohttp as _aiohttp

    profile = make_profile(webhooks=[make_webhook(events=["analysis_completed"])])
    payload = create_webhook_payload("analysis_completed", {}, "R")

    call_count = 0

    def _raise_conn_err(url, data=None, headers=None, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=_aiohttp.ClientConnectionError("refused"))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return mock_ctx

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=_raise_conn_err)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", payload)

    assert call_count == 2
    assert results[0]["success"] is False


# ---------------------------------------------------------------------------
# Test 29: webhook dict schema — required keys are url, events, secret
# ---------------------------------------------------------------------------

def test_make_webhook_has_required_keys():
    """The helper make_webhook produces dicts with url, events, and secret keys."""
    wh = make_webhook()
    assert "url" in wh
    assert "events" in wh
    assert "secret" in wh


# ---------------------------------------------------------------------------
# Test 30: delivery result dict contains all four required keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_result_has_all_required_keys(dispatcher):
    """Each delivery result dict must have url, status, success, error keys."""
    profile = make_profile(webhooks=[make_webhook(events=["analysis_completed"])])
    payload = create_webhook_payload("analysis_completed", {}, "Keys")

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", payload)

    assert len(results) == 1
    result = results[0]
    assert "url" in result
    assert "status" in result
    assert "success" in result
    assert "error" in result


# ---------------------------------------------------------------------------
# Test 31: SUPPORTED_EVENTS is a frozenset (immutable)
# ---------------------------------------------------------------------------

def test_supported_events_is_frozenset():
    """SUPPORTED_EVENTS must be a frozenset to prevent accidental mutation."""
    from shared.webhook_dispatcher import SUPPORTED_EVENTS
    assert isinstance(SUPPORTED_EVENTS, frozenset)


# ---------------------------------------------------------------------------
# Test 32: HMAC signature with empty-string secret is 64 hex chars
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_hmac_header_present_when_no_secret(dispatcher):
    """Even without a secret, X-Valinor-Signature header is present and 64 chars long."""
    profile = make_profile(webhooks=[make_webhook(events=["analysis_completed"], secret="")])
    payload = create_webhook_payload("analysis_completed", {"k": "v"}, "NoSecret")

    captured_headers: dict = {}

    def _capture_post(url, data=None, headers=None, **kwargs):
        captured_headers.update(headers or {})
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=_capture_post)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        results = await dispatcher.dispatch(profile, "analysis_completed", payload)

    assert results[0]["success"] is True
    sig = captured_headers.get("X-Valinor-Signature", "")
    assert len(sig) == 64  # SHA-256 hex digest is always 64 chars
