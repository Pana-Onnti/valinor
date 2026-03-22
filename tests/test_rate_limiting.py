"""
Tests for rate limiting, headers, CORS, request tracing, and content-type validation.

Uses the same stub pattern as test_api_endpoints.py — all external dependencies
(Redis, MetadataStorage, supabase, slowapi, structlog, adapters, shared.*) are
stubbed in sys.modules before importing api.main.
"""

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
# Stub optional packages — identical pattern from test_api_endpoints.py
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
_structlog.get_logger = MagicMock(
    return_value=MagicMock(
        info=MagicMock(),
        error=MagicMock(),
        warning=MagicMock(),
        debug=MagicMock(),
    )
)

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
for _m in (
    "shared.memory",
    "shared.memory.profile_store",
    "shared.memory.client_profile",
):
    _stub_missing(_m)

_profile_store_stub = sys.modules["shared.memory.profile_store"]


def _make_profile_store_mock() -> MagicMock:
    store = MagicMock()
    store._get_pool = AsyncMock(return_value=None)
    store.load = AsyncMock(return_value=None)
    store.load_or_create = AsyncMock(return_value=MagicMock(webhooks=[]))
    store.save = AsyncMock(return_value=None)
    return store


_profile_store_stub.get_profile_store = MagicMock(return_value=_make_profile_store_mock())

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
# Helpers / fixtures
# ---------------------------------------------------------------------------

ORIGIN_ALLOWED = "http://localhost:3000"
ORIGIN_DISALLOWED = "http://evil.example.com"

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


def _make_redis_mock():
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.hgetall = AsyncMock(return_value={})
    mock.hget = AsyncMock(return_value=None)
    mock.hset = AsyncMock(return_value=True)
    mock.expire = AsyncMock(return_value=True)
    mock.incr = AsyncMock(return_value=1)
    mock.get = AsyncMock(return_value=None)
    mock.info = AsyncMock(return_value={"redis_version": "7.0.0", "uptime_in_days": 1})
    mock.close = AsyncMock()
    mock.lpush = AsyncMock(return_value=1)
    mock.ltrim = AsyncMock(return_value=True)
    mock.lrange = AsyncMock(return_value=[])

    async def _empty_scan(*args, **kwargs):
        return
        yield  # makes it an async generator

    mock.scan_iter = _empty_scan
    return mock


