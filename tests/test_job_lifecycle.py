"""
End-to-end job lifecycle tests for Valinor SaaS API.

Uses httpx.AsyncClient with ASGITransport to test without a running server.
All external dependencies (Redis, MetadataStorage, supabase, slowapi …) are
mocked/stubbed so that tests run without a full Docker environment.
"""

import json
import sys
import types
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# ---------------------------------------------------------------------------
# Ensure project root is on the path first
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub out optional packages that are not installed in the local venv so that
# importing api.main (and its transitive imports) does not crash.
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = None  # silence importlib warnings
    return mod


def _stub_missing(*module_names: str) -> None:
    for name in module_names:
        if name not in sys.modules:
            stub = _make_stub(name)
            sys.modules[name] = stub
        # Wire each child as an attribute on its parent so that
        # unittest.mock.patch can resolve dotted names via getattr().
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent_name = ".".join(parts[:i])
            child_attr  = parts[i]
            if parent_name not in sys.modules:
                sys.modules[parent_name] = _make_stub(parent_name)
            parent_mod = sys.modules[parent_name]
            child_mod  = sys.modules.get(".".join(parts[: i + 1]))
            if child_mod is not None and not hasattr(parent_mod, child_attr):
                setattr(parent_mod, child_attr, child_mod)


# supabase
_stub_missing("supabase")
_supabase_stub = sys.modules["supabase"]
_supabase_stub.create_client = MagicMock(return_value=MagicMock())
_supabase_stub.Client = MagicMock

# slowapi
_stub_missing("slowapi", "slowapi.util", "slowapi.errors")
_slowapi = sys.modules["slowapi"]

class _FakeLimiter:
    def __init__(self, key_func=None):
        pass
    def limit(self, rate: str):
        def decorator(func):
            return func
        return decorator

_slowapi.Limiter = _FakeLimiter
_slowapi._rate_limit_exceeded_handler = MagicMock()
sys.modules["slowapi.util"].get_remote_address = MagicMock(return_value="127.0.0.1")

class _FakeRateLimitExceeded(Exception):
    pass

sys.modules["slowapi.errors"].RateLimitExceeded = _FakeRateLimitExceeded

# structlog
import structlog  # real module — stub breaks structlog.contextvars
_structlog = structlog
_structlog.get_logger = MagicMock(return_value=MagicMock(
    info=MagicMock(),
    error=MagicMock(),
    warning=MagicMock(),
    debug=MagicMock(),
))

# adapters
_stub_missing("adapters", "adapters.valinor_adapter")
_adapter_stub = sys.modules["adapters.valinor_adapter"]
_adapter_stub.ValinorAdapter = MagicMock
_adapter_stub.PipelineExecutor = MagicMock

# shared.storage  — stub the whole module so MetadataStorage can be replaced
_stub_missing("shared.storage")
_storage_stub = sys.modules["shared.storage"]

class _FakeMetadataStorage:
    async def health_check(self):
        return True

_storage_stub.MetadataStorage = _FakeMetadataStorage

# shared.memory.*
for _m in (
    "shared.memory",
    "shared.memory.profile_store",
    "shared.memory.client_profile",
):
    _stub_missing(_m)

_profile_store_stub = sys.modules["shared.memory.profile_store"]

def _make_profile_store_mock() -> MagicMock:
    """Profile store mock whose async methods are AsyncMocks."""
    store = MagicMock()
    store._get_pool = AsyncMock(return_value=None)  # None → endpoint skips DB path
    store.load = AsyncMock(return_value=None)
    store.load_or_create = AsyncMock(return_value=MagicMock(webhooks=[]))
    store.save = AsyncMock(return_value=None)
    return store

_profile_store_stub.get_profile_store = MagicMock(return_value=_make_profile_store_mock())

# Wire parent→child attribute relationships so dotted attribute lookups work
# (sys.modules entries alone are not enough for unittest.mock.patch)
_shared_stub = sys.modules.get("shared")
if _shared_stub is not None:
    _shared_memory_stub = sys.modules.get("shared.memory")
    if _shared_memory_stub is not None:
        _shared_stub.memory = _shared_memory_stub
        _shared_memory_stub.profile_store = _profile_store_stub
        _shared_memory_stub.client_profile = sys.modules.get("shared.memory.client_profile")

