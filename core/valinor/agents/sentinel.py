"""
Sentinel Agent — Stage 3b: Data Quality.

Uses Sonnet to find data quality issues: duplicates, nulls,
orphans, outliers, and inconsistencies.
"""

import json
import logging
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

logger = logging.getLogger(__name__)

SKILL_PATH = Path(__file__).parent.parent.parent / ".claude" / "skills" / "data_quality.md"


async def run_sentinel(
    query_results: dict, entity_map: dict, memory: dict | None, baseline: dict,
    kg=None,
) -> dict:
    """
    Run the Sentinel agent for data quality analysis.

    Args:
        query_results: Results from Stage 2.5 query execution.
        entity_map: Entity map from Stage 1.
        memory: Previous swarm memory (or None for first run).
        baseline: Shared revenue baseline for context.
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
    REVENUE BASELINE (measured — use for impact calculations):
    {baseline_summary}

    {f"SCHEMA KNOWLEDGE GRAPH (tables, filters, JOIN paths, business concepts):{chr(10)}    {kg_context}" if kg_context else ""}

    CONTEXT:
    {shared_context}

    FOCUS:
    Find data quality issues: duplicates, null rates, orphan records,
    outliers, inconsistencies, data freshness problems.

    CRITICAL RULES:
    1. When estimating EUR impact of a data quality issue (e.g., "duplicate invoices
       worth €X"), derive the value from baseline.total_revenue or actual query rows.
       Mark as [ESTIMADO] if you cannot compute it exactly.
    2. If entity_map contains query_rules or base_filter conditions, check whether
       existing queries respected those filters. Flag any unfiltered queries.
    3. If multi-tenant data is detected (multiple ad_client_id values, etc.),
       flag it as CRITICAL — it means all unfiltered aggregates are wrong.
    4. Always include the table name and column name in each finding.

    OUTPUT: JSON array of findings. Each finding MUST have:
    - id (e.g., "DQ-001")
    - severity (critical/warning/info)
    - headline (1 sentence with specific numbers)
    - evidence (table name, column, actual counts or rates)
    - value_eur (number or null)
    - value_confidence ("measured" | "estimated" | "inferred")
    - action (specific: exclude, fix, investigate, add filter)
    - domain: "data_quality"

    Wrap your complete findings list in a JSON array.
    """

    results = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if hasattr(msg, "content"):
                for block in msg.content:
                    if hasattr(block, "text"):
                        results.append(block.text)
    except (RuntimeError, ConnectionError, TypeError, ValueError) as exc:
        logger.warning("sentinel agent query failed", exc_info=exc)

    return {"agent": "sentinel", "output": "\n".join(results)}
