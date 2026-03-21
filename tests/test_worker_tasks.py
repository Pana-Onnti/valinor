"""
Tests for Celery worker tasks in Valinor SaaS.

All external dependencies (Redis, ValinorAdapter, webhooks, structlog, etc.)
are mocked so that tests run without a Docker / Redis environment.
"""

import json
import sys
import types
import asyncio
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Stub helper
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


# ---------------------------------------------------------------------------
# Stubs for optional packages
# ---------------------------------------------------------------------------

# structlog
_stub_missing("structlog")
_structlog = sys.modules["structlog"]
_structlog.get_logger = MagicMock(
    return_value=MagicMock(info=MagicMock(), error=MagicMock(), warning=MagicMock())
)

# supabase
_stub_missing("supabase")
sys.modules["supabase"].create_client = MagicMock(return_value=MagicMock())
sys.modules["supabase"].Client = MagicMock

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
sys.modules["slowapi.util"].get_remote_address = MagicMock(return_value="127.0.0.1")


class _FakeRateLimitExceeded(Exception):
    pass


sys.modules["slowapi.errors"].RateLimitExceeded = _FakeRateLimitExceeded

# shared.storage
_stub_missing("shared.storage")


class _FakeMetadataStorage:
    async def health_check(self):
        return True


sys.modules["shared.storage"].MetadataStorage = _FakeMetadataStorage

# shared.memory.*
for _m in ("shared.memory", "shared.memory.profile_store", "shared.memory.client_profile"):
    _stub_missing(_m)

_profile_store_stub = sys.modules["shared.memory.profile_store"]
_profile_store_stub.get_profile_store = MagicMock(return_value=MagicMock(load=AsyncMock(return_value=None)))

# api.webhooks
_stub_missing("api.webhooks")
_wh_stub = sys.modules["api.webhooks"]
_wh_stub.fire_job_completion_webhook = AsyncMock()
_wh_stub.build_job_summary = MagicMock(return_value={})

# api.adapters.valinor_adapter
_stub_missing("api.adapters", "api.adapters.valinor_adapter")
_adapter_mod = sys.modules["api.adapters.valinor_adapter"]

_FAKE_RESULTS = {
    "findings": {"revenue": 1, "anomalies": 2},
    "execution_time_seconds": 42.0,
    "status": "completed",
}


class _FakeValinorAdapter:
    def __init__(self, progress_callback=None):
        self.run_analysis = AsyncMock(return_value=_FAKE_RESULTS)


class _FakePipelineExecutor:
    def __init__(self, adapter):
        self.adapter = adapter
        self.run_with_retry = AsyncMock(return_value=_FAKE_RESULTS)
        self.run_with_fallback = AsyncMock(return_value=_FAKE_RESULTS)


_adapter_mod.ValinorAdapter = _FakeValinorAdapter
_adapter_mod.PipelineExecutor = _FakePipelineExecutor

# also stub api.adapters package itself
_stub_missing("api")
sys.modules["api.adapters"] = sys.modules["api.adapters"]
setattr(sys.modules["api"], "adapters", sys.modules["api.adapters"])

# ---------------------------------------------------------------------------
# Import modules under test AFTER stubs are in place
# ---------------------------------------------------------------------------
import worker.celery_app as celery_app_module  # noqa: E402
import worker.tasks as tasks_module  # noqa: E402

from worker.tasks import (  # noqa: E402
    run_analysis_task,
    cleanup_expired_jobs,
    get_redis_client,
)
from worker.celery_app import celery_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

JOB_ID = "test-job-123"
CLIENT_NAME = "acme-corp"
PERIOD = "Q1-2026"
CONNECTION_CONFIG = {
    "ssh_config": {"host": "ssh.example.com", "username": "user", "key_path": "/tmp/key"},
    "db_config": {"host": "db.example.com", "port": 5432, "dbname": "prod"},
}
ANALYSIS_CONFIG = {"sector": "retail", "country": "US", "currency": "USD"}


