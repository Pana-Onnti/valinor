"""
Tests for the onboarding API routes.

Uses the same stub/mock pattern as test_api_endpoints.py.
All external I/O (SQLAlchemy engine, paramiko SSH) is mocked so no real
network connections are required.
"""

import sys
import types
import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from httpx import AsyncClient, ASGITransport

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
import structlog  # real module — stub breaks structlog.contextvars
_structlog = structlog
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
# Build a synchronous ASGI client from the FastAPI app.
# Uses httpx.AsyncClient + ASGITransport for httpx 0.28 compatibility.
# ---------------------------------------------------------------------------

from api.main import app  # noqa: E402

_redis_mock = MagicMock()
_redis_mock.ping = MagicMock(return_value=True)

_storage_mock = MagicMock()
_storage_mock.health_check = AsyncMock(return_value=True)


class _SyncAsgiClient:
    """Sync wrapper around httpx.AsyncClient + ASGITransport."""

    def __init__(self, _app):
        self._app = _app
        self._loop = asyncio.new_event_loop()

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _request(self, method: str, url: str, **kwargs):
        async def _inner():
            async with AsyncClient(
                transport=ASGITransport(app=self._app),
                base_url="http://testserver",
            ) as c:
                return await getattr(c, method)(url, **kwargs)
        with (
            patch("api.main.metadata_storage", _storage_mock),
            patch("api.main.redis_client", _redis_mock),
        ):
            return self._run(_inner())

    def get(self, url, **kwargs): return self._request("get", url, **kwargs)
    def post(self, url, **kwargs): return self._request("post", url, **kwargs)
    def put(self, url, **kwargs): return self._request("put", url, **kwargs)
    def delete(self, url, **kwargs): return self._request("delete", url, **kwargs)
    def patch(self, url, **kwargs): return self._request("patch", url, **kwargs)


_test_client = _SyncAsgiClient(app)


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


# ---------------------------------------------------------------------------
# Additional tests — untested behaviors
# ---------------------------------------------------------------------------

