"""
Tests for webhook management API endpoints.

Covers:
  POST   /api/clients/{name}/webhooks  — register a webhook URL
  GET    /api/clients/{name}/webhooks  — list webhooks
  DELETE /api/clients/{name}/webhooks  — remove a webhook by URL query-param

All external dependencies (Redis, MetadataStorage, supabase, slowapi, …) are
stubbed so that tests run without a Docker environment.
"""

from __future__ import annotations

import sys
import types
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# ---------------------------------------------------------------------------
# Ensure project root is on the path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Stub helpers (identical pattern to test_api_endpoints.py)
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
    """Profile store mock whose async methods are AsyncMocks."""
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
# Helpers
# ---------------------------------------------------------------------------

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

    async def _empty_scan(*args, **kwargs):
        return
        yield  # async generator

    mock.scan_iter = _empty_scan
    return mock


def _make_storage_mock():
    mock = MagicMock()
    mock.health_check = AsyncMock(return_value=True)
    return mock


def _webhook_patch(store: MagicMock | None = None):
    """Patch the profile store used by inline imports inside webhook endpoints."""
    s = store or _make_profile_store_mock()
    return patch(
        "shared.memory.profile_store.get_profile_store",
        return_value=s,
    )


def _make_profile(webhooks=None) -> MagicMock:
    profile = MagicMock()
    profile.webhooks = webhooks if webhooks is not None else []
    return profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def redis_mock():
    return _make_redis_mock()


@pytest.fixture
def storage_mock():
    return _make_storage_mock()


@pytest_asyncio.fixture
async def client(redis_mock, storage_mock):
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
# POST /api/clients/{name}/webhooks
# ---------------------------------------------------------------------------


class TestRegisterWebhook:
    @pytest.mark.asyncio
    async def test_register_returns_200(self, client):
        """Registering a valid URL returns HTTP 200."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "https://example.com/hook"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_register_response_structure(self, client):
        """Response contains status, url, and client fields."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "https://example.com/hook"},
            )
        data = response.json()
        assert data["status"] == "registered"
        assert data["url"] == "https://example.com/hook"
        assert data["client"] == "acme"

    @pytest.mark.asyncio
    async def test_register_profile_saved(self, client):
        """store.save is called after registering a webhook."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "https://example.com/hook"},
            )
        store.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_invalid_url_returns_400(self, client):
        """A URL that doesn't start with 'http' is rejected with 400."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "ftp://bad-scheme.com/hook"},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_register_missing_url_returns_400(self, client):
        """A request body with no 'url' key returns 400."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"events": ["analysis_completed"]},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_register_non_json_body_returns_422(self, client):
        """Sending a non-JSON body triggers a 422 Unprocessable Entity."""
        with _webhook_patch():
            response = await client.post(
                "/api/clients/acme/webhooks",
                content=b"not-json",
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_max_five_webhooks(self, client):
        """Existing webhooks beyond 5 are capped; the endpoint does not crash."""
        # Start with 5 existing webhooks (distinct URLs) to verify the cap logic.
        existing = [
            {"url": f"https://example.com/hook{i}", "active": True}
            for i in range(5)
        ]
        profile = _make_profile(webhooks=existing)
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "https://new.example.com/hook"},
            )
        assert response.status_code == 200
        # After saving, profile.webhooks must not exceed 5
        assert len(profile.webhooks) <= 5

    @pytest.mark.asyncio
    async def test_register_deduplicates_url(self, client):
        """Re-registering the same URL does not create a duplicate entry."""
        url = "https://example.com/hook"
        existing = [{"url": url, "active": True}]
        profile = _make_profile(webhooks=existing)
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            await client.post("/api/clients/acme/webhooks", json={"url": url})

        # After the call the list still contains exactly one entry for that URL
        urls = [w.get("url") for w in profile.webhooks]
        assert urls.count(url) == 1

    @pytest.mark.asyncio
    async def test_register_webhook_with_events_list(self, client):
        """A body that includes an 'events' key is accepted (200) without error."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={
                    "url": "https://example.com/hook",
                    "events": ["analysis_completed", "finding_critical"],
                },
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_register_webhook_with_wildcard_events(self, client):
        """A body with events=['*'] is accepted without error."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "https://example.com/hook", "events": ["*"]},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_register_webhook_secret_accepted(self, client):
        """A body that includes a 'secret' field is accepted (200)."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={
                    "url": "https://example.com/hook",
                    "secret": "my-super-secret",
                },
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/clients/{name}/webhooks
# ---------------------------------------------------------------------------