def _make_redis_mock():
    """Return a MagicMock that quacks like a Redis client."""
    rc = MagicMock()
    rc.hset = MagicMock()
    rc.set = MagicMock()
    rc.get = MagicMock(return_value=None)
    rc.hget = MagicMock(return_value=None)
    rc.hgetall = MagicMock(return_value={})
    rc.keys = MagicMock(return_value=[])
    rc.delete = MagicMock()
    rc.expire = MagicMock()
    rc.ping = MagicMock(return_value=True)
    return rc


def _run_task(task_fn, *args, **kwargs):
    """
    Invoke a Celery task function directly (bypassing the broker) in
    'always eager' mode by calling the underlying Python function.
    """
    return task_fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_redis_global():
    """Ensure the global redis_client is reset between tests."""
    original = tasks_module.redis_client
    tasks_module.redis_client = None
    yield
    tasks_module.redis_client = original


# ===========================================================================
# 1. run_analysis_task — happy path: status transitions
# ===========================================================================

class TestRunAnalysisTaskHappyPath:
    def _invoke(self, rc):
        with patch.object(tasks_module, "get_redis_client", return_value=rc), \
             patch.object(tasks_module, "_fire_webhooks_sync"), \
             patch.object(tasks_module, "cleanup_job") as mock_cleanup:
            mock_cleanup.apply_async = MagicMock()
            result = run_analysis_task.run(
                JOB_ID, CLIENT_NAME, CONNECTION_CONFIG, PERIOD, ANALYSIS_CONFIG
            )
        return result, rc

    def test_status_set_to_running_first(self):
        """First hset call must set status='running'."""
        rc = _make_redis_mock()
        self._invoke(rc)
        first_call = rc.hset.call_args_list[0]
        mapping = first_call[1].get("mapping") or first_call[0][1]
        assert mapping["status"] == "running"

    def test_status_set_to_completed_last(self):
        """Last hset call must set status='completed'."""
        rc = _make_redis_mock()
        self._invoke(rc)
        last_call = rc.hset.call_args_list[-1]
        mapping = last_call[1].get("mapping") or last_call[0][1]
        assert mapping["status"] == "completed"

    def test_results_stored_in_redis(self):
        """Results JSON is stored under job:<id>:results key."""
        rc = _make_redis_mock()
        self._invoke(rc)
        rc.set.assert_called_once()
        key_arg = rc.set.call_args[0][0]
        assert key_arg == f"job:{JOB_ID}:results"

    def test_results_json_is_valid(self):
        """The stored value must be valid JSON."""
        rc = _make_redis_mock()
        self._invoke(rc)
        raw = rc.set.call_args[0][1]
        parsed = json.loads(raw)
        assert "findings" in parsed

    def test_return_value_contains_job_id(self):
        rc = _make_redis_mock()
        result, _ = self._invoke(rc)
        assert result["job_id"] == JOB_ID

    def test_return_value_status_completed(self):
        rc = _make_redis_mock()
        result, _ = self._invoke(rc)
        assert result["status"] == "completed"

    def test_return_value_findings_count(self):
        rc = _make_redis_mock()
        result, _ = self._invoke(rc)
        # _FAKE_RESULTS["findings"] has 2 keys
        assert result["findings_count"] == 2

    def test_return_value_execution_time(self):
        rc = _make_redis_mock()
        result, _ = self._invoke(rc)
        assert result["execution_time"] == 42.0

    def test_results_ttl_is_set(self):
        """Redis set must include a TTL (ex=86400)."""
        rc = _make_redis_mock()
        self._invoke(rc)
        kwargs = rc.set.call_args[1]
        assert kwargs.get("ex") == 86400

    def test_webhooks_fired_on_success(self):
        rc = _make_redis_mock()
        with patch.object(tasks_module, "get_redis_client", return_value=rc), \
             patch.object(tasks_module, "_fire_webhooks_sync") as mock_wh, \
             patch.object(tasks_module, "cleanup_job") as mock_cleanup:
            mock_cleanup.apply_async = MagicMock()
            run_analysis_task.run(
                JOB_ID, CLIENT_NAME, CONNECTION_CONFIG, PERIOD, ANALYSIS_CONFIG
            )
        mock_wh.assert_called_once_with(JOB_ID, CLIENT_NAME, "completed", _FAKE_RESULTS)


# ===========================================================================
# 2. run_analysis_task — exception / failure handling
# ===========================================================================

