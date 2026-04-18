#!/usr/bin/env python3
"""
Generate a SalesReportV2 JSON from real Gloria data — demo-grade.

Applies loss framing (Kahneman), profile-aware scripts, real category names,
and decision-forcing next_actions. See VAL-141 refactor.

Output: web/public/demo/sales-v2-gloria.json

Refs: VAL-141
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from sqlalchemy import create_engine, text

from valinor.queries.sales_v2 import build_sales_v2_queries, hhi_level


GLORIA_CONN = "postgresql://tad:tad@localhost:5432/gloria"
OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "web" / "public" / "demo" / "sales-v2-gloria.json"
)

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
        "product_categories": {
            "table": "m_product_category",
            "key_columns": {
                "category_id": "m_product_category_id",
                "category_name": "name",
            },
        },
    },
}


# ─────────────────────────────────────────────────────────────────────
# Curated segment-level copy (keeps output deterministic and editable)
# ─────────────────────────────────────────────────────────────────────

SEGMENT_ACTIONS = {
    "champions":           "Programa VIP. Gerente comercial directo. Renovación anticipada.",
    "loyal":               "Bundle + cross-sell. Descuentos por volumen para consolidar.",
    "potential_loyalists": "Onboarding comercial. Catálogo expandido. Segundo pedido es clave.",
    "new_customers":       "Seguimiento a 30 días. Validar calidad de servicio en primer envío.",
    "promising":           "Email personalizado + oferta de primer volumen. Educar en producto.",
    "need_attention":      "Call comercial. Verificar por qué bajó la frecuencia vs. histórico.",
    "about_to_sleep":      "Reactivación con incentivo de reorder. Última ventana antes de churn.",
    "at_risk":             "Prioridad alta. Llamada del gerente, no del vendedor.",
    "cannot_lose":         "Escalamiento C-level. Retención a cualquier costo — LTV insustituible.",
    "hibernating":         "Campaña email automática. Bajo costo de intento, alto volumen.",
    "lost":                "Archivar. Evaluar patrones de churn de 12 meses para prevención.",
}


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


_UUID_RE = re.compile(r"\(\s*[0-9A-Fa-f]{16,}\s*\)\s*$")


def _clean_customer_name(name: str) -> str:
    """Strip trailing UUIDs from names (legacy Openbravo dump artifacts)."""
    if not name:
        return "(sin nombre)"
    cleaned = _UUID_RE.sub("", name).strip()
    return cleaned or name  # never return empty


def _build_script_for_profile(row: dict) -> tuple[str, str]:
    """
    Return (reason, script_hint) tuned to the customer's profile.
    3 variants per the user's feedback — no more one-size-fits-all.
    """
    recency = int(row["recency_days"])
    ltv = float(row["ltv_eur"])
    freq = int(row["frequency"])
    profile = row.get("profile", "cuenta_media")
    avg_order = float(row.get("avg_order_eur", ltv / max(freq, 1)))

    if profile == "cuenta_top":
        reason = (
            f"Cuenta TOP (LTV €{ltv:,.0f}, {freq} pedidos) — "
            f"{recency} días sin comprar. Cliente crítico, impacto directo en revenue."
        )
        script = (
            "Sos una cuenta estratégica para nosotros y notamos que hace un tiempo no "
            "coincidimos. Queremos entender qué pasó — producto, precio, lead time. "
            "Agendamos una reunión con el equipo directivo esta semana."
        )
    elif profile == "account_grande":
        reason = (
            f"Cuenta grande ({freq} pedidos históricos, LTV €{ltv:,.0f}), "
            f"{recency} días fuera de ciclo."
        )
        script = (
            "Notamos que hace meses no recibimos tu pedido habitual. "
            "¿Cambió algo del lado comercial o logístico? Armamos la orden base "
            f"de €{avg_order:,.0f} para que aprueben."
        )
    elif profile == "outlier":
        reason = (
            f"Outlier: solo {freq} pedido(s) histórico(s) de €{ltv:,.0f}. "
            "Muestra insuficiente — potencial real desconocido."
        )
        script = (
            "Hiciste un pedido importante y no volvimos a coincidir. "
            "Queremos entender tu caso: ¿qué hizo falta? "
            "Sin presionar la venta — primero entender."
        )
    else:  # cuenta_media
        reason = (
            f"Cadencia cayó: {freq} pedidos en histórico, "
            f"{recency} días desde el último (€{ltv:,.0f} LTV)."
        )
        script = (
            f"Tu pedido medio era €{avg_order:,.0f} y venías comprando regularmente. "
            "¿Hay algo que podamos ajustar — producto, precio, logística?"
        )
    return reason, script


def _to_jsonable(row, cols):
    from decimal import Decimal
    out = {}
    for c, v in zip(cols, row):
        if isinstance(v, Decimal):
            out[c] = float(v)
        elif hasattr(v, "isoformat"):
            out[c] = v.isoformat()
        else:
            out[c] = v
    return out


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────


def main() -> None:
    engine = create_engine(GLORIA_CONN)
    queries = build_sales_v2_queries(ENTITY_MAP, months=12)

    results: dict[str, list[dict]] = {}
    with engine.connect() as conn:
        for qid, sql in queries.items():
            rs = conn.execute(text(sql))
            cols = list(rs.keys())
            results[qid] = [_to_jsonable(row, cols) for row in rs]
            print(f"  {qid}: {len(results[qid])} rows")

    # ── HHI / concentration ─────────────────────────────────────────
    hhi_row = results["concentration_hhi"][0]
    hhi = float(hhi_row["hhi"])
    level = hhi_level(hhi)
    cr1, cr5, cr10 = float(hhi_row["cr1_pct"]), float(hhi_row["cr5_pct"]), float(hhi_row["cr10_pct"])
    total_customers = int(hhi_row["total_customers"])
    total_revenue = float(hhi_row["total_revenue"])

    # ── RFM aggregates (also needed for interpretation) ─────────────
    seg_agg: dict[str, dict] = defaultdict(lambda: {"count": 0, "revenue": 0.0})
    total_rfm_revenue = 0.0
    for row in results["rfm_segmentation"]:
        seg = row["segment"]
        rev = float(row["monetary_eur"])
        seg_agg[seg]["count"] += 1
        seg_agg[seg]["revenue"] += rev
        total_rfm_revenue += rev

    champions_count = seg_agg.get("champions", {}).get("count", 0)
    champions_share = (
        100 * seg_agg.get("champions", {}).get("revenue", 0) / (total_rfm_revenue or 1)
    )

    # Reconciled interpretation (fixes the HHI vs Champions 71% contradiction)
    interp = (
        f"Por cliente individual la cartera es {{'diversified': 'muy diversificada', "
        f"'moderate': 'moderada', 'high_risk': 'concentrada'}}[level] "
        f"(HHI {hhi:.0f}, CR5 {cr5:.1f}%). Pero por comportamiento, {champions_count} "
        f"clientes 'Champions' ({100*champions_count/max(total_customers,1):.0f}% de la base) "
        f"generan el {champions_share:.0f}% del revenue: si la cola de Champions cae, "
        f"perdés un tercio de la facturación."
    ).replace("{'diversified': 'muy diversificada', 'moderate': 'moderada', 'high_risk': 'concentrada'}[level]",
              {"diversified": "muy diversificada",
               "moderate": "moderada", "high_risk": "concentrada"}[level])

    rfm_segments = []
    for seg, agg in seg_agg.items():
        cnt = agg["count"]
        share = min(100.0, round(100 * agg["revenue"] / (total_rfm_revenue or 1), 2))
        rfm_segments.append({
            "segment": seg,
            "count": cnt,
            "revenue_share_pct": share,
            "avg_ltv": round(agg["revenue"] / cnt, 2) if cnt else 0,
            "recommended_action": SEGMENT_ACTIONS.get(seg, ""),
            "confidence": "measured",
        })
    rfm_segments.sort(key=lambda s: s["revenue_share_pct"], reverse=True)

    # ── Top customers (clean names, no UUIDs) ───────────────────────
    top_customers = []
    for r in results["concentration_top_customers"]:
        top_customers.append({
            "customer_name": _clean_customer_name(r["customer_name"]),
            "customer_id": (r["customer_id"][:8] if r["customer_id"] else None),
            "ltv_eur": float(r["ltv_eur"]),
            "share_pct": float(r["share_pct"]),
            "last_purchase": r["last_purchase"],
            "risk": r["risk"],
            "confidence": "measured",
        })

    # ── Magic Matrix (real category names!) ─────────────────────────
    matrix_rows = results["cross_sell_matrix"]
    cat_totals = Counter()
    seg_counter = Counter()
    for r in matrix_rows:
        cat_totals[r["category"]] += float(r.get("category_revenue_eur", 0) or 0)
        seg_counter[r["segment"]] += int(r["customers_buying"])
    top_cats = {c for c, _ in cat_totals.most_common(6)}
    top_segs = {s for s, _ in seg_counter.most_common(6)}
    valid_segments = set(SEGMENT_ACTIONS.keys())

    magic_matrix = []
    for r in matrix_rows:
        if r["segment"] not in valid_segments or r["segment"] not in top_segs:
            continue
        if r["category"] not in top_cats:
            continue
        pen = float(r["penetration_pct"])
        # Real gap opportunity: (100-pen)/100 × segment_size × category_avg_revenue_per_customer
        # where avg_per_customer = total_category_revenue / buyers_of_that_category
        cat_total = cat_totals[r["category"]] or 0
        # Use the segment size from this row (customers_buying / penetration)
        seg_size = int(r["segment_size"])
        buyers_total = sum(int(x["customers_buying"]) for x in matrix_rows if x["category"] == r["category"])
        avg_per_buyer = cat_total / max(buyers_total, 1)
        untapped_customers = seg_size * (1 - pen / 100)
        gap_eur = max(0, round(untapped_customers * avg_per_buyer * 0.3, 2))  # 30% capture assumption
        magic_matrix.append({
            "segment": r["segment"],
            "category": str(r["category"])[:24],
            "penetration_pct": pen,
            "gap_opportunity_eur": gap_eur,
            "confidence": "estimated",
        })

    # ── Call list (profile-aware scripts) ───────────────────────────
    call_list = []
    for i, r in enumerate(results["churn_risk_scoring"][:12], start=1):
        reason, script = _build_script_for_profile(r)
        profile = r.get("profile", "cuenta_media")
        freq = int(r["frequency"])
        recovery = float(r["recovery_potential_eur"])
        call_list.append({
            "rank": i,
            "customer_name": _clean_customer_name(r["customer_name"]),
            "customer_id": (r["customer_id"][:8] if r["customer_id"] else None),
            "profile": profile,
            "frequency": freq,
            "deal_risk_score": float(r["deal_risk_score"]),
            "last_purchase": r["last_purchase"],
            "ltv_eur": float(r["ltv_eur"]),
            "recovery_potential_eur": recovery,
            "recovery_confidence": "estimated" if profile != "outlier" else "inferred",
            "reason": reason,
            "script_hint": script,
        })

    # ── HERO (loss framing!) ────────────────────────────────────────
    # Sum of top-12 dormant LTV — this is what walks out the door if no action
    top_dormant_ltv = sum(c["ltv_eur"] for c in call_list)
    hero_loss_headline = (
        f"€{top_dormant_ltv:,.0f} de LTV dormido en {len(call_list)} cuentas "
        f"que dejaron de comprarte. Si no las llamás esta semana, las perdés definitivamente."
    )

    # ── Dormants aggregate ──────────────────────────────────────────
    dormants = sum(
        1 for r in results["rfm_segmentation"]
        if r["segment"] in ("about_to_sleep", "at_risk", "hibernating", "lost")
    )

    # ── KPI bar (loss-framed first) ─────────────────────────────────
    kpi_bar = [
        {"label": "LTV en riesgo", "value": f"€{top_dormant_ltv:,.0f}".replace(",", "."),
         "sub": f"top {len(call_list)} dormantes", "confidence": "measured"},
        {"label": "Clientes activos", "value": f"{total_customers:,}".replace(",", "."),
         "confidence": "measured"},
        {"label": "Dormantes", "value": f"{dormants:,}".replace(",", "."),
         "sub": "> 60 días", "confidence": "measured"},
        {"label": "HHI", "value": f"{hhi:.0f}",
         "sub": {"diversified": "diversificada*", "moderate": "moderada",
                 "high_risk": "alta"}[level],
         "confidence": "measured"},
        {"label": "Champions", "value": f"{champions_share:.0f}%",
         "sub": f"{champions_count} clientes del revenue", "confidence": "measured"},
    ]

    # ── Category performance (NO MoM — single period, don't fake it) ─
    category_performance = []
    for cat, rev in cat_totals.most_common(8):
        category_performance.append({
            "category": str(cat)[:24],
            "revenue_eur": float(rev),
            "share_pct": round(100 * rev / max(sum(cat_totals.values()), 1), 2),
            "mom_pct": None,  # None — will render as "—" in UI
            "trend": None,
            "confidence": "measured",
        })

    # ── next_actions (decision forcing) ─────────────────────────────
    top5 = call_list[:5]
    top5_names = ", ".join(c["customer_name"].split()[0][:14] for c in top5)
    top5_recovery = sum(c["recovery_potential_eur"] for c in top5)

    next_actions = [
        {
            "priority": 1,
            "title": f"Llamar al top 5 dormantes ({top5_names})",
            "rationale": (
                f"LTV combinado €{sum(c['ltv_eur'] for c in top5):,.0f}. "
                f"Recuperable mínimo €{top5_recovery:,.0f}. Ventana corta."
            ),
            "impact_eur": round(top5_recovery, 2),
            "impact_confidence": "estimated",
            "deadline": "Esta semana",
        },
        {
            "priority": 2,
            "title": "Segmentar Champions en tier A/B/C",
            "rationale": (
                f"{champions_count} Champions concentran {champions_share:.0f}% del revenue. "
                "Si cae la cola se pierde un tercio de la facturación anual."
            ),
            "impact_eur": round(0.33 * total_revenue, 2),
            "impact_confidence": "estimated",
            "deadline": "Próximas 2 semanas",
        },
        {
            "priority": 3,
            "title": f"Email de reactivación automático para {seg_agg.get('about_to_sleep', {}).get('count', 0)} 'About to Sleep'",
            "rationale": (
                "Ventana de recuperación se cierra en 30 días antes de migrar a 'Hibernating'."
            ),
            "impact_eur": round(
                seg_agg.get("about_to_sleep", {}).get("revenue", 0) * 0.15, 2
            ),
            "impact_confidence": "estimated",
            "deadline": "Próximos 30 días",
        },
    ]

    # ── Assemble ────────────────────────────────────────────────────
    report = {
        "client_name": "Gloria",
        "period": "Últimos 12 meses",
        "currency": "EUR",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hero_loss_eur": round(top_dormant_ltv, 2),
        "hero_loss_headline": hero_loss_headline,
        "kpi_bar": kpi_bar,
        "rfm_segments": rfm_segments,
        "concentration": {
            "hhi": round(hhi, 2),
            "hhi_level": level,
            "cr1_pct": cr1, "cr5_pct": cr5, "cr10_pct": cr10,
            "total_customers": total_customers,
            "interpretation": interp,
            "confidence": "measured",
        },
        "top_customers": top_customers,
        "category_performance": category_performance,
        "magic_matrix": magic_matrix,
        "call_list": call_list,
        "next_actions": next_actions,
        "executive_summary": (
            f"€{top_dormant_ltv:,.0f} de LTV concentrado en {len(call_list)} cuentas dormantes "
            f"(top: {top5[0]['customer_name']}, €{top5[0]['ltv_eur']:,.0f}). "
            f"Cartera con HHI {hhi:.0f} por cliente individual, pero {champions_count} Champions "
            f"generan {champions_share:.0f}% del revenue — concentración por comportamiento alta. "
            f"Acción inmediata: call list priorizada por Deal Risk Score."
        ),
        "data_caveats": [
            f"Datos del período rolling 12 meses (al {datetime.now().strftime('%Y-%m-%d')}).",
            "MoM % omitido — requiere comparación con período previo (ver plan).",
            "Recovery potential = avg_order × 30% × confidence_factor (0.1-1.0 según frecuencia).",
        ],
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Written {OUTPUT_PATH}")
    print(f"   hero: {hero_loss_headline[:100]}...")
    print(f"   {total_customers:,} customers, HHI {hhi:.0f} ({level}), Champions {champions_count} = {champions_share:.1f}%")
    print(f"   call_list: {len(call_list)} · next_actions: {len(next_actions)}")


if __name__ == "__main__":
    main()
