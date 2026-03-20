"""
Valinor SaaS API - FastAPI application for MVP.
Provides REST API endpoints for Valinor analysis.
"""

import os
import sys
import uuid
import json
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field, validator
import structlog
import redis.asyncio as redis

# Add shared modules to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from adapters.valinor_adapter import ValinorAdapter, PipelineExecutor
from shared.storage import MetadataStorage

logger = structlog.get_logger()

# Configure FastAPI app
app = FastAPI(
    title="Valinor SaaS API",
    description="Enterprise Analytics API - Transform database insights into business intelligence",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
async def start_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    Start a new Valinor analysis job.
    
    Returns immediately with job ID. Use /api/jobs/{job_id}/status to track progress.
    """
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
        job_data = {
            "job_id": job_id,
            "status": "pending",
            "client_name": client_name,
            "period": period,
            "created_at": datetime.utcnow().isoformat(),
            "request": json.dumps(request.dict()),
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
    limit: int = 10,
    redis_client: redis.Redis = Depends(get_redis)
):
    """
    List recent analysis jobs.
    """
    try:
        # Get all job keys
        job_keys = await redis_client.keys("job:*")
        job_keys = [key for key in job_keys if not key.endswith(":results")]
        
        jobs = []
        for key in job_keys[-limit:]:  # Get latest jobs
            job_data = await redis_client.hgetall(key)
            if job_data:
                jobs.append({
                    "job_id": job_data.get("job_id"),
                    "client_name": job_data.get("client_name"),
                    "period": job_data.get("period"),
                    "status": job_data.get("status"),
                    "created_at": job_data.get("created_at")
                })
        
        # Sort by creation time (newest first)
        jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return {
            "jobs": jobs,
            "total": len(jobs)
        }
        
    except Exception as e:
        logger.error("Failed to list jobs", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list jobs: {str(e)}"
        )

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