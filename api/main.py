"""
Valinor SaaS API - FastAPI application for MVP.
Provides REST API endpoints for Valinor analysis.
"""

import os
import sys
import uuid
import uuid as _uuid
import json
import asyncio
import re as _re
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field, validator
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import structlog
import redis.asyncio as redis

# Add shared modules to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.valinor_adapter import ValinorAdapter, PipelineExecutor
from shared.storage import MetadataStorage
from api.routes.quality import router as quality_router
from api.routes.onboarding import router as onboarding_router

logger = structlog.get_logger()

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
    patterns = [r'^Q[1-4]-\d{4}$', r'^H[12]-\d{4}$', r'^\d{4}$', r'^[A-Z][a-z]+-\d{4}$']
    if not any(_re.match(p, period) for p in patterns):
        raise ValueError(f"Invalid period format: {period}. Expected: Q1-2025, H1-2025, 2025")
    return period

# Configure FastAPI app
app = FastAPI(
    title="Valinor SaaS API",
    description="Enterprise Analytics API - Transform database insights into business intelligence",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Don't add HSTS in dev since we're on HTTP
        return response

app.add_middleware(SecurityHeadersMiddleware)

# Request ID tracing middleware
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(_uuid.uuid4())[:8])
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIDMiddleware)

# Register routers
app.include_router(quality_router)
app.include_router(onboarding_router)

# Global components
redis_client = None
metadata_storage = MetadataStorage()

# ═══ REQUEST/RESPONSE MODELS ═══

class SSHConfig(BaseModel):
    """SSH tunnel configuration."""
    host: str = Field(..., description="SSH server hostname")
    username: Optional[str] = Field(None, description="SSH username")
    user: Optional[str] = Field(None, description="SSH username (alias)")
    private_key_path: Optional[str] = Field(None, description="Path to SSH private key")
    key: Optional[str] = Field(None, description="SSH private key content")
    port: int = Field(22, description="SSH port")

class DatabaseConfig(BaseModel):
    """Database connection configuration."""
    host: str = Field(..., description="Database hostname")
    port: int = Field(..., description="Database port")
    name: Optional[str] = Field(None, description="Database name")
    database: Optional[str] = Field(None, description="Database name (alias)")
    type: str = Field(..., description="Database type (postgres, mysql, etc.)")
    user: Optional[str] = Field(None, description="Database user")
    password: Optional[str] = Field(None, description="Database password")
    connection_string: Optional[str] = Field(None, description="Full connection string (auto-generated if not provided)")

    def get_db_name(self) -> str:
        return self.name or self.database or ""

    def get_connection_string(self) -> str:
        if self.connection_string:
            return self.connection_string
        db_name = self.get_db_name()
        if self.type in ("postgresql", "postgres"):
            return f"postgresql://{self.user}:{self.password}@{{host}}:{{port}}/{db_name}"
        elif self.type == "mysql":
            return f"mysql://{self.user}:{self.password}@{{host}}:{{port}}/{db_name}"
        elif self.type == "sqlserver":
            return f"mssql+pyodbc://{self.user}:{self.password}@{{host}}:{{port}}/{db_name}"
        return f"{self.type}://{self.user}:{self.password}@{{host}}:{{port}}/{db_name}"

class AnalysisRequest(BaseModel):
    """Request model for starting analysis."""
    client_name: Optional[str] = Field(None, description="Client name for this analysis")
    period: Optional[str] = Field(None, description="Analysis period (Q1-2025, H1-2025, 2025)")
    ssh_config: Optional[SSHConfig] = Field(None, description="SSH tunnel config (optional)")
    db_config: DatabaseConfig
    
    # Optional configuration
    sector: Optional[str] = Field(None, description="Industry sector")
    country: Optional[str] = Field("US", description="Country code")
    currency: Optional[str] = Field("USD", description="Currency code")
    language: Optional[str] = Field("en", description="Language code")
    erp: Optional[str] = Field(None, description="ERP system")
    fiscal_context: Optional[str] = Field("generic", description="Fiscal context")
    overrides: Optional[Dict[str, Any]] = Field({}, description="Configuration overrides")
    
    @validator('period', pre=True, always=True)
    def validate_period(cls, v):
        """Validate period format."""
        if v is None:
            return None
        valid_formats = [
            'Q1-2025', 'Q2-2025', 'Q3-2025', 'Q4-2025',
            'Q1-2026', 'Q2-2026', 'Q3-2026', 'Q4-2026',
            'H1-2025', 'H2-2025', 'H1-2026', 'H2-2026',
            '2025', '2026',
        ]
        if v not in valid_formats:
            # Accept any reasonable period format instead of rejecting
            return v
        return v

