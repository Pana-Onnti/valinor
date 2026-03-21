"""
Valinor SaaS API - FastAPI application for MVP.
Provides REST API endpoints for Valinor analysis.
"""

import os
import sys
import uuid
import uuid as _uuid
import json
import time
import asyncio
import re as _re
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
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

# ═══ IN-MEMORY LRU CACHE FOR COMPLETED JOB RESULTS ═══
# Keyed by job_id → (results_dict, cached_at_timestamp)
_results_cache: dict[str, tuple[dict, float]] = {}
_RESULTS_CACHE_TTL = 300  # seconds (5 minutes)

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
    description="""
## Valinor — AI-Powered Business Intelligence

Analiza cualquier base de datos empresarial y genera reportes ejecutivos en 15 minutos.

### Arquitectura
- **Zero Data Storage** — solo metadata y resultados agregados
- **Multi-agent pipeline**: Cartographer → DataQualityGate → QueryBuilder → Analysts → Narrators
- **Calidad institucional**: 9 controles de datos antes de cada análisis

### Flujo típico
1. `POST /api/analyze` — inicia análisis (devuelve job_id)
2. `GET /api/jobs/{id}/stream` — SSE para progreso en tiempo real
3. `GET /api/jobs/{id}/results` — resultados completos
4. `GET /api/jobs/{id}/pdf` — reporte PDF con marca Valinor
5. `GET /api/jobs/{id}/quality` — reporte de calidad de datos

### Metodología de calidad de datos
Implementa estándares de: Renaissance Technologies, Bloomberg Terminal, ECB, Big 4 Audit
- Ecuación contable (Activos = Pasivos + Capital)
- Reconciliación 3 rutas de revenue
- Ley de Benford
- Descomposición STL estacional
- Cointegración Engle-Granger
    """,
    version="2.0.0",
    contact={"name": "Delta 4C", "email": "hola@delta4c.com"},
    license_info={"name": "Proprietary"},
    docs_url="/docs",
    redoc_url="/redoc",
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
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIDMiddleware)

# ═══ GLOBAL EXCEPTION HANDLERS ═══

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    request_id = getattr(request.state, "request_id", None)
    body = {"error": "not_found", "path": request.url.path}
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=404, content=body)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        "Unhandled exception",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    body = {
        "error": "internal_error",
        "message": "An unexpected error occurred",
    }
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=500, content=body)

from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    errors = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err.get("loc", []))
        errors.append({"field": field, "message": err.get("msg"), "type": err.get("type")})
    body = {
        "error": "validation_error",
        "message": "Request validation failed",
        "details": errors,
    }
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=422, content=body)

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
    error_detail: Optional[Dict[str, Any]] = None  # structured detail for DQ HALT and similar

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
        "version": "2.0.0"
    }

@app.post("/api/analyze", response_model=Dict[str, str], summary="Start analysis", tags=["Analysis"])
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

        # Per-client concurrent job limit: max 2 running jobs per client_name
        running_count = 0
        async for key in redis_client.scan_iter("job:*"):
            job_status_val = await redis_client.hget(key, "status")
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

@app.get("/api/jobs/{job_id}/status", response_model=JobStatus, summary="Get job status", tags=["Jobs"])
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
        
        error_detail = None
        if job_data.get("error_detail"):
            try:
                error_detail = json.loads(job_data["error_detail"])
            except Exception:
                pass

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

