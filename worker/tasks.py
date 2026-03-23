"""
Celery Worker Tasks for Valinor SaaS.
Handles background processing of analysis jobs.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timedelta

import structlog
import redis

# Add shared modules to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.adapters.valinor_adapter import ValinorAdapter
from shared.storage import MetadataStorage
from worker.celery_app import celery_app

logger = structlog.get_logger()

_SENSITIVE_KEYS = frozenset({"password", "ssh_key", "ssh_private_key_path"})


def _redact_config(data: Any) -> Any:
    """Return a deep copy of *data* with sensitive fields replaced by '***REDACTED***'."""
    if isinstance(data, dict):
        return {
            k: ("***REDACTED***" if k in _SENSITIVE_KEYS else _redact_config(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact_config(item) for item in data]
    return data


def _fire_webhooks_sync(job_id: str, client_name: str, status: str, results: dict):
    """Fire registered webhooks for a client synchronously (called from Celery task)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_fire_webhooks_async(job_id, client_name, status, results))
        finally:
            loop.close()
    except Exception as e:
        logger.warning("Webhook firing failed", job_id=job_id, error=str(e))


async def _fire_webhooks_async(job_id: str, client_name: str, status: str, results: dict):
    """Load client profile and fire all registered webhooks."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared.memory.profile_store import get_profile_store
    from api.webhooks import fire_job_completion_webhook, build_job_summary

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        return

    webhooks = getattr(profile, "webhooks", []) or []
    if not webhooks:
        return

    summary = build_job_summary(results)
    for wh in webhooks:
        url = wh.get("url") if isinstance(wh, dict) else str(wh)
        if url:
            await fire_job_completion_webhook(url, job_id, client_name, status, summary)

# Global components
redis_client = None
metadata_storage = MetadataStorage()

def get_redis_client():
    """Get Redis client for progress updates."""
    global redis_client
    if redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
    return redis_client

class ProgressUpdater:
    """Helper class to update job progress in Redis."""
    
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.redis_client = get_redis_client()
        
    async def update_progress(self, stage: str, progress: int, message: str):
        """Update job progress in Redis."""
        try:
            self.redis_client.hset(f"job:{self.job_id}", mapping={
                "status": "running",
                "stage": stage,
                "progress": progress,
                "message": message,
                "updated_at": datetime.utcnow().isoformat()
            })
            
            logger.info(
                "Progress updated",
                job_id=self.job_id,
                stage=stage,
                progress=progress,
                message=message
            )
            
        except Exception as e:
            logger.warning(
                "Failed to update progress",
                job_id=self.job_id,
                error=str(e)
            )

@celery_app.task(name='worker.tasks.cleanup_job', queue='maintenance')
def cleanup_job(job_id: str):
    """
    Clean up temporary files and data for completed job.
    
    Args:
        job_id: Job to clean up
    """
    logger.info("Starting job cleanup", job_id=job_id)
    
    try:
        # Remove temporary output files
        output_dir = Path(f"/tmp/valinor_output/{job_id}")
        if output_dir.exists():
            import shutil
            shutil.rmtree(output_dir, ignore_errors=True)
            logger.info("Removed output directory", job_id=job_id, path=str(output_dir))
        
        # Remove Redis data
        redis_client = get_redis_client()
        
        # Remove job data (keep for audit trail - just expire sooner)
        redis_client.expire(f"job:{job_id}", 604800)  # 7 days
        redis_client.expire(f"job:{job_id}:results", 604800)  # 7 days
        
        logger.info("Job cleanup completed", job_id=job_id)
        
    except Exception as e:
        logger.error(
            "Job cleanup failed",
            job_id=job_id,
            error=str(e)
        )
        # Don't raise - cleanup failures shouldn't fail the task

@celery_app.task(
    bind=True,
    name="worker.tasks.run_analysis_task",
    max_retries=2,
    retry_backoff=True,
    queue="analysis",
)
def run_analysis_task(
    self,
    job_id: str,
    client_name: str,
    connection_config: Dict[str, Any],
    period: str,
    analysis_config: Dict[str, Any],
):
    """
    Celery task that executes a full Valinor analysis for a given job.

    Parameters
    ----------
    job_id:            Unique job identifier (UUID string).
    client_name:       Human-readable client label.
    connection_config: SSH + DB connection details forwarded to ValinorAdapter.
    period:            Analysis period string (e.g. "Q1-2026").
    analysis_config:   Extra options dict (sector, country, overrides, …).
    """
    logger.info(
        "Starting run_analysis_task",
        job_id=job_id,
        client=client_name,
        celery_task_id=self.request.id,
    )

    rc = get_redis_client()

    try:
        # Mark job as running (redact sensitive fields before writing to Redis)
        safe_config = _redact_config(connection_config)
        rc.hset(f"job:{job_id}", mapping={
            "status": "running",
            "started_at": datetime.utcnow().isoformat(),
            "task_id": self.request.id,
            "config": json.dumps(safe_config, default=str),
        })

        # Run the async pipeline in a fresh event loop (with original, unredacted config)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(
                _run_analysis_task_async(
                    job_id, client_name, connection_config, period, analysis_config
                )
            )
        finally:
            loop.close()

        # Persist results
        rc.set(
            f"job:{job_id}:results",
            json.dumps(results, default=str),
            ex=86400,  # 24 hours
        )

        # Update status to completed
        rc.hset(f"job:{job_id}", mapping={
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "message": "Analysis completed successfully",
        })

        logger.info(
            "run_analysis_task completed",
            job_id=job_id,
            client=client_name,
            execution_time=results.get("execution_time_seconds"),
        )

        # Fire webhooks
        _fire_webhooks_sync(job_id, client_name, "completed", results)

        # Schedule per-job cleanup after 24 h
        cleanup_job.apply_async(args=[job_id], countdown=86400)

        return {
            "job_id": job_id,
            "status": "completed",
            "findings_count": len(results.get("findings", {})),
            "execution_time": results.get("execution_time_seconds"),
        }

    except Exception as exc:
        logger.error(
            "run_analysis_task failed",
            job_id=job_id,
            client=client_name,
            error=str(exc),
            exc_info=True,
        )

        try:
            rc.hset(f"job:{job_id}", mapping={
                "status": "failed",
                "error": str(exc),
                "failed_at": datetime.utcnow().isoformat(),
            })
        except Exception:
            pass

        _fire_webhooks_sync(job_id, client_name, "failed", {})

        # Retry with backoff (raises MaxRetriesExceededError when exhausted)
        raise self.retry(exc=exc)


async def _run_analysis_task_async(
    job_id: str,
    client_name: str,
    connection_config: Dict[str, Any],
    period: str,
    analysis_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Async core for run_analysis_task."""
    # Merge analysis_config into connection_config so ValinorAdapter receives
    # sector, country, currency, overrides, etc.
    full_config = {**connection_config, **analysis_config, "client_name": client_name}

    adapter = ValinorAdapter()
    results = await adapter.run_analysis(
        job_id=job_id,
        client_name=client_name,
        connection_config=full_config,
        period=period,
    )
    return results


