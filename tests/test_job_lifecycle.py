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
_stub_missing("structlog")
_structlog = sys.modules["structlog"]
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

    with (
        patch("redis.asyncio.from_url", return_value=redis_mock),
        patch("api.main.metadata_storage", storage_mock),
        patch("api.main.redis_client", redis_mock),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            yield ac


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

        with patch("api.main.run_analysis_task", new=AsyncMock()):
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

        with patch("api.main.run_analysis_task", new=AsyncMock()):
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
