"""
Valinor connector layer — VAL-33.

Provides a unified abstraction over multiple database sources,
built on top of dlt (Data Load Tool).

Available connectors:
- PostgreSQLConnector  — generic PostgreSQL
- MySQLConnector       — generic MySQL
- EtendoConnector      — Etendo ERP via PostgreSQL + SSH tunnel

Use ConnectorFactory.create(source_type, config) to get a connector.
"""

from .base import DeltaConnector, SourceType
from .postgresql import PostgreSQLConnector
from .mysql import MySQLConnector
from .etendo import EtendoConnector
from .factory import ConnectorFactory

__all__ = [
    "DeltaConnector",
    "SourceType",
    "PostgreSQLConnector",
    "MySQLConnector",
    "EtendoConnector",
    "ConnectorFactory",
]
