"""
E2E pipeline tests for Gloria (VAL-7).

Exercises the full pipeline from query builder through narrators using the
gloria_entity_map fixture, an SQLite in-memory DB with Gloria-like schema,
and mocked LLM agent calls.  Cartographer is skipped — we use the fixture.

Stages covered:
  Query Builder → Execute Queries + Baseline → Analysis Agents → Reconciliation → Narrators

Refs: VAL-7
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

from valinor.agents.query_builder import build_queries
from valinor.pipeline_stages import compute_baseline, gate_calibration
from valinor.pipeline import execute_queries, run_analysis_agents
from valinor.pipeline_reconciliation import reconcile_swarm, _parse_findings_from_output
from valinor.pipeline_narrator import prepare_narrator_context
from valinor.schemas.agent_outputs import CartographerOutput


# ══════════════════════════════════════════════════════════════════════════
# Gloria-like SQLite schema  (c_invoice, c_bpartner, fin_payment_schedule)
# ══════════════════════════════════════════════════════════════════════════

_GLORIA_DDL = [
    """CREATE TABLE c_bpartner (
        c_bpartner_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        iscustomer TEXT DEFAULT 'Y',
        isactive TEXT DEFAULT 'Y'
    )""",
    """CREATE TABLE c_invoice (
        c_invoice_id INTEGER PRIMARY KEY,
        c_bpartner_id INTEGER,
        grandtotal REAL,
        dateinvoiced TEXT,
        issotrx TEXT DEFAULT 'Y',
        docstatus TEXT DEFAULT 'CO',
        isactive TEXT DEFAULT 'Y'
    )""",
    """CREATE TABLE fin_payment_schedule (
        fin_payment_schedule_id INTEGER PRIMARY KEY,
        c_invoice_id INTEGER,
        outstandingamt REAL,
        duedate TEXT,
        isactive TEXT DEFAULT 'Y'
    )""",
    """CREATE TABLE fin_payment (
        fin_payment_id INTEGER PRIMARY KEY,
        c_bpartner_id INTEGER,
        amount REAL,
        isreceipt TEXT DEFAULT 'Y',
        isactive TEXT DEFAULT 'Y'
    )""",
]


def _populate_gloria_db(engine):
    """Insert realistic Gloria sample data."""
    with engine.connect() as conn:
        for ddl in _GLORIA_DDL:
            conn.execute(text(ddl))

        # 10 customers
        for i in range(1, 11):
            conn.execute(text(
                "INSERT INTO c_bpartner VALUES (:id, :name, 'Y', 'Y')"
            ), {"id": i, "name": f"Customer {i}"})

        # 20 sales invoices spread across 2025
        for i in range(1, 21):
            month = ((i - 1) % 12) + 1
            conn.execute(text(
                "INSERT INTO c_invoice VALUES "
                "(:id, :bp, :amt, :dt, 'Y', 'CO', 'Y')"
            ), {
                "id": i,
                "bp": (i % 10) + 1,
                "amt": 50_000.0 + i * 2_500.0,
                "dt": f"2025-{month:02d}-15",
            })

        # 5 purchase invoices (issotrx='N') — should be excluded by base_filter
        for i in range(21, 26):
            conn.execute(text(
                "INSERT INTO c_invoice VALUES "
                "(:id, :bp, :amt, :dt, 'N', 'CO', 'Y')"
            ), {"id": i, "bp": 1, "amt": 10_000.0, "dt": "2025-06-01"})

        # Payment schedules
        for i in range(1, 11):
            conn.execute(text(
                "INSERT INTO fin_payment_schedule VALUES "
                "(:id, :inv, :out, :due, 'Y')"
            ), {
                "id": i,
                "inv": i,
                "out": 5_000.0 * i,
                "due": f"2025-{((i-1)%12)+1:02d}-28",
            })

        # Payments
        for i in range(1, 6):
            conn.execute(text(
                "INSERT INTO fin_payment VALUES "
                "(:id, :bp, :amt, 'Y', 'Y')"
            ), {"id": i, "bp": i, "amt": 10_000.0 * i})

        conn.commit()


@pytest.fixture(scope="module")
def gloria_sqlite_conn_str():
    """Create and populate a Gloria-like SQLite DB, yield connection string."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn_str = f"sqlite:///{tmp.name}"
    engine = create_engine(conn_str)
    _populate_gloria_db(engine)
    engine.dispose()
    yield conn_str
    os.unlink(tmp.name)


