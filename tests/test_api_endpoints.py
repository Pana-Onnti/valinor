"""
Tests for Valinor SaaS API endpoints.

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
# GET /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_structure(self, client):
        response = await client.get("/health")
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "components" in data
        assert "version" in data
        assert "redis" in data["components"]
        assert "storage" in data["components"]

    @pytest.mark.asyncio
    async def test_health_version(self, client):
        response = await client.get("/health")
        assert response.json()["version"] == "2.0.0"


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
        data = response = await client.get("/api/system/status")
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
    async def test_system_status_has_quality_checks(self, client):
        response = await client.get("/api/system/status")
        data = response.json()
        assert "quality_checks" in data
        assert isinstance(data["quality_checks"], list)
        assert len(data["quality_checks"]) > 0


# ---------------------------------------------------------------------------
# GET /api/system/metrics
# ---------------------------------------------------------------------------


class TestSystemMetricsEndpoint:
    """
    /api/system/metrics calls `from shared.memory.profile_store import get_profile_store`
    inline, so we patch the stub module's attribute directly for each test.
    """

    @staticmethod
    def _metrics_patch():
        """Context manager that patches profile store for inline import in endpoint."""
        store = _make_profile_store_mock()
        return patch(
            "shared.memory.profile_store.get_profile_store",
            return_value=store,
        )

    @pytest.mark.asyncio
    async def test_metrics_returns_200(self, client):
        with self._metrics_patch():
            response = await client.get("/api/system/metrics")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_metrics_structure(self, client):
        with self._metrics_patch():
            response = await client.get("/api/system/metrics")
        data = response.json()
        assert "jobs" in data
        assert "success_rate_pct" in data
        assert "timestamp" in data
        assert "estimated_total_cost_usd" in data

    @pytest.mark.asyncio
    async def test_metrics_jobs_has_status_counts(self, client):
        with self._metrics_patch():
            response = await client.get("/api/system/metrics")
        jobs = response.json()["jobs"]
        for key in ("completed", "failed", "running", "pending", "total"):
            assert key in jobs, f"Missing key '{key}' in jobs dict"

    @pytest.mark.asyncio
    async def test_metrics_success_rate_is_numeric(self, client):
        with self._metrics_patch():
            response = await client.get("/api/system/metrics")
        rate = response.json()["success_rate_pct"]
        assert isinstance(rate, (int, float))


# ---------------------------------------------------------------------------
# POST /api/analyze
# ---------------------------------------------------------------------------


class TestAnalyzeEndpoint:
    @pytest.mark.asyncio
    async def test_analyze_rate_limit_response_structure(self, client, redis_mock):
        """
        Simulate per-client concurrent job limit (>= 2 running jobs for the same
        client) and assert that a 429 with the expected error shape is returned.
        """
        # Make scan_iter yield two fake "running" keys for the same client
        async def _scan_two_running(*args, **kwargs):
            yield "job:aaaa"
            yield "job:bbbb"

        redis_mock.scan_iter = _scan_two_running

        async def _hget_side_effect(key, field):
            if field == "status":
                return "running"
            if field == "client_name":
                return "test-client"
            return None

        redis_mock.hget = AsyncMock(side_effect=_hget_side_effect)

        response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)
        assert response.status_code == 429
        detail = response.json().get("detail", {})
        # FastAPI wraps HTTPException detail as-is
        if isinstance(detail, dict):
            assert detail.get("error") == "too_many_concurrent_jobs"
        else:
            # Some versions may serialize detail as string
            assert "too_many_concurrent" in str(detail)

    @pytest.mark.asyncio
    async def test_analyze_invalid_client_name_special_chars(self, client):
        """client_name with spaces/special chars should return 422."""
        payload = {**VALID_ANALYSIS_PAYLOAD, "client_name": "bad name!"}
        response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_client_name_too_long(self, client):
        """client_name longer than 100 chars should return 422."""
        payload = {**VALID_ANALYSIS_PAYLOAD, "client_name": "a" * 101}
        response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_missing_db_config_returns_422(self, client):
        """Omitting db_config entirely must return a validation error."""
        response = await client.post("/api/analyze", json={"client_name": "test"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_missing_required_db_field(self, client):
        """db_config without 'type' must fail validation."""
        payload = {
            "client_name": "test-client",
            "db_config": {
                "host": "db.example.com",
                "port": 5432,
                # 'type' intentionally omitted
            },
        }
        response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_analyze_success_returns_job_id(self, client, redis_mock):
        """A valid request with no concurrent jobs should succeed and return job_id."""
        # Ensure no running jobs
        async def _empty_scan(*args, **kwargs):
            return
            yield

        redis_mock.scan_iter = _empty_scan

        with patch("api.main.run_analysis_task", new=AsyncMock()):
            response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "pending"


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/status  —  nonexistent job
# ---------------------------------------------------------------------------


class TestJobStatusEndpoint:
    @pytest.mark.asyncio
    async def test_nonexistent_job_returns_404(self, client, redis_mock):
        """An unknown job_id should yield a 404."""
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.get("/api/jobs/nonexistent-job/status")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_job_error_message(self, client, redis_mock):
        """
        The 404 body should contain an error indicator.
        The global @app.exception_handler(404) returns {"error": "not_found", "path": …}
        for unmatched routes; HTTPExceptions raised inside a route handler may be
        caught by the same handler or by FastAPI's default, depending on the version.
        Either way the response must clearly signal the error.
        """
        redis_mock.hgetall = AsyncMock(return_value={})
        response = await client.get("/api/jobs/nonexistent-job/status")
        data = response.json()
        # Accept either the custom handler shape or FastAPI's default detail shape
        has_error_key = "error" in data or "detail" in data
        assert has_error_key, f"Expected an error key in 404 body, got: {data}"

    @pytest.mark.asyncio
    async def test_existing_job_returns_status(self, client, redis_mock):
        """A job that exists in Redis should return its status fields."""
        from datetime import datetime

        redis_mock.hgetall = AsyncMock(
            return_value={
                "job_id": "test-job-123",
                "status": "running",
                "stage": "cartographer",
                "progress": "25",
                "message": "Mapping schema",
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        response = await client.get("/api/jobs/test-job-123/status")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "running"
        assert data["stage"] == "cartographer"
        assert data["progress"] == 25


# ---------------------------------------------------------------------------
# POST /api/onboarding/validate-period
# ---------------------------------------------------------------------------


class TestValidatePeriodEndpoint:
    @pytest.mark.asyncio
    async def test_valid_quarter_period(self, client):
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": "Q1-2025"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["period"] == "Q1-2025"

    @pytest.mark.asyncio
    async def test_valid_half_year_period(self, client):
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": "H2-2026"}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True

    @pytest.mark.asyncio
    async def test_valid_annual_period(self, client):
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": "2025"}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True

    @pytest.mark.asyncio
    async def test_invalid_period_free_text(self, client):
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": "last quarter"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "message" in data

    @pytest.mark.asyncio
    async def test_invalid_period_wrong_quarter(self, client):
        """Q5 is not a valid quarter."""
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": "Q5-2025"}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_invalid_period_wrong_half(self, client):
        """H3 is not a valid half-year."""
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": "H3-2025"}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_empty_period_is_invalid(self, client):
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": ""}
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_response_includes_period_echo(self, client):
        """The response must echo back the submitted period value."""
        response = await client.post(
            "/api/onboarding/validate-period", json={"period": "Q3-2026"}
        )
        assert response.json()["period"] == "Q3-2026"
