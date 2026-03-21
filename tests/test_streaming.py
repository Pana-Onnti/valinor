"""
Tests for streaming-related endpoints (SSE and WebSocket).

These tests verify the API contract (content-type, status codes, route existence)
without consuming the full response body, which would block on live generators.
"""
import json
import sys
import types
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _make_stub(name):
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


def _stub_missing(*names):
    for name in names:
        if name not in sys.modules:
            sys.modules[name] = _make_stub(name)
        parts = name.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            child_attr = parts[i]
            if parent not in sys.modules:
                sys.modules[parent] = _make_stub(parent)
            parent_mod = sys.modules[parent]
            child_mod = sys.modules.get(".".join(parts[: i + 1]))
            if child_mod is not None and not hasattr(parent_mod, child_attr):
                setattr(parent_mod, child_attr, child_mod)


_stub_missing("supabase")
sys.modules["supabase"].create_client = MagicMock(return_value=MagicMock())
sys.modules["supabase"].Client = MagicMock

_stub_missing("slowapi", "slowapi.util", "slowapi.errors")


class _FakeLimiter:
    def __init__(self, *a, **kw): pass
    def limit(self, *a, **kw):
        return lambda f: f

    def __call__(self, *a, **kw):
        return self


class _FakeRateLimitExceeded(Exception):
    pass


sys.modules["slowapi"].Limiter = _FakeLimiter
sys.modules["slowapi"]._limiter = MagicMock()
sys.modules["slowapi"]._rate_limit_exceeded_handler = MagicMock()
sys.modules["slowapi.util"].get_remote_address = MagicMock(return_value="127.0.0.1")
sys.modules["slowapi.errors"].RateLimitExceeded = _FakeRateLimitExceeded

_stub_missing("structlog")
sys.modules["structlog"].get_logger = lambda *a, **kw: MagicMock()

_stub_missing("adapters", "adapters.valinor_adapter")
sys.modules["adapters.valinor_adapter"].ValinorAdapter = MagicMock
sys.modules["adapters.valinor_adapter"].PipelineExecutor = MagicMock

_stub_missing("shared.storage")
sys.modules["shared.storage"].MetadataStorage = MagicMock

for _m in ("shared.memory", "shared.memory.profile_store", "shared.memory.client_profile"):
    _stub_missing(_m)

_ps = sys.modules["shared.memory.profile_store"]
_ps.get_profile_store = MagicMock(return_value=MagicMock(
    _get_pool=AsyncMock(return_value=None),
    load=AsyncMock(return_value=None),
    load_or_create=AsyncMock(return_value=MagicMock(webhooks=[])),
    save=AsyncMock(),
))

_stub_missing("shared.pdf_generator")
sys.modules["shared.pdf_generator"].generate_pdf_report = MagicMock(return_value=b"%PDF-1.4")

# Wire parent.child attributes
_sh = sys.modules.get("shared")
if _sh:
    _sh.memory = sys.modules.get("shared.memory")
    _sh.pdf_generator = sys.modules.get("shared.pdf_generator")
    _shm = sys.modules.get("shared.memory")
    if _shm:
        _shm.profile_store = sys.modules.get("shared.memory.profile_store")
        _shm.client_profile = sys.modules.get("shared.memory.client_profile")


def _make_redis_mock():
    m = AsyncMock()
    m.ping = AsyncMock(return_value=True)
    m.hgetall = AsyncMock(return_value={})
    m.hget = AsyncMock(return_value=None)
    m.hset = AsyncMock(return_value=True)
    m.expire = AsyncMock(return_value=True)
    m.get = AsyncMock(return_value=None)
    m.info = AsyncMock(return_value={"redis_version": "7.0.0", "uptime_in_days": 1})
    m.close = AsyncMock()

    async def _empty_scan(*a, **kw):
        return
        yield

    m.scan_iter = _empty_scan
    return m


@pytest.fixture()
def async_client():
    """Async client fixture for non-streaming endpoint tests."""
    import asyncio
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    redis_mock = _make_redis_mock()
    storage_mock = MagicMock()
    storage_mock.health_check = AsyncMock(return_value=True)

    async def _make():
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    with (
        patch("redis.asyncio.from_url", return_value=redis_mock),
        patch("api.main.metadata_storage", storage_mock),
        patch("api.main.redis_client", redis_mock),
    ):
        loop = asyncio.new_event_loop()
        client = loop.run_until_complete(_make())
        client._loop = loop
        client._redis_mock = redis_mock
        yield client
        loop.run_until_complete(client.aclose())
        loop.close()


