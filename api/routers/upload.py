"""
Upload router — File upload with validation and storage.

Accepts CSV and Excel files for analysis, validates extension/size/content,
detects Excel sheet names, saves to tenant-isolated storage, and registers
upload metadata in an in-memory registry (temporary until Alembic migration).

Refs: VAL-83
"""

import io
import os
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from api.models import UploadResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/upload", tags=["Upload"])

# ── Configuration ─────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024

_DEFAULT_UPLOAD_DIR = "/tmp/valinor/uploads"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", _DEFAULT_UPLOAD_DIR))

# Temporary in-memory registry until Alembic migration provides a DB table.
# Keys are upload_id (str UUID), values are metadata dicts.
_uploads_registry: dict[str, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_extension(filename: str) -> str:
    """Return the lowercased file extension including the leading dot."""
    return Path(filename).suffix.lower()


def _get_file_type(extension: str) -> str:
    """Map extension to a canonical file_type string."""
    return extension.lstrip(".")


def _detect_excel_sheets(content: bytes) -> list[str]:
    """
    Load an Excel workbook in read-only mode and return its sheet names.

    Returns an empty list if the file cannot be parsed as a valid workbook.
    """
    try:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheets = wb.sheetnames
        wb.close()
        return list(sheets)
    except Exception as exc:
        logger.warning("upload.excel_sheet_detection_failed", error=str(exc))
        return []


def _validate_csv_content(content: bytes) -> None:
    """
    Verify that the CSV bytes look like text and contain at least one data row.

    Raises HTTPException 400 if the check fails.
    """
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="CSV file is not valid UTF-8 text")

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise HTTPException(
            status_code=400,
            detail="CSV file must contain a header row and at least one data row",
        )


def _tenant_id_from_request(request: Request) -> str:
    """
    Return the tenant_id set by TenantMiddleware, falling back to the
    default development tenant if not present.
    """
    return getattr(request.state, "tenant_id", None) or "00000000-0000-0000-0000-000000000001"


def _build_storage_path(tenant_id: str, client_name: str, upload_id: str, filename: str) -> Path:
    """Construct and create the tenant-isolated storage path."""
    dest_dir = UPLOAD_DIR / tenant_id / client_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_filename = Path(filename).name  # strip any path traversal
    return dest_dir / f"{upload_id}_{safe_filename}"


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/{client_name}", response_model=UploadResponse)
async def upload_file(
    client_name: str,
    request: Request,
    file: UploadFile = File(...),
) -> UploadResponse:
    """
    Upload a CSV or Excel file for analysis.

    Validations (in order):
    1. Extension must be .csv, .xlsx, or .xls  → 400
    2. File must not be empty                   → 400
    3. Size must not exceed MAX_UPLOAD_SIZE      → 413
    4. Content-specific checks (CSV rows / Excel sheets)

    The file is saved under UPLOAD_DIR/{tenant_id}/{client_name}/{upload_id}_{filename}.
    Metadata is recorded in the in-memory registry until the DB migration lands.
    """
    filename = file.filename or "upload"

    # 1. Validate extension
    extension = _get_extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{extension}'. "
                f"Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    # 2. Read content (async — does not block event loop)
    content = await file.read()

    # 3. Empty file check
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # 4. Size check
    if len(content) > MAX_UPLOAD_SIZE:
        max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the maximum allowed size of {max_mb} MB",
        )

    # 5. Content-specific validation and sheet detection
    sheets: list[str] = []
    if extension == ".csv":
        _validate_csv_content(content)
    else:
        # .xlsx / .xls
        sheets = _detect_excel_sheets(content)
        if not sheets:
            raise HTTPException(
                status_code=400,
                detail="Could not read any sheets from the Excel file. Ensure the file is a valid workbook.",
            )

    # 6. Tenant isolation
    tenant_id = _tenant_id_from_request(request)

    # 7. Persist to storage
    upload_id = str(uuid.uuid4())
    storage_path = _build_storage_path(tenant_id, client_name, upload_id, filename)

    try:
        storage_path.write_bytes(content)
    except OSError as exc:
        logger.error(
            "upload.storage_write_failed",
            path=str(storage_path),
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    # 8. Record metadata in in-memory registry
    file_type = _get_file_type(extension)
    _uploads_registry[upload_id] = {
        "upload_id": upload_id,
        "tenant_id": tenant_id,
        "client_name": client_name,
        "filename": filename,
        "size_bytes": len(content),
        "file_type": file_type,
        "sheets": sheets,
        "storage_path": str(storage_path),
        "status": "pending",
    }

    logger.info(
        "upload.received",
        upload_id=upload_id,
        tenant_id=tenant_id,
        client_name=client_name,
        filename=filename,
        size_bytes=len(content),
        file_type=file_type,
        sheets=sheets,
    )

    return UploadResponse(
        upload_id=upload_id,
        filename=filename,
        size_bytes=len(content),
        file_type=file_type,
        sheets=sheets,
        status="pending",
    )
