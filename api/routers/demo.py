"""
Demo router — Run the real Valinor pipeline against a synthetic SQLite database.

Provides a zero-config demo experience:
  POST /api/demo/run   — seeds demo DB if needed, triggers analysis, returns job_id
  GET  /api/demo/status — returns cached demo report if available, or current job status

Results are cached so re-runs are instant (until server restart or manual clear).

Refs: VAL-62
"""

import json
import os
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from api.deps import get_redis

logger = structlog.get_logger()

router = APIRouter(prefix="/api/demo", tags=["Demo"])

# ── Configuration ─────────────────────────────────────────────────────────────

DEMO_DB_PATH = Path(os.getenv("DEMO_DB_PATH", "/tmp/valinor/demo/demo.db"))
DEMO_CLIENT_NAME = "valinor-demo"
DEMO_PERIOD = "2025"
DEMO_CURRENCY = "EUR"

# In-memory cache for demo results
_demo_cache: Dict[str, Any] = {
    "job_id": None,
    "status": "idle",       # idle | seeding | running | completed | failed
    "results": None,
    "error": None,
    "started_at": None,
    "completed_at": None,
}

# Lock to prevent concurrent demo runs
_demo_lock = asyncio.Lock()

# ── Demo client config (Etendo ERP, EUR, EU context) ─────────────────────────