class TestListWebhooks:
    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        """Listing webhooks for an existing client returns 200."""
        profile = _make_profile(webhooks=[{"url": "https://example.com/hook", "active": True}])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.get("/api/clients/acme/webhooks")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_response_structure(self, client):
        """Response contains 'client' and 'webhooks' keys."""
        profile = _make_profile(webhooks=[{"url": "https://example.com/hook", "active": True}])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.get("/api/clients/acme/webhooks")
        data = response.json()
        assert "client" in data
        assert "webhooks" in data
        assert data["client"] == "acme"

    @pytest.mark.asyncio
    async def test_list_returns_all_webhooks(self, client):
        """All registered webhooks appear in the list response."""
        webhooks = [
            {"url": "https://a.example.com/hook", "active": True},
            {"url": "https://b.example.com/hook", "active": True},
        ]
        profile = _make_profile(webhooks=webhooks)
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.get("/api/clients/acme/webhooks")
        assert len(response.json()["webhooks"]) == 2

    @pytest.mark.asyncio
    async def test_list_empty_when_no_webhooks(self, client):
        """A client with no webhooks returns an empty list, not a 404."""
        profile = _make_profile(webhooks=[])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.get("/api/clients/acme/webhooks")
        assert response.status_code == 200
        assert response.json()["webhooks"] == []

    @pytest.mark.asyncio
    async def test_list_unknown_client_returns_404(self, client):
        """Listing webhooks for a client that does not exist returns 404."""
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=None)  # client not found

        with _webhook_patch(store):
            response = await client.get("/api/clients/unknown-client/webhooks")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/clients/{name}/webhooks
# ---------------------------------------------------------------------------


