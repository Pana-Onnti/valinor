"""
End-to-end integration tests for the full Valinor SaaS job lifecycle.

Covers:
  POST /api/analyze → job_id
  GET  /api/jobs/{job_id}/status   (pending → running → completed)
  GET  /api/jobs/{job_id}/results
  GET  /api/jobs/{job_id}/export/pdf
  GET  /api/jobs/{job_id}/quality
  POST /api/jobs/{job_id}/cancel
  POST /api/jobs/{job_id}/retry
  DELETE /api/jobs/cleanup
  GET  /api/jobs  (pagination, client_name filter, status filter)

All external dependencies (Redis, MetadataStorage, supabase, slowapi …) are
mocked/stubbed so tests run without a full Docker environment.
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

def _make_redis_mock(job_data: dict | None = None):
    """Return an AsyncMock that behaves like redis.asyncio.Redis."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.hgetall = AsyncMock(return_value=job_data or {})
    mock.hget = AsyncMock(return_value=None)
    mock.hset = AsyncMock(return_value=True)
    mock.expire = AsyncMock(return_value=True)
    mock.incr = AsyncMock(return_value=1)  # monthly limit counter
    mock.get = AsyncMock(return_value=None)
    mock.info = AsyncMock(return_value={"redis_version": "7.0.0", "uptime_in_days": 1})
    mock.close = AsyncMock()
    mock.delete = AsyncMock(return_value=1)
    mock.lrange = AsyncMock(return_value=[])
    mock.lpush = AsyncMock(return_value=1)
    mock.ltrim = AsyncMock(return_value=True)

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

# Minimal completed job stored in Redis hash
_COMPLETED_JOB_HASH = {
    "job_id": "lifecycle-job-001",
    "status": "completed",
    "client_name": "test-client",
    "period": "Q1-2025",
    "stage": "narrator",
    "progress": "100",
    "message": "Analysis complete",
    "created_at": "2026-03-21T10:00:00",
    "completed_at": "2026-03-21T10:01:00",
}

_RESULTS_PAYLOAD = json.dumps(
    {
        "job_id": "lifecycle-job-001",
        "client_name": "test-client",
        "period": "Q1-2025",
        "status": "completed",
        "execution_time_seconds": 60.0,
        "timestamp": "2026-03-21T10:01:00",
        "findings": {},
        "reports": {
            "executive": "Valinor completed the analysis. No critical findings."
        },
        "data_quality": {
            "score": 0.95,
            "confidence_label": "CONFIRMED",
            "tag": "dq:confirmed",
            "checks": [],
        },
        "currency_warnings": {},
    }
)


# ---------------------------------------------------------------------------
# Test: full job lifecycle
# ---------------------------------------------------------------------------


