"""
Tests for digest and quality API endpoints.

Covers:
  GET  /api/jobs/{job_id}/digest          — preview HTML email digest
  POST /api/jobs/{job_id}/send-digest     — send digest via SMTP (or report smtp_not_configured)
  GET  /api/jobs/{job_id}/quality         — data quality report for a job
"""

from __future__ import annotations

import json
import sys
import types
import asyncio
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

def _make_stub(name):
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


def _stub_missing(*names):
    for name in names:
        if name not in sys.modules:
            sys.modules[name] = _make_stub(name)
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            child_attr = parts[i]
            if parent not in sys.modules:
                sys.modules[parent] = _make_stub(parent)
            parent_mod = sys.modules[parent]
            child_mod = sys.modules.get(".".join(parts[: i + 1]))
            if child_mod is not None and not hasattr(parent_mod, child_attr):
                setattr(parent_mod, child_attr, child_mod)


_stub_missing("supabase")
sys.modules["supabase"].create_client = MagicMock(return_value=MagicMock())
sys.modules["supabase"].Client = MagicMock

_stub_missing("slowapi", "slowapi.util", "slowapi.errors")


class _FakeLimiter:
    def __init__(self, *a, **kw):
        pass

    def limit(self, *a, **kw):
        return lambda f: f

    def __call__(self, *a, **kw):
        return self


sys.modules["slowapi"].Limiter = _FakeLimiter
sys.modules["slowapi"]._rate_limit_exceeded_handler = MagicMock()
sys.modules["slowapi.util"].get_remote_address = MagicMock(return_value="127.0.0.1")


class _FakeRateLimitExceeded(Exception):
    pass


sys.modules["slowapi.errors"].RateLimitExceeded = _FakeRateLimitExceeded

_stub_missing("structlog")
sys.modules["structlog"].get_logger = lambda *a, **kw: MagicMock()

_stub_missing("adapters", "adapters.valinor_adapter")
sys.modules["adapters.valinor_adapter"].ValinorAdapter = MagicMock
sys.modules["adapters.valinor_adapter"].PipelineExecutor = MagicMock

_stub_missing("shared.storage")
sys.modules["shared.storage"].MetadataStorage = MagicMock

for _m in ("shared.memory", "shared.memory.profile_store", "shared.memory.client_profile"):
    _stub_missing(_m)

_ps = sys.modules["shared.memory.profile_store"]
_ps.get_profile_store = MagicMock(return_value=MagicMock(
    _get_pool=AsyncMock(return_value=None),
    load=AsyncMock(return_value=None),
    load_or_create=AsyncMock(return_value=MagicMock(webhooks=[], alert_thresholds=[])),
    save=AsyncMock(),
))

_sh = sys.modules.get("shared")
if _sh:
    _sh.memory = sys.modules.get("shared.memory")
    _shm = sys.modules.get("shared.memory")
    if _shm:
        _shm.profile_store = sys.modules.get("shared.memory.profile_store")

_stub_missing("shared.pdf_generator")
sys.modules["shared.pdf_generator"].generate_pdf_report = MagicMock(return_value=b"%PDF-1.4")

# ---------------------------------------------------------------------------
# Import app after stubs
# ---------------------------------------------------------------------------
from api.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _make_redis_mock():
    m = AsyncMock()
    m.ping = AsyncMock(return_value=True)
    m.hgetall = AsyncMock(return_value={})
    m.hget = AsyncMock(return_value=None)
    m.hset = AsyncMock(return_value=True)
    m.expire = AsyncMock(return_value=True)
    m.get = AsyncMock(return_value=None)
    m.info = AsyncMock(return_value={"redis_version": "7.0.0", "uptime_in_days": 1})
    m.close = AsyncMock()

    async def _empty_scan(*a, **kw):
        return
        yield

    m.scan_iter = _empty_scan
    return m


def _minimal_results(**overrides) -> bytes:
    """Return JSON-encoded minimal job results payload."""
    base = {
        "client_name": "Acme Corp",
        "period": "Q1 2026",
        "run_delta": {"new": [], "resolved": []},
        "findings": {},
        "triggered_alerts": None,
        "data_quality": None,
        "currency_warnings": {},
        "stages": {},
    }
    base.update(overrides)
    return json.dumps(base).encode()


