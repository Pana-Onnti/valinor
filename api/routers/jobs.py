"""
Jobs router — Analysis job lifecycle endpoints.

Extracted from main.py for better modularity.
"""

import os
import uuid
import json
import time
import math
import asyncio
import re as _re
from typing import Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, status, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
import structlog
import redis.asyncio as redis

from api.models import AnalysisRequest, JobStatus, AgentStatus
from api.deps import get_redis, get_limiter  # noqa: F401
from shared.events.pipeline_events import (
    subscribe_pipeline_events,
    get_agent_statuses,
    estimate_remaining_seconds,
)  # PipelineEvent used internally by subscribe_pipeline_events

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["Jobs"])


# ═══ INPUT VALIDATION HELPERS ═══

def _validate_client_name(name: str) -> str:
    if not name or len(name) > 100:
        raise ValueError("client_name must be 1-100 characters")
    if not _re.match(r'^[a-zA-Z0-9_\-\.]+$', name):
        raise ValueError("client_name may only contain alphanumeric characters, underscore, hyphen, dot")
    return name


def _validate_period(period: str) -> str:
    if not period:
        return period
    patterns = [
        r'^Q[1-4]-\d{4}$',  # Q1-2025
        r'^H[12]-\d{4}$',       # H1-2025
        r'^\d{4}$',              # 2025
        r'^\d{4}-\d{2}$',       # 2025-04 (monthly)
        r'^[A-Z][a-z]+-\d{4}$',  # Enero-2025
    ]
    if not any(_re.match(p, period) for p in patterns):
        raise ValueError(f"Invalid period format: {period}. Expected: 2025-04, Q1-2025, H1-2025, 2025")
    return period


# ═══ IN-MEMORY LRU CACHE FOR COMPLETED JOB RESULTS ═══
# Keyed by job_id -> (results_dict, cached_at_timestamp)
_results_cache: dict[str, tuple[dict, float]] = {}
_RESULTS_CACHE_TTL = 300  # seconds (5 minutes)