class TestFullJobLifecycle:
    """
    Simulate the complete lifecycle:
      submit → poll pending → poll running → poll completed → results → PDF → quality
    """

    @pytest.mark.asyncio
    async def test_full_job_lifecycle(self, client, redis_mock):
        """
        Submit an analysis job, simulate status transitions via Redis mock side-effects,
        then fetch results, PDF, and quality report.
        """
        # ── Step 1: POST /api/analyze ─────────────────────────────────────
        # Ensure no concurrent running jobs for rate-limit check
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan

        with patch("api.main.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        job_id = data["job_id"]
        assert data["status"] == "pending"

        # ── Step 2: GET status → pending ──────────────────────────────────
        redis_mock.hgetall = AsyncMock(return_value={
            "job_id": job_id,
            "status": "pending",
            "stage": "queued",
            "progress": "0",
            "message": "Waiting to start",
            "created_at": "2026-03-21T10:00:00",
        })
        response = await client.get(f"/api/jobs/{job_id}/status")
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

        # ── Step 3: GET status → running ──────────────────────────────────
        redis_mock.hgetall = AsyncMock(return_value={
            "job_id": job_id,
            "status": "running",
            "stage": "cartographer",
            "progress": "25",
            "message": "Mapping schema",
            "created_at": "2026-03-21T10:00:00",
        })
        response = await client.get(f"/api/jobs/{job_id}/status")
        assert response.status_code == 200
        status_data = response.json()
        assert status_data["status"] == "running"
        assert status_data["stage"] == "cartographer"
        assert status_data["progress"] == 25

        # ── Step 4: GET status → completed ────────────────────────────────
        redis_mock.hgetall = AsyncMock(return_value={
            "job_id": job_id,
            "status": "completed",
            "stage": "narrator",
            "progress": "100",
            "message": "Analysis complete",
            "created_at": "2026-03-21T10:00:00",
            "completed_at": "2026-03-21T10:01:00",
        })
        response = await client.get(f"/api/jobs/{job_id}/status")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["progress"] == 100

        # ── Step 5: GET /api/jobs/{job_id}/results ────────────────────────
        redis_mock.hgetall = AsyncMock(return_value={
            **_COMPLETED_JOB_HASH,
            "job_id": job_id,
        })
        redis_mock.get = AsyncMock(return_value=_RESULTS_PAYLOAD)
        response = await client.get(f"/api/jobs/{job_id}/results")
        assert response.status_code == 200
        results = response.json()
        assert "reports" in results
        assert "executive" in results["reports"]

        # ── Step 6: GET /api/jobs/{job_id}/export/pdf ─────────────────────
        redis_mock.hgetall = AsyncMock(return_value={
            **_COMPLETED_JOB_HASH,
            "job_id": job_id,
        })
        redis_mock.get = AsyncMock(return_value=_RESULTS_PAYLOAD)
        response = await client.get(f"/api/jobs/{job_id}/export/pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content[:5] == b"%PDF-"

        # ── Step 7: GET /api/jobs/{job_id}/quality ────────────────────────
        redis_mock.get = AsyncMock(return_value=_RESULTS_PAYLOAD)
        response = await client.get(f"/api/jobs/{job_id}/quality")
        assert response.status_code == 200
        quality = response.json()
        assert "data_quality" in quality
        assert quality["data_quality"] is not None
        assert quality["data_quality"]["score"] == 0.95


# ---------------------------------------------------------------------------
# Test: 404 for nonexistent job
# ---------------------------------------------------------------------------


class TestJobNotFound:
    @pytest.mark.asyncio
    async def test_job_not_found_status_returns_404(self, client, redis_mock):
        """GET /api/jobs/{id}/status for a nonexistent job returns 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.get("/api/jobs/does-not-exist-abc/status")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_job_not_found_results_returns_404(self, client, redis_mock):
        """GET /api/jobs/{id}/results for a nonexistent job returns 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.get("/api/jobs/does-not-exist-abc/results")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_job_not_found_pdf_returns_404(self, client, redis_mock):
        """GET /api/jobs/{id}/export/pdf for a nonexistent job returns 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.get("/api/jobs/does-not-exist-abc/export/pdf")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_job_not_found_quality_returns_404(self, client, redis_mock):
        """GET /api/jobs/{id}/quality for a nonexistent job returns 404."""
        redis_mock.get = AsyncMock(return_value=None)
        response = await client.get("/api/jobs/does-not-exist-abc/quality")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: cancel running job
# ---------------------------------------------------------------------------


class TestCancelRunningJob:
    @pytest.mark.asyncio
    async def test_cancel_running_job(self, client, redis_mock):
        """POST /api/jobs/{id}/cancel on a running job sets status to 'cancelled'."""
        redis_mock.hgetall = AsyncMock(return_value={
            "job_id": "running-job-cancel",
            "status": "running",
            "stage": "query_builder",
            "progress": "50",
            "created_at": "2026-03-21T10:00:00",
        })

        response = await client.post("/api/jobs/running-job-cancel/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"
        assert data["job_id"] == "running-job-cancel"

        # Verify that hset was called to persist the cancellation
        redis_mock.hset.assert_called()

    @pytest.mark.asyncio
    async def test_cancel_already_completed_job_returns_finished_message(self, client, redis_mock):
        """Cancelling an already-completed job returns a 'already finished' indicator."""
        redis_mock.hgetall = AsyncMock(return_value={
            "job_id": "completed-job-cancel",
            "status": "completed",
            "created_at": "2026-03-21T10:00:00",
        })

        response = await client.post("/api/jobs/completed-job-cancel/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert "message" in data

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job_returns_404(self, client, redis_mock):
        """Cancelling a nonexistent job returns 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.post("/api/jobs/no-such-job/cancel")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: retry failed job
# ---------------------------------------------------------------------------


class TestRetryFailedJob:
    _FAILED_JOB_DATA = {
        "job_id": "failed-job-retry",
        "status": "failed",
        "client_name": "retry-client",
        "period": "Q1-2025",
        "created_at": "2026-03-21T10:00:00",
        "request_data": json.dumps({
            "client_name": "retry-client",
            "period": "Q1-2025",
            "db_config": {
                "host": "db.example.com",
                "port": 5432,
                "name": "testdb",
                "type": "postgresql",
                "user": "user",
                "password": "secret",
            },
        }),
    }

    @pytest.mark.asyncio
    async def test_retry_failed_job_returns_new_job_id(self, client, redis_mock):
        """POST /api/jobs/{id}/retry on a failed job returns a new job_id."""
        redis_mock.hgetall = AsyncMock(return_value=self._FAILED_JOB_DATA)

        with patch("api.main.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/jobs/failed-job-retry/retry")

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        # The new job_id must differ from the original
        assert data["job_id"] != "failed-job-retry"
        assert data["status"] == "pending"
        assert data["retry_of"] == "failed-job-retry"

    @pytest.mark.asyncio
    async def test_retry_pending_job_returns_400(self, client, redis_mock):
        """Retrying a still-pending (non-failed) job is rejected with 400."""
        redis_mock.hgetall = AsyncMock(return_value={
            "job_id": "pending-job-retry",
            "status": "pending",
            "created_at": "2026-03-21T10:00:00",
        })

        response = await client.post("/api/jobs/pending-job-retry/retry")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_retry_nonexistent_job_returns_404(self, client, redis_mock):
        """Retrying a nonexistent job returns 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.post("/api/jobs/no-such-job/retry")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: cleanup old jobs
# ---------------------------------------------------------------------------


class TestCleanupOldJobs:
    @pytest.mark.asyncio
    async def test_cleanup_returns_deleted_count(self, client, redis_mock):
        """DELETE /api/jobs/cleanup returns the number of deleted jobs."""
        # Two old completed jobs in Redis
        old_ts = "2025-01-01T00:00:00"

        async def _scan_two(*args, **kwargs):
            yield "job:old-job-001"
            yield "job:old-job-002"

        redis_mock.scan_iter = _scan_two
        redis_mock.hgetall = AsyncMock(return_value={
            "status": "completed",
            "created_at": old_ts,
        })

        response = await client.delete("/api/jobs/cleanup")
        assert response.status_code == 200
        data = response.json()
        assert "deleted" in data
        assert isinstance(data["deleted"], int)
        assert data["deleted"] == 2

    @pytest.mark.asyncio
    async def test_cleanup_no_eligible_jobs_returns_zero(self, client, redis_mock):
        """When no jobs are old enough, deleted count is 0."""
        # One recent running job — should not be deleted
        async def _scan_one(*args, **kwargs):
            yield "job:recent-job-001"

        redis_mock.scan_iter = _scan_one
        redis_mock.hgetall = AsyncMock(return_value={
            "status": "running",
            "created_at": "2099-01-01T00:00:00",
        })

        response = await client.delete("/api/jobs/cleanup")
        assert response.status_code == 200
        assert response.json()["deleted"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_response_includes_cutoff(self, client, redis_mock):
        """The cleanup response must include the 'cutoff' timestamp."""
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan

        response = await client.delete("/api/jobs/cleanup")
        assert response.status_code == 200
        assert "cutoff" in response.json()


# ---------------------------------------------------------------------------
# Test: jobs list pagination
# ---------------------------------------------------------------------------


class TestJobsListPagination:
    """GET /api/jobs with page and page_size parameters."""

    @staticmethod
    def _build_scan_and_hgetall(n: int, status: str = "completed", client_name: str = "acme"):
        """
        Return (scan_iter coroutine, hgetall side-effect) for n jobs.
        Job keys are job:job-0001 … job:job-{n:04d}.
        """
        keys = [f"job:job-{i:04d}" for i in range(1, n + 1)]

        async def _scan(*args, **kwargs):
            for k in keys:
                yield k

        job_records = {
            k: {
                "job_id": k.replace("job:", ""),
                "status": status,
                "client_name": client_name,
                "period": "Q1-2025",
                "created_at": f"2026-03-21T10:{i:02d}:00",
                "progress": "100",
            }
            for i, k in enumerate(keys)
        }

        async def _hgetall(key):
            return job_records.get(key, {})

        return _scan, _hgetall

    @pytest.mark.asyncio
    async def test_pagination_page_two_returns_correct_slice(self, client, redis_mock):
        """25 total jobs, page=2 page_size=10 → jobs 11-20 (10 items)."""
        scan_fn, hgetall_fn = self._build_scan_and_hgetall(25)
        redis_mock.scan_iter = scan_fn
        redis_mock.hgetall = AsyncMock(side_effect=hgetall_fn)

        response = await client.get("/api/jobs?page=2&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 25
        assert data["page"] == 2
        assert data["page_size"] == 10
        assert len(data["jobs"]) == 10

    @pytest.mark.asyncio
    async def test_pagination_last_page_has_remaining_jobs(self, client, redis_mock):
        """25 total jobs, page=3 page_size=10 → jobs 21-25 (5 items)."""
        scan_fn, hgetall_fn = self._build_scan_and_hgetall(25)
        redis_mock.scan_iter = scan_fn
        redis_mock.hgetall = AsyncMock(side_effect=hgetall_fn)

        response = await client.get("/api/jobs?page=3&page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 5

    @pytest.mark.asyncio
    async def test_pagination_includes_pages_count(self, client, redis_mock):
        """Response must include a 'pages' key reflecting total page count."""
        scan_fn, hgetall_fn = self._build_scan_and_hgetall(25)
        redis_mock.scan_iter = scan_fn
        redis_mock.hgetall = AsyncMock(side_effect=hgetall_fn)

        response = await client.get("/api/jobs?page_size=10")
        assert response.status_code == 200
        data = response.json()
        assert "pages" in data
        assert data["pages"] == 3


# ---------------------------------------------------------------------------
# Test: jobs list client_name filter
# ---------------------------------------------------------------------------


class TestJobsListClientFilter:
    @pytest.mark.asyncio
    async def test_client_name_filter_returns_only_matching_client(self, client, redis_mock):
        """Filter by client_name=acme should exclude jobs from other clients."""
        keys = ["job:acme-job-001", "job:acme-job-002", "job:other-job-001"]
        job_records = {
            "job:acme-job-001": {
                "job_id": "acme-job-001",
                "status": "completed",
                "client_name": "acme",
                "period": "Q1-2025",
                "created_at": "2026-03-21T10:00:00",
            },
            "job:acme-job-002": {
                "job_id": "acme-job-002",
                "status": "completed",
                "client_name": "acme",
                "period": "Q1-2025",
                "created_at": "2026-03-21T10:01:00",
            },
            "job:other-job-001": {
                "job_id": "other-job-001",
                "status": "completed",
                "client_name": "other-corp",
                "period": "Q1-2025",
                "created_at": "2026-03-21T10:02:00",
            },
        }

        async def _scan(*args, **kwargs):
            for k in keys:
                yield k

        async def _hgetall(key):
            return job_records.get(key, {})

        redis_mock.scan_iter = _scan
        redis_mock.hgetall = AsyncMock(side_effect=_hgetall)

        response = await client.get("/api/jobs?client_name=acme")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        for job in data["jobs"]:
            assert job["client_name"] == "acme"

    @pytest.mark.asyncio
    async def test_client_name_filter_unknown_client_returns_empty(self, client, redis_mock):
        """Filtering by a client that has no jobs returns an empty list."""
        keys = ["job:acme-job-001"]
        job_records = {
            "job:acme-job-001": {
                "job_id": "acme-job-001",
                "status": "completed",
                "client_name": "acme",
                "created_at": "2026-03-21T10:00:00",
            },
        }

        async def _scan(*args, **kwargs):
            for k in keys:
                yield k

        async def _hgetall(key):
            return job_records.get(key, {})

        redis_mock.scan_iter = _scan
        redis_mock.hgetall = AsyncMock(side_effect=_hgetall)

        response = await client.get("/api/jobs?client_name=nobody")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["jobs"] == []


# ---------------------------------------------------------------------------
# Test: jobs list status filter
# ---------------------------------------------------------------------------


class TestJobsListStatusFilter:
    @pytest.mark.asyncio
    async def test_status_filter_completed_excludes_running(self, client, redis_mock):
        """status_filter=completed should only return completed jobs."""
        keys = [
            "job:comp-001",
            "job:comp-002",
            "job:running-001",
        ]
        job_records = {
            "job:comp-001": {
                "job_id": "comp-001",
                "status": "completed",
                "client_name": "acme",
                "created_at": "2026-03-21T10:00:00",
            },
            "job:comp-002": {
                "job_id": "comp-002",
                "status": "completed",
                "client_name": "acme",
                "created_at": "2026-03-21T10:01:00",
            },
            "job:running-001": {
                "job_id": "running-001",
                "status": "running",
                "client_name": "acme",
                "created_at": "2026-03-21T10:02:00",
            },
        }

        async def _scan(*args, **kwargs):
            for k in keys:
                yield k

        async def _hgetall(key):
            return job_records.get(key, {})

        redis_mock.scan_iter = _scan
        redis_mock.hgetall = AsyncMock(side_effect=_hgetall)

        response = await client.get("/api/jobs?status_filter=completed")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        for job in data["jobs"]:
            assert job["status"] == "completed"

    @pytest.mark.asyncio
    async def test_status_filter_running_excludes_completed(self, client, redis_mock):
        """status_filter=running should only return running jobs."""
        keys = ["job:comp-001", "job:running-001"]
        job_records = {
            "job:comp-001": {
                "job_id": "comp-001",
                "status": "completed",
                "client_name": "acme",
                "created_at": "2026-03-21T10:00:00",
            },
            "job:running-001": {
                "job_id": "running-001",
                "status": "running",
                "client_name": "acme",
                "created_at": "2026-03-21T10:01:00",
            },
        }

        async def _scan(*args, **kwargs):
            for k in keys:
                yield k

        async def _hgetall(key):
            return job_records.get(key, {})

        redis_mock.scan_iter = _scan
        redis_mock.hgetall = AsyncMock(side_effect=_hgetall)

        response = await client.get("/api/jobs?status_filter=running")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["jobs"][0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_combined_status_and_client_filter(self, client, redis_mock):
        """Combining status_filter and client_name applies both constraints."""
        keys = [
            "job:acme-done",
            "job:acme-running",
            "job:other-done",
        ]
        job_records = {
            "job:acme-done": {
                "job_id": "acme-done",
                "status": "completed",
                "client_name": "acme",
                "created_at": "2026-03-21T10:00:00",
            },
            "job:acme-running": {
                "job_id": "acme-running",
                "status": "running",
                "client_name": "acme",
                "created_at": "2026-03-21T10:01:00",
            },
            "job:other-done": {
                "job_id": "other-done",
                "status": "completed",
                "client_name": "other-corp",
                "created_at": "2026-03-21T10:02:00",
            },
        }

        async def _scan(*args, **kwargs):
            for k in keys:
                yield k

        async def _hgetall(key):
            return job_records.get(key, {})

        redis_mock.scan_iter = _scan
        redis_mock.hgetall = AsyncMock(side_effect=_hgetall)

        response = await client.get("/api/jobs?status_filter=completed&client_name=acme")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["jobs"][0]["job_id"] == "acme-done"
        assert data["jobs"][0]["client_name"] == "acme"
        assert data["jobs"][0]["status"] == "completed"
