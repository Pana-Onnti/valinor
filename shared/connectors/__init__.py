"""
Valinor connector layer — VAL-33.

Provides a unified abstraction over multiple database sources,
built on top of dlt (Data Load Tool).

Available connectors:
- PostgreSQLConnector  — generic PostgreSQL
- MySQLConnector       — generic MySQL
- EtendoConnector      — Etendo ERP via PostgreSQL + SSH tunnel
- SQLiteConnector      — SQLite databases from uploaded CSV/Excel files (VAL-84)

Use ConnectorFactory.create(source_type, config) to get a connector.
"""

from .base import DeltaConnector, SourceType
from .postgresql import PostgreSQLConnector
from .mysql import MySQLConnector
from .etendo import EtendoConnector
from .sqlite import SQLiteConnector
from .factory import ConnectorFactory

__all__ = [
    "DeltaConnector",
    "SourceType",
    "PostgreSQLConnector",
    "MySQLConnector",
    "EtendoConnector",
    "SQLiteConnector",
    "ConnectorFactory",
]
