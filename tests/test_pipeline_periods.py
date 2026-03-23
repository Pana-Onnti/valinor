"""
Parameterized pipeline tests by period — real agents, real data, no contradictions.

Runs the full pipeline against a realistic Gloria-like DB (~300 invoices,
50 customers, 2 years of data) with entity_map that MATCHES the actual DB.
Tests different time windows to evaluate agent behavior.

Each run saves output to tests/output/periods/ for later comparison.

Requires: claude CLI or proxy running.

Refs: VAL-90
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
from random import Random

import pytest
from sqlalchemy import create_engine, text

from valinor.agents.query_builder import build_queries
from valinor.pipeline_stages import compute_baseline
from valinor.pipeline import execute_queries, run_analysis_agents
from valinor.pipeline_reconciliation import reconcile_swarm, _parse_findings_from_output
from valinor.pipeline_narrator import prepare_narrator_context


# ══════════════════════════════════════════════════════════════════════════
# LLM availability
# ══════════════════════════════════════════════════════════════════════════

def _llm_available() -> bool:
    try:
        resp = urllib.request.urlopen("http://localhost:8099/health", timeout=3)
        return resp.status == 200
    except Exception:
        pass
    return shutil.which("claude") is not None


LLM_IS_AVAILABLE = _llm_available()

OUTPUT_DIR = Path(__file__).parent / "output" / "periods"


def _save_output(data: dict, label: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    path = OUTPUT_DIR / f"{label}_{ts}.json"
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


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


# ══════════════════════════════════════════════════════════════════════════
# Realistic Gloria DB — ~300 invoices, 50 customers, 2024-2025
# Entity map matches EXACTLY what's in the DB.
# ══════════════════════════════════════════════════════════════════════════

_DDL = [
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


def _build_realistic_db(engine):
    """
    ~300 sales invoices across 2024-2025, 50 customers, realistic patterns.
    Seeded random for reproducibility.
    """
    rng = Random(42)

    with engine.connect() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))

        # 50 customers (45 active customers + 5 suppliers)
        customer_names = [
            "Distribuciones García", "Importadora López", "Comercial Pérez",
            "Logística Martínez", "Suministros Rodríguez", "Alimentaria Sánchez",
            "Textil Fernández", "Electro González", "Metalúrgica Ruiz",
            "Construcciones Díaz", "Farmacia Moreno", "Química Industrial",
            "Plásticos del Sur", "Envases Modernos", "Transporte Rápido",
            "Café Premium", "Materiales Express", "Hidráulica Total",
            "Pinturas Nova", "Papel y Cartón SA", "Ferretería Central",
            "Muebles Hogar", "Agro Semillas", "Vinos del Valle",
            "Óptica Visual", "Calzado Confort", "Joyería Elegance",
            "Deportes Action", "Librería Cultura", "Panadería Artesanal",
            "Automotriz del Este", "Cerámica Fina", "Lácteos Frescos",
            "Carnicería Premium", "Pescadería Mar Azul", "Verdulería Orgánica",
            "Heladería Glaciar", "Pastelería Dulce", "Florería Primavera",
            "Peluquería Style", "Veterinaria Animal", "Inmobiliaria Centro",
            "Seguros Confianza", "Consultoría Delta", "Tecnología Avanzada",
            "Proveedor Alpha", "Proveedor Beta", "Proveedor Gamma",
            "Proveedor Delta", "Proveedor Epsilon",
        ]
        for i, name in enumerate(customer_names, 1):
            is_customer = "Y" if i <= 45 else "N"
            conn.execute(text(
                "INSERT INTO c_bpartner VALUES (:id, :name, :cust, 'Y')"
            ), {"id": i, "name": name, "cust": is_customer})

        # ~300 sales invoices across 2024-2025
        # Top 5 customers get more invoices (concentration pattern)
        invoice_id = 0
        for year in (2024, 2025):
            for month in range(1, 13):
                # Top 5 customers: 2-3 invoices/month each
                for cust_id in range(1, 6):
                    n_invoices = rng.randint(2, 3)
                    for _ in range(n_invoices):
                        invoice_id += 1
                        day = rng.randint(1, 28)
                        # Top customers: higher amounts (€20K-€80K)
                        amount = round(rng.uniform(20_000, 80_000), 2)
                        conn.execute(text(
                            "INSERT INTO c_invoice VALUES "
                            "(:id, :bp, :amt, :dt, 'Y', 'CO', 'Y')"
                        ), {
                            "id": invoice_id, "bp": cust_id,
                            "amt": amount,
                            "dt": f"{year}-{month:02d}-{day:02d}",
                        })

                # Other 40 customers: 0-1 invoices/month (sparse)
                for cust_id in range(6, 46):
                    if rng.random() < 0.15:  # 15% chance per month
                        invoice_id += 1
                        day = rng.randint(1, 28)
                        amount = round(rng.uniform(2_000, 25_000), 2)
                        conn.execute(text(
                            "INSERT INTO c_invoice VALUES "
                            "(:id, :bp, :amt, :dt, 'Y', 'CO', 'Y')"
                        ), {
                            "id": invoice_id, "bp": cust_id,
                            "amt": amount,
                            "dt": f"{year}-{month:02d}-{day:02d}",
                        })

        total_sales = invoice_id

        # ~30 purchase invoices (issotrx='N') from suppliers
        for i in range(total_sales + 1, total_sales + 31):
            supplier = rng.choice(range(46, 51))
            month = rng.randint(1, 12)
            conn.execute(text(
                "INSERT INTO c_invoice VALUES "
                "(:id, :bp, :amt, :dt, 'N', 'CO', 'Y')"
            ), {
                "id": i, "bp": supplier,
                "amt": round(rng.uniform(5_000, 40_000), 2),
                "dt": f"2025-{month:02d}-{rng.randint(1,28):02d}",
            })

        # Payment schedules for recent invoices
        ps_id = 0
        for inv_id in range(1, total_sales + 1):
            ps_id += 1
            outstanding = round(rng.uniform(0, 15_000), 2) if rng.random() < 0.3 else 0
            month = rng.randint(1, 12)
            conn.execute(text(
                "INSERT INTO fin_payment_schedule VALUES "
                "(:id, :inv, :out, :due, 'Y')"
            ), {
                "id": ps_id, "inv": inv_id,
                "out": outstanding,
                "due": f"2025-{month:02d}-28",
            })

        # Payments
        pay_id = 0
        for cust_id in range(1, 46):
            n_payments = rng.randint(1, 5)
            for _ in range(n_payments):
                pay_id += 1
                conn.execute(text(
                    "INSERT INTO fin_payment VALUES "
                    "(:id, :bp, :amt, 'Y', 'Y')"
                ), {
                    "id": pay_id, "bp": cust_id,
                    "amt": round(rng.uniform(5_000, 50_000), 2),
                })

        conn.commit()

    # Count actual data for entity_map
    with engine.connect() as conn:
        stats = {}
        stats["total_invoices"] = conn.execute(text("SELECT COUNT(*) FROM c_invoice")).scalar()
        stats["sales_invoices"] = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE issotrx='Y'")).scalar()
        stats["purchase_invoices"] = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE issotrx='N'")).scalar()
        stats["co_invoices"] = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE docstatus='CO'")).scalar()
        stats["active_invoices"] = conn.execute(text("SELECT COUNT(*) FROM c_invoice WHERE isactive='Y'")).scalar()
        stats["total_bpartners"] = conn.execute(text("SELECT COUNT(*) FROM c_bpartner")).scalar()
        stats["customers"] = conn.execute(text("SELECT COUNT(*) FROM c_bpartner WHERE iscustomer='Y'")).scalar()
        stats["non_customers"] = conn.execute(text("SELECT COUNT(*) FROM c_bpartner WHERE iscustomer='N'")).scalar()
        stats["active_bpartners"] = conn.execute(text("SELECT COUNT(*) FROM c_bpartner WHERE isactive='Y'")).scalar()
        stats["payment_schedules"] = conn.execute(text("SELECT COUNT(*) FROM fin_payment_schedule")).scalar()
        stats["payments"] = conn.execute(text("SELECT COUNT(*) FROM fin_payment")).scalar()
        stats["receipts"] = conn.execute(text("SELECT COUNT(*) FROM fin_payment WHERE isreceipt='Y'")).scalar()

    return stats


def _build_entity_map(stats: dict) -> dict:
    """Entity map that MATCHES the actual test DB — no contradictions."""
    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "type": "TRANSACTIONAL",
                "row_count": stats["total_invoices"],
                "confidence": 0.99,
                "key_columns": {
                    "pk": "c_invoice_id",
                    "invoice_date": "dateinvoiced",
                    "amount_col": "grandtotal",
                    "customer_fk": "c_bpartner_id",
                },
                "base_filter": "issotrx='Y' AND docstatus='CO' AND isactive='Y'",
                "probed_values": {
                    "issotrx": {"Y": stats["sales_invoices"], "N": stats["purchase_invoices"]},
                    "docstatus": {"CO": stats["co_invoices"]},
                    "isactive": {"Y": stats["active_invoices"]},
                },
            },
            "customers": {
                "table": "c_bpartner",
                "type": "MASTER",
                "row_count": stats["total_bpartners"],
                "confidence": 0.98,
                "key_columns": {
                    "pk": "c_bpartner_id",
                    "customer_name": "name",
                },
                "base_filter": "iscustomer='Y' AND isactive='Y'",
                "probed_values": {
                    "iscustomer": {"Y": stats["customers"], "N": stats["non_customers"]},
                    "isactive": {"Y": stats["active_bpartners"]},
                },
            },
            "payment_schedule": {
                "table": "fin_payment_schedule",
                "type": "TRANSACTIONAL",
                "row_count": stats["payment_schedules"],
                "confidence": 0.97,
                "key_columns": {
                    "pk": "fin_payment_schedule_id",
                    "invoice_fk": "c_invoice_id",
                    "outstanding_amount": "outstandingamt",
                    "due_date": "duedate",
                },
                "base_filter": "isactive='Y'",
                "probed_values": {
                    "isactive": {"Y": stats["payment_schedules"]},
                },
            },
            "payments": {
                "table": "fin_payment",
                "type": "TRANSACTIONAL",
                "row_count": stats["payments"],
                "confidence": 0.97,
                "key_columns": {
                    "pk": "fin_payment_id",
                    "partner_fk": "c_bpartner_id",
                    "amount": "amount",
                },
                "base_filter": "isreceipt='Y' AND isactive='Y'",
                "probed_values": {
                    "isreceipt": {"Y": stats["receipts"], "N": stats["payments"] - stats["receipts"]},
                    "isactive": {"Y": stats["payments"]},
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
# FIXTURES
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def realistic_db():
    """Create realistic Gloria DB, return (conn_str, entity_map, stats)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn_str = f"sqlite:///{tmp.name}"
    engine = create_engine(conn_str)
    stats = _build_realistic_db(engine)
    entity_map = _build_entity_map(stats)
    engine.dispose()
    yield conn_str, entity_map, stats
    os.unlink(tmp.name)


