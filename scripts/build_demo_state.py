#!/usr/bin/env python3
"""
Deterministic synthetic pipeline-state fixture for the N3 GraphRAG eval
(VAL-192 N3). 100% synthetic — committable, runs in CI, no client data.

The numbers are ARITHMETICALLY CONSISTENT by construction (shares sum to 100%,
category/period revenues sum to the total, Pareto-80% needs exactly 9
customers) so scripts/build_global_references.py can compute exact reference
answers via pure joins. Values are string-serialized like real DB drivers do
(N1 Bug-1 realism).

Usage:
    python scripts/build_demo_state.py [--out evals/fixtures/state_demo.json]

Refs: VAL-192
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

TOTAL = 2_400_000.00

# (id, name, ltv, segment)  — sum(ltv) == TOTAL
CUSTOMERS = [
    ("C001", "FERRETERIA EL NORTE SA",      480_000.00, "Champions"),
    ("C002", "DISTRIBUIDORA ANDINA SRL",    360_000.00, "At Risk"),
    ("C003", "COMERCIAL DEL SUR SA",        280_000.00, "Champions"),
    ("C004", "ALMACENES UNIDOS SA",         220_000.00, "Champions"),
    ("C005", "PINTURERIA CENTRAL SRL",      180_000.00, "At Risk"),
    ("C006", "ELECTRO HOGAR SA",            150_000.00, "Loyal"),
    ("C007", "CONSTRUMART SRL",             130_000.00, "Loyal"),
    ("C008", "BAZAR INDUSTRIAL SA",         110_000.00, "Loyal"),
    ("C009", "VIVERO LAS LOMAS SRL",         95_000.00, "At Risk"),
    ("C010", "TALLERES DEL ESTE SA",         85_000.00, "Loyal"),
    ("C011", "KIOSCO MAYORISTA SRL",        190_000.00, "Hibernating"),
    ("C012", "REPUESTOS RAPIDOS SA",        120_000.00, "Hibernating"),
]

# (customer_id, deal_risk_score, days_since_purchase)
CHURN_RISK = [("C002", 85.0, 120), ("C005", 72.5, 95), ("C009", 64.0, 200), ("C011", 55.0, 110)]
DORMANT = [("C002", 120), ("C009", 200), ("C011", 110), ("C012", 130)]

# (segment, category, penetration_pct, category_revenue_eur)
# Champions deliberately do NOT buy JARDIN (the Q2 gap). Category revenues sum to TOTAL.
CROSS_SELL = [
    ("Champions",   "HERRAMIENTAS", 92.0, 620_000.00),
    ("Champions",   "PINTURA",      71.0, 250_000.00),
    ("Champions",   "ELECTRICIDAD", 55.0, 110_000.00),
    ("At Risk",     "HERRAMIENTAS", 64.0, 290_000.00),
    ("At Risk",     "PINTURA",      58.0, 200_000.00),
    ("At Risk",     "JARDIN",       41.0, 145_000.00),
    ("Loyal",       "HERRAMIENTAS", 49.0, 190_000.00),
    ("Loyal",       "PINTURA",      52.0, 150_000.00),
    ("Loyal",       "ELECTRICIDAD", 77.0, 340_000.00),
    ("Hibernating", "JARDIN",       38.0, 105_000.00),
]

PERIODS = [("2025-01-01 00:00:00", 850_000.00), ("2025-02-01 00:00:00", 750_000.00),
           ("2025-03-01 00:00:00", 800_000.00)]


def build() -> dict:
    rows_conc = [{
        "customer_id": cid, "customer_name": name,
        "ltv_eur": f"{ltv:.2f}", "share_pct": f"{ltv / TOTAL * 100:.2f}",
    } for cid, name, ltv, _ in sorted(CUSTOMERS, key=lambda c: -c[2])[:10]]

    ltv_by_id = {cid: ltv for cid, _, ltv, _ in CUSTOMERS}
    rows_churn = [{
        "customer_id": cid, "deal_risk_score": f"{score:.1f}",
        "days_since_purchase": days, "ltv_eur": f"{ltv_by_id[cid]:.2f}",
    } for cid, score, days in CHURN_RISK]

    rows_rfm = [{
        "customer_id": cid, "customer_name": name, "segment": seg,
        "monetary_eur": f"{ltv:.2f}",
    } for cid, name, ltv, seg in CUSTOMERS]

    rows_dormant = [{"customer_id": cid, "days_since_purchase": days} for cid, days in DORMANT]

    rows_xsell = [{
        "segment": seg, "category": cat,
        "penetration_pct": f"{pen:.2f}", "category_revenue_eur": f"{rev:.2f}",
    } for seg, cat, pen, rev in CROSS_SELL]

    query_results = {"results": {
        "total_revenue_summary": {"rows": [{
            "total_revenue": f"{TOTAL:.2f}", "num_invoices": 4800,
            "avg_invoice": "500.00", "min_invoice": "-850.00",
            "max_invoice": "98000.00", "distinct_customers": 12,
            "date_from": "2025-01-02 00:00:00", "date_to": "2025-03-31 00:00:00",
        }]},
        "revenue_by_period": {"rows": [
            {"period": p, "revenue": f"{r:.2f}"} for p, r in PERIODS]},
        "concentration_top_customers": {"rows": rows_conc},
        "churn_risk_scoring": {"rows": rows_churn},
        "rfm_segmentation": {"rows": rows_rfm},
        "dormant_customers": {"rows": rows_dormant},
        "cross_sell_matrix": {"rows": rows_xsell},
        "customer_retention": {"rows": [{
            "retained_customers": 8, "churned_customers": 4, "retention_rate": "66.70"}]},
        "data_freshness": {"rows": [{"days_since_latest": "45 days, 0:00:00"}]},
    }, "errors": {}}

    findings = {
        "analyst": {"findings": [
            {"id": "FIN-001", "severity": "high",
             "desc": "Concentración: FERRETERIA EL NORTE SA representa el 20.00% "
                     "de la facturación (€480,000.00) — riesgo de dependencia."},
            {"id": "FIN-002", "severity": "medium",
             "desc": "Caída de revenue en febrero: €750,000.00 vs €850,000.00 de "
                     "enero (-11.8% MoM)."},
        ]},
        "sentinel": {"findings": [
            {"id": "DQ-001", "severity": "medium",
             "desc": "Posibles facturas duplicadas en categoría PINTURA, incluye "
                     "operaciones de FERRETERIA EL NORTE SA — auditar."},
        ]},
        "hunter": {"findings": [
            {"id": "HUN-001", "severity": "high",
             "desc": "DISTRIBUIDORA ANDINA SRL: deal_risk_score 85.0, 120 días "
                     "sin comprar, €360,000.00 de LTV en riesgo de churn."},
            {"id": "HUN-002", "severity": "medium",
             "desc": "Dormancia: VIVERO LAS LOMAS SRL (200 días) y KIOSCO "
                     "MAYORISTA SRL (110 días) sin actividad."},
        ]},
        "_reconciliation": {"notes": "Sin contradicciones entre agentes."},
    }

    baseline = {
        "data_available": True, "total_revenue": TOTAL, "num_invoices": 4800,
        "avg_invoice": 500.0, "min_invoice": -850.0, "max_invoice": 98000.0,
        "distinct_customers": 12, "data_freshness_days": 45,
        "date_from": "2025-01-02", "date_to": "2025-03-31",
    }

    entity_map = {
        "entities": {
            "c_invoice": {"type": "transactional", "row_count": 4800},
            "c_bpartner": {"type": "master", "row_count": 12},
            "m_product": {"type": "master", "row_count": 240},
            "m_product_category": {"type": "master", "row_count": 4},
        },
        "relationships": [
            {"from": "c_invoice", "to": "c_bpartner", "type": "fk"},
            {"from": "m_product", "to": "m_product_category", "type": "fk"},
        ],
    }

    return {
        "entity_map": entity_map,
        "query_results": query_results,
        "baseline": baseline,
        "findings": findings,
        "memory": None,
        "client_config": {"name": "demo", "display_name": "Demo Ferretera (sintética)",
                          "sector": "distribucion", "currency": "EUR", "language": "es",
                          "erp": "demo"},
        "narrator_timeout": 300,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evals/fixtures/state_demo.json")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