# shared.pdf_generator — stub with a minimal PDF bytes generator
_stub_missing("shared.pdf_generator")
_pdf_stub = sys.modules["shared.pdf_generator"]
_pdf_stub.generate_pdf_report = MagicMock(return_value=b"%PDF-1.4 test pdf")
if _shared_stub is not None:
    _shared_stub.pdf_generator = _pdf_stub

# Do NOT stub api.routes.* — those are real modules we want to import

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

async def _async_gen(*keys):
    """Async generator helper: yields each key in order."""
    for k in keys:
        yield k


def _make_redis_mock(job_data: dict | None = None):
    """Return an AsyncMock that behaves like redis.asyncio.Redis."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.hgetall = AsyncMock(return_value=job_data or {})
    mock.hget = AsyncMock(return_value=None)
    mock.hset = AsyncMock(return_value=True)
    mock.expire = AsyncMock(return_value=True)
    mock.incr = AsyncMock(return_value=1)
    mock.get = AsyncMock(return_value=None)
    mock.lpush = AsyncMock(return_value=1)
    mock.ltrim = AsyncMock(return_value=True)
    mock.lrange = AsyncMock(return_value=[])
    mock.info = AsyncMock(return_value={"redis_version": "7.0.0", "uptime_in_days": 1})
    mock.close = AsyncMock()

    # scan_iter: async generator that yields nothing by default
    async def _empty_scan(*args, **kwargs):
        return
        yield  # makes it an async generator

    mock.scan_iter = _empty_scan
    return mock


def _make_storage_mock():
    """Return a MagicMock for MetadataStorage."""
    mock = MagicMock()
    mock.health_check = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def redis_mock():
    return _make_redis_mock()


@pytest.fixture
def storage_mock():
    return _make_storage_mock()


@pytest_asyncio.fixture
async def client(redis_mock, storage_mock):
    """
    AsyncClient wired to the FastAPI app with all external I/O mocked.

    All stubs for optional packages (supabase, slowapi, structlog, adapters,
    shared.storage …) are registered into sys.modules at module load time above,
    so api.main can be imported cleanly here.
    """
    # Import (or reuse cached) app after stubs are in place
    from api.main import app  # noqa: PLC0415

    from api.deps import set_redis_client

    with (
        patch("redis.asyncio.from_url", return_value=redis_mock),
        patch("api.main.metadata_storage", storage_mock),
        patch("api.main.redis_client", redis_mock),
    ):
        set_redis_client(redis_mock)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            yield ac
        set_redis_client(None)


# ---------------------------------------------------------------------------
# Minimal valid AnalysisRequest payload
# ---------------------------------------------------------------------------

VALID_ANALYSIS_PAYLOAD = {
    "client_name": "test-client",
    "period": "Q1-2025",
    "db_config": {
        "host": "db.example.com",
        "port": 5432,
        "name": "testdb",
        "type": "postgresql",
        "user": "user",
        "password": "secret",
    },
}


# ---------------------------------------------------------------------------
# TestJobLifecycle
# ---------------------------------------------------------------------------


class TestJobLifecycle:
    """End-to-end tests covering the main job lifecycle transitions."""

    @pytest.mark.asyncio
    async def test_submit_and_poll_lifecycle(self, client, redis_mock):
        """
        POST /api/analyze returns job_id with status 'pending'.
        GET /api/jobs/{id}/status returns the expected structure.
        """
        from datetime import datetime

        # No concurrent running jobs — scan_iter yields nothing
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan

        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            submit_resp = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)

        assert submit_resp.status_code == 200
        submit_data = submit_resp.json()
        assert "job_id" in submit_data
        assert submit_data["status"] == "pending"

        job_id = submit_data["job_id"]

        # Poll status — Redis now returns a running job for that id
        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "running",
                "stage": "cartographer",
                "progress": "10",
                "message": "Mapping schema",
                "created_at": datetime.utcnow().isoformat(),
            }
        )

        status_resp = await client.get(f"/api/jobs/{job_id}/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["job_id"] == job_id
        assert status_data["status"] == "running"
        assert "stage" in status_data
        assert "progress" in status_data

    @pytest.mark.asyncio
    async def test_completed_job_results_accessible(self, client, redis_mock):
        """
        With Redis mocked to return a completed job,
        GET /api/jobs/{id}/results returns findings/reports.
        """
        job_id = "completed-job-lifecycle-001"

        results_payload = {
            "job_id": job_id,
            "client_name": "test-client",
            "period": "Q1-2025",
            "status": "completed",
            "execution_time_seconds": 42.0,
            "timestamp": "2026-03-21T10:00:00",
            "findings": {"revenue_drop": {"severity": "HIGH", "value": -12.5}},
            "reports": {
                "executive": "Analysis complete. Revenue dropped 12.5% QoQ."
            },
        }

        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "completed",
                "client_name": "test-client",
                "period": "Q1-2025",
            }
        )
        redis_mock.get = AsyncMock(return_value=json.dumps(results_payload))

        # Evict any cached entry so we always exercise the Redis path
        from api.main import _results_cache
        _results_cache.pop(job_id, None)

        response = await client.get(f"/api/jobs/{job_id}/results")
        assert response.status_code == 200
        data = response.json()
        assert "findings" in data
        assert "reports" in data
        assert data["findings"]["revenue_drop"]["severity"] == "HIGH"
        assert "executive" in data["reports"]

    @pytest.mark.asyncio
    async def test_failed_job_shows_error(self, client, redis_mock):
        """
        GET /api/jobs/{id}/status for a failed job returns status 'failed'
        and the error field.
        GET /api/jobs/{id}/results for a failed job returns 400 (not completed).
        """
        from datetime import datetime

        job_id = "failed-job-lifecycle-002"

        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "failed",
                "error": "Connection timeout to database",
                "stage": "cartographer",
                "progress": "5",
                "created_at": datetime.utcnow().isoformat(),
            }
        )

        # Status endpoint must surface the failed state and the error field
        status_resp = await client.get(f"/api/jobs/{job_id}/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] == "failed"
        assert "error" in status_data

        # Results endpoint must refuse with 400 since job did not complete
        results_resp = await client.get(f"/api/jobs/{job_id}/results")
        assert results_resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_running_job(self, client, redis_mock):
        """
        POST /api/jobs/{id}/cancel on a running job returns status 'cancelled'
        and calls hset to persist the transition in Redis.
        """
        job_id = "running-job-lifecycle-003"

        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "running",
                "stage": "query_builder",
                "progress": "40",
            }
        )

        response = await client.post(f"/api/jobs/{job_id}/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"
        assert data["job_id"] == job_id

        # hset must have been called with status=cancelled in the mapping
        redis_mock.hset.assert_called_once()
        call_kwargs = redis_mock.hset.call_args
        mapping = call_kwargs.kwargs.get("mapping") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else {}
        )
        assert mapping.get("status") == "cancelled"

    @pytest.mark.asyncio
    async def test_retry_failed_job_returns_new_id(self, client, redis_mock):
        """
        POST /api/jobs/{id}/retry on a failed job returns a new job_id that
        differs from the original, with status 'pending'.
        """
        original_job_id = "failed-job-lifecycle-004"
        original_request = {
            "client_name": "test-client",
            "period": "Q1-2025",
            "db_config": {
                "host": "db.example.com",
                "port": 5432,
                "name": "testdb",
                "type": "postgresql",
                "user": "user",
                "password": "secret",
            },
        }

        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": original_job_id,
                "status": "failed",
                "client_name": "test-client",
                "request_data": json.dumps(original_request),
            }
        )

        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post(f"/api/jobs/{original_job_id}/retry")

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["job_id"] != original_job_id
        assert data["status"] == "pending"
        assert data.get("retry_of") == original_job_id


# ---------------------------------------------------------------------------
# TestJobsListFiltering
# ---------------------------------------------------------------------------


class TestJobsListFiltering:
    """Tests for GET /api/jobs list, filter and pagination."""

    @pytest.mark.asyncio
    async def test_filter_by_client_name(self, client, redis_mock):
        """
        Multiple jobs with different client_names in Redis; filtering by one
        client should return only that client's jobs.
        """
        jobs = {
            "job:job-1": {
                "job_id": "job-1",
                "status": "completed",
                "client_name": "alpha-corp",
                "period": "Q1-2025",
                "created_at": "2026-03-01T10:00:00",
            },
            "job:job-2": {
                "job_id": "job-2",
                "status": "completed",
                "client_name": "beta-inc",
                "period": "Q1-2025",
                "created_at": "2026-03-02T10:00:00",
            },
            "job:job-3": {
                "job_id": "job-3",
                "status": "running",
                "client_name": "alpha-corp",
                "period": "Q1-2025",
                "created_at": "2026-03-03T10:00:00",
            },
        }

        redis_mock.scan_iter = MagicMock(
            return_value=_async_gen("job:job-1", "job:job-2", "job:job-3")
        )
        redis_mock.hgetall = AsyncMock(side_effect=lambda key: jobs.get(key, {}))

        response = await client.get("/api/jobs?client_name=alpha-corp")
        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        returned_clients = {j["client_name"] for j in data["jobs"]}
        assert returned_clients == {"alpha-corp"}
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_filter_by_status(self, client, redis_mock):
        """
        Mix of completed/pending jobs; filtering by 'completed' returns only
        completed jobs.
        """
        jobs = {
            "job:job-a": {
                "job_id": "job-a",
                "status": "completed",
                "client_name": "client-x",
                "period": "Q2-2025",
                "created_at": "2026-03-01T09:00:00",
            },
            "job:job-b": {
                "job_id": "job-b",
                "status": "pending",
                "client_name": "client-x",
                "period": "Q2-2025",
                "created_at": "2026-03-02T09:00:00",
            },
            "job:job-c": {
                "job_id": "job-c",
                "status": "completed",
                "client_name": "client-y",
                "period": "Q2-2025",
                "created_at": "2026-03-03T09:00:00",
            },
        }

        redis_mock.scan_iter = MagicMock(
            return_value=_async_gen("job:job-a", "job:job-b", "job:job-c")
        )
        redis_mock.hgetall = AsyncMock(side_effect=lambda key: jobs.get(key, {}))

        response = await client.get("/api/jobs?status_filter=completed")
        assert response.status_code == 200
        data = response.json()
        returned_statuses = {j["status"] for j in data["jobs"]}
        assert returned_statuses == {"completed"}
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_pagination_slice(self, client, redis_mock):
        """
        5 jobs total; requesting page_size=2 page=2 returns exactly 2 jobs
        and total=5.
        """
        keys = [f"job:job-{i}" for i in range(1, 6)]
        jobs = {
            f"job:job-{i}": {
                "job_id": f"job-{i}",
                "status": "completed",
                "client_name": "paginate-client",
                "period": "Q1-2025",
                "created_at": f"2026-03-{i:02d}T08:00:00",
            }
            for i in range(1, 6)
        }

        redis_mock.scan_iter = MagicMock(
            return_value=_async_gen(
                "job:job-1",
                "job:job-2",
                "job:job-3",
                "job:job-4",
                "job:job-5",
            )
        )
        redis_mock.hgetall = AsyncMock(side_effect=lambda key: jobs.get(key, {}))

        response = await client.get("/api/jobs?page=2&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["jobs"]) == 2
        assert data["page"] == 2
        assert data["page_size"] == 2


# ---------------------------------------------------------------------------
# TestHealthAndMetricsEndpoints
# ---------------------------------------------------------------------------


class TestHealthAndMetricsEndpoints:
    """Tests covering /health and /metrics system endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_200(self, client, redis_mock):
        """GET /health returns 200 and the body contains a 'status' key."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    @pytest.mark.asyncio
    async def test_metrics_endpoint_returns_200(self, client, redis_mock):
        """GET /metrics returns 200 (Prometheus text exposition format)."""
        response = await client.get("/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_nonexistent_job_status_returns_404(self, client, redis_mock):
        """GET /api/jobs/does-not-exist/status with Redis returning {} should return 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.get("/api/jobs/does-not-exist/status")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TestAnalysisSubmissionValidation
