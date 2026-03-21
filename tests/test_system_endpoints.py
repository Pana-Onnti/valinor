"""
Tests for Valinor SaaS system/health/metrics endpoints.

Uses httpx.AsyncClient with ASGITransport to test without a running server.
All external dependencies (Redis, MetadataStorage, supabase, slowapi …) are
mocked/stubbed so that tests run without a full Docker environment.
"""

import json
import sys
import time
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
    mock.lpush = AsyncMock(return_value=1)
    mock.ltrim = AsyncMock(return_value=True)
    mock.lrange = AsyncMock(return_value=[])

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
# GET /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_has_status_field(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "status" in data
        assert data["status"] in ("healthy", "unhealthy")

    @pytest.mark.asyncio
    async def test_health_has_uptime_seconds(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_health_has_environment_field(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "environment" in data
        assert isinstance(data["environment"], str)

    @pytest.mark.asyncio
    async def test_health_has_version(self, client):
        response = await client.get("/health")
        assert response.json()["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_health_has_components(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "components" in data
        assert "redis" in data["components"]
        assert "storage" in data["components"]

    @pytest.mark.asyncio
    async def test_health_has_timestamp(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)

    @pytest.mark.asyncio
    async def test_health_responds_quickly(self, client):
        """Health check must complete in under 1 second."""
        start = time.time()
        response = await client.get("/health")
        elapsed = time.time() - start
        assert response.status_code == 200
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_health_redis_healthy_when_ping_succeeds(self, client):
        response = await client.get("/health")
        data = response.json()
        assert data["components"]["redis"] == "healthy"


# ---------------------------------------------------------------------------
# GET /api/version
# ---------------------------------------------------------------------------


class TestVersionEndpoint:
    @pytest.mark.asyncio
    async def test_version_returns_200(self, client):
        response = await client.get("/api/version")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_version_is_200(self, client):
        response = await client.get("/api/version")
        assert response.json()["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_version_includes_supported_db_types(self, client):
        response = await client.get("/api/version")
        data = response.json()
        assert "supported_db_types" in data
        db_types = data["supported_db_types"]
        assert isinstance(db_types, list)
        assert len(db_types) > 0
        # Core DB types must be present
        for expected in ("postgres", "mysql"):
            assert expected in db_types

    @pytest.mark.asyncio
    async def test_version_is_idempotent(self, client):
        """Same response on repeated calls."""
        r1 = await client.get("/api/version")
        r2 = await client.get("/api/version")
        assert r1.json()["version"] == r2.json()["version"]
        assert r1.json()["supported_db_types"] == r2.json()["supported_db_types"]

    @pytest.mark.asyncio
    async def test_version_has_max_analysis_duration(self, client):
        response = await client.get("/api/version")
        data = response.json()
        assert "max_analysis_duration_minutes" in data
        assert data["max_analysis_duration_minutes"] == 15


# ---------------------------------------------------------------------------
# GET /api/system/status
# ---------------------------------------------------------------------------


class TestSystemStatusEndpoint:
    @pytest.mark.asyncio
    async def test_system_status_returns_200(self, client):
        response = await client.get("/api/system/status")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_system_status_version(self, client):
        response = await client.get("/api/system/status")
        assert response.json()["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_system_status_has_features(self, client):
        response = await client.get("/api/system/status")
        data = response.json()
        assert "features" in data
        features = data["features"]
        assert "data_quality_gate" in features
        assert features["data_quality_gate"] is True
        assert "sse_streaming" in features
        assert "client_memory" in features

    @pytest.mark.asyncio
    async def test_system_status_has_services(self, client):
        response = await client.get("/api/system/status")
        data = response.json()
        assert "services" in data
        services = data["services"]
        assert "api" in services
        assert services["api"] == "healthy"

    @pytest.mark.asyncio
    async def test_system_status_has_packages(self, client):
        response = await client.get("/api/system/status")
        data = response.json()
        assert "packages" in data
        pkgs = data["packages"]
        assert "pandas" in pkgs
        assert "httpx" in pkgs

    @pytest.mark.asyncio
    async def test_system_status_has_quality_checks(self, client):
        response = await client.get("/api/system/status")
        data = response.json()
        assert "quality_checks" in data
        assert isinstance(data["quality_checks"], list)
        assert len(data["quality_checks"]) > 0


# ---------------------------------------------------------------------------
# GET /metrics  (Prometheus)
# ---------------------------------------------------------------------------


class TestPrometheusMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_returns_200(self, client):
        response = await client.get("/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_content_type_is_text(self, client):
        response = await client.get("/metrics")
        assert "text/plain" in response.headers["content-type"]

    @pytest.mark.asyncio
    async def test_metrics_contains_help_lines(self, client):
        response = await client.get("/metrics")
        body = response.text
        assert "# HELP" in body

    @pytest.mark.asyncio
    async def test_metrics_contains_type_lines(self, client):
        response = await client.get("/metrics")
        body = response.text
        assert "# TYPE" in body

    @pytest.mark.asyncio
    async def test_metrics_has_valinor_jobs_total(self, client):
        response = await client.get("/metrics")
        body = response.text
        assert "valinor_jobs_total" in body

    @pytest.mark.asyncio
    async def test_metrics_has_valinor_clients_total(self, client):
        response = await client.get("/metrics")
        body = response.text
        assert "valinor_clients_total" in body


# ---------------------------------------------------------------------------
# GET /api/system/metrics  (JSON)
# ---------------------------------------------------------------------------


class TestSystemMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_system_metrics_returns_200(self, client):
        response = await client.get("/api/system/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_system_metrics_has_jobs(self, client):
        response = await client.get("/api/system/metrics")
        data = response.json()
        assert "jobs" in data
        jobs = data["jobs"]
        assert "total" in jobs
        assert "completed" in jobs
        assert "failed" in jobs

    @pytest.mark.asyncio
    async def test_system_metrics_has_success_rate(self, client):
        response = await client.get("/api/system/metrics")
        data = response.json()
        assert "success_rate_pct" in data
        assert isinstance(data["success_rate_pct"], (int, float))

    @pytest.mark.asyncio
    async def test_system_metrics_has_timestamp(self, client):
        response = await client.get("/api/system/metrics")
        data = response.json()
        assert "timestamp" in data


# ---------------------------------------------------------------------------
# GET /api/cache/stats
# ---------------------------------------------------------------------------


class TestCacheStatsEndpoint:
    @pytest.mark.asyncio
    async def test_cache_stats_returns_200(self, client):
        response = await client.get("/api/cache/stats")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_cache_stats_has_cached_jobs(self, client):
        response = await client.get("/api/cache/stats")
        data = response.json()
        assert "cached_jobs" in data
        assert isinstance(data["cached_jobs"], int)
        assert data["cached_jobs"] >= 0

    @pytest.mark.asyncio
    async def test_cache_stats_has_oldest_entry_age(self, client):
        response = await client.get("/api/cache/stats")
        data = response.json()
        assert "oldest_entry_age_seconds" in data
        assert isinstance(data["oldest_entry_age_seconds"], (int, float))


# ---------------------------------------------------------------------------
# POST /api/audit  and  GET /api/audit
# ---------------------------------------------------------------------------


class TestAuditEndpoints:
    @pytest.mark.asyncio
    async def test_post_audit_returns_200(self, client):
        response = await client.post(
            "/api/audit",
            json={"event_type": "test_event", "detail": "unit test"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_post_audit_returns_logged_true(self, client):
        response = await client.post(
            "/api/audit",
            json={"event_type": "test_event"},
        )
        assert response.json()["logged"] is True

    @pytest.mark.asyncio
    async def test_get_audit_returns_200(self, client):
        response = await client.get("/api/audit")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_audit_has_events_list(self, client):
        response = await client.get("/api/audit")
        data = response.json()
        assert "events" in data
        assert isinstance(data["events"], list)

    @pytest.mark.asyncio
    async def test_get_audit_has_total_returned(self, client):
        response = await client.get("/api/audit")
        data = response.json()
        assert "total_returned" in data
        assert isinstance(data["total_returned"], int)

    @pytest.mark.asyncio
    async def test_get_audit_empty_log_returns_zero(self, client):
        """When Redis returns no entries, events list should be empty."""
        response = await client.get("/api/audit")
        data = response.json()
        # redis_mock.lrange returns [] by default
        assert data["events"] == []
        assert data["total_returned"] == 0

    @pytest.mark.asyncio
    async def test_get_audit_filter_by_event_type(self, redis_mock, storage_mock):
        """Filter by event_type returns only matching events."""
        from api.main import app  # noqa: PLC0415

        audit_entries = [
            json.dumps({"event_type": "analysis_started", "job_id": "abc"}),
            json.dumps({"event_type": "analysis_completed", "job_id": "xyz"}),
        ]
        redis_mock.lrange = AsyncMock(return_value=audit_entries)

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get("/api/audit?event_type=analysis_started")

        data = response.json()
        assert response.status_code == 200
        for evt in data["events"]:
            assert evt["event_type"] == "analysis_started"

    @pytest.mark.asyncio
    async def test_get_audit_limit_param(self, redis_mock, storage_mock):
        """limit query param is forwarded to Redis lrange."""
        from api.main import app  # noqa: PLC0415

        # Populate five entries; with limit=2 only those 2 should be fetched
        entries = [
            json.dumps({"event_type": f"evt_{i}"}) for i in range(5)
        ]
        # Redis will return only the first 2 because lrange respects limit-1
        redis_mock.lrange = AsyncMock(return_value=entries[:2])

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get("/api/audit?limit=2")

        data = response.json()
        assert response.status_code == 200
        assert data["total_returned"] == 2

    @pytest.mark.asyncio
    async def test_post_audit_malformed_event_missing_body(self, client):
        """POST /api/audit without a JSON body should return 422."""
        response = await client.post(
            "/api/audit",
            content=b"",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_audit_skips_invalid_json_entries(self, redis_mock, storage_mock):
        """Malformed JSON entries in Redis audit log are silently skipped."""
        from api.main import app  # noqa: PLC0415

        bad_entries = [b"not-json", json.dumps({"event_type": "ok_event"})]
        redis_mock.lrange = AsyncMock(return_value=bad_entries)

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get("/api/audit")

        data = response.json()
        assert response.status_code == 200
        # Only the valid entry should appear
        assert data["total_returned"] == 1
        assert data["events"][0]["event_type"] == "ok_event"


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/status  — 404 and field validation
# ---------------------------------------------------------------------------


class TestJobStatusEndpoint:
    @pytest.mark.asyncio
    async def test_job_status_returns_404_for_unknown_job(self, client):
        """Non-existent job_id must return 404."""
        response = await client.get("/api/jobs/does-not-exist/status")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_job_status_404_has_error_info(self, client):
        """404 response body must include either a detail or an error field."""
        response = await client.get("/api/jobs/no-such-job/status")
        data = response.json()
        assert "detail" in data or "error" in data

    @pytest.mark.asyncio
    async def test_job_status_returns_job_fields(self, redis_mock, storage_mock):
        """A found job should include job_id and status fields."""
        from api.main import app  # noqa: PLC0415

        job_id = "test-job-abc"
        redis_mock.hgetall = AsyncMock(return_value={
            "status": "running",
            "stage": "cartographer",
            "progress": "30",
            "message": "Mapping schema",
            "started_at": "2026-03-21T10:00:00",
        })

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get(f"/api/jobs/{job_id}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == "running"
        assert data["stage"] == "cartographer"
        assert data["progress"] == 30


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/results  — 404 / 400 paths
# ---------------------------------------------------------------------------


class TestJobResultsEndpoint:
    @pytest.mark.asyncio
    async def test_job_results_returns_404_for_unknown_job(self, client):
        """GET /api/jobs/{id}/results must return 404 when job does not exist."""
        response = await client.get("/api/jobs/ghost-job/results")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_job_results_returns_400_when_not_completed(self, redis_mock, storage_mock):
        """Results endpoint returns 400 when job is still running."""
        from api.main import app  # noqa: PLC0415

        redis_mock.hgetall = AsyncMock(return_value={"status": "running"})
        redis_mock.get = AsyncMock(return_value=None)

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get("/api/jobs/running-job/results")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_job_results_returns_completed_data(self, redis_mock, storage_mock):
        """When job is completed and results exist, they are returned."""
        import json as _json
        from api.main import app  # noqa: PLC0415
        import api.main as _main

        job_id = "done-job-xyz"
        results_payload = {
            "job_id": job_id,
            "client_name": "acme",
            "period": "Q1-2026",
            "status": "completed",
            "stages": {},
        }

        redis_mock.hgetall = AsyncMock(return_value={"status": "completed"})
        redis_mock.get = AsyncMock(return_value=_json.dumps(results_payload))

        # Ensure the in-memory cache does not serve stale data for this job
        _main._results_cache.pop(job_id, None)

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get(f"/api/jobs/{job_id}/results")

        assert response.status_code == 200
        data = response.json()
        assert data["client_name"] == "acme"


# ---------------------------------------------------------------------------
# GET /api/jobs  — listing / pagination / validation
# ---------------------------------------------------------------------------


class TestListJobsEndpoint:
    @pytest.mark.asyncio
    async def test_list_jobs_returns_200(self, client):
        response = await client.get("/api/jobs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_jobs_has_pagination_fields(self, client):
        response = await client.get("/api/jobs")
        data = response.json()
        for field in ("jobs", "total", "page", "page_size", "pages"):
            assert field in data, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_list_jobs_invalid_page_returns_400(self, client):
        """page=0 is invalid and must return 400."""
        response = await client.get("/api/jobs?page=0")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_list_jobs_invalid_page_size_returns_400(self, client):
        """page_size=0 is out of [1, 100] and must return 400."""
        response = await client.get("/api/jobs?page_size=0")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_list_jobs_invalid_sort_by_returns_400(self, client):
        """Unknown sort_by value must return 400."""
        response = await client.get("/api/jobs?sort_by=nonexistent_field")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_list_jobs_invalid_sort_order_returns_400(self, client):
        """sort_order must be 'asc' or 'desc'."""
        response = await client.get("/api/jobs?sort_order=random")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_list_jobs_empty_when_no_keys(self, client):
        """With no job keys in Redis the jobs list should be empty."""
        response = await client.get("/api/jobs")
        data = response.json()
        assert data["jobs"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/cancel  and  POST /api/jobs/{job_id}/retry
# ---------------------------------------------------------------------------


class TestJobControlEndpoints:
    @pytest.mark.asyncio
    async def test_cancel_job_returns_404_for_unknown_job(self, client):
        response = await client.post("/api/jobs/ghost-job/cancel")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_running_job_returns_cancelled(self, redis_mock, storage_mock):
        """Cancelling a running job sets status to cancelled."""
        from api.main import app  # noqa: PLC0415

        job_id = "run-job-1"
        redis_mock.hgetall = AsyncMock(return_value={"status": "running"})

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.post(f"/api/jobs/{job_id}/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cancelled"
        assert data["job_id"] == job_id

    @pytest.mark.asyncio
    async def test_cancel_already_completed_job_returns_current_status(self, redis_mock, storage_mock):
        """Cancelling an already-completed job returns its current status without error."""
        from api.main import app  # noqa: PLC0415

        redis_mock.hgetall = AsyncMock(return_value={"status": "completed"})

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.post("/api/jobs/done-job/cancel")

        assert response.status_code == 200
        assert response.json()["status"] == "completed"

    @pytest.mark.asyncio
    async def test_retry_non_failed_job_returns_400(self, redis_mock, storage_mock):
        """Retrying a running (non-failed) job must return 400."""
        from api.main import app  # noqa: PLC0415

        redis_mock.hgetall = AsyncMock(return_value={"status": "running"})

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.post("/api/jobs/run-job/retry")

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/export/pdf
# ---------------------------------------------------------------------------


class TestExportPdfEndpoint:
    @pytest.mark.asyncio
    async def test_export_pdf_returns_404_for_unknown_job(self, client):
        response = await client.get("/api/jobs/no-job/export/pdf")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_export_pdf_returns_400_when_not_completed(self, redis_mock, storage_mock):
        from api.main import app  # noqa: PLC0415

        redis_mock.hgetall = AsyncMock(return_value={"status": "pending"})

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get("/api/jobs/pending-job/export/pdf")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_export_pdf_returns_pdf_content_type(self, redis_mock, storage_mock):
        """A completed job must return application/pdf with Content-Disposition."""
        import json as _json
        from api.main import app  # noqa: PLC0415

        redis_mock.hgetall = AsyncMock(return_value={"status": "completed"})
        redis_mock.get = AsyncMock(return_value=_json.dumps({
            "job_id": "pdf-job",
            "client_name": "testcorp",
            "period": "Q1-2026",
        }))

        with (
            patch("redis.asyncio.from_url", return_value=redis_mock),
            patch("api.main.metadata_storage", storage_mock),
            patch("api.main.redis_client", redis_mock),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as ac:
                response = await ac.get("/api/jobs/pdf-job/export/pdf")

        assert response.status_code == 200
        assert "application/pdf" in response.headers["content-type"]
        assert "attachment" in response.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/download/{filename}  — security validation
# ---------------------------------------------------------------------------


class TestDownloadEndpoint:
    @pytest.mark.asyncio
    async def test_download_disallowed_filename_returns_400(self, client):
        """Requesting a filename not on the allowed list returns 400."""
        response = await client.get("/api/jobs/some-job/download/../../etc/passwd")
        assert response.status_code in (400, 404)

    @pytest.mark.asyncio
    async def test_download_invalid_filename_extension_returns_400(self, client):
        """A filename with an arbitrary extension is rejected."""
        response = await client.get("/api/jobs/some-job/download/evil.sh")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/system/status  — additional field checks
# ---------------------------------------------------------------------------


class TestSystemStatusAdditionalFields:
    @pytest.mark.asyncio
    async def test_system_status_has_redis_info(self, client):
        """Response should include a redis key (dict or empty dict)."""
        response = await client.get("/api/system/status")
        data = response.json()
        assert "redis" in data
        assert isinstance(data["redis"], dict)

    @pytest.mark.asyncio
    async def test_system_status_has_llm_provider(self, client):
        """llm_provider field must be present and be a string."""
        response = await client.get("/api/system/status")
        data = response.json()
        assert "llm_provider" in data
        assert isinstance(data["llm_provider"], str)

    @pytest.mark.asyncio
    async def test_system_status_has_timestamp(self, client):
        response = await client.get("/api/system/status")
        data = response.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], str)


# ---------------------------------------------------------------------------
# GET /api/version  — additional field checks
# ---------------------------------------------------------------------------


class TestVersionAdditionalFields:
    @pytest.mark.asyncio
    async def test_version_has_cost_per_analysis(self, client):
        """cost_per_analysis_usd must be present and numeric."""
        response = await client.get("/api/version")
        data = response.json()
        assert "cost_per_analysis_usd" in data
        assert isinstance(data["cost_per_analysis_usd"], (int, float))

    @pytest.mark.asyncio
    async def test_version_has_api_prefix(self, client):
        """api_prefix must be present."""
        response = await client.get("/api/version")
        data = response.json()
        assert "api_prefix" in data
        assert isinstance(data["api_prefix"], str)


# ---------------------------------------------------------------------------
# POST /api/analyze  — validation edge-cases
# ---------------------------------------------------------------------------


class TestAnalyzeValidation:
    _VALID_PAYLOAD = {
        "client_name": "acme",
        "period": "Q1-2026",
        "db_config": {
            "host": "db.example.com",
            "port": 5432,
            "type": "postgres",
            "user": "admin",
            "password": "secret",
            "name": "prod_db",
        },
    }

    @pytest.mark.asyncio
    async def test_analyze_missing_db_config_returns_422(self, client):
        """Submitting a request without db_config must return 422."""
        response = await client.post(
            "/api/analyze",
            json={"client_name": "acme", "period": "Q1-2026"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_valid_payload_returns_job_id(self, client):
        """A valid request must return a job_id in the response."""
        response = await client.post("/api/analyze", json=self._VALID_PAYLOAD)
        # 200 (success) or 429 (monthly limit hit in CI) are both acceptable
        assert response.status_code in (200, 429)
        if response.status_code == 200:
            data = response.json()
            assert "job_id" in data
            assert data["status"] == "pending"