class JobStatus(BaseModel):
    """Job status response."""
    job_id: str
    status: str  # pending, running, completed, failed
    stage: Optional[str] = None
    progress: Optional[int] = None
    message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

class AnalysisResults(BaseModel):
    """Analysis results response."""
    job_id: str
    client_name: str
    period: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    execution_time_seconds: Optional[float]
    stages: Dict[str, Any]
    findings: Optional[Dict[str, Any]] = None
    reports: Optional[Dict[str, Any]] = None
    download_urls: Optional[Dict[str, str]] = None

# ═══ STARTUP/SHUTDOWN ═══

@app.on_event("startup")
async def startup_event():
    """Initialize application components."""
    global redis_client
    
    logger.info("Starting Valinor SaaS API...")
    
    try:
        # Initialize Redis connection
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connection established", redis_url=redis_url)
        
        # Test metadata storage
        await metadata_storage.health_check()
        logger.info("Metadata storage initialized")
        
    except Exception as e:
        logger.error("Startup failed", error=str(e))
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global redis_client
    
    logger.info("Shutting down Valinor SaaS API...")
    
    if redis_client:
        await redis_client.close()

# ═══ DEPENDENCY INJECTION ═══

async def get_redis() -> redis.Redis:
    """Get Redis client dependency."""
    global redis_client
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis not available"
        )
    return redis_client

# ═══ API ENDPOINTS ═══

@app.get("/health", summary="Health check")
async def health_check():
    """Service health check endpoint."""
    try:
        # Check Redis
        redis_client = await get_redis()
        await redis_client.ping()
        redis_status = "healthy"
    except:
        redis_status = "unhealthy"
    
    try:
        # Check metadata storage
        await metadata_storage.health_check()
        storage_status = "healthy"
    except:
        storage_status = "unhealthy"
    
    overall_status = "healthy" if all([
        redis_status == "healthy",
        storage_status == "healthy"
    ]) else "unhealthy"
    
    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "redis": redis_status,
            "storage": storage_status
        },
        "version": "1.0.0"
    }

@app.post("/api/analyze", response_model=Dict[str, str], summary="Start analysis")
@limiter.limit("10/minute")
async def start_analysis(
    http_request: Request,
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Start a new Valinor analysis job.

    Returns immediately with job ID. Use /api/jobs/{job_id}/status to track progress.
    """
    # Input validation
    if request.client_name:
        try:
            _validate_client_name(request.client_name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if request.period:
        try:
            _validate_period(request.period)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if request.db_config.port < 1 or request.db_config.port > 65535:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="db_config.port must be between 1 and 65535")
    if request.ssh_config:
        ssh_host = request.ssh_config.host
        if not ssh_host or not _re.match(r'^[a-zA-Z0-9\.\-\_]+$', ssh_host):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ssh_config.host contains invalid characters")

    job_id = str(uuid.uuid4())

    logger.info(
        "Starting analysis",
        job_id=job_id,
        client=request.client_name,
        period=request.period
    )

    try:
        # Store job request in Redis
        client_name = request.client_name or request.db_config.get_db_name() or "unknown"
        period = request.period or "unspecified"
        # Build a sanitized copy of the request for retry support (no passwords)
        request_dict = request.dict()
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
            "request": json.dumps(request.dict()),
            "request_data": json.dumps(safe_request),
        }

        await redis_client.hset(f"job:{job_id}", mapping=job_data)
        await redis_client.expire(f"job:{job_id}", 86400)  # 24 hours
        
        # Queue background task
        background_tasks.add_task(
            run_analysis_task,
            job_id,
            request.dict()
        )
        
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Analysis queued successfully"
        }
        
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

@app.get("/api/jobs/{job_id}/status", response_model=JobStatus, summary="Get job status")
async def get_job_status(
    job_id: str,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get current status of an analysis job.
    """
    try:
        job_data = await redis_client.hgetall(f"job:{job_id}")
        
        if not job_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )
        
        return JobStatus(
            job_id=job_id,
            status=job_data.get("status", "unknown"),
            stage=job_data.get("stage"),
            progress=int(job_data["progress"]) if job_data.get("progress") else None,
            message=job_data.get("message"),
            started_at=datetime.fromisoformat(job_data["started_at"]) if job_data.get("started_at") else None,
            completed_at=datetime.fromisoformat(job_data["completed_at"]) if job_data.get("completed_at") else None,
            error=job_data.get("error")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get job status",
            job_id=job_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job status: {str(e)}"
        )

