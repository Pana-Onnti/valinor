"""
Tests for the DeltaConnector layer (VAL-33).

All tests use mocks — no real database connections required.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.connectors.base import DeltaConnector, SourceType
from shared.connectors.factory import ConnectorFactory


# ── Base class tests ──────────────────────────────────────────────────────────

class TestDeltaConnectorBase:
    def test_require_select_allows_select(self):
        """_require_select allows SELECT statements."""
        from shared.connectors.postgresql import PostgreSQLConnector
        conn = PostgreSQLConnector.__new__(PostgreSQLConnector)
        conn._require_select("SELECT 1")  # Should not raise

    def test_require_select_allows_with(self):
        """_require_select allows WITH (CTE) statements."""
        from shared.connectors.postgresql import PostgreSQLConnector
        conn = PostgreSQLConnector.__new__(PostgreSQLConnector)
        conn._require_select("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_require_select_rejects_insert(self):
        """_require_select rejects INSERT."""
        from shared.connectors.postgresql import PostgreSQLConnector
        conn = PostgreSQLConnector.__new__(PostgreSQLConnector)
        with pytest.raises(ValueError, match="SELECT"):
            conn._require_select("INSERT INTO t VALUES (1)")

    def test_require_select_rejects_delete(self):
        """_require_select rejects DELETE."""
        from shared.connectors.postgresql import PostgreSQLConnector
        conn = PostgreSQLConnector.__new__(PostgreSQLConnector)
        with pytest.raises(ValueError):
            conn._require_select("DELETE FROM t")

    def test_require_connected_raises_when_not_connected(self):
        """_require_connected raises RuntimeError when not connected."""
        from shared.connectors.postgresql import PostgreSQLConnector
        conn = PostgreSQLConnector.__new__(PostgreSQLConnector)
        conn._connected = False
        with pytest.raises(RuntimeError, match="not connected"):
            conn._require_connected()

    def test_context_manager(self):
        """DeltaConnector works as context manager."""
        from shared.connectors.postgresql import PostgreSQLConnector

        conn = PostgreSQLConnector.__new__(PostgreSQLConnector)
        conn.connect = MagicMock()
        conn.close = MagicMock()

        with conn:
            conn.connect.assert_called_once()

        conn.close.assert_called_once()


# ── PostgreSQLConnector tests ─────────────────────────────────────────────────

class TestPostgreSQLConnector:
    def test_source_type(self):
        """PostgreSQLConnector has correct source_type."""
        from shared.connectors.postgresql import PostgreSQLConnector
        conn = PostgreSQLConnector({"connection_string": "postgresql://x"})
        assert conn.source_type == SourceType.POSTGRESQL

    def test_connect_raises_without_connection_string(self):
        """connect() raises ConnectionError without connection_string."""
        from shared.connectors.postgresql import PostgreSQLConnector
        conn = PostgreSQLConnector({})
        with pytest.raises(ConnectionError, match="connection_string"):
            conn.connect()

    @patch("sqlalchemy.create_engine")
    def test_connect_success(self, mock_create_engine):
        """connect() sets _connected = True on success."""
        from shared.connectors.postgresql import PostgreSQLConnector

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        connector = PostgreSQLConnector({"connection_string": "postgresql://localhost/test"})
        connector.connect()

        assert connector.is_connected

    @patch("sqlalchemy.create_engine")
    def test_execute_query_returns_rows(self, mock_create_engine):
        """execute_query() returns list of dicts."""
        from shared.connectors.postgresql import PostgreSQLConnector

        mock_result = MagicMock()
        mock_result.keys.return_value = ["id", "name"]
        mock_result.fetchmany.return_value = [(1, "Acme"), (2, "Globex")]

        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        connector = PostgreSQLConnector({"connection_string": "postgresql://localhost/test"})
        connector._connected = True
        connector._engine = mock_engine

        rows = connector.execute_query("SELECT id, name FROM customers")
        assert isinstance(rows, list)

    def test_execute_query_rejects_non_select(self):
        """execute_query() rejects non-SELECT statements."""
        from shared.connectors.postgresql import PostgreSQLConnector

        connector = PostgreSQLConnector({"connection_string": "postgresql://localhost/test"})
        connector._connected = True
        connector._engine = MagicMock()

        with pytest.raises(ValueError):
            connector.execute_query("DROP TABLE customers")

    @patch("sqlalchemy.create_engine")
    def test_get_schema_returns_tables(self, mock_create_engine):
        """get_schema() returns table metadata."""
        from shared.connectors.postgresql import PostgreSQLConnector

        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["c_invoice", "c_bpartner"]
        mock_inspector.get_columns.return_value = [
            {"name": "id", "type": MagicMock(__str__=lambda s: "INTEGER")},
        ]

        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        connector = PostgreSQLConnector({"connection_string": "postgresql://localhost/test"})
        connector._connected = True
        connector._engine = mock_engine
        connector._default_schema = "public"

        # Mock pg_class row count query
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (1000,)
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_result
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_engine.connect.return_value = mock_conn

        with patch("sqlalchemy.inspect", return_value=mock_inspector):
            schema = connector.get_schema()

        assert "tables" in schema
        assert schema["source_type"] == "postgresql"


# ── MySQLConnector tests ──────────────────────────────────────────────────────

class TestMySQLConnector:
    def test_source_type(self):
        """MySQLConnector has correct source_type."""
        from shared.connectors.mysql import MySQLConnector
        conn = MySQLConnector({"connection_string": "mysql://x"})
        assert conn.source_type == SourceType.MYSQL

    def test_connect_raises_without_connection_string(self):
        """connect() raises ConnectionError without connection_string."""
        from shared.connectors.mysql import MySQLConnector
        conn = MySQLConnector({})
        with pytest.raises(ConnectionError):
            conn.connect()

    def test_execute_query_rejects_update(self):
        """execute_query() rejects UPDATE statements."""
        from shared.connectors.mysql import MySQLConnector

        connector = MySQLConnector({"connection_string": "mysql://localhost/db"})
        connector._connected = True

        with pytest.raises(ValueError):
            connector.execute_query("UPDATE t SET x = 1")


# ── Factory tests ─────────────────────────────────────────────────────────────

class TestConnectorFactory:
    def test_create_postgresql(self):
        """Factory creates PostgreSQLConnector for 'postgresql'."""
        from shared.connectors.postgresql import PostgreSQLConnector

        connector = ConnectorFactory.create("postgresql", {"connection_string": "pg://x"})
        assert isinstance(connector, PostgreSQLConnector)

    def test_create_postgres_alias(self):
        """Factory creates PostgreSQLConnector for 'postgres' alias."""
        from shared.connectors.postgresql import PostgreSQLConnector

        connector = ConnectorFactory.create("postgres", {"connection_string": "pg://x"})
        assert isinstance(connector, PostgreSQLConnector)

    def test_create_mysql(self):
        """Factory creates MySQLConnector for 'mysql'."""
        from shared.connectors.mysql import MySQLConnector

        connector = ConnectorFactory.create("mysql", {"connection_string": "mysql://x"})
        assert isinstance(connector, MySQLConnector)

    def test_create_mariadb_alias(self):
        """Factory creates MySQLConnector for 'mariadb' alias."""
        from shared.connectors.mysql import MySQLConnector

        connector = ConnectorFactory.create("mariadb", {"connection_string": "mysql://x"})
        assert isinstance(connector, MySQLConnector)

    def test_create_etendo(self):
        """Factory creates EtendoConnector for 'etendo'."""
        from shared.connectors.etendo import EtendoConnector

        connector = ConnectorFactory.create("etendo", {
            "connection_string": "postgresql://x",
            "ssh_host": "bastion",
            "ssh_user": "user",
            "ssh_key_path": "/key",
        })
        assert isinstance(connector, EtendoConnector)

    def test_create_unsupported_raises(self):
        """Factory raises ValueError for unsupported source type."""
        with pytest.raises(ValueError, match="Unsupported"):
            ConnectorFactory.create("oracle", {})

    def test_list_supported(self):
        """list_supported() returns all registered source types."""
        supported = ConnectorFactory.list_supported()
        assert "postgresql" in supported
        assert "mysql" in supported
        assert "etendo" in supported
        assert "postgres" in supported


# ── EtendoConnector unit tests (no SSH) ──────────────────────────────────────

class TestEtendoConnector:
    def test_source_type(self):
        """EtendoConnector has ETENDO source_type."""
        from shared.connectors.etendo import EtendoConnector
        conn = EtendoConnector({
            "connection_string": "postgresql://x",
            "ssh_host": "h",
            "ssh_user": "u",
            "ssh_key_path": "/k",
        })
        assert conn.source_type == SourceType.ETENDO

    def test_connect_raises_without_ssh_config(self):
        """connect() raises when SSH config is incomplete."""
        from shared.connectors.etendo import EtendoConnector
        conn = EtendoConnector({"connection_string": "postgresql://x"})
        with pytest.raises(ConnectionError, match="ssh_host"):
            conn.connect()

    def test_extract_host(self):
        """_extract_host parses hostname from DSN."""
        from shared.connectors.etendo import EtendoConnector
        host = EtendoConnector._extract_host("postgresql://user:pass@db.internal:5432/etendo")
        assert host == "db.internal"