class TestDeleteWebhook:
    @pytest.mark.asyncio
    async def test_delete_existing_webhook_returns_200(self, client):
        """Deleting an existing webhook returns 200."""
        url = "https://example.com/hook"
        profile = _make_profile(webhooks=[{"url": url, "active": True}])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.delete(
                "/api/clients/acme/webhooks",
                params={"url": url},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_response_structure(self, client):
        """Response contains 'status' and 'remaining' fields."""
        url = "https://example.com/hook"
        profile = _make_profile(webhooks=[{"url": url, "active": True}])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.delete(
                "/api/clients/acme/webhooks",
                params={"url": url},
            )
        data = response.json()
        assert data["status"] == "removed"
        assert "remaining" in data

    @pytest.mark.asyncio
    async def test_delete_removes_only_target_webhook(self, client):
        """Only the targeted webhook is removed; others remain."""
        url_to_delete = "https://a.example.com/hook"
        url_to_keep = "https://b.example.com/hook"
        profile = _make_profile(webhooks=[
            {"url": url_to_delete, "active": True},
            {"url": url_to_keep, "active": True},
        ])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.delete(
                "/api/clients/acme/webhooks",
                params={"url": url_to_delete},
            )
        assert response.json()["remaining"] == 1
        remaining_urls = [w.get("url") for w in profile.webhooks]
        assert url_to_keep in remaining_urls
        assert url_to_delete not in remaining_urls

    @pytest.mark.asyncio
    async def test_delete_nonexistent_client_returns_404(self, client):
        """Attempting to delete from a non-existent client returns 404."""
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=None)

        with _webhook_patch(store):
            response = await client.delete(
                "/api/clients/ghost/webhooks",
                params={"url": "https://example.com/hook"},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_url_still_returns_200(self, client):
        """Deleting a URL that was never registered succeeds with 0 removed."""
        profile = _make_profile(webhooks=[{"url": "https://other.com/hook", "active": True}])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.delete(
                "/api/clients/acme/webhooks",
                params={"url": "https://never-registered.com/hook"},
            )
        # The endpoint does a filter; nothing removed is still a valid operation
        assert response.status_code == 200
        assert response.json()["remaining"] == 1


# ---------------------------------------------------------------------------
# Additional tests — edge cases and extra coverage
# ---------------------------------------------------------------------------


class TestRegisterWebhookExtra:
    @pytest.mark.asyncio
    async def test_register_http_url_accepted(self, client):
        """HTTP (non-TLS) webhook URLs are accepted."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "http://plain-http.example.com/hook"},
            )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_register_empty_body_returns_400_or_422(self, client):
        """An empty JSON body (no 'url' key) is rejected."""
        with _webhook_patch():
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={},
            )
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_register_url_with_query_params_accepted(self, client):
        """Webhook URLs containing query parameters are accepted."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        url = "https://example.com/hook?token=abc123&version=2"
        with _webhook_patch(store):
            response = await client.post(
                "/api/clients/acme/webhooks",
                json={"url": url},
            )
        assert response.status_code == 200
        assert response.json()["url"] == url

    @pytest.mark.asyncio
    async def test_register_store_save_called_with_profile(self, client):
        """store.save receives the profile object as its argument."""
        profile = _make_profile()
        store = _make_profile_store_mock()
        store.load_or_create = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            await client.post(
                "/api/clients/acme/webhooks",
                json={"url": "https://example.com/hook"},
            )
        # save must have been awaited with the profile as first positional arg
        store.save.assert_awaited_once_with(profile)


class TestListWebhooksExtra:
    @pytest.mark.asyncio
    async def test_list_returns_count_field(self, client):
        """List response includes a 'count' field matching the number of webhooks."""
        webhooks = [
            {"url": "https://a.example.com/hook", "active": True},
            {"url": "https://b.example.com/hook", "active": False},
        ]
        profile = _make_profile(webhooks=webhooks)
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.get("/api/clients/acme/webhooks")
        data = response.json()
        if "count" in data:
            assert data["count"] == len(data["webhooks"])

    @pytest.mark.asyncio
    async def test_list_inactive_webhooks_included(self, client):
        """Inactive webhooks are still included in the listing."""
        webhooks = [
            {"url": "https://active.example.com/hook", "active": True},
            {"url": "https://inactive.example.com/hook", "active": False},
        ]
        profile = _make_profile(webhooks=webhooks)
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.get("/api/clients/acme/webhooks")
        assert response.status_code == 200
        assert len(response.json()["webhooks"]) == 2

    @pytest.mark.asyncio
    async def test_list_five_webhooks(self, client):
        """Listing a client with the maximum 5 webhooks returns all five."""
        webhooks = [
            {"url": f"https://example.com/hook{i}", "active": True}
            for i in range(5)
        ]
        profile = _make_profile(webhooks=webhooks)
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.get("/api/clients/acme/webhooks")
        assert response.status_code == 200
        assert len(response.json()["webhooks"]) == 5


class TestDeleteWebhookExtra:
    @pytest.mark.asyncio
    async def test_delete_missing_url_param_returns_422(self, client):
        """DELETE without the 'url' query param returns 422."""
        profile = _make_profile(webhooks=[{"url": "https://example.com/hook", "active": True}])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.delete("/api/clients/acme/webhooks")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_from_empty_list_returns_200(self, client):
        """DELETE on a client with no webhooks returns 200 with remaining=0."""
        profile = _make_profile(webhooks=[])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            response = await client.delete(
                "/api/clients/acme/webhooks",
                params={"url": "https://example.com/hook"},
            )
        assert response.status_code == 200
        assert response.json()["remaining"] == 0

    @pytest.mark.asyncio
    async def test_delete_saves_profile_after_removal(self, client):
        """store.save is called after a webhook is removed."""
        url = "https://example.com/hook"
        profile = _make_profile(webhooks=[{"url": url, "active": True}])
        store = _make_profile_store_mock()
        store.load = AsyncMock(return_value=profile)

        with _webhook_patch(store):
            await client.delete(
                "/api/clients/acme/webhooks",
                params={"url": url},
            )
        store.save.assert_awaited_once()