@router.post("/analyze", response_model=Dict[str, str], summary="Start analysis", tags=["Analysis"])
async def start_analysis(
    request: Request,
    body: AnalysisRequest,
    background_tasks: BackgroundTasks,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Start a new Valinor analysis job.

    Returns immediately with job ID. Use /api/jobs/{job_id}/status to track progress.
    """
    # Input validation
    if body.client_name:
        try:
            _validate_client_name(body.client_name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if body.period:
        try:
            _validate_period(body.period)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if body.db_config.port < 1 or body.db_config.port > 65535:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="db_config.port must be between 1 and 65535")
    if body.ssh_config:
        ssh_host = body.ssh_config.host
        if not ssh_host or not _re.match(r'^[a-zA-Z0-9\.\-\_]+$', ssh_host):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ssh_config.host contains invalid characters")

    job_id = str(uuid.uuid4())

    logger.info(
        "Starting analysis",
        job_id=job_id,
        client=body.client_name,
        period=body.period
    )

    try:
        # Store job request in Redis
        client_name = body.client_name or body.db_config.get_db_name() or "unknown"
        period = body.period or "unspecified"

        # Per-client monthly analysis limit: max 25 analyses per client per month
        current_month = datetime.utcnow().strftime("%Y-%m")
        monthly_key = f"monthly_limit:{client_name}:{current_month}"
        monthly_count = await redis_client.incr(monthly_key)
        if monthly_count == 1:
            # First increment — set TTL of 33 days so the key auto-expires after the month
            await redis_client.expire(monthly_key, 33 * 86400)
        if monthly_count > 25:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "monthly_limit_reached",
                    "client": client_name,
                    "limit": 25,
                    "message": "Monthly analysis limit reached",
                }
            )

        # Per-client concurrent job limit: max 2 running jobs per client_name
        running_count = 0
        async for key in redis_client.scan_iter("job:*"):
            if b":" in key[4:] if isinstance(key, bytes) else ":" in key[4:]:
                continue  # skip job:UUID:sub-key entries
            try:
                job_status_val = await redis_client.hget(key, "status")
            except Exception:
                continue
            if job_status_val == "running":
                job_client = await redis_client.hget(key, "client_name")
                if job_client == client_name:
                    running_count += 1
                    if running_count >= 2:
                        break
        if running_count >= 2:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "too_many_concurrent_jobs",
                    "message": "Maximum 2 concurrent jobs per client",
                    "client": client_name,
                }
            )
        # Build a sanitized copy of the request for retry support (no passwords)
        request_dict = body.model_dump()
        safe_request = json.loads(json.dumps(request_dict, default=str))
        for sensitive_key in ("password", "ssh_password", "private_key", "ssh_private_key"):
            if "db_config" in safe_request and isinstance(safe_request["db_config"], dict):
                safe_request["db_config"].pop(sensitive_key, None)
            if "ssh_config" in safe_request and isinstance(safe_request["ssh_config"], dict):
                safe_request["ssh_config"].pop(sensitive_key, None)

        job_data = {
            "job_id": job_id,
            "status": "pending",
            "client_name": client_name,
            "period": period,
            "created_at": datetime.utcnow().isoformat(),
            "request": json.dumps(body.model_dump()),
            "request_data": json.dumps(safe_request),
        }

        await redis_client.hset(f"job:{job_id}", mapping=job_data)
        await redis_client.expire(f"job:{job_id}", 86400)  # 24 hours

        # Audit log: analysis_started
        await redis_client.lpush("audit_log", json.dumps({
            "event_type": "analysis_started",
            "job_id": job_id,
            "client_name": client_name,
            "timestamp": datetime.utcnow().isoformat(),
        }))
        await redis_client.ltrim("audit_log", 0, 999)

        # Queue background task
        from api.tasks import run_analysis_task

        celery_enabled = os.getenv("CELERY_ENABLED", "false").lower() in ("1", "true", "yes")
        if celery_enabled:
            try:
                from worker.tasks import run_analysis_task as _celery_run_analysis_task

                _req_dict = body.model_dump()
                _connection_config = {
                    "ssh_config": _req_dict.get("ssh_config"),
                    "db_config": _req_dict.get("db_config"),
                }
                _analysis_config = {
                    "sector": body.sector,
                    "country": body.country or "US",
                    "currency": body.currency or "USD",
                    "language": body.language or "en",
                    "erp": body.erp,
                    "fiscal_context": body.fiscal_context or "generic",
                    "overrides": body.overrides or {},
                }
                _celery_run_analysis_task.apply_async(
                    kwargs={
                        "job_id": job_id,
                        "client_name": client_name,
                        "connection_config": _connection_config,
                        "period": period,
                        "analysis_config": _analysis_config,
                    },
                    queue="valinor",
                )
                logger.info("Analysis dispatched to Celery", job_id=job_id, client=client_name)
            except Exception as _celery_err:
                logger.warning(
                    "Celery dispatch failed, falling back to BackgroundTasks",
                    job_id=job_id,
                    error=str(_celery_err),
                )
                background_tasks.add_task(run_analysis_task, job_id, body.model_dump())
        else:
            background_tasks.add_task(
                run_analysis_task,
                job_id,
                body.model_dump(),
            )

        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Analysis queued successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to queue analysis",
            job_id=job_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue analysis: {str(e)}"
        )


@router.get("/jobs/{job_id}/status", response_model=JobStatus, summary="Get job status")
async def get_job_status(
    job_id: str,
    redis_client: redis.Redis = Depends(get_redis)
):
    """Get current status of an analysis job, enriched with per-agent detail."""
    try:
        job_data = await redis_client.hgetall(f"job:{job_id}")

        if not job_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )

        error_detail = None
        if job_data.get("error_detail"):
            try:
                error_detail = json.loads(job_data["error_detail"])
            except Exception:
                pass

        # Fetch per-agent statuses from Redis hash (best-effort)
        agents = None
        remaining = None
        try:
            agent_statuses_raw = await get_agent_statuses(redis_client, job_id)
            agents = [AgentStatus(**a) for a in agent_statuses_raw] if agent_statuses_raw else None
            remaining = await estimate_remaining_seconds(redis_client, job_id)
        except Exception:
            pass  # Graceful degradation — agent details are optional

        return JobStatus(
            job_id=job_id,
            status=job_data.get("status", "unknown"),
            stage=job_data.get("stage"),
            progress=int(job_data["progress"]) if job_data.get("progress") else None,
            message=job_data.get("message"),
            started_at=datetime.fromisoformat(job_data["started_at"]) if job_data.get("started_at") else None,
            completed_at=datetime.fromisoformat(job_data["completed_at"]) if job_data.get("completed_at") else None,
            error=job_data.get("error"),
            error_detail=error_detail,
            agents=agents,
            estimated_remaining_seconds=remaining,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get job status", job_id=job_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job status: {str(e)}"
        )


@router.get("/jobs/{job_id}/stream", summary="Stream job progress via SSE")
async def stream_job_progress(job_id: str):
    """
    Server-Sent Events stream for real-time job progress.

    Uses Redis pub/sub for instant event delivery (no polling).
    On connect, sends current state snapshot so late subscribers
    can catch up. Terminates on job completion, failure, or cancel.
    """
    async def event_generator():
        try:
            r = await get_redis()

            # ── 1. Check if job exists ──
            job_data = await r.hgetall(f"job:{job_id}")
            if not job_data:
                yield f"data: {json.dumps({'error': 'Job not found', 'job_id': job_id})}\n\n"
                return

            current_status = job_data.get("status", "unknown")

            # ── 2. Send current state snapshot (reconnect support) ──
            agent_statuses = await get_agent_statuses(r, job_id)
            remaining = await estimate_remaining_seconds(r, job_id)
            snapshot = {
                "job_id": job_id,
                "type": "snapshot",
                "status": current_status,
                "stage": job_data.get("stage", ""),
                "progress": int(job_data.get("progress", 0) or 0),
                "message": job_data.get("message", ""),
                "agents": agent_statuses,
                "estimated_remaining_seconds": remaining,
                "timestamp": datetime.utcnow().isoformat(),
            }
            yield f"data: {json.dumps(snapshot)}\n\n"

            # ── 3. If already terminal, close immediately ──
            if current_status in ("completed", "failed", "cancelled"):
                yield f'data: {json.dumps({"final": True, "status": current_status})}\n\n'
                return

            # ── 4. Subscribe to pub/sub for live events ──
            async for event in subscribe_pipeline_events(r, job_id):
                event_data = {
                    "job_id": job_id,
                    "type": "agent_event",
                    "agent": event.agent,
                    "agent_status": event.status,
                    "status": "running",
                    "progress": event.progress or 0,
                    "stage": event.agent,
                    "message": event.message,
                    "timestamp": event.timestamp.isoformat(),
                }
                if event.duration_seconds is not None:
                    event_data["duration_seconds"] = event.duration_seconds
                if event.metadata:
                    event_data["metadata"] = event.metadata

                yield f"data: {json.dumps(event_data)}\n\n"

                if event.agent == "delivery" and event.status == "completed":
                    final_agents = await get_agent_statuses(r, job_id)
                    yield f"data: {json.dumps({'job_id': job_id, 'type': 'final', 'status': 'completed', 'stage': 'done', 'progress': 100, 'message': 'Analysis completed', 'agents': final_agents, 'final': True})}\n\n"
                    return

                if event.status == "error":
                    final_agents = await get_agent_statuses(r, job_id)
                    error_event = {
                        "job_id": job_id,
                        "type": "final",
                        "status": "failed",
                        "stage": event.agent,
                        "progress": event.progress or 0,
                        "message": event.message,
                        "agents": final_agents,
                        "final": True,
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                    return

        except asyncio.CancelledError:
            pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

        yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.websocket("/jobs/{job_id}/ws")
async def job_progress_ws(job_id: str, websocket: WebSocket):
    """WebSocket endpoint for real-time job progress via Redis pub/sub."""
    await websocket.accept()
    try:
        r = await get_redis()
        job_data = await r.hgetall(f"job:{job_id}")
        if not job_data:
            await websocket.send_json({"error": "job_not_found"})
            return

        current_status = job_data.get("status", "unknown")

        # Send current state snapshot
        agent_statuses = await get_agent_statuses(r, job_id)
        await websocket.send_json({
            "type": "snapshot",
            "status": current_status,
            "progress": int(job_data.get("progress", 0) or 0),
            "stage": job_data.get("stage", ""),
            "agents": agent_statuses,
        })

        # If already terminal, close
        if current_status in ("completed", "failed", "cancelled"):
            await websocket.send_json({"final": True, "status": current_status})
            return

        # Subscribe to pub/sub for live events
        async for event in subscribe_pipeline_events(r, job_id):
            payload = {
                "type": "agent_event",
                "agent": event.agent,
                "agent_status": event.status,
                "status": "running",
                "progress": event.progress or 0,
                "stage": event.agent,
                "message": event.message,
            }
            if event.duration_seconds is not None:
                payload["duration_seconds"] = event.duration_seconds
            if event.metadata:
                payload["metadata"] = event.metadata

            await websocket.send_json(payload)

            if event.agent == "delivery" and event.status == "completed":
                await websocket.send_json({"final": True, "status": "completed"})
                return
            if event.status == "error":
                await websocket.send_json({"final": True, "status": "failed"})
                return
    except WebSocketDisconnect:
        pass


@router.get("/jobs/{job_id}/results", summary="Get job results")
async def get_job_results(
    job_id: str,
    redis_client: redis.Redis = Depends(get_redis)
):
    """Get results from completed analysis job."""
    try:
        # ── Cache hit: return without touching Redis ──
        now = time.time()
        cached = _results_cache.get(job_id)
        if cached is not None:
            cached_results, cached_at = cached
            if now - cached_at <= _RESULTS_CACHE_TTL:
                return cached_results

        job_data = await redis_client.hgetall(f"job:{job_id}")

        if not job_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

        if job_data.get("status") != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job not completed. Current status: {job_data.get('status', 'unknown')}"
            )

        results_key = f"job:{job_id}:results"
        results_data = await redis_client.get(results_key)

        if not results_data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Results not found")

        results = json.loads(results_data)

        # Add download URLs for output files
        output_dir = results.get("stages", {}).get("delivery", {}).get("output_path")
        if output_dir and Path(output_dir).exists():
            results["download_urls"] = {
                "executive_report": f"/api/jobs/{job_id}/download/executive_report.pdf",
                "ceo_report": f"/api/jobs/{job_id}/download/ceo_report.pdf",
                "controller_report": f"/api/jobs/{job_id}/download/controller_report.pdf",
                "sales_report": f"/api/jobs/{job_id}/download/sales_report.pdf",
                "raw_data": f"/api/jobs/{job_id}/download/raw_data.json"
            }

        # Surface DQ metadata prominently in results
        if results.get("data_quality"):
            results["_dq_summary"] = {
                "score": results["data_quality"]["score"],
                "label": results["data_quality"]["confidence_label"],
                "tag": results["data_quality"]["tag"],
            }

        # ── Store in cache for subsequent requests ──
        _results_cache[job_id] = (results, time.time())

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get job results", job_id=job_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job results: {str(e)}"
        )


@router.get("/jobs/{job_id}/download/{filename}", summary="Download result file")
async def download_file(job_id: str, filename: str):
    """Download specific result file from completed job."""
    try:
        allowed_files = [
            "executive_report.pdf",
            "ceo_report.pdf",
            "controller_report.pdf",
            "sales_report.pdf",
            "raw_data.json"
        ]

        if filename not in allowed_files:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")

        redis_client = await get_redis()
        job_data = await redis_client.hgetall(f"job:{job_id}")

        if not job_data or job_data.get("status") != "completed":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found or not completed")

        output_dir = Path(f"/tmp/valinor_output/{job_id}")
        file_path = output_dir / filename

        if not file_path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

        return FileResponse(path=str(file_path), filename=filename, media_type='application/octet-stream')

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to download file", job_id=job_id, filename=filename, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}"
        )


_VALID_SORT_FIELDS = {"created_at", "status", "client_name"}


@router.get("/jobs", summary="List jobs")
async def list_jobs(
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    client_name: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    """List analysis jobs with pagination, sorting and optional status filter."""
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if not (1 <= page_size <= 100):
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 100")
    if sort_by not in _VALID_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"sort_by must be one of: {', '.join(sorted(_VALID_SORT_FIELDS))}",
        )
    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

    redis_client = await get_redis()

    job_keys = []
    async for key in redis_client.scan_iter("job:*"):
        key_str = key if isinstance(key, str) else key.decode()
        if ":results" not in key_str:
            job_keys.append(key_str)

    jobs = []
    for key in job_keys:
        job_data = await redis_client.hgetall(key)
        if not job_data:
            continue
        job_id_val = key.replace("job:", "")
        job_status = job_data.get("status", "unknown")
        if status_filter and job_status != status_filter:
            continue
        job_client = job_data.get("client_name", "")
        if client_name and job_client != client_name:
            continue
        jobs.append({
            "job_id": job_id_val,
            "status": job_status,
            "client_name": job_data.get("client_name", "unknown"),
            "period": job_data.get("period"),
            "created_at": job_data.get("created_at"),
            "completed_at": job_data.get("completed_at"),
            "stage": job_data.get("stage"),
            "progress": job_data.get("progress"),
        })

    reverse = sort_order == "desc"
    jobs.sort(key=lambda x: x.get(sort_by) or "", reverse=reverse)

    total = len(jobs)
    pages = math.ceil(total / page_size) if page_size else 1
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "jobs": jobs[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }


# ═══ JOB LIFECYCLE MANAGEMENT ═══

@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a running or pending job."""
    redis_client = await get_redis()
    job_data = await redis_client.hgetall(f"job:{job_id}")
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    current_status = job_data.get("status", "unknown")
    if current_status in ("completed", "failed", "cancelled"):
        return {"status": current_status, "message": "Job already finished"}

    await redis_client.hset(f"job:{job_id}", mapping={
        "status": "cancelled",
        "cancelled_at": datetime.utcnow().isoformat(),
    })
    return {"status": "cancelled", "job_id": job_id}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, background_tasks: BackgroundTasks):
    """Retry a failed job with the same parameters."""
    redis_client = await get_redis()
    job_data = await redis_client.hgetall(f"job:{job_id}")

    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data.get("status") not in ("failed", "cancelled"):
        raise HTTPException(status_code=400, detail="Only failed or cancelled jobs can be retried")

    request_data_raw = job_data.get("request_data")
    if not request_data_raw:
        raise HTTPException(status_code=400, detail="Original request data not available for retry")

    from api.tasks import run_analysis_task

    new_job_id = str(uuid.uuid4())
    request_data = json.loads(request_data_raw)
    request_data["job_id"] = new_job_id

    await redis_client.hset(f"job:{new_job_id}", mapping={
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "client_name": job_data.get("client_name", "unknown"),
        "retry_of": job_id,
        "request_data": request_data_raw,
    })
    await redis_client.expire(f"job:{new_job_id}", 86400)

    background_tasks.add_task(run_analysis_task, new_job_id, request_data)
    return {"job_id": new_job_id, "status": "pending", "retry_of": job_id}


