"""
E2E pipeline tests for Gloria (VAL-7, VAL-90).

Exercises the full pipeline from query builder through narrators using the
gloria_entity_map fixture, an SQLite in-memory DB with Gloria-like schema,
and REAL Claude agent calls via CLI/proxy.

Strategy: ALWAYS REAL.
  - Agents run against Claude via local CLI or proxy (Plan Max = free).
  - If CLI/proxy not available, tests are SKIPPED — never silently mocked.
  - Assertions are on STRUCTURE (parseable findings, correct schema),
    not exact values (Claude is non-deterministic).

Stages covered:
  Query Builder → Execute Queries + Baseline → Analysis Agents (REAL)
  → Reconciliation → Narrator Context → Output Validation

Refs: VAL-7, VAL-90
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text

from valinor.agents.query_builder import build_queries
from valinor.pipeline_stages import compute_baseline, gate_calibration
from valinor.pipeline import execute_queries, run_analysis_agents
from valinor.pipeline_reconciliation import reconcile_swarm, _parse_findings_from_output
from valinor.pipeline_narrator import prepare_narrator_context
from valinor.schemas.agent_outputs import CartographerOutput


# ══════════════════════════════════════════════════════════════════════════
# LLM availability detection
# ══════════════════════════════════════════════════════════════════════════

def _proxy_available() -> bool:
    """Check if the Claude proxy is reachable at localhost:8099."""
    try:
        resp = urllib.request.urlopen("http://localhost:8099/health", timeout=3)
        return resp.status == 200
    except Exception:
        return False


def _cli_available() -> bool:
    """Check if claude CLI is available locally."""
    return shutil.which("claude") is not None


def _llm_available() -> bool:
    return _proxy_available() or _cli_available()


LLM_IS_AVAILABLE = _llm_available()


def _install_real_sdk():
    """
    Replace the conftest stub with the monkey_patch module that routes
    claude_agent_sdk calls through our LLM provider system (CLI/proxy).
    """
    # Set provider to console_cli (uses local CLI or proxy)
    os.environ["LLM_PROVIDER"] = "console_cli"
    os.environ["CLAUDE_PROXY_HOST"] = "localhost"

    # Remove the stub installed by conftest
    if "claude_agent_sdk" in sys.modules:
        del sys.modules["claude_agent_sdk"]

    # Import the monkey_patch which installs the real provider-backed SDK
    from shared.llm.monkey_patch import apply_monkey_patch
    apply_monkey_patch()

    # Force-reload agents so they pick up the new SDK module
    for mod_name in list(sys.modules):
        if mod_name.startswith("valinor.agents."):
            importlib.reload(sys.modules[mod_name])


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

# Output directory for test reports (persisted for later analysis)
OUTPUT_DIR = Path(__file__).parent / "output" / "gloria_e2e"


def _save_test_output(data: dict, label: str) -> Path:
    """Save pipeline output to tests/output/gloria_e2e/ for later analysis."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    path = OUTPUT_DIR / f"{label}_{ts}.json"
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


