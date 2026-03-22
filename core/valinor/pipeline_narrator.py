"""
Pipeline Narrator — Verification-aware finding preparation and narrator orchestration.

Extracted from pipeline.py for better modularity.

Contains:
  - prepare_narrator_context   Stage 3.75: pre-filter findings by verification status
  - run_narrators              Stage 4: audience-specific reports (parallelized)
"""

import asyncio
from typing import Any

import structlog

from valinor.pipeline_reconciliation import _parse_findings_from_output

_narrator_logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# STAGE 3.75 — VERIFICATION-AWARE FINDING PREPARATION
# ═══════════════════════════════════════════════════════════════


def prepare_narrator_context(
    findings: dict,
    verification_report: Any = None,
    role: str = "executive",
) -> dict:
    """
    Pre-filter and tag findings based on verification status.

    Different narrator roles see different subsets:
      - ceo: only VERIFIED findings (high confidence only)
      - controller: all findings with explicit confidence tags
      - sales: VERIFIED + UNVERIFIABLE (no FAILED)
      - executive: all findings with full detail

    FAILED findings are retracted with explanation in all roles except executive.

    Returns a dict with:
      - verified_findings: list of findings that passed verification
      - unverifiable_findings: list of findings with no verification data
      - retracted_findings: list of findings that failed verification
      - summary: human-readable summary of verification state
    """
    if not verification_report:
        # No verification — pass everything through untagged
        return {
            "verified_findings": findings,
            "unverifiable_findings": {},
            "retracted_findings": [],
            "summary": "No verification report available — all findings unverified.",
        }

    # Build a map of claim_id -> verification status
    claim_statuses: dict[str, str] = {}
    claim_details: dict[str, str] = {}
    for result in getattr(verification_report, "results", []):
        claim_statuses[result.claim_id] = result.status
        claim_details[result.claim_id] = result.evidence

    # Classify each agent's findings
    verified: dict[str, Any] = {}
    unverifiable: dict[str, Any] = {}
    retracted: list[dict] = []

    for agent_name, agent_data in findings.items():
        if agent_name.startswith("_") or not isinstance(agent_data, dict):
            # Preserve metadata like _reconciliation
            verified[agent_name] = agent_data
            continue

        if agent_data.get("error"):
            continue

        agent_findings = _parse_findings_from_output(agent_data)
        verified_list = []
        unverifiable_list = []

        for finding in agent_findings:
            finding_id = finding.get("id", "")
            # Check if any claim from this finding was FAILED
            has_failed = any(
                status == "FAILED"
                for cid, status in claim_statuses.items()
                if cid.startswith(finding_id)
            )
            has_verified = any(
                status in ("VERIFIED", "APPROXIMATE")
                for cid, status in claim_statuses.items()
                if cid.startswith(finding_id)
            )

            if has_failed:
                # Collect retraction details
                failed_evidence = [
                    claim_details.get(cid, "")
                    for cid, status in claim_statuses.items()
                    if cid.startswith(finding_id) and status == "FAILED"
                ]
                retracted.append({
                    "finding_id": finding_id,
                    "agent": agent_name,
                    "original_headline": finding.get("headline", ""),
                    "original_value": finding.get("value_eur"),
                    "retraction_reason": "; ".join(failed_evidence[:2]),
                })
            elif has_verified:
                finding["_verification_tag"] = "VERIFIED"
                verified_list.append(finding)
            else:
                finding["_verification_tag"] = "UNVERIFIABLE"
                unverifiable_list.append(finding)

        if verified_list:
            verified[agent_name] = {**agent_data, "findings": verified_list}
        if unverifiable_list:
            unverifiable[agent_name] = {**agent_data, "findings": unverifiable_list}

    # Role-based filtering
    if role == "ceo":
        # CEO only sees verified findings
        filtered_findings = verified
        filtered_unverifiable = {}
    elif role == "sales":
        # Sales sees verified + unverifiable (no FAILED details)
        filtered_findings = {**verified, **unverifiable}
        filtered_unverifiable = {}
        retracted = []  # Hide retractions from sales
    elif role == "controller":
        # Controller sees everything
        filtered_findings = {**verified, **unverifiable}
        filtered_unverifiable = unverifiable
    else:
        # Executive sees everything with full retraction details
        filtered_findings = {**verified, **unverifiable}
        filtered_unverifiable = unverifiable

    # Build summary
    n_verified = sum(
        len(d.get("findings", [])) for d in verified.values()
        if isinstance(d, dict) and "findings" in d
    )
    n_unverifiable = sum(
        len(d.get("findings", [])) for d in unverifiable.values()
        if isinstance(d, dict) and "findings" in d
    )
    n_retracted = len(retracted)

    summary_parts = []
    if n_verified:
        summary_parts.append(f"{n_verified} verified findings")
    if n_unverifiable:
        summary_parts.append(f"{n_unverifiable} unverifiable findings")
    if n_retracted:
        summary_parts.append(f"{n_retracted} retracted findings (contradicted by data)")
    summary = ". ".join(summary_parts) + "." if summary_parts else "No findings to report."

    return {
        "verified_findings": filtered_findings,
        "unverifiable_findings": filtered_unverifiable,
        "retracted_findings": retracted,
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════════
# STAGE 4 — NARRATORS
# ═══════════════════════════════════════════════════════════════

async def run_narrators(
    findings: dict,
    entity_map: dict,
    memory: dict | None,
    client_config: dict,
    baseline: dict,
    query_results: dict,
    verification_report: Any = None,
    narrator_timeout: int = 60,
) -> dict[str, str]:
    """
    Run all four narrator agents in parallel to produce audience-specific reports.

    Each narrator runs as an independent asyncio task with a configurable timeout
    (default: 60s). If a narrator fails or times out, the others continue
    producing their reports (graceful degradation).

    Args:
        findings: swarm output including _reconciliation notes
        entity_map: schema map from Cartographer
        memory: previous analysis memory (or None)
        client_config: client configuration dict
        baseline: frozen brief with provenance
        query_results: raw rows for customer lists / AR tables
        verification_report: optional VerificationReport with Number Registry
        narrator_timeout: max seconds per narrator (default: 60)

    Returns:
        Dict mapping report name to markdown string.
    """
    from valinor.agents.narrators.ceo        import narrate_ceo
    from valinor.agents.narrators.controller import narrate_controller
    from valinor.agents.narrators.sales      import narrate_sales
    from valinor.agents.narrators.executive  import narrate_executive

    # Map narrator roles to their preparation context
    narrator_roles = {
        "briefing_ceo": "ceo",
        "reporte_controller": "controller",
        "reporte_ventas": "sales",
        "reporte_ejecutivo": "executive",
    }

    narrator_specs = [
        ("briefing_ceo",       narrate_ceo,        {"verification_report": verification_report}),
        ("reporte_controller", narrate_controller, {"query_results": query_results, "verification_report": verification_report}),
        ("reporte_ventas",     narrate_sales,      {"query_results": query_results, "verification_report": verification_report}),
        ("reporte_ejecutivo",  narrate_executive,  {"verification_report": verification_report}),
    ]

    async def _run_single_narrator(name: str, fn, extra_kwargs: dict) -> tuple[str, str]:
        """Run a single narrator with timeout and error handling."""
        try:
            role = narrator_roles.get(name, "executive")
            narrator_ctx = prepare_narrator_context(
                findings, verification_report, role=role,
            )
            role_findings = narrator_ctx["verified_findings"]

            extra_kwargs["_verification_summary"] = narrator_ctx["summary"]
            extra_kwargs["_retracted_findings"] = narrator_ctx["retracted_findings"]

            result = await asyncio.wait_for(
                fn(role_findings, entity_map, memory, client_config, baseline, **extra_kwargs),
                timeout=narrator_timeout,
            )
            _narrator_logger.info("Narrator completed", narrator=name)
            return (name, result)
        except asyncio.TimeoutError:
            _narrator_logger.warning(
                "Narrator timed out",
                narrator=name,
                timeout_seconds=narrator_timeout,
            )
            return (name, f"# {name}\n\n*Narrator timed out after {narrator_timeout}s.*")
        except Exception as e:
            _narrator_logger.error(
                "Narrator failed",
                narrator=name,
                error=str(e),
            )
            return (name, f"# Error generating {name}\n\n{e}")

    # Run all narrators in parallel with asyncio.gather
    tasks = [
        _run_single_narrator(name, fn, dict(extra_kwargs))
        for name, fn, extra_kwargs in narrator_specs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    reports: dict[str, str] = {}
    for name, report in results:
        reports[name] = report

    return reports
