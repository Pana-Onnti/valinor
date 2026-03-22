"""
Hunter Agent — Stage 3c: Opportunity Detection.

Uses Sonnet to find money on the table: churn risk, dormant customers,
cross-sell potential, pricing anomalies, debt recovery opportunities.
"""

import json
import logging
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

logger = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).parent.parent.parent / ".claude" / "skills" / "sales_intelligence.md"


async def run_hunter(
    query_results: dict, entity_map: dict, memory: dict | None, baseline: dict,
    kg=None,
) -> dict:
    """
    Run the Hunter agent for opportunity detection.

    Args:
        query_results: Results from Stage 2.5 query execution.
        entity_map: Entity map from Stage 1.
        memory: Previous swarm memory (or None for first run).
        baseline: Shared revenue baseline — use for consistent EUR estimates.
        kg: Optional SchemaKnowledgeGraph for enriched schema context.

    Returns:
        Dict with agent name and findings.
    """
    skill_content = ""
    if SKILL_PATH.exists():
        skill_content = SKILL_PATH.read_text(encoding="utf-8")

    shared_context = json.dumps(
        {
            "entity_map": entity_map,
            "query_results": query_results,
            "previous_memory": memory,
        },
        indent=2,
        ensure_ascii=False,
        default=str,
    )

    baseline_summary = json.dumps(baseline, indent=2, ensure_ascii=False, default=str)

    kg_context = kg.to_prompt_context() if kg else ""

    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=skill_content,
        max_turns=20,
    )

    prompt = f"""
    REVENUE BASELINE (measured from actual data):
    {baseline_summary}

    {f"SCHEMA KNOWLEDGE GRAPH (tables, filters, JOIN paths, business concepts):{chr(10)}    {kg_context}" if kg_context else ""}

    CONTEXT:
    {shared_context}

    FOCUS:
    Find money on the table: churn risk (customers about to leave),
    dormant customers (used to buy, stopped), cross-sell opportunities,
    pricing anomalies, and debt recovery potential.

    CRITICAL RULES:
    1. If query_results contains dormant_customer_list rows, use those EXACT
       customer names and IDs in your findings. Never invent customer names.
       If no query returned customer names, say "customers identified by ID in
       dormant_customer_list query — run it to get names" instead of inventing names.
    2. All EUR opportunity estimates must be based on:
       a) Actual data from query results (preferred), or
       b) baseline.avg_invoice × count of affected customers (acceptable), or
       c) Clearly labeled as [ESTIMADO] with the assumption stated.
    3. Conservative estimates beat optimistic ones. A salesperson acting on
       wrong data loses trust. Say "€60K conservatively" over "€18M in theory".
    4. If baseline.data_freshness_days > 14, caveat all churn/dormancy findings
       — the customer may have purchased in the unsynced period.

    OUTPUT: JSON array of findings. Each finding MUST have:
    - id (e.g., "HUNT-001")
    - severity (critical/warning/opportunity)
    - headline (1 sentence — include customer names if available from query,
               use [ESTIMADO] for EUR values not from query results)
    - evidence (reference which query or table produced the data)
    - value_eur (number or null)
    - value_confidence ("measured" | "estimated" | "inferred")
    - action (specific: "call customer X (id: ABC123)", "adjust pricing for SKU Y")
    - domain: "sales"

    Wrap your complete findings list in a JSON array.
    """

    results = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        results.append(block.text)
    except (RuntimeError, ConnectionError, TypeError, ValueError) as exc:
        logger.warning("hunter agent query failed", exc_info=exc)

    return {"agent": "hunter", "output": "\n".join(results)}
