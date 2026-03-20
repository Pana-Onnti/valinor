#!/usr/bin/env python3
"""
Seed a demo ClientProfile with synthetic historical data.
Usage: python scripts/seed_demo_profile.py [client_name]

Creates a profile with:
- 5 historical runs
- Known findings (some persistent, some resolved)
- KPI history (5 data points per KPI)
- Refinement suggestions
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

from shared.memory.client_profile import ClientProfile, ClientRefinement
from shared.memory.profile_store import get_profile_store


DEMO_FINDINGS = [
    {
        "id": "CRIT-1",
        "title": "Facturas sin cobrar > 90 días",
        "severity": "CRITICAL",
        "agent": "sentinel",
        "runs_open": 5,
        "auto_escalated": False,
    },
    {
        "id": "HIGH-2",
        "title": "Pagos duplicados detectados",
        "severity": "HIGH",
        "agent": "hunter",
        "runs_open": 3,
    },
    {
        "id": "MED-3",
        "title": "Clientes sin actividad >6 meses",
        "severity": "MEDIUM",
        "agent": "analyst",
        "runs_open": 2,
    },
    {
        "id": "LOW-4",
        "title": "Productos sin stock mínimo configurado",
        "severity": "LOW",
        "agent": "analyst",
        "runs_open": 1,
    },
]

DEMO_RESOLVED = [
    {
        "id": "SENT-1",
        "title": "Proveedor con deuda vencida >180 días",
        "severity": "HIGH",
        "agent": "sentinel",
        "first_seen": (datetime.utcnow() - timedelta(days=90)).isoformat(),
        "last_seen": (datetime.utcnow() - timedelta(days=30)).isoformat(),
        "resolved_at": (datetime.utcnow() - timedelta(days=15)).isoformat(),
        "runs_open": 2,
    },
    {
        "id": "LOW-5",
        "title": "Facturas sin número correlativo",
        "severity": "LOW",
        "agent": "analyst",
        "first_seen": (datetime.utcnow() - timedelta(days=60)).isoformat(),
        "last_seen": (datetime.utcnow() - timedelta(days=20)).isoformat(),
        "resolved_at": (datetime.utcnow() - timedelta(days=10)).isoformat(),
        "runs_open": 1,
    },
]

DEMO_KPI_LABELS = [
    "Facturación Total",
    "Cobranza Pendiente",
    "Clientes Activos",
    "Margen Bruto",
]

DEMO_VALUES = [
    ["$8.2M", "$9.1M", "$10.3M", "$9.8M", "$11.2M"],
    ["$1.2M", "$1.5M", "$1.3M", "$1.8M", "$1.6M"],
    ["142", "138", "145", "151", "149"],
    ["38%", "37%", "39%", "41%", "40%"],
]

DEMO_NUMERIC = [
    [8.2, 9.1, 10.3, 9.8, 11.2],
    [1.2, 1.5, 1.3, 1.8, 1.6],
    [142, 138, 145, 151, 149],
    [38, 37, 39, 41, 40],
]

DEMO_PERIODS = ["Q3-2024", "Q4-2024", "Q1-2025", "Q2-2025", "Q3-2025"]


async def seed_profile(client_name: str):
    now = datetime.utcnow()

    profile = ClientProfile.new(client_name)
    profile.run_count = 5
    profile.last_run_date = now.isoformat()
    profile.industry_inferred = "distribución mayorista"
    profile.currency_detected = "ARS"
    profile.focus_tables = ["c_invoice", "c_payment", "c_bpartner", "m_product", "c_order"]
    profile.table_weights = {
        "c_invoice": 0.95,
        "c_payment": 0.85,
        "c_bpartner": 0.70,
        "m_product": 0.50,
        "c_order": 0.60,
    }

    # Add findings with timestamps
    for i, f in enumerate(DEMO_FINDINGS):
        days_ago = (5 - f["runs_open"]) * 30
        profile.known_findings[f["id"]] = {
            **f,
            "first_seen": (now - timedelta(days=days_ago + 30)).isoformat(),
            "last_seen": now.isoformat(),
        }

    for f in DEMO_RESOLVED:
        profile.resolved_findings[f["id"]] = f

    # Add KPI history
    for label_i, label in enumerate(DEMO_KPI_LABELS):
        profile.baseline_history[label] = []
        for period_i, period in enumerate(DEMO_PERIODS):
            profile.baseline_history[label].append({
                "period": period,
                "label": label,
                "value": DEMO_VALUES[label_i][period_i],
                "numeric_value": DEMO_NUMERIC[label_i][period_i],
                "run_date": (now - timedelta(days=(4 - period_i) * 45)).isoformat(),
            })

    # Add run history
    for i, period in enumerate(DEMO_PERIODS):
        profile.run_history.append({
            "run_date": (now - timedelta(days=(4 - i) * 45)).isoformat(),
            "period": period,
            "success": True,
            "findings_count": 4 + i,
            "new": 1 if i > 0 else 4,
            "resolved": 1 if i == 2 else 0,
        })

    # Refinement
    profile.refinement = {
        "table_weights": profile.table_weights,
        "query_hints": [
            "filtrar DocStatus='CO' para facturas confirmadas",
            "usar iscustomer='Y' AND isactive='Y' para clientes",
            "JOIN c_bpartner ON c_invoice.c_bpartner_id = c_bpartner.c_bpartner_id",
        ],
        "focus_areas": ["cobranza vencida", "pagos duplicados", "clientes inactivos"],
        "suppress_ids": ["SENT-1", "LOW-5"],
        "context_block": f"{client_name} es una empresa de distribución mayorista en Argentina. Moneda funcional: ARS. Hallazgo crítico persistente: facturas sin cobrar >90 días (5 runs consecutivos).",
        "generated_at": now.isoformat(),
    }

    # Entity map cache
    profile.entity_map_cache = {
        "entities": {
            "invoices": {"table": "c_invoice", "confidence": 0.95, "base_filter": "AND docstatus='CO'"},
            "customers": {"table": "c_bpartner", "confidence": 0.92, "base_filter": "AND iscustomer='Y'"},
            "payments": {"table": "c_payment", "confidence": 0.88, "base_filter": ""},
            "products": {"table": "m_product", "confidence": 0.85, "base_filter": "AND isactive='Y'"},
            "orders": {"table": "c_order", "confidence": 0.80, "base_filter": "AND docstatus='CO'"},
        },
        "relationships": [
            {"from": "invoices", "to": "customers", "via": "c_bpartner_id"},
        ],
    }
    profile.entity_map_updated_at = now.isoformat()

    store = get_profile_store()
    await store.save(profile)
    print(f"Demo profile created for '{client_name}'")
    print(f"   Runs: {profile.run_count}")
    print(f"   Active findings: {len(profile.known_findings)}")
    print(f"   Resolved: {len(profile.resolved_findings)}")
    print(f"   KPI history: {len(profile.baseline_history)} metrics x {len(DEMO_PERIODS)} periods")
    print(f"   Profile saved to: /tmp/valinor_profiles/{client_name}.json")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Gloria_SA"
    asyncio.run(seed_profile(name))