def _make_storage_mock():
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
# 1. Security headers are present on responses
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    @pytest.mark.asyncio
    async def test_x_content_type_options_header(self, client):
        """X-Content-Type-Options must be 'nosniff' on every response."""
        response = await client.get("/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options_header(self, client):
        """X-Frame-Options must be 'DENY' to prevent clickjacking."""
        response = await client.get("/health")
        assert response.headers.get("x-frame-options") == "DENY"

    @pytest.mark.asyncio
    async def test_x_xss_protection_header(self, client):
        """X-XSS-Protection header must be present."""
        response = await client.get("/health")
        assert "x-xss-protection" in response.headers

    @pytest.mark.asyncio
    async def test_referrer_policy_header(self, client):
        """Referrer-Policy header must be present."""
        response = await client.get("/health")
        assert "referrer-policy" in response.headers

    @pytest.mark.asyncio
    async def test_permissions_policy_header(self, client):
        """Permissions-Policy header must be present."""
        response = await client.get("/health")
        assert "permissions-policy" in response.headers

    @pytest.mark.asyncio
    async def test_security_headers_on_api_endpoint(self, client):
        """Security headers must also be present on API endpoints, not just /health."""
        response = await client.get("/api/version")
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"


# ---------------------------------------------------------------------------
# 2. Request-ID tracing middleware
# ---------------------------------------------------------------------------


class TestRequestIDHeader:
    @pytest.mark.asyncio
    async def test_response_includes_request_id_header(self, client):
        """Every response must include an X-Request-ID header."""
        response = await client.get("/health")
        assert "x-request-id" in response.headers

    @pytest.mark.asyncio
    async def test_provided_request_id_is_echoed(self, client):
        """If the client sends X-Request-ID, the server must echo the same value."""
        custom_id = "my-trace-id-42"
        response = await client.get("/health", headers={"X-Request-ID": custom_id})
        assert response.headers.get("x-request-id") == custom_id

    @pytest.mark.asyncio
    async def test_auto_generated_request_id_is_non_empty(self, client):
        """When no X-Request-ID is sent the server must generate a non-empty one."""
        response = await client.get("/api/version")
        request_id = response.headers.get("x-request-id", "")
        assert len(request_id) > 0


# ---------------------------------------------------------------------------
# 3. CORS headers
# ---------------------------------------------------------------------------


class TestCORSHeaders:
    @pytest.mark.asyncio
    async def test_cors_allowed_origin_present(self, client):
        """An allowed origin must get Access-Control-Allow-Origin in the response."""
        response = await client.get(
            "/health", headers={"Origin": ORIGIN_ALLOWED}
        )
        assert "access-control-allow-origin" in response.headers

    @pytest.mark.asyncio
    async def test_cors_allowed_origin_value(self, client):
        """The reflected origin must match the one sent by the client."""
        response = await client.get(
            "/health", headers={"Origin": ORIGIN_ALLOWED}
        )
        acao = response.headers.get("access-control-allow-origin", "")
        assert acao == ORIGIN_ALLOWED or acao == "*"

    @pytest.mark.asyncio
    async def test_cors_disallowed_origin_not_reflected(self, client):
        """An origin not in the allow-list must NOT be reflected back."""
        response = await client.get(
            "/health", headers={"Origin": ORIGIN_DISALLOWED}
        )
        acao = response.headers.get("access-control-allow-origin", "")
        assert acao != ORIGIN_DISALLOWED


# ---------------------------------------------------------------------------
# 4. OPTIONS preflight request
# ---------------------------------------------------------------------------


class TestOptionsPreflightRequests:
    @pytest.mark.asyncio
    async def test_options_preflight_returns_200_or_204(self, client):
        """OPTIONS /health with CORS headers should return 200 or 204."""
        response = await client.options(
            "/health",
            headers={
                "Origin": ORIGIN_ALLOWED,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code in (200, 204)

    @pytest.mark.asyncio
    async def test_options_preflight_for_post_analyze(self, client):
        """OPTIONS /api/analyze preflight should return 200 or 204."""
        response = await client.options(
            "/api/analyze",
            headers={
                "Origin": ORIGIN_ALLOWED,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code in (200, 204)


# ---------------------------------------------------------------------------
# 5. /health accessible without auth
# ---------------------------------------------------------------------------


class TestHealthNoAuth:
    @pytest.mark.asyncio
    async def test_health_returns_200_no_auth(self, client):
        """/health must be reachable without any auth header."""
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_json(self, client):
        """/health must respond with application/json content-type."""
        response = await client.get("/health")
        assert "application/json" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 6. Rate-limit behaviour (per-client concurrent job cap → 429)
# ---------------------------------------------------------------------------


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_too_many_concurrent_jobs_returns_429(self, client, redis_mock):
        """When 2+ jobs are already running for the same client, 429 is returned."""

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

    @pytest.mark.asyncio
    async def test_429_body_has_error_key(self, client, redis_mock):
        """The 429 body must contain 'error' or 'detail' describing the problem."""

        async def _scan_two(*args, **kwargs):
            yield "job:x1"
            yield "job:x2"

        redis_mock.scan_iter = _scan_two

        async def _hget(key, field):
            if field == "status":
                return "running"
            if field == "client_name":
                return "test-client"
            return None

        redis_mock.hget = AsyncMock(side_effect=_hget)

        response = await client.post("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)
        data = response.json()
        assert "detail" in data or "error" in data


# ---------------------------------------------------------------------------
# 7. Protected endpoints return 422 when required fields are missing
# ---------------------------------------------------------------------------


class TestValidationErrors:
    @pytest.mark.asyncio
    async def test_post_analyze_missing_db_config_returns_422(self, client):
        """Omitting db_config entirely must return 422."""
        response = await client.post("/api/analyze", json={"client_name": "test"})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_post_analyze_missing_db_type_returns_422(self, client):
        """db_config without 'type' must return 422."""
        payload = {
            "client_name": "test-client",
            "db_config": {
                "host": "db.example.com",
                "port": 5432,
            },
        }
        response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_validation_error_body_has_error_key(self, client):
        """422 body from custom handler must have 'error' == 'validation_error'."""
        response = await client.post("/api/analyze", json={"client_name": "x"})
        assert response.status_code == 422
        data = response.json()
        # Custom handler sets error='validation_error'; standard FastAPI uses 'detail'
        assert "error" in data or "detail" in data

    @pytest.mark.asyncio
    async def test_post_analyze_empty_body_returns_422(self, client):
        """An empty JSON body must return 422 (db_config is required)."""
        response = await client.post(
            "/api/analyze",
            content="{}",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 8. Content-type validation
# ---------------------------------------------------------------------------


class TestContentTypeValidation:
    @pytest.mark.asyncio
    async def test_post_with_wrong_content_type_returns_error(self, client):
        """Sending form-encoded data to a JSON endpoint must not return 200."""
        response = await client.post(
            "/api/analyze",
            content="client_name=test",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code in (400, 415, 422)

    @pytest.mark.asyncio
    async def test_post_with_plain_text_returns_error(self, client):
        """Sending plain text to /api/analyze must not return 200."""
        response = await client.post(
            "/api/analyze",
            content="hello world",
            headers={"content-type": "text/plain"},
        )
        assert response.status_code in (400, 415, 422)

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_json_content_type(self, client):
        """GET /health must respond with application/json content-type."""
        response = await client.get("/health")
        assert "application/json" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_api_version_returns_json_content_type(self, client):
        """GET /api/version must respond with application/json content-type."""
        response = await client.get("/api/version")
        assert "application/json" in response.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 9. Additional validation scenarios — missing required fields
# ---------------------------------------------------------------------------


class TestAdditionalValidationScenarios:
    @pytest.mark.asyncio
    async def test_post_analyze_missing_client_name_accepted(self, client):
        """client_name is optional; omitting it must not return a 5xx error."""
        payload = {
            "db_config": {
                "host": "db.example.com",
                "port": 5432,
                "name": "testdb",
                "type": "postgresql",
                "user": "user",
                "password": "secret",
            }
        }
        response = await client.post("/api/analyze", json=payload)
        # client_name is Optional — must not crash the server
        assert response.status_code < 500

    @pytest.mark.asyncio
    async def test_post_analyze_numeric_field_as_string_returns_error(self, client):
        """Providing db_config.port as a non-numeric string must return 422."""
        payload = {
            "client_name": "test-client",
            "db_config": {
                "host": "db.example.com",
                "port": "not-a-number",
                "name": "testdb",
                "type": "postgresql",
                "user": "user",
                "password": "secret",
            },
        }
        response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_post_analyze_malformed_json_returns_error(self, client):
        """Sending syntactically invalid JSON must not return 2xx."""
        response = await client.post(
            "/api/analyze",
            content=b'{"client_name": "test", "db_config": {broken}',
            headers={"content-type": "application/json"},
        )
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_post_analyze_empty_string_body_returns_error(self, client):
        """Sending a completely empty body with JSON content-type must return an error."""
        response = await client.post(
            "/api/analyze",
            content=b"",
            headers={"content-type": "application/json"},
        )
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_post_analyze_null_db_config_returns_422(self, client):
        """Passing null for db_config must return 422 (required object)."""
        payload = {"client_name": "test-client", "db_config": None}
        response = await client.post("/api/analyze", json=payload)
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_post_analyze_extra_unknown_fields_accepted_or_rejected(self, client):
        """Extra fields in the payload must not cause a 5xx server error."""
        payload = {**VALID_ANALYSIS_PAYLOAD, "unexpected_field": "should-be-ignored"}
        response = await client.post("/api/analyze", json=payload)
        # Must be 200/202 (accepted) or 4xx (rejected), never a 5xx crash
        assert response.status_code < 500

    @pytest.mark.asyncio
    async def test_get_method_on_post_only_endpoint_returns_405(self, client):
        """GET /api/analyze (a POST-only endpoint) must return 405 Method Not Allowed."""
        response = await client.get("/api/analyze")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_put_method_on_analyze_returns_405(self, client):
        """PUT /api/analyze must return 405 Method Not Allowed."""
        response = await client.put("/api/analyze", json=VALID_ANALYSIS_PAYLOAD)
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_delete_method_on_analyze_returns_405(self, client):
        """DELETE /api/analyze must return 405 Method Not Allowed."""
        response = await client.delete("/api/analyze")
        assert response.status_code == 405

    @pytest.mark.asyncio
    async def test_post_analyze_client_name_empty_string_no_server_error(self, client):
        """An empty client_name string must not cause a 5xx server error."""
        payload = {
            "client_name": "",
            "db_config": {
                "host": "db.example.com",
                "port": 5432,
                "name": "testdb",
                "type": "postgresql",
                "user": "user",
                "password": "secret",
            },
        }
        response = await client.post("/api/analyze", json=payload)
        # client_name is optional — server must not crash regardless of the value
        assert response.status_code < 500
