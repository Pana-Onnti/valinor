"""
ConnectorFactory — creates DeltaConnector instances by source type (VAL-33).

Usage:
    from shared.connectors import ConnectorFactory

    connector = ConnectorFactory.create("postgresql", {
        "connection_string": "postgresql+psycopg2://user:pass@localhost:5432/db"
    })
    connector.connect()
    schema = connector.get_schema()
    connector.close()

    # Or with context manager:
    with ConnectorFactory.create("etendo", config) as conn:
        rows = conn.execute_query("SELECT * FROM c_invoice LIMIT 10")
"""

from __future__ import annotations

from typing import Any, Dict, Type

from .base import DeltaConnector, SourceType


# Registry of available connectors
_CONNECTOR_REGISTRY: Dict[str, Type[DeltaConnector]] = {}


def _register_connectors() -> None:
    """Lazy import to avoid circular dependencies."""
    from .postgresql import PostgreSQLConnector
    from .mysql import MySQLConnector
    from .etendo import EtendoConnector
    from .sqlite import SQLiteConnector

    _CONNECTOR_REGISTRY.update({
        SourceType.POSTGRESQL.value: PostgreSQLConnector,
        SourceType.MYSQL.value: MySQLConnector,
        SourceType.ETENDO.value: EtendoConnector,
        SourceType.SQLITE.value: SQLiteConnector,
        # Aliases
        "postgres": PostgreSQLConnector,
        "pg": PostgreSQLConnector,
        "mariadb": MySQLConnector,
        "file": SQLiteConnector,
        "excel": SQLiteConnector,
        "csv": SQLiteConnector,
    })


class ConnectorFactory:
    """
    Factory for creating DeltaConnector instances.

    Supports all source types defined in SourceType enum plus common aliases.
    """

    @staticmethod
    def create(source_type: str, config: Dict[str, Any]) -> DeltaConnector:
        """
        Create a DeltaConnector for the given source type.

        Args:
            source_type: One of "postgresql", "mysql", "etendo", or aliases
                         ("postgres", "pg", "mariadb").
            config: Source-specific configuration dict.

        Returns:
            DeltaConnector instance (not yet connected — call .connect()).

        Raises:
            ValueError: If source_type is not supported.
        """
        if not _CONNECTOR_REGISTRY:
            _register_connectors()

        key = source_type.lower().strip()
        connector_class = _CONNECTOR_REGISTRY.get(key)

        if connector_class is None:
            supported = sorted(set(_CONNECTOR_REGISTRY.keys()))
            raise ValueError(
                f"Unsupported source_type: {source_type!r}. "
                f"Supported: {supported}"
            )

        return connector_class(config)

    @staticmethod
    def list_supported() -> list:
        """Return list of supported source type strings."""
        if not _CONNECTOR_REGISTRY:
            _register_connectors()
        return sorted(set(_CONNECTOR_REGISTRY.keys()))