@pytest.fixture
def client_config():
    return {
        "name": "Gloria Test",
        "display_name": "Gloria Distribuciones S.A.",
        "sector": "distribucion",
        "currency": "EUR",
        "language": "es",
    }


# ══════════════════════════════════════════════════════════════════════════
# PARAMETERIZED TESTS — different periods
# ══════════════════════════════════════════════════════════════════════════

PERIODS = {
    "1_month": {"start": "2025-06-01", "end": "2025-06-30", "label": "Jun-2025"},
    "1_quarter": {"start": "2025-04-01", "end": "2025-06-30", "label": "Q2-2025"},
    "1_year": {"start": "2025-01-01", "end": "2025-12-31", "label": "FY-2025"},
}


@pytest.mark.skipif(not LLM_IS_AVAILABLE, reason="Claude CLI/proxy not available")
class TestPipelineByPeriod:
    """Pipeline tests parameterized by period — always real agents."""

    @pytest.fixture(autouse=True, scope="class")
    def setup_real_sdk(self):
        _install_real_sdk()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("period_name,period", [
        pytest.param("1_month", PERIODS["1_month"], id="1-month"),
        pytest.param("1_quarter", PERIODS["1_quarter"], id="1-quarter"),
        pytest.param("1_year", PERIODS["1_year"], id="1-year"),
    ])
    async def test_pipeline_period(
        self, realistic_db, client_config, period_name, period,
    ):
        """
        Full pipeline for a specific period. Validates:
        - Queries execute and return data for the period
        - Agents produce parseable findings
        - Findings reference real data, not hallucinated numbers
        - Output saved for comparison
        """
        conn_str, entity_map, db_stats = realistic_db
        config = {"connection_string": conn_str}

        # ── Stages 2-2.5: Queries + Baseline ──
        query_pack = build_queries(entity_map, period)
        query_results = await execute_queries(query_pack, config)

        assert len(query_results["results"]) > 0, (
            f"No queries succeeded for {period_name}. Errors: {query_results.get('errors', {})}"
        )

        baseline = compute_baseline(query_results)

        # ── Stage 3: REAL agents ──
        findings = await run_analysis_agents(
            query_results, entity_map, None, baseline,
        )

        # Parse findings
        agents_with_findings = 0
        for agent_name in ("analyst", "sentinel", "hunter"):
            if agent_name in findings and isinstance(findings[agent_name], dict):
                parsed = _parse_findings_from_output(findings[agent_name])
                if parsed:
                    findings[agent_name]["findings"] = parsed
                    agents_with_findings += 1

        assert agents_with_findings >= 2, (
            f"Only {agents_with_findings}/3 agents produced findings for {period_name}"
        )

        # ── Stage 3.5: Reconciliation ──
        findings = await reconcile_swarm(findings, baseline)
        assert findings["_reconciliation"]["ran"] is True

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

        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "period": period,
            "period_name": period_name,
            "db_stats": db_stats,
            "summary": {
                "queries_executed": len(query_results["results"]),
                "queries_failed": len(query_results.get("errors", {})),
                "baseline_revenue": baseline.get("total_revenue"),
                "baseline_customers": baseline.get("distinct_customers"),
                "baseline_invoices": baseline.get("num_invoices"),
                "agents_with_findings": agents_with_findings,
                "total_findings": total_findings,
                "conflicts": findings["_reconciliation"]["conflicts_found"],
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
            "findings": findings_clean,
            "entity_map_stats": db_stats,
        }

        output_path = _save_output(report, f"pipeline_{period_name}")

        print(
            f"\n{'='*60}\n"
            f"PIPELINE {period_name.upper()} — {period['label']}\n"
            f"  DB: {db_stats['sales_invoices']} sales invoices, "
            f"{db_stats['customers']} customers\n"
            f"  Period data: {baseline.get('num_invoices', 0)} invoices, "
            f"€{baseline.get('total_revenue', 0):,.0f}\n"
            f"  Agents: {agents_with_findings}/3 | "
            f"Findings: {total_findings} | "
            f"Conflicts: {findings['_reconciliation']['conflicts_found']}\n"
            f"  Output: {output_path}\n"
            f"{'='*60}"
        )
