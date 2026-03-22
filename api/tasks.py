"""
Valinor SaaS API — Background tasks for analysis execution.

Extracted from main.py for better modularity.
"""

import json
import asyncio
from typing import Dict, Any
from datetime import datetime

import structlog

from api.deps import get_redis
from adapters.valinor_adapter import ValinorAdapter

logger = structlog.get_logger()


async def progress_callback(job_id: str, stage: str, progress: int, message: str):
    """Progress callback for analysis jobs."""
    try:
        redis_client = await get_redis()

        await redis_client.hset(f"job:{job_id}", mapping={
            "status": "running",
            "stage": stage,
            "progress": progress,
            "message": message,
            "updated_at": datetime.utcnow().isoformat()
        })

        logger.info(
            "Analysis progress",
            job_id=job_id,
            stage=stage,
            progress=progress,
            message=message
        )

    except Exception as e:
        logger.warning(
            "Failed to update progress",
            job_id=job_id,
            error=str(e)
        )


async def run_analysis_task(job_id: str, request_data: Dict[str, Any]):
    """Background task to run Valinor analysis."""
    redis_client = None

    try:
        redis_client = await get_redis()

        # Update job status
        await redis_client.hset(f"job:{job_id}", mapping={
            "status": "running",
            "started_at": datetime.utcnow().isoformat()
        })

        # Create adapter with progress callback
        adapter = ValinorAdapter(
            progress_callback=lambda stage, progress, message:
                progress_callback(job_id, stage, progress, message)
        )

        # Prepare connection config
        connection_config = {
            "ssh_config": request_data["ssh_config"],
            "db_config": request_data["db_config"],
            "sector": request_data.get("sector"),
            "country": request_data.get("country", "US"),
            "currency": request_data.get("currency", "USD"),
            "language": request_data.get("language", "en"),
            "erp": request_data.get("erp"),
            "fiscal_context": request_data.get("fiscal_context", "generic"),
            "overrides": request_data.get("overrides", {})
        }

        db_cfg = request_data.get("db_config") or {}
        default_client = db_cfg.get("name") or db_cfg.get("database") or "unknown"
        default_period = "Q1-2026"

        # Run analysis
        results = await adapter.run_analysis(
            job_id=job_id,
            client_name=request_data.get("client_name") or default_client,
            connection_config=connection_config,
            period=request_data.get("period") or default_period
        )

        # Ensure run_delta is present at the top level of results
        if "run_delta" not in results and isinstance(results.get("stages"), dict):
            results["run_delta"] = results["stages"].get("run_delta")

        # Store results in Redis
        await redis_client.set(
            f"job:{job_id}:results",
            json.dumps(results, default=str),
            ex=86400  # 24 hours
        )

        # Update job status
        await redis_client.hset(f"job:{job_id}", mapping={
            "status": "completed",
            "completed_at": datetime.utcnow().isoformat(),
            "message": "Analysis completed successfully"
        })

        logger.info(
            "Analysis completed successfully",
            job_id=job_id,
            client=request_data["client_name"]
        )

        # Fire webhooks if registered
        try:
            from api.webhooks import fire_job_completion_webhook, build_job_summary
            from shared.memory.profile_store import get_profile_store

            client_name = request_data.get("client_name", "unknown")
            store = get_profile_store()
            profile = await store.load(client_name)
            if profile:
                for webhook in profile.webhooks:
                    if webhook.get("active") and webhook.get("url"):
                        summary = build_job_summary(results)
                        asyncio.create_task(fire_job_completion_webhook(
                            webhook["url"], job_id, client_name, "completed", summary
                        ))
        except Exception as _wh_err:
            logger.warning("Webhook setup failed", error=str(_wh_err))

    except Exception as e:
        import re as _re2
        error_msg = str(e)
        is_dq_halt = error_msg.startswith("Data quality gate HALT:")

        logger.error(
            "Analysis failed",
            job_id=job_id,
            error=error_msg,
            dq_halt=is_dq_halt,
        )

        if redis_client:
            try:
                if is_dq_halt:
                    _score_match = _re2.search(r'score=(\d+(?:\.\d+)?)/100', error_msg)
                    _dq_score = float(_score_match.group(1)) if _score_match else None
                    _issues_part = error_msg.split("Issues: ", 1)
                    _fatal_checks = [i.strip() for i in _issues_part[1].split("; ")] if len(_issues_part) > 1 else []
                    dq_halt_payload = json.dumps({
                        "error": "data_quality_halt",
                        "dq_score": _dq_score,
                        "fatal_checks": _fatal_checks,
                        "message": f"Analysis blocked by Data Quality Gate (score={_dq_score}/100). Resolve the listed issues and retry.",
                    })
                    await redis_client.hset(f"job:{job_id}", mapping={
                        "status": "failed",
                        "error": error_msg,
                        "error_code": "data_quality_halt",
                        "error_detail": dq_halt_payload,
                        "failed_at": datetime.utcnow().isoformat(),
                    })
                else:
                    await redis_client.hset(f"job:{job_id}", mapping={
                        "status": "failed",
                        "error": error_msg,
                        "failed_at": datetime.utcnow().isoformat(),
                    })
            except Exception:
                pass  # Don't fail on status update error

        # Fire failure webhooks if registered
        try:
            from api.webhooks import fire_job_completion_webhook
            from shared.memory.profile_store import get_profile_store

            client_name = request_data.get("client_name", "unknown")
            store = get_profile_store()
            profile = await store.load(client_name)
            if profile:
                for webhook in profile.webhooks:
                    if webhook.get("active") and webhook.get("url"):
                        asyncio.create_task(fire_job_completion_webhook(
                            webhook["url"], job_id, client_name, "failed", {}
                        ))
        except Exception as _wh_err:
            logger.warning("Webhook setup failed (failure path)", error=str(_wh_err))
