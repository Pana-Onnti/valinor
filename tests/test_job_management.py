"""
Tests for job management endpoints in api/main.py:
  - POST /api/jobs/{id}/cancel   (lines 2458-2474)
  - POST /api/jobs/{id}/retry    (lines 2477-2508)
  - DELETE /api/jobs/cleanup     (lines 2511-2532)
  - GET /api/cache/stats         (lines 912-932)
  - GET /api/jobs                (lines 998-1077)
  - GET /api/jobs/{id}/export/pdf (lines 838-909)
  - GET /api/clients/{c}/dq-history (lines 1608-1641)
  - GET /api/clients/{c}/kpis       (lines 1644-1680)
  - GET /api/clients/{c}/stats      (lines 1683-1731)
  - GET /api/clients/{c}/analytics  (lines 1734-1811)
"""

import sys
import types
import json
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import httpx

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Dependency stubs — must be installed before importing api.main
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


def _stub_missing(*names: str) -> None:
    for name in names:
        if name not in sys.modules:
            sys.modules[name] = _make_stub(name)
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            child_key = ".".join(parts[: i + 1])
            if parent not in sys.modules:
                sys.modules[parent] = _make_stub(parent)
            parent_mod = sys.modules[parent]
            child_mod = sys.modules.get(child_key)
            if child_mod is not None and not hasattr(parent_mod, parts[i]):
                setattr(parent_mod, parts[i], child_mod)


# supabase
_stub_missing("supabase")
sys.modules["supabase"].create_client = MagicMock(return_value=MagicMock())
sys.modules["supabase"].Client = MagicMock

# slowapi
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


class _FakeRLE(Exception):
    pass


sys.modules["slowapi.errors"].RateLimitExceeded = _FakeRLE

# structlog
import structlog  # real module — stub breaks structlog.contextvars
structlog.get_logger = lambda *a, **kw: MagicMock()

# adapters
_stub_missing("adapters", "adapters.valinor_adapter")
sys.modules["adapters.valinor_adapter"].ValinorAdapter = MagicMock
sys.modules["adapters.valinor_adapter"].PipelineExecutor = MagicMock

# shared.storage
_stub_missing("shared.storage")
sys.modules["shared.storage"].MetadataStorage = MagicMock

# shared.memory / profile_store
for _m in ("shared.memory", "shared.memory.profile_store", "shared.memory.client_profile"):
    _stub_missing(_m)

_ps = sys.modules["shared.memory.profile_store"]
_ps.get_profile_store = MagicMock(
    return_value=MagicMock(
        _get_pool=AsyncMock(return_value=None),
        load=AsyncMock(return_value=None),
        load_or_create=AsyncMock(
            return_value=MagicMock(webhooks=[], alert_thresholds=[])
        ),
        save=AsyncMock(),
    )
)

_sh = sys.modules.get("shared")
if _sh:
    _sh.memory = sys.modules.get("shared.memory")
    _shm = sys.modules.get("shared.memory")
    if _shm:
        _shm.profile_store = _ps

# shared.pdf_generator
_stub_missing("shared.pdf_generator")
sys.modules["shared.pdf_generator"].generate_pdf_report = MagicMock(
    return_value=b"%PDF-1.4 fake"
)

# ---------------------------------------------------------------------------
# Import the app after stubs are in place
# ---------------------------------------------------------------------------
from api.main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_redis_mock(job_data: dict | None = None):
    """Return a fully-stubbed async Redis mock."""
    m = AsyncMock()
    m.ping = AsyncMock(return_value=True)
    m.hgetall = AsyncMock(return_value=job_data or {})
    m.hget = AsyncMock(return_value=None)
    m.hset = AsyncMock(return_value=True)
    m.expire = AsyncMock(return_value=True)
    m.get = AsyncMock(return_value=None)
    m.delete = AsyncMock(return_value=1)
    m.info = AsyncMock(
        return_value={"redis_version": "7.0.0", "uptime_in_days": 1}
    )
    m.close = AsyncMock()

    async def _empty_scan(*a, **kw):
        return
        yield  # make it an async generator

    m.scan_iter = _empty_scan
    return m


