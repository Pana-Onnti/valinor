"""
Deliver — Stage 5: Output generation.

Saves reports as markdown, entity_map and run_log as JSON,
and builds the updated swarm memory for future runs.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


async def deliver_reports(
    reports: dict[str, str],
    entity_map: dict,
    findings: dict,
    run_log: dict,
    output_dir: Path,
    query_results: dict | None = None,
) -> dict[str, str]:
    """
    Save all output artifacts to the output directory.

    Args:
        reports: Dict mapping report name to markdown content.
        entity_map: Complete entity map from Stage 1.
        findings: Raw findings from Stage 3 agents.
        run_log: Execution metadata (timings, counts, etc.).
        output_dir: Target directory for output files.
        query_results: Optional query results to save alongside findings.

    Returns:
        Dict mapping artifact name to file path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {}

    # Save reports as markdown
    for name, content in reports.items():
        path = output_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        artifacts[name] = str(path)

    # Save entity map
    entity_path = output_dir / "entity_map.json"
    entity_path.write_text(
        json.dumps(entity_map, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    artifacts["entity_map"] = str(entity_path)

    # Save run log
    run_log["completed_at"] = datetime.now().isoformat()
    run_log["output_dir"] = str(output_dir)
    run_log["artifacts"] = artifacts

    log_path = output_dir / "run_log.json"
    log_path.write_text(
        json.dumps(run_log, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    artifacts["run_log"] = str(log_path)

    # Save raw findings for debugging
    findings_path = output_dir / "raw_findings.json"
    findings_path.write_text(
        json.dumps(findings, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    artifacts["raw_findings"] = str(findings_path)

    # Save query results if provided (enables post-hoc verification)
    if query_results:
        queries_path = output_dir / "query_results.json"
        queries_path.write_text(
            json.dumps(query_results, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        artifacts["query_results"] = str(queries_path)

    return artifacts


def _extract_findings(agent_data: dict) -> list[dict]:
    """
    Parse structured findings from agent output.

    Tries to extract the JSON array of findings from the agent's text output.
    Falls back to counting finding IDs (FIN-001, DQ-001, HUNT-001) if JSON
    parsing fails.

    Returns list of finding dicts (may be empty).
    """
    # If agent already parsed findings as a list
    if isinstance(agent_data.get("findings"), list):
        return agent_data["findings"]

    output = agent_data.get("output", "")
    if not isinstance(output, str) or not output.strip():
        return []

    # Try to parse JSON arrays from the output text
    # Agents wrap findings in a JSON array — extract it
    json_arrays = re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', output)
    for candidate in json_arrays:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                # Validate it looks like findings (has id or headline)
                if any("id" in item or "headline" in item for item in parsed[:2]):
                    return parsed
        except (json.JSONDecodeError, ValueError):
            continue

    # Fallback: count unique finding IDs as proxy
    ids = list(set(re.findall(r'"id"\s*:\s*"([A-Z]+-\d{3})"', output)))
    return [{"id": fid} for fid in ids]


def build_memory(
    entity_map: dict,
    findings: dict,
    run_log: dict,
    previous_memory: dict | None,
    baseline: dict | None = None,
) -> dict[str, Any]:
    """
    Build the swarm memory for this run.

    Memory captures key findings and metrics so future runs can
    compare and track changes over time.

    Args:
        entity_map: Entity map from this run.
        findings: Agent findings from this run.
        run_log: Execution log.
        previous_memory: Previous run's memory (or None).
        baseline: Revenue baseline from this run (optional).

    Returns:
        New memory dict to persist.
    """
    memory: dict[str, Any] = {
        "run_timestamp": datetime.now().isoformat(),
        "previous_run": None,
    }

    # Capture entity summary
    memory["entity_summary"] = {
        name: {
            "table": entity.get("table"),
            "row_count": entity.get("row_count"),
            "confidence": entity.get("confidence"),
        }
        for name, entity in entity_map.get("entities", {}).items()
    }

    # Capture and count actual distinct findings (not headline lines)
    all_findings: list[dict] = []
    agent_counts: dict[str, int] = {}

    for agent_name, agent_data in findings.items():
        if isinstance(agent_data, dict) and not agent_data.get("error"):
            agent_findings = _extract_findings(agent_data)
            all_findings.extend(agent_findings)
            agent_counts[agent_name] = len(agent_findings)

    memory["findings_by_agent"] = agent_counts
    memory["total_distinct_findings"] = len(all_findings)

    # Store finding headlines for quick scanning in future runs
    memory["finding_headlines"] = [
        {
            "id": f.get("id", "?"),
            "severity": f.get("severity", "?"),
            "headline": f.get("headline", "")[:200],
        }
        for f in all_findings
        if f.get("headline") or f.get("id")
    ]

    # Store baseline metrics for trend comparison across runs
    if baseline:
        memory["baseline"] = {
            "total_revenue": baseline.get("total_revenue"),
            "num_invoices": baseline.get("num_invoices"),
            "avg_invoice": baseline.get("avg_invoice"),
            "distinct_customers": baseline.get("distinct_customers"),
            "total_outstanding_ar": baseline.get("total_outstanding_ar"),
            "data_freshness_days": baseline.get("data_freshness_days"),
            "date_from": baseline.get("date_from"),
            "date_to": baseline.get("date_to"),
        }

    # Capture run metrics
    memory["run_metrics"] = {
        "stages": run_log.get("stages", {}),
        "total_distinct_findings": memory["total_distinct_findings"],
        "findings_by_agent": agent_counts,
    }

    # Link to previous memory
    if previous_memory:
        memory["previous_run"] = {
            "timestamp": previous_memory.get("run_timestamp"),
            "total_findings": previous_memory.get("total_distinct_findings")
                              or previous_memory.get("run_metrics", {}).get("total_findings", 0),
            "baseline": previous_memory.get("baseline"),
        }

    return memory