@app.get("/api/jobs/{job_id}/results", summary="Get job results")
async def get_job_results(
    job_id: str,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get results from completed analysis job.
    """
    try:
        job_data = await redis_client.hgetall(f"job:{job_id}")
        
        if not job_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )
        
        if job_data.get("status") != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job not completed. Current status: {job_data.get('status', 'unknown')}"
            )
        
        # Get results from Redis
        results_key = f"job:{job_id}:results"
        results_data = await redis_client.get(results_key)
        
        if not results_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Results not found"
            )
        
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

        return results
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get job results",
            job_id=job_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job results: {str(e)}"
        )

@app.get("/api/jobs/{job_id}/download/{filename}", summary="Download result file")
async def download_file(job_id: str, filename: str):
    """
    Download specific result file from completed job.
    """
    try:
        # Security: validate filename
        allowed_files = [
            "executive_report.pdf",
            "ceo_report.pdf", 
            "controller_report.pdf",
            "sales_report.pdf",
            "raw_data.json"
        ]
        
        if filename not in allowed_files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid filename"
            )
        
        # Check job exists and is completed
        redis_client = await get_redis()
        job_data = await redis_client.hgetall(f"job:{job_id}")
        
        if not job_data or job_data.get("status") != "completed":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found or not completed"
            )
        
        # Construct file path
        output_dir = Path(f"/tmp/valinor_output/{job_id}")
        file_path = output_dir / filename
        
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found"
            )
        
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type='application/octet-stream'
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to download file",
            job_id=job_id,
            filename=filename,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download file: {str(e)}"
        )

@app.get("/api/jobs", summary="List jobs")
async def list_jobs(
    limit: int = 20,
    status_filter: Optional[str] = None,
):
    """
    List recent analysis jobs with optional status filter.
    Use status_filter=completed|failed|pending|running|cancelled.
    """
    redis_client = await get_redis()

    # Scan for job keys (scan_iter avoids blocking)
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

    # Sort by created_at desc
    jobs.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"jobs": jobs[:limit], "total": len(jobs)}

# ── Client Profile endpoints ──────────────────────────────────────────────────

@app.get("/api/clients/{client_name}/profile")
async def get_client_profile(client_name: str):
    """
    Get the persistent ClientProfile for a client.
    Used by the history dashboard.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")
    return profile.to_dict()


@app.get("/api/clients")
async def list_clients():
    """
    List all clients that have profiles.
    """
    import sys, os, glob, json

    # Try local files first
    profile_dir = "/tmp/valinor_profiles"
    os.makedirs(profile_dir, exist_ok=True)

    clients = []
    for path in glob.glob(os.path.join(profile_dir, "*.json")):
        try:
            data = json.loads(open(path).read())
            clients.append({
                "client_name": data.get("client_name"),
                "run_count": data.get("run_count", 0),
                "last_run_date": data.get("last_run_date"),
                "known_findings_count": len(data.get("known_findings", {})),
            })
        except Exception:
            pass

    return {"clients": clients}


@app.put("/api/clients/{client_name}/profile/false-positive")
async def mark_false_positive(client_name: str, finding_id: str):
    """
    Mark a finding as a false positive for this client.
    It will be suppressed in future runs.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    if finding_id not in profile.false_positives:
        profile.false_positives.append(finding_id)

    # Also add to suppress list in refinement
    if profile.refinement is None:
        profile.refinement = {}
    suppress = profile.refinement.get("suppress_ids", [])
    if finding_id not in suppress:
        suppress.append(finding_id)
    profile.refinement["suppress_ids"] = suppress

    await store.save(profile)
    return {"status": "ok", "finding_id": finding_id, "client": client_name}


@app.delete("/api/clients/{client_name}/profile")
async def reset_client_profile(client_name: str):
    """
    Reset (delete) a client's profile.
    Useful when the client's database schema changes significantly.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store
    from shared.memory.client_profile import ClientProfile

    store = get_profile_store()
    # Create a blank profile (reset)
    blank = ClientProfile.new(client_name)
    await store.save(blank)
    return {"status": "reset", "client": client_name}


@app.get("/api/clients/{client_name}/dq-history")
async def get_client_dq_history(client_name: str):
    """Get historical DQ scores for a client."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")

    dq_history = getattr(profile, 'dq_history', []) or profile.__dict__.get('dq_history', [])

    avg_score = sum(r["score"] for r in dq_history) / len(dq_history) if dq_history else None
    trend = None
    if len(dq_history) >= 2:
        recent = dq_history[-3:]
        early = dq_history[:-3] if len(dq_history) > 3 else dq_history[:1]
        recent_avg = sum(r["score"] for r in recent) / len(recent)
        early_avg = sum(r["score"] for r in early) / len(early)
        if recent_avg > early_avg + 2:
            trend = "improving"
        elif recent_avg < early_avg - 2:
            trend = "declining"
        else:
            trend = "stable"

    return {
        "client": client_name,
        "dq_history": dq_history,
        "avg_score": round(avg_score, 1) if avg_score else None,
        "trend": trend,
        "runs_with_dq": len(dq_history),
    }


@app.get("/api/clients/{client_name}/stats")
async def get_client_stats(client_name: str):
    """
    Get summary statistics for a client.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for: {client_name}")

    # Compute trend for findings count
    run_history = profile.run_history[-10:]
    findings_trend = [r.get("findings_count", 0) for r in run_history]
    trend_direction = "stable"
    if len(findings_trend) >= 2:
        if findings_trend[-1] > findings_trend[0]:
            trend_direction = "increasing"
        elif findings_trend[-1] < findings_trend[0]:
            trend_direction = "decreasing"

    # Average resolution time
    resolved = list(profile.resolved_findings.values())

    return {
        "client_name": client_name,
        "run_count": profile.run_count,
        "last_run_date": profile.last_run_date,
        "industry": profile.industry_inferred,
        "currency": profile.currency_detected,
        "active_findings": len(profile.known_findings),
        "resolved_findings": len(profile.resolved_findings),
        "critical_active": sum(
            1 for r in profile.known_findings.values()
            if r.get("severity", "") == "CRITICAL"
        ),
        "avg_runs_open": round(
            sum(r.get("runs_open", 1) for r in profile.known_findings.values()) /
            max(len(profile.known_findings), 1), 1
        ),
        "findings_trend": trend_direction,
        "kpi_count": len(profile.baseline_history),
        "focus_tables": profile.focus_tables[:5],
        "refinement_ready": profile.refinement is not None,
        "entity_cache_fresh": profile.is_entity_map_fresh(),
    }


# ── PDF Export ───────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/pdf")
@limiter.limit("30/minute")
async def download_report_pdf(request: Request, job_id: str):
    """
    Generate and return a branded PDF for a completed analysis job.
    """
    from fastapi.responses import Response
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    # Load results from Redis
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    results_raw = await redis_client.get(f"job:{job_id}:results")
    if not results_raw:
        raise HTTPException(status_code=404, detail="Job results not found")

    import json as _json
    results = _json.loads(results_raw)

    reports = results.get("reports", {})
    executive_report = reports.get("executive", "")
    if not executive_report:
        raise HTTPException(status_code=404, detail="No executive report found")

    client_name = results.get("client_name", "Cliente")
    period = results.get("period", "")
    run_delta = results.get("run_delta", {})

    # Build findings summary
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


# ── Alert Thresholds ──────────────────────────────────────────────────────────

@app.get("/api/clients/{client_name}/alerts")
async def get_client_alerts(client_name: str):
    """Get alert thresholds and recent triggers for a client."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found")

    return {
        "client_name": client_name,
        "thresholds": profile.alert_thresholds,
        "triggered_alerts": (profile.triggered_alerts or [])[-10:],
    }


@app.post("/api/clients/{client_name}/alerts")
async def add_alert_threshold(client_name: str, threshold: dict):
    """
    Add an alert threshold for a client.
    Body: {"label": "Alerta cobranza", "metric": "Cobranza Pendiente", "operator": ">", "value": 1000000}
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    required = ["label", "metric", "operator", "value"]
    if not all(k in threshold for k in required):
        raise HTTPException(status_code=400, detail=f"Required fields: {required}")

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    # Avoid duplicates
    existing = [t for t in profile.alert_thresholds if t.get("label") == threshold["label"]]
    if existing:
        # Update existing
        for t in profile.alert_thresholds:
            if t.get("label") == threshold["label"]:
                t.update(threshold)
    else:
        profile.alert_thresholds.append({**threshold, "triggered": False, "created_at": datetime.utcnow().isoformat()})

    await store.save(profile)
    return {"status": "ok", "thresholds_count": len(profile.alert_thresholds)}


@app.delete("/api/clients/{client_name}/alerts/{alert_label}")
async def delete_alert_threshold(client_name: str, alert_label: str):
    """Remove an alert threshold."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load_or_create(client_name)
    profile.alert_thresholds = [t for t in profile.alert_thresholds if t.get("label") != alert_label]
    await store.save(profile)
    return {"status": "deleted"}


# ── Email Digest ──────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/digest")
async def preview_email_digest(job_id: str):
    """Preview HTML email digest for a completed job."""
    from fastapi.responses import HTMLResponse
    import sys, os, json as _json
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    results_raw = await redis_client.get(f"job:{job_id}:results")
    if not results_raw:
        raise HTTPException(status_code=404, detail="Job results not found")

    results = _json.loads(results_raw)
    run_delta = results.get("run_delta", {})
    findings = results.get("findings", {})
    client_name = results.get("client_name", "Cliente")
    period = results.get("period", "")

    # Build top findings list
    top_findings = []
    for agent_result in findings.values():
        if isinstance(agent_result, dict):
            top_findings.extend(agent_result.get("findings", []))
    top_findings.sort(key=lambda f: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(f.get("severity","").upper(), 4))

    findings_summary = {
        "critical": sum(1 for f in top_findings if f.get("severity","").upper() == "CRITICAL"),
        "high": sum(1 for f in top_findings if f.get("severity","").upper() == "HIGH"),
    }

    from api.email_digest import build_digest_html
    html = build_digest_html(
        client_name=client_name,
        period=period,
        run_delta=run_delta,
        findings_summary=findings_summary,
        top_findings=top_findings[:5],
    )
    return HTMLResponse(content=html)


@app.post("/api/jobs/{job_id}/send-digest")
async def send_email_digest(job_id: str, to_email: str):
    """Send email digest to specified address."""
    import sys, os, json as _json
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    results_raw = await redis_client.get(f"job:{job_id}:results")
    if not results_raw:
        raise HTTPException(status_code=404, detail="Job not found")

    results = _json.loads(results_raw)
    client_name = results.get("client_name", "Cliente")
    period = results.get("period", "")

    from api.email_digest import build_digest_html, send_digest
    html = build_digest_html(
        client_name=client_name,
        period=period,
        run_delta=results.get("run_delta", {}),
        findings_summary={},
        top_findings=[],
    )
    sent = await send_digest(
        to_email=to_email,
        subject=f"Valinor — {client_name} — {period} — Análisis completado",
        html_content=html,
    )
    return {"status": "sent" if sent else "smtp_not_configured", "to": to_email}


@app.get("/api/jobs/{job_id}/quality")
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


@app.post("/api/clients/{client_name}/webhooks")
async def register_webhook(client_name: str, body: dict):
    """Register a webhook URL for a client."""
    from shared.memory.profile_store import get_profile_store
    webhook_url = body.get("url")
    if not webhook_url or not webhook_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Valid webhook URL required")

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    if not hasattr(profile, '__dict__'):
        raise HTTPException(status_code=500, detail="Profile error")

    # Store webhook in profile (as extra field)
    webhooks = profile.__dict__.get('_webhooks', [])
    existing = [w for w in webhooks if w.get("url") != webhook_url]
    existing.append({"url": webhook_url, "registered_at": datetime.utcnow().isoformat(), "active": True})
    profile.__dict__['_webhooks'] = existing[-5:]  # max 5 webhooks

    await store.save(profile)
    return {"status": "registered", "url": webhook_url, "client": client_name}


@app.get("/api/clients/{client_name}/webhooks")
async def list_webhooks(client_name: str):
    """List registered webhooks for a client."""
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")
    webhooks = profile.__dict__.get('_webhooks', [])
    return {"client": client_name, "webhooks": webhooks}


@app.delete("/api/clients/{client_name}/webhooks")
async def delete_webhook(client_name: str, url: str):
    """Remove a webhook."""
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")
    webhooks = [w for w in profile.__dict__.get('_webhooks', []) if w.get("url") != url]
    profile.__dict__['_webhooks'] = webhooks
    await store.save(profile)
    return {"status": "removed", "remaining": len(webhooks)}


@app.get("/api/clients/{client_name}/segmentation")
async def get_client_segmentation(client_name: str):
    """Get latest customer segmentation for a client."""
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")

    history = getattr(profile, "segmentation_history", []) or profile.__dict__.get("segmentation_history", [])
    if not history:
        return {"client": client_name, "segmentation": None, "message": "No segmentation data yet"}

    latest = history[-1]
    return {
        "client": client_name,
        "computed_at": latest.get("computed_at"),
        "total_customers": latest.get("total_customers"),
        "total_revenue": latest.get("total_revenue"),
        "segments": latest.get("segments", {}),
        "history_count": len(history),
    }


# ═══ JOB LIFECYCLE MANAGEMENT ═══

@app.post("/api/jobs/{job_id}/cancel")
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


@app.post("/api/jobs/{job_id}/retry")
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

    # Create new job
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


@app.delete("/api/jobs/cleanup")
async def cleanup_old_jobs(older_than_days: int = 7):
    """Delete completed/failed jobs older than N days."""
    from datetime import timedelta
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


# ═══ BACKGROUND TASKS ═══

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
    """
    Background task to run Valinor analysis.
    """
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
                webhooks = profile.__dict__.get('_webhooks', [])
                for webhook in webhooks:
                    if webhook.get("active") and webhook.get("url"):
                        summary = build_job_summary(results)
                        asyncio.create_task(fire_job_completion_webhook(
                            webhook["url"], job_id, client_name, "completed", summary
                        ))
        except Exception as _wh_err:
            logger.warning("Webhook setup failed", error=str(_wh_err))

    except Exception as e:
        logger.error(
            "Analysis failed",
            job_id=job_id,
            error=str(e)
        )

        if redis_client:
            try:
                await redis_client.hset(f"job:{job_id}", mapping={
                    "status": "failed",
                    "error": str(e),
                    "failed_at": datetime.utcnow().isoformat()
                })
            except:
                pass  # Don't fail on status update error

        # Fire failure webhooks if registered
        try:
            from api.webhooks import fire_job_completion_webhook
            from shared.memory.profile_store import get_profile_store

            client_name = request_data.get("client_name", "unknown")
            store = get_profile_store()
            profile = await store.load(client_name)
            if profile:
                webhooks = profile.__dict__.get('_webhooks', [])
                for webhook in webhooks:
                    if webhook.get("active") and webhook.get("url"):
                        asyncio.create_task(fire_job_completion_webhook(
                            webhook["url"], job_id, client_name, "failed", {}
                        ))
        except Exception as _wh_err:
            logger.warning("Webhook setup failed (failure path)", error=str(_wh_err))

# ═══ MAIN ═══

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )