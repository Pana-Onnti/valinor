"""
Tests for core/valinor/tools/db_tools.py

Covers: connect_database, introspect_schema, sample_table,
        probe_column_values, classify_entity
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Stub claude_agent_sdk before any core imports
# ---------------------------------------------------------------------------
if "claude_agent_sdk" not in sys.modules:
    _sdk = types.ModuleType("claude_agent_sdk")
    _sdk.__spec__ = None

    def _tool_stub(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f

    _sdk.tool = _tool_stub
    _sdk.query = MagicMock()
    _sdk.ClaudeAgentOptions = MagicMock
    _sdk.AssistantMessage = MagicMock
    _sdk.TextBlock = MagicMock
    _sdk.create_sdk_mcp_server = MagicMock(return_value=MagicMock())
    sys.modules["claude_agent_sdk"] = _sdk

from valinor.tools.db_tools import (
    classify_entity,
    connect_database,
    introspect_schema,
    probe_column_values,
    sample_table,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def parse_result(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# SQLite in-memory fixture — writes a real file so SQLAlchemy can inspect it
# ---------------------------------------------------------------------------

@pytest.fixture()
def sqlite_db(tmp_path):
    """
    Creates a SQLite file with two tables:
      - main.orders  (TRANSACTIONAL-like)
      - main.customers (MASTER-like)

    Returns a dict with 'url' and 'path'.
    """
    import sqlite3

    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            order_date TEXT NOT NULL,
            total_amount REAL,
            customer_id INTEGER
        )
        """
    )
    cur.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?)",
        [(i, f"2025-0{(i % 9) + 1}-01", float(i * 10), i % 5)
         for i in range(1, 201)],
    )

    cur.execute(
        """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT
        )
        """
    )
    cur.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
        [(i, f"Customer {i}", f"c{i}@example.com", "555-0000", f"Addr {i}")
         for i in range(1, 101)],
    )

    conn.commit()
    conn.close()

    url = f"sqlite:///{db_file}"
    return {"url": url, "path": str(db_file)}


# ===========================================================================
# connect_database
# ===========================================================================

class TestConnectDatabase:

    def test_connect_success_returns_status(self, sqlite_db):
        result = parse_result(run(connect_database({
            "connection_string": sqlite_db["url"],
            "client_name": "test_client",
        })))
        assert result["status"] == "connected"

    def test_connect_returns_client_name(self, sqlite_db):
        result = parse_result(run(connect_database({
            "connection_string": sqlite_db["url"],
            "client_name": "acme_corp",
        })))
        assert result["client"] == "acme_corp"

    def test_connect_lists_tables(self, sqlite_db):
        result = parse_result(run(connect_database({
            "connection_string": sqlite_db["url"],
            "client_name": "test_client",
        })))
        # SQLite schema is "main"
        all_tables = []
        for tables in result["tables"].values():
            all_tables.extend(tables)
        assert "orders" in all_tables
        assert "customers" in all_tables

    def test_connect_table_count_positive(self, sqlite_db):
        result = parse_result(run(connect_database({
            "connection_string": sqlite_db["url"],
            "client_name": "test_client",
        })))
        assert result["table_count"] >= 2

    def test_connect_returns_schemas(self, sqlite_db):
        result = parse_result(run(connect_database({
            "connection_string": sqlite_db["url"],
            "client_name": "test_client",
        })))
        assert isinstance(result["schemas"], list)
        assert len(result["schemas"]) >= 1

    def test_connect_invalid_url_raises_or_returns_error(self):
        """Bad connection string should raise an exception (not silently succeed)."""
        with pytest.raises(Exception):
            run(connect_database({
                "connection_string": "postgresql://nonexistent_host:5432/nodb",
                "client_name": "fail_client",
            }))

    def test_connect_nonexistent_sqlite_creates_empty_db(self, tmp_path):
        """SQLAlchemy creates a new SQLite file if it doesn't exist."""
        url = f"sqlite:///{tmp_path}/brand_new.db"
        result = parse_result(run(connect_database({
            "connection_string": url,
            "client_name": "new_client",
        })))
        assert result["status"] == "connected"
        assert result["table_count"] == 0


# ===========================================================================
# introspect_schema
# ===========================================================================

