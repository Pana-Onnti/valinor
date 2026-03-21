"""
Webhook manager — fires HTTP callbacks when analysis jobs complete.
Clients can register webhook URLs to receive instant notifications.
"""
from __future__ import annotations
import asyncio
import json
import hmac
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any
import httpx
import structlog

# Delays (in seconds) between retry attempts: attempt 1→2, attempt 2→3, attempt 3→give up
RETRY_DELAYS = [1, 5, 15]
MAX_ATTEMPTS = 3

logger = structlog.get_logger()

WEBHOOK_SECRET = "valinor_webhook_v1"  # In prod, per-client secret from env/config


async def fire_job_completion_webhook(
    webhook_url: str,
    job_id: str,
    client_name: str,
    status: str,  # "completed" | "failed"
    summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Fire a webhook POST to the registered URL with exponential backoff retries.
    Payload is signed with HMAC-SHA256 for verification.

    Returns a dict: {"success": bool, "attempts": int, "last_status_code": int | None}
    Retries up to MAX_ATTEMPTS times with delays defined in RETRY_DELAYS.
    """
    payload = {
        "event": "job.completed" if status == "completed" else "job.failed",
        "job_id": job_id,
        "client_name": client_name,
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
        "summary": summary or {},
    }

    payload_json = json.dumps(payload, ensure_ascii=False)
    signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload_json.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Valinor-Signature": f"sha256={signature}",
        "X-Valinor-Event": payload["event"],
        "User-Agent": "Valinor-Webhooks/1.0",
    }

    last_status_code: Optional[int] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, content=payload_json, headers=headers)
                last_status_code = response.status_code
                success = response.status_code < 300
                logger.info(
                    "Webhook fired",
                    url=webhook_url[:40],
                    status_code=response.status_code,
                    success=success,
                    job_id=job_id,
                    attempt=attempt,
                )
                if success:
                    return {"success": True, "attempts": attempt, "last_status_code": last_status_code}
        except Exception as e:
            logger.warning(
                "Webhook delivery failed",
                url=webhook_url[:40],
                error=str(e),
                attempt=attempt,
                job_id=job_id,
            )

        if attempt < MAX_ATTEMPTS:
            delay = RETRY_DELAYS[attempt - 1]
            logger.info(
                "Webhook retry scheduled",
                url=webhook_url[:40],
                next_attempt=attempt + 1,
                delay_seconds=delay,
                job_id=job_id,
            )
            await asyncio.sleep(delay)

    logger.error(
        "Webhook delivery exhausted all attempts",
        url=webhook_url[:40],
        attempts=MAX_ATTEMPTS,
        last_status_code=last_status_code,
        job_id=job_id,
    )
    return {"success": False, "attempts": MAX_ATTEMPTS, "last_status_code": last_status_code}


def build_job_summary(results: dict) -> dict:
    """Extract key metrics for webhook payload."""
    findings = results.get("findings", {})
    all_findings = []
    for agent_results in findings.values():
        if isinstance(agent_results, list):
            all_findings.extend(agent_results)
        elif isinstance(agent_results, dict):
            all_findings.extend(agent_results.get("findings", []))

    critical = sum(1 for f in all_findings if isinstance(f, dict) and f.get("severity") == "CRITICAL")
    high = sum(1 for f in all_findings if isinstance(f, dict) and f.get("severity") == "HIGH")

    triggered_alerts = results.get("triggered_alerts", [])

    return {
        "total_findings": len(all_findings),
        "critical_count": critical,
        "high_count": high,
        "dq_score": results.get("data_quality", {}).get("score"),
        "dq_label": results.get("data_quality", {}).get("confidence_label"),
        "period": results.get("period"),
        "run_delta": results.get("run_delta", {}),
        "triggered_alerts": len(triggered_alerts),
        "alert_labels": [a.get("threshold_label") for a in triggered_alerts[:5]],
    }