def _results_with_dq(**dq_overrides) -> bytes:
    dq = {
        "score": 88,
        "confidence_label": "ALTA",
        "tag": "GOLD",
        "decision": "PROCEED",
        "gate_decision": "PROCEED",
        "checks": [],
    }
    dq.update(dq_overrides)
    return _minimal_results(data_quality=dq)


def _results_with_findings() -> bytes:
    findings = {
        "analyst": {
            "findings": [
                {"id": "F1", "title": "Revenue drop", "severity": "CRITICAL"},
                {"id": "F2", "title": "Churn spike", "severity": "HIGH"},
                {"id": "F3", "title": "Low NPS", "severity": "MEDIUM"},
            ]
        }
    }
    return _minimal_results(findings=findings)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    redis_mock = _make_redis_mock()
    storage_mock = MagicMock()
    storage_mock.health_check = AsyncMock(return_value=True)
    with (
        patch("redis.asyncio.from_url", return_value=redis_mock),
        patch("api.main.metadata_storage", storage_mock),
        patch("api.main.redis_client", redis_mock),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c


# ===========================================================================
# GET /api/jobs/{job_id}/digest
# ===========================================================================

@pytest.mark.asyncio
async def test_digest_job_not_found_returns_404(client):
    """When Redis has no results for the job, digest returns 404."""
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=None)
        r = await client.get("/api/jobs/nonexistent-job/digest")
    assert r.status_code == 404
    body = r.json()
    assert body  # some error body is returned


@pytest.mark.asyncio
async def test_digest_returns_html_response(client):
    """Completed job returns an HTML response."""
    raw = _minimal_results()
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-123/digest")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_digest_html_contains_client_name(client):
    """HTML digest contains the client name from job results."""
    raw = _minimal_results(client_name="Acme Corp")
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-123/digest")
    assert r.status_code == 200
    assert "Acme Corp" in r.text


@pytest.mark.asyncio
async def test_digest_html_contains_period(client):
    """HTML digest contains the analysis period."""
    raw = _minimal_results(period="Q1 2026")
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-123/digest")
    assert r.status_code == 200
    assert "Q1 2026" in r.text


@pytest.mark.asyncio
async def test_digest_html_with_findings(client):
    """Digest HTML includes findings when present in results."""
    raw = _results_with_findings()
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-abc/digest")
    assert r.status_code == 200
    # HTML should reference critical findings
    assert "Revenue drop" in r.text or "CRITICAL" in r.text


@pytest.mark.asyncio
async def test_digest_html_with_data_quality(client):
    """When data quality info is present, it is rendered in the digest."""
    raw = _results_with_dq(score=92)
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-dq/digest")
    assert r.status_code == 200
    # Score should appear in the HTML
    assert "92" in r.text


@pytest.mark.asyncio
async def test_digest_html_with_triggered_alerts(client):
    """Triggered alerts section is rendered when alerts are present."""
    alerts = [{"metric": "revenue", "severity": "CRITICAL", "computed_value": -25.0,
               "threshold_value": -10.0, "name": "Revenue Alert", "operator": "<"}]
    raw = _minimal_results(triggered_alerts=alerts)
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-alerts/digest")
    assert r.status_code == 200
    assert "Revenue Alert" in r.text or "ALERTAS" in r.text


@pytest.mark.asyncio
async def test_digest_html_default_client_name(client):
    """When client_name is absent from results, defaults to 'Cliente'."""
    base = {
        "period": "Q1 2026",
        "run_delta": {},
        "findings": {},
    }
    raw = json.dumps(base).encode()
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-noname/digest")
    assert r.status_code == 200
    assert "Cliente" in r.text


# ===========================================================================
# POST /api/jobs/{job_id}/send-digest
# ===========================================================================

