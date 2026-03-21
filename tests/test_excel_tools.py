"""
Tests for core/valinor/tools/excel_tools.py

Covers: excel_to_sqlite, csv_to_sqlite
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
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

from valinor.tools.excel_tools import csv_to_sqlite, excel_to_sqlite


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def parse_result(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def excel_file(tmp_path):
    """Creates a real .xlsx file with two sheets using openpyxl."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()

    ws1 = wb.active
    ws1.title = "Sales Data"
    ws1.append(["id", "date", "amount", "customer"])
    for i in range(1, 11):
        ws1.append([i, f"2025-0{(i % 9) + 1}-01", float(i * 100), f"Customer {i}"])

    ws2 = wb.create_sheet(title="Products")
    ws2.append(["product_id", "name", "price"])
    for i in range(1, 6):
        ws2.append([i, f"Product {i}", float(i * 9.99)])

    file_path = tmp_path / "test_data.xlsx"
    wb.save(str(file_path))
    return str(file_path)


@pytest.fixture()
def csv_file(tmp_path):
    """Creates a real CSV file."""
    content = "id,name,revenue,region\n"
    for i in range(1, 21):
        content += f"{i},Entity {i},{i * 500.0},Region{i % 3}\n"
    file_path = tmp_path / "test_data.csv"
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)


# ===========================================================================
# excel_to_sqlite
# ===========================================================================

class TestExcelToSqlite:

    def test_converts_successfully(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "test_excel_client",
        })))
        assert result["status"] == "converted"

    def test_returns_sqlite_path(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "test_excel_client2",
        })))
        assert "sqlite_path" in result
        assert result["sqlite_path"].endswith(".db")

    def test_returns_connection_string(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "test_excel_client3",
        })))
        assert result["connection_string"].startswith("sqlite:///")

    def test_creates_table_per_sheet(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "test_excel_client4",
        })))
        table_names = [t["table"] for t in result["tables"]]
        assert "sales_data" in table_names
        assert "products" in table_names

    def test_table_row_counts_correct(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "test_excel_client5",
        })))
        by_table = {t["table"]: t for t in result["tables"]}
        assert by_table["sales_data"]["rows"] == 10
        assert by_table["products"]["rows"] == 5

    def test_table_columns_listed(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "test_excel_client6",
        })))
        by_table = {t["table"]: t for t in result["tables"]}
        assert "id" in by_table["sales_data"]["columns"]
        assert "amount" in by_table["sales_data"]["columns"]

    def test_sheet_name_preserved(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "test_excel_client7",
        })))
        sheet_names = [t["sheet"] for t in result["tables"]]
        assert "Sales Data" in sheet_names
        assert "Products" in sheet_names

    def test_file_not_found_returns_error(self, tmp_path):
        result = parse_result(run(excel_to_sqlite({
            "file_path": str(tmp_path / "does_not_exist.xlsx"),
            "client_name": "no_file_client",
        })))
        assert "error" in result

    def test_sqlite_db_actually_queryable(self, excel_file):
        """The resulting SQLite file should be readable with sqlite3."""
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "queryable_client",
        })))
        db_path = result["sqlite_path"]
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM sales_data").fetchone()
        conn.close()
        assert rows[0] == 10

    def test_sheet_name_spaces_replaced_with_underscore(self, excel_file):
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "space_client",
        })))
        table_names = [t["table"] for t in result["tables"]]
        # "Sales Data" → "sales_data"
        for name in table_names:
            assert " " not in name


# ===========================================================================
# csv_to_sqlite
# ===========================================================================

class TestCsvToSqlite:

    def test_converts_successfully(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "test_csv_client",
            "table_name": "sales",
        })))
        assert result["status"] == "converted"

    def test_returns_sqlite_path(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "test_csv_client2",
            "table_name": "sales",
        })))
        assert result["sqlite_path"].endswith(".db")

    def test_returns_connection_string(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "test_csv_client3",
            "table_name": "sales",
        })))
        assert result["connection_string"].startswith("sqlite:///")

    def test_row_count_correct(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "test_csv_client4",
            "table_name": "mydata",
        })))
        assert result["rows"] == 20

    def test_columns_listed(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "test_csv_client5",
            "table_name": "mydata",
        })))
        assert "id" in result["columns"]
        assert "revenue" in result["columns"]
        assert "region" in result["columns"]

    def test_table_name_respected(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "test_csv_client6",
            "table_name": "custom_table",
        })))
        assert result["table"] == "custom_table"

    def test_default_table_name_is_data(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "test_csv_default",
        })))
        assert result["table"] == "data"

    def test_file_not_found_returns_error(self, tmp_path):
        result = parse_result(run(csv_to_sqlite({
            "file_path": str(tmp_path / "missing.csv"),
            "client_name": "no_file_client",
            "table_name": "data",
        })))
        assert "error" in result

    def test_sqlite_db_actually_queryable(self, csv_file):
        """The resulting SQLite file should be queryable."""
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "queryable_csv_client",
            "table_name": "revenues",
        })))
        db_path = result["sqlite_path"]
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT COUNT(*) FROM revenues").fetchone()
        conn.close()
        assert rows[0] == 20

    def test_source_path_in_result(self, csv_file):
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "source_check_client",
            "table_name": "data",
        })))
        assert result["source"] == csv_file


# ===========================================================================
# Additional tests — untested behaviors
# ===========================================================================

