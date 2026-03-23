"""
System router — Health checks, system status, metrics, and audit endpoints.

Extracted from main.py for better modularity.
"""

import os
import time
import json
import importlib
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Body
import structlog
import redis.asyncio as redis

from api.deps import get_redis
from api.metrics import metrics_response
from shared.storage import MetadataStorage

logger = structlog.get_logger()

router = APIRouter(tags=["System"])

metadata_storage = MetadataStorage()
_app_start_time: float = time.time()


def set_app_start_time(t: float):
    global _app_start_time
    _app_start_time = t


@router.get("/health", summary="Health check")
async def health_check():
    """Service health check endpoint."""
    try:
        redis_client = await get_redis()
        await redis_client.ping()
        redis_status = "healthy"
    except Exception:
        redis_status = "unhealthy"

    try:
        await metadata_storage.health_check()
        storage_status = "healthy"
    except Exception:
        storage_status = "unhealthy"

    overall_status = "healthy" if all([
        redis_status == "healthy",
        storage_status == "healthy"
    ]) else "unhealthy"

    uptime_seconds = time.time() - _app_start_time
    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "redis": redis_status,
            "storage": storage_status
        },
        "version": "2.0.0",
        "uptime_seconds": round(uptime_seconds, 1),
        "environment": os.getenv("APP_ENV", "development"),
    }


@router.get("/api/version", summary="API version info", tags=["System"])
async def get_version():
    """Return API version and build info."""
    return {
        "version": "2.0.0",
        "api_prefix": "/api/v1",
        "supported_db_types": ["postgres", "mysql", "sqlserver", "oracle"],
        "max_analysis_duration_minutes": 15,
        "cost_per_analysis_usd": 8.0,
    }


