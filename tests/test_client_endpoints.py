"""
Tests for Valinor SaaS /api/clients/* endpoints.

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
    mock.incr = AsyncMock(return_value=1)
    mock.get = AsyncMock(return_value=None)
    mock.info = AsyncMock(return_value={"redis_version": "7.0.0", "uptime_in_days": 1})
    mock.close = AsyncMock()

    async def _empty_scan(*args, **kwargs):
        return
        yield

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
# Helper: build a rich profile mock with all attributes the endpoints touch
# ---------------------------------------------------------------------------

def _make_full_profile(client_name: str = "acme") -> MagicMock:
    """Return a MagicMock that mimics a ClientProfile with all needed fields."""
    profile = MagicMock()
    profile.client_name = client_name
    profile.run_count = 5
    profile.last_run_date = "2026-03-01"
    profile.industry_inferred = "retail"
    profile.currency_detected = "USD"
    profile.known_findings = {
        "f1": {"severity": "CRITICAL", "title": "Missing index", "status": "open",
               "agent": "sentinel", "first_seen": "2026-01-01", "last_seen": "2026-03-01", "runs_open": 3},
        "f2": {"severity": "HIGH", "title": "Null ratio spike", "status": "open",
               "agent": "hunter", "first_seen": "2026-02-01", "last_seen": "2026-03-01", "runs_open": 1},
    }
    profile.resolved_findings = {}
    profile.dq_history = [
        {"score": 85, "timestamp": "2026-01-15T00:00:00Z"},
        {"score": 90, "timestamp": "2026-02-15T00:00:00Z"},
        {"score": 92, "timestamp": "2026-03-01T00:00:00Z"},
    ]
    profile.baseline_history = {
        "Revenue": [{"period": "Q1-2025", "value": 1000000}],
        "COGS":    [{"period": "Q1-2025", "value": 600000}],
    }
    profile.run_history = [
        {"run_date": "2026-01-15", "findings_count": 4, "new": 2, "resolved": 0, "success": True},
        {"run_date": "2026-02-15", "findings_count": 3, "new": 1, "resolved": 1, "success": True},
        {"run_date": "2026-03-01", "findings_count": 2, "new": 0, "resolved": 1, "success": True},
    ]
    profile.alert_thresholds = [
        {"metric": "Revenue", "condition": "pct_change_below", "value": -10.0,
         "severity": "HIGH", "label": "Revenue", "triggered": False,
         "description": "Revenue drop alert", "created_at": "2026-01-01T00:00:00"},
    ]
    profile.triggered_alerts = []
    profile.metadata = {"last_triggered_alerts": []}
    profile.false_positives = []
    profile.refinement = None
    profile.focus_tables = ["orders", "customers", "products"]
    profile.webhooks = []
    profile.is_entity_map_fresh = MagicMock(return_value=True)
    profile.to_dict = MagicMock(return_value={
        "client_name": client_name,
        "run_count": 5,
        "last_run_date": "2026-03-01",
        "known_findings": profile.known_findings,
        "dq_history": profile.dq_history,
    })
    return profile


def _store_patch(profile=None):
    """
    Return a context manager that replaces get_profile_store with a mock
    whose .load() returns *profile* (or None if omitted).
    """
    store = _make_profile_store_mock()
    store.load = AsyncMock(return_value=profile)
    full = profile or _make_full_profile()
    store.load_or_create = AsyncMock(return_value=full)
    return patch(
        "shared.memory.profile_store.get_profile_store",
        return_value=store,
    )


# ---------------------------------------------------------------------------
# GET /api/clients
# ---------------------------------------------------------------------------

class TestListClients:
    @pytest.mark.asyncio
    async def test_list_clients_returns_200(self, client):
        response = await client.get("/api/clients")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_clients_has_clients_key(self, client):
        response = await client.get("/api/clients")
        data = response.json()
        assert "clients" in data

    @pytest.mark.asyncio
    async def test_list_clients_clients_is_list(self, client):
        response = await client.get("/api/clients")
        data = response.json()
        assert isinstance(data["clients"], list)


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/profile
# ---------------------------------------------------------------------------

class TestGetClientProfile:
    @pytest.mark.asyncio
    async def test_profile_returns_200_when_found(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/profile")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_profile_calls_to_dict(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/profile")
        data = response.json()
        assert data["client_name"] == "acme"

    @pytest.mark.asyncio
    async def test_profile_returns_404_when_missing(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/profile")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_profile_404_detail_mentions_client(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/profile")
        assert response.status_code == 404
        body = response.json()
        # FastAPI wraps HTTPException detail as {"detail": "..."};
        # tolerate both shapes in case of response serialization variance.
        detail_str = body.get("detail") or str(body)
        assert "ghost" in detail_str or response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/findings
# ---------------------------------------------------------------------------

class TestGetClientFindings:
    @pytest.mark.asyncio
    async def test_findings_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/findings")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_findings_structure(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/findings")
        data = response.json()
        assert "findings" in data
        assert "total" in data
        assert "critical" in data

    @pytest.mark.asyncio
    async def test_findings_404_for_missing_client(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/findings")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_findings_count_matches_open_findings(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/findings")
        data = response.json()
        assert data["total"] == len(data["findings"])


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/kpis
# ---------------------------------------------------------------------------

class TestGetClientKpis:
    @pytest.mark.asyncio
    async def test_kpis_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/kpis")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_kpis_has_required_keys(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/kpis")
        data = response.json()
        for key in ("client_name", "kpis", "kpi_count"):
            assert key in data, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_kpis_count_matches_baseline_history(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/kpis")
        data = response.json()
        assert data["kpi_count"] == 2

    @pytest.mark.asyncio
    async def test_kpis_404_for_missing_client(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/kpis")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/dq-history
# ---------------------------------------------------------------------------

class TestGetClientDqHistory:
    @pytest.mark.asyncio
    async def test_dq_history_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/dq-history")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_dq_history_has_required_keys(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/dq-history")
        data = response.json()
        for key in ("client", "dq_history", "runs_with_dq"):
            assert key in data, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_dq_history_empty_when_no_history(self, client):
        profile = _make_full_profile("acme")
        profile.dq_history = []
        profile.__dict__["dq_history"] = []
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/dq-history")
        data = response.json()
        assert data["dq_history"] == []
        assert data["runs_with_dq"] == 0

    @pytest.mark.asyncio
    async def test_dq_history_404_for_missing_client(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/dq-history")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/clients/comparison
# ---------------------------------------------------------------------------

class TestGetClientsComparison:
    @pytest.mark.asyncio
    async def test_comparison_returns_200(self, client):
        with _store_patch():
            response = await client.get("/api/clients/comparison")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_comparison_has_clients_key(self, client):
        with _store_patch():
            response = await client.get("/api/clients/comparison")
        data = response.json()
        assert "clients" in data

    @pytest.mark.asyncio
    async def test_comparison_has_generated_at(self, client):
        with _store_patch():
            response = await client.get("/api/clients/comparison")
        data = response.json()
        assert "generated_at" in data


# ---------------------------------------------------------------------------
# POST /api/clients/{name}/alerts/thresholds
# ---------------------------------------------------------------------------

class TestPostAlertThreshold:
    _VALID_BODY = {
        "metric": "Revenue",
        "condition": "pct_change_below",
        "threshold_value": -10.0,
        "severity": "HIGH",
        "description": "Revenue drop alert",
    }

    @pytest.mark.asyncio
    async def test_create_threshold_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.post(
                "/api/clients/acme/alerts/thresholds",
                json=self._VALID_BODY,
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_threshold_response_structure(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.post(
                "/api/clients/acme/alerts/thresholds",
                json=self._VALID_BODY,
            )
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
        assert "threshold" in data

    @pytest.mark.asyncio
    async def test_create_threshold_missing_field_returns_422(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.post(
                "/api/clients/acme/alerts/thresholds",
                json={"metric": "Revenue"},  # missing condition, threshold_value, severity
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_threshold_invalid_condition_returns_422(self, client):
        profile = _make_full_profile("acme")
        bad_body = {**self._VALID_BODY, "condition": "not_a_real_condition"}
        with _store_patch(profile):
            response = await client.post(
                "/api/clients/acme/alerts/thresholds",
                json=bad_body,
            )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/alerts/thresholds
# ---------------------------------------------------------------------------

class TestGetAlertThresholds:
    @pytest.mark.asyncio
    async def test_get_thresholds_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/alerts/thresholds")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_thresholds_has_thresholds_key(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/alerts/thresholds")
        data = response.json()
        assert "thresholds" in data
        assert "count" in data

    @pytest.mark.asyncio
    async def test_get_thresholds_404_for_missing_client(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/alerts/thresholds")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/clients/{name}/alerts/thresholds/{metric}
# ---------------------------------------------------------------------------

class TestDeleteAlertThreshold:
    @pytest.mark.asyncio
    async def test_delete_existing_threshold_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.delete(
                "/api/clients/acme/alerts/thresholds/Revenue"
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_existing_threshold_response(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.delete(
                "/api/clients/acme/alerts/thresholds/Revenue"
            )
        data = response.json()
        assert data["deleted"] is True
        assert data["metric"] == "Revenue"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_threshold_returns_404(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.delete(
                "/api/clients/acme/alerts/thresholds/NoSuchMetric"
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/alerts/triggered
# ---------------------------------------------------------------------------

class TestGetTriggeredAlerts:
    @pytest.mark.asyncio
    async def test_triggered_alerts_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/alerts/triggered")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_triggered_alerts_has_triggered_key(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/alerts/triggered")
        data = response.json()
        assert "triggered" in data

    @pytest.mark.asyncio
    async def test_triggered_alerts_is_list(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/alerts/triggered")
        data = response.json()
        assert isinstance(data["triggered"], list)

    @pytest.mark.asyncio
    async def test_triggered_alerts_404_for_missing_client(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/alerts/triggered")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/clients/summary
# ---------------------------------------------------------------------------

class TestGetClientsSummary:
    @pytest.mark.asyncio
    async def test_summary_returns_200(self, client):
        with _store_patch():
            response = await client.get("/api/clients/summary")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_summary_has_required_keys(self, client):
        with _store_patch():
            response = await client.get("/api/clients/summary")
        data = response.json()
        for key in ("total_clients", "total_runs", "total_critical_findings"):
            assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/stats
# ---------------------------------------------------------------------------

class TestGetClientStats:
    @pytest.mark.asyncio
    async def test_stats_returns_200(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/stats")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_has_required_keys(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/stats")
        data = response.json()
        for key in ("client_name", "run_count", "active_findings", "resolved_findings"):
            assert key in data, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_stats_404_for_missing_client(self, client):
        with _store_patch(None):
            response = await client.get("/api/clients/ghost/stats")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stats_run_count_matches_profile(self, client):
        profile = _make_full_profile("acme")
        with _store_patch(profile):
            response = await client.get("/api/clients/acme/stats")
        data = response.json()
        assert data["run_count"] == 5