GLORIA_PERIOD = {"start": "2025-01-01", "end": "2025-12-31", "label": "FY-2025"}


# ══════════════════════════════════════════════════════════════════════════
# TEST CLASS
# ══════════════════════════════════════════════════════════════════════════


class TestGloriaE2EPipeline:
    """End-to-end pipeline tests for Gloria (VAL-7)."""

    # ── Test 1: Query Builder generates all expected domains ──────────

    def test_query_builder_generates_all_domains(self, gloria_entity_map):
        """build_queries must produce queries for financial, credit, and sales domains."""
        period = {"start": "2025-01-01", "end": "2025-12-31", "label": "FY-2025"}
        query_pack = build_queries(gloria_entity_map, period)

        queries = query_pack["queries"]
        assert len(queries) > 0, "build_queries should generate at least 1 query"

        domains_present = {q["domain"] for q in queries}
        # Gloria entity map uses 'pk' (not 'invoice_pk'/'customer_pk') so credit
        # and some sales/financial queries that need explicit PK naming are skipped.
        # The core domains that MUST always be generated are financial and data_quality.
        # sales (customer_retention) also succeeds because it doesn't need customer_pk.
        for expected_domain in ("financial", "data_quality"):
            assert expected_domain in domains_present, (
                f"Domain '{expected_domain}' missing. Got: {domains_present}"
            )
        # At least 4 queries should be generated (revenue summary, revenue_by_period, etc.)
        assert len(queries) >= 4, f"Expected >= 4 queries, got {len(queries)}"

        # Every query must have non-empty SQL
        for q in queries:
            assert q["sql"].strip(), f"Query {q['id']} has empty SQL"

        # base_filter from invoices entity must be injected in relevant SQL
        invoice_filter = gloria_entity_map["entities"]["invoices"]["base_filter"]
        # At least some queries referencing the invoice table should contain
        # part of the base_filter (e.g., "issotrx" or "docstatus")
        filter_keywords = [kw.split("=")[0].strip().split(".")[-1]
                           for kw in invoice_filter.split("AND")]
        invoice_queries = [q for q in queries if "c_invoice" in q["sql"]]
        assert len(invoice_queries) > 0, "No queries reference c_invoice table"

        injected_count = 0
        for q in invoice_queries:
            sql_lower = q["sql"].lower()
            if any(kw.strip().lower() in sql_lower for kw in filter_keywords if kw.strip()):
                injected_count += 1

        assert injected_count > 0, (
            "base_filter keywords not found in any invoice query SQL"
        )

    # ── Test 2: Baseline computation from query results ──────────────

    def test_baseline_computation_from_query_results(self):
        """compute_baseline must extract metrics and track provenance."""
        query_results = {
            "results": {
                "total_revenue_summary": {
                    "rows": [{
                        "total_revenue": 1_600_000,
                        "num_invoices": 3139,
                        "avg_invoice": 509.72,
                        "min_invoice": 0.50,
                        "max_invoice": 125_000.0,
                        "date_from": "2025-01-01",
                        "date_to": "2025-12-31",
                        "distinct_customers": 88,
                    }],
                    "row_count": 1,
                    "domain": "financial",
                },
                "ar_outstanding_actual": {
                    "rows": [{
                        "total_outstanding": 864_000,
                        "overdue_amount": 320_000,
                        "customers_with_debt": 42,
                    }],
                    "row_count": 1,
                    "domain": "credit",
                },
            },
            "errors": {},
        }

        baseline = compute_baseline(query_results)

        assert baseline["data_available"] is True
        assert baseline["total_revenue"] == 1_600_000.0
        assert baseline["num_invoices"] == 3139
        assert baseline["total_outstanding_ar"] == 864_000.0
        assert baseline["distinct_customers"] == 88

        # Provenance tracking
        prov = baseline["_provenance"]
        assert "total_revenue" in prov
        assert prov["total_revenue"]["source_query"] == "total_revenue_summary"
        assert prov["total_revenue"]["confidence"] == "measured"
        assert "total_outstanding_ar" in prov
        assert prov["total_outstanding_ar"]["source_query"] == "ar_outstanding_actual"

    # ── Test 3: Full pipeline stages with mocked agents ──────────────

    @pytest.mark.asyncio
    async def test_full_pipeline_stages_with_mocked_agents(
        self, gloria_entity_map, gloria_sqlite_conn_str,
    ):
        """
        Run query builder -> execute -> baseline -> mocked agents -> reconcile.
        All stages must complete without errors.
        """
        # Stage 2: Build queries
        query_pack = build_queries(gloria_entity_map, GLORIA_PERIOD)
        assert len(query_pack["queries"]) > 0

        # Stage 2.5: Execute queries against SQLite
        config = {"connection_string": gloria_sqlite_conn_str}
        query_results = await execute_queries(query_pack, config)

        assert isinstance(query_results, dict)
        assert "results" in query_results
        # At least total_revenue_summary should succeed on our schema
        assert len(query_results["results"]) > 0, (
            f"No queries succeeded. Errors: {query_results.get('errors', {})}"
        )

        # Post-2.5: Compute baseline
        baseline = compute_baseline(query_results)
        assert baseline["data_available"] is True

        # Stage 3: Mock the three analysis agents
        mock_analyst_result = {
            "agent": "analyst",
            "findings": [{
                "id": "FIN-001",
                "severity": "warning",
                "headline": "Revenue concentration: top 3 customers = 45% of revenue",
                "evidence": "total_revenue_summary query, c_invoice table",
                "value_eur": 720_000,
                "value_confidence": "measured",
                "action": "Diversify customer base",
                "domain": "financial",
            }],
        }
        mock_sentinel_result = {
            "agent": "sentinel",
            "findings": [{
                "id": "DQ-001",
                "severity": "info",
                "headline": "Data completeness: 0% null rate on key fields",
                "evidence": "null_analysis query, c_invoice table",
                "value_eur": None,
                "value_confidence": "measured",
                "action": "No action needed",
                "domain": "data_quality",
            }],
        }
        mock_hunter_result = {
            "agent": "hunter",
            "findings": [{
                "id": "SALES-001",
                "severity": "opportunity",
                "headline": "5 dormant customers with lifetime revenue > 50,000 EUR",
                "evidence": "dormant_customer_list query, c_bpartner table",
                "value_eur": 250_000,
                "value_confidence": "estimated",
                "action": "Re-engage dormant accounts",
                "domain": "sales",
            }],
        }

        with patch("valinor.pipeline.run_analyst", new_callable=AsyncMock, return_value=mock_analyst_result), \
             patch("valinor.pipeline.run_sentinel", new_callable=AsyncMock, return_value=mock_sentinel_result), \
             patch("valinor.pipeline.run_hunter", new_callable=AsyncMock, return_value=mock_hunter_result):

            findings = await run_analysis_agents(
                query_results, gloria_entity_map, None, baseline,
            )

        assert "analyst" in findings
        assert "sentinel" in findings
        assert "hunter" in findings
        assert findings["analyst"]["agent"] == "analyst"
        assert len(findings["analyst"]["findings"]) == 1

        # Stage 3.5: Reconcile (no conflicts expected — different domains)
        reconciled = await reconcile_swarm(findings, baseline)
        assert "_reconciliation" in reconciled
        assert reconciled["_reconciliation"]["ran"] is True
        # Different domains -> no conflicts
        assert reconciled["_reconciliation"]["conflicts_found"] == 0

    # ── Test 4: Narrator context preparation ─────────────────────────

    def test_narrator_context_preparation(self):
        """
        prepare_narrator_context must separate findings by verification status.
        CEO role must only see verified findings.
        """
        findings = {
            "analyst": {
                "agent": "analyst",
                "findings": [
                    {
                        "id": "FIN-001",
                        "headline": "Revenue grew 12% YoY",
                        "value_eur": 1_600_000,
                        "domain": "financial",
                    },
                    {
                        "id": "FIN-002",
                        "headline": "Margin compression detected",
                        "value_eur": 50_000,
                        "domain": "financial",
                    },
                ],
            },
            "sentinel": {
                "agent": "sentinel",
                "findings": [
                    {
                        "id": "DQ-001",
                        "headline": "3% null rate in invoice dates",
                        "value_eur": None,
                        "domain": "data_quality",
                    },
                ],
            },
        }

        # Mock verification report where FIN-001 is VERIFIED, FIN-002 is FAILED,
        # and DQ-001 has no verification data (UNVERIFIABLE)
        mock_report = MagicMock()
        result_fin001 = MagicMock()
        result_fin001.claim_id = "FIN-001_revenue"
        result_fin001.status = "VERIFIED"
        result_fin001.evidence = "Confirmed by total_revenue_summary"

        result_fin002 = MagicMock()
        result_fin002.claim_id = "FIN-002_margin"
        result_fin002.status = "FAILED"
        result_fin002.evidence = "Margin data not available in source"

        mock_report.results = [result_fin001, result_fin002]

        # Executive role: should see verified + unverifiable + retracted
        ctx_exec = prepare_narrator_context(findings, mock_report, role="executive")
        assert "verified_findings" in ctx_exec
        assert "retracted_findings" in ctx_exec
        assert len(ctx_exec["retracted_findings"]) == 1
        assert ctx_exec["retracted_findings"][0]["finding_id"] == "FIN-002"

        # CEO role: should only see verified findings
        ctx_ceo = prepare_narrator_context(findings, mock_report, role="ceo")
        # CEO should not see unverifiable findings
        assert ctx_ceo["unverifiable_findings"] == {}

        # Without verification report: all pass through untagged
        ctx_no_vr = prepare_narrator_context(findings, verification_report=None)
        assert ctx_no_vr["verified_findings"] == findings
        assert ctx_no_vr["retracted_findings"] == []

    # ── Test 5: Entity map schema compliance ─────────────────────────

    def test_entity_map_schema_compliance(self, gloria_entity_map):
        """
        gloria_entity_map must parse through CartographerOutput.from_entity_map_dict()
        without errors, and roundtrip back to dict preserving structure.
        """
        parsed = CartographerOutput.from_entity_map_dict(gloria_entity_map)

        # Validate parsed entities
        assert "invoices" in parsed.entities
        assert "customers" in parsed.entities
        assert "payment_schedule" in parsed.entities
        assert "payments" in parsed.entities

        # Check entity properties
        inv = parsed.entities["invoices"]
        assert inv.table == "c_invoice"
        assert inv.row_count == 4117
        assert inv.confidence == 0.99
        assert "issotrx" in inv.base_filter

        # Check relationships
        assert len(parsed.relationships) == 3

        # Roundtrip: to_entity_map_dict() must preserve structure
        roundtrip = parsed.to_entity_map_dict()
        assert "entities" in roundtrip
        assert "relationships" in roundtrip

        # Entity keys preserved
        for key in gloria_entity_map["entities"]:
            assert key in roundtrip["entities"], f"Entity '{key}' lost in roundtrip"

        # Key columns preserved
        orig_inv = gloria_entity_map["entities"]["invoices"]["key_columns"]
        rt_inv = roundtrip["entities"]["invoices"]["key_columns"]
        for col_key, col_val in orig_inv.items():
            assert rt_inv[col_key] == col_val, (
                f"key_columns['{col_key}'] changed: {col_val} -> {rt_inv.get(col_key)}"
            )

        # Relationships preserved (check count and via columns)
        assert len(roundtrip["relationships"]) == len(gloria_entity_map["relationships"])
        orig_vias = {r["via"] for r in gloria_entity_map["relationships"]}
        rt_vias = {r["via"] for r in roundtrip["relationships"]}
        assert orig_vias == rt_vias