class TestRunAnalysisTaskFailure:
    def test_status_set_to_failed_on_exception(self):
        """When _run_analysis_task_async raises, Redis must record status='failed'."""
        rc = _make_redis_mock()
        boom = RuntimeError("DB unreachable")

        with patch.object(tasks_module, "get_redis_client", return_value=rc), \
             patch.object(tasks_module, "_run_analysis_task_async", side_effect=boom), \
             patch.object(tasks_module, "_fire_webhooks_sync"), \
             pytest.raises(Exception):
            run_analysis_task.run(
                JOB_ID, CLIENT_NAME, CONNECTION_CONFIG, PERIOD, ANALYSIS_CONFIG
            )

        statuses = [
            (c[1].get("mapping") or c[0][1]).get("status")
            for c in rc.hset.call_args_list
        ]
        assert "failed" in statuses

    def test_error_message_stored_in_redis(self):
        rc = _make_redis_mock()
        boom = RuntimeError("DB unreachable")

        with patch.object(tasks_module, "get_redis_client", return_value=rc), \
             patch.object(tasks_module, "_run_analysis_task_async", side_effect=boom), \
             patch.object(tasks_module, "_fire_webhooks_sync"), \
             pytest.raises(Exception):
            run_analysis_task.run(
                JOB_ID, CLIENT_NAME, CONNECTION_CONFIG, PERIOD, ANALYSIS_CONFIG
            )

        # Find the failed hset call
        failed_mapping = None
        for c in rc.hset.call_args_list:
            m = c[1].get("mapping") or c[0][1]
            if m.get("status") == "failed":
                failed_mapping = m
                break
        assert failed_mapping is not None
        assert "DB unreachable" in failed_mapping["error"]

    def test_failure_webhook_fired(self):
        rc = _make_redis_mock()
        boom = RuntimeError("connection timeout")

        with patch.object(tasks_module, "get_redis_client", return_value=rc), \
             patch.object(tasks_module, "_run_analysis_task_async", side_effect=boom), \
             patch.object(tasks_module, "_fire_webhooks_sync") as mock_wh, \
             pytest.raises(Exception):
            run_analysis_task.run(
                JOB_ID, CLIENT_NAME, CONNECTION_CONFIG, PERIOD, ANALYSIS_CONFIG
            )

        mock_wh.assert_called_with(JOB_ID, CLIENT_NAME, "failed", {})

    def test_retry_called_on_transient_failure(self):
        """The task must call self.retry(exc=...) on failure."""
        rc = _make_redis_mock()
        boom = ConnectionError("transient")

        # Simulate self.retry raising Retry exception (standard Celery behaviour)
        retry_exc = Exception("Retry")

        with patch.object(tasks_module, "get_redis_client", return_value=rc), \
             patch.object(tasks_module, "_run_analysis_task_async", side_effect=boom), \
             patch.object(tasks_module, "_fire_webhooks_sync"):
            # Patch the task's retry method
            with patch.object(run_analysis_task, "retry", side_effect=retry_exc) as mock_retry:
                with pytest.raises(Exception):
                    run_analysis_task.run(
                        JOB_ID, CLIENT_NAME, CONNECTION_CONFIG, PERIOD, ANALYSIS_CONFIG
                    )
            mock_retry.assert_called_once()
            _, retry_kwargs = mock_retry.call_args
            assert retry_kwargs["exc"] is boom


# ===========================================================================
# 3. cleanup_expired_jobs
# ===========================================================================