class TestIntrospectSchema:

    def test_introspect_returns_columns(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        col_names = [c["name"] for c in result["columns"]]
        assert "id" in col_names
        assert "order_date" in col_names
        assert "total_amount" in col_names

    def test_introspect_returns_row_count(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        assert result["row_count"] == 200

    def test_introspect_returns_table_name(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "customers",
            "schema": "main",
        })))
        assert result["table"] == "customers"

    def test_introspect_column_has_type(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        for col in result["columns"]:
            assert "type" in col
            assert isinstance(col["type"], str)

    def test_introspect_has_pk_constraint(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        assert "primary_key" in result

    def test_introspect_has_indexes_list(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        assert isinstance(result["indexes"], list)

    def test_introspect_has_foreign_keys_list(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        assert isinstance(result["foreign_keys"], list)

    def test_introspect_nonexistent_table_returns_error(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "does_not_exist",
            "schema": "main",
        })))
        assert "error" in result

    def test_introspect_customers_has_five_columns(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "customers",
            "schema": "main",
        })))
        assert len(result["columns"]) == 5

    def test_introspect_schema_field_returned(self, sqlite_db):
        result = parse_result(run(introspect_schema({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        assert result["schema"] == "main"


# ===========================================================================
# sample_table
# ===========================================================================

class TestSampleTable:

    def test_sample_returns_rows(self, sqlite_db):
        result = parse_result(run(sample_table({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
            "limit": 5,
        })))
        assert result["row_count"] == 5
        assert len(result["sample_rows"]) == 5

    def test_sample_returns_columns(self, sqlite_db):
        result = parse_result(run(sample_table({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
            "limit": 3,
        })))
        assert "id" in result["columns"]
        assert "total_amount" in result["columns"]

    def test_sample_default_limit_is_five(self, sqlite_db):
        result = parse_result(run(sample_table({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
        })))
        assert result["row_count"] <= 5

    def test_sample_limit_respected(self, sqlite_db):
        result = parse_result(run(sample_table({
            "connection_string": sqlite_db["url"],
            "table_name": "customers",
            "schema": "main",
            "limit": 10,
        })))
        assert result["row_count"] == 10

    def test_sample_returns_table_name(self, sqlite_db):
        result = parse_result(run(sample_table({
            "connection_string": sqlite_db["url"],
            "table_name": "customers",
            "schema": "main",
            "limit": 1,
        })))
        assert result["table"] == "customers"

    def test_sample_row_values_serializable(self, sqlite_db):
        result = parse_result(run(sample_table({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "schema": "main",
            "limit": 5,
        })))
        # Should be JSON-round-trippable already (parse_result does this)
        for row in result["sample_rows"]:
            for v in row.values():
                assert isinstance(v, (str, int, float, bool, type(None)))

    def test_sample_nonexistent_table_returns_error(self, sqlite_db):
        result = parse_result(run(sample_table({
            "connection_string": sqlite_db["url"],
            "table_name": "ghost_table",
            "schema": "main",
            "limit": 5,
        })))
        assert "error" in result


# ===========================================================================
# probe_column_values
# ===========================================================================

class TestProbeColumnValues:

    def test_probe_returns_distinct_values(self, sqlite_db):
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "column_name": "customer_id",
            "schema": "main",
        })))
        assert "distinct_values" in result
        assert len(result["distinct_values"]) > 0

    def test_probe_values_have_count(self, sqlite_db):
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "column_name": "customer_id",
            "schema": "main",
        })))
        for item in result["distinct_values"]:
            assert "value" in item
            assert "count" in item
            assert item["count"] > 0

    def test_probe_sorted_by_count_desc(self, sqlite_db):
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "column_name": "customer_id",
            "schema": "main",
        })))
        counts = [item["count"] for item in result["distinct_values"]]
        assert counts == sorted(counts, reverse=True)

    def test_probe_max_20_values(self, sqlite_db):
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "column_name": "order_date",
            "schema": "main",
        })))
        assert len(result["distinct_values"]) <= 20

    def test_probe_returns_total_rows_sampled(self, sqlite_db):
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "column_name": "customer_id",
            "schema": "main",
        })))
        assert "total_rows_sampled" in result
        assert result["total_rows_sampled"] > 0

    def test_probe_returns_note(self, sqlite_db):
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "column_name": "customer_id",
            "schema": "main",
        })))
        assert "note" in result

    def test_probe_nonexistent_table_returns_error(self, sqlite_db):
        """Probing a column on a nonexistent table returns an error."""
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "nonexistent_table_xyz",
            "column_name": "amount",
            "schema": "main",
        })))
        assert "error" in result

    def test_probe_customer_ids_are_five_values(self, sqlite_db):
        """orders.customer_id is i % 5 → exactly 5 distinct values."""
        result = parse_result(run(probe_column_values({
            "connection_string": sqlite_db["url"],
            "table_name": "orders",
            "column_name": "customer_id",
            "schema": "main",
        })))
        assert len(result["distinct_values"]) == 5


