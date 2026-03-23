"""
Reports router — PDF export, email digest, and quality report endpoints.

Extracted from main.py for better modularity.
"""

import json
from datetime import datetime  # noqa: F401

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse
import structlog
import redis.asyncio as redis

from api.deps import get_redis

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["Reports"])


@router.get("/jobs/{job_id}/export/pdf", summary="Export job results as PDF", tags=["Jobs"])
async def export_job_pdf(
    request: Request,
    job_id: str,
    redis_client: redis.Redis = Depends(get_redis),
):
    """Generate and download a PDF report for a completed analysis job."""
    from fastapi.responses import Response as _Response

    from shared.pdf_generator import generate_pdf_report

    try:
        job_data = await redis_client.hgetall(f"job:{job_id}")

        if not job_data:
            raise HTTPException(status_code=404, detail="Job not found")

        job_status = job_data.get("status", "unknown")
        if job_status != "completed":
            raise HTTPException(status_code=400, detail=f"Job not completed. Current status: {job_status}")

        results_raw = await redis_client.get(f"job:{job_id}:results")
        if results_raw:
            results = json.loads(results_raw)
        else:
            results = {
                "job_id": job_id,
                "client_name": job_data.get("client_name", "N/A"),
                "period": job_data.get("period", "N/A"),
                "status": job_status,
                "execution_time_seconds": None,
                "timestamp": job_data.get("completed_at", job_data.get("created_at")),
            }

        pdf_bytes = generate_pdf_report(results)

        client_name = results.get("client_name", "report")
        period = results.get("period", "")
        filename = f"valinor_{client_name}_{period}.pdf".replace(" ", "_")

        return _Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to export PDF", job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")


@router.get("/jobs/{job_id}/pdf", tags=["Reports"])
async def download_report_pdf(request: Request, job_id: str):
    """Generate and return a branded PDF for a completed analysis job."""
    from fastapi.responses import Response

    redis_client = await get_redis()
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    results_raw = await redis_client.get(f"job:{job_id}:results")
    if not results_raw:
        raise HTTPException(status_code=404, detail="Job results not found")

    results = json.loads(results_raw)

    reports = results.get("reports", {})
    executive_report = reports.get("executive", "")
    if not executive_report:
        raise HTTPException(status_code=404, detail="No executive report found")

    client_name = results.get("client_name", "Cliente")
    period = results.get("period", "")
    run_delta = results.get("run_delta", {})

    findings = results.get("findings", {})
    findings_summary = {
        "critical": sum(
            1 for af in findings.values() if isinstance(af, dict)
            for f in af.get("findings", []) if f.get("severity", "").upper() == "CRITICAL"
        ),
        "high": sum(
            1 for af in findings.values() if isinstance(af, dict)
            for f in af.get("findings", []) if f.get("severity", "").upper() == "HIGH"
        ),
        "medium": sum(
            1 for af in findings.values() if isinstance(af, dict)
            for f in af.get("findings", []) if f.get("severity", "").upper() == "MEDIUM"
        ),
        "new": len(run_delta.get("new", [])),
        "resolved": len(run_delta.get("resolved", [])),
    }

    try:
        from api.pdf_generator import BrandedPDFGenerator
        pdf_bytes = BrandedPDFGenerator().generate(
            report_markdown=executive_report,
            client_name=client_name,
            period=period,
            run_delta=run_delta,
            findings_summary=findings_summary,
            results=results,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    filename = f"valinor_{client_name}_{period}.pdf".replace(" ", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/jobs/{job_id}/quality", tags=["Quality"])
async def get_job_quality_report(job_id: str):
    """Get the Data Quality Gate report for a completed job."""
    redis_client = await get_redis()
    results_raw = await redis_client.get(f"job:{job_id}:results")
    if not results_raw:
        raise HTTPException(status_code=404, detail="Job results not found")
    results = json.loads(results_raw)
    dq = results.get("data_quality")
    if not dq:
        return {"job_id": job_id, "data_quality": None, "message": "No DQ report (pre-gate job)"}
    return {
        "job_id": job_id,
        "data_quality": dq,
        "currency_warnings": results.get("currency_warnings", {}),
        "snapshot_timestamp": results.get("stages", {}).get("query_execution", {}).get("snapshot_timestamp"),
    }


# ── Email Digest ──────────────────────────────────────────────────────────────

def _build_findings_list(findings: dict) -> list:
    """Build a sorted list of findings from agent results."""
    top_findings = []
    for agent_result in findings.values():
        if isinstance(agent_result, dict):
            top_findings.extend(agent_result.get("findings", []))
    top_findings.sort(key=lambda f: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(f.get("severity", "").upper(), 4))
    return top_findings


@router.get("/jobs/{job_id}/digest")
async def preview_email_digest(job_id: str):
    """Preview HTML email digest for a completed job."""
    redis_client = await get_redis()
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    results_raw = await redis_client.get(f"job:{job_id}:results")
    if not results_raw:
        raise HTTPException(status_code=404, detail="Job results not found")

    results = json.loads(results_raw)
    run_delta = results.get("run_delta", {})
    findings = results.get("findings", {})
    client_name = results.get("client_name", "Cliente")
    period = results.get("period", "")

    top_findings = _build_findings_list(findings)

    findings_summary = {
        "critical": sum(1 for f in top_findings if f.get("severity", "").upper() == "CRITICAL"),
        "high": sum(1 for f in top_findings if f.get("severity", "").upper() == "HIGH"),
    }

    data_quality = results.get("data_quality")
    triggered_alerts = results.get("triggered_alerts")

    from api.email_digest import build_digest_html
    html = build_digest_html(
        client_name=client_name,
        period=period,
        run_delta=run_delta,
        findings_summary=findings_summary,
        top_findings=top_findings[:5],
        triggered_alerts=triggered_alerts,
        data_quality=data_quality,
    )
    return HTMLResponse(content=html)


@router.post("/jobs/{job_id}/send-digest")
async def send_email_digest(job_id: str, to_email: str):
    """Send email digest to specified address."""
    redis_client = await get_redis()
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    results_raw = await redis_client.get(f"job:{job_id}:results")
    if not results_raw:
        raise HTTPException(status_code=404, detail="Job not found")

    results = json.loads(results_raw)
    client_name = results.get("client_name", "Cliente")
    period = results.get("period", "")
    run_delta = results.get("run_delta", {})
    findings = results.get("findings", {})
    data_quality = results.get("data_quality")
    triggered_alerts = results.get("triggered_alerts")

    top_findings = _build_findings_list(findings)

    findings_summary = {
        "critical": sum(1 for f in top_findings if f.get("severity", "").upper() == "CRITICAL"),
        "high": sum(1 for f in top_findings if f.get("severity", "").upper() == "HIGH"),
    }

    from api.email_digest import build_digest_html, send_digest
    html = build_digest_html(
        client_name=client_name,
        period=period,
        run_delta=run_delta,
        findings_summary=findings_summary,
        top_findings=top_findings[:5],
        triggered_alerts=triggered_alerts,
        data_quality=data_quality,
    )
    sent = await send_digest(
        to_email=to_email,
        subject=f"Valinor \u2014 {client_name} \u2014 {period} \u2014 Analisis completado",
        html_content=html,
    )
    return {"status": "sent" if sent else "smtp_not_configured", "to": to_email}