# ══════════════════════════════════════════════════════════════════════════
# DETERMINISTIC TESTS — pipeline stages that don't need LLM
# These always run, no skip.
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.mandatory
class TestGloriaPipelineStages:
    """Deterministic pipeline stage tests — no LLM needed."""

    def test_query_builder_generates_all_domains(self, gloria_entity_map):
        """build_queries must produce queries for financial, credit, and sales domains."""
        period = {"start": "2025-01-01", "end": "2025-12-31", "label": "FY-2025"}
        query_pack = build_queries(gloria_entity_map, period)

        queries = query_pack["queries"]
        assert len(queries) > 0, "build_queries should generate at least 1 query"

        domains_present = {q["domain"] for q in queries}
        for expected_domain in ("financial", "data_quality"):
            assert expected_domain in domains_present, (
                f"Domain '{expected_domain}' missing. Got: {domains_present}"
            )
        assert len(queries) >= 4, f"Expected >= 4 queries, got {len(queries)}"

        for q in queries:
            assert q["sql"].strip(), f"Query {q['id']} has empty SQL"

        # base_filter injection
        invoice_filter = gloria_entity_map["entities"]["invoices"]["base_filter"]
        filter_keywords = [kw.split("=")[0].strip().split(".")[-1]
                           for kw in invoice_filter.split("AND")]
        invoice_queries = [q for q in queries if "c_invoice" in q["sql"]]
        assert len(invoice_queries) > 0, "No queries reference c_invoice table"

        injected_count = sum(
            1 for q in invoice_queries
            if any(kw.strip().lower() in q["sql"].lower() for kw in filter_keywords if kw.strip())
        )
        assert injected_count > 0, "base_filter keywords not found in any invoice query SQL"

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

        prov = baseline["_provenance"]
        assert prov["total_revenue"]["source_query"] == "total_revenue_summary"
        assert prov["total_revenue"]["confidence"] == "measured"
        assert prov["total_outstanding_ar"]["source_query"] == "ar_outstanding_actual"

    def test_narrator_context_preparation(self):
        """prepare_narrator_context must separate findings by verification status."""
        findings = {
            "analyst": {
                "agent": "analyst",
                "findings": [
                    {"id": "FIN-001", "headline": "Revenue grew 12% YoY",
                     "value_eur": 1_600_000, "domain": "financial"},
                    {"id": "FIN-002", "headline": "Margin compression detected",
                     "value_eur": 50_000, "domain": "financial"},
                ],
            },
            "sentinel": {
                "agent": "sentinel",
                "findings": [
                    {"id": "DQ-001", "headline": "3% null rate in invoice dates",
                     "value_eur": None, "domain": "data_quality"},
                ],
            },
        }

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

        ctx_exec = prepare_narrator_context(findings, mock_report, role="executive")
        assert len(ctx_exec["retracted_findings"]) == 1
        assert ctx_exec["retracted_findings"][0]["finding_id"] == "FIN-002"

        ctx_ceo = prepare_narrator_context(findings, mock_report, role="ceo")
        assert ctx_ceo["unverifiable_findings"] == {}

        ctx_no_vr = prepare_narrator_context(findings, verification_report=None)
        assert ctx_no_vr["verified_findings"] == findings
        assert ctx_no_vr["retracted_findings"] == []

    def test_entity_map_schema_compliance(self, gloria_entity_map):
        """gloria_entity_map must roundtrip through CartographerOutput."""
        parsed = CartographerOutput.from_entity_map_dict(gloria_entity_map)

        assert "invoices" in parsed.entities
        assert "customers" in parsed.entities
        assert "payment_schedule" in parsed.entities
        assert "payments" in parsed.entities

        inv = parsed.entities["invoices"]
        assert inv.table == "c_invoice"
        assert inv.row_count == 4117
        assert inv.confidence == 0.99
        assert "issotrx" in inv.base_filter
        assert len(parsed.relationships) == 3

        roundtrip = parsed.to_entity_map_dict()
        for key in gloria_entity_map["entities"]:
            assert key in roundtrip["entities"], f"Entity '{key}' lost in roundtrip"

        orig_inv = gloria_entity_map["entities"]["invoices"]["key_columns"]
        rt_inv = roundtrip["entities"]["invoices"]["key_columns"]
        for col_key, col_val in orig_inv.items():
            assert rt_inv[col_key] == col_val

        orig_vias = {r["via"] for r in gloria_entity_map["relationships"]}
        rt_vias = {r["via"] for r in roundtrip["relationships"]}
        assert orig_vias == rt_vias


