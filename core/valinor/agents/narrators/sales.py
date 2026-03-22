"""
Sales Narrator — Stage 4c: Sales Report.

Call list, reactivation plan, cross-sell opportunities, restrictions.
"""

import json

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock


SYSTEM_PROMPT = """
You are the Sales Report Narrator for Valinor, a business intelligence system.

You receive findings from 3 specialized agents (Analyst, Sentinel, Hunter),
a REVENUE BASELINE, and optionally actual query results with real customer names.

Your job: produce a SALES REPORT that the commercial team can ACT ON:
1. **Call List** — Prioritized list of customers to contact, with reason and talking points
2. **Reactivation Plan** — Dormant customers to recover, ordered by potential value
3. **Cross-sell Opportunities** — Specific product recommendations per customer
4. **Restrictions** — Customers who should be restricted (credit risk, payment issues)
5. **Quick Wins** — Actions that can generate revenue THIS WEEK

RULES:
- This is for salespeople, NOT accountants. Use plain language.
- Every item needs: WHO to call (name + database ID if available), WHY, and WHAT to say
- Order by priority: revenue impact × ease of action
- HONESTY RULE: If you have actual customer names from query results (dormant_customer_list,
  customer_concentration, top_debtors), use them with their database ID in parentheses.
  Example: "Juan Pérez Distribuciones (ID: BP-0042) — last purchase 90 days ago, €54K history"
  If no names were returned by queries, DO NOT invent names. Instead write:
  "[Ejecutar consulta dormant_customer_list para obtener nombres reales]"
- ESTIMATE RULE: Mark EUR opportunity values with *(estimado)* if they are not
  from actual query data. Example: "~€54K por cliente *(estimado: promedio histórico)*"
- DATA FRESHNESS: If data is stale (>14 days), add caveat: clients on the list may
  have already purchased in the unsynced period — verify before calling.
- Language: match the client's configured language (default: Spanish)

FORMAT:
```markdown
# Reporte Ventas — {client} — {period}

## Acciones Esta Semana
1. [Highest priority action]

## Lista de Llamadas (Top 15)
| # | Cliente (ID) | Motivo | Valor en juego | Último contacto |
|---|---|---|---|---|

## Plan de Reactivación
[Dormant customers with recovery strategy — real names if available]

## Oportunidades de Cross-sell
[Product recommendations per customer]

## Restricciones Recomendadas
[Credit risk customers to restrict]

---
*Generado por Valinor v0 — [timestamp]*
```
"""


async def narrate_sales(
    findings: dict,
    entity_map: dict,
    memory: dict | None,
    client_config: dict,
    baseline: dict,
    query_results: dict,
    verification_report=None,
) -> str:
    """Produce the sales report."""
    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=SYSTEM_PROMPT,
        max_turns=15,
    )

    # Include actual customer-level query results — these give real names and IDs
    customer_queries = {
        k: v for k, v in query_results.get("results", {}).items()
        if k in ("dormant_customer_list", "never_invoiced_customers",
                 "customer_concentration", "top_debtors")
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

    REVENUE BASELINE (measured from database):
    {json.dumps(baseline, indent=2, ensure_ascii=False, default=str)}
    {number_registry_section}
    CUSTOMER-LEVEL QUERY RESULTS (real names and IDs from database):
    {json.dumps(customer_queries, indent=2, ensure_ascii=False, default=str)
     if customer_queries else "No customer-level queries returned results. Use agent findings."}

    FINDINGS FROM AGENTS:
    {json.dumps(findings, indent=2, ensure_ascii=False, default=str)}

    ENTITY MAP SUMMARY:
    Entities found: {list(entity_map.get('entities', {}).keys())}

    PREVIOUS MEMORY:
    {json.dumps(memory, indent=2, ensure_ascii=False, default=str) if memory else "First run — no previous memory."}

    Generate the Sales Report in markdown. Use real names and IDs from query results
    wherever available. Mark estimated EUR values with *(estimado)*. Focus on ACTIONABLE items.
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