@pytest.mark.asyncio
async def test_send_digest_job_not_found_returns_404(client):
    """When no results exist for job, send-digest returns 404."""
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=None)
        r = await client.post("/api/jobs/missing-job/send-digest?to_email=test@example.com")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_send_digest_without_email_returns_422(client):
    """Missing to_email query param returns 422."""
    r = await client.post("/api/jobs/job-123/send-digest")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_send_digest_smtp_not_configured(client):
    """When SMTP_HOST is not set, returns smtp_not_configured status."""
    raw = _minimal_results()
    with (
        patch("api.main.redis_client") as rm,
        patch.dict("os.environ", {}, clear=False),
        patch("api.email_digest.send_digest", new=AsyncMock(return_value=False)),
    ):
        rm.get = AsyncMock(return_value=raw)
        r = await client.post("/api/jobs/job-123/send-digest?to_email=user@example.com")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("sent", "smtp_not_configured")
    assert body["to"] == "user@example.com"


@pytest.mark.asyncio
async def test_send_digest_smtp_configured_returns_sent(client):
    """When send_digest returns True, status is 'sent'."""
    raw = _minimal_results()
    with (
        patch("api.main.redis_client") as rm,
        patch("api.email_digest.send_digest", new=AsyncMock(return_value=True)),
    ):
        rm.get = AsyncMock(return_value=raw)
        r = await client.post("/api/jobs/job-456/send-digest?to_email=boss@corp.com")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent"
    assert body["to"] == "boss@corp.com"


@pytest.mark.asyncio
async def test_send_digest_returns_correct_recipient(client):
    """Response always echoes back the to_email address."""
    raw = _minimal_results()
    with (
        patch("api.main.redis_client") as rm,
        patch("api.email_digest.send_digest", new=AsyncMock(return_value=False)),
    ):
        rm.get = AsyncMock(return_value=raw)
        r = await client.post("/api/jobs/job-789/send-digest?to_email=specific@test.io")
    assert r.status_code == 200
    assert r.json()["to"] == "specific@test.io"


@pytest.mark.asyncio
async def test_send_digest_with_findings_and_dq(client):
    """Send-digest with findings + DQ data completes without error."""
    raw = _results_with_dq(score=75)
    with (
        patch("api.main.redis_client") as rm,
        patch("api.email_digest.send_digest", new=AsyncMock(return_value=False)),
    ):
        rm.get = AsyncMock(return_value=raw)
        r = await client.post("/api/jobs/job-complex/send-digest?to_email=cto@acme.com")
    assert r.status_code == 200


# ===========================================================================
# GET /api/jobs/{job_id}/quality
# ===========================================================================

@pytest.mark.asyncio
async def test_quality_job_not_found_returns_404(client):
    """When no results exist for job, quality returns 404."""
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=None)
        r = await client.get("/api/jobs/ghost-job/quality")
    assert r.status_code == 404
    body = r.json()
    assert body  # some error body is returned


@pytest.mark.asyncio
async def test_quality_no_dq_returns_null_with_message(client):
    """Job with no data_quality key returns null dq and a message."""
    raw = _minimal_results(data_quality=None)
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-nodq/quality")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-nodq"
    assert body["data_quality"] is None
    assert "message" in body


@pytest.mark.asyncio
async def test_quality_returns_dq_report(client):
    """Job with data_quality returns the DQ object."""
    dq = {"score": 92, "decision": "PROCEED", "checks": [], "label": "ALTA"}
    raw = _results_with_dq(**dq)
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-dq/quality")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == "job-dq"
    assert body["data_quality"] is not None
    assert body["data_quality"]["score"] == 92


@pytest.mark.asyncio
async def test_quality_includes_currency_warnings(client):
    """Quality response includes currency_warnings field."""
    raw = _minimal_results(
        data_quality={"score": 80, "decision": "PROCEED_WITH_WARNINGS"},
        currency_warnings={"orders": "stale 48h"},
    )
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-cw/quality")
    assert r.status_code == 200
    body = r.json()
    assert "currency_warnings" in body
    assert body["currency_warnings"].get("orders") == "stale 48h"


@pytest.mark.asyncio
async def test_quality_includes_snapshot_timestamp(client):
    """Quality response includes snapshot_timestamp from stages."""
    stages = {"query_execution": {"snapshot_timestamp": "2026-03-21T10:00:00Z"}}
    raw = _minimal_results(
        data_quality={"score": 85, "decision": "PROCEED"},
        stages=stages,
    )
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-snap/quality")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot_timestamp"] == "2026-03-21T10:00:00Z"