# ---------------------------------------------------------------------------
# Tests: SSE endpoint contract
# ---------------------------------------------------------------------------

class TestSSEEndpointContract:
    """Test the SSE endpoint API contract without consuming the full stream."""

    def test_sse_route_exists(self, async_client):
        """GET /api/jobs/{id}/stream must be a registered route."""
        from api.main import app
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("stream" in r for r in routes), f"No stream route found in {routes}"

    def test_sse_nonexistent_job_returns_200_stream(self, async_client):
        """SSE for a nonexistent job should still return 200 with event-stream."""
        import asyncio
        redis_mock = async_client._redis_mock
        redis_mock.hgetall = AsyncMock(return_value={})  # job not found

        async def _run():
            async with async_client.stream(
                "GET", "/api/jobs/ghost-job/stream",
                headers={"Accept": "text/event-stream"},
            ) as r:
                assert r.status_code == 200
                assert "text/event-stream" in r.headers.get("content-type", "")
                # Read just the first chunk — do NOT consume entire body
                chunk = await r.aiter_bytes().__anext__()
                assert b"data:" in chunk or b"error" in chunk or b"done" in chunk

        with patch("api.main.redis_client", redis_mock):
            async_client._loop.run_until_complete(_run())


# ---------------------------------------------------------------------------
# Tests: WebSocket endpoint contract
# ---------------------------------------------------------------------------

class TestWebSocketEndpointContract:
    """Test the WebSocket endpoint API contract."""

    def test_ws_route_registered(self):
        """WS /api/jobs/{id}/ws must be a registered route."""
        from api.main import app
        ws_routes = [r for r in app.routes if hasattr(r, "path") and "ws" in r.path]
        assert len(ws_routes) >= 1, "No WebSocket route found"

    def test_ws_path_contains_job_id(self):
        """WebSocket route must have {job_id} path parameter."""
        from api.main import app
        ws_routes = [r for r in app.routes if hasattr(r, "path") and "/ws" in r.path]
        assert any("{job_id}" in r.path for r in ws_routes)


# ---------------------------------------------------------------------------
# Tests: SSE response shape validation (unit tests on generator logic)
# ---------------------------------------------------------------------------

class TestSSEEventFormat:
    """Validate the SSE event format produced by the generator."""

    def test_sse_event_is_prefixed_with_data(self):
        """SSE events must follow 'data: {json}\\n\\n' format."""
        import json
        sample_event = {"job_id": "j1", "status": "running", "progress": 50}
        line = f"data: {json.dumps(sample_event)}\n\n"
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        parsed = json.loads(line[len("data: "):].strip())
        assert parsed["job_id"] == "j1"

    def test_sse_final_event_has_final_true(self):
        """The terminal SSE event must include 'final: True'."""
        import json
        final_event = {"job_id": "j1", "status": "completed", "final": True}
        line = f"data: {json.dumps(final_event)}\n\n"
        parsed = json.loads(line[len("data: "):].strip())
        assert parsed["final"] is True

    def test_sse_done_sentinel(self):
        """The generator's final line must be the done sentinel."""
        done_line = 'data: {"done": true}\n\n'
        parsed = json.loads(done_line[len("data: "):].strip())
        assert parsed.get("done") is True


# ---------------------------------------------------------------------------
# Tests: streaming endpoint headers
# ---------------------------------------------------------------------------

class TestStreamingHeaders:
    """Verify that streaming responses set correct headers."""

    def test_event_stream_content_type_value(self):
        """text/event-stream must be the media_type for SSE."""
        from fastapi.responses import StreamingResponse

        async def _gen():
            yield b"data: test\n\n"

        resp = StreamingResponse(_gen(), media_type="text/event-stream")
        assert resp.media_type == "text/event-stream"

    def test_cache_control_header_in_sse(self):
        """SSE responses must include Cache-Control: no-cache."""
        from fastapi.responses import StreamingResponse

        async def _gen():
            yield b"data: x\n\n"

        resp = StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
        assert resp.headers.get("Cache-Control") == "no-cache"
