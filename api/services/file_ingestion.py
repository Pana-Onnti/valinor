"""
FileIngestionService — converts uploaded CSV/Excel files to SQLite (VAL-84).

Reads a raw uploaded file from storage, uses pandas to parse it, writes every
table into an in-memory SQLite database, then persists the .db file via
StorageManager.  Returns structured metadata (table names, column lists, row
counts) that the /process endpoint returns to the caller.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _normalise_table_name(raw: str) -> str:
    """
    Convert a sheet / file stem into a SQL-safe table name.

    Mirrors the normalisation used in core/valinor/tools/excel_tools.py so
    that downstream queries are consistent regardless of entry point.
    """
    return (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
        .strip("_")
    ) or "data"


class FileIngestionService:
    """Converts uploaded CSV/Excel files to SQLite for analysis.

    The service is stateless: each call to :meth:`convert_to_sqlite` is
    independent.  The StorageManager dependency is injected so it can be
    replaced in tests.
    """

    def __init__(self, storage_manager=None) -> None:
        if storage_manager is None:
            from api.services.storage_manager import StorageManager
            storage_manager = StorageManager()
        self.storage = storage_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert_to_sqlite(
        self,
        file_path: str,
        file_type: str,
        client_name: str,
        tenant_id: str,
        upload_id: str,
    ) -> Dict[str, Any]:
        """
        Convert an uploaded file to a SQLite database.

        Steps:
          1. Read the raw file bytes from *file_path*.
          2. Dispatch to the CSV or Excel parser (via pandas).
          3. Write all DataFrames into an in-memory SQLite database.
          4. Dump the .db bytes and persist via StorageManager.save_sqlite().
          5. Return a result dict describing the tables produced.

        Args:
            file_path:   Absolute path to the raw uploaded file.
            file_type:   One of "csv", "xlsx", "xls".
            client_name: Slug-safe client identifier (used for storage path).
            tenant_id:   Tenant UUID string (used for storage path).
            upload_id:   Upload UUID string (used as the .db filename stem).

        Returns:
            {
                "db_path": "/abs/path/to/{upload_id}.db",
                "tables": [
                    {
                        "name": "sheet_or_stem",
                        "row_count": int,
                        "columns": ["col1", "col2", ...],
                    },
                    ...
                ],
            }

        Raises:
            FileNotFoundError: If *file_path* does not exist.
            ValueError: If *file_type* is not supported.
            RuntimeError: If conversion or storage fails.
        """
        source = Path(file_path)
        if not source.exists():
            raise FileNotFoundError(f"Upload file not found: {file_path}")

        file_type = file_type.lower().lstrip(".")
        if file_type not in {"csv", "xlsx", "xls"}:
            raise ValueError(
                f"Unsupported file_type: {file_type!r}. "
                "Expected csv, xlsx, or xls."
            )

        # 1. Parse into {table_name: DataFrame}
        if file_type == "csv":
            frames = self._parse_csv(source)
        else:
            frames = self._parse_excel(source)

        # 2. Build SQLite in memory
        db_bytes = self._frames_to_sqlite_bytes(frames)

        # 3. Persist via StorageManager
        db_path = self.storage.save_sqlite(
            tenant_id=tenant_id,
            client_name=client_name,
            upload_id=upload_id,
            db_bytes=db_bytes,
        )

        # 4. Build table metadata from frames
        tables: List[Dict[str, Any]] = [
            {
                "name": table_name,
                "row_count": len(df),
                "columns": list(df.columns),
            }
            for table_name, df in frames.items()
        ]

        logger.info(
            "file_ingestion.converted tenant=%s client=%s upload_id=%s "
            "file_type=%s tables=%d db_path=%s",
            tenant_id,
            client_name,
            upload_id,
            file_type,
            len(tables),
            db_path,
        )

        return {
            "db_path": db_path,
            "tables": tables,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_csv(self, path: Path) -> Dict[str, Any]:
        """
        Parse a CSV file into a single-table dict.

        The table name is derived from the file stem.  Bad lines are skipped
        silently (mirrors csv_to_sqlite behaviour in excel_tools.py).
        """
        import pandas as pd

        table_name = _normalise_table_name(path.stem)
        df = pd.read_csv(str(path), encoding="utf-8", on_bad_lines="skip")
        return {table_name: df}

    def _parse_excel(self, path: Path) -> Dict[str, Any]:
        """
        Parse an Excel workbook into a dict of {table_name: DataFrame}.

        Each sheet becomes one table.  Sheet names are normalised in the same
        way as in excel_to_sqlite() in excel_tools.py.
        """
        import pandas as pd

        sheets: Dict[str, Any] = pd.read_excel(str(path), sheet_name=None)
        return {
            _normalise_table_name(sheet_name): df
            for sheet_name, df in sheets.items()
        }

    def _frames_to_sqlite_bytes(self, frames: Dict[str, Any]) -> bytes:
        """
        Write all DataFrames to an in-memory SQLite database and return the
        raw bytes of the resulting .db file.

        Using the undocumented but stable SQLite ``serialize`` method available
        since Python 3.11.  For older Pythons we fall back to writing a
        temporary file and reading it back.
        """
        import pandas as pd  # noqa: F401 (ensure import available)

        conn = sqlite3.connect(":memory:")
        try:
            for table_name, df in frames.items():
                df.to_sql(table_name, conn, if_exists="replace", index=False)

            # Python ≥ 3.11: sqlite3.Connection.serialize()
            if hasattr(conn, "serialize"):
                db_bytes: bytes = conn.serialize()
            else:
                # Fallback: dump to a temp file and read bytes
                with tempfile.NamedTemporaryFile(
                    suffix=".db", delete=False
                ) as tmp:
                    tmp_path = tmp.name

                try:
                    conn.close()
                    disk_conn = sqlite3.connect(tmp_path)
                    for table_name, df in frames.items():
                        df.to_sql(
                            table_name,
                            disk_conn,
                            if_exists="replace",
                            index=False,
                        )
                    disk_conn.close()
                    with open(tmp_path, "rb") as f:
                        db_bytes = f.read()
                    # conn already closed above — skip finally close
                    return db_bytes
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return db_bytes