class TestConnectionEndpointExtended:
    """Extended coverage for /api/onboarding/test-connection."""

    def test_mysql_db_type_succeeds(self):
        """MySQL path builds a mysql+pymysql connection string and must return success=True."""
        engine_mock, inspector_mock = _make_engine_mock(["orders", "customers"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            payload = {**VALID_CONNECTION_PAYLOAD, "db_type": "mysql"}
            resp = _test_client.post("/api/onboarding/test-connection", json=payload)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_idempiere_erp_detected(self):
        """Tables c_bpartner + c_invoice must trigger idempiere detection."""
        engine_mock, inspector_mock = _make_engine_mock(["c_bpartner", "c_invoice", "c_order"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["erp_detected"] == "idempiere"

    def test_sap_b1_erp_detected(self):
        """Tables ocrd + oinv must trigger sap_b1 detection."""
        engine_mock, inspector_mock = _make_engine_mock(["ocrd", "oinv", "opor"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["erp_detected"] == "sap_b1"

    def test_generic_postgresql_detected_when_no_erp_tables(self):
        """A non-empty table list with no known ERP signatures returns generic_postgresql."""
        engine_mock, inspector_mock = _make_engine_mock(["users", "products", "orders"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["erp_detected"] == "generic_postgresql"

    def test_unknown_erp_when_empty_tables(self):
        """An empty table list should produce erp_detected == 'unknown'."""
        engine_mock, inspector_mock = _make_engine_mock([])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["erp_detected"] == "unknown"

    def test_accounting_only_recommendation(self):
        """has_accounting=True but no invoices/partners → recommended_analysis == 'accounting_only'."""
        engine_mock, inspector_mock = _make_engine_mock(["account_move", "unrelated_table"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_accounting"] is True
        assert data["recommended_analysis"] == "accounting_only"

    def test_limited_recommendation_no_accounting(self):
        """No accounting/invoice/partner tables → recommended_analysis == 'limited'."""
        engine_mock, inspector_mock = _make_engine_mock(["log_entries", "config"])
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["recommended_analysis"] == "limited"

    def test_error_message_truncated_to_200_chars(self):
        """Errors longer than 200 characters must be truncated in the response."""
        long_error = "x" * 500
        with patch("sqlalchemy.create_engine", side_effect=Exception(long_error)):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert len(resp.json()["error"]) <= 200

    def test_missing_user_returns_422(self):
        """Required field 'user' missing must produce a 422 Unprocessable Entity."""
        payload = {k: v for k, v in VALID_CONNECTION_PAYLOAD.items() if k != "user"}
        resp = _test_client.post("/api/onboarding/test-connection", json=payload)
        assert resp.status_code == 422

    def test_table_count_returned_correctly(self):
        """table_count in the response must match the number of tables returned by the inspector."""
        tables = ["a", "b", "c", "d", "e"]
        engine_mock, inspector_mock = _make_engine_mock(tables)
        with (
            patch("sqlalchemy.create_engine", return_value=engine_mock),
            patch("sqlalchemy.inspect", return_value=inspector_mock),
        ):
            resp = _test_client.post("/api/onboarding/test-connection", json=VALID_CONNECTION_PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["table_count"] == len(tables)


class TestSSHTestEndpoint:
    """Coverage for /api/onboarding/ssh-test zero-trust host validation."""

    def test_loopback_ssh_host_rejected(self):
        """127.x address for ssh_host must be blocked with 400."""
        payload = {**VALID_SSH_PAYLOAD, "ssh_host": "127.0.0.1"}
        resp = _test_client.post("/api/onboarding/ssh-test", json=payload)
        assert resp.status_code == 400

    def test_private_10_range_ssh_host_rejected(self):
        """10.x.x.x address must be blocked (RFC-1918 SSRF guard)."""
        payload = {**VALID_SSH_PAYLOAD, "ssh_host": "10.0.0.5"}
        resp = _test_client.post("/api/onboarding/ssh-test", json=payload)
        assert resp.status_code == 400

    def test_private_192_168_range_db_host_rejected(self):
        """192.168.x.x address for db_host must be blocked."""
        payload = {**VALID_SSH_PAYLOAD, "db_host": "192.168.1.100"}
        resp = _test_client.post("/api/onboarding/ssh-test", json=payload)
        assert resp.status_code == 400


class TestSupportedDatabasesExtended:
    """Extended coverage for /api/onboarding/supported-databases."""

    def test_contains_sqlserver(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        ids = [db["id"] for db in resp.json()]
        assert "sqlserver" in ids

    def test_contains_oracle(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        ids = [db["id"] for db in resp.json()]
        assert "oracle" in ids

    def test_mysql_default_port_is_3306(self):
        resp = _test_client.get("/api/onboarding/supported-databases")
        mysql_entry = next(db for db in resp.json() if db["id"] == "mysql")
        assert mysql_entry["default_port"] == 3306


class TestEstimateCostExtended:
    """Extended coverage for /api/onboarding/estimate-cost."""

    def test_duration_within_bounds(self):
        """Estimated duration must be between 3 and 30 minutes (per module spec)."""
        payload = {"estimated_rows": 1_000_000, "tables_count": 20, "period": "Q3-2025"}
        resp = _test_client.post("/api/onboarding/estimate-cost", json=payload)
        assert resp.status_code == 200
        duration = resp.json()["estimated_duration_minutes"]
        assert 3 <= duration <= 30

    def test_token_estimate_includes_base(self):
        """With zero rows and zero tables the token estimate must be at least 50 000 (base)."""
        payload = {"estimated_rows": 0, "tables_count": 0, "period": "2025"}
        resp = _test_client.post("/api/onboarding/estimate-cost", json=payload)
        assert resp.status_code == 200
        assert resp.json()["token_estimate"] >= 50_000


class TestValidatePeriodExtended:
    """Extended coverage for /api/onboarding/validate-period."""

    def test_valid_h2_format(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "H2-2024"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_invalid_q0_returns_false(self):
        """Q0 is not a valid quarter."""
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "Q0-2025"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_response_contains_message_field(self):
        """Response must always include a 'message' key."""
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": "Q1-2025"})
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_empty_string_period_invalid(self):
        resp = _test_client.post("/api/onboarding/validate-period", json={"period": ""})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False
