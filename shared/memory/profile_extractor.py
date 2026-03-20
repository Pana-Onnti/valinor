"""
ProfileExtractor — updates a ClientProfile from a completed run's results.

Called after each run completes. Extracts:
- Finding deltas (new / persisted / resolved)
- KPI time series
- Table signal weights
- Preferred queries
"""
from __future__ import annotations
import re
from typing import Dict, List, Any, Optional
from datetime import datetime

import structlog

from .client_profile import ClientProfile, FindingRecord, KPIDataPoint

logger = structlog.get_logger()


class ProfileExtractor:
    """Stateless helper — call update_from_run() after each completed run."""

    def update_from_run(
        self,
        profile: ClientProfile,
        findings: Dict[str, Any],
        entity_map: Dict[str, Any],
        reports: Dict[str, str],
        period: str,
        run_success: bool = True,
    ) -> Dict[str, List[str]]:
        """
        Update profile in-place from a completed run.

        Returns delta dict:
        {
            "new":      [finding_id, ...],
            "persists": [finding_id, ...],
            "resolved": [finding_id, ...],
            "worsened": [finding_id, ...],
            "improved": [finding_id, ...]
        }
        """
        now = datetime.utcnow().isoformat()
        delta: Dict[str, List[str]] = {
            "new": [], "persists": [], "resolved": [], "worsened": [], "improved": []
        }

        # 1. Extract all finding IDs seen in this run
        current_finding_ids: set[str] = set()
        all_findings: List[Dict] = []

        for agent_name, agent_result in findings.items():
            if not isinstance(agent_result, dict):
                continue
            for f in agent_result.get("findings", []):
                fid = f.get("id") or f.get("finding_id", "")
                if fid:
                    current_finding_ids.add(fid)
                    all_findings.append({**f, "_agent": agent_name})

        # 2. Compute deltas vs known_findings
        previously_known = set(profile.known_findings.keys())

        for fid in current_finding_ids:
            finding_data = next((f for f in all_findings if (f.get("id") or f.get("finding_id", "")) == fid), {})
            severity = finding_data.get("severity", "").upper()
            title = finding_data.get("title", fid)
            agent = finding_data.get("_agent", "unknown")

            if fid not in previously_known:
                # Brand new finding
                delta["new"].append(fid)
                profile.known_findings[fid] = {
                    "id": fid,
                    "title": title,
                    "severity": severity,
                    "agent": agent,
                    "first_seen": now,
                    "last_seen": now,
                    "runs_open": 1,
                }
            else:
                # Previously known — update
                rec = profile.known_findings[fid]
                old_severity = rec.get("severity", "")
                new_severity = severity

                rec["last_seen"] = now
                rec["runs_open"] = rec.get("runs_open", 0) + 1

                sev_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
                if sev_rank.get(new_severity, 0) > sev_rank.get(old_severity, 0):
                    delta["worsened"].append(fid)
                    rec["severity"] = new_severity
                elif sev_rank.get(new_severity, 0) < sev_rank.get(old_severity, 0):
                    delta["improved"].append(fid)
                    rec["severity"] = new_severity
                else:
                    delta["persists"].append(fid)

                profile.known_findings[fid] = rec

                # Remove from resolved if it reappeared
                profile.resolved_findings.pop(fid, None)

        # 3. Mark vanished findings as resolved
        for fid in previously_known - current_finding_ids:
            rec = profile.known_findings.pop(fid, None)
            if rec:
                rec["resolved_at"] = now
                profile.resolved_findings[fid] = rec
                delta["resolved"].append(fid)

        # 4. Update table weights based on finding density
        table_finding_count: Dict[str, int] = {}
        for entity_name, entity_data in entity_map.get("entities", {}).items():
            table_name = entity_data.get("table", entity_name)
            count = sum(
                1 for f in all_findings
                if table_name in str(f.get("sql", "")) or entity_name in str(f.get("title", ""))
            )
            if count > 0:
                table_finding_count[table_name] = count

        # Normalize to [0.1 .. 1.0]
        if table_finding_count:
            max_count = max(table_finding_count.values())
            for tbl, cnt in table_finding_count.items():
                weight = 0.1 + 0.9 * (cnt / max_count)
                profile.table_weights[tbl] = round(weight, 2)
            profile.focus_tables = sorted(
                table_finding_count.keys(), key=lambda t: table_finding_count[t], reverse=True
            )[:10]

        # 5. Extract KPIs from report text for baseline_history
        exec_report = reports.get("executive", "")
        if exec_report:
            kpis = self._extract_kpis_from_report(exec_report)
            for kpi in kpis:
                key = kpi["label"]
                if key not in profile.baseline_history:
                    profile.baseline_history[key] = []
                # Avoid duplicates for same period
                existing_periods = {dp.get("period") for dp in profile.baseline_history[key]}
                if period not in existing_periods:
                    profile.baseline_history[key].append({
                        "period": period,
                        "label": kpi["label"],
                        "value": kpi["value"],
                        "numeric_value": kpi.get("numeric_value"),
                        "run_date": now,
                    })
                # Keep only last 24 data points per KPI
                profile.baseline_history[key] = profile.baseline_history[key][-24:]

        # 6. Update run stats
        profile.run_count += 1
        profile.last_run_date = now
        profile.run_history.append({
            "run_date": now,
            "period": period,
            "success": run_success,
            "findings_count": len(current_finding_ids),
            "new": len(delta["new"]),
            "resolved": len(delta["resolved"]),
        })
        profile.run_history = profile.run_history[-20:]  # keep last 20
        self._auto_escalate_persistent(profile)

        logger.info(
            "ProfileExtractor.update_from_run",
            client=profile.client_name,
            new=len(delta["new"]),
            persists=len(delta["persists"]),
            resolved=len(delta["resolved"]),
        )
        return delta

    def _auto_escalate_persistent(self, profile: "ClientProfile") -> List[str]:
        """
        Auto-escalate severity for findings open 5+ consecutive runs.
        Returns list of escalated finding IDs.
        """
        escalated = []
        sev_rank = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

        for fid, rec in profile.known_findings.items():
            if rec.get("runs_open", 0) >= 5:
                current_sev = rec.get("severity", "LOW").upper()
                if current_sev in sev_rank:
                    idx = sev_rank.index(current_sev)
                    if idx < len(sev_rank) - 1:
                        new_sev = sev_rank[idx + 1]
                        rec["severity"] = new_sev
                        rec["auto_escalated"] = True
                        escalated.append(fid)
                        logger.info(
                            "Finding auto-escalated",
                            finding=fid,
                            from_sev=current_sev,
                            to_sev=new_sev,
                            runs_open=rec.get("runs_open"),
                        )
        return escalated

    def _extract_kpis_from_report(self, report_text: str) -> List[Dict]:
        """
        Extract KPI label-value pairs from report markdown.
        Looks for patterns like:
          - **Facturacion Total**: $12.3M
          - **Cobranza Pendiente**: ARS 4.5M (32%)
        """
        kpis = []
        # Match markdown bold key: value lines
        pattern = re.compile(
            r'\*\*([^*]{5,60}?)\*\*\s*[:–-]\s*([^\n]{1,80})',
            re.MULTILINE
        )
        for m in pattern.finditer(report_text):
            label = m.group(1).strip()
            value = m.group(2).strip()
            # Try to extract a numeric value
            nums = re.findall(r'[\d.,]+', value.replace(',', ''))
            numeric_value = None
            if nums:
                try:
                    numeric_value = float(nums[0].replace(',', ''))
                except ValueError:
                    pass
            kpis.append({"label": label, "value": value, "numeric_value": numeric_value})
        return kpis[:20]  # cap at 20 KPIs


# Module singleton
_extractor: Optional[ProfileExtractor] = None

def get_profile_extractor() -> ProfileExtractor:
    global _extractor
    if _extractor is None:
        _extractor = ProfileExtractor()
    return _extractor
