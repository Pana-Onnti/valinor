"""
Pipeline Reconciliation — Swarm conflict detection and resolution.

Extracted from pipeline.py for better modularity.

Contains:
  - reconcile_swarm         Stage 3.5: detect & resolve agent numeric conflicts
  - _parse_findings_from_output   helper to extract structured findings
"""

import json
import re
from typing import Any

from claude_agent_sdk import query as agent_query, ClaudeAgentOptions, AssistantMessage, TextBlock


def _parse_findings_from_output(agent_data: dict) -> list[dict]:
    """Extract structured findings list from an agent's raw output."""
    if isinstance(agent_data.get("findings"), list):
        return agent_data["findings"]
    output = agent_data.get("output", "")
    if not output:
        return []
    for candidate in re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', output):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                if any("id" in item or "value_eur" in item for item in parsed[:2]):
                    return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    return []


# ═══════════════════════════════════════════════════════════════
# STAGE 3.5 — RECONCILIATION NODE
# Pattern: Debate + Judge (Arbiter) / Self-Consistency
# Source: Multi-Agent Collaboration Survey (arxiv:2501.06322, 2025)
#         Agent Drift paper (arxiv:2601.04170, 2025)
# ═══════════════════════════════════════════════════════════════

async def reconcile_swarm(findings: dict, baseline: dict) -> dict:
    """
    Detect and resolve numeric conflicts between Analyst, Sentinel, and Hunter.

    Algorithm:
      1. Parse structured findings from all 3 agents.
      2. Group by domain (financial / data_quality / sales).
      3. Within each domain, collect all value_eur values.
      4. If any pair differs by > CONFLICT_THRESHOLD (2x), invoke a Haiku
         Arbiter that:
           - Sees both findings + the frozen baseline
           - Selects the more defensible value WITH a citation
           - Explains the discrepancy in one sentence
      5. Attach a reconciliation_notes list to the findings dict.
         Narrators pick this up automatically.

    The Arbiter DOES NOT average values — it selects the one supported by
    the baseline or re-executable query evidence.
    """
    CONFLICT_THRESHOLD = 2.0  # flag when max/min ratio exceeds this

    # ── Collect all findings with value_eur ──
    all_findings: list[dict] = []
    for agent_name, agent_data in findings.items():
        if isinstance(agent_data, dict) and not agent_data.get("error"):
            for f in _parse_findings_from_output(agent_data):
                if isinstance(f, dict) and f.get("value_eur") is not None:
                    f["_agent"] = agent_name
                    all_findings.append(f)

    if not all_findings:
        findings["_reconciliation"] = {
            "ran": True, "conflicts_found": 0, "notes": [],
            "message": "No structured findings with value_eur to reconcile.",
        }
        return findings

    # ── Group by domain and headline keywords ──
    # Simple heuristic: cluster findings that share the same domain AND
    # at least one significant keyword (>5 chars) in their headline
    conflicts: list[dict] = []
    processed_pairs: set[frozenset] = set()

    for i, f1 in enumerate(all_findings):
        for j, f2 in enumerate(all_findings):
            if i >= j:
                continue
            pair_key = frozenset([f1.get("id",""), f2.get("id","")])
            if pair_key in processed_pairs:
                continue
            # Same agent -> no conflict by definition
            if f1["_agent"] == f2["_agent"]:
                continue
            # Different domain -> different topics, not a conflict
            if f1.get("domain") != f2.get("domain"):
                continue

            v1 = float(f1["value_eur"])
            v2 = float(f2["value_eur"])
            if v1 <= 0 or v2 <= 0:
                continue

            ratio = max(v1, v2) / min(v1, v2)
            if ratio < CONFLICT_THRESHOLD:
                continue

            # Check headline similarity (at least 1 significant word overlap)
            words1 = {w.lower() for w in re.findall(r'\b\w{5,}\b', f1.get("headline", ""))}
            words2 = {w.lower() for w in re.findall(r'\b\w{5,}\b', f2.get("headline", ""))}
            if not words1 & words2:
                continue

            processed_pairs.add(pair_key)
            conflicts.append({
                "finding_1": f1,
                "finding_2": f2,
                "ratio": round(ratio, 1),
                "domain": f1.get("domain"),
            })

    if not conflicts:
        findings["_reconciliation"] = {
            "ran": True,
            "conflicts_found": 0,
            "notes": [],
            "message": f"No numeric conflicts found among {len(all_findings)} findings (threshold: {CONFLICT_THRESHOLD}x).",
        }
        return findings

    # ── Invoke Haiku arbiter for each conflict ──
    reconciliation_notes: list[dict] = []

    baseline_summary = {
        k: v for k, v in baseline.items()
        if not k.startswith("_") and v is not None
    }

    for conflict in conflicts:
        f1 = conflict["finding_1"]
        f2 = conflict["finding_2"]

        arbiter_prompt = f"""
Two analysis agents disagree on the same metric by {conflict['ratio']}x.
Your job: select the more defensible value and explain the discrepancy in one sentence.

FROZEN BASELINE (measured from database — ground truth):
{json.dumps(baseline_summary, indent=2, default=str)}

FINDING 1 (from {f1['_agent']}):
  headline: {f1.get('headline')}
  value_eur: {f1.get('value_eur')}
  evidence: {f1.get('evidence', 'not provided')}
  value_confidence: {f1.get('value_confidence', 'unknown')}

FINDING 2 (from {f2['_agent']}):
  headline: {f2.get('headline')}
  value_eur: {f2.get('value_eur')}
  evidence: {f2.get('evidence', 'not provided')}
  value_confidence: {f2.get('value_confidence', 'unknown')}

Respond with valid JSON only:
{{
  "selected_value": <number>,
  "selected_agent": "<agent name>",
  "discrepancy_explanation": "<one sentence: why they differ>",
  "confidence": "high|medium|low"
}}
"""

        arbiter_options = ClaudeAgentOptions(model="haiku", max_turns=3)
        arbiter_output = []

        try:
            async for msg in agent_query(prompt=arbiter_prompt, options=arbiter_options):
                if hasattr(msg, "content"):
                    for block in msg.content:
                        if hasattr(block, "text"):
                            arbiter_output.append(block.text)
        except Exception as e:
            arbiter_output = [f'{{"error": "{e}"}}']

        raw_response = "\n".join(arbiter_output)
        arbitration: dict = {}
        try:
            json_match = re.search(r'\{[\s\S]*\}', raw_response)
            if json_match:
                arbitration = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            arbitration = {"error": "Could not parse arbiter response", "raw": raw_response[:200]}

        reconciliation_notes.append({
            "finding_ids": [f1.get("id"), f2.get("id")],
            "agents": [f1["_agent"], f2["_agent"]],
            "domain": conflict["domain"],
            "ratio": conflict["ratio"],
            "values": {f1["_agent"]: f1["value_eur"], f2["_agent"]: f2["value_eur"]},
            "arbitration": arbitration,
        })

    findings["_reconciliation"] = {
        "ran": True,
        "conflicts_found": len(conflicts),
        "notes": reconciliation_notes,
        "message": (
            f"Resolved {len(reconciliation_notes)} conflict(s) across "
            f"{len(all_findings)} findings."
        ),
    }

    return findings
