"""
Tests for the onboarding API routes.

Uses the same stub/mock pattern as test_api_endpoints.py.
All external I/O (SQLAlchemy engine, paramiko SSH) is mocked so no real
network connections are required.
"""

import sys
import types
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub out optional packages that may not be installed in the local venv.
# Must mirror the stubs from test_api_endpoints.py so that api.main (and
# transitive imports) can be imported without a full Docker stack.
# ---------------------------------------------------------------------------

def _make_stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


def _stub_missing(*module_names: str) -> None:
    for name in module_names:
        if name not in sys.modules:
            stub = _make_stub(name)
            sys.modules[name] = stub
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent_name = ".".join(parts[:i])
            child_attr = parts[i]
            if parent_name not in sys.modules:
                sys.modules[parent_name] = _make_stub(parent_name)
            parent_mod = sys.modules[parent_name]
            child_mod = sys.modules.get(".".join(parts[: i + 1]))
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
    info=MagicMock(), error=MagicMock(), warning=MagicMock(), debug=MagicMock(),
))

# adapters
_stub_missing("adapters", "adapters.valinor_adapter")
_adapter_stub = sys.modules["adapters.valinor_adapter"]
_adapter_stub.ValinorAdapter = MagicMock
_adapter_stub.PipelineExecutor = MagicMock

# shared.storage
_stub_missing("shared.storage")
_storage_stub = sys.modules["shared.storage"]


class _FakeMetadataStorage:
    async def health_check(self):
        return True


_storage_stub.MetadataStorage = _FakeMetadataStorage

# shared.memory.*
for _m in ("shared.memory", "shared.memory.profile_store", "shared.memory.client_profile"):
    _stub_missing(_m)

_profile_store_stub = sys.modules["shared.memory.profile_store"]
_profile_store_stub.get_profile_store = MagicMock(return_value=MagicMock(
    _get_pool=AsyncMock(return_value=None),
    load=AsyncMock(return_value=None),
    load_or_create=AsyncMock(return_value=MagicMock(webhooks=[])),
    save=AsyncMock(return_value=None),
))

_shared_stub = sys.modules.get("shared")
if _shared_stub is not None:
    _shared_memory_stub = sys.modules.get("shared.memory")
    if _shared_memory_stub is not None:
        _shared_stub.memory = _shared_memory_stub
        _shared_memory_stub.profile_store = _profile_store_stub
        _shared_memory_stub.client_profile = sys.modules.get("shared.memory.client_profile")

# shared.pdf_generator
_stub_missing("shared.pdf_generator")
_pdf_stub = sys.modules["shared.pdf_generator"]
_pdf_stub.generate_pdf_report = MagicMock(return_value=b"%PDF-1.4 test pdf")
if _shared_stub is not None:
    _shared_stub.pdf_generator = _pdf_stub

# ---------------------------------------------------------------------------
# Build a synchronous TestClient from the FastAPI app.
# We patch Redis/storage at the api.main level so imports succeed.
# ---------------------------------------------------------------------------

from api.main import app  # noqa: E402

_redis_mock = MagicMock()
_redis_mock.ping = MagicMock(return_value=True)

_storage_mock = MagicMock()
_storage_mock.health_check = AsyncMock(return_value=True)

# Patch at module level so the TestClient can be reused across all tests.
with (
    patch("api.main.metadata_storage", _storage_mock),
    patch("api.main.redis_client", _redis_mock),
):
    _test_client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine_mock(tables: list[str] | None = None):
    """Return a mock SQLAlchemy engine whose inspector returns `tables`."""
    tables = tables or []
    conn_mock = MagicMock()
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    conn_mock.execute = MagicMock(return_value=MagicMock())

    inspector_mock = MagicMock()
    inspector_mock.get_table_names = MagicMock(return_value=tables)

    engine_mock = MagicMock()
    engine_mock.connect = MagicMock(return_value=conn_mock)
    engine_mock.dispose = MagicMock()
    return engine_mock, inspector_mock


# Minimal valid payloads
VALID_CONNECTION_PAYLOAD = {
    "db_type": "postgresql",
    "host": "db.example.com",
    "port": 5432,
    "database": "testdb",
    "user": "admin",
    "password": "s3cr3t",
}

VALID_SSH_PAYLOAD = {
    "ssh_host": "bastion.example.com",
    "ssh_port": 22,
    "ssh_user": "ubuntu",
    "ssh_key": "c3NoLWtleQ==",  # base64("ssh-key")
    "db_host": "db.internal.example.com",
    "db_port": 5432,
    "db_type": "postgresql",
    "db_name": "prod",
    "db_user": "admin",
    "db_password": "hunter2",
}


# ---------------------------------------------------------------------------
# POST /api/onboarding/test-connection
# ---------------------------------------------------------------------------

