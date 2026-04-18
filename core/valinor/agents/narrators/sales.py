"""
Sales Narrator v2 — emits a structured SalesReportV2 JSON.

Consumed directly by the frontend (SalesReportV2.tsx) — no markdown parsing.
Every numeric field carries a confidence marker (measured/estimated/inferred)
so the UI can render [MEDIDO]/[ESTIMADO]/[INFERIDO] badges.

Refs: VAL-141
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from claude_agent_sdk import query, ClaudeAgentOptions

from valinor.schemas.sales_report_v2 import SalesReportV2

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are the Sales Report Narrator v2 for Valinor — a business intelligence
system for B2B distributors. Your output is a decision-forcing diagnostic,
not a dashboard.

Your ONLY output is a single JSON object conforming to the SalesReportV2
schema. NO markdown. NO prose outside the JSON. NO code fences. Raw JSON
only — first character `{`, last character `}`.

You receive:
  - REVENUE BASELINE (measured from database)
  - 5 structured query results: rfm_segmentation, concentration_hhi,
    concentration_top_customers, cross_sell_matrix, churn_risk_scoring
  - FINDINGS from the Analyst, Sentinel, Hunter agents
  - Optional NUMBER REGISTRY (verified values you MUST reuse verbatim)

Your job: produce the JSON report with these fields:

{
  "client_name": "...",
  "period": "Últimos 12 meses",
  "currency": "EUR",
  "generated_at": "ISO-8601 timestamp",

  // HERO — loss-framed (Kahneman 2×). Sum of top-12 dormant LTV.
  // This is the first element the CEO sees: what walks out the door if
  // nothing is done THIS WEEK. Never gain-frame.
  "hero_loss_eur": 1315041,
  "hero_loss_headline": "€1,315,041 de LTV dormido en 12 cuentas que dejaron de comprarte. Si no las llamás esta semana, las perdés definitivamente.",

  "kpi_bar": [
    // 5 tiles. First tile = LTV at risk (loss-framed). Others: clientes
    // activos, dormantes, HHI (with level in sub), Champions share.
    {"label": "LTV en riesgo", "value": "€1.315.041", "sub": "top 12 dormantes", "confidence": "measured"},
    {"label": "Clientes activos", "value": "1.928", "confidence": "measured"},
    {"label": "Dormantes", "value": "1.084", "sub": "> 60 días", "confidence": "measured"},
    {"label": "HHI", "value": "290", "sub": "diversificada*", "confidence": "measured"},
    {"label": "Champions", "value": "72%", "sub": "414 clientes del revenue", "confidence": "measured"}
  ],

  "rfm_segments": [
    // 1 row per non-empty segment from rfm_segmentation query
    {"segment": "champions", "count": 414, "revenue_share_pct": 71.5,
     "avg_ltv": 5862, "recommended_action": "Programa VIP. Gerente comercial directo.",
     "confidence": "measured"}
  ],

  "concentration": {
    "hhi": 290.18, "hhi_level": "diversified",
    "cr1_pct": 14.47, "cr5_pct": 28.48, "cr10_pct": 37.21,
    "total_customers": 1928,
    // MUST reconcile HHI (individual) with Champions share (behavioral).
    // Avoid contradictions like "diversified" + "71% concentration".
    "interpretation": "Por cliente individual la cartera es muy diversificada (HHI 290). Pero por comportamiento, 414 Champions (21% de la base) generan el 72% del revenue: si la cola de Champions cae, perdés un tercio de la facturación.",
    "confidence": "measured"
  },

  "top_customers": [
    // STRIP UUIDs from customer_name. Customer IDs go in customer_id
    // field (truncate to 8 chars if long hash). Title stays clean.
    {"customer_name": "ISKAY PET S.LU.", "customer_id": "159599AA",
     "ltv_eur": 489781, "share_pct": 14.47, "last_purchase": "2025-06-19",
     "risk": "high", "confidence": "measured"}
  ],

  "category_performance": [
    // Use REAL category names from cross_sell_matrix (joined to
    // product_categories.name). Never emit UUIDs like "BCA314D8".
    // If only one period is available, set mom_pct=null, trend=null —
    // NEVER fill MoM with 0 (misleading).
    {"category": "ALIMENTACIÓN", "revenue_eur": 312000, "share_pct": 31.4,
     "mom_pct": null, "trend": null, "confidence": "measured"}
  ],

  "magic_matrix": [
    // RFM segment × real category name. gap_opportunity_eur should be
    // derived as untapped_customers × avg_per_buyer × 0.3, NOT just
    // (100-penetration) × placeholder.
    {"segment": "champions", "category": "ALIMENTACIÓN",
     "penetration_pct": 89.0, "gap_opportunity_eur": 12000,
     "confidence": "estimated"}
  ],

  "call_list": [
    // Top 10-12 prioritized by deal_risk_score. Each entry carries its
    // profile for script selection. 3 profiles:
    //   - account_grande (>100 pedidos históricos)
    //   - cuenta_media (4-100)
    //   - outlier (1-3) — low confidence, careful script
    // Script MUST differ by profile. Never use the same one-liner
    // for an outlier (1 pedido) and a regular account (100+).
    {"rank": 1, "customer_name": "ISKAY PET S.LU.", "customer_id": "159599AA",
     "profile": "cuenta_media", "frequency": 32,
     "deal_risk_score": 80.7, "last_purchase": "2025-06-19",
     "ltv_eur": 489781, "recovery_potential_eur": 4592,
     "recovery_confidence": "estimated",
     "reason": "32 pedidos históricos, €489K LTV, 303 días fuera de ciclo.",
     "script_hint": "Tu pedido medio era €15K y venías comprando regularmente. ¿Hay algo que podamos ajustar — producto, precio, logística?"}
  ],

  "next_actions": [
    // DECISION-FORCING block: 3-5 concrete actions for THIS WEEK.
    // Each with rationale + impact_eur + deadline. Finish the report
    // with "acá está lo que tenés que hacer", not with caveats alone.
    {"priority": 1, "title": "Llamar al top 5 dormantes esta semana",
     "rationale": "LTV combinado €1.1M. Recuperable mínimo €16K en 30 días.",
     "impact_eur": 16000, "impact_confidence": "estimated",
     "deadline": "Esta semana"}
  ],

  "executive_summary": "3-5 sentences. Lead with the loss-framed hero. Second sentence = HHI-vs-Champions reconciliation. End with call to action.",
  "data_caveats": []
}

RULES (non-negotiable):

1. ENUM VALUES — use exactly these strings:
   - rfm_segments[].segment: champions | loyal | potential_loyalists | new_customers | promising | need_attention | about_to_sleep | at_risk | cannot_lose | hibernating | lost
   - concentration.hhi_level: diversified | moderate | high_risk
   - top_customers[].risk: low | medium | high
   - call_list[].profile: account_grande | cuenta_media | outlier
   - confidence / recovery_confidence / impact_confidence: measured | estimated | inferred
   - category_performance[].trend: sube | estable | baja | caida (OR null if MoM unavailable)

2. LOSS FRAMING (critical) — the hero and the executive summary lead with
   what's AT RISK (€X of LTV dormido), NOT what's RECOVERABLE (€Y).
   hero_loss_eur = sum of top-12 call_list LTV (not the average potential).

3. HONESTY — if a query returned no rows or failed, emit empty lists and
   add a caveat in data_caveats. Do NOT invent rows. If MoM is unavailable,
   set mom_pct=null, trend=null (never default to 0).

4. HHI RECONCILIATION — always reconcile HHI (per-customer) vs Champions
   (behavioral) in concentration.interpretation. Say both: "por cliente
   diversificada · por comportamiento concentrada en Champions".

5. 3 SCRIPT VARIANTS — script_hint MUST differ per profile:
   - account_grande: "Hace meses no recibimos tu pedido habitual — ¿cambió
     algo del lado logístico/comercial?"
   - cuenta_media: "Tu pedido medio era €X — ¿hay algo que podamos ajustar?"
   - outlier: "Hiciste un pedido importante y no volvimos a coincidir.
     Queremos entender tu caso, sin presionar venta."

6. UUIDs — strip trailing hashes from customer_name. Hashes go in
   customer_id field only. Never display UUIDs as category names —
   cross_sell_matrix ALREADY joins to product_categories.name.

7. CONFIDENCE MARKERS — mark as "measured" only if the value comes directly
   from a query. Use "estimated" for derived values (recovery_potential_eur,
   gap_opportunity_eur). Use "inferred" when the agent reasoned without a query.

8. LANGUAGE — Spanish for all human-readable strings (recommended_action,
   reason, script_hint, interpretation, executive_summary). Keep it operational
   and action-oriented (imperative verbs, specific amounts and names).

9. NUMBER REGISTRY — if present, use those exact values. NEVER contradict them.

10. TOP-N LIMITS — 7-10 top_customers, up to 11 rfm_segments, 10-15 call_list
    entries, magic_matrix cells up to 30 (focus on significant gaps), 3-5
    next_actions.

11. OUTPUT — raw JSON only. Your first character is `{`. Your last is `}`.
"""


