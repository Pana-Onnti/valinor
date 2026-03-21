"""
Tests for the Cartographer agent — Stage 1 Schema Discovery.

Covers:
  - _prescan_filter_candidates: deterministic Phase 1 pre-scan
  - _format_phase1_hints: hint formatting for the LLM prompt
  - _format_calibration_feedback: retry feedback formatting
  - classify_entity tool: heuristic table classification
  - connect_database tool: connection and schema discovery
  - introspect_schema tool: per-table deep introspection
  - sample_table tool: row sampling
  - probe_column_values tool: discriminator column discovery
  - run_cartographer: integration path (agent loop mocked)

SQLite in-memory databases are used for all DB-touching tests.
The Claude Agent SDK (query / create_sdk_mcp_server) is always mocked
so the test suite runs offline with no API keys.
"""

import asyncio
import json
import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Path bootstrap — mirrors the pattern used in other tests in this project
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Stub heavy optional dependencies not installed in the test venv
# ---------------------------------------------------------------------------
import types as _types

def _make_stub(name: str) -> _types.ModuleType:
    mod = _types.ModuleType(name)
    mod.__spec__ = None
    return mod

# claude_agent_sdk stub — the @tool decorator must return the function unchanged
_sdk_stub = _make_stub("claude_agent_sdk")
def _tool_stub(*args, **kwargs):
    # Called as @tool(name, desc, schema) → return decorator
    # Called as @tool (bare decorator, func as first arg with no other args)
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]  # bare @tool usage
    return lambda f: f  # @tool(...) usage — return identity decorator

_sdk_stub.tool = _tool_stub
_sdk_stub.query = MagicMock()  # will be replaced per-test as AsyncMock
_sdk_stub.ClaudeAgentOptions = MagicMock
_sdk_stub.AssistantMessage = MagicMock
_sdk_stub.TextBlock = MagicMock
_sdk_stub.create_sdk_mcp_server = MagicMock()
sys.modules.setdefault("claude_agent_sdk", _sdk_stub)

# anthropic stub
_anthropic_stub = _make_stub("anthropic")
sys.modules.setdefault("anthropic", _anthropic_stub)

# structlog stub
if "structlog" not in sys.modules:
    _sl = _make_stub("structlog")
    _sl.get_logger = lambda: MagicMock()
    sys.modules["structlog"] = _sl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously (pytest-asyncio not required)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _sqlite_url(engine):
    """Return the raw SQLite connection string for a given engine."""
    return str(engine.url)


# ---------------------------------------------------------------------------
# Fixtures — SQLite in-memory databases
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_engine(tmp_path):
    """Completely empty SQLite engine — no tables at all."""
    db_file = tmp_path / "empty.db"
    return create_engine(f"sqlite:///{db_file}")


@pytest.fixture
def minimal_engine(tmp_path):
    """Engine with a single non-business table (config-like)."""
    db_file = tmp_path / "minimal.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE ad_system (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO ad_system VALUES (1, 'Valinor')"))
        conn.commit()
    return engine


