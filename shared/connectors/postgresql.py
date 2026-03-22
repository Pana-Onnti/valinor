"""
PostgreSQL generic connector (VAL-33).

Wraps SQLAlchemy for execution and dlt for optional pipeline/ingestion.
Supports any PostgreSQL-compatible database (Postgres, CockroachDB, etc.).

Config keys:
    connection_string (required): SQLAlchemy DSN, e.g.
        "postgresql+psycopg2://user:pass@host:5432/dbname"
    schema (optional): Default schema to inspect (default "public")
    max_rows (optional): Default max rows per query (default 10,000)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from .base import DeltaConnector, SourceType

logger = structlog.get_logger()


class PostgreSQLConnector(DeltaConnector):
    """
    Generic PostgreSQL connector.

    All agents that previously used SQLAlchemy create_engine() directly
    can be migrated to use this connector for a unified interface.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._engine = None
        self._default_schema: str = config.get("schema", "public")

    @property
    def source_type(self) -> SourceType:
        return SourceType.POSTGRESQL

    def connect(self) -> None:
        """Create SQLAlchemy engine and verify connectivity."""
        from sqlalchemy import create_engine, text as sa_text

        conn_str = self.config.get("connection_string", "")
        if not conn_str:
            raise ConnectionError("connection_string is required for PostgreSQLConnector")

        try:
            self._engine = create_engine(conn_str)
            # Verify connectivity
            with self._engine.connect() as conn:
                conn.execute(sa_text("SELECT 1"))
            self._connected = True
            logger.info("postgresql.connect", host=self._parse_host(conn_str))
        except Exception as exc:
            self._engine = None
            self._connected = False
            raise ConnectionError(f"PostgreSQL connection failed: {exc}") from exc

    def close(self) -> None:
        """Dispose engine and release connections."""
        if self._engine:
            try:
                self._engine.dispose()
                logger.info("postgresql.close")
            except OSError as exc:
                logger.warning("postgresql.close failed", error=str(exc))
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
        Retrieve table and column metadata from the PostgreSQL database.

        Returns a schema dict compatible with the Cartographer's entity_map format.
        """
        self._require_connected()

        from sqlalchemy import inspect as sa_inspect

        target_schema = schema_name or self._default_schema
        inspector = sa_inspect(self._engine)

        tables = {}
        for table_name in inspector.get_table_names(schema=target_schema):
            try:
                cols = inspector.get_columns(table_name, schema=target_schema)
                column_info = [
                    {"name": c["name"], "type": str(c["type"])}
                    for c in cols
                ]

                # Approximate row count
                row_count = self._estimate_row_count(table_name, target_schema)

                tables[table_name] = {
                    "columns": column_info,
                    "row_count": row_count,
                }
            except Exception as exc:
                logger.warning("postgresql.get_schema.table_failed", table=table_name, error=str(exc))

        return {
            "tables": tables,
            "source_type": self.source_type.value,
            "schema": target_schema,
        }

    def _estimate_row_count(self, table_name: str, schema: str) -> int:
        """Estimate row count using pg_class for speed (no full table scan)."""
        try:
            from sqlalchemy import text as sa_text
            with self._engine.connect() as conn:
                result = conn.execute(
                    sa_text(
                        "SELECT reltuples::bigint FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE c.relname = :table AND n.nspname = :schema"
                    ),
                    {"table": table_name, "schema": schema},
                )
                row = result.fetchone()
                return int(row[0]) if row and row[0] else 0
        except Exception:
            return 0

    @staticmethod
    def _parse_host(conn_str: str) -> str:
        """Extract host from connection string for logging (no password)."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(conn_str)
            return parsed.hostname or "unknown"
        except Exception:
            return "unknown"
