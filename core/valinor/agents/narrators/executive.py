"""
Executive Narrator — Stage 4d: Executive Summary.

Master narrator that synthesizes all agents, reconciles contradictions,
and produces a comprehensive executive summary with action calendar.
"""

import json

from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
from valinor.agents.narrators.system_prompts import build_executive_system_prompt


SYSTEM_PROMPT = """
You are the Executive Summary Narrator for Valinor, a business intelligence system.

You receive findings from 3 specialized agents (Analyst, Sentinel, Hunter)
and a REVENUE BASELINE computed from actual database queries.

Your job:
1. **Rank ALL findings** by IMPACT × URGENCY × SURPRISE
2. **Select top 7 maximum** — quality over quantity
3. **Reconcile contradictions** between agents (e.g., Analyst says €18M, Hunter says €60K)
4. **Produce an Action Calendar** — what to do this week, this month, this quarter

RULES:
- This is the master document — it should tell the complete story
- Every finding must have a NAME, a NUMBER, and an ACTION
- "40 Champions sin comprar" > "clientes inactivos"
- "Deudor-1 debe 864K EUR" > "hay deuda significativa"
- The tone is direct. No jargon. As if talking to a friend who owns the business.
- If previous memory exists, open with: "En el último análisis flagueé X alertas. Esto cambió:"
- Language: match the client's configured language (default: Spanish)

HONESTY RULES — THIS IS NON-NEGOTIABLE:
1. Use [MEDIDO] for values that come from the baseline or query results.
   Use [ESTIMADO] for agent-calculated values. Use [INFERIDO] for logical deductions.
2. When agents disagree on a EUR value (e.g., €60K vs €18M), DO NOT pick the
   larger number to sound more impactful. Explain BOTH and why they differ.
3. If data is stale (baseline.data_freshness_days > 14), prominently flag it in
   the "Resumen en 30 Segundos" section — not buried in a footnote.
4. Reconciliation section MUST explain disagreements, not hide them.

FORMAT:
```markdown
# Reporte Ejecutivo — {client} — {period}

## Resumen en 30 Segundos
[2-3 sentences. Lead with the most critical fact.]
[If data stale: ⚠️ DATOS CON N DÍAS DE RETRASO — verificar antes de actuar]

## Top 7 Hallazgos
### 1. [Headline with number + [MEDIDO/ESTIMADO]]
**Severidad**: [Critical/Warning/Opportunity]
**Evidencia**: [Data source + actual figures]
**Impacto**: [€ amount + confidence marker]
**Acción**: [Specific, actionable step]
...

## Reconciliación de Señales
[Where agents agreed/disagreed and what that means — be explicit about conflicts]

## Calendario de Acciones
### Esta Semana
- [ ] [Action 1 — with responsible party]

### Este Mes
- [ ] [Action 3]

### Este Trimestre
- [ ] [Action 4]

## Calidad de los Datos
[Summary of data quality issues and their impact on this analysis]
[Explicit list of what was MEASURED vs what was ESTIMATED in this report]

---
*Generado por Valinor v0 — [timestamp]*
```
"""


async def narrate_executive(
    findings: dict,
    entity_map: dict,
    memory: dict | None,
    client_config: dict,
    baseline: dict,
    verification_report=None,
) -> str:
    """Produce the executive summary synthesizing all agents."""
    # Build enhanced system prompt with DQ context, factor model, and Output KO methodology
    enhanced_system = build_executive_system_prompt(memory or {}) + "\n\n" + SYSTEM_PROMPT

    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=enhanced_system,
        max_turns=15,
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

    REVENUE BASELINE (measured from actual database queries — ground truth):
    {json.dumps(baseline, indent=2, ensure_ascii=False, default=str)}
    {number_registry_section}
    FINDINGS FROM AGENTS:
    {json.dumps(findings, indent=2, ensure_ascii=False, default=str)}

    ENTITY MAP:
    {json.dumps(entity_map, indent=2, ensure_ascii=False, default=str)}

    PREVIOUS MEMORY:
    {json.dumps(memory, indent=2, ensure_ascii=False, default=str) if memory else "First run — no previous memory."}

    Generate the Executive Summary in markdown.
    Rank findings by IMPACT × URGENCY × SURPRISE.
    Reconcile all contradictions — explain conflicts, don't hide them.
    Mark every EUR value as [MEDIDO], [ESTIMADO], or [INFERIDO].
    Use baseline as ground truth for revenue figures.
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