@router.delete("/jobs/cleanup")
async def cleanup_old_jobs(older_than_days: int = 7):
    """Delete completed/failed jobs older than N days."""
    redis_client = await get_redis()
    cutoff = (datetime.utcnow() - timedelta(days=older_than_days)).isoformat()

    deleted = 0
    async for key in redis_client.scan_iter("job:*"):
        key_str = key if isinstance(key, str) else key.decode()
        if ":results" in key_str:
            continue
        job_data = await redis_client.hgetall(key_str)
        job_status = job_data.get("status", "")
        created_at = job_data.get("created_at", "")

        if job_status in ("completed", "failed", "cancelled") and created_at < cutoff:
            await redis_client.delete(key_str)
            await redis_client.delete(f"{key_str}:results")
            deleted += 1

    return {"deleted": deleted, "cutoff": cutoff}


@router.get("/cache/stats", summary="In-memory results cache statistics", tags=["Observability"])
async def get_cache_stats():
    """Return observability metrics for the in-memory completed-job results cache."""
    now = time.time()
    stale_keys = [k for k, (_, ts) in _results_cache.items() if now - ts > _RESULTS_CACHE_TTL]
    for k in stale_keys:
        del _results_cache[k]

    cached_jobs = len(_results_cache)
    if cached_jobs == 0:
        oldest_age = 0.0
    else:
        oldest_age = round(max(now - ts for _, ts in _results_cache.values()), 2)

    return {
        "cached_jobs": cached_jobs,
        "oldest_entry_age_seconds": oldest_age,
    }