class TestExcelToSqliteExtra:

    def test_source_path_in_result(self, excel_file):
        """excel_to_sqlite must echo back the original file path as 'source'."""
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "extra_source_client",
        })))
        assert result["source"] == excel_file

    def test_tables_count_matches_sheet_count(self, excel_file):
        """The 'tables' list must have one entry per sheet in the workbook."""
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "extra_count_client",
        })))
        # Fixture creates exactly 2 sheets
        assert len(result["tables"]) == 2

    def test_dash_and_dot_in_sheet_name_normalized(self, tmp_path):
        """Sheet names with dashes and dots must be normalized to underscores."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "My-Sheet.V2"
        ws.append(["col_a", "col_b"])
        ws.append([1, 2])
        path = tmp_path / "dash_dot.xlsx"
        wb.save(str(path))

        result = parse_result(run(excel_to_sqlite({
            "file_path": str(path),
            "client_name": "extra_dash_dot_client",
        })))
        table_names = [t["table"] for t in result["tables"]]
        assert "my_sheet_v2" in table_names

    def test_single_sheet_workbook(self, tmp_path):
        """A workbook with only one sheet should produce exactly one table."""
        openpyxl = pytest.importorskip("openpyxl")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "OnlySheet"
        ws.append(["x", "y"])
        ws.append([10, 20])
        path = tmp_path / "single_sheet.xlsx"
        wb.save(str(path))

        result = parse_result(run(excel_to_sqlite({
            "file_path": str(path),
            "client_name": "extra_single_sheet_client",
        })))
        assert len(result["tables"]) == 1
        assert result["tables"][0]["table"] == "onlysheet"

    def test_data_values_stored_correctly(self, excel_file):
        """Querying the SQLite DB should return the exact cell values written."""
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "extra_values_client",
        })))
        db_path = result["sqlite_path"]
        conn = sqlite3.connect(db_path)
        # Row 1 in the fixture: id=1, amount=100.0, customer="Customer 1"
        row = conn.execute(
            "SELECT amount, customer FROM sales_data WHERE id = 1"
        ).fetchone()
        conn.close()
        assert row[0] == 100.0
        assert row[1] == "Customer 1"

    def test_second_call_same_client_overwrites_table(self, tmp_path):
        """Calling excel_to_sqlite twice with same client_name replaces old data."""
        openpyxl = pytest.importorskip("openpyxl")

        def make_wb(value, path):
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Info"
            ws.append(["val"])
            ws.append([value])
            wb.save(str(path))

        path1 = tmp_path / "v1.xlsx"
        path2 = tmp_path / "v2.xlsx"
        make_wb(42, path1)
        make_wb(99, path2)

        run(excel_to_sqlite({"file_path": str(path1), "client_name": "extra_overwrite_excel"}))
        run(excel_to_sqlite({"file_path": str(path2), "client_name": "extra_overwrite_excel"}))

        db_path = f"/tmp/valinor/extra_overwrite_excel.db"
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT val FROM info").fetchall()
        conn.close()
        # Only one row, and it is the second write's value
        assert len(rows) == 1
        assert rows[0][0] == 99

    def test_sqlite_path_contains_client_name(self, excel_file):
        """The returned sqlite_path must include the client_name segment."""
        result = parse_result(run(excel_to_sqlite({
            "file_path": excel_file,
            "client_name": "my_special_client",
        })))
        assert "my_special_client" in result["sqlite_path"]


class TestCsvToSqliteExtra:

    def test_data_values_stored_correctly(self, csv_file):
        """Querying the SQLite DB should return the exact cell values written."""
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "extra_csv_values_client",
            "table_name": "entities",
        })))
        db_path = result["sqlite_path"]
        conn = sqlite3.connect(db_path)
        # Row 1 in the fixture: id=1, name="Entity 1", revenue=500.0, region="Region1"
        row = conn.execute(
            "SELECT name, revenue FROM entities WHERE id = 1"
        ).fetchone()
        conn.close()
        assert row[0] == "Entity 1"
        assert row[1] == 500.0

    def test_sqlite_path_contains_client_name(self, csv_file):
        """The returned sqlite_path must include the client_name segment."""
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "csv_named_client",
            "table_name": "data",
        })))
        assert "csv_named_client" in result["sqlite_path"]

    def test_single_row_csv(self, tmp_path):
        """A CSV with one header row and one data row should convert without error."""
        path = tmp_path / "one_row.csv"
        path.write_text("alpha,beta\n7,hello\n", encoding="utf-8")

        result = parse_result(run(csv_to_sqlite({
            "file_path": str(path),
            "client_name": "extra_single_row_client",
            "table_name": "tiny",
        })))
        assert result["status"] == "converted"
        assert result["rows"] == 1
        assert "alpha" in result["columns"]
        assert "beta" in result["columns"]

    def test_second_call_same_client_overwrites_table(self, tmp_path):
        """Calling csv_to_sqlite twice with same client_name replaces old table data."""
        path1 = tmp_path / "first.csv"
        path2 = tmp_path / "second.csv"
        path1.write_text("n\n1\n2\n", encoding="utf-8")
        path2.write_text("n\n9\n", encoding="utf-8")

        run(csv_to_sqlite({"file_path": str(path1), "client_name": "extra_overwrite_csv", "table_name": "nums"}))
        run(csv_to_sqlite({"file_path": str(path2), "client_name": "extra_overwrite_csv", "table_name": "nums"}))

        db_path = "/tmp/valinor/extra_overwrite_csv.db"
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT n FROM nums").fetchall()
        conn.close()
        # Only the second write's single row should remain
        assert len(rows) == 1
        assert rows[0][0] == 9

    def test_connection_string_matches_sqlite_path(self, csv_file):
        """connection_string must be 'sqlite:///' prepended to sqlite_path."""
        result = parse_result(run(csv_to_sqlite({
            "file_path": csv_file,
            "client_name": "extra_connstr_client",
            "table_name": "data",
        })))
        expected = "sqlite:///" + result["sqlite_path"]
        assert result["connection_string"] == expected
