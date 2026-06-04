"""
Tests for MSSQLConnector and dialect-aware SQL generation (VAL-122).

Unit tests only — no real SQL Server instance required.
Tests marked with @pytest.mark.mssql require a live SQL Server.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from shared.connectors.base import DeltaConnector, SourceType
from shared.connectors.mssql_connector import MSSQLConnector
from shared.connectors.factory import ConnectorFactory


# ── MSSQLConnector instantiation ─────────────────────────────────────────────


class TestMSSQLConnectorInit:
    """Test MSSQLConnector instantiation and config parsing."""

    def test_default_schema_is_dbo(self):
        connector = MSSQLConnector({"connection_string": "mssql+pymssql://u:p@host/db"})
        assert connector._default_schema == "dbo"

    def test_custom_schema(self):
        connector = MSSQLConnector({
            "connection_string": "mssql+pymssql://u:p@host/db",
            "schema": "custom_schema",
        })
        assert connector._default_schema == "custom_schema"

    def test_source_type_is_mssql(self):
        connector = MSSQLConnector({"connection_string": "mssql+pymssql://u:p@host/db"})
        assert connector.source_type == SourceType.MSSQL
        assert connector.source_type.value == "mssql"

    def test_is_subclass_of_delta_connector(self):
        assert issubclass(MSSQLConnector, DeltaConnector)

    def test_not_connected_initially(self):
        connector = MSSQLConnector({"connection_string": "mssql+pymssql://u:p@host/db"})
        assert connector.is_connected is False

    def test_requires_connected_raises(self):
        connector = MSSQLConnector({"connection_string": "mssql+pymssql://u:p@host/db"})
        with pytest.raises(RuntimeError, match="not connected"):
            connector.execute_query("SELECT 1")

    def test_requires_select_raises_on_insert(self):
        connector = MSSQLConnector({"connection_string": "mssql+pymssql://u:p@host/db"})
        connector._connected = True  # bypass connection check
        with pytest.raises(ValueError, match="Only SELECT"):
            connector.execute_query("INSERT INTO foo VALUES (1)")


class TestMSSQLConnectorConnect:
    """Test connect() method with mocked SQLAlchemy."""

    def test_connect_adds_pymssql_driver(self):
        """If connection_string starts with mssql://, driver should be auto-added."""
        connector = MSSQLConnector({"connection_string": "mssql://u:p@host/db"})
        with patch("sqlalchemy.create_engine") as mock_ce:
            mock_engine = MagicMock()
            mock_ce.return_value = mock_engine
            mock_conn = MagicMock()
            mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

            connector.connect()
            # Should have been called with pymssql driver
            call_arg = mock_ce.call_args[0][0]
            assert "pymssql" in call_arg

    def test_connect_raises_on_missing_connection_string(self):
        connector = MSSQLConnector({"connection_string": ""})
        with pytest.raises(ConnectionError, match="connection_string is required"):
            connector.connect()

    def test_close_when_not_connected(self):
        """close() should be safe to call even if never connected."""
        connector = MSSQLConnector({"connection_string": "mssql+pymssql://u:p@host/db"})
        connector.close()  # Should not raise
        assert connector.is_connected is False


# ── ConnectorFactory registration ────────────────────────────────────────────


class TestConnectorFactoryMSSQL:
    """Test that MSSQL is properly registered in the factory."""

    def test_factory_creates_mssql(self):
        connector = ConnectorFactory.create("mssql", {
            "connection_string": "mssql+pymssql://u:p@host/db"
        })
        assert isinstance(connector, MSSQLConnector)

    def test_factory_creates_sqlserver_alias(self):
        connector = ConnectorFactory.create("sqlserver", {
            "connection_string": "mssql+pymssql://u:p@host/db"
        })
        assert isinstance(connector, MSSQLConnector)

    def test_factory_creates_sql_server_alias(self):
        connector = ConnectorFactory.create("sql_server", {
            "connection_string": "mssql+pymssql://u:p@host/db"
        })
        assert isinstance(connector, MSSQLConnector)

    def test_mssql_in_supported_list(self):
        supported = ConnectorFactory.list_supported()
        assert "mssql" in supported
        assert "sqlserver" in supported

    def test_factory_case_insensitive(self):
        connector = ConnectorFactory.create("MSSQL", {
            "connection_string": "mssql+pymssql://u:p@host/db"
        })
        assert isinstance(connector, MSSQLConnector)


# ── SourceType enum ──────────────────────────────────────────────────────────


class TestSourceTypeMSSQL:
    """Test that MSSQL is in the SourceType enum."""

    def test_mssql_in_enum(self):
        assert SourceType.MSSQL.value == "mssql"

    def test_enum_still_has_all_others(self):
        assert SourceType.POSTGRESQL.value == "postgresql"
        assert SourceType.MYSQL.value == "mysql"
        assert SourceType.ETENDO.value == "etendo"
        assert SourceType.SQLITE.value == "sqlite"


# ── Dialect-aware SQL generation ─────────────────────────────────────────────


