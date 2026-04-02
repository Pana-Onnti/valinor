"""
SQLite connector for uploaded CSV/Excel files (VAL-84).

Used after FileIngestionService has converted a raw upload to a .db file.
Provides the same DeltaConnector interface as the PostgreSQL/MySQL connectors
so that all downstream agents (Cartographer, DataQualityGate, …) can consume
SQLite sources transparently.

Config keys:
    db_path (required): Absolute filesystem path to the .db file.
    max_rows (optional): Default max rows per query (default 10,000).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from .base import DeltaConnector, SourceType

logger = structlog.get_logger()


class SQLiteConnector(DeltaConnector):
    """
    Connector for SQLite databases generated from uploaded CSV/Excel files.

    Each instance wraps a single .db file produced by FileIngestionService.
    Connection is a plain ``sqlite3`` connection (thread-check disabled so
    the connection can be used from FastAPI/Celery worker threads).

    Aliases recognised by ConnectorFactory: sqlite, file, excel, csv.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.SQLITE

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """
        Open the SQLite database file.

        Raises:
            ConnectionError: If db_path is missing, the file does not exist,
                             or sqlite3 cannot open it.
        """
        db_path = self.config.get("db_path", "")
        if not db_path:
            raise ConnectionError("db_path is required for SQLiteConnector")

        path = Path(db_path)
        if not path.exists():
            raise ConnectionError(f"SQLite database file not found: {db_path}")

        try:
            # check_same_thread=False: safe for read-only workloads in async/
            # Celery contexts; we never write after connect().
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            # Validate the file is a real SQLite database
            self._conn.execute("SELECT 1")
            self._connected = True
            logger.info("sqlite.connect", db_path=db_path)
        except sqlite3.DatabaseError as exc:
            self._conn = None
            self._connected = False
            raise ConnectionError(f"SQLite connection failed: {exc}") from exc

    def close(self) -> None:
        """Close the SQLite connection and release resources."""
        if self._conn is not None:
            try:
                self._conn.close()
                logger.info("sqlite.close")
            except sqlite3.Error as exc:
                logger.warning("sqlite.close failed", error=str(exc))
        self._conn = None
        self._connected = False

    # ── Query ─────────────────────────────────────────────────────────────────

    def execute_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        max_rows: int = 10_000,
    ) -> List[Dict[str, Any]]:
        """
        Execute a read-only SELECT query and return results as list of dicts.

        Args:
            sql: SQL SELECT (or WITH …) statement.
            params: Optional bind parameters (dict — mapped to :key notation).
            max_rows: Maximum rows to fetch.

        Returns:
            List of row dicts: [{"col": val, ...}, ...]

        Raises:
            RuntimeError: If not connected.
            ValueError: If SQL is not a SELECT/WITH statement.
        """
        self._require_connected()
        self._require_select(sql)

        effective_max = min(max_rows, self.config.get("max_rows", 10_000))

        cursor = self._conn.execute(sql, params or {})
        col_names = [desc[0] for desc in cursor.description]
        rows = cursor.fetchmany(effective_max)
        return [dict(zip(col_names, row)) for row in rows]

    # ── Schema ────────────────────────────────────────────────────────────────

    def get_schema(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Introspect table and column metadata from the SQLite database.

        ``schema_name`` is ignored (SQLite has no named schemas in the
        multi-schema sense); it is accepted for interface compatibility.

        Returns:
            {
                "tables": {
                    "table_name": {
                        "columns": [{"name": ..., "type": ...}, ...],
                        "row_count": int,
                    },
                    ...
                },
                "source_type": "sqlite",
                "db_path": "/abs/path/to/file.db",
            }
        """
        self._require_connected()

        # List all user tables (exclude SQLite internal tables)
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = [row[0] for row in cursor.fetchall()]

        tables: Dict[str, Any] = {}
        for table_name in table_names:
            try:
                # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
                col_cursor = self._conn.execute(f"PRAGMA table_info({table_name!r})")
                columns = [
                    {"name": row[1], "type": row[2] or "TEXT"}
                    for row in col_cursor.fetchall()
                ]

                count_cursor = self._conn.execute(
                    f"SELECT COUNT(*) FROM {table_name!r}"  # noqa: S608
                )
                row_count = count_cursor.fetchone()[0]

                tables[table_name] = {
                    "columns": columns,
                    "row_count": row_count,
                }
            except sqlite3.Error as exc:
                logger.warning(
                    "sqlite.get_schema.table_failed",
                    table=table_name,
                    error=str(exc),
                )

        return {
            "tables": tables,
            "source_type": self.source_type.value,
            "db_path": self.config.get("db_path", ""),
        }