def _make_profile(
    *,
    run_count: int = 5,
    last_run_date: str = "2026-03-01",
    industry: str = "retail",
    currency: str = "USD",
    run_history: list | None = None,
    known_findings: dict | None = None,
    resolved_findings: dict | None = None,
    baseline_history: dict | None = None,
    dq_history: list | None = None,
    focus_tables: list | None = None,
    refinement: object = None,
):
    """Return a MagicMock that looks like a ClientProfile."""
    p = MagicMock()
    p.run_count = run_count
    p.last_run_date = last_run_date
    p.industry_inferred = industry
    p.currency_detected = currency
    p.run_history = run_history or []
    p.known_findings = known_findings or {}
    p.resolved_findings = resolved_findings or {}
    p.baseline_history = baseline_history or {}
    p.dq_history = dq_history or []
    p.focus_tables = focus_tables or []
    p.refinement = refinement
    p.is_entity_map_fresh = MagicMock(return_value=True)
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client():
    """Default client — Redis returns empty dicts (no jobs)."""
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
            c._redis = redis_mock
            yield c


# ---------------------------------------------------------------------------
# ══ CANCEL JOB ═══════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestCancelJob:
    async def test_cancel_nonexistent_job_returns_404(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={})
        resp = await client.post("/api/jobs/nonexistent-id/cancel")
        assert resp.status_code == 404
        # The custom error middleware returns {"error": "not_found", ...}
        body = resp.json()
        assert "not_found" in body.get("error", "") or "not found" in str(body).lower()

    async def test_cancel_running_job_returns_200(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "running"})
        resp = await client.post("/api/jobs/job-123/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "cancelled"
        assert body["job_id"] == "job-123"

    async def test_cancel_pending_job_returns_200(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "pending"})
        resp = await client.post("/api/jobs/job-pending/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    async def test_cancel_running_job_calls_hset(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "running"})
        await client.post("/api/jobs/job-xyz/cancel")
        redis_mock.hset.assert_called_once()
        call_kwargs = redis_mock.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or call_kwargs.args[1]
        assert mapping["status"] == "cancelled"

    async def test_cancel_completed_job_returns_200_already_finished(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "completed"})
        resp = await client.post("/api/jobs/job-done/cancel")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert "already finished" in body["message"].lower()

    async def test_cancel_failed_job_returns_already_finished(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "failed"})
        resp = await client.post("/api/jobs/job-failed/cancel")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Job already finished"

    async def test_cancel_already_cancelled_job(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "cancelled"})
        resp = await client.post("/api/jobs/job-cancelled/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# ══ RETRY JOB ════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestRetryJob:
    async def test_retry_nonexistent_job_returns_404(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={})
        resp = await client.post("/api/jobs/ghost-job/retry")
        assert resp.status_code == 404

    async def test_retry_running_job_returns_400(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(
            return_value={"status": "running", "client_name": "acme"}
        )
        resp = await client.post("/api/jobs/running-job/retry")
        assert resp.status_code == 400
        assert "failed or cancelled" in resp.json()["detail"].lower()

    async def test_retry_completed_job_returns_400(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(
            return_value={"status": "completed", "client_name": "acme"}
        )
        resp = await client.post("/api/jobs/done-job/retry")
        assert resp.status_code == 400

    async def test_retry_failed_job_without_request_data_returns_400(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(
            return_value={"status": "failed", "client_name": "acme"}
        )
        resp = await client.post("/api/jobs/failed-job/retry")
        assert resp.status_code == 400
        assert "request data" in resp.json()["detail"].lower()

    async def test_retry_failed_job_with_request_data_returns_200(self, client):
        redis_mock = client._redis
        request_payload = json.dumps(
            {"client_name": "acme", "db_type": "postgresql"}
        )
        redis_mock.hgetall = AsyncMock(
            return_value={
                "status": "failed",
                "client_name": "acme",
                "request_data": request_payload,
            }
        )
        with patch("api.main.run_analysis_task", new_callable=AsyncMock):
            resp = await client.post("/api/jobs/failed-job/retry")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert body["retry_of"] == "failed-job"
        assert "job_id" in body

    async def test_retry_cancelled_job_with_request_data_returns_200(self, client):
        redis_mock = client._redis
        request_payload = json.dumps({"client_name": "beta", "db_type": "mysql"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "status": "cancelled",
                "client_name": "beta",
                "request_data": request_payload,
            }
        )
        with patch("api.main.run_analysis_task", new_callable=AsyncMock):
            resp = await client.post("/api/jobs/cancelled-job/retry")
        assert resp.status_code == 200
        body = resp.json()
        assert body["retry_of"] == "cancelled-job"
        new_id = body["job_id"]
        assert new_id != "cancelled-job"

    async def test_retry_creates_new_job_id(self, client):
        redis_mock = client._redis
        request_payload = json.dumps({"client_name": "acme", "db_type": "postgresql"})
        redis_mock.hgetall = AsyncMock(
            return_value={
                "status": "failed",
                "client_name": "acme",
                "request_data": request_payload,
            }
        )
        with patch("api.main.run_analysis_task", new_callable=AsyncMock):
            resp = await client.post("/api/jobs/original-job/retry")
        body = resp.json()
        assert body["job_id"] != "original-job"


# ---------------------------------------------------------------------------
# ══ CLEANUP JOBS ══════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestCleanupJobs:
    async def test_cleanup_with_no_jobs_returns_zero(self, client):
        resp = await client.delete("/api/jobs/cleanup")
        assert resp.status_code == 200
        body = resp.json()
        assert body["deleted"] == 0
        assert "cutoff" in body

    async def test_cleanup_returns_deleted_count_and_cutoff(self, client):
        resp = await client.delete("/api/jobs/cleanup")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["deleted"], int)
        assert isinstance(body["cutoff"], str)

    async def test_cleanup_custom_older_than_days(self, client):
        resp = await client.delete("/api/jobs/cleanup?older_than_days=30")
        assert resp.status_code == 200

    async def test_cleanup_deletes_old_completed_jobs(self, client):
        redis_mock = client._redis
        old_date = "2020-01-01T00:00:00"

        async def _scan_jobs(*a, **kw):
            yield "job:old-job-1"

        redis_mock.scan_iter = _scan_jobs
        redis_mock.hgetall = AsyncMock(
            return_value={"status": "completed", "created_at": old_date}
        )
        resp = await client.delete("/api/jobs/cleanup?older_than_days=7")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 1

    async def test_cleanup_skips_results_keys(self, client):
        redis_mock = client._redis

        async def _scan_both(*a, **kw):
            yield "job:some-id"
            yield "job:some-id:results"

        redis_mock.scan_iter = _scan_both
        redis_mock.hgetall = AsyncMock(
            return_value={"status": "completed", "created_at": "2020-01-01T00:00:00"}
        )
        resp = await client.delete("/api/jobs/cleanup")
        assert resp.status_code == 200
        # only the non-:results key should be counted
        assert resp.json()["deleted"] == 1


# ---------------------------------------------------------------------------
# ══ CACHE STATS ═══════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestCacheStats:
    async def test_cache_stats_returns_200(self, client):
        resp = await client.get("/api/cache/stats")
        assert resp.status_code == 200

    async def test_cache_stats_has_cached_jobs_key(self, client):
        resp = await client.get("/api/cache/stats")
        body = resp.json()
        assert "cached_jobs" in body

    async def test_cache_stats_has_oldest_entry_age_key(self, client):
        resp = await client.get("/api/cache/stats")
        body = resp.json()
        assert "oldest_entry_age_seconds" in body

    async def test_cache_stats_cached_jobs_is_int(self, client):
        resp = await client.get("/api/cache/stats")
        assert isinstance(resp.json()["cached_jobs"], int)

    async def test_cache_stats_oldest_age_is_numeric(self, client):
        resp = await client.get("/api/cache/stats")
        age = resp.json()["oldest_entry_age_seconds"]
        assert isinstance(age, (int, float))


# ---------------------------------------------------------------------------
# ══ JOB LIST ══════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestListJobs:
    async def test_list_jobs_returns_200(self, client):
        resp = await client.get("/api/jobs")
        assert resp.status_code == 200

    async def test_list_jobs_has_pagination_keys(self, client):
        resp = await client.get("/api/jobs")
        body = resp.json()
        for key in ("jobs", "total", "page", "page_size", "pages"):
            assert key in body, f"missing key: {key}"

    async def test_list_jobs_invalid_page_returns_400(self, client):
        resp = await client.get("/api/jobs?page=0")
        assert resp.status_code == 400

    async def test_list_jobs_invalid_page_size_returns_400(self, client):
        resp = await client.get("/api/jobs?page_size=0")
        assert resp.status_code == 400

    async def test_list_jobs_invalid_sort_field_returns_400(self, client):
        resp = await client.get("/api/jobs?sort_by=nonsense")
        assert resp.status_code == 400

    async def test_list_jobs_invalid_sort_order_returns_400(self, client):
        resp = await client.get("/api/jobs?sort_order=sideways")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# ══ PDF EXPORT ════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestPdfExport:
    async def test_export_pdf_nonexistent_job_returns_404(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={})
        resp = await client.get("/api/jobs/no-such-job/export/pdf")
        assert resp.status_code == 404

    async def test_export_pdf_pending_job_returns_400(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "pending"})
        resp = await client.get("/api/jobs/pending-job/export/pdf")
        assert resp.status_code == 400
        assert "not completed" in resp.json()["detail"].lower()

    async def test_export_pdf_completed_job_returns_pdf(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(
            return_value={
                "status": "completed",
                "client_name": "acme",
                "period": "2026-Q1",
            }
        )
        redis_mock.get = AsyncMock(
            return_value=json.dumps(
                {
                    "job_id": "job-pdf",
                    "client_name": "acme",
                    "period": "2026-Q1",
                    "status": "completed",
                }
            )
        )
        resp = await client.get("/api/jobs/job-pdf/export/pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"

    async def test_export_pdf_content_disposition_header(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(
            return_value={
                "status": "completed",
                "client_name": "acme",
                "period": "2026-Q1",
            }
        )
        redis_mock.get = AsyncMock(
            return_value=json.dumps(
                {"client_name": "acme", "period": "2026-Q1", "status": "completed"}
            )
        )
        resp = await client.get("/api/jobs/job-pdf/export/pdf")
        assert "content-disposition" in resp.headers
        assert "attachment" in resp.headers["content-disposition"]

    async def test_export_pdf_body_starts_with_pdf_header(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(
            return_value={"status": "completed", "client_name": "x", "period": "p"}
        )
        redis_mock.get = AsyncMock(
            return_value=json.dumps(
                {"client_name": "x", "period": "p", "status": "completed"}
            )
        )
        resp = await client.get("/api/jobs/job-pdf2/export/pdf")
        assert resp.content.startswith(b"%PDF")

    async def test_export_pdf_running_job_returns_400(self, client):
        redis_mock = client._redis
        redis_mock.hgetall = AsyncMock(return_value={"status": "running"})
        resp = await client.get("/api/jobs/running-job/export/pdf")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# ══ DQ HISTORY ════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestDqHistory:
    async def test_dq_history_unknown_client_returns_404(self, client):
        store = MagicMock()
        store.load = AsyncMock(return_value=None)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/unknown-client/dq-history")
        assert resp.status_code == 404

    async def test_dq_history_known_client_returns_200(self, client):
        profile = _make_profile(dq_history=[{"score": 88, "run_date": "2026-03-01"}])
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/dq-history")
        assert resp.status_code == 200

    async def test_dq_history_response_has_required_keys(self, client):
        profile = _make_profile(dq_history=[{"score": 90, "run_date": "2026-03-01"}])
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/dq-history")
        body = resp.json()
        for key in ("client", "dq_history", "avg_score", "trend", "runs_with_dq"):
            assert key in body, f"missing key: {key}"

    async def test_dq_history_empty_profile_returns_nulls(self, client):
        profile = _make_profile(dq_history=[])
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/dq-history")
        body = resp.json()
        assert body["avg_score"] is None
        assert body["trend"] is None
        assert body["runs_with_dq"] == 0

    async def test_dq_history_trend_stable_for_similar_scores(self, client):
        dq_history = [{"score": 88, "run_date": f"2026-0{i}-01"} for i in range(1, 7)]
        profile = _make_profile(dq_history=dq_history)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/dq-history")
        assert resp.json()["trend"] == "stable"

    async def test_dq_history_client_name_in_response(self, client):
        profile = _make_profile()
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/my-client/dq-history")
        assert resp.json()["client"] == "my-client"


# ---------------------------------------------------------------------------
# ══ CLIENT KPIs ═══════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestClientKpis:
    async def test_kpis_unknown_client_returns_404(self, client):
        store = MagicMock()
        store.load = AsyncMock(return_value=None)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/ghost/kpis")
        assert resp.status_code == 404

    async def test_kpis_known_client_returns_200(self, client):
        profile = _make_profile(baseline_history={"revenue": [{"period": "2026-Q1", "value": 1000}]})
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/kpis")
        assert resp.status_code == 200

    async def test_kpis_response_has_required_keys(self, client):
        profile = _make_profile()
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/kpis")
        body = resp.json()
        for key in ("client_name", "kpis", "kpi_count", "earliest_period", "latest_period"):
            assert key in body, f"missing key: {key}"

    async def test_kpis_empty_baseline_returns_zero_count(self, client):
        profile = _make_profile(baseline_history={})
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/kpis")
        body = resp.json()
        assert body["kpi_count"] == 0
        assert body["earliest_period"] is None
        assert body["latest_period"] is None

    async def test_kpis_count_matches_baseline_history_length(self, client):
        bh = {
            "revenue": [{"period": "2026-Q1", "value": 1}],
            "costs": [{"period": "2026-Q1", "value": 2}],
            "margin": [{"period": "2026-Q1", "value": 3}],
        }
        profile = _make_profile(baseline_history=bh)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/kpis")
        assert resp.json()["kpi_count"] == 3

    async def test_kpis_valid_client_name_pattern_accepted(self, client):
        # _validate_client_name allows alphanumeric, underscore, hyphen, dot.
        # A valid-pattern name that has no profile returns 404 (not a crash).
        store = MagicMock()
        store.load = AsyncMock(return_value=None)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/valid-client.name_123/kpis")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# ══ CLIENT STATS ══════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestClientStats:
    async def test_stats_unknown_client_returns_404(self, client):
        store = MagicMock()
        store.load = AsyncMock(return_value=None)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/nobody/stats")
        assert resp.status_code == 404

    async def test_stats_known_client_returns_200(self, client):
        profile = _make_profile()
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/stats")
        assert resp.status_code == 200

    async def test_stats_has_all_expected_keys(self, client):
        profile = _make_profile()
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/stats")
        body = resp.json()
        expected_keys = {
            "client_name", "run_count", "last_run_date", "industry", "currency",
            "active_findings", "resolved_findings", "critical_active", "avg_runs_open",
            "findings_trend", "kpi_count", "focus_tables", "refinement_ready",
            "entity_cache_fresh",
        }
        for key in expected_keys:
            assert key in body, f"missing key: {key}"

    async def test_stats_critical_count_reflects_findings(self, client):
        known_findings = {
            "f1": {"severity": "CRITICAL", "runs_open": 2},
            "f2": {"severity": "HIGH", "runs_open": 1},
            "f3": {"severity": "CRITICAL", "runs_open": 3},
        }
        profile = _make_profile(known_findings=known_findings)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/stats")
        assert resp.json()["critical_active"] == 2

    async def test_stats_refinement_ready_false_when_none(self, client):
        profile = _make_profile(refinement=None)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/stats")
        assert resp.json()["refinement_ready"] is False

    async def test_stats_focus_tables_capped_at_five(self, client):
        tables = ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]
        profile = _make_profile(focus_tables=tables)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/stats")
        assert len(resp.json()["focus_tables"]) <= 5


# ---------------------------------------------------------------------------
# ══ CLIENT ANALYTICS ══════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------


class TestClientAnalytics:
    async def test_analytics_unknown_client_returns_404(self, client):
        store = MagicMock()
        store.load = AsyncMock(return_value=None)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/nobody/analytics")
        assert resp.status_code == 404

    async def test_analytics_known_client_returns_200(self, client):
        profile = _make_profile()
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        assert resp.status_code == 200

    async def test_analytics_has_required_keys(self, client):
        profile = _make_profile()
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        body = resp.json()
        for key in (
            "client_name", "total_runs", "success_rate", "avg_findings_per_run",
            "avg_new_findings_per_run", "avg_resolved_per_run", "runs_by_month",
            "finding_velocity", "last_5_runs",
        ):
            assert key in body, f"missing key: {key}"

    async def test_analytics_empty_run_history_success_rate_zero(self, client):
        profile = _make_profile(run_history=[])
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        body = resp.json()
        assert body["total_runs"] == 0
        assert body["success_rate"] == 0.0

    async def test_analytics_success_rate_computed_correctly(self, client):
        run_history = [
            {"run_date": "2026-03-01", "success": True, "findings_count": 2},
            {"run_date": "2026-03-02", "success": True, "findings_count": 3},
            {"run_date": "2026-03-03", "success": False, "findings_count": 1},
            {"run_date": "2026-03-04", "success": True, "findings_count": 2},
        ]
        profile = _make_profile(run_history=run_history)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        body = resp.json()
        assert body["success_rate"] == 75.0

    async def test_analytics_runs_by_month_groups_correctly(self, client):
        run_history = [
            {"run_date": "2026-03-01", "findings_count": 1, "success": True},
            {"run_date": "2026-03-15", "findings_count": 1, "success": True},
            {"run_date": "2026-02-10", "findings_count": 2, "success": True},
        ]
        profile = _make_profile(run_history=run_history)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        runs_by_month = resp.json()["runs_by_month"]
        assert runs_by_month.get("2026-03") == 2
        assert runs_by_month.get("2026-02") == 1

    async def test_analytics_last_5_runs_capped(self, client):
        run_history = [
            {"run_date": f"2026-0{i}-01", "findings_count": i, "success": True}
            for i in range(1, 9)
        ]
        profile = _make_profile(run_history=run_history)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        assert len(resp.json()["last_5_runs"]) <= 5

    async def test_analytics_finding_velocity_increasing(self, client):
        run_history = [
            {"run_date": f"2026-0{i}-01", "findings_count": i * 10, "success": True}
            for i in range(1, 6)
        ]
        profile = _make_profile(run_history=run_history)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        assert resp.json()["finding_velocity"] == "increasing"

    async def test_analytics_finding_velocity_decreasing(self, client):
        run_history = [
            {"run_date": f"2026-0{i}-01", "findings_count": (6 - i) * 10, "success": True}
            for i in range(1, 6)
        ]
        profile = _make_profile(run_history=run_history)
        store = MagicMock()
        store.load = AsyncMock(return_value=profile)
        with patch("shared.memory.profile_store.get_profile_store", return_value=store):
            resp = await client.get("/api/clients/acme/analytics")
        assert resp.json()["finding_velocity"] == "decreasing"