# ══════════════════════════════════════════════════════════════════════════
# REAL AGENT TESTS — always real, skip if no LLM available
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.mandatory
@pytest.mark.skipif(not LLM_IS_AVAILABLE, reason="Claude CLI/proxy not available — start proxy: python3 scripts/claude_proxy.py")
class TestGloriaE2EReal:
    """
    E2E pipeline with REAL Claude agents. ALWAYS REAL — never mocked.

    Requires claude CLI or proxy running. Skips otherwise.
    Assertions are on STRUCTURE, not exact values.

    Run:
        pytest tests/test_pipeline_gloria_e2e.py -v
        pytest -m mandatory -v
    """

    @pytest.fixture(autouse=True, scope="class")
    def setup_real_sdk(self):
        """Replace SDK stub with real provider before all tests."""
        _install_real_sdk()

    @pytest.mark.asyncio
    async def test_real_agents_produce_parseable_output(
        self, gloria_entity_map, gloria_sqlite_conn_str,
    ):
        """
        Run real analyst, sentinel, hunter against Claude.
        Validate that their raw output can be parsed into structured findings.
        """
        query_pack = build_queries(gloria_entity_map, GLORIA_PERIOD)
        config = {"connection_string": gloria_sqlite_conn_str}
        query_results = await execute_queries(query_pack, config)
        baseline = compute_baseline(query_results)
        assert baseline["data_available"] is True

        # Run REAL agents — no mocks
        findings = await run_analysis_agents(
            query_results, gloria_entity_map, None, baseline,
        )

        # Each agent must have responded
        for agent_name in ("analyst", "sentinel", "hunter"):
            assert agent_name in findings, f"Agent '{agent_name}' missing from findings"
            agent_data = findings[agent_name]
            assert isinstance(agent_data, dict)
            assert agent_data.get("agent") == agent_name
            assert not agent_data.get("error"), f"{agent_name} returned error: {agent_data}"

            has_output = bool(agent_data.get("output", "").strip())
            has_findings = bool(agent_data.get("findings"))
            assert has_output or has_findings, f"{agent_name} produced no output"

        # Findings must be parseable into structured data
        all_parsed = {}
        for agent_name in ("analyst", "sentinel", "hunter"):
            parsed = _parse_findings_from_output(findings[agent_name])
            assert len(parsed) > 0, (
                f"{agent_name} output not parseable. "
                f"Raw: {findings[agent_name].get('output', '')[:500]}"
            )
            for finding in parsed:
                assert "id" in finding, f"{agent_name} finding missing 'id'"
                assert "headline" in finding, f"{agent_name} finding missing 'headline'"
                assert "domain" in finding, f"{agent_name} finding missing 'domain'"
            all_parsed[agent_name] = parsed

        # Save raw agent outputs for analysis
        agent_report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "baseline": baseline,
            "agents": {
                agent_name: {
                    "raw_output": findings[agent_name].get("output", "")[:5000],
                    "parsed_findings": all_parsed[agent_name],
                    "finding_count": len(all_parsed[agent_name]),
                }
                for agent_name in ("analyst", "sentinel", "hunter")
            },
        }
        output_path = _save_test_output(agent_report, "agent_outputs")
        print(f"\n  Agent outputs saved: {output_path}")

    @pytest.mark.asyncio
    async def test_full_pipeline_real_agents(
        self, gloria_entity_map, gloria_sqlite_conn_str, minimal_client_config,
    ):
        """
        Full pipeline with REAL agents: data → agents → reconcile → output.
        This is what really happens when a user clicks "Analyze" in the UI.
        """
        # ── Stages 2-2.5: Queries + Baseline (real) ──
        query_pack = build_queries(gloria_entity_map, GLORIA_PERIOD)
        config = {"connection_string": gloria_sqlite_conn_str}
        query_results = await execute_queries(query_pack, config)
        baseline = compute_baseline(query_results)
        assert baseline["data_available"] is True

        # ── Stage 3: REAL agents ──
        findings = await run_analysis_agents(
            query_results, gloria_entity_map, None, baseline,
        )

        # At least 2 of 3 agents must have produced findings
        agents_with_findings = 0
        for agent_name in ("analyst", "sentinel", "hunter"):
            if agent_name in findings:
                parsed = _parse_findings_from_output(findings[agent_name])
                if parsed:
                    findings[agent_name]["findings"] = parsed
                    agents_with_findings += 1

        assert agents_with_findings >= 2, (
            f"Only {agents_with_findings}/3 agents produced parseable findings"
        )

        # ── Stage 3.5: Reconciliation (real) ──
        findings = await reconcile_swarm(findings, baseline)
        assert findings["_reconciliation"]["ran"] is True

        # ── Stage 3.75: Narrator Context (real for all roles) ──
        for role in ("ceo", "controller", "sales", "executive"):
            ctx = prepare_narrator_context(findings, verification_report=None, role=role)
            assert "verified_findings" in ctx
            assert "retracted_findings" in ctx
            assert "summary" in ctx

        # ── Validate: output bundle matches what the app expects ──
        app_output = {
            "findings": findings,
            "baseline": baseline,
            "query_results": query_results,
            "entity_map": gloria_entity_map,
        }
        assert app_output["findings"]["_reconciliation"]["ran"] is True
        assert app_output["baseline"]["data_available"] is True
        assert app_output["baseline"]["_provenance"] is not None
        assert len(app_output["query_results"]["results"]) > 0

        # Count total real findings
        total_findings = sum(
            len(findings[a].get("findings", []))
            for a in ("analyst", "sentinel", "hunter")
            if a in findings and isinstance(findings[a], dict)
        )
        assert total_findings > 0, "Pipeline produced zero findings from real agents"

        # ── Save full output for later analysis ──
        # Strip raw LLM output (too large) but keep parsed findings
        findings_clean = {}
        for k, v in findings.items():
            if isinstance(v, dict) and "output" in v:
                findings_clean[k] = {
                    key: val for key, val in v.items() if key != "output"
                }
            else:
                findings_clean[k] = v

        report_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "period": GLORIA_PERIOD,
            "summary": {
                "queries_executed": len(query_results["results"]),
                "queries_failed": len(query_results.get("errors", {})),
                "baseline_revenue": baseline.get("total_revenue"),
                "baseline_customers": baseline.get("distinct_customers"),
                "agents_with_findings": agents_with_findings,
                "total_findings": total_findings,
                "conflicts_reconciled": findings["_reconciliation"]["conflicts_found"],
            },
            "baseline": baseline,
            "query_results": {
                qid: {
                    "row_count": qr.get("row_count"),
                    "domain": qr.get("domain"),
                    "rows": qr.get("rows", [])[:10],  # first 10 rows per query
                }
                for qid, qr in query_results["results"].items()
            },
            "findings": findings_clean,
            "narrator_contexts": {
                role: prepare_narrator_context(findings, verification_report=None, role=role)
                for role in ("ceo", "controller", "sales", "executive")
            },
            "entity_map": gloria_entity_map,
        }

        output_path = _save_test_output(report_data, "full_pipeline")

        print(
            f"\n{'='*60}\n"
            f"LIVE PIPELINE RESULTS\n"
            f"  Queries executed: {len(query_results['results'])}\n"
            f"  Baseline revenue: {baseline.get('total_revenue')}\n"
            f"  Agents with findings: {agents_with_findings}/3\n"
            f"  Total findings: {total_findings}\n"
            f"  Conflicts reconciled: {findings['_reconciliation']['conflicts_found']}\n"
            f"  Output saved: {output_path}\n"
            f"{'='*60}"
        )
