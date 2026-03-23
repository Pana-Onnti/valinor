"""
DeltaConnector — Abstract base class for all Valinor data source connectors (VAL-33).

Built on top of dlt (Data Load Tool) pipeline primitives.
All concrete connectors (PostgreSQL, MySQL, Etendo, ...) subclass this.

Design:
- connect() / close() — lifecycle management
- execute_query() — read-only SQL execution
- get_schema() — returns table/column metadata
- The existing agents (Cartographer, DataQualityGate, etc.) are NOT modified.
  They consume DeltaConnector instances just like they consumed SQLAlchemy engines.
"""

from __future__ import annotations

import abc
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceType(str, Enum):
    """Supported data source types."""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    ETENDO = "etendo"
    SQLITE = "sqlite"


class DeltaConnector(abc.ABC):
    """
    Abstract base class for all Valinor data connectors.

    Lifecycle:
        connector = ConnectorFactory.create("postgresql", config)
        connector.connect()
        schema = connector.get_schema()
        rows = connector.execute_query("SELECT 1")
        connector.close()

    Or as a context manager:
        with ConnectorFactory.create("postgresql", config) as connector:
            schema = connector.get_schema()
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: Source-specific configuration dict. See subclass docs for keys.
        """
        self.config = config
        self._connected: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def connect(self) -> None:
        """
        Establish a connection to the data source.

        Raises:
            ConnectionError: If connection cannot be established.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """
        Close the connection and release all resources.
        Safe to call even if not connected.
        """

    def __enter__(self) -> "DeltaConnector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ── Query ─────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def execute_query(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
        max_rows: int = 10_000,
    ) -> List[Dict[str, Any]]:
        """
        Execute a read-only SQL query and return results as a list of dicts.

        Args:
            sql: SQL SELECT statement.
            params: Optional bind parameters.
            max_rows: Maximum rows to fetch (default 10,000).

        Returns:
            List of row dicts: [{"col": val, ...}, ...]

        Raises:
            RuntimeError: If not connected.
            ValueError: If SQL is not a SELECT statement.
        """

    # ── Schema ────────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def get_schema(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieve schema metadata from the data source.

        Args:
            schema_name: Database schema to inspect (optional, source-dependent).

        Returns:
            {
                "tables": {
                    "table_name": {
                        "columns": [{"name": ..., "type": ...}, ...],
                        "row_count": int,
                    },
                    ...
                },
                "source_type": "postgresql",
            }
        """

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def source_type(self) -> SourceType:
        raise NotImplementedError

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _require_connected(self) -> None:
        """Raise RuntimeError if not connected."""
        if not self._connected:
            raise RuntimeError(
                f"{self.__class__.__name__} is not connected. Call connect() first."
            )

    def _require_select(self, sql: str) -> None:
        """Raise ValueError if SQL is not a SELECT statement."""
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
            raise ValueError(
                f"Only SELECT / WITH statements are allowed. Got: {sql[:50]!r}"
            )
