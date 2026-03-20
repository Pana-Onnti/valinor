#!/usr/bin/env python3
"""
Valinor SaaS - Simplified MVP
Single file FastAPI server with threading for background jobs.
"""

import os
import json
import uuid
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import paramiko

# Simple job storage (replace complex Redis/Postgres)
JOBS_DIR = Path("/tmp/valinor_jobs")
JOBS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Valinor SaaS - Simple MVP")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══ MODELS ═══

class AnalysisRequest(BaseModel):
    client_name: str
    period: str  # Q1-2025, etc.
    ssh_host: str
    ssh_user: str
    ssh_key_path: str
    db_host: str
    db_port: int
    db_connection_string: str

class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, running, completed, failed
    progress: int = 0
    message: str = ""
    error: Optional[str] = None

# ═══ SIMPLE STORAGE ═══

def save_job(job_id: str, data: Dict[str, Any]):
    """Save job data to JSON file."""
    job_file = JOBS_DIR / f"{job_id}.json"
    with open(job_file, 'w') as f:
        json.dump(data, f, indent=2)

def load_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Load job data from JSON file."""
    job_file = JOBS_DIR / f"{job_id}.json"
    if not job_file.exists():
        return None
    
    with open(job_file, 'r') as f:
        return json.load(f)

def update_job_status(job_id: str, status: str, progress: int = 0, message: str = "", error: str = None):
    """Update job status."""
    data = load_job(job_id) or {}
    data.update({
        "status": status,
        "progress": progress,
        "message": message,
        "updated_at": datetime.utcnow().isoformat()
    })
    if error:
        data["error"] = error
    save_job(job_id, data)

# ═══ SIMPLE SSH TUNNEL ═══

@contextmanager
def simple_ssh_tunnel(ssh_host: str, ssh_user: str, ssh_key_path: str, 
                     db_host: str, db_port: int, job_id: str):
    """Create simple SSH tunnel without complexity."""
    import socket
    
    # Find free local port
    with socket.socket() as s:
        s.bind(('', 0))
        local_port = s.getsockname()[1]
    
    # Create SSH client
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # Connect
        private_key = paramiko.RSAKey.from_private_key_file(ssh_key_path)
        ssh.connect(ssh_host, username=ssh_user, pkey=private_key, timeout=30)
        
        # Setup port forwarding
        transport = ssh.get_transport()
        transport.request_port_forward('', local_port)
        
        print(f"SSH tunnel: {ssh_host} -> {db_host}:{db_port} via localhost:{local_port}")
        yield local_port
        
    finally:
        ssh.close()

# ═══ SIMPLE ANALYSIS RUNNER ═══

def run_valinor_analysis(job_id: str, request_data: Dict[str, Any]):
    """Run Valinor analysis in background thread."""
    try:
        update_job_status(job_id, "running", 10, "Starting analysis...")
        
        # Extract config
        ssh_config = {
            "host": request_data["ssh_host"],
            "user": request_data["ssh_user"],
            "key_path": request_data["ssh_key_path"]
        }
        
        db_config = {
            "host": request_data["db_host"],
            "port": request_data["db_port"],
            "connection_string": request_data["db_connection_string"]
        }
        
        # TESTING MODE: Skip SSH for localhost connections
        if ssh_config["host"] == "localhost" and db_config["host"] == "localhost":
            update_job_status(job_id, "running", 20, "Using direct local connection (test mode)...")
            
            # Use connection string directly for localhost
            tunneled_conn = db_config["connection_string"]
            
            update_job_status(job_id, "running", 40, "Running Valinor analysis...")
            
            # Call real Valinor v0 analysis
            results = run_real_valinor_analysis_integrated(job_id, request_data, tunneled_conn)
            
            update_job_status(job_id, "running", 90, "Generating reports...")
            
            # Save results
            job_data = load_job(job_id)
            job_data["results"] = results
            save_job(job_id, job_data)
            
            update_job_status(job_id, "completed", 100, "Analysis completed successfully")
        
        else:
            # Create SSH tunnel for remote connections
            update_job_status(job_id, "running", 20, "Creating secure connection...")
            
            with simple_ssh_tunnel(
                ssh_config["host"], ssh_config["user"], ssh_config["key_path"],
                db_config["host"], db_config["port"], job_id
            ) as local_port:
                
                # Update connection string to use tunnel
                tunneled_conn = db_config["connection_string"].replace(
                    f"{db_config['host']}:{db_config['port']}",
                    f"localhost:{local_port}"
                )
                
                update_job_status(job_id, "running", 40, "Running Valinor analysis...")
                
                # Call real Valinor v0 analysis
                results = run_real_valinor_analysis_integrated(job_id, request_data, tunneled_conn)
                
                update_job_status(job_id, "running", 90, "Generating reports...")
                
                # Save results
                job_data = load_job(job_id)
                job_data["results"] = results
                save_job(job_id, job_data)
                
                update_job_status(job_id, "completed", 100, "Analysis completed successfully")
            
    except Exception as e:
        error_msg = str(e)
        print(f"Analysis failed for job {job_id}: {error_msg}")
        update_job_status(job_id, "failed", -1, "Analysis failed", error_msg)

def run_real_valinor_analysis_integrated(job_id: str, request_data: Dict, connection_string: str) -> Dict[str, Any]:
    """Run real Valinor analysis integrated with v0 core."""
    
    # Import real Valinor runner
    from valinor_runner import integrate_with_simple_api
    
    # Create progress callback
    def progress_update(stage: str, progress: int, message: str):
        update_job_status(job_id, "running", progress, message)
    
    # Run integrated analysis
    return integrate_with_simple_api(job_id, request_data, connection_string, progress_update)

# ═══ API ENDPOINTS ═══

@app.get("/health")
async def health():
    return {"status": "healthy", "version": "simple-mvp"}

@app.post("/api/analyze")
async def start_analysis(request: AnalysisRequest):
    """Start new analysis job."""
    job_id = str(uuid.uuid4())
    
    # Save initial job data
    job_data = {
        "job_id": job_id,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "request_data": request.dict()
    }
    save_job(job_id, job_data)
    
    # Start background thread
    thread = threading.Thread(
        target=run_valinor_analysis,
        args=(job_id, request.dict()),
        daemon=True
    )
    thread.start()
    
    return {"job_id": job_id, "status": "pending"}

@app.get("/api/status/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get job status."""
    job_data = load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatus(
        job_id=job_id,
        status=job_data.get("status", "unknown"),
        progress=job_data.get("progress", 0),
        message=job_data.get("message", ""),
        error=job_data.get("error")
    )

@app.get("/api/results/{job_id}")
async def get_job_results(job_id: str):
    """Get job results."""
    job_data = load_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job_data.get("status") != "completed":
        raise HTTPException(
            status_code=400, 
            detail=f"Job not completed. Status: {job_data.get('status')}"
        )
    
    return job_data.get("results", {})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)