@router.post("/api/audit", summary="Log audit event", tags=["System"])
async def log_audit_event(
    event: dict = Body(...),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Internal endpoint to log audit events."""
    await redis_client.lpush("audit_log", json.dumps({**event, "timestamp": datetime.utcnow().isoformat()}))
    await redis_client.ltrim("audit_log", 0, 999)
    return {"logged": True}


@router.get("/api/audit", summary="Read audit events", tags=["System"])
async def get_audit_events(
    limit: int = 50,
    event_type: Optional[str] = None,
    redis_client: redis.Redis = Depends(get_redis)
):
    """Read recent audit events from Redis."""
    raw_events = await redis_client.lrange("audit_log", 0, limit - 1)
    events = []
    for raw in raw_events:
        try:
            evt = json.loads(raw)
        except Exception:
            continue
        if event_type is None or evt.get("event_type") == event_type:
            events.append(evt)
    return {"events": events, "total_returned": len(events)}


@router.get("/sentry-debug", include_in_schema=False)
async def sentry_debug():
    """Trigger a test error to verify Sentry integration. Non-production only."""
    if os.getenv("APP_ENV", "development") == "production":
        raise HTTPException(status_code=404)
    raise ZeroDivisionError("Sentry debug endpoint triggered")


@router.get("/api/system/status", tags=["System"])
async def system_status():
    """Comprehensive system status."""
    def check_pkg(name: str) -> dict:
        try:
            mod = importlib.import_module(name.replace('-', '_'))
            return {"installed": True, "version": getattr(mod, '__version__', 'unknown')}
        except ImportError:
            return {"installed": False, "version": None}

    redis_ok = False
    redis_info = {}
    try:
        r = await get_redis()
        await r.ping()
        redis_ok = True
        info = await r.info("server")
        redis_info = {"version": info.get("redis_version"), "uptime_days": info.get("uptime_in_days")}
    except Exception:
        pass

    db_ok = False
    try:
        import asyncpg
        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            conn = await asyncpg.connect(db_url)
            await conn.close()
            db_ok = True
    except Exception:
        pass

    return {
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "api": "healthy",
            "redis": "healthy" if redis_ok else "unavailable",
            "database": "healthy" if db_ok else "unavailable",
        },
        "redis": redis_info,
        "features": {
            "data_quality_gate": True,
            "factor_model": True,
            "stl_decomposition": check_pkg("statsmodels")["installed"],
            "cointegration_test": check_pkg("statsmodels")["installed"],
            "benford_law": check_pkg("scipy")["installed"],
            "pdf_reports": check_pkg("reportlab")["installed"],
            "webhooks": True,
            "sse_streaming": True,
            "client_memory": True,
            "segmentation": True,
            "auto_refinement": True,
        },
        "packages": {
            "statsmodels": check_pkg("statsmodels"),
            "scipy": check_pkg("scipy"),
            "reportlab": check_pkg("reportlab"),
            "pandas": check_pkg("pandas"),
            "asyncpg": check_pkg("asyncpg"),
            "httpx": check_pkg("httpx"),
        },
        "quality_checks": [
            "schema_integrity", "null_density", "duplicate_rate",
            "accounting_balance", "cross_table_reconcile", "outlier_screen",
            "benford_compliance", "temporal_consistency", "receivables_cointegration"
        ],
        "llm_provider": os.getenv("LLM_PROVIDER", "console_cli"),
    }


@router.get("/api/system/metrics", tags=["System"])
async def system_metrics():
    """Operational metrics."""
    redis_client = await get_redis()

    status_counts = {"completed": 0, "failed": 0, "running": 0, "pending": 0, "cancelled": 0}
    total_jobs = 0

    async for key in redis_client.scan_iter("job:*"):
        key_str = key if isinstance(key, str) else key.decode()
        if ":results" in key_str:
            continue
        total_jobs += 1
        job_data = await redis_client.hgetall(key_str)
        job_status = job_data.get("status", "unknown")
        if job_status in status_counts:
            status_counts[job_status] += 1

    success_rate = (
        status_counts["completed"] / max(status_counts["completed"] + status_counts["failed"], 1) * 100
    )

    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    client_count = 0
    pool = await store._get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                client_count = await conn.fetchval("SELECT COUNT(*) FROM client_profiles")
        except Exception:
            pass

    estimated_cost_usd = round(status_counts["completed"] * 8.0, 2)

    all_dq_scores = []
    try:
        if pool:
            import json as _json_m
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT profile->>'dq_history' AS dqh FROM client_profiles")
                for row in rows:
                    hist = _json_m.loads(row["dqh"] or "[]")
                    for e in (hist or []):
                        if isinstance(e, dict) and "score" in e:
                            all_dq_scores.append(e["score"])
    except Exception:
        pass
    avg_dq = round(sum(all_dq_scores) / len(all_dq_scores), 1) if all_dq_scores else None

    return {
        "jobs": {**status_counts, "total": total_jobs},
        "success_rate_pct": round(success_rate, 1),
        "clients_with_profile": client_count,
        "estimated_total_cost_usd": estimated_cost_usd,
        "avg_dq_score_all_time": avg_dq,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/api/v1/system/operator-stats", tags=["System"])
async def operator_stats():
    """Aggregated operator dashboard stats."""
    redis_client = await get_redis()

    status_counts = {"completed": 0, "failed": 0, "running": 0, "pending": 0}
    total_jobs = 0
    jobs_today = 0
    execution_times: list[float] = []
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    async for key in redis_client.scan_iter("job:*"):
        key_str = key if isinstance(key, str) else key.decode()
        if ":results" in key_str:
            continue
        total_jobs += 1
        job_data = await redis_client.hgetall(key_str)
        job_status = job_data.get("status", "unknown")
        if job_status in status_counts:
            status_counts[job_status] += 1

        # Count jobs created today
        started = job_data.get("started_at", "")
        if isinstance(started, bytes):
            started = started.decode()
        if started.startswith(today_str):
            jobs_today += 1

        # Collect execution times for completed jobs
        if job_status == "completed":
            elapsed = job_data.get("elapsed_seconds")
            if elapsed is not None:
                try:
                    if isinstance(elapsed, bytes):
                        elapsed = elapsed.decode()
                    execution_times.append(float(elapsed))
                except (ValueError, TypeError):
                    pass

    finished = status_counts["completed"] + status_counts["failed"]
    success_rate = (status_counts["completed"] / max(finished, 1)) * 100
    avg_exec = round(sum(execution_times) / len(execution_times), 2) if execution_times else 0.0
    active_agents = min(status_counts["running"], 5)

    # Client count
    client_count = 0
    try:
        from shared.memory.profile_store import get_profile_store
        store = get_profile_store()
        pool = await store._get_pool()
        if pool:
            async with pool.acquire() as conn:
                client_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM client_profiles"
                )
    except Exception:
        pass

    return {
        "total_clients": client_count,
        "jobs_today": jobs_today,
        "success_rate": round(success_rate, 1),
        "avg_execution_time_s": avg_exec,
        "active_agents": active_agents,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/metrics", tags=["System"], include_in_schema=False)
async def prometheus_metrics():
    """Prometheus text exposition."""
    return metrics_response()
