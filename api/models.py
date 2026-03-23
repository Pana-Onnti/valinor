"""
Valinor SaaS API — Pydantic request/response models.

Extracted from main.py for better modularity.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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

    @field_validator('period', mode='before')
    @classmethod
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


class UploadResponse(BaseModel):
    """Response model for file upload endpoint."""
    upload_id: str
    filename: str
    size_bytes: int
    file_type: str  # csv, xlsx, xls
    sheets: List[str] = []  # only populated for Excel files
    status: str = "pending"


class PreviewRequest(BaseModel):
    """Request model for file preview."""
    rows: int = 20
    sheet: Optional[str] = None
