"""Tenant-scoped Redis jobs mechanism (VAL-176 / VAL-174·B) — additive, mock-based.

Tests the pure key helpers + the ownership-checking get_job_for_tenant dependency
with an AsyncMock redis (no fakeredis dep). The mechanism is not wired into any
router yet, so this is pure unit coverage of the isolation logic — including the
legacy dual-read IDOR the adversarial review caught and reproduced.
"""
import pytest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.deps_jobs import get_job_for_tenant
from api.tenant import DEFAULT_TENANT_ID
from api.tenant_redis_helper import (
    _validate_tenant_uuid,
    tenant_job_key,
    tenant_job_pattern,
    tenant_job_results_key,
)

JOB_ID = "job-abc"
OTHER_TENANT_ID = "00000000-0000-0000-0000-0000000000ff"


class TestKeyHelpers:
    def test_key_formats(self):
        assert tenant_job_key(DEFAULT_TENANT_ID, JOB_ID) == f"tenant:{DEFAULT_TENANT_ID}:job:{JOB_ID}"
        assert tenant_job_results_key(DEFAULT_TENANT_ID, JOB_ID) == f"tenant:{DEFAULT_TENANT_ID}:job:{JOB_ID}:results"
        assert tenant_job_pattern(DEFAULT_TENANT_ID) == f"tenant:{DEFAULT_TENANT_ID}:job:*"

    def test_default_tenant_is_valid(self):
        assert _validate_tenant_uuid(DEFAULT_TENANT_ID) == DEFAULT_TENANT_ID

    @pytest.mark.parametrize("bad", ["", "*", "a:job:x", "tenant:../x", "not-a-uuid", "../../etc", "job:1"])
    def test_non_uuid_rejected_400(self, bad):
        with pytest.raises(HTTPException) as exc:
            tenant_job_key(bad, JOB_ID)
        assert exc.value.status_code == 400


def _redis_returning(mapping):
    """AsyncMock redis whose hgetall(key) -> mapping.get(key, {})."""
    redis = AsyncMock()

    async def _hgetall(key):
        return mapping.get(key, {})

    redis.hgetall = AsyncMock(side_effect=_hgetall)
    return redis


class TestGetJobForTenant:
    @pytest.mark.asyncio
    async def test_owner_reads_its_namespaced_job(self):
        key = tenant_job_key(DEFAULT_TENANT_ID, JOB_ID)
        redis = _redis_returning({key: {"job_id": JOB_ID, "tenant_id": DEFAULT_TENANT_ID, "status": "completed"}})
        with patch("api.deps_jobs.get_redis", AsyncMock(return_value=redis)):
            job = await get_job_for_tenant(JOB_ID, tenant_id=DEFAULT_TENANT_ID)
        assert job["job_id"] == JOB_ID

    @pytest.mark.asyncio
    async def test_absent_job_is_404(self):
        redis = _redis_returning({})
        with patch("api.deps_jobs.get_redis", AsyncMock(return_value=redis)):
            with pytest.raises(HTTPException) as exc:
                await get_job_for_tenant(JOB_ID, tenant_id=DEFAULT_TENANT_ID)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_stamped_other_tenant_is_404_idor(self):
        # A job stamped for DEFAULT must not be readable by OTHER even if OTHER
        # guesses the namespaced key.
        key = tenant_job_key(OTHER_TENANT_ID, JOB_ID)
        redis = _redis_returning({key: {"job_id": JOB_ID, "tenant_id": DEFAULT_TENANT_ID}})
        with patch("api.deps_jobs.get_redis", AsyncMock(return_value=redis)):
            with pytest.raises(HTTPException) as exc:
                await get_job_for_tenant(JOB_ID, tenant_id=OTHER_TENANT_ID)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_default_tenant_dual_reads_legacy_bare_key(self):
        # Legacy job (no tenant_id) belongs to DEFAULT -> default tenant can read it.
        redis = _redis_returning({f"job:{JOB_ID}": {"job_id": JOB_ID, "status": "completed", "client_name": "x"}})
        with patch("api.deps_jobs.get_redis", AsyncMock(return_value=redis)):
            job = await get_job_for_tenant(JOB_ID, tenant_id=DEFAULT_TENANT_ID)
        assert job["job_id"] == JOB_ID

    @pytest.mark.asyncio
    async def test_non_default_tenant_cannot_read_legacy_bare_key_idor(self):
        # The critical IDOR the review reproduced: a legacy bare-key job (no
        # tenant_id) must NOT leak to a non-default tenant via the dual-read.
        redis = _redis_returning({f"job:{JOB_ID}": {"job_id": JOB_ID, "client_name": "victim"}})
        with patch("api.deps_jobs.get_redis", AsyncMock(return_value=redis)):
            with pytest.raises(HTTPException) as exc:
                await get_job_for_tenant(JOB_ID, tenant_id=OTHER_TENANT_ID)
        assert exc.value.status_code == 404
