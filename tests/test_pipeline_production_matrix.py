"""
PRODUCTION MATRIX TEST — Multiple clients × timelines × repetitions.

Runs the FULL pipeline (DQ → Queries → Baseline → Agents → Reconcile → Narrators)
against real databases with real Claude agents. Zero mocks.

Matrix:
  Clients:   Gloria (PostgreSQL :5432), HardisGroup (PostgreSQL :5436)
  Timelines: 1 month, 1 quarter, 1 year
  Reps:      3 per combination → 18 total runs

Output saved to tests/output/production_matrix/ with run metadata for
consistency analysis across repetitions.

Requires:
  - Gloria PostgreSQL on localhost:5432 (user=tad, pass=tad, db=gloria)
  - HardisGroup PostgreSQL on localhost:5436 (user=tad, pass=tad, db=HardisGroup)
  - Claude CLI or proxy running

Refs: VAL-90
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import shutil
import time
import urllib.request
from pathlib import Path

import pytest

# ══════════════════════════════════════════════════════════════════════════
# Prerequisites
# ══════════════════════════════════════════════════════════════════════════

GLORIA_CONN = "postgresql://tad:tad@localhost:5432/gloria"
HARDIS_CONN = "postgresql://tad:tad@localhost:5436/HardisGroup"
OUTPUT_DIR = Path(__file__).parent / "output" / "production_matrix"


def _pg_available(conn: str) -> bool:
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(conn)
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _llm_available() -> bool:
    try:
        resp = urllib.request.urlopen("http://localhost:8099/health", timeout=3)
        return resp.status == 200
    except Exception:
        pass
    return shutil.which("claude") is not None


GLORIA_AVAILABLE = _pg_available(GLORIA_CONN)
HARDIS_AVAILABLE = _pg_available(HARDIS_CONN)
LLM_IS_AVAILABLE = _llm_available()


def _install_real_sdk():
    os.environ["LLM_PROVIDER"] = "console_cli"
    os.environ["CLAUDE_PROXY_HOST"] = "localhost"
    if "claude_agent_sdk" in sys.modules:
        del sys.modules["claude_agent_sdk"]
    from shared.llm.monkey_patch import apply_monkey_patch
    apply_monkey_patch()
    for mod_name in list(sys.modules):
        if mod_name.startswith("valinor.agents."):
            importlib.reload(sys.modules[mod_name])


def _save_output(data: dict, label: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    path = OUTPUT_DIR / f"{label}_{ts}.json"
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


def _save_report(content: str, name: str, subdir: str) -> Path:
    reports_dir = OUTPUT_DIR / "reports" / subdir
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    path = reports_dir / f"{name}_{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════
# Client configurations
# ══════════════════════════════════════════════════════════════════════════

CLIENTS = {
    "gloria": {
        "connection_string": GLORIA_CONN,
        "client_config": {
            "name": "gloria",
            "display_name": "Gloria (Openbravo)",
            "sector": "distribucion",
            "currency": "EUR",
            "language": "es",
            "erp": "openbravo",
        },
        "available": GLORIA_AVAILABLE,
    },
    "hardis": {
        "connection_string": HARDIS_CONN,
        "client_config": {
            "name": "hardis",
            "display_name": "Hardis Group (Openbravo)",
            "sector": "logistica",
            "currency": "EUR",
            "language": "es",
            "erp": "openbravo",
        },
        "available": HARDIS_AVAILABLE,
    },
}

TIMELINES = {
    "1_month": {"start": "2025-12-01", "end": "2025-12-12", "label": "Dec-2025"},
    "1_quarter": {"start": "2025-10-01", "end": "2025-12-12", "label": "Q4-2025"},
    "1_year": {"start": "2025-01-01", "end": "2025-12-12", "label": "FY-2025"},
}

REPETITIONS = 3


# ══════════════════════════════════════════════════════════════════════════
# Entity map builder (per client)
# ══════════════════════════════════════════════════════════════════════════

def _build_entity_map(conn_str: str) -> dict:
    """Query real DB to build accurate entity_map."""
    from sqlalchemy import create_engine, text
    engine = create_engine(conn_str)

    with engine.connect() as conn:
        inv = conn.execute(text("SELECT COUNT(*) FROM c_invoice")).scalar()
        inv_sales = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE issotrx='Y'")).scalar()
        inv_purch = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE issotrx='N'")).scalar()
        inv_co = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE docstatus='CO'")).scalar()
        inv_dr = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE docstatus='DR'")).scalar()
        inv_active = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE isactive='Y'")).scalar()

        bp = conn.execute(text("SELECT COUNT(*) FROM c_bpartner")).scalar()
        bp_cust = conn.execute(text("SELECT COUNT(*) FROM c_bpartner WHERE iscustomer='Y'")).scalar()
        bp_non = conn.execute(text("SELECT COUNT(*) FROM c_bpartner WHERE iscustomer='N'")).scalar()
        bp_active = conn.execute(text("SELECT COUNT(*) FROM c_bpartner WHERE isactive='Y'")).scalar()

        ps = conn.execute(text("SELECT COUNT(*) FROM fin_payment_schedule")).scalar()
        ps_active = conn.execute(text("SELECT COUNT(*) FROM fin_payment_schedule WHERE isactive='Y'")).scalar()

        pay = conn.execute(text("SELECT COUNT(*) FROM fin_payment")).scalar()
        pay_receipt = conn.execute(text("SELECT COUNT(*) FROM fin_payment WHERE isreceipt='Y'")).scalar()
        pay_disb = conn.execute(text("SELECT COUNT(*) FROM fin_payment WHERE isreceipt='N'")).scalar()
        pay_active = conn.execute(text("SELECT COUNT(*) FROM fin_payment WHERE isactive='Y'")).scalar()

    engine.dispose()

    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "type": "TRANSACTIONAL",
                "row_count": inv,
                "confidence": 0.99,
                "key_columns": {
                    "pk": "c_invoice_id",
                    "invoice_date": "dateinvoiced",
                    "amount_col": "grandtotal",
                    "customer_fk": "c_bpartner_id",
                },
                "base_filter": "issotrx='Y' AND docstatus='CO' AND isactive='Y'",
                "probed_values": {
                    "issotrx": {"Y": inv_sales, "N": inv_purch},
                    "docstatus": {"CO": inv_co, "DR": inv_dr},
                    "isactive": {"Y": inv_active},
                },
            },
            "customers": {
                "table": "c_bpartner",
                "type": "MASTER",
                "row_count": bp,
                "confidence": 0.98,
                "key_columns": {
                    "pk": "c_bpartner_id",
                    "customer_name": "name",
                },
                "base_filter": "iscustomer='Y' AND isactive='Y'",
                "probed_values": {
                    "iscustomer": {"Y": bp_cust, "N": bp_non},
                    "isactive": {"Y": bp_active},
                },
            },
            "payment_schedule": {
                "table": "fin_payment_schedule",
                "type": "TRANSACTIONAL",
                "row_count": ps,
                "confidence": 0.97,
                "key_columns": {
                    "pk": "fin_payment_schedule_id",
                    "invoice_fk": "c_invoice_id",
                    "outstanding_amount": "outstandingamt",
                    "due_date": "duedate",
                },
                "base_filter": "isactive='Y'",
                "probed_values": {
                    "isactive": {"Y": ps_active},
                },
            },
            "payments": {
                "table": "fin_payment",
                "type": "TRANSACTIONAL",
                "row_count": pay,
                "confidence": 0.97,
                "key_columns": {
                    "pk": "fin_payment_id",
                    "partner_fk": "c_bpartner_id",
                    "amount": "amount",
                },
                "base_filter": "isreceipt='Y' AND isactive='Y'",
                "probed_values": {
                    "isreceipt": {"Y": pay_receipt, "N": pay_disb},
                    "isactive": {"Y": pay_active},
                },
            },
        },
        "relationships": [
            {"from": "invoices", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
            {"from": "payment_schedule", "to": "invoices", "via": "c_invoice_id", "cardinality": "N:1"},
            {"from": "payments", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# Test matrix generation
# ══════════════════════════════════════════════════════════════════════════

def _generate_matrix():
    """Generate (client_name, timeline_name, period, rep) tuples."""
    params = []
    for client_name, client_data in CLIENTS.items():
        if not client_data["available"]:
            continue
        for timeline_name, period in TIMELINES.items():
            for rep in range(1, REPETITIONS + 1):
                test_id = f"{client_name}-{timeline_name}-rep{rep}"
                params.append(
                    pytest.param(
                        client_name, timeline_name, period, rep,
                        id=test_id,
                    )
                )
    return params


MATRIX_PARAMS = _generate_matrix()

SKIP_REASON = []
if not GLORIA_AVAILABLE and not HARDIS_AVAILABLE:
    SKIP_REASON.append("No PostgreSQL clients available (Gloria:5432, Hardis:5436)")
if not LLM_IS_AVAILABLE:
    SKIP_REASON.append("Claude CLI/proxy not available")


# ══════════════════════════════════════════════════════════════════════════
# TEST CLASS
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(bool(SKIP_REASON), reason=" + ".join(SKIP_REASON))
class TestProductionMatrix:
    """
    Full production pipeline — ALL real, ZERO mocks.
    Runs across clients × timelines × repetitions.

    Run with: pytest tests/test_pipeline_production_matrix.py -v -s
    """

    @pytest.fixture(autouse=True, scope="class")
    def setup_real_sdk(self):
        _install_real_sdk()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "client_name,timeline_name,period,rep",
        MATRIX_PARAMS,
    )
    async def test_production_pipeline(
        self, client_name, timeline_name, period, rep,
    ):
        """
        Full pipeline for a client × timeline × repetition.
        DQ Gate → Queries → Baseline → Agents → Reconcile → Narrators.
        """
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline_stages import compute_baseline, gate_calibration
        from valinor.pipeline import execute_queries, run_analysis_agents
        from valinor.pipeline_reconciliation import reconcile_swarm, _parse_findings_from_output
        from valinor.pipeline_narrator import prepare_narrator_context, run_narrators
        from valinor.quality.data_quality_gate import DataQualityGate
        from sqlalchemy import create_engine

        client_data = CLIENTS[client_name]
        conn_str = client_data["connection_string"]
        client_config = client_data["client_config"]
        config = {"connection_string": conn_str}

        run_label = f"{client_name}_{timeline_name}_rep{rep}"
        run_start = time.time()

        print(f"\n{'='*70}")
        print(f"  PRODUCTION MATRIX — {client_name.upper()} | {timeline_name} | rep {rep}/3")
        print(f"  Period: {period['label']} ({period['start']} → {period['end']})")
        print(f"  DB: {conn_str}")
        print(f"{'='*70}")

        # ── Stage 0: Data Quality Gate ──
        print("\n  Stage 0: Data Quality Gate...")
        t0 = time.time()
        dq_engine = create_engine(conn_str)
        dq_gate = DataQualityGate(
            engine=dq_engine,
            period_start=period["start"],
            period_end=period["end"],
            erp=client_config.get("erp", "generic"),
        )
        dq_report = dq_gate.run()
        dq_engine.dispose()
        dq_time = time.time() - t0
        print(f"    DQ Score: {dq_report.overall_score:.0f}/100 ({dq_report.gate_decision}) [{dq_time:.1f}s]")

        assert dq_report.gate_decision != "HALT", (
            f"DQ Gate halted for {run_label}: {dq_report.blocking_issues}"
        )

        # ── Stage 1.5: Build entity_map from real DB ──
        print("\n  Stage 1.5: Building entity map...")
        entity_map = _build_entity_map(conn_str)
        print(f"    Entities: {list(entity_map['entities'].keys())}")

        # ── Stage 1.5b: Gate Calibration ──
        print("\n  Stage 1.5b: Gate Calibration...")
        t0 = time.time()
        calibration = await gate_calibration(entity_map, config)
        cal_time = time.time() - t0
        print(f"    Calibration: {'PASS' if calibration['passed'] else 'FAIL'} [{cal_time:.1f}s]")

        # ── Stage 2: Query Builder ──
        print("\n  Stage 2: Query Builder...")
        query_pack = build_queries(entity_map, period)
        print(f"    {len(query_pack['queries'])} queries built, {len(query_pack['skipped'])} skipped")

        # ── Stage 2.5: Execute Queries ──
        print("\n  Stage 2.5: Executing queries against PostgreSQL...")
        t0 = time.time()
        query_results = await execute_queries(query_pack, config)
        query_time = time.time() - t0
        print(f"    {len(query_results['results'])} succeeded, {len(query_results['errors'])} failed [{query_time:.1f}s]")

        for qid in sorted(query_results["results"]):
            qr = query_results["results"][qid]
            print(f"      OK {qid}: {qr['row_count']} rows")
        for qid, err in query_results["errors"].items():
            print(f"      FAIL {qid}: {err['error'][:80]}")

        assert len(query_results["results"]) > 0, f"No queries succeeded for {run_label}"

        # ── Post-2.5: Compute Baseline ──
        baseline = compute_baseline(query_results)
        baseline["dq_score"] = dq_report.overall_score
        baseline["dq_confidence"] = dq_report.confidence_label
        baseline["dq_tag"] = dq_report.data_quality_tag
        baseline["dq_context"] = dq_report.to_prompt_context()

        print(f"\n    Baseline: revenue={baseline.get('total_revenue', 0):,.0f} | "
              f"invoices={baseline.get('num_invoices', 0)} | "
              f"customers={baseline.get('distinct_customers', 0)}")

        assert baseline["data_available"] is True, f"No data available for {run_label}"

        # ── Stage 3: REAL Analysis Agents ──
        print("\n  Stage 3: Analysis agents (REAL Claude)...")
        t0 = time.time()
        findings = await run_analysis_agents(
            query_results, entity_map, None, baseline,
        )
        agents_time = time.time() - t0

        agents_ok = 0
        for agent_name in ("analyst", "sentinel", "hunter"):
            if agent_name in findings and isinstance(findings[agent_name], dict):
                parsed = _parse_findings_from_output(findings[agent_name])
                if parsed:
                    findings[agent_name]["findings"] = parsed
                    agents_ok += 1
                    print(f"    OK {agent_name}: {len(parsed)} findings")
                else:
                    print(f"    WARN {agent_name}: no parseable findings")
            else:
                print(f"    FAIL {agent_name}: missing or error")
        print(f"    [{agents_time:.1f}s]")

        assert agents_ok >= 2, f"Only {agents_ok}/3 agents for {run_label}"

        # ── Stage 3.5: Reconciliation ──
        print("\n  Stage 3.5: Reconciliation...")
        t0 = time.time()
        findings = await reconcile_swarm(findings, baseline)
        recon = findings["_reconciliation"]
        recon_time = time.time() - t0
        print(f"    Conflicts: {recon['conflicts_found']} [{recon_time:.1f}s]")

        # ── Stage 3.75: Narrator Context ──
        print("\n  Stage 3.75: Narrator context...")
        narrator_contexts = {}
        for role in ("ceo", "controller", "sales", "executive"):
            ctx = prepare_narrator_context(findings, verification_report=None, role=role)
            narrator_contexts[role] = ctx

        # ── Stage 4: REAL Narrators ──
        print("\n  Stage 4: Narrators (REAL Claude)...")
        t0 = time.time()
        reports = await run_narrators(
            findings, entity_map, None, client_config,
            baseline, query_results,
            narrator_timeout=180,
        )
        narrator_time = time.time() - t0
        print(f"    {len(reports)} reports generated [{narrator_time:.1f}s]")

        report_subdir = f"{client_name}_{timeline_name}_rep{rep}"
        for name, content in reports.items():
            chars = len(content)
            is_error = content.startswith("# Error") or "timed out" in content.lower()
            status = "FAIL" if is_error else "OK"
            print(f"    {status} {name}: {chars:,} chars")
            _save_report(content, name, report_subdir)

        total_time = time.time() - run_start

        # ── Count findings ──
        total_findings = sum(
            len(findings[a].get("findings", []))
            for a in ("analyst", "sentinel", "hunter")
            if a in findings and isinstance(findings[a], dict)
        )

        # ── Save full output ──
        findings_clean = {}
        for k, v in findings.items():
            if isinstance(v, dict) and "output" in v:
                findings_clean[k] = {kk: vv for kk, vv in v.items() if kk != "output"}
            else:
                findings_clean[k] = v

        real_reports = {
            name: content for name, content in reports.items()
            if not content.startswith("# Error")
            and "timed out" not in content.lower()
            and len(content) > 200
        }

        output = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "run_label": run_label,
            "client": client_config,
            "period": period,
            "timeline": timeline_name,
            "repetition": rep,
            "total_time_seconds": round(total_time, 1),
            "stage_times": {
                "dq_gate": round(dq_time, 1),
                "calibration": round(cal_time, 1),
                "queries": round(query_time, 1),
                "agents": round(agents_time, 1),
                "reconciliation": round(recon_time, 1),
                "narrators": round(narrator_time, 1),
            },
            "dq_gate": {
                "score": dq_report.overall_score,
                "decision": dq_report.gate_decision,
                "confidence": dq_report.confidence_label,
                "checks_passed": sum(1 for c in dq_report.checks if c.passed),
                "checks_total": len(dq_report.checks),
            },
            "calibration": {
                "passed": calibration["passed"],
                "entities_verified": calibration["entities_verified"],
            },
            "summary": {
                "queries_built": len(query_pack["queries"]),
                "queries_executed": len(query_results["results"]),
                "queries_failed": len(query_results["errors"]),
                "baseline_revenue": baseline.get("total_revenue"),
                "baseline_invoices": baseline.get("num_invoices"),
                "baseline_customers": baseline.get("distinct_customers"),
                "agents_with_findings": agents_ok,
                "total_findings": total_findings,
                "conflicts": recon["conflicts_found"],
                "reports_generated": len(reports),
                "real_reports": len(real_reports),
            },
            "baseline": baseline,
            "query_results": {
                qid: {
                    "row_count": qr.get("row_count"),
                    "domain": qr.get("domain"),
                    "rows": qr.get("rows", [])[:20],
                }
                for qid, qr in query_results["results"].items()
            },
            "query_errors": {
                qid: err.get("error", "")[:200]
                for qid, err in query_results.get("errors", {}).items()
            },
            "findings": findings_clean,
            "reports": {name: content for name, content in reports.items()},
            "entity_map": entity_map,
        }

        output_path = _save_output(output, run_label)

        print(f"\n{'='*70}")
        print(f"  {run_label.upper()} COMPLETE — {total_time:.0f}s")
        print(f"  DQ: {dq_report.overall_score:.0f}/100 | "
              f"Queries: {len(query_results['results'])}/{len(query_pack['queries'])} | "
              f"Revenue: {baseline.get('total_revenue', 0):,.0f}")
        print(f"  Agents: {agents_ok}/3 | Findings: {total_findings} | "
              f"Reports: {len(real_reports)}/{len(reports)}")
        print(f"  Output: {output_path}")
        print(f"{'='*70}")

        # ── Assertions ──
        assert total_findings > 0, f"Zero findings for {run_label}"
        assert len(reports) >= 3, f"Only {len(reports)} reports for {run_label}"
        assert len(real_reports) >= 2, (
            f"Only {len(real_reports)} real reports for {run_label}. "
            f"Statuses: {', '.join(f'{n}={len(c)} chars' for n, c in reports.items())}"
        )
