"""
Onboarding endpoints — validate connections and detect ERP type before full analysis.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import re

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


class ConnectionTestRequest(BaseModel):
    db_type: str = "postgresql"
    host: str
    port: int = 5432
    database: str
    user: str
    password: str
    ssh_host: Optional[str] = None
    ssh_port: int = 22
    ssh_user: Optional[str] = None
    ssh_key: Optional[str] = None  # base64-encoded private key


class ConnectionTestResult(BaseModel):
    success: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    erp_detected: Optional[str] = None        # "odoo", "idempiere", "generic_postgresql", "unknown"
    erp_version: Optional[str] = None
    table_count: Optional[int] = None
    has_accounting: bool = False
    has_invoices: bool = False
    has_partners: bool = False
    recommended_analysis: Optional[str] = None  # "full" | "accounting_only" | "limited"


@router.post("/test-connection", response_model=ConnectionTestResult)
async def test_db_connection(request: ConnectionTestRequest):
    """
    Test database connectivity and auto-detect ERP type.
    Does NOT store any client data. Ephemeral connection only.
    """
    import time
    from sqlalchemy import create_engine, text, inspect

    start = time.time()

    # Build connection string (no SSH for now — SSH validation is separate)
    if request.db_type == "postgresql":
        conn_str = f"postgresql://{request.user}:{request.password}@{request.host}:{request.port}/{request.database}"
    elif request.db_type == "mysql":
        conn_str = f"mysql+pymysql://{request.user}:{request.password}@{request.host}:{request.port}/{request.database}"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported DB type: {request.db_type}")

    try:
        engine = create_engine(conn_str, connect_args={"connect_timeout": 8})
        with engine.connect() as conn:
            # Basic connectivity
            conn.execute(text("SELECT 1"))
            latency_ms = (time.time() - start) * 1000

            # Get table count
            inspector = inspect(engine)
            tables = inspector.get_table_names()
            table_count = len(tables)

            # ERP detection
            erp = _detect_erp(tables, conn)

            # Check key tables
            has_accounting = any(t in tables for t in ['account_move', 'c_invoice', 'gl_journal'])
            has_invoices = any(t in tables for t in ['account_move', 'c_invoice', 'invoice'])
            has_partners = any(t in tables for t in ['res_partner', 'c_bpartner', 'customer'])

            # Recommend analysis type
            if has_accounting and has_invoices and has_partners:
                recommended = "full"
            elif has_accounting:
                recommended = "accounting_only"
            else:
                recommended = "limited"

        engine.dispose()

        return ConnectionTestResult(
            success=True,
            latency_ms=round(latency_ms, 1),
            erp_detected=erp["name"],
            erp_version=erp.get("version"),
            table_count=table_count,
            has_accounting=has_accounting,
            has_invoices=has_invoices,
            has_partners=has_partners,
            recommended_analysis=recommended,
        )

    except Exception as e:
        return ConnectionTestResult(
            success=False,
            error=str(e)[:200],
            latency_ms=round((time.time() - start) * 1000, 1),
        )


def _detect_erp(tables: list, conn) -> dict:
    """Auto-detect ERP type from table names and metadata."""
    from sqlalchemy import text

    table_set = set(t.lower() for t in tables)

    # Odoo detection
    if 'res_partner' in table_set and 'account_move' in table_set:
        # Try to get version from ir_module_module
        version = None
        if 'ir_module_module' in table_set:
            try:
                result = conn.execute(text(
                    "SELECT latest_version FROM ir_module_module WHERE name='base' LIMIT 1"
                )).fetchone()
                if result:
                    version = str(result[0])
            except Exception:
                pass
        return {"name": "odoo", "version": version}

    # iDempiere detection
    if 'c_bpartner' in table_set and 'c_invoice' in table_set:
        return {"name": "idempiere", "version": None}

    # SAP B1 detection
    if 'ocrd' in table_set and 'oinv' in table_set:
        return {"name": "sap_b1", "version": None}

    # Generic PostgreSQL
    if len(table_set) > 0:
        return {"name": "generic_postgresql", "version": None}

    return {"name": "unknown", "version": None}


@router.post("/validate-period")
async def validate_period(body: dict):
    """Validate that a period has data in the client database."""
    period = body.get("period", "")
    patterns = [r'^Q[1-4]-\d{4}$', r'^H[12]-\d{4}$', r'^\d{4}$']
    valid = any(re.match(p, period) for p in patterns)
    return {
        "valid": valid,
        "period": period,
        "message": "Período válido" if valid else "Formato inválido. Usar: Q1-2025, H1-2025, 2025"
    }
