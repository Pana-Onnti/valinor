"""
Controller Narrator — Stage 4b: Controller Report.

P&L analysis, provisions, anomalies, forecast, and regulatory flags.
"""

import json

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock


SYSTEM_PROMPT = """
You are the Controller Report Narrator for Valinor, a business intelligence system.

You receive findings from 3 specialized agents (Analyst, Sentinel, Hunter),
a REVENUE BASELINE from actual database queries, and optionally raw query results.

Your job: produce a CONTROLLER REPORT covering:
1. **P&L Summary** — Revenue, costs, margins with period comparison
2. **Provisions & Debt** — Aging analysis, provision requirements, top debtors
3. **Data Quality Alerts** — Issues that could affect financial reporting
4. **Anomalies** — Unusual patterns that need investigation
5. **Forecast Indicators** — Forward-looking signals

RULES:
- Be precise with numbers — the controller will cross-check
- Flag anything that could affect regulatory compliance
- CRITICAL: Distinguish MEASURED values (from baseline/query_results) from ESTIMATED
  values (agent inference). Use these markers clearly:
    [MEDIDO] — from actual database query
    [ESTIMADO] — agent calculation or inference
    [INFERIDO] — logical deduction from structure (no direct query)
- Reference the data source for each claim (e.g., "query: total_revenue_summary",
  "table: fin_payment_schedule", "agent: analyst finding FIN-003")
- Use accounting terminology appropriate to the client's fiscal context
- If AR outstanding data is in baseline (total_outstanding_ar), use it directly.
  Do NOT extrapolate AR from invoice counts if the actual number is available.
- Language: match the client's configured language (default: Spanish)

FORMAT:
```markdown
# Reporte Controller — {client} — {period}

## Resumen P&L
| Concepto | Periodo Actual | Fuente | Confianza |
|---|---|---|---|

## Provisiones y Deuda
[Aging table + top debtors — use actual query results if available]

## Alertas de Calidad de Datos
[Issues from Sentinel — with table/column references]

## Anomalías
[Unusual patterns requiring investigation]

## Indicadores Prospectivos
[Forward-looking signals]

---
*Generado por Valinor v0 — [timestamp]*
```
"""


async def narrate_controller(
    findings: dict,
    entity_map: dict,
    memory: dict | None,
    client_config: dict,
    baseline: dict,
    query_results: dict,
) -> str:
    """Produce the controller report."""
    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=SYSTEM_PROMPT,
        max_turns=15,
    )

    # Include actual query result rows for the controller — most important ones
    key_query_results = {
        k: v for k, v in query_results.get("results", {}).items()
        if k in ("total_revenue_summary", "ar_outstanding_actual", "aging_analysis",
                 "top_debtors", "data_freshness", "duplicate_detection", "null_analysis")
    }

    prompt = f"""
    CLIENT: {client_config.get('display_name', client_config.get('name', 'Unknown'))}
    SECTOR: {client_config.get('sector', 'Unknown')}
    CURRENCY: {client_config.get('currency', 'EUR')}
    FISCAL CONTEXT: {client_config.get('fiscal_context', 'generic')}
    LANGUAGE: {client_config.get('language', 'es')}

    REVENUE BASELINE (measured from database):
    {json.dumps(baseline, indent=2, ensure_ascii=False, default=str)}

    KEY QUERY RESULTS (actual database rows):
    {json.dumps(key_query_results, indent=2, ensure_ascii=False, default=str)}

    FINDINGS FROM AGENTS:
    {json.dumps(findings, indent=2, ensure_ascii=False, default=str)}

    ENTITY MAP:
    {json.dumps({k: {'table': v.get('table'), 'row_count': v.get('row_count')}
                 for k, v in entity_map.get('entities', {}).items()}, indent=2)}

    PREVIOUS MEMORY:
    {json.dumps(memory, indent=2, ensure_ascii=False, default=str) if memory else "First run — no previous memory."}

    Generate the Controller Report. Mark every EUR value as [MEDIDO], [ESTIMADO],
    or [INFERIDO]. Reference the source query or agent finding for each claim.
    """

    output = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        output.append(block.text)
    except Exception:
        pass

    return "\n".join(output)
