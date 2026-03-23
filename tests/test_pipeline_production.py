"""
PRODUCTION PIPELINE TEST — Full real pipeline against Gloria PostgreSQL.

This is the definitive test: runs the EXACT same pipeline as the app
against the real Gloria database on localhost:5432.

ALL stages are REAL — zero mocks:
  Stage 0:    Data Quality Gate
  Stage 1.5:  Gate Calibration (guard rail)
  Stage 2:    Query Builder
  Stage 2.5:  Execute Queries (PostgreSQL — DATE_TRUNC, EXTRACT work)
  Post-2.5:   Compute Baseline
  Stage 3:    Analysis Agents (analyst, sentinel, hunter — REAL Claude)
  Stage 3.5:  Reconciliation
  Stage 3.75: Narrator Context
  Stage 4:    Narrators (CEO, controller, sales, executive — REAL Claude)

Output saved to tests/output/production/ for analysis.

Requires:
  - Gloria PostgreSQL on localhost:5432 (user=tad, pass=tad, db=gloria)
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
OUTPUT_DIR = Path(__file__).parent / "output" / "production"


def _pg_available() -> bool:
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine(GLORIA_CONN)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
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


PG_IS_AVAILABLE = _pg_available()
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


def _save_report(content: str, name: str) -> Path:
    """Save a narrator report as markdown."""
    reports_dir = OUTPUT_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    path = reports_dir / f"{name}_{ts}.md"
    path.write_text(content, encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════
# Gloria entity map — built from real DB stats
# ══════════════════════════════════════════════════════════════════════════

def _build_entity_map_from_gloria() -> dict:
    """Query the real Gloria DB to build an accurate entity_map."""
    from sqlalchemy import create_engine, text
    engine = create_engine(GLORIA_CONN)

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
# TEST
# ══════════════════════════════════════════════════════════════════════════

SKIP_REASON = []
if not PG_IS_AVAILABLE:
    SKIP_REASON.append("Gloria PostgreSQL not available (localhost:5432)")
if not LLM_IS_AVAILABLE:
    SKIP_REASON.append("Claude CLI/proxy not available")


@pytest.mark.skipif(bool(SKIP_REASON), reason=" + ".join(SKIP_REASON))
class TestProductionPipeline:
    """
    Full production pipeline — ALL real, ZERO mocks.
    Run with: pytest tests/test_pipeline_production.py -v -s
    """

    @pytest.fixture(autouse=True, scope="class")
    def setup_real_sdk(self):
        _install_real_sdk()

    @pytest.mark.asyncio
    async def test_full_production_pipeline_q1_2025(self):
        """
        Q1-2025: ~9,400 invoices, €4.8M, 2,200 customers.
        Full pipeline: DQ Gate → Queries → Baseline → Agents → Reconcile → Narrators.
        """
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline_stages import compute_baseline, gate_calibration
        from valinor.pipeline import execute_queries, run_analysis_agents
        from valinor.pipeline_reconciliation import reconcile_swarm, _parse_findings_from_output
        from valinor.pipeline_narrator import prepare_narrator_context, run_narrators
        from valinor.quality.data_quality_gate import DataQualityGate
        from sqlalchemy import create_engine

        run_start = time.time()
        period = {"start": "2025-01-01", "end": "2025-03-31", "label": "Q1-2025"}
        config = {"connection_string": GLORIA_CONN}
        client_config = {
            "name": "gloria",
            "display_name": "Gloria (Openbravo)",
            "sector": "distribucion",
            "currency": "EUR",
            "language": "es",
            "erp": "openbravo",
        }

        print(f"\n{'='*70}")
        print(f"  VALINOR PRODUCTION TEST — Gloria Q1-2025")
        print(f"  DB: {GLORIA_CONN}")
        print(f"{'='*70}")

        # ── Stage 0: Data Quality Gate ──
        print("\n▸ Stage 0: Data Quality Gate...")
        t0 = time.time()
        dq_engine = create_engine(GLORIA_CONN)
        dq_gate = DataQualityGate(
            engine=dq_engine,
            period_start=period["start"],
            period_end=period["end"],
            erp="openbravo",
        )
        dq_report = dq_gate.run()
        dq_engine.dispose()
        print(f"  DQ Score: {dq_report.overall_score:.0f}/100 ({dq_report.gate_decision}) [{time.time()-t0:.1f}s]")

        assert dq_report.gate_decision != "HALT", f"DQ Gate halted: {dq_report.blocking_issues}"

        # ── Stage 1.5: Build entity_map from real DB ──
        print("\n▸ Stage 1.5: Building entity map from real DB...")
        entity_map = _build_entity_map_from_gloria()
        print(f"  Entities: {list(entity_map['entities'].keys())}")

        # ── Stage 1.5b: Gate Calibration ──
        print("\n▸ Stage 1.5b: Gate Calibration...")
        t0 = time.time()
        calibration = await gate_calibration(entity_map, config)
        print(f"  Calibration: {'PASS' if calibration['passed'] else 'FAIL'} [{time.time()-t0:.1f}s]")

        # ── Stage 2: Query Builder ──
        print("\n▸ Stage 2: Query Builder...")
        query_pack = build_queries(entity_map, period)
        print(f"  {len(query_pack['queries'])} queries built, {len(query_pack['skipped'])} skipped")

        # ── Stage 2.5: Execute Queries (real PostgreSQL!) ──
        print("\n▸ Stage 2.5: Executing queries against PostgreSQL...")
        t0 = time.time()
        query_results = await execute_queries(query_pack, config)
        print(f"  {len(query_results['results'])} succeeded, {len(query_results['errors'])} failed [{time.time()-t0:.1f}s]")

        for qid in sorted(query_results["results"]):
            qr = query_results["results"][qid]
            print(f"    ✅ {qid}: {qr['row_count']} rows ({qr.get('domain', '?')})")
        for qid, err in query_results["errors"].items():
            print(f"    ❌ {qid}: {err['error'][:80]}")

        assert len(query_results["results"]) > 0, "No queries succeeded"

        # ── Post-2.5: Compute Baseline ──
        baseline = compute_baseline(query_results)
        baseline["dq_score"] = dq_report.overall_score
        baseline["dq_confidence"] = dq_report.confidence_label
        baseline["dq_tag"] = dq_report.data_quality_tag
        baseline["dq_context"] = dq_report.to_prompt_context()

        print(f"\n  Baseline: revenue=€{baseline.get('total_revenue', 0):,.0f} | "
              f"invoices={baseline.get('num_invoices', 0)} | "
              f"customers={baseline.get('distinct_customers', 0)}")

        assert baseline["data_available"] is True

        # ── Stage 3: REAL Analysis Agents ──
        print("\n▸ Stage 3: Analysis agents (REAL Claude)...")
        t0 = time.time()
        findings = await run_analysis_agents(
            query_results, entity_map, None, baseline,
        )
        agents_time = time.time() - t0

        # Parse findings
        agents_ok = 0
        for agent_name in ("analyst", "sentinel", "hunter"):
            if agent_name in findings and isinstance(findings[agent_name], dict):
                parsed = _parse_findings_from_output(findings[agent_name])
                if parsed:
                    findings[agent_name]["findings"] = parsed
                    agents_ok += 1
                    print(f"  ✅ {agent_name}: {len(parsed)} findings")
                else:
                    print(f"  ⚠️  {agent_name}: no parseable findings")
            else:
                print(f"  ❌ {agent_name}: missing or error")
        print(f"  [{agents_time:.1f}s]")

        assert agents_ok >= 2, f"Only {agents_ok}/3 agents produced findings"

        # ── Stage 3.5: Reconciliation ──
        print("\n▸ Stage 3.5: Reconciliation...")
        t0 = time.time()
        findings = await reconcile_swarm(findings, baseline)
        recon = findings["_reconciliation"]
        print(f"  Conflicts: {recon['conflicts_found']} [{time.time()-t0:.1f}s]")

        # ── Stage 3.75: Narrator Context ──
        print("\n▸ Stage 3.75: Narrator context...")
        narrator_contexts = {}
        for role in ("ceo", "controller", "sales", "executive"):
            ctx = prepare_narrator_context(findings, verification_report=None, role=role)
            narrator_contexts[role] = ctx

        # ── Stage 4: REAL Narrators ──
        print("\n▸ Stage 4: Narrators (REAL Claude)...")
        t0 = time.time()
        reports = await run_narrators(
            findings, entity_map, None, client_config,
            baseline, query_results,
            narrator_timeout=180,
        )
        print(f"  {len(reports)} reports generated [{time.time()-t0:.1f}s]")

        for name, content in reports.items():
            chars = len(content)
            is_error = content.startswith("# Error") or "timed out" in content.lower()
            status = "❌" if is_error else "✅"
            print(f"  {status} {name}: {chars:,} chars")
            # Save each report as markdown
            _save_report(content, name)

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

        output = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_time_seconds": round(total_time, 1),
            "period": period,
            "client": client_config,
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

        output_path = _save_output(output, f"gloria_{period['label']}")

        print(f"\n{'='*70}")
        print(f"  PRODUCTION PIPELINE COMPLETE — {total_time:.0f}s")
        print(f"  DQ Score: {dq_report.overall_score:.0f}/100")
        print(f"  Queries: {len(query_results['results'])}/{len(query_pack['queries'])}")
        print(f"  Revenue: €{baseline.get('total_revenue', 0):,.0f}")
        print(f"  Agents: {agents_ok}/3 | Findings: {total_findings}")
        print(f"  Reports: {len(reports)} ({', '.join(reports.keys())})")
        print(f"  Output: {output_path}")
        print(f"{'='*70}")

        # ── Assertions ──
        assert total_findings > 0, "Zero findings"
        assert len(reports) >= 3, f"Only {len(reports)} reports generated"

        # At least 2 reports must be real (not error/timeout)
        real_reports = {
            name: content for name, content in reports.items()
            if not content.startswith("# Error") and "timed out" not in content and len(content) > 200
        }
        assert len(real_reports) >= 2, (
            f"Only {len(real_reports)} real reports. "
            f"Statuses: {', '.join(f'{n}={len(c)} chars' for n, c in reports.items())}"
        )
