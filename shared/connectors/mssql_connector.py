"""
Microsoft SQL Server connector (VAL-122).

Wraps SQLAlchemy with pymssql driver for SQL Server databases
(SQL Server 2017+, Azure SQL, SQL Server Express).

Config keys:
    connection_string (required): SQLAlchemy DSN, e.g.
        "mssql+pymssql://user:pass@host:1433/ERPDB"
    schema (optional): Default schema to inspect (default "dbo")
    max_rows (optional): Default max rows per query (default 10,000)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from .base import DeltaConnector, SourceType

logger = structlog.get_logger()


class MSSQLConnector(DeltaConnector):
    """
    Generic Microsoft SQL Server connector.

    Supports SQL Server 2017+, SQL Server Express, and Azure SQL
    via SQLAlchemy + pymssql driver (no ODBC driver required).
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._engine = None
        self._default_schema: str = config.get("schema", "dbo")

    @property
    def source_type(self) -> SourceType:
        return SourceType.MSSQL

    def connect(self) -> None:
        """Create SQLAlchemy engine and verify connectivity."""
        from sqlalchemy import create_engine, text as sa_text

        conn_str = self.config.get("connection_string", "")
        if not conn_str:
            raise ConnectionError("connection_string is required for MSSQLConnector")

        # Ensure pymssql driver is specified
        if conn_str.startswith("mssql://"):
            conn_str = conn_str.replace("mssql://", "mssql+pymssql://", 1)

        try:
            self._engine = create_engine(conn_str)
            # Verify connectivity
            with self._engine.connect() as conn:
                conn.execute(sa_text("SELECT 1"))
            self._connected = True
            logger.info("mssql.connect", host=self._parse_host(conn_str))
        except Exception as exc:
            self._engine = None
            self._connected = False
            raise ConnectionError(f"SQL Server connection failed: {exc}") from exc

    def close(self) -> None:
        """Dispose engine and release connections."""
        if self._engine:
            try:
                self._engine.dispose()
                logger.info("mssql.close")
            except OSError as exc:
                logger.warning("mssql.close failed", error=str(exc))
        self._engine = None
        self._connected = False

    def execute_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        max_rows: int = 10_000,
    ) -> List[Dict[str, Any]]:
        """Execute a read-only SELECT and return results as list of dicts."""
        self._require_connected()
        self._require_select(sql)

        from sqlalchemy import text as sa_text

        max_rows = min(max_rows, self.config.get("max_rows", 10_000))

        with self._engine.connect() as conn:
            result = conn.execute(sa_text(sql), params or {})
            cols = list(result.keys())
            rows = result.fetchmany(max_rows)
            return [dict(zip(cols, row)) for row in rows]

    def get_schema(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieve table and column metadata from the SQL Server database.

        Returns a schema dict compatible with the Cartographer's entity_map format.
        """
        self._require_connected()

        from sqlalchemy import inspect as sa_inspect

        target_schema = schema_name or self._default_schema
        inspector = sa_inspect(self._engine)

        table_names = inspector.get_table_names(schema=target_schema)

        # Batch-fetch all row counts in a single query
        row_counts = self._estimate_all_row_counts(table_names, target_schema)

        tables = {}
        for table_name in table_names:
            try:
                cols = inspector.get_columns(table_name, schema=target_schema)
                column_info = [
                    {"name": c["name"], "type": str(c["type"])}
                    for c in cols
                ]

                tables[table_name] = {
                    "columns": column_info,
                    "row_count": row_counts.get(table_name, 0),
                }
            except Exception as exc:
                logger.warning("mssql.get_schema.table_failed", table=table_name, error=str(exc))

        return {
            "tables": tables,
            "source_type": self.source_type.value,
            "schema": target_schema,
        }

    def _estimate_all_row_counts(
        self, table_names: List[str], schema: str,
    ) -> Dict[str, int]:
        """Estimate row counts for all tables via sys.dm_db_partition_stats."""
        if not table_names:
            return {}
        try:
            from sqlalchemy import text as sa_text
            # Build IN clause with positional placeholders
            placeholders = ", ".join(f":t{i}" for i in range(len(table_names)))
            sql = (
                "SELECT t.name, SUM(p.rows) AS row_count "
                "FROM sys.tables t "
                "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                "JOIN sys.dm_db_partition_stats p ON p.object_id = t.object_id "
                "WHERE p.index_id IN (0, 1) "
                "  AND s.name = :schema "
                f"  AND t.name IN ({placeholders}) "
                "GROUP BY t.name"
            )
            bind: Dict[str, Any] = {f"t{i}": name for i, name in enumerate(table_names)}
            bind["schema"] = schema

            with self._engine.connect() as conn:
                result = conn.execute(sa_text(sql), bind)
                return {
                    row[0]: max(int(row[1]), 0) for row in result.fetchall()
                }
        except Exception:
            return {}

    @staticmethod
    def _parse_host(conn_str: str) -> str:
        """Extract host from connection string for logging (no password)."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(conn_str)
            return parsed.hostname or "unknown"
        except Exception:
            return "unknown"
