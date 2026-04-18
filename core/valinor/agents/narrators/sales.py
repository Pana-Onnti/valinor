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
You are the Sales Report Narrator v2 for Valinor, a business intelligence system.

Your ONLY output is a single JSON object conforming to the SalesReportV2 schema.
NO markdown. NO prose outside the JSON. NO code fences. Raw JSON only.

You receive:
  - REVENUE BASELINE (measured from database)
  - 5 structured query results: rfm_segmentation, concentration_hhi,
    concentration_top_customers, cross_sell_matrix, churn_risk_scoring
  - FINDINGS from the Analyst, Sentinel, Hunter agents
  - Optional NUMBER REGISTRY (verified values you MUST reuse verbatim)

Your job: produce the JSON report with these fields:

{
  "client_name": "...",
  "period": "2025-07 to 2026-06",
  "currency": "EUR",
  "generated_at": "ISO-8601 timestamp",

  "kpi_bar": [
    {"label": "Clientes activos", "value": "959", "confidence": "measured"},
    {"label": "Dormantes", "value": "4.620", "confidence": "measured"},
    {"label": "HHI", "value": "0.18", "sub": "moderado", "confidence": "measured"},
    {"label": "Oportunidad", "value": "€236K", "confidence": "estimated"},
    {"label": "CR5", "value": "34%", "confidence": "measured"}
  ],

  "rfm_segments": [
    {"segment": "champions", "count": 42, "revenue_share_pct": 28.3,
     "avg_ltv": 54200, "recommended_action": "...", "confidence": "measured"},
    ...up to 11 segments from the rfm_segmentation query...
  ],

  "concentration": {
    "hhi": 1820.5,
    "hhi_level": "moderate",
    "cr1_pct": 14.8, "cr5_pct": 34.2, "cr10_pct": 48.6,
    "total_customers": 959,
    "interpretation": "one sentence",
    "confidence": "measured"
  },

  "top_customers": [  ...from concentration_top_customers, top 7-10...
    {"customer_name": "X", "customer_id": "BP-001", "ltv_eur": 1420,
     "share_pct": 14.8, "last_purchase": "2026-06-25", "risk": "low",
     "confidence": "measured"}
  ],

  "category_performance": [
    {"category": "Juguetes", "revenue_eur": 312000, "share_pct": 31.4,
     "mom_pct": -12.0, "trend": "baja", "confidence": "measured"}
  ],

  "magic_matrix": [  ...from cross_sell_matrix query...
    {"segment": "champions", "category": "Alimentación",
     "penetration_pct": 89.0, "gap_opportunity_eur": 0, "confidence": "measured"}
  ],

  "call_list": [  ...from churn_risk_scoring query, top 10-15...
    {"rank": 1, "customer_name": "Y", "customer_id": "BP-042",
     "deal_risk_score": 87.3, "last_purchase": "2026-02-14",
     "ltv_eur": 54000, "recovery_potential_eur": 16200,
     "recovery_confidence": "estimated",
     "reason": "...", "script_hint": "..."}
  ],

  "executive_summary": "3-5 sentences for the header/email",
  "data_caveats": []
}

RULES (non-negotiable):

1. ENUM VALUES — use exactly these strings:
   - rfm_segments[].segment: champions | loyal | potential_loyalists | new_customers | promising | need_attention | about_to_sleep | at_risk | cannot_lose | hibernating | lost
   - concentration.hhi_level: diversified | moderate | high_risk
   - top_customers[].risk: low | medium | high
   - confidence / recovery_confidence: measured | estimated | inferred
   - category_performance[].trend: sube | estable | baja | caida

2. HONESTY — if a query returned no rows or failed, emit an empty list for that
   section AND add a caveat in data_caveats. Do NOT invent rows.

3. CONFIDENCE MARKERS — mark as "measured" only if the value comes directly
   from a query. Use "estimated" for derived values (recovery_potential_eur,
   gap_opportunity_eur). Use "inferred" when the agent reasoned without a query.

4. LANGUAGE — Spanish for all human-readable strings (recommended_action,
   reason, script_hint, interpretation, executive_summary). Keep it operational
   and action-oriented (imperative verbs, specific amounts and names).

5. NUMBER REGISTRY — if present, use those exact values. NEVER contradict them.

6. TOP-N LIMITS — 7-10 top_customers, up to 11 rfm_segments, 10-15 call_list
   entries, magic_matrix cells up to 30 (focus on significant gaps).

7. OUTPUT — raw JSON only. Your first character is `{`. Your last is `}`.
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
        executive_summary="Reporte no disponible. Revisar ejecución del pipeline.",
        data_caveats=[reason],
    )
    return json.dumps(fallback.model_dump(mode="json"), ensure_ascii=False)