async def narrate_sales(
    findings: dict,
    entity_map: dict,
    memory: dict | None,
    client_config: dict,
    baseline: dict,
    query_results: dict,
    verification_report=None,
    **kwargs,
) -> str:
    """
    Produce the Sales Report v2 as a JSON-serialized string.

    The payload conforms to the SalesReportV2 Pydantic schema. Returned as a
    string (not a dict) for backward compatibility with the narrator pipeline,
    which stores all narrator outputs in Dict[str, str]. The frontend parses
    this with JSON.parse() and renders via SalesReportV2.tsx.

    On parse failure, returns a schema-valid fallback JSON string with caveats.
    """
    results = query_results.get("results", {}) if isinstance(query_results, dict) else {}

    sales_queries = {
        k: results.get(k) for k in (
            "rfm_segmentation",
            "concentration_hhi",
            "concentration_top_customers",
            "cross_sell_matrix",
            "churn_risk_scoring",
        ) if results.get(k) is not None
    }

    legacy_customer_queries = {
        k: results.get(k) for k in (
            "dormant_customer_list",
            "never_invoiced_customers",
            "customer_concentration",
            "top_debtors",
        ) if results.get(k) is not None
    }

    number_registry_section = ""
    if verification_report and hasattr(verification_report, "to_prompt_context"):
        number_registry_section = f"""
NUMBER REGISTRY — USE ONLY THESE VALUES
{verification_report.to_prompt_context()}
"""

    prompt = f"""
CLIENT: {client_config.get('display_name', client_config.get('name', 'Unknown'))}
SECTOR: {client_config.get('sector', 'Unknown')}
CURRENCY: {client_config.get('currency', 'EUR')}
LANGUAGE: {client_config.get('language', 'es')}
GENERATED_AT: {datetime.now(timezone.utc).isoformat()}

REVENUE BASELINE (measured from database):
{json.dumps(baseline, indent=2, ensure_ascii=False, default=str)}
{number_registry_section}
SALES V2 QUERY RESULTS (5 structured analyses):
{json.dumps(sales_queries, indent=2, ensure_ascii=False, default=str)
 if sales_queries else "NO SALES V2 QUERIES RETURNED. Emit empty sections + caveats."}

LEGACY CUSTOMER QUERIES (supplementary — use for top_customers fallback / dormants):
{json.dumps(legacy_customer_queries, indent=2, ensure_ascii=False, default=str)
 if legacy_customer_queries else "(none)"}

FINDINGS FROM AGENTS:
{json.dumps(findings, indent=2, ensure_ascii=False, default=str)}

ENTITY MAP SUMMARY:
Entities found: {list(entity_map.get('entities', {}).keys())}

PREVIOUS MEMORY:
{json.dumps(memory, indent=2, ensure_ascii=False, default=str) if memory else "First run."}

Emit the SalesReportV2 JSON now. Raw JSON only. No code fences. No prose.
"""

    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=SYSTEM_PROMPT,
        max_turns=10,
    )

    raw_chunks: list[str] = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        raw_chunks.append(block.text)
    except (RuntimeError, ConnectionError, TypeError, ValueError) as exc:
        logger.warning("sales narrator v2 query failed", exc_info=exc)

    raw = "".join(raw_chunks).strip()

    # Strip optional code fences defensively
    if raw.startswith("```"):
        raw = raw.strip("`")
        first_newline = raw.find("\n")
        if first_newline != -1:
            raw = raw[first_newline + 1 :]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
        validated = SalesReportV2.model_validate(parsed)
        return json.dumps(validated.model_dump(mode="json"), ensure_ascii=False)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("sales narrator v2: invalid JSON or schema mismatch: %s", exc)
        return _fallback_report(client_config, reason=f"narrator output invalid: {exc}")


def _fallback_report(client_config: dict, reason: str) -> str:
    """Minimal schema-valid report when the narrator fails to emit usable JSON."""
    fallback = SalesReportV2(
        client_name=client_config.get("display_name", client_config.get("name", "Unknown")),
        period="N/A",
        currency=client_config.get("currency", "EUR"),
        generated_at=datetime.now(timezone.utc).isoformat(),
        hero_loss_eur=0.0,
        hero_loss_headline="",
        kpi_bar=[],
        rfm_segments=[],
        concentration={
            "hhi": 0,
            "hhi_level": "diversified",
            "cr1_pct": 0,
            "cr5_pct": 0,
            "cr10_pct": 0,
            "total_customers": 0,
            "interpretation": "Datos insuficientes.",
            "confidence": "inferred",
        },
        top_customers=[],
        category_performance=[],
        magic_matrix=[],
        call_list=[],
        next_actions=[],
        executive_summary="Reporte no disponible. Revisar ejecución del pipeline.",
        data_caveats=[reason],
    )
    return json.dumps(fallback.model_dump(mode="json"), ensure_ascii=False)