DEMO_CLIENT_CONFIG = {
    "name": DEMO_CLIENT_NAME,
    "display_name": "Valinor Demo Company",
    "sector": "manufacturing",
    "country": "ES",
    "currency": DEMO_CURRENCY,
    "language": "en",
    "erp": "etendo",
    "fiscal_context": "eu",
    "overrides": {},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_demo_db_if_needed() -> bool:
    """Seed the demo database if it does not exist. Returns True if seeded."""
    if DEMO_DB_PATH.exists():
        return False

    from scripts.seed_demo_db import seed_demo_db

    logger.info("Seeding demo database", path=str(DEMO_DB_PATH))
    row_counts = seed_demo_db(DEMO_DB_PATH, force=False)
    logger.info("Demo database seeded", row_counts=row_counts)
    return True


async def _run_demo_pipeline(job_id: str) -> None:
    """Run the full Valinor pipeline against the demo SQLite database."""
    try:
        _demo_cache["status"] = "seeding"
        _demo_cache["started_at"] = datetime.utcnow().isoformat()

        # Seed DB synchronously (fast, <1s)
        _seed_demo_db_if_needed()

        _demo_cache["status"] = "running"

        conn_str = f"sqlite:///{DEMO_DB_PATH}"

        # Build request_data matching the shape expected by run_analysis_task
        request_data = {
            "client_name": DEMO_CLIENT_NAME,
            "period": DEMO_PERIOD,
            "ssh_config": None,
            "db_config": {
                "host": "localhost",
                "port": 0,
                "name": DEMO_CLIENT_NAME,
                "type": "sqlite",
                "connection_string": conn_str,
            },
            "sector": DEMO_CLIENT_CONFIG["sector"],
            "country": DEMO_CLIENT_CONFIG["country"],
            "currency": DEMO_CLIENT_CONFIG["currency"],
            "language": DEMO_CLIENT_CONFIG["language"],
            "erp": DEMO_CLIENT_CONFIG["erp"],
            "fiscal_context": DEMO_CLIENT_CONFIG["fiscal_context"],
            "overrides": DEMO_CLIENT_CONFIG["overrides"],
        }

        from api.tasks import run_analysis_task

        await run_analysis_task(job_id, request_data)

        # Fetch results from Redis
        redis_client = None
        try:
            redis_client = await get_redis()
            raw = await redis_client.get(f"job:{job_id}:results")
            if raw:
                _demo_cache["results"] = json.loads(raw)
        except Exception as e:
            logger.warning("Could not fetch demo results from Redis", error=str(e))

        _demo_cache["status"] = "completed"
        _demo_cache["completed_at"] = datetime.utcnow().isoformat()

        logger.info("Demo pipeline completed", job_id=job_id)

    except Exception as e:
        logger.error("Demo pipeline failed", job_id=job_id, error=str(e))
        _demo_cache["status"] = "failed"
        _demo_cache["error"] = str(e)
        _demo_cache["completed_at"] = datetime.utcnow().isoformat()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run", summary="Run demo analysis")
async def run_demo(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Trigger a demo analysis using synthetic data.

    - Seeds the demo SQLite database if not present
    - Runs the REAL Valinor pipeline (Cartographer -> DQ Gate -> Analysts -> Narrators)
    - Caches results so subsequent calls return instantly

    Returns job_id for tracking progress via /api/demo/status.
    """
    global _demo_cache

    # If we already have cached results, return them immediately
    if _demo_cache["status"] == "completed" and _demo_cache["results"]:
        return JSONResponse(content={
            "job_id": _demo_cache["job_id"],
            "status": "completed",
            "cached": True,
            "message": "Demo results available (cached)",
        })

    # If a demo is already running, return current job_id
    if _demo_cache["status"] in ("seeding", "running"):
        return JSONResponse(
            status_code=202,
            content={
                "job_id": _demo_cache["job_id"],
                "status": _demo_cache["status"],
                "cached": False,
                "message": "Demo analysis already in progress",
            },
        )

    # Start new demo run
    import uuid
    job_id = f"demo-{uuid.uuid4().hex[:12]}"

    _demo_cache = {
        "job_id": job_id,
        "status": "seeding",
        "results": None,
        "error": None,
        "started_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }

    # Store job in Redis for compatibility with /api/jobs/{id}/status
    try:
        redis_client = await get_redis()
        await redis_client.hset(f"job:{job_id}", mapping={
            "job_id": job_id,
            "status": "pending",
            "client_name": DEMO_CLIENT_NAME,
            "period": DEMO_PERIOD,
            "created_at": datetime.utcnow().isoformat(),
            "is_demo": "true",
        })
        await redis_client.expire(f"job:{job_id}", 86400)
    except Exception as e:
        logger.warning("Could not store demo job in Redis", error=str(e))

    # Run in background
    background_tasks.add_task(_run_demo_pipeline, job_id)

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "seeding",
            "cached": False,
            "message": "Demo analysis started. Track progress via /api/demo/status or /api/jobs/{job_id}/status",
        },
    )


@router.get("/status", summary="Get demo status")
async def demo_status(request: Request):
    """
    Get the current status of the demo analysis.

    Returns cached results if available, or current pipeline progress.
    """
    response: Dict[str, Any] = {
        "status": _demo_cache["status"],
        "job_id": _demo_cache["job_id"],
        "started_at": _demo_cache["started_at"],
        "completed_at": _demo_cache["completed_at"],
    }

    if _demo_cache["status"] == "completed" and _demo_cache["results"]:
        response["results"] = _demo_cache["results"]

    if _demo_cache["status"] == "failed":
        response["error"] = _demo_cache["error"]

    # If running, try to get progress from Redis
    if _demo_cache["status"] in ("seeding", "running") and _demo_cache["job_id"]:
        try:
            redis_client = await get_redis()
            job_data = await redis_client.hgetall(f"job:{_demo_cache['job_id']}")
            if job_data:
                response["stage"] = job_data.get("stage", "initializing")
                response["progress"] = int(job_data.get("progress", 0))
                response["message"] = job_data.get("message", "")
        except Exception:
            pass

    return JSONResponse(content=response)


@router.post("/reset", summary="Reset demo cache")
async def reset_demo(request: Request):
    """
    Clear cached demo results so the next /run triggers a fresh analysis.

    Does NOT delete the demo database (only the cached results).
    """
    global _demo_cache

    if _demo_cache["status"] in ("seeding", "running"):
        raise HTTPException(
            status_code=409,
            detail="Cannot reset while demo is running",
        )

    _demo_cache = {
        "job_id": None,
        "status": "idle",
        "results": None,
        "error": None,
        "started_at": None,
        "completed_at": None,
    }

    return {"status": "reset", "message": "Demo cache cleared"}