class TestCleanupExpiredJobs:
    def _old_ts(self, days: int = 8) -> str:
        return (datetime.utcnow() - timedelta(days=days)).isoformat()

    def _recent_ts(self, days: int = 1) -> str:
        return (datetime.utcnow() - timedelta(days=days)).isoformat()

    def test_deletes_jobs_older_than_7_days(self):
        rc = _make_redis_mock()
        old_key = "job:old-job-1"
        rc.keys.return_value = [old_key]
        rc.hget.return_value = self._old_ts(8)

        with patch.object(tasks_module, "get_redis_client", return_value=rc):
            result = cleanup_expired_jobs.run()

        rc.delete.assert_any_call(old_key)
        assert result["deleted_jobs"] == 1

    def test_keeps_recent_jobs(self):
        rc = _make_redis_mock()
        recent_key = "job:recent-job-1"
        rc.keys.return_value = [recent_key]
        rc.hget.return_value = self._recent_ts(1)

        with patch.object(tasks_module, "get_redis_client", return_value=rc):
            result = cleanup_expired_jobs.run()

        # delete should not have been called for this key
        for c in rc.delete.call_args_list:
            assert recent_key not in c[0]
        assert result["deleted_jobs"] == 0

    def test_returns_count_of_deleted_jobs(self):
        rc = _make_redis_mock()
        keys = [f"job:old-{i}" for i in range(3)]
        rc.keys.return_value = keys
        rc.hget.return_value = self._old_ts(10)

        with patch.object(tasks_module, "get_redis_client", return_value=rc):
            result = cleanup_expired_jobs.run()

        assert result["deleted_jobs"] == 3

    def test_also_deletes_results_key(self):
        """For each expired job, the :results sub-key must also be deleted."""
        rc = _make_redis_mock()
        job_key = "job:old-job-x"
        rc.keys.return_value = [job_key]
        rc.hget.side_effect = [self._old_ts(9), None]  # created_at, then job_id lookup

        with patch.object(tasks_module, "get_redis_client", return_value=rc):
            cleanup_expired_jobs.run()

        deleted_keys = [c[0][0] for c in rc.delete.call_args_list]
        results_key_deleted = any(":results" in k for k in deleted_keys)
        assert results_key_deleted

    def test_excludes_results_sub_keys_from_scan(self):
        """Keys ending in :results must be skipped by the scanner."""
        rc = _make_redis_mock()
        rc.keys.return_value = ["job:foo:results", "job:foo"]
        # Only "job:foo" has created_at; the :results key should be ignored
        rc.hget.return_value = self._recent_ts(1)

        with patch.object(tasks_module, "get_redis_client", return_value=rc):
            result = cleanup_expired_jobs.run()

        # Only one key inspected (not the :results one)
        assert rc.hget.call_count == 1

    def test_returns_zero_when_no_jobs(self):
        rc = _make_redis_mock()
        rc.keys.return_value = []

        with patch.object(tasks_module, "get_redis_client", return_value=rc):
            result = cleanup_expired_jobs.run()

        assert result["deleted_jobs"] == 0

    def test_continues_on_per_key_error(self):
        """Errors on individual keys should not abort the whole scan."""
        rc = _make_redis_mock()
        rc.keys.return_value = ["job:bad-key", "job:old-good"]
        # First hget raises, second returns an old timestamp
        rc.hget.side_effect = [Exception("bad key"), self._old_ts(9), None]

        with patch.object(tasks_module, "get_redis_client", return_value=rc):
            result = cleanup_expired_jobs.run()

        # The good old job should still be deleted
        assert result["deleted_jobs"] == 1


# ===========================================================================
# 4. Celery app configuration
# ===========================================================================

class TestCeleryAppConfiguration:
    def test_broker_url_default(self):
        assert celery_app.conf.broker_url == "redis://localhost:6380/0"

    def test_backend_url_default(self):
        assert celery_app.conf.result_backend == "redis://localhost:6380/0"

    def test_task_serializer_is_json(self):
        assert celery_app.conf.task_serializer == "json"

    def test_result_serializer_is_json(self):
        assert celery_app.conf.result_serializer == "json"

    def test_timezone_is_utc(self):
        assert celery_app.conf.timezone == "UTC"

    def test_task_time_limit(self):
        assert celery_app.conf.task_time_limit == 3600

    def test_task_soft_time_limit(self):
        assert celery_app.conf.task_soft_time_limit == 3300

    def test_task_routing_to_valinor_queue(self):
        routes = celery_app.conf.task_routes
        assert "worker.tasks.*" in routes
        assert routes["worker.tasks.*"]["queue"] == "valinor"

    def test_beat_schedule_contains_cleanup(self):
        assert "cleanup-expired-jobs" in celery_app.conf.beat_schedule

    def test_run_analysis_task_max_retries(self):
        assert run_analysis_task.max_retries == 2

    def test_run_analysis_task_retry_backoff(self):
        assert run_analysis_task.retry_backoff is True