# ===========================================================================
# classify_entity
# ===========================================================================

class TestClassifyEntity:

    def _cols(self, names: list) -> str:
        return json.dumps([{"name": n} for n in names])

    def test_transactional_with_date_and_amount(self):
        result = parse_result(run(classify_entity({
            "table_name": "c_invoice",
            "columns": self._cols(["id", "date_invoice", "total_amount", "customer_id"]),
            "sample_data": "{}",
            "row_count": 50000,
        })))
        assert result["classification"] == "TRANSACTIONAL"

    def test_transactional_high_confidence(self):
        result = parse_result(run(classify_entity({
            "table_name": "c_invoice",
            "columns": self._cols(["id", "date_invoice", "total_amount", "customer_id"]),
            "sample_data": "{}",
            "row_count": 50000,
        })))
        assert result["confidence"] >= 0.7

    def test_master_high_row_count_no_amount(self):
        result = parse_result(run(classify_entity({
            "table_name": "c_bpartner",
            "columns": self._cols(["id", "name", "address", "phone", "email"]),
            "sample_data": "{}",
            "row_count": 500,
        })))
        assert result["classification"] in ("MASTER", "TRANSACTIONAL")

    def test_bridge_few_cols_low_rows(self):
        result = parse_result(run(classify_entity({
            "table_name": "ad_sysconfig",
            "columns": self._cols(["id", "name", "value"]),
            "sample_data": "{}",
            "row_count": 20,
        })))
        assert result["classification"] in ("BRIDGE", "CONFIG")

    def test_confidence_in_valid_range(self):
        result = parse_result(run(classify_entity({
            "table_name": "some_table",
            "columns": self._cols(["id", "col1"]),
            "sample_data": "{}",
            "row_count": 10,
        })))
        assert 0.0 <= result["confidence"] <= 1.0

    def test_note_always_present(self):
        result = parse_result(run(classify_entity({
            "table_name": "payments",
            "columns": self._cols(["id", "amount", "date"]),
            "sample_data": "{}",
            "row_count": 1000,
        })))
        assert "note" in result

    def test_reasoning_list_present(self):
        result = parse_result(run(classify_entity({
            "table_name": "payments",
            "columns": self._cols(["id", "amount", "date"]),
            "sample_data": "{}",
            "row_count": 1000,
        })))
        assert isinstance(result["reasoning"], list)

    def test_table_name_preserved_in_output(self):
        result = parse_result(run(classify_entity({
            "table_name": "MySpecialTable",
            "columns": self._cols(["id"]),
            "sample_data": "{}",
            "row_count": 5,
        })))
        assert result["table"] == "MySpecialTable"

    def test_transactional_name_hint_invoice(self):
        result = parse_result(run(classify_entity({
            "table_name": "sales_invoice",
            "columns": self._cols(["id", "amount", "invoice_date"]),
            "sample_data": "{}",
            "row_count": 5000,
        })))
        assert result["classification"] == "TRANSACTIONAL"

    def test_config_name_hint(self):
        result = parse_result(run(classify_entity({
            "table_name": "system_config",
            "columns": self._cols(["id", "key", "value"]),
            "sample_data": "{}",
            "row_count": 30,
        })))
        # config hint in name → reasoning should mention it
        reasons_text = " ".join(result["reasoning"])
        assert "config" in reasons_text.lower()

    def test_master_name_hint_customer(self):
        result = parse_result(run(classify_entity({
            "table_name": "customer_master",
            "columns": self._cols(["id", "name", "email", "address", "phone", "created"]),
            "sample_data": "{}",
            "row_count": 200,
        })))
        # "customer" hint in name + no amount cols → MASTER
        assert result["classification"] == "MASTER"

    def test_empty_columns_string_no_crash(self):
        result = parse_result(run(classify_entity({
            "table_name": "mystery_table",
            "columns": "",
            "sample_data": "{}",
            "row_count": 0,
        })))
        assert "classification" in result

    def test_zero_row_count_defaults_config_or_bridge(self):
        result = parse_result(run(classify_entity({
            "table_name": "tiny_lookup",
            "columns": self._cols(["id", "code"]),
            "sample_data": "{}",
            "row_count": 0,
        })))
        assert result["classification"] in ("BRIDGE", "CONFIG")