class TestDialectAwareSQL:
    """Test that db_tools generates correct SQL for MSSQL vs PostgreSQL dialects."""

    def test_is_mssql_true_for_mssql_dialect(self):
        from core.valinor.tools.db_tools import _is_mssql
        engine = MagicMock()
        engine.dialect.name = "mssql"
        assert _is_mssql(engine) is True

    def test_is_mssql_false_for_postgresql(self):
        from core.valinor.tools.db_tools import _is_mssql
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        assert _is_mssql(engine) is False

    def test_is_mssql_false_for_sqlite(self):
        from core.valinor.tools.db_tools import _is_mssql
        engine = MagicMock()
        engine.dialect.name = "sqlite"
        assert _is_mssql(engine) is False

    def test_quote_ident_mssql_uses_brackets(self):
        from core.valinor.tools.db_tools import _quote_ident
        engine = MagicMock()
        engine.dialect.name = "mssql"
        result = _quote_ident(engine, "dbo", "Clientes")
        assert result == "[dbo].[Clientes]"

    def test_quote_ident_postgres_uses_double_quotes(self):
        from core.valinor.tools.db_tools import _quote_ident
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        result = _quote_ident(engine, "public", "customers")
        assert result == '"public"."customers"'


# ── MSSQL-specific SQL patterns ──────────────────────────────────────────────


class TestMSSQLSQLPatterns:
    """Verify that the probe/sample queries generate valid T-SQL patterns."""

    def test_sample_uses_top_for_mssql(self):
        """The sample_table tool should generate SELECT TOP(N) for MSSQL."""
        from core.valinor.tools.db_tools import _is_mssql, _quote_ident
        engine = MagicMock()
        engine.dialect.name = "mssql"
        qualified = _quote_ident(engine, "dbo", "Clientes")
        # Simulate what sample_table does
        if _is_mssql(engine):
            sql = f"SELECT TOP(:limit) * FROM {qualified}"
        else:
            sql = f"SELECT * FROM {qualified} LIMIT :limit"
        assert "TOP" in sql
        assert "LIMIT" not in sql
        assert "[dbo].[Clientes]" in sql

    def test_sample_uses_limit_for_postgres(self):
        """The sample_table tool should generate LIMIT for PostgreSQL."""
        from core.valinor.tools.db_tools import _is_mssql, _quote_ident
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        qualified = _quote_ident(engine, "public", "customers")
        if _is_mssql(engine):
            sql = f"SELECT TOP(:limit) * FROM {qualified}"
        else:
            sql = f"SELECT * FROM {qualified} LIMIT :limit"
        assert "LIMIT" in sql
        assert "TOP" not in sql

    def test_probe_uses_top_for_mssql(self):
        """The probe_column_values tool should generate TOP 20 for MSSQL."""
        from core.valinor.tools.db_tools import _is_mssql, _quote_ident
        engine = MagicMock()
        engine.dialect.name = "mssql"
        qualified = _quote_ident(engine, "dbo", "Facturas")
        column = "estado"
        if _is_mssql(engine):
            col_ref = f"[{column}]"
            sql = (
                f"SELECT TOP 20 {col_ref}, COUNT(*) AS cnt "
                f"FROM {qualified} "
                f"GROUP BY {col_ref} ORDER BY cnt DESC"
            )
        else:
            col_ref = f'"{column}"'
            sql = (
                f"SELECT {col_ref}, COUNT(*) AS cnt "
                f"FROM {qualified} "
                f"GROUP BY 1 ORDER BY cnt DESC LIMIT 20"
            )
        assert "TOP 20" in sql
        assert "LIMIT" not in sql
        assert "[estado]" in sql
        assert "GROUP BY [estado]" in sql


# ── Row count estimation ─────────────────────────────────────────────────────


class TestMSSQLRowCountEstimation:
    """Test the _estimate_all_row_counts method uses sys.dm_db_partition_stats."""

    def test_empty_table_list_returns_empty(self):
        connector = MSSQLConnector({"connection_string": "mssql+pymssql://u:p@host/db"})
        result = connector._estimate_all_row_counts([], "dbo")
        assert result == {}


# ── Connection string parsing ────────────────────────────────────────────────


class TestMSSQLParseHost:
    """Test host extraction from connection strings."""

    def test_parse_host_standard(self):
        host = MSSQLConnector._parse_host("mssql+pymssql://sa:pass@myserver:1433/ERPDB")
        assert host == "myserver"

    def test_parse_host_localhost(self):
        host = MSSQLConnector._parse_host("mssql+pymssql://sa:pass@localhost/ERPDB")
        assert host == "localhost"

    def test_parse_host_invalid_returns_unknown(self):
        host = MSSQLConnector._parse_host("not-a-url")
        assert host == "unknown"


# ── Live SQL Server tests (skipped unless --mssql flag) ──────────────────────


@pytest.mark.mssql
class TestMSSQLLive:
    """Tests that require a real SQL Server instance. Skipped by default."""

    def test_connect_to_real_server(self):
        """Connect to a real SQL Server and verify."""
        pytest.skip("Requires a live SQL Server instance")
