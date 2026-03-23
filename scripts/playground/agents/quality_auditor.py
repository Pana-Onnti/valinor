"""
Playground Swarm — Agent 10: Quality Auditor.

Continuous agent that reads smoke reports, fetches job results from the
API, runs quality checks, and produces audit reports with a quality score.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

import aiohttp

from scripts.playground.agents.base import (
    AgentResult,
    PlaygroundAgent,
    PlaygroundContext,
)


class QualityAuditorAgent(PlaygroundAgent):
    """Audits completed pipeline jobs for quality and correctness."""

    name = "quality_auditor"
    tier = "tester"
    interval = 60

    def __init__(self) -> None:
        super().__init__()
        self._audited_jobs: Set[str] = set()
        self._total_audited = 0
        self._quality_scores: List[float] = []
        self._failures = 0

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        errors: List[str] = []

        # Gather smoke reports
        smoke_reports = self._load_smoke_reports(ctx.reports_dir)
        if not smoke_reports:
            self.logger.info("No smoke reports found — nothing to audit.")
            return AgentResult(self.name, success=True, stats=self._stats())

        # Filter to un-audited completed jobs
        to_audit = [
            r for r in smoke_reports
            if r.get("job_id")
            and r["job_id"] not in self._audited_jobs
            and r.get("status") in ("completed", "failed")
        ]

        if not to_audit:
            self.logger.info("No new jobs to audit.")
            return AgentResult(self.name, success=True, stats=self._stats())

        async with aiohttp.ClientSession() as session:
            for report in to_audit:
                job_id = report["job_id"]
                dataset_name = report.get("dataset_name", "unknown")

                try:
                    audit = await self._audit_job(session, ctx, report)
                    self._save_report(ctx, audit, "audit")
                    self._audited_jobs.add(job_id)
                    self._total_audited += 1
                    score = audit["quality_score"]
                    self._quality_scores.append(score)
                    if score < 100.0:
                        self._failures += 1

                    self.logger.info(
                        "Audited job %s (%s): quality=%.0f%%",
                        job_id, dataset_name, score,
                    )
                except Exception as exc:
                    msg = f"Error auditing job {job_id}: {exc}"
                    self.logger.error(msg)
                    errors.append(msg)

        avg_q = (
            sum(self._quality_scores) / len(self._quality_scores)
            if self._quality_scores
            else 0.0
        )
        self.logger.info(
            "Audited %d jobs, avg quality: %.1f%%", len(to_audit), avg_q
        )

        return AgentResult(
            self.name,
            success=len(errors) == 0,
            errors=errors,
            stats=self._stats(),
        )

    # ── core audit logic ──────────────────────────────────────────────

    async def _audit_job(
        self,
        session: aiohttp.ClientSession,
        ctx: PlaygroundContext,
        smoke_report: Dict[str, Any],
    ) -> Dict[str, Any]:
        job_id = smoke_report["job_id"]
        dataset_name = smoke_report.get("dataset_name", "unknown")
        status = smoke_report.get("status", "unknown")
        exec_time = smoke_report.get("execution_time", 0)

        # Fetch results from API
        results_data: Dict[str, Any] = {}
        if status == "completed":
            try:
                url = f"{ctx.api_base_url}/api/jobs/{job_id}/results"
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    results_data = await resp.json()
            except Exception as exc:
                self.logger.warning("Could not fetch results for %s: %s", job_id, exc)

        # Run quality checks
        checks: Dict[str, bool] = {}

        # 1. findings_exist — check if any agent produced non-empty output
        findings = results_data.get("findings", {})
        has_any_output = False
        if isinstance(findings, dict):
            for agent_name, agent_data in findings.items():
                if isinstance(agent_data, dict):
                    output = agent_data.get("output", "")
                    if output and len(str(output)) > 10:
                        has_any_output = True
                        break
                    # Also check for findings list format
                    agent_findings = agent_data.get("findings", [])
                    if agent_findings and len(agent_findings) > 0:
                        has_any_output = True
                        break
        checks["findings_exist"] = has_any_output

        # 2. no_zero_revenue
        revenue_ok = True
        if findings:
            for key, value in findings.items():
                if "revenue" in key.lower():
                    try:
                        if float(value) <= 0:
                            revenue_ok = False
                    except (TypeError, ValueError):
                        pass
        checks["no_zero_revenue"] = revenue_ok

        # 3. dq_gate_ran — check both results["data_quality"] and results["stages"]
        dq_data = results_data.get("data_quality")
        if dq_data and isinstance(dq_data, dict) and dq_data.get("score") is not None:
            checks["dq_gate_ran"] = True
        else:
            stages = results_data.get("stages", [])
            if isinstance(stages, dict):
                stages = list(stages.keys())
            checks["dq_gate_ran"] = any(
                "data_quality" in str(s).lower() or "dq" in str(s).lower()
                for s in stages
            )

        # 4. reasonable_execution_time
        checks["reasonable_execution_time"] = exec_time < 300

        # 5. no_crash
        checks["no_crash"] = status == "completed"

        # Score
        total_checks = len(checks)
        passed_checks = sum(1 for v in checks.values() if v)
        quality_score = (passed_checks / total_checks * 100) if total_checks > 0 else 0.0

        return {
            "dataset_name": dataset_name,
            "job_id": job_id,
            "quality_score": round(quality_score, 1),
            "checks_detail": checks,
            "timestamp": datetime.utcnow().isoformat(),
            "status": status,
            "execution_time": exec_time,
        }

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _load_smoke_reports(reports_dir: Path) -> List[Dict[str, Any]]:
        """Load all smoke_*.json reports from the reports directory."""
        reports: List[Dict[str, Any]] = []
        if not reports_dir.exists():
            return reports
        for path in sorted(reports_dir.glob("smoke_*.json")):
            try:
                data = json.loads(path.read_text())
                reports.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        return reports

    def _stats(self) -> Dict[str, Any]:
        avg = (
            sum(self._quality_scores) / len(self._quality_scores)
            if self._quality_scores
            else 0.0
        )
        return {
            "total_audited": self._total_audited,
            "avg_quality_score": round(avg, 1),
            "failures": self._failures,
        }
