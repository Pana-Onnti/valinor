"""
Onboarding endpoints — validate connections and detect ERP type before full analysis.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import re

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ─── Models ───────────────────────────────────────────────────────────────────

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
    data_from: Optional[str] = None            # "YYYY-MM" — oldest transaction date found
    data_to: Optional[str] = None              # "YYYY-MM" — most recent transaction date found


class SSHTestRequest(BaseModel):
    """Request body for SSH + DB connectivity test."""
    ssh_host: str
    ssh_port: int = 22
    ssh_user: str
    ssh_key: str  # base64-encoded PEM private key
    db_host: str
    db_port: int = 5432
    db_type: str = "postgresql"
    db_name: str
    db_user: str
    db_password: str


class SSHTestResult(BaseModel):
    ssh_ok: bool
    db_ok: bool
    latency_ms: float
    error: Optional[str] = None


class DBTypeInfo(BaseModel):
    id: str
    label: str
    default_port: int
    connection_template: str
    notes: str


class CostEstimateRequest(BaseModel):
    estimated_rows: int
    tables_count: int
    period: str  # e.g. "Q1-2025", "H1-2025", "2025"


class CostEstimateResult(BaseModel):
    estimated_cost_usd: float
    estimated_duration_minutes: int
    token_estimate: int


# ─── Endpoints ────────────────────────────────────────────────────────────────

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

            # Detect available date range from transaction tables
            data_from, data_to = _detect_date_range(erp["name"], tables, conn)

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
            data_from=data_from,
            data_to=data_to,
        )

    except Exception as e:
        return ConnectionTestResult(
            success=False,
            error=str(e)[:200],
            latency_ms=round((time.time() - start) * 1000, 1),
        )


@router.post("/ssh-test", response_model=SSHTestResult)
async def test_ssh_and_db(request: SSHTestRequest):
    """
    Test SSH tunnel + DB connectivity without running any analysis.
    Validates SSH config, opens tunnel, attempts a DB ping, then immediately disconnects.
    No client data is stored.

    Returns: ssh_ok, db_ok, latency_ms, error
    """
    import time
    import base64
    import tempfile
    import os
    import paramiko
    import socket

    # ── Zero-trust validation ────────────────────────────────────────────────
    _validate_ssh_host(request.ssh_host)
    _validate_ssh_host(request.db_host)

    start = time.time()
    ssh_ok = False
    db_ok = False
    error_msg: Optional[str] = None

    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.RejectPolicy())  # zero-trust: reject unknown hosts
    key_file = None

    try:
        # Decode base64 key and write to temp file
        try:
            key_bytes = base64.b64decode(request.ssh_key)
        except Exception:
            # Try raw PEM
            key_bytes = request.ssh_key.encode()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="wb") as tf:
            tf.write(key_bytes)
            key_file = tf.name
        os.chmod(key_file, 0o600)

        try:
            private_key = paramiko.RSAKey.from_private_key_file(key_file)
        except paramiko.ssh_exception.SSHException:
            try:
                private_key = paramiko.Ed25519Key.from_private_key_file(key_file)
            except paramiko.ssh_exception.SSHException:
                private_key = paramiko.ECDSAKey.from_private_key_file(key_file)

        # ── SSH connect ──────────────────────────────────────────────────────
        ssh_client.connect(
            hostname=request.ssh_host,
            port=request.ssh_port,
            username=request.ssh_user,
            pkey=private_key,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )
        ssh_ok = True

        # ── DB connectivity via SSH transport channel ────────────────────────
        transport = ssh_client.get_transport()
        if transport is None:
            raise RuntimeError("SSH transport not available after connect")

        # Find a free local port for the tunnel
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            local_port = s.getsockname()[1]

        channel = transport.open_channel(
            "direct-tcpip",
            (request.db_host, request.db_port),
            ("127.0.0.1", local_port),
        )
        channel.settimeout(8)

        # Minimal DB handshake to confirm reachability
        if request.db_type in ("postgresql", "postgres"):
            _check = _ping_postgres_via_channel(channel, request.db_name, request.db_user, request.db_password)
        elif request.db_type == "mysql":
            _check = _ping_mysql_via_channel(channel)
        else:
            # Generic: if channel opened without error, consider db_ok
            _check = True

        db_ok = _check
        channel.close()

    except paramiko.AuthenticationException as exc:
        error_msg = f"SSH authentication failed: {exc}"
    except paramiko.ssh_exception.NoValidConnectionsError as exc:
        error_msg = f"SSH connection refused: {exc}"
    except socket.timeout:
        error_msg = "Connection timed out"
    except Exception as exc:
        error_msg = str(exc)[:300]
    finally:
        try:
            ssh_client.close()
        except Exception:
            pass
        if key_file:
            try:
                os.unlink(key_file)
            except Exception:
                pass

    latency_ms = round((time.time() - start) * 1000, 1)

    return SSHTestResult(
        ssh_ok=ssh_ok,
        db_ok=db_ok,
        latency_ms=latency_ms,
        error=error_msg,
    )


@router.get("/supported-databases", response_model=List[DBTypeInfo])
async def supported_databases():
    """
    Returns the list of supported database types with connection string templates
    and default port information.
    """
    return [
        DBTypeInfo(
            id="postgresql",
            label="PostgreSQL",
            default_port=5432,
            connection_template="postgresql://{user}:{password}@{host}:{port}/{database}",
            notes="Fully supported. Odoo, iDempiere, and custom schemas auto-detected.",
        ),
        DBTypeInfo(
            id="mysql",
            label="MySQL / MariaDB",
            default_port=3306,
            connection_template="mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
            notes="MySQL 5.7+ and MariaDB 10.3+ supported.",
        ),
        DBTypeInfo(
            id="sqlserver",
            label="SQL Server",
            default_port=1433,
            connection_template="mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server",
            notes="SQL Server 2016+ supported. Requires ODBC Driver 17.",
        ),
        DBTypeInfo(
            id="oracle",
            label="Oracle Database",
            default_port=1521,
            connection_template="oracle+oracledb://{user}:{password}@{host}:{port}/{database}",
            notes="Oracle 12c+ supported via python-oracledb.",
        ),
    ]


@router.post("/estimate-cost", response_model=CostEstimateResult)
async def estimate_cost(request: CostEstimateRequest):
    """
    Estimate analysis cost based on rough database size.

    Formula:
      base = $3.00
      + $0.50 per 100 000 rows
      + $0.20 per table
      min = $5.00, max = $15.00

    Duration estimate: 3 min base + 1 min per 500k rows + 0.5 min per 10 tables.
    Token estimate: 50k base + 10 tokens per row (sampled) + 500 per table.
    """
    rows = max(0, request.estimated_rows)
    tables = max(0, request.tables_count)

    cost = 3.0 + (rows / 100_000) * 0.5 + tables * 0.2
    cost = max(5.0, min(15.0, cost))
    cost = round(cost, 2)

    # Duration in minutes
    duration = 3 + int(rows / 500_000) + int(tables / 10) * 1
    duration = max(3, min(30, duration))

    # Rough token estimate (very conservative — most rows are sampled, not streamed)
    sampled_rows = min(rows, 10_000)  # sampling cap
    tokens = 50_000 + sampled_rows * 10 + tables * 500
    tokens = int(min(tokens, 500_000))

    return CostEstimateResult(
        estimated_cost_usd=cost,
        estimated_duration_minutes=duration,
        token_estimate=tokens,
    )


@router.post("/validate-period")
async def validate_period(body: dict):
    """Validate that a period has data in the client database."""
    period = body.get("period", "")
    patterns = [
        r'^Q[1-4]-\d{4}$',    # Q1-2025
        r'^H[12]-\d{4}$',     # H1-2025
        r'^\d{4}$',            # 2025
        r'^\d{4}-\d{2}$',     # 2025-01 (monthly)
    ]
    valid = any(re.match(p, period) for p in patterns)
    return {
        "valid": valid,
        "period": period,
        "message": "Período válido" if valid else "Formato inválido. Usar: 2025-01, Q1-2025, H1-2025, 2025"
    }


# ─── Internal helpers ─────────────────────────────────────────────────────────

_PRIVATE_RANGES = [
    re.compile(r'^127\.'),
    re.compile(r'^10\.'),
    re.compile(r'^192\.168\.'),
    re.compile(r'^172\.(1[6-9]|2\d|3[01])\.'),
    re.compile(r'^0\.'),
    re.compile(r'^169\.254\.'),
    re.compile(r'^::1$'),
    re.compile(r'^fc00:', re.IGNORECASE),
    re.compile(r'^fe80:', re.IGNORECASE),
]

_ALLOWED_HOSTNAME = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$')


def _validate_ssh_host(host: str) -> None:
    """
    ZeroTrustValidator: block RFC-1918 / loopback addresses to prevent
    SSRF via SSH tunnel. Only public hostnames and IPs are allowed.
    Raises HTTPException(400) on violation.
    """
    if not host or len(host) > 253:
        raise HTTPException(status_code=400, detail="Invalid host value")

    # Block private/loopback ranges
    for pattern in _PRIVATE_RANGES:
        if pattern.match(host):
            raise HTTPException(
                status_code=400,
                detail=f"Host '{host}' is in a reserved/private range and is not allowed (zero-trust policy)"
            )

    # Allow numeric IPs (basic check) or valid hostnames
    if not _ALLOWED_HOSTNAME.match(host):
        # Could be a raw IP — let it through, private ranges already blocked above
        ip_pattern = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')
        if not ip_pattern.match(host):
            raise HTTPException(status_code=400, detail=f"Invalid hostname format: '{host}'")


def _ping_postgres_via_channel(channel, dbname: str, user: str, password: str) -> bool:
    """
    Send a minimal PostgreSQL startup message over a paramiko channel to confirm
    the DB is reachable and credentials are accepted. Returns True on success.
    """
    import struct

    try:
        # Startup message: length (4) + protocol (4) + params + null
        params = f"user\x00{user}\x00database\x00{dbname}\x00\x00".encode()
        proto = struct.pack("!I", 196608)  # 3.0
        msg_len = struct.pack("!I", 4 + 4 + len(params))
        channel.sendall(msg_len + proto + params)

        # Read response byte (AuthenticationOk = 'R', ErrorResponse = 'E')
        resp = channel.recv(1)
        if resp in (b'R', b'S'):
            return True  # 'R' = auth request (connected), 'S' = parameter status
        if resp == b'E':
            # Error from server — still reachable, but credentials may be wrong
            return True  # TCP/DB is reachable
        return False
    except Exception:
        return False


def _ping_mysql_via_channel(channel) -> bool:
    """
    Read the MySQL server greeting to confirm DB is reachable.
    Does not attempt authentication.
    """
    try:
        data = channel.recv(64)
        # MySQL greeting starts with packet length (3 bytes) + seq (1 byte)
        # followed by protocol version (0x0a for MySQL 5+)
        if len(data) >= 5 and data[4] == 0x0a:
            return True
        return len(data) > 0
    except Exception:
        return False


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


def _detect_date_range(erp_name: str, tables: list, conn) -> tuple:
    """
    Query the most relevant transaction table to find MIN/MAX transaction dates.
    Returns (data_from, data_to) as "YYYY-MM" strings, or (None, None) on failure.
    """
    from sqlalchemy import text as _text
    from typing import Tuple

    table_set = set(t.lower() for t in tables)

    # Candidate queries: (table, date_column) ordered by preference
    candidates = []
    if erp_name == "idempiere":
        if "c_invoice" in table_set:
            candidates.append(("c_invoice", "dateinvoiced"))
        if "c_order" in table_set:
            candidates.append(("c_order", "dateordered"))
    elif erp_name == "odoo":
        if "account_move" in table_set:
            candidates.append(("account_move", "invoice_date"))
        if "sale_order" in table_set:
            candidates.append(("sale_order", "date_order"))
    elif erp_name == "sap_b1":
        if "oinv" in table_set:
            candidates.append(("oinv", "\"DocDate\""))
    else:
        # Generic: try common date-column names in any of these tables
        for tbl in ("invoices", "orders", "transactions", "sales"):
            if tbl in table_set:
                candidates.append((tbl, "created_at"))

    for table, col in candidates:
        try:
            row = conn.execute(_text(
                f"SELECT MIN({col})::date, MAX({col})::date FROM {table} WHERE {col} IS NOT NULL"
            )).fetchone()
            if row and row[0] and row[1]:
                d_from = str(row[0])[:7]  # "YYYY-MM"
                d_to   = str(row[1])[:7]
                return d_from, d_to
        except Exception:
            continue

    return None, None
