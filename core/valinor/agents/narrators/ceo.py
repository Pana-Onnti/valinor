"""
CEO Narrator — Stage 4a: CEO Briefing.

Produces a concise briefing: 5 numbers that matter + 3 decisions this week.
"""

import json
import logging

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are the CEO Briefing Narrator for Valinor, a business intelligence system.

You receive findings from 3 specialized agents (Analyst, Sentinel, Hunter)
and a REVENUE BASELINE computed from actual database queries.

Your job: produce a CEO BRIEFING with exactly:
1. **5 Numbers That Matter** — The most impactful KPIs, each with context
2. **3 Decisions This Week** — Concrete decisions the CEO should make NOW

RULES:
- Maximum 1 page. CEO time is expensive.
- Every number must have context: "€2.1M revenue (+12% vs Q1)" not just "€2.1M"
- Every decision must have a deadline and expected impact
- If previous memory exists, open with: "Desde el último análisis: [what changed]"
- Tone: direct, clear, no jargon. Like talking to a friend who owns the business.
- Language: match the client's configured language (default: Spanish)
- HONESTY RULE: If a value comes from agent estimation (not direct measurement),
  mark it with *(estimado)* so the CEO knows to verify before acting.
  Measured values (from baseline or query results) have no asterisk.
- FRESHNESS RULE: If data is >14 days old, add a note: "⚠️ Datos con N días de retraso"

FORMAT:
```markdown
# Briefing CEO — {client} — {period}

## 5 Números Que Importan
1. **[Metric]**: [Value] ([context/change])
2. ...

## 3 Decisiones Esta Semana
1. **[Decision]**: [Why now] → [Expected impact]
   - Deadline: [date]
2. ...

---
*Generado por Valinor v0 — [timestamp]*
```
"""


async def narrate_ceo(
    findings: dict,
    entity_map: dict,
    memory: dict | None,
    client_config: dict,
    baseline: dict,
    verification_report=None,
) -> str:
    """Produce the CEO briefing."""
    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=SYSTEM_PROMPT,
        max_turns=10,
    )

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

    REVENUE BASELINE (measured from database — these are the real numbers):
    {json.dumps(baseline, indent=2, ensure_ascii=False, default=str)}
    {number_registry_section}
    FINDINGS FROM AGENTS:
    {json.dumps(findings, indent=2, ensure_ascii=False, default=str)}

    ENTITY MAP SUMMARY:
    Entities: {list(entity_map.get('entities', {}).keys())}

    PREVIOUS MEMORY:
    {json.dumps(memory, indent=2, ensure_ascii=False, default=str) if memory else "First run — no previous memory."}

    Generate the CEO Briefing in markdown.
    Use baseline numbers as ground truth. Mark agent estimates with *(estimado)*.
    Be specific. Quantify everything. Max 1 page.
    """

    output = []
    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        output.append(block.text)
    except (RuntimeError, ConnectionError, TypeError, ValueError) as exc:
        logger.warning("ceo narrator query failed", exc_info=exc)

    return "\n".join(output)