@pytest.mark.asyncio
async def test_quality_snapshot_timestamp_none_when_absent(client):
    """snapshot_timestamp is None when stages data is absent."""
    raw = _minimal_results(data_quality={"score": 70, "decision": "PROCEED_WITH_WARNINGS"})
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-nosnap/quality")
    assert r.status_code == 200
    assert r.json()["snapshot_timestamp"] is None


@pytest.mark.asyncio
async def test_quality_job_id_echoed_in_response(client):
    """The job_id in the response matches the requested job."""
    raw = _minimal_results(data_quality={"score": 100, "decision": "PROCEED"})
    job_id = "unique-job-id-xyz"
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get(f"/api/jobs/{job_id}/quality")
    assert r.status_code == 200
    assert r.json()["job_id"] == job_id


# ===========================================================================
# Additional tests — edge cases and extra coverage
# ===========================================================================

@pytest.mark.asyncio
async def test_digest_html_empty_findings(client):
    """Digest renders without error when findings dict is empty."""
    raw = _minimal_results(findings={})
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-empty-findings/digest")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


@pytest.mark.asyncio
async def test_digest_html_no_triggered_alerts(client):
    """Digest renders without error when triggered_alerts is None."""
    raw = _minimal_results(triggered_alerts=None)
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-no-alerts/digest")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_digest_html_empty_triggered_alerts_list(client):
    """Digest renders correctly when triggered_alerts is an empty list."""
    raw = _minimal_results(triggered_alerts=[])
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-empty-alerts/digest")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_send_digest_missing_email_with_job_that_exists_returns_422(client):
    """When job exists but to_email param is missing, the response is 422."""
    raw = _minimal_results()
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.post("/api/jobs/job-123/send-digest")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_quality_gate_decision_absent_defaults_gracefully(client):
    """DQ report missing 'gate_decision' key is still returned without 500."""
    dq = {"score": 65, "decision": "PROCEED_WITH_WARNINGS", "checks": []}
    raw = _results_with_dq(**dq)
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-no-gate/quality")
    assert r.status_code == 200
    assert r.json()["data_quality"] is not None


@pytest.mark.asyncio
async def test_quality_with_failed_checks(client):
    """DQ report containing failed checks is returned without 500."""
    checks = [
        {"name": "null_ratio", "passed": False, "severity": "CRITICAL", "detail": "30% nulls"},
        {"name": "pk_uniqueness", "passed": True, "severity": "HIGH", "detail": "ok"},
    ]
    raw = _results_with_dq(score=40, checks=checks)
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-failed-checks/quality")
    assert r.status_code == 200
    body = r.json()
    assert body["data_quality"]["score"] == 40


@pytest.mark.asyncio
async def test_digest_html_with_empty_currency_warnings(client):
    """Digest renders without error when currency_warnings is an empty dict."""
    raw = _minimal_results(currency_warnings={})
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-no-currency/digest")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_quality_currency_warnings_empty_dict(client):
    """Quality endpoint returns empty dict for currency_warnings when none exist."""
    raw = _minimal_results(
        data_quality={"score": 95, "decision": "PROCEED"},
        currency_warnings={},
    )
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-no-cw/quality")
    assert r.status_code == 200
    assert r.json()["currency_warnings"] == {}


@pytest.mark.asyncio
async def test_quality_score_zero_is_valid(client):
    """A DQ score of 0 is a valid response (worst quality gate result)."""
    raw = _results_with_dq(score=0, decision="ABORT")
    with patch("api.main.redis_client") as rm:
        rm.get = AsyncMock(return_value=raw)
        r = await client.get("/api/jobs/job-zero-score/quality")
    assert r.status_code == 200
    assert r.json()["data_quality"]["score"] == 0


@pytest.mark.asyncio
async def test_send_digest_with_empty_findings(client):
    """Sending a digest for a job with empty findings completes without error."""
    raw = _minimal_results(findings={}, triggered_alerts=[])
    with (
        patch("api.main.redis_client") as rm,
        patch("api.email_digest.send_digest", new=AsyncMock(return_value=False)),
    ):
        rm.get = AsyncMock(return_value=raw)
        r = await client.post("/api/jobs/job-empty/send-digest?to_email=ops@example.com")
    assert r.status_code == 200
    assert r.json()["to"] == "ops@example.com"