@pytest.fixture
def business_engine(tmp_path):
    """Engine with ERP-style tables including discriminator columns."""
    db_file = tmp_path / "business.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE c_invoice (
                c_invoice_id INTEGER PRIMARY KEY,
                ad_client_id INTEGER,
                issotrx TEXT,
                docstatus TEXT,
                grandtotal REAL,
                dateinvoiced TEXT,
                c_bpartner_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE c_bpartner (
                c_bpartner_id INTEGER PRIMARY KEY,
                name TEXT,
                iscustomer TEXT,
                isactive TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE fin_payment_schedule (
                fin_payment_schedule_id INTEGER PRIMARY KEY,
                c_bpartner_id INTEGER,
                duedate TEXT,
                outstandingamt REAL,
                isreceipt TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE ad_preference (
                ad_preference_id INTEGER PRIMARY KEY,
                attribute TEXT,
                value TEXT
            )
        """))
        # Seed invoices — 40 sales (issotrx='Y') + 20 purchase (issotrx='N')
        for i in range(1, 41):
            conn.execute(text(
                f"INSERT INTO c_invoice VALUES ({i}, 1000000, 'Y', 'CO', {1000 + i * 50}, '2025-01-{(i % 28) + 1:02d}', {(i % 5) + 1})"
            ))
        for i in range(41, 61):
            conn.execute(text(
                f"INSERT INTO c_invoice VALUES ({i}, 1000000, 'N', 'CO', {500 + i * 30}, '2025-01-{(i % 28) + 1:02d}', {(i % 5) + 1})"
            ))
        # Partners
        for i in range(1, 6):
            conn.execute(text(
                f"INSERT INTO c_bpartner VALUES ({i}, 'Partner {i}', 'Y', 'Y')"
            ))
        # Payments
        for i in range(1, 11):
            conn.execute(text(
                f"INSERT INTO fin_payment_schedule VALUES ({i}, {i}, '2025-02-{i:02d}', {2000 + i * 100}, 'Y')"
            ))
        conn.commit()
    return engine


# ---------------------------------------------------------------------------
# 1. _prescan_filter_candidates — Phase 1 deterministic pre-scan
# ---------------------------------------------------------------------------

class TestPrescanFilterCandidates:
    """Tests for the deterministic discriminator-column pre-scan."""

    def test_returns_candidate_hints_for_business_tables(self, business_engine):
        from valinor.agents.cartographer import _prescan_filter_candidates

        config = {"connection_string": _sqlite_url(business_engine)}
        result = _run(_prescan_filter_candidates(config))

        assert "candidate_hints" in result
        hints = result["candidate_hints"]
        # c_invoice matches the 'invoice' business hint and has ad_client_id / issotrx
        assert any("invoice" in t for t in hints), (
            f"Expected c_invoice in hints, got keys: {list(hints.keys())}"
        )

    def test_returns_empty_hints_for_non_business_tables(self, minimal_engine):
        from valinor.agents.cartographer import _prescan_filter_candidates

        config = {"connection_string": _sqlite_url(minimal_engine)}
        result = _run(_prescan_filter_candidates(config))

        assert result.get("candidate_hints") == {}

    def test_returns_error_key_on_bad_connection(self):
        from valinor.agents.cartographer import _prescan_filter_candidates

        config = {"connection_string": "postgresql://invalid:5432/nonexistent"}
        result = _run(_prescan_filter_candidates(config))

        # Must not raise; must return structured error
        assert "error" in result or "candidate_hints" in result

    def test_discriminator_values_contain_value_and_count(self, business_engine):
        from valinor.agents.cartographer import _prescan_filter_candidates

        config = {"connection_string": _sqlite_url(business_engine)}
        result = _run(_prescan_filter_candidates(config))

        hints = result["candidate_hints"]
        for _table, cols in hints.items():
            for _col, values in cols.items():
                for entry in values:
                    assert "value" in entry
                    assert "count" in entry
                    assert isinstance(entry["count"], int)

    def test_caps_at_six_business_tables(self, business_engine):
        """Phase 1 should probe at most 6 tables to stay fast."""
        from valinor.agents.cartographer import _prescan_filter_candidates

        config = {"connection_string": _sqlite_url(business_engine)}
        result = _run(_prescan_filter_candidates(config))

        assert len(result.get("candidate_hints", {})) <= 6


# ---------------------------------------------------------------------------
# 2. _format_phase1_hints — prompt section builder
# ---------------------------------------------------------------------------

class TestFormatPhase1Hints:
    """Tests for the Phase 1 hint formatter."""

    def test_empty_hints_returns_empty_string(self):
        from valinor.agents.cartographer import _format_phase1_hints

        output = _format_phase1_hints({"candidate_hints": {}})
        assert output == ""

    def test_missing_candidate_hints_key_returns_empty_string(self):
        from valinor.agents.cartographer import _format_phase1_hints

        output = _format_phase1_hints({})
        assert output == ""

    def test_output_contains_table_and_column_names(self):
        from valinor.agents.cartographer import _format_phase1_hints

        prescan = {
            "candidate_hints": {
                "c_invoice": {
                    "issotrx": [
                        {"value": "Y", "count": 30100},
                        {"value": "N", "count": 15134},
                    ]
                }
            }
        }
        output = _format_phase1_hints(prescan)

        assert "c_invoice" in output
        assert "issotrx" in output
        assert "30,100" in output or "30100" in output  # formatted count

    def test_output_contains_phase1_section_header(self):
        from valinor.agents.cartographer import _format_phase1_hints

        prescan = {
            "candidate_hints": {
                "c_bpartner": {
                    "ad_client_id": [{"value": "1000000", "count": 5000}]
                }
            }
        }
        output = _format_phase1_hints(prescan)

        assert "PHASE 1" in output.upper() or "PRE-SCAN" in output.upper()


# ---------------------------------------------------------------------------
# 3. _format_calibration_feedback — retry feedback formatter
# ---------------------------------------------------------------------------

class TestFormatCalibrationFeedback:
    """Tests for the Reflexion retry feedback formatter."""

    def test_empty_failures_returns_empty_string(self):
        from valinor.agents.cartographer import _format_calibration_feedback

        assert _format_calibration_feedback([]) == ""

    def test_output_contains_entity_name_and_feedback(self):
        from valinor.agents.cartographer import _format_calibration_feedback

        failures = [
            {"entity": "invoices", "feedback": "filtered_count is 0 — base_filter too restrictive"},
        ]
        output = _format_calibration_feedback(failures)

        assert "invoices" in output
        assert "filtered_count is 0" in output

    def test_output_contains_calibration_header(self):
        from valinor.agents.cartographer import _format_calibration_feedback

        failures = [{"entity": "payments", "feedback": "no rows returned"}]
        output = _format_calibration_feedback(failures)

        assert "CALIBRATION" in output.upper()

    def test_multiple_failures_all_appear_in_output(self):
        from valinor.agents.cartographer import _format_calibration_feedback

        failures = [
            {"entity": "invoices", "feedback": "count=0"},
            {"entity": "orders", "feedback": "wrong filter"},
            {"entity": "customers", "feedback": "base_filter missing"},
        ]
        output = _format_calibration_feedback(failures)

        for f in failures:
            assert f["entity"] in output


# ---------------------------------------------------------------------------
# 4. classify_entity tool — heuristic classification
# ---------------------------------------------------------------------------

class TestClassifyEntityTool:
    """Tests for the deterministic classify_entity MCP tool."""

    def _classify(self, table_name, columns, row_count):
        from valinor.tools.db_tools import classify_entity

        args = {
            "table_name": table_name,
            "columns": json.dumps(columns),
            "sample_data": "[]",
            "row_count": row_count,
        }
        result = _run(classify_entity(args))
        payload = json.loads(result["content"][0]["text"])
        return payload

    def test_transactional_invoice_table(self):
        columns = [
            {"name": "id"}, {"name": "dateinvoiced"}, {"name": "grandtotal"},
            {"name": "c_bpartner_id"}, {"name": "docstatus"},
        ]
        result = self._classify("c_invoice", columns, row_count=50000)

        assert result["classification"] == "TRANSACTIONAL"
        assert result["confidence"] >= 0.8

    def test_master_customer_table(self):
        columns = [
            {"name": "id"}, {"name": "name"}, {"name": "email"},
            {"name": "phone"}, {"name": "iscustomer"},
        ]
        result = self._classify("c_bpartner", columns, row_count=500)

        assert result["classification"] in ("MASTER", "TRANSACTIONAL")
        # At minimum confidence should be returned
        assert 0.0 <= result["confidence"] <= 1.0

    def test_config_table_low_rows(self):
        columns = [{"name": "id"}, {"name": "key"}, {"name": "value"}]
        result = self._classify("ad_preference", columns, row_count=10)

        assert result["classification"] in ("CONFIG", "BRIDGE")

    def test_bridge_table_few_columns_low_rows(self):
        columns = [{"name": "a_id"}, {"name": "b_id"}]
        result = self._classify("product_category_rel", columns, row_count=30)

        assert result["classification"] == "BRIDGE"
        assert result["confidence"] >= 0.5

    def test_result_includes_required_keys(self):
        columns = [{"name": "id"}, {"name": "name"}]
        result = self._classify("some_table", columns, row_count=100)

        for key in ("table", "classification", "confidence", "reasoning"):
            assert key in result, f"Missing key: {key}"

    def test_name_hint_boosts_confidence_for_payment_table(self):
        columns = [
            {"name": "id"}, {"name": "amount"}, {"name": "payment_date"},
        ]
        result = self._classify("fin_payment", columns, row_count=1000)

        assert result["confidence"] > 0.7


# ---------------------------------------------------------------------------
# 5. connect_database tool — connection and schema metadata
# ---------------------------------------------------------------------------

class TestConnectDatabaseTool:
    """Tests for the connect_database MCP tool using SQLite in-memory."""

    def test_successful_connection_returns_status_connected(self, business_engine):
        from valinor.tools.db_tools import connect_database

        args = {
            "connection_string": _sqlite_url(business_engine),
            "client_name": "test_client",
        }
        result = _run(connect_database(args))
        payload = json.loads(result["content"][0]["text"])

        assert payload["status"] == "connected"
        assert payload["client"] == "test_client"

    def test_returns_table_count(self, business_engine):
        from valinor.tools.db_tools import connect_database

        args = {
            "connection_string": _sqlite_url(business_engine),
            "client_name": "test_client",
        }
        result = _run(connect_database(args))
        payload = json.loads(result["content"][0]["text"])

        assert payload["table_count"] >= 3  # c_invoice, c_bpartner, fin_payment_schedule

    def test_returns_empty_schema_for_empty_database(self, empty_engine):
        from valinor.tools.db_tools import connect_database

        args = {
            "connection_string": _sqlite_url(empty_engine),
            "client_name": "empty_client",
        }
        result = _run(connect_database(args))
        payload = json.loads(result["content"][0]["text"])

        assert payload["table_count"] == 0


# ---------------------------------------------------------------------------
# 6. introspect_schema tool — column and constraint metadata
# ---------------------------------------------------------------------------

class TestIntrospectSchemaTool:
    """Tests for the introspect_schema MCP tool."""

    def test_returns_columns_for_existing_table(self, business_engine):
        from valinor.tools.db_tools import introspect_schema

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "c_invoice",
            "schema": "main",  # SQLite uses 'main' as default schema
        }
        result = _run(introspect_schema(args))
        payload = json.loads(result["content"][0]["text"])

        assert "columns" in payload
        col_names = [c["name"] for c in payload["columns"]]
        assert "grandtotal" in col_names
        assert "issotrx" in col_names

    def test_returns_row_count(self, business_engine):
        from valinor.tools.db_tools import introspect_schema

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "c_bpartner",
            "schema": "main",
        }
        result = _run(introspect_schema(args))
        payload = json.loads(result["content"][0]["text"])

        assert "row_count" in payload
        assert payload["row_count"] == 5

    def test_returns_error_for_nonexistent_table(self, business_engine):
        from valinor.tools.db_tools import introspect_schema

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "nonexistent_table",
            "schema": "main",
        }
        result = _run(introspect_schema(args))
        payload = json.loads(result["content"][0]["text"])

        assert "error" in payload


# ---------------------------------------------------------------------------
# 7. sample_table tool — row sampling
# ---------------------------------------------------------------------------

class TestSampleTableTool:
    """Tests for the sample_table MCP tool."""

    def test_returns_sample_rows(self, business_engine):
        from valinor.tools.db_tools import sample_table

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "c_bpartner",
            "schema": "main",
            "limit": 3,
        }
        result = _run(sample_table(args))
        payload = json.loads(result["content"][0]["text"])

        assert "sample_rows" in payload
        assert len(payload["sample_rows"]) <= 3
        assert "columns" in payload

    def test_sample_rows_contain_expected_columns(self, business_engine):
        from valinor.tools.db_tools import sample_table

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "c_invoice",
            "schema": "main",
            "limit": 5,
        }
        result = _run(sample_table(args))
        payload = json.loads(result["content"][0]["text"])

        assert "issotrx" in payload["columns"]
        assert "grandtotal" in payload["columns"]

    def test_error_on_nonexistent_table(self, business_engine):
        from valinor.tools.db_tools import sample_table

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "ghost_table",
            "schema": "main",
            "limit": 5,
        }
        result = _run(sample_table(args))
        payload = json.loads(result["content"][0]["text"])

        assert "error" in payload


# ---------------------------------------------------------------------------
# 8. probe_column_values tool — discriminator discovery
# ---------------------------------------------------------------------------

class TestProbeColumnValuesTool:
    """Tests for the probe_column_values MCP tool (ReFoRCE pattern)."""

    def test_returns_distinct_values_with_counts(self, business_engine):
        from valinor.tools.db_tools import probe_column_values

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "c_invoice",
            "column_name": "issotrx",
            "schema": "main",
        }
        result = _run(probe_column_values(args))
        payload = json.loads(result["content"][0]["text"])

        assert "distinct_values" in payload
        values = {entry["value"]: entry["count"] for entry in payload["distinct_values"]}
        assert "Y" in values
        assert "N" in values
        assert values["Y"] == 40
        assert values["N"] == 20

    def test_dominant_value_appears_first(self, business_engine):
        from valinor.tools.db_tools import probe_column_values

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "c_invoice",
            "column_name": "issotrx",
            "schema": "main",
        }
        result = _run(probe_column_values(args))
        payload = json.loads(result["content"][0]["text"])

        # Results ordered DESC by count — Y (40) should be first
        first = payload["distinct_values"][0]
        assert first["value"] == "Y"
        assert first["count"] == 40

    def test_returns_error_for_nonexistent_column(self, business_engine):
        from valinor.tools.db_tools import probe_column_values

        # Use a non-existent TABLE (not just column) — reliably raises an error
        # in both PostgreSQL and SQLite (SQLite silently returns literals for
        # missing column names but will error on a missing table).
        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "non_existent_table",
            "column_name": "some_column",
            "schema": "main",
        }
        result = _run(probe_column_values(args))
        payload = json.loads(result["content"][0]["text"])

        assert "error" in payload

    def test_total_rows_sampled_matches_actual_count(self, business_engine):
        from valinor.tools.db_tools import probe_column_values

        args = {
            "connection_string": _sqlite_url(business_engine),
            "table_name": "c_bpartner",
            "column_name": "iscustomer",
            "schema": "main",
        }
        result = _run(probe_column_values(args))
        payload = json.loads(result["content"][0]["text"])

        assert payload["total_rows_sampled"] == 5  # 5 partners seeded


# ---------------------------------------------------------------------------
# 9. run_cartographer — integration path (agent loop fully mocked)
# ---------------------------------------------------------------------------

class TestRunCartographer:
    """
    Integration tests for run_cartographer.

    The Claude Agent SDK (query / create_sdk_mcp_server) and filesystem
    write_artifact paths are mocked so these tests run offline.
    """

    def _mock_entity_map(self, client_name: str) -> dict:
        return {
            "client": client_name,
            "mapped_at": "2026-01-01T00:00:00",
            "database_type": "sqlite",
            "total_tables": 4,
            "tenants": [],
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "type": "TRANSACTIONAL",
                    "key_columns": {"invoice_pk": "c_invoice_id"},
                    "row_count": 60,
                    "confidence": 0.95,
                    "base_filter": "issotrx='Y'",
                    "quality_flags": [],
                },
                "customers": {
                    "table": "c_bpartner",
                    "type": "MASTER",
                    "key_columns": {"customer_pk": "c_bpartner_id"},
                    "row_count": 5,
                    "confidence": 0.9,
                    "base_filter": "iscustomer='Y'",
                    "quality_flags": [],
                },
            },
            "relationships": [
                {"from": "invoices", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"}
            ],
            "query_rules": [],
            "unmapped_tables": [],
            "quality_summary": "GOOD",
        }

    def test_returns_entity_map_when_artifact_written(self, tmp_path, business_engine):
        from valinor.agents.cartographer import run_cartographer

        client_name = "test_client"
        entity_map_data = self._mock_entity_map(client_name)

        # Write a fake artifact so the function finds it
        artifact_dir = tmp_path / "output" / client_name / "discovery"
        artifact_dir.mkdir(parents=True)
        artifact_path = artifact_dir / "entity_map.json"
        artifact_path.write_text(json.dumps(entity_map_data), encoding="utf-8")

        client_config = {
            "name": client_name,
            "connection_string": _sqlite_url(business_engine),
        }

        with (
            patch("valinor.agents.cartographer.query", new_callable=MagicMock) as mock_query,
            patch("valinor.agents.cartographer.create_sdk_mcp_server", return_value=MagicMock()),
            patch(
                "valinor.agents.cartographer.Path",
                side_effect=lambda *a: artifact_path if "entity_map.json" in str(a) else Path(*a),
            ),
        ):
            # query() is used as an async generator
            async def fake_query(**_kwargs):
                return
                yield  # make it an async generator

            mock_query.side_effect = fake_query

            # Patch artifact_path lookup inside run_cartographer
            with patch.object(
                Path, "exists", return_value=True
            ), patch.object(
                Path, "read_text", return_value=json.dumps(entity_map_data)
            ):
                result = _run(run_cartographer(client_config))

        assert result["client"] == client_name
        assert "entities" in result

    def test_returns_partial_status_when_no_artifact(self, business_engine):
        from valinor.agents.cartographer import run_cartographer

        client_config = {
            "name": "missing_artifact_client",
            "connection_string": _sqlite_url(business_engine),
        }

        with (
            patch("valinor.agents.cartographer.query", new_callable=MagicMock) as mock_query,
            patch("valinor.agents.cartographer.create_sdk_mcp_server", return_value=MagicMock()),
        ):
            async def fake_query(**_kwargs):
                return
                yield

            mock_query.side_effect = fake_query

            result = _run(run_cartographer(client_config))

        # No artifact on disk → partial fallback
        assert result.get("status") == "partial" or "entities" in result

    def test_phase1_prescan_metadata_attached_to_result(self, tmp_path, business_engine):
        from valinor.agents.cartographer import run_cartographer

        client_name = "prescan_meta_client"
        entity_map_data = self._mock_entity_map(client_name)
        entity_map_data["_phase1_prescan"] = None  # will be overwritten

        artifact_dir = tmp_path / "output" / client_name / "discovery"
        artifact_dir.mkdir(parents=True)
        artifact_path = artifact_dir / "entity_map.json"
        artifact_path.write_text(json.dumps(entity_map_data), encoding="utf-8")

        client_config = {
            "name": client_name,
            "connection_string": _sqlite_url(business_engine),
        }

        with (
            patch("valinor.agents.cartographer.query", new_callable=MagicMock) as mock_query,
            patch("valinor.agents.cartographer.create_sdk_mcp_server", return_value=MagicMock()),
        ):
            async def fake_query(**_kwargs):
                return
                yield

            mock_query.side_effect = fake_query

            with patch.object(Path, "exists", return_value=True), patch.object(
                Path, "read_text", return_value=json.dumps(entity_map_data)
            ):
                result = _run(run_cartographer(client_config))

        # _phase1_prescan must have been injected by run_cartographer
        assert "_phase1_prescan" in result
        assert "tables_probed" in result["_phase1_prescan"]
        assert "retry_attempt" in result["_phase1_prescan"]

    def test_calibration_feedback_accepted_without_error(self, business_engine):
        """run_cartographer must accept calibration_feedback without raising."""
        from valinor.agents.cartographer import run_cartographer

        client_config = {
            "name": "retry_client",
            "connection_string": _sqlite_url(business_engine),
        }
        feedback = [
            {"entity": "invoices", "feedback": "filtered_count is 0, base_filter wrong"}
        ]

        with (
            patch("valinor.agents.cartographer.query", new_callable=MagicMock) as mock_query,
            patch("valinor.agents.cartographer.create_sdk_mcp_server", return_value=MagicMock()),
        ):
            async def fake_query(**_kwargs):
                return
                yield

            mock_query.side_effect = fake_query

            # Should not raise
            result = _run(run_cartographer(client_config, calibration_feedback=feedback))

        assert isinstance(result, dict)

    def test_overrides_from_client_config_included_in_prompt(self, business_engine):
        """Overrides in client_config should be included in the prompt sent to the LLM."""
        from valinor.agents.cartographer import run_cartographer

        captured_prompts = []

        async def capturing_query(prompt, options):
            captured_prompts.append(prompt)
            return
            yield

        client_config = {
            "name": "overrides_client",
            "connection_string": _sqlite_url(business_engine),
            "overrides": {"tenant_id": "1000000", "currency": "USD"},
        }

        with (
            patch("valinor.agents.cartographer.query", side_effect=capturing_query),
            patch("valinor.agents.cartographer.create_sdk_mcp_server", return_value=MagicMock()),
        ):
            _run(run_cartographer(client_config))

        assert len(captured_prompts) == 1
        prompt_text = captured_prompts[0]
        assert "tenant_id" in prompt_text
        assert "1000000" in prompt_text
        assert "currency" in prompt_text
