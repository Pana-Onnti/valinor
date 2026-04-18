#!/usr/bin/env python3
"""
Generate a SalesReportV2 JSON from real Gloria data.

Runs the 5 sales_v2 queries against the Gloria Postgres and assembles the
complete SalesReportV2 payload *deterministically* from SQL — no LLM. The
human-readable fields (recommended_action, script_hint, etc.) are picked
from a small template table indexed by segment / deal-risk bucket.

Output: web/public/demo/sales-v2-gloria.json

The frontend `/demo/sales-v2-gloria` route fetches this static JSON and
renders SalesReportV2.tsx — so the demo shows 100% real numbers from the
Gloria database without requiring the full LLM pipeline.

Refs: VAL-141
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make core/ importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from sqlalchemy import create_engine, text

from valinor.queries.sales_v2 import build_sales_v2_queries, hhi_level


GLORIA_CONN = "postgresql://tad:tad@localhost:5432/gloria"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "web" / "public" / "demo" / "sales-v2-gloria.json"

ENTITY_MAP = {
    "entities": {
        "invoices": {
            "table": "c_invoice",
            "key_columns": {
                "invoice_id": "c_invoice_id",
                "invoice_date": "dateacct",
                "customer_id": "c_bpartner_id",
                "total_amount": "grandtotal",
            },
            "base_filter": "AND issotrx = 'Y'",
        },
        "customers": {
            "table": "c_bpartner",
            "key_columns": {"customer_id": "c_bpartner_id", "customer_name": "name"},
        },
        "invoice_lines": {
            "table": "c_invoiceline",
            "key_columns": {
                "invoice_id": "c_invoice_id",
                "product_id": "m_product_id",
                "line_amount": "linenetamt",
            },
        },
        "products": {
            "table": "m_product",
            "key_columns": {
                "product_id": "m_product_id",
                "category": "m_product_category_id",
            },
        },
    },
}


# ─────────────────────────────────────────────────────────────────────
# Template actions per segment — non-LLM, curated copy
# ─────────────────────────────────────────────────────────────────────

SEGMENT_ACTIONS = {
    "champions": "Programa VIP. Contacto del gerente comercial directo. Renovación anticipada.",
    "loyal": "Bundle + cross-sell. Descuentos por volumen para consolidar la fidelidad.",
    "potential_loyalists": "Onboarding comercial. Catálogo expandido. Segundo pedido es clave.",
    "new_customers": "Seguimiento a 30 días. Validar calidad de servicio en primer envío.",
    "promising": "Email personalizado + oferta de primer volumen. Educación de producto.",
    "need_attention": "Call comercial. Verificar por qué bajó la frecuencia vs. histórico.",
    "about_to_sleep": "Reactivación con incentivo de reorder. Última ventana antes de churn.",
    "at_risk": "Prioridad alta. Llamada del gerente, no del vendedor. Ajuste de condiciones.",
    "cannot_lose": "Escalamiento C-level. Retención a cualquier costo — LTV insustituible.",
    "hibernating": "Campaña email automática. Bajo costo de intento, alto volumen.",
    "lost": "Archivar. Evaluar patrones de churn de 12 meses para prevención futura.",
}


def _build_call_script(row: dict) -> tuple[str, str]:
    """Return (reason, script_hint) for a dormant customer."""
    recency = row["recency_days"]
    ltv = float(row["ltv_eur"])
    freq = row["frequency"]

    if recency > 180:
        reason = f"{recency} días sin compras. LTV €{ltv:,.0f} en {freq} pedidos históricos."
        script = "Es posible que haya cambiado el contacto de compras. Verificar y proponer reorder base."
    elif recency > 90:
        reason = f"{recency} días fuera de ciclo. Frecuencia histórica: {freq} pedidos."
        script = "¿Algún problema con la última entrega? Ofrecer bajar el mínimo por única vez."
    else:
        reason = f"{recency} días sin pedido — primera vez fuera del ciclo habitual."
        script = "Llamada breve para confirmar que todo está bien. Catálogo de novedades."
    return reason, script


def _risk_from_days(days: int) -> str:
    if days > 90:
        return "high"
    if days > 45:
        return "medium"
    return "low"


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────


def main() -> None:
    engine = create_engine(GLORIA_CONN)
    queries = build_sales_v2_queries(ENTITY_MAP, months=12)

    results: dict[str, list[dict]] = {}
    with engine.connect() as conn:
        for qid, sql in queries.items():
            result = conn.execute(text(sql))
            cols = list(result.keys())
            results[qid] = [
                {
                    c: (float(v) if hasattr(v, "is_integer") or str(type(v)) == "<class 'decimal.Decimal'>" else
                        v.isoformat() if hasattr(v, "isoformat") else v)
                    for c, v in zip(cols, row)
                }
                for row in result
            ]
            print(f"  {qid}: {len(results[qid])} rows")

    # ── HHI / concentration ────────────────────────────────────────
    hhi_row = results["concentration_hhi"][0]
    hhi = float(hhi_row["hhi"])
    level = hhi_level(hhi)
    cr1 = float(hhi_row["cr1_pct"])
    cr5 = float(hhi_row["cr5_pct"])
    cr10 = float(hhi_row["cr10_pct"])
    total_customers = int(hhi_row["total_customers"])
    total_revenue = float(hhi_row["total_revenue"])

    interp = {
        "diversified":
            f"Cartera muy diversificada ({total_customers} clientes activos). "
            f"El top 5 es el {cr5:.1f}% — riesgo de concentración bajo.",
        "moderate":
            f"Cartera moderadamente concentrada. El top 5 acumula {cr5:.1f}% del revenue.",
        "high_risk":
            f"Alta concentración: si el top 5 ({cr5:.1f}% del revenue) se va, el impacto es severo.",
    }[level]

    # ── RFM segments ───────────────────────────────────────────────
    from collections import defaultdict
    seg_agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "revenue": 0.0, "ltv_sum": 0.0})
    total_rfm_revenue = 0.0
    for row in results["rfm_segmentation"]:
        seg = row["segment"]
        rev = float(row["monetary_eur"])
        seg_agg[seg]["count"] += 1
        seg_agg[seg]["revenue"] += rev
        seg_agg[seg]["ltv_sum"] += rev
        total_rfm_revenue += rev

    rfm_segments = []
    rfm_denom = total_rfm_revenue or 1.0
    for seg, agg in seg_agg.items():
        cnt = agg["count"]
        # Use RFM's own total as denominator (HHI query filters differently)
        share = min(100.0, round(100 * agg["revenue"] / rfm_denom, 2))
        rfm_segments.append({
            "segment": seg,
            "count": cnt,
            "revenue_share_pct": share,
            "avg_ltv": round(agg["ltv_sum"] / cnt, 2) if cnt else 0,
            "recommended_action": SEGMENT_ACTIONS.get(seg, ""),
            "confidence": "measured",
        })
    rfm_segments.sort(key=lambda s: s["revenue_share_pct"], reverse=True)

    # ── Top customers ──────────────────────────────────────────────
    top_customers = []
    for r in results["concentration_top_customers"]:
        top_customers.append({
            "customer_name": r["customer_name"] or "(sin nombre)",
            "customer_id": r["customer_id"],
            "ltv_eur": float(r["ltv_eur"]),
            "share_pct": float(r["share_pct"]),
            "last_purchase": r["last_purchase"],
            "risk": r["risk"],
            "confidence": "measured",
        })

    # ── Magic Matrix ───────────────────────────────────────────────
    # Keep only the 15 biggest segments × top categories for readability
    matrix_rows = results["cross_sell_matrix"]
    # For display we need category names — m_product_category_id is a UUID in Openbravo,
    # so we keep the id. If names are needed, join `m_product_category`.
    # Limit to top 6 categories by total presence, + top 6 segments by size.
    from collections import Counter
    cat_counter = Counter()
    seg_counter = Counter()
    for r in matrix_rows:
        cat_counter[r["category"]] += int(r["customers_buying"])
        seg_counter[r["segment"]] += int(r["customers_buying"])
    top_cats = {c for c, _ in cat_counter.most_common(6)}
    top_segs = {s for s, _ in seg_counter.most_common(6)}

    magic_matrix = []
    valid_segments = set(SEGMENT_ACTIONS.keys())
    for r in matrix_rows:
        # Filter out 'other' bucket from cross_sell_matrix CTE (schema only
        # accepts the 11 canonical RFM segments)
        if r["segment"] not in valid_segments:
            continue
        if r["category"] not in top_cats or r["segment"] not in top_segs:
            continue
        pen = float(r["penetration_pct"])
        # Gap opportunity: naive estimate = (100 - penetration) * avg_order_eur * segment_size / 10
        magic_matrix.append({
            "segment": r["segment"],
            "category": str(r["category"])[:8],  # Truncate UUID for display
            "penetration_pct": pen,
            "gap_opportunity_eur": round((100 - pen) * 100, 2),  # placeholder estimate
            "confidence": "estimated",
        })

    # ── Call list ──────────────────────────────────────────────────
    call_list = []
    for i, r in enumerate(results["churn_risk_scoring"][:12], start=1):
        reason, script = _build_call_script(r)
        avg_order = float(r["ltv_eur"]) / max(int(r["frequency"]), 1)
        call_list.append({
            "rank": i,
            "customer_name": r["customer_name"] or "(sin nombre)",
            "customer_id": r["customer_id"][:10] if r["customer_id"] else None,
            "deal_risk_score": float(r["deal_risk_score"]),
            "last_purchase": r["last_purchase"],
            "ltv_eur": float(r["ltv_eur"]),
            "recovery_potential_eur": round(avg_order * 0.3, 2),
            "recovery_confidence": "estimated",
            "reason": reason,
            "script_hint": script,
        })

    # ── KPI bar ────────────────────────────────────────────────────
    dormants = sum(1 for r in results["rfm_segmentation"]
                   if r["segment"] in ("about_to_sleep", "at_risk", "hibernating", "lost"))
    opportunity_eur = sum(c["recovery_potential_eur"] for c in call_list)

    kpi_bar = [
        {"label": "Clientes activos", "value": f"{total_customers:,}".replace(",", "."),
         "confidence": "measured"},
        {"label": "Dormantes", "value": f"{dormants:,}".replace(",", "."),
         "sub": "> 60 días sin comprar", "confidence": "measured"},
        {"label": "HHI", "value": f"{hhi:.0f}",
         "sub": {"diversified": "diversificada",
                 "moderate": "moderada",
                 "high_risk": "alta"}[level],
         "confidence": "measured"},
        {"label": "CR5", "value": f"{cr5:.1f}%",
         "sub": "top 5 clientes", "confidence": "measured"},
        {"label": "Oportunidad", "value": f"€{opportunity_eur:,.0f}".replace(",", "."),
         "sub": "top 12 call list", "confidence": "estimated"},
    ]

    # ── Category performance — use cross_sell_matrix aggregated ────
    # Group cross_sell_matrix by category, sum customers_buying → proxy for category share
    # (Real category revenue would need a separate query; this is a demo approximation)
    cat_totals = Counter()
    for r in matrix_rows:
        cat_totals[r["category"]] += int(r["customers_buying"])
    cat_total_sum = sum(cat_totals.values()) or 1
    category_performance = []
    for cat, count in cat_totals.most_common(6):
        share = round(100 * count / cat_total_sum, 2)
        category_performance.append({
            "category": str(cat)[:8],
            "revenue_eur": round(count * 100, 2),  # proxy — not real €
            "share_pct": share,
            "mom_pct": 0.0,  # needs a second period to compute
            "trend": "estable",
            "confidence": "inferred",
        })

    # ── Assemble ───────────────────────────────────────────────────
    report = {
        "client_name": "Gloria",
        "period": "Últimos 12 meses",
        "currency": "EUR",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpi_bar": kpi_bar,
        "rfm_segments": rfm_segments,
        "concentration": {
            "hhi": round(hhi, 2),
            "hhi_level": level,
            "cr1_pct": cr1,
            "cr5_pct": cr5,
            "cr10_pct": cr10,
            "total_customers": total_customers,
            "interpretation": interp,
            "confidence": "measured",
        },
        "top_customers": top_customers,
        "category_performance": category_performance,
        "magic_matrix": magic_matrix,
        "call_list": call_list,
        "executive_summary": (
            f"Cartera de {total_customers:,} clientes activos en los últimos 12 meses, "
            f"HHI {hhi:.0f} "
            f"({ {'diversified': 'muy diversificada', 'moderate': 'moderada', 'high_risk': 'concentrada'}[level] }). "
            f"{len(call_list)} clientes identificados como prioridad de llamada, "
            f"€{opportunity_eur:,.0f} de oportunidad estimada en reactivación. "
            f"Segmento 'Champions' concentra "
            f"{sum(s['revenue_share_pct'] for s in rfm_segments if s['segment']=='champions'):.1f}% "
            f"del revenue."
        ),
        "data_caveats": [
            "Category names truncated to 8-char UUID prefixes (Openbravo m_product_category_id).",
            "Category revenue_eur es proxy por count × 100 — el dato € real requiere join con invoice_lines.",
            "MoM trends fijados en 0 — requieren ejecutar el mismo análisis sobre 2 períodos.",
            "Magic Matrix gap_opportunity_eur es estimado heurístico (100 - penetration_pct) × 100.",
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Written {OUTPUT_PATH}")
    print(f"   {total_customers:,} customers, HHI {hhi:.0f} ({level}), {len(call_list)} call-list entries")


if __name__ == "__main__":
    main()