@app.get("/api/jobs/{job_id}/stream", summary="Stream job progress via SSE")
async def stream_job_progress(job_id: str):
    """
    Server-Sent Events stream for real-time job progress.
    Client subscribes and receives events as the job progresses.
    Automatically closes when job completes or fails.
    """
    async def event_generator():
        last_stage = None
        last_progress = -1
        consecutive_polls = 0
        max_polls = 360  # 30 minutes max at 5s interval

        while consecutive_polls < max_polls:
            try:
                r = await get_redis()
                job_data = await r.hgetall(f"job:{job_id}")

                if not job_data:
                    yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                    break

                current_status = job_data.get("status", "unknown")
                current_stage = job_data.get("stage", "")
                current_progress = job_data.get("progress", "0")
                current_message = job_data.get("message", "")

                # Only yield if something changed
                if current_stage != last_stage or current_progress != last_progress:
                    event_data = {
                        "job_id": job_id,
                        "status": current_status,
                        "stage": current_stage,
                        "progress": int(current_progress) if current_progress else 0,
                        "message": current_message,
                        "timestamp": datetime.utcnow().isoformat(),
                    }

                    # Add DQ score when available
                    if current_stage == "data_quality" or current_status == "completed":
                        try:
                            results_raw = await r.get(f"job:{job_id}:results")
                            if results_raw:
                                results = json.loads(results_raw)
                                dq = results.get("data_quality")
                                if dq:
                                    event_data["dq_score"] = dq.get("score")
                                    event_data["dq_label"] = dq.get("confidence_label")
                        except Exception:
                            pass

                    yield f"data: {json.dumps(event_data)}\n\n"
                    last_stage = current_stage
                    last_progress = current_progress

                # Terminal states — close stream
                if current_status in ("completed", "failed", "cancelled"):
                    final_event = {
                        "job_id": job_id,
                        "status": current_status,
                        "stage": "done",
                        "progress": 100 if current_status == "completed" else 0,
                        "message": "Análisis completado" if current_status == "completed" else "Error en análisis",
                        "final": True,
                    }
                    yield f"data: {json.dumps(final_event)}\n\n"
                    break

                consecutive_polls += 1
                await asyncio.sleep(2)  # Poll Redis every 2 seconds

            except asyncio.CancelledError:
                break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break

        yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@app.get("/api/jobs/{job_id}/results", summary="Get job results", tags=["Jobs"])
