"""
Analyst Agent — Stage 3a: Financial Intelligence.

Uses Sonnet for deep financial analysis. Finds patterns in
revenue, margins, concentration, seasonality, and customer dynamics.
"""

import json
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

SKILL_PATH = Path(__file__).parent.parent.parent / ".claude" / "skills" / "financial_analysis.md"


async def run_analyst(
    query_results: dict, entity_map: dict, memory: dict | None, baseline: dict,
    kg=None,
) -> dict:
    """
    Run the Analyst agent for financial pattern discovery.

    Args:
        query_results: Results from Stage 2.5 query execution.
        entity_map: Entity map from Stage 1.
        memory: Previous swarm memory (or None for first run).
        baseline: Shared revenue baseline — use these numbers for all EUR estimates.
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
    REVENUE BASELINE (measured from actual data — use these for all EUR estimates):
    {baseline_summary}

    {f"SCHEMA KNOWLEDGE GRAPH (tables, filters, JOIN paths, business concepts):{chr(10)}    {kg_context}" if kg_context else ""}

    CONTEXT:
    {shared_context}

    FOCUS:
    Find financial patterns: revenue trends, customer concentration, margin analysis,
    seasonality, year-over-year comparisons, and cash flow indicators.

    CRITICAL RULES:
    1. All EUR values MUST be derived from the baseline or query_results above.
       If you cannot derive a value from actual data, mark it as [ESTIMADO] and
       explain the assumption clearly.
    2. If baseline.total_revenue is available, use it as the denominator for
       all percentage calculations. Do not invent a different total.
    3. If a query returned actual customer names and IDs (e.g., dormant_customer_list,
       customer_concentration), use those exact names and IDs in your findings.
       Never invent customer names.
    4. If data is stale (baseline.data_freshness_days > 14), flag this in each
       finding that depends on current data.

    OUTPUT: JSON array of findings. Each finding MUST have:
    - id (e.g., "FIN-001")
    - severity (critical/warning/opportunity)
    - headline (1 sentence, with specific number — use [ESTIMADO] if the value is estimated)
    - evidence (data-backed; reference which query or table produced the number)
    - value_eur (number; null if genuinely unknown)
    - value_confidence ("measured" | "estimated" | "inferred")
    - action (specific, actionable recommendation)
    - domain: "financial"

    Wrap your complete findings list in a JSON array.
    """

    results = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        results.append(block.text)
    except Exception:
        pass

    return {"agent": "analyst", "output": "\n".join(results)}