# ---------------------------------------------------------------------------


class TestAnalysisSubmissionValidation:
    """Tests covering input validation on POST /api/analyze."""

    @pytest.mark.asyncio
    async def test_submit_with_invalid_client_name_returns_422(self, client, redis_mock):
        """POST /api/analyze with a client_name containing invalid characters → 422."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan

        payload = {
            **VALID_ANALYSIS_PAYLOAD,
            "client_name": "invalid name with spaces!",
        }
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_with_missing_db_config_returns_422(self, client, redis_mock):
        """POST /api/analyze without db_config → 422 (required field)."""
        payload = {
            "client_name": "test-client",
            "period": "Q1-2025",
            # db_config intentionally omitted
        }
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_with_invalid_db_port_returns_422(self, client, redis_mock):
        """POST /api/analyze with db_config port as string 'not-a-port' → 422 (Pydantic)."""
        payload = {
            "client_name": "test-client",
            "period": "Q1-2025",
            "db_config": {
                "host": "db.example.com",
                "port": "not-a-port",
                "name": "testdb",
                "type": "postgresql",
                "user": "user",
                "password": "secret",
            },
        }
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_concurrent_job_limit_returns_429(self, client, redis_mock):
        """
        If 2+ running jobs exist for the same client, POST /api/analyze returns 429.

        The API iterates scan_iter("job:*") and calls hget(key, "status") /
        hget(key, "client_name").  We stub those to simulate 2 running jobs
        belonging to the same client_name used in VALID_ANALYSIS_PAYLOAD.
        """
        client_name = VALID_ANALYSIS_PAYLOAD["client_name"]

        running_keys = [f"job:running-{i}" for i in range(1, 3)]

        async def _running_scan(*args, **kwargs):
            for k in running_keys:
                yield k

        redis_mock.scan_iter = _running_scan

        # hget returns "running" for status, client_name for client_name field
        async def _hget_side_effect(key, field):
            if field == "status":
                return "running"
            if field == "client_name":
                return client_name
            return None

        redis_mock.hget = AsyncMock(side_effect=_hget_side_effect)

        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)
        assert response.status_code == 429


# ---------------------------------------------------------------------------
# TestJobResultsEdgeCases
# ---------------------------------------------------------------------------


class TestJobResultsEdgeCases:
    """Edge-case tests for GET /api/jobs/{id}/results."""

    @pytest.mark.asyncio
    async def test_results_for_nonexistent_job_returns_404(self, client, redis_mock):
        """GET /api/jobs/ghost-job/results with Redis returning {} → 404."""
        redis_mock.hgetall = AsyncMock(return_value={})

        # Evict cache to ensure we always hit Redis
        from api.main import _results_cache
        _results_cache.pop("ghost-job", None)

        response = await client.get("/api/jobs/ghost-job/results")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_results_for_pending_job_returns_400(self, client, redis_mock):
        """GET /api/jobs/pending-job/results with status='pending' → 400."""
        job_id = "pending-job"
        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "pending",
                "client_name": "test-client",
                "period": "Q1-2025",
                "created_at": "2026-03-21T08:00:00",
            }
        )

        from api.main import _results_cache
        _results_cache.pop(job_id, None)

        response = await client.get(f"/api/jobs/{job_id}/results")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_creates_redis_entry(self, client, redis_mock):
        """POST /api/analyze → redis_mock.hset should be called (job stored in Redis)."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan

        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)

        assert response.status_code == 200
        redis_mock.hset.assert_called()