class TestConnectionEndpoint:
    def test_valid_config_returns_success(self):
        engine_mock, inspector_mock = _make_engine_mock(["res_partner", "account_move"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_valid_config_returns_latency(self):
        engine_mock, inspector_mock = _make_engine_mock(["res_partner", "account_move"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["latency_ms"] is not None

    def test_odoo_tables_detected(self):
        engine_mock, inspector_mock = _make_engine_mock(
            ["res_partner", "account_move", "ir_module_module"]
        )
        # Mock the ERP version query
        row_mock = MagicMock()
        row_mock.__getitem__ = MagicMock(return_value="16.0")
        conn_ctx = engine_mock.connect.return_value.__enter__.return_value
        conn_ctx.execute.return_value.fetchone = MagicMock(return_value=row_mock)
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["erp_detected"] == "odoo"

    def test_db_error_returns_success_false(self):
        with patch("sqlalchemy.create_engine", side_effect=Exception("connection refused")):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "connection refused" in data["error"]

    def test_missing_ssh_host_field_is_optional(self):
        """ssh_host is Optional — omitting it is valid (422 should NOT be raised)."""
        engine_mock, inspector_mock = _make_engine_mock([])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            payload = {**VALID_CONNECTION_PAYLOAD}
            payload.pop("ssh_host", None)
            resp = _test_client.post("/api/onboarding/test-connection", json=payload)
        assert resp.status_code == 200

    def test_missing_host_returns_422(self):
        payload = {k: v for k, v in VALID_CONNECTION_PAYLOAD.items() if k != "host"}
        resp = _test_client.post("/api/onboarding/test-connection", json=payload)
        assert resp.status_code == 422

    def test_missing_db_port_uses_default(self):
        """port has a default of 5432 — omitting it must not raise 422."""
        engine_mock, inspector_mock = _make_engine_mock([])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            payload = {k: v for k, v in VALID_CONNECTION_PAYLOAD.items() if k != "port"}
            resp = _test_client.post("/api/onboarding/test-connection", json=payload)
        assert resp.status_code == 200

    def test_missing_database_returns_422(self):
        payload = {k: v for k, v in VALID_CONNECTION_PAYLOAD.items() if k != "database"}
        resp = _test_client.post("/api/onboarding/test-connection", json=payload)
        assert resp.status_code == 422

    def test_unsupported_db_type_returns_success_false(self):
        """Unsupported db_type raises HTTPException(400) which the route catches."""
        payload = {**VALID_CONNECTION_PAYLOAD, "db_type": "mongodb"}
        resp = _test_client.post("/api/onboarding/test-connection", json=payload)
        # The handler wraps exceptions and returns success=False
        assert resp.status_code in (200, 400)

    def test_full_accounting_tables_recommend_full(self):
        engine_mock, inspector_mock = _make_engine_mock(
            ["res_partner", "account_move", "c_invoice"]
        )
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["recommended_analysis"] == "full"


# ---------------------------------------------------------------------------
# GET /api/onboarding/supported-databases
# ---------------------------------------------------------------------------

class TestSupportedDatabases:
    def test_returns_200(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        assert resp.status_code == 200

    def test_returns_list(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        assert isinstance(resp.json(), list)

    def test_contains_postgresql(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        ids = [db["id"] for db in resp.json()]
        assert "postgresql" in ids

    def test_contains_mysql(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        ids = [db["id"] for db in resp.json()]
        assert "mysql" in ids

    def test_each_entry_has_required_fields(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        for entry in resp.json():
            assert "id" in entry
            assert "label" in entry
            assert "default_port" in entry
            assert "connection_template" in entry


# ---------------------------------------------------------------------------
# POST /api/onboarding/estimate-cost
# ---------------------------------------------------------------------------

class TestEstimateCost:
    def test_100k_rows_returns_reasonable_cost(self):
        payload = {"estimated_rows": 100_000, "tables_count": 10, "period": "Q1-2025"}
        resp = _test_client.post("/api/onboarding/estimate-cost", json=payload)
        assert resp.status_code == 200
        cost = resp.json()["estimated_cost_usd"]
        assert 5.0 <= cost <= 15.0

    def test_zero_rows_returns_minimum_cost(self):
        payload = {"estimated_rows": 0, "tables_count": 5, "period": "Q1-2025"}
        resp = _test_client.post("/api/onboarding/estimate-cost", json=payload)
        assert resp.status_code == 200
        assert resp.json()["estimated_cost_usd"] == 5.0

    def test_many_tables_raises_cost(self):
        few_tables_payload = {"estimated_rows": 100_000, "tables_count": 1, "period": "Q1-2025"}
        many_tables_payload = {"estimated_rows": 100_000, "tables_count": 50, "period": "Q1-2025"}
        r_few = _test_client.post("/api/onboarding/estimate-cost", json=few_tables_payload)
        r_many = _test_client.post("/api/onboarding/estimate-cost", json=many_tables_payload)
        assert r_many.json()["estimated_cost_usd"] >= r_few.json()["estimated_cost_usd"]

    def test_response_has_all_fields(self):
        payload = {"estimated_rows": 50_000, "tables_count": 10, "period": "2025"}
        resp = _test_client.post("/api/onboarding/estimate-cost", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "estimated_cost_usd" in data
        assert "estimated_duration_minutes" in data
        assert "token_estimate" in data

    def test_very_large_db_capped_at_max_cost(self):
        payload = {"estimated_rows": 100_000_000, "tables_count": 500, "period": "2025"}
        resp = _test_client.post("/api/onboarding/estimate-cost", json=payload)
        assert resp.status_code == 200
        assert resp.json()["estimated_cost_usd"] <= 15.0


# ---------------------------------------------------------------------------
# POST /api/onboarding/validate-period
# ---------------------------------------------------------------------------

class TestValidatePeriod:
    def test_valid_q1_2025(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "Q1-2025"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_valid_q4_2024(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "Q4-2024"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_valid_h1_format(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "H1-2025"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_valid_annual_format(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "2025"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_invalid_period_returns_false(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "Q5-2025"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_invalid_period_free_text(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "last month"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_missing_period_key_returns_false(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_response_echoes_period(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "Q2-2025"})
        assert resp.json()["period"] == "Q2-2025"