async def get_job_results(
    job_id: str,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Get results from completed analysis job.
    """
    try:
        # ── Cache hit: return without touching Redis ──────────────────────
        now = time.time()
        cached = _results_cache.get(job_id)
        if cached is not None:
            cached_results, cached_at = cached
            if now - cached_at <= _RESULTS_CACHE_TTL:
                return cached_results

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

        # ── Store in cache for subsequent requests ────────────────────────
        _results_cache[job_id] = (results, time.time())

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


@app.get("/api/cache/stats", summary="In-memory results cache statistics", tags=["Observability"])
async def get_cache_stats():
    """
    Return observability metrics for the in-memory completed-job results cache.
    """
    now = time.time()
    # Evict stale entries so counts reflect only live entries
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

_VALID_SORT_FIELDS = {"created_at", "status", "client_name"}

@app.get("/api/jobs", summary="List jobs")
async def list_jobs(
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    """
    List analysis jobs with pagination, sorting and optional status filter.

    - **page**: 1-based page number (default 1)
    - **page_size**: items per page, max 100 (default 20)
    - **status_filter**: filter by status — completed|failed|pending|running|cancelled
    - **sort_by**: field to sort by — created_at|status|client_name (default created_at)
    - **sort_order**: asc or desc (default desc)
    """
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

    # Sort by requested field
    reverse = sort_order == "desc"
    jobs.sort(key=lambda x: x.get(sort_by) or "", reverse=reverse)

    total = len(jobs)
    import math
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

# ── Client Profile endpoints ──────────────────────────────────────────────────

@app.get("/api/clients/{client_name}/profile", tags=["Clients"])
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


@app.get("/api/clients/{client_name}/profile/export", tags=["Clients"])
async def export_client_profile(client_name: str):
    """
    Export the full ClientProfile as a downloadable JSON file.
    Returns Content-Disposition: attachment so browsers trigger a download.
    """
    import sys, os, json as _json
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store
    from fastapi.responses import Response

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    payload = _json.dumps(profile.to_dict(), indent=2, ensure_ascii=False)
    filename = f"{client_name}_profile.json"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/clients/{client_name}/profile/import", tags=["Clients"])
async def import_client_profile(client_name: str, body: dict):
    """
    Import (overwrite) a ClientProfile from a JSON body.
    The body must contain a `client_name` field that matches the URL parameter.
    Returns 400 if the names do not match.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store
    from shared.memory.client_profile import ClientProfile

    if body.get("client_name") != client_name:
        raise HTTPException(
            status_code=400,
            detail=f"client_name in body ('{body.get('client_name')}') does not match URL parameter ('{client_name}')",
        )

    store = get_profile_store()
    try:
        profile = ClientProfile.from_dict(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid profile data: {exc}")

    await store.save(profile)
    return {"status": "imported", "client": client_name}


@app.get("/api/clients/{client_name}/refinement", tags=["Clients"])
async def get_client_refinement(client_name: str):
    """
    Return the current refinement settings stored in the ClientProfile.
    The refinement dict captures analysis preferences (depth, focus areas,
    excluded tables, language, etc.) produced by the Auto-Refinement Engine.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    return {
        "client_name": client_name,
        "refinement": profile.refinement or {},
    }


@app.patch("/api/clients/{client_name}/refinement", tags=["Clients"])
async def patch_client_refinement(client_name: str, body: dict):
    """
    Merge a partial refinement dict into the existing refinement settings and
    persist the updated ClientProfile.  Keys present in the body overwrite the
    corresponding keys in the stored refinement; all other keys are preserved.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    current = profile.refinement or {}
    current.update(body)
    profile.refinement = current

    from datetime import datetime
    profile.updated_at = datetime.utcnow().isoformat()

    await store.save(profile)
    return {
        "client_name": client_name,
        "refinement": profile.refinement,
    }


@app.get("/api/clients", tags=["Clients"])
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


@app.get("/api/clients/summary", tags=["Clients"])
async def get_clients_summary():
    """Aggregated summary of all clients for operator dashboard."""
    import sys, os, glob as _glob, json as _json
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    # Load all client names first (from list_clients), then load each profile
    # This ensures we read from DB when available, not just local files
    store = get_profile_store()
    all_profiles_data = []

    # Try DB first via asyncpg pool
    try:
        pool = await store._get_pool()
        if pool:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT profile FROM client_profiles")
                for row in rows:
                    try:
                        all_profiles_data.append(_json.loads(row["profile"]))
                    except Exception:
                        pass
        else:
            raise Exception("no pool")
    except Exception:
        # Fallback: local JSON files
        profile_dir = "/tmp/valinor_profiles"
        os.makedirs(profile_dir, exist_ok=True)
        for path in _glob.glob(os.path.join(profile_dir, "*.json")):
            try:
                all_profiles_data.append(_json.loads(open(path).read()))
            except Exception:
                pass

    total_critical = sum(
        sum(1 for f in p.get("known_findings", {}).values() if isinstance(f, dict) and f.get("severity") == "CRITICAL")
        for p in all_profiles_data
    )

    dq_scores = [
        e["score"]
        for p in all_profiles_data
        for e in (p.get("dq_history") or [])
        if isinstance(e, dict) and "score" in e
    ]
    avg_dq = round(sum(dq_scores) / len(dq_scores), 1) if dq_scores else None

    return {
        "total_clients": len(all_profiles_data),
        "total_critical_findings": total_critical,
        "avg_dq_score": avg_dq,
        "total_runs": sum(p.get("run_count", 0) for p in all_profiles_data),
        "clients_with_criticals": sum(
            1 for p in all_profiles_data
            if any(
                isinstance(f, dict) and f.get("severity") == "CRITICAL"
                for f in p.get("known_findings", {}).values()
            )
        ),
    }


@app.get("/api/clients/comparison", tags=["Clients"])
async def get_clients_comparison(clients: Optional[str] = None):
    """
    Compare DQ scores and trends across multiple clients.

    Optional query param: ?clients=client1,client2,client3 (comma-separated).
    If omitted, all clients with profiles are included.
    """
    import sys, os, glob as _glob, json as _json
    from datetime import datetime, timezone
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()

    # Resolve the list of client names to include
    if clients:
        requested_names = [c.strip() for c in clients.split(",") if c.strip()]
    else:
        requested_names = None  # means "all"

    # Load raw profile dicts (same two-path strategy as get_clients_summary)
    all_profiles_data: list = []
    try:
        pool = await store._get_pool()
        if pool:
            async with pool.acquire() as conn:
                if requested_names:
                    rows = await conn.fetch(
                        "SELECT profile FROM client_profiles WHERE client_name = ANY($1)",
                        requested_names,
                    )
                else:
                    rows = await conn.fetch("SELECT profile FROM client_profiles")
                for row in rows:
                    try:
                        all_profiles_data.append(_json.loads(row["profile"]))
                    except Exception:
                        pass
        else:
            raise Exception("no pool")
    except Exception:
        profile_dir = "/tmp/valinor_profiles"
        os.makedirs(profile_dir, exist_ok=True)
        for path in _glob.glob(os.path.join(profile_dir, "*.json")):
            try:
                data = _json.loads(open(path).read())
                if requested_names is None or data.get("client_name") in requested_names:
                    all_profiles_data.append(data)
            except Exception:
                pass

    def _compute_trend(dq_history: list) -> str:
        """Return 'improving', 'degrading', or 'stable' based on last-3 vs first-3 scores."""
        scores = [
            e["score"] for e in dq_history
            if isinstance(e, dict) and "score" in e
        ]
        if len(scores) < 2:
            return "stable"
        first_window = scores[:3]
        last_window = scores[-3:]
        avg_first = sum(first_window) / len(first_window)
        avg_last = sum(last_window) / len(last_window)
        diff = avg_last - avg_first
        if diff > 2:
            return "improving"
        elif diff < -2:
            return "degrading"
        return "stable"

    result_clients = []
    for p in all_profiles_data:
        dq_history = p.get("dq_history") or []
        scores = [e["score"] for e in dq_history if isinstance(e, dict) and "score" in e]
        avg_dq = round(sum(scores) / len(scores), 1) if scores else None

        known_findings = p.get("known_findings") or {}
        critical_count = sum(
            1 for f in known_findings.values()
            if isinstance(f, dict) and f.get("severity") == "CRITICAL"
        )

        # last_run: prefer last dq_history timestamp, fall back to last_run_date field
        last_run = None
        if dq_history:
            last_entry = dq_history[-1]
            if isinstance(last_entry, dict):
                last_run = last_entry.get("timestamp") or last_entry.get("date")
        if not last_run:
            last_run = p.get("last_run_date")

        result_clients.append({
            "name": p.get("client_name"),
            "run_count": p.get("run_count", 0),
            "avg_dq_score": avg_dq,
            "dq_trend": _compute_trend(dq_history),
            "critical_findings": critical_count,
            "last_run": last_run,
            "industry": p.get("industry"),
        })

    # Sort by avg_dq_score descending (None last)
    result_clients.sort(
        key=lambda c: c["avg_dq_score"] if c["avg_dq_score"] is not None else -1,
        reverse=True,
    )

    return {
        "clients": result_clients,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/clients/{client_name}/findings", tags=["Clients"])
async def get_client_findings(
    client_name: str,
    severity_filter: Optional[str] = None,
):
    """
    Return all active findings for a client with full details.

    Reads from profile.known_findings (dict keyed by finding_id).
    Counts by severity and resolved findings are included in the summary.

    - **severity_filter**: optional — filter to a single severity level
      (CRITICAL|HIGH|MEDIUM|LOW|UNKNOWN).  Case-insensitive.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    severity_filter_upper: Optional[str] = severity_filter.upper() if severity_filter else None

    store = get_profile_store()
    profile = await store.load(client_name)

    if profile is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_name}' not found")

    known_findings: dict = profile.known_findings or {}

    findings_list = []
    resolved_count = 0
    severity_counts: dict = {}

    for finding_id, record in known_findings.items():
        if not isinstance(record, dict):
            continue

        status = record.get("status", "open")
        if status == "resolved":
            resolved_count += 1
            continue

        severity = record.get("severity", "UNKNOWN")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

        # Apply severity filter before appending
        if severity_filter_upper and severity != severity_filter_upper:
            continue

        findings_list.append({
            "id": finding_id,
            "title": record.get("title") or record.get("description") or finding_id,
            "severity": severity,
            "agent": record.get("agent") or record.get("source_agent"),
            "first_seen": record.get("first_seen"),
            "last_seen": record.get("last_seen"),
            "runs_open": record.get("runs_open", 0),
        })

    # Sort: CRITICAL first, then HIGH, MEDIUM, LOW, UNKNOWN
    _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}
    findings_list.sort(key=lambda f: _sev_order.get(f["severity"], 99))

    return {
        "client": client_name,
        "findings": findings_list,
        "total": len(findings_list),
        "critical": severity_counts.get("CRITICAL", 0),
        "high": severity_counts.get("HIGH", 0),
        "resolved_count": resolved_count,
        "severity_filter": severity_filter_upper,
    }


@app.get("/api/clients/{client_name}/findings/{finding_id}", tags=["Clients"])
async def get_client_finding(client_name: str, finding_id: str):
    """
    Return a single finding by ID for a client.

    Returns 404 if the client has no profile or the finding_id does not exist.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store
    from fastapi import HTTPException

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    known_findings: dict = profile.known_findings or {}

    if finding_id not in known_findings:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found for client '{client_name}'")

    record = known_findings[finding_id]
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' has invalid format")

    return {
        "client": client_name,
        "finding": {
            "id": finding_id,
            **record,
        },
    }


@app.get("/api/clients/{client_name}/costs", tags=["Clients"])
async def get_client_costs(client_name: str):
    """
    Return a cost summary for a client based on their run history.

    Reads from profile.run_history. Each run contributes $8 (default) or
    the value of its `estimated_cost_usd` field if present.
    `runs_this_month` and `cost_this_month_usd` are computed from runs
    whose `timestamp` field starts with the current YYYY-MM prefix.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    _validate_client_name(client_name)

    store = get_profile_store()
    profile = await store.load(client_name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    run_history: list = profile.run_history or []
    current_month_prefix = datetime.utcnow().strftime("%Y-%m")

    total_cost = 0.0
    cost_this_month = 0.0
    runs_this_month = 0

    for run in run_history:
        run_cost = float(run.get("estimated_cost_usd", 8.0))
        total_cost += run_cost
        ts = run.get("timestamp", "")
        if isinstance(ts, str) and ts.startswith(current_month_prefix):
            runs_this_month += 1
            cost_this_month += run_cost

    total_runs = len(run_history)
    avg_cost = round(total_cost / total_runs, 2) if total_runs else 0.0

    return {
        "client_name": client_name,
        "total_runs": total_runs,
        "estimated_total_cost_usd": round(total_cost, 2),
        "avg_cost_per_run_usd": avg_cost,
        "runs_this_month": runs_this_month,
        "cost_this_month_usd": round(cost_this_month, 2),
    }


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


@app.get("/api/clients/{client_name}/dq-history", tags=["Quality"])
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


@app.get("/api/clients/{client_name}/kpis", tags=["Clients"])
async def get_client_kpis(client_name: str):
    """
    Get KPI baseline history for a client.

    Returns the full `baseline_history` from the client profile — a dict of
    KPI label → list of datapoints — together with summary metadata such as
    the total number of tracked KPIs and the earliest/latest periods present.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    _validate_client_name(client_name)

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    baseline_history: dict = profile.baseline_history or {}

    # Collect all period strings across every KPI to derive earliest/latest
    all_periods: list[str] = []
    for datapoints in baseline_history.values():
        for dp in datapoints:
            period = dp.get("period")
            if period:
                all_periods.append(period)

    return {
        "client_name": client_name,
        "kpis": baseline_history,
        "kpi_count": len(baseline_history),
        "earliest_period": min(all_periods) if all_periods else None,
        "latest_period": max(all_periods) if all_periods else None,
    }


@app.get("/api/clients/{client_name}/stats", tags=["Clients"])
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


@app.get("/api/clients/{client_name}/analytics", tags=["Clients"])
async def get_client_analytics(client_name: str):
    """
    Return deeper run analytics derived from the client's run_history.

    Includes total runs, success rate, average findings per run,
    monthly run distribution, finding velocity trend, and a summary
    of the last 5 runs.
    """
    import sys, os
    from collections import defaultdict
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for: {client_name}")

    run_history = profile.run_history or []
    total_runs = len(run_history)

    # Success rate
    successful = sum(1 for r in run_history if r.get("success", True))
    success_rate = round(successful / total_runs * 100, 1) if total_runs else 0.0

    # Average findings / new findings / resolved per run
    avg_findings = round(
        sum(r.get("findings_count", 0) for r in run_history) / max(total_runs, 1), 1
    )
    avg_new = round(
        sum(r.get("new", 0) for r in run_history) / max(total_runs, 1), 1
    )
    avg_resolved = round(
        sum(r.get("resolved", 0) for r in run_history) / max(total_runs, 1), 1
    )

    # Runs grouped by month (YYYY-MM)
    runs_by_month: dict = defaultdict(int)
    for r in run_history:
        date_str = r.get("run_date", "")
        if date_str and len(date_str) >= 7:
            month_key = date_str[:7]  # "YYYY-MM"
            runs_by_month[month_key] += 1

    # Finding velocity — trend over last 5 runs
    last_5 = run_history[-5:]
    velocity_counts = [r.get("findings_count", 0) for r in last_5]
    finding_velocity = "stable"
    if len(velocity_counts) >= 2:
        if velocity_counts[-1] > velocity_counts[0]:
            finding_velocity = "increasing"
        elif velocity_counts[-1] < velocity_counts[0]:
            finding_velocity = "decreasing"

    # Last 5 run summaries
    last_5_runs = [
        {
            "run_date": r.get("run_date"),
            "findings_count": r.get("findings_count", 0),
            "new": r.get("new", 0),
            "resolved": r.get("resolved", 0),
            "success": r.get("success", True),
        }
        for r in last_5
    ]

    return {
        "client_name": client_name,
        "total_runs": total_runs,
        "success_rate": success_rate,
        "avg_findings_per_run": avg_findings,
        "avg_new_findings_per_run": avg_new,
        "avg_resolved_per_run": avg_resolved,
        "runs_by_month": dict(sorted(runs_by_month.items())),
        "finding_velocity": finding_velocity,
        "last_5_runs": last_5_runs,
    }


# ── PDF Export ───────────────────────────────────────────────────────────────

@app.get("/api/jobs/{job_id}/pdf", tags=["Reports"])
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

@app.get("/api/clients/{client_name}/alerts", tags=["Alerts"])
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
    run_delta = results.get("run_delta", {})
    findings = results.get("findings", {})
    data_quality = results.get("data_quality")
    triggered_alerts = results.get("triggered_alerts")

    # Build top findings list
    top_findings = []
    for agent_result in findings.values():
        if isinstance(agent_result, dict):
            top_findings.extend(agent_result.get("findings", []))
    top_findings.sort(key=lambda f: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(f.get("severity", "").upper(), 4))

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
        subject=f"Valinor — {client_name} — {period} — Análisis completado",
        html_content=html,
    )
    return {"status": "sent" if sent else "smtp_not_configured", "to": to_email}


@app.get("/api/jobs/{job_id}/quality", tags=["Quality"])
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


@app.get("/api/system/status", tags=["System"])
async def system_status():
    """
    Comprehensive system status — services, versions, installed packages, feature flags.
    """
    import importlib

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
    except:
        pass

    db_ok = False
    try:
        import asyncpg
        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            conn = await asyncpg.connect(db_url)
            await conn.close()
            db_ok = True
    except:
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


@app.get("/api/system/metrics", tags=["System"])
async def system_metrics():
    """
    Operational metrics — job counts, success rates, client counts.
    """
    redis_client = await get_redis()

    # Count jobs by status
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

    # Count clients
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    client_count = 0
    pool = await store._get_pool()
    if pool:
        try:
            async with pool.acquire() as conn:
                client_count = await conn.fetchval("SELECT COUNT(*) FROM client_profiles")
        except:
            pass

    # Estimate cost from completed jobs (~$8 per analysis average)
    estimated_cost_usd = round(status_counts["completed"] * 8.0, 2)

    # Aggregate all-time avg DQ score across all profiles
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


@app.post("/api/clients/{client_name}/webhooks")
async def register_webhook(client_name: str, body: dict):
    """Register a webhook URL for a client."""
    from shared.memory.profile_store import get_profile_store
    webhook_url = body.get("url")
    if not webhook_url or not webhook_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Valid webhook URL required")

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    # Deduplicate and append, capped at 5
    existing = [w for w in profile.webhooks if w.get("url") != webhook_url]
    existing.append({"url": webhook_url, "registered_at": datetime.utcnow().isoformat(), "active": True})
    profile.webhooks = existing[-5:]  # max 5 webhooks

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
    return {"client": client_name, "webhooks": profile.webhooks}


@app.delete("/api/clients/{client_name}/webhooks")
async def delete_webhook(client_name: str, url: str):
    """Remove a webhook."""
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")
    profile.webhooks = [w for w in profile.webhooks if w.get("url") != url]
    await store.save(profile)
    return {"status": "removed", "remaining": len(profile.webhooks)}


@app.get("/api/clients/{client_name}/segmentation", tags=["Segmentation"])
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
                for webhook in profile.webhooks:
                    if webhook.get("active") and webhook.get("url"):
                        summary = build_job_summary(results)
                        asyncio.create_task(fire_job_completion_webhook(
                            webhook["url"], job_id, client_name, "completed", summary
                        ))
        except Exception as _wh_err:
            logger.warning("Webhook setup failed", error=str(_wh_err))

    except Exception as e:
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
                    # Parse score and blocking issues out of the error message so the
                    # status endpoint can surface a structured DQ HALT payload.
                    # Format: "Data quality gate HALT: score=NN/100. Issues: ..."
                    import re as _re2
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
                for webhook in profile.webhooks:
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