# ---------------------------------------------------------------------------
# TestCancelRetryEdgeCases
# ---------------------------------------------------------------------------


class TestCancelRetryEdgeCases:
    """Edge cases for the cancel and retry job endpoints."""

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job_returns_404(self, client, redis_mock):
        """POST /api/jobs/ghost/cancel with Redis returning {} → 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.post("/api/jobs/ghost/cancel")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_completed_job_returns_current_status(self, client, redis_mock):
        """
        POST /api/jobs/{id}/cancel on an already-completed job should NOT
        transition to cancelled; the API returns the current status.
        """
        job_id = "already-completed-job"
        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "completed",
                "stage": "done",
                "progress": "100",
            }
        )
        response = await client.post(f"/api/jobs/{job_id}/cancel")
        assert response.status_code == 200
        data = response.json()
        # The endpoint returns the existing terminal status, NOT "cancelled"
        assert data["status"] == "completed"
        # hset must NOT have been called (no transition needed)
        redis_mock.hset.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_nonexistent_job_returns_404(self, client, redis_mock):
        """POST /api/jobs/ghost/retry with Redis returning {} → 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.post("/api/jobs/ghost/retry")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_running_job_returns_400(self, client, redis_mock):
        """
        POST /api/jobs/{id}/retry on a running job → 400.
        Only failed or cancelled jobs may be retried.
        """
        job_id = "still-running-job"
        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "running",
                "stage": "cartographer",
                "progress": "50",
                "request_data": json.dumps(VALID_ANALYSIS_PAYLOAD),
            }
        )
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post(f"/api/jobs/{job_id}/retry")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_retry_cancelled_job_succeeds(self, client, redis_mock):
        """POST /api/jobs/{id}/retry on a *cancelled* job must also succeed."""
        job_id = "cancelled-for-retry"
        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "cancelled",
                "client_name": "test-client",
                "request_data": json.dumps(VALID_ANALYSIS_PAYLOAD),
            }
        )
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post(f"/api/jobs/{job_id}/retry")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["job_id"] != job_id
        assert data.get("retry_of") == job_id


# ---------------------------------------------------------------------------
# TestJobsListSorting
# ---------------------------------------------------------------------------


class TestJobsListSorting:
    """Tests covering sort_by and sort_order parameters on GET /api/jobs."""

    @pytest.mark.asyncio
    async def test_invalid_sort_by_returns_400(self, client, redis_mock):
        """GET /api/jobs?sort_by=invalid → 400."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        response = await client.get("/api/jobs?sort_by=invalid_field")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_sort_order_returns_400(self, client, redis_mock):
        """GET /api/jobs?sort_order=sideways → 400."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        response = await client.get("/api/jobs?sort_order=sideways")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_page_size_exceeds_maximum_returns_400(self, client, redis_mock):
        """GET /api/jobs?page_size=999 → 400 (max is 100)."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        response = await client.get("/api/jobs?page_size=999")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_page_zero_returns_400(self, client, redis_mock):
        """GET /api/jobs?page=0 → 400 (pages are 1-indexed)."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        response = await client.get("/api/jobs?page=0")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_job_list_returns_zero_total(self, client, redis_mock):
        """When no jobs exist GET /api/jobs returns total=0 and jobs=[]."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        response = await client.get("/api/jobs")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["jobs"] == []


# ---------------------------------------------------------------------------
# TestAuditEndpoints
# ---------------------------------------------------------------------------


class TestAuditEndpoints:
    """Tests for POST /api/audit and GET /api/audit."""

    @pytest.mark.asyncio
    async def test_post_audit_event_returns_logged_true(self, client, redis_mock):
        """POST /api/audit with a valid body → {"logged": true}."""
        response = await client.post(
            "/api/audit",
            json={"event_type": "test_event", "detail": "unit test"},
        )
        assert response.status_code == 200
        assert response.json().get("logged") is True
        # lpush and ltrim must have been called
        redis_mock.lpush.assert_called_once()
        redis_mock.ltrim.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_audit_events_returns_events_list(self, client, redis_mock):
        """
        GET /api/audit when Redis lrange returns serialised events → list is
        decoded and returned under the 'events' key.
        """
        sample_events = [
            json.dumps({"event_type": "analysis_started", "job_id": "j1"}),
            json.dumps({"event_type": "analysis_completed", "job_id": "j1"}),
        ]
        redis_mock.lrange = AsyncMock(return_value=sample_events)

        response = await client.get("/api/audit?limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert len(data["events"]) == 2
        assert data["events"][0]["event_type"] == "analysis_started"

    @pytest.mark.asyncio
    async def test_get_audit_events_filter_by_event_type(self, client, redis_mock):
        """GET /api/audit?event_type=analysis_started returns only matching events."""
        sample_events = [
            json.dumps({"event_type": "analysis_started", "job_id": "j1"}),
            json.dumps({"event_type": "analysis_completed", "job_id": "j1"}),
            json.dumps({"event_type": "analysis_started", "job_id": "j2"}),
        ]
        redis_mock.lrange = AsyncMock(return_value=sample_events)

        response = await client.get("/api/audit?event_type=analysis_started")
        assert response.status_code == 200
        data = response.json()
        types = {e["event_type"] for e in data["events"]}
        assert types == {"analysis_started"}
        assert data["total_returned"] == 2


# ---------------------------------------------------------------------------
# TestSystemEndpoints
# ---------------------------------------------------------------------------


class TestSystemEndpoints:
    """Tests for /api/version, /api/cache/stats, and /api/system/metrics."""

    @pytest.mark.asyncio
    async def test_version_endpoint_returns_version_string(self, client, redis_mock):
        """GET /api/version returns a dict with a 'version' key."""
        response = await client.get("/api/version")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_cache_stats_returns_cached_jobs_key(self, client, redis_mock):
        """GET /api/cache/stats returns at least the 'cached_jobs' field."""
        response = await client.get("/api/cache/stats")
        assert response.status_code == 200
        data = response.json()
        assert "cached_jobs" in data
        assert isinstance(data["cached_jobs"], int)

    @pytest.mark.asyncio
    async def test_results_cache_hit_bypasses_redis(self, client, redis_mock):
        """
        After a completed result is loaded, a second GET /api/jobs/{id}/results
        should be served from the in-memory cache — redis.get must be called
        only once across the two requests.
        """
        job_id = "cache-hit-job-001"
        results_payload = {
            "job_id": job_id,
            "client_name": "cache-client",
            "period": "Q1-2025",
            "status": "completed",
            "execution_time_seconds": 10.0,
            "timestamp": "2026-03-21T10:00:00",
            "findings": {},
            "reports": {"executive": "Done."},
        }

        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": job_id,
                "status": "completed",
                "client_name": "cache-client",
                "period": "Q1-2025",
            }
        )
        redis_mock.get = AsyncMock(return_value=json.dumps(results_payload))

        from api.main import _results_cache
        _results_cache.pop(job_id, None)

        # First request — populates cache
        r1 = await client.get(f"/api/jobs/{job_id}/results")
        assert r1.status_code == 200

        # Reset call count so we can assert the second request doesn't hit Redis
        redis_mock.get.reset_mock()

        # Second request — should be served from in-memory cache
        r2 = await client.get(f"/api/jobs/{job_id}/results")
        assert r2.status_code == 200
        redis_mock.get.assert_not_called()


# ---------------------------------------------------------------------------
# TestAnalysisSubmissionAdditionalValidation
# ---------------------------------------------------------------------------


class TestAnalysisSubmissionAdditionalValidation:
    """Additional validation coverage for POST /api/analyze."""

    @pytest.mark.asyncio
    async def test_submit_with_out_of_range_port_returns_422(self, client, redis_mock):
        """POST /api/analyze with db_config.port=0 → 422 (port must be 1-65535)."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        payload = {
            **VALID_ANALYSIS_PAYLOAD,
            "db_config": {**VALID_ANALYSIS_PAYLOAD["db_config"], "port": 0},
        }
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_with_invalid_ssh_host_returns_422(self, client, redis_mock):
        """POST /api/analyze with an ssh_config.host containing spaces → 422."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        payload = {
            **VALID_ANALYSIS_PAYLOAD,
            "ssh_config": {
                "host": "invalid host name!",
                "username": "admin",
                "port": 22,
            },
        }
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_submit_returns_message_field(self, client, redis_mock):
        """POST /api/analyze success response contains a non-empty 'message' field."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["message"]  # non-empty string

    @pytest.mark.asyncio
    async def test_monthly_limit_returns_429_when_exceeded(self, client, redis_mock):
        """
        When redis.incr for the monthly limit counter returns 26,
        POST /api/analyze → 429 with error='monthly_limit_reached'.
        """
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan
        # Simulate monthly counter already at 26 (> 25 limit)
        redis_mock.incr = AsyncMock(return_value=26)
        with patch("api.routers.jobs.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)
        assert response.status_code == 429
        detail = response.json().get("detail", {})
        assert isinstance(detail, dict)
        assert detail.get("error") == "monthly_limit_reached"

    @pytest.mark.asyncio
    async def test_health_endpoint_contains_version_and_uptime(self, client, redis_mock):
        """GET /health response includes 'version' and 'uptime_seconds' fields."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))

    @pytest.mark.asyncio
    async def test_health_includes_component_status(self, client, redis_mock):
        """GET /health response contains a 'components' dict with redis and storage keys."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "components" in data
        assert "redis" in data["components"]
        assert "storage" in data["components"]