@celery_app.task(name="worker.tasks.cleanup_expired_jobs", queue="maintenance")
def cleanup_expired_jobs():
    """
    Periodic task (every 6 hours) that removes Redis job keys older than 7 days.
    Only the job hash key is deleted; the corresponding :results key is also
    deleted when found.
    """
    logger.info("cleanup_expired_jobs: starting scan")

    rc = get_redis_client()
    cutoff = datetime.utcnow() - timedelta(days=7)
    deleted = 0

    try:
        # Scan for all job hash keys (exclude :results sub-keys)
        # Use scan_iter instead of keys() to avoid blocking Redis (O(N) KEYS)
        job_keys = [k for k in rc.scan_iter("job:*") if not k.endswith(":results")]

        for key in job_keys:
            try:
                created_at_raw = rc.hget(key, "created_at")
                if not created_at_raw:
                    continue
                created_at = datetime.fromisoformat(created_at_raw)
                if created_at < cutoff:
                    job_id = rc.hget(key, "job_id") or key.split(":", 1)[-1]
                    rc.delete(key)
                    rc.delete(f"job:{job_id}:results")
                    deleted += 1
            except Exception as inner_exc:
                logger.warning(
                    "cleanup_expired_jobs: error processing key",
                    key=key,
                    error=str(inner_exc),
                )

        logger.info("cleanup_expired_jobs: finished", deleted_jobs=deleted)
        return {"deleted_jobs": deleted}

    except Exception as exc:
        logger.error("cleanup_expired_jobs: scan failed", error=str(exc))
        return {"error": str(exc)}


@celery_app.task(name='worker.tasks.health_check', queue='maintenance')
def health_check():
    """
    Worker health check task.
    """
    try:
        # Check Redis connectivity
        redis_client = get_redis_client()
        redis_client.ping()
        
        # Check metadata storage
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(metadata_storage.health_check())
        finally:
            loop.close()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "worker_id": os.getpid()
        }
        
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
            "worker_id": os.getpid()
        }

@celery_app.task(name='worker.tasks.monitor_jobs', queue='maintenance')
def monitor_jobs():
    """
    Periodic task to monitor job status and handle stale jobs.
    """
    logger.info("Running job monitor")
    
    try:
        redis_client = get_redis_client()
        
        # Find running jobs that might be stale
        # Use scan_iter instead of keys() to avoid blocking Redis (O(N) KEYS)
        job_keys = [key for key in redis_client.scan_iter("job:*") if not key.endswith(":results")]
        
        stale_cutoff = datetime.utcnow().timestamp() - 7200  # 2 hours
        stale_jobs = []
        
        for key in job_keys:
            job_data = redis_client.hgetall(key)
            
            if job_data.get("status") == "running":
                updated_at = job_data.get("updated_at")
                if updated_at:
                    try:
                        updated_timestamp = datetime.fromisoformat(updated_at).timestamp()
                        if updated_timestamp < stale_cutoff:
                            stale_jobs.append(job_data.get("job_id"))
                    except:
                        continue
        
        # Mark stale jobs as failed
        for job_id in stale_jobs:
            redis_client.hset(f"job:{job_id}", mapping={
                "status": "failed",
                "error": "Job timeout - marked as stale",
                "failed_at": datetime.utcnow().isoformat()
            })
            
            logger.warning("Marked stale job as failed", job_id=job_id)
        
        return {
            "checked_jobs": len(job_keys),
            "stale_jobs_found": len(stale_jobs),
            "stale_jobs": stale_jobs
        }
        
    except Exception as e:
        logger.error("Job monitoring failed", error=str(e))
        return {"error": str(e)}

# Periodic tasks configuration
# Note: cleanup_expired_jobs is already registered in celery_app.py beat_schedule.
# The entries below are merged/updated here to keep all schedule definitions together.
celery_app.conf.beat_schedule.update({
    'health-check': {
        'task': 'worker.tasks.health_check',
        'schedule': 300.0,  # Every 5 minutes
    },
    'monitor-jobs': {
        'task': 'worker.tasks.monitor_jobs',
        'schedule': 600.0,  # Every 10 minutes
    },
})

if __name__ == "__main__":
    # For debugging - run worker programmatically
    celery_app.start()