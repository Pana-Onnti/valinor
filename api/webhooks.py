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

logger = structlog.get_logger()

WEBHOOK_SECRET = "valinor_webhook_v1"  # In prod, per-client secret from env/config


async def fire_job_completion_webhook(
    webhook_url: str,
    job_id: str,
    client_name: str,
    status: str,  # "completed" | "failed"
    summary: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Fire a webhook POST to the registered URL.
    Payload is signed with HMAC-SHA256 for verification.
    Returns True if delivered successfully.
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

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, content=payload_json, headers=headers)
            success = response.status_code < 300
            logger.info(
                "Webhook fired",
                url=webhook_url[:40],
                status_code=response.status_code,
                success=success,
                job_id=job_id,
            )
            return success
    except Exception as e:
        logger.warning("Webhook delivery failed", url=webhook_url[:40], error=str(e))
        return False


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

    return {
        "total_findings": len(all_findings),
        "critical_count": critical,
        "high_count": high,
        "dq_score": results.get("data_quality", {}).get("score"),
        "dq_label": results.get("data_quality", {}).get("confidence_label"),
        "period": results.get("period"),
        "run_delta": results.get("run_delta", {}),
    }
