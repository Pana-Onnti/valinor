"""
Clients router — Client profile, findings, costs, analytics endpoints.

Extracted from main.py for better modularity.
"""

import os
import sys
import glob as _glob
import json as _json
import re as _re
from typing import Optional
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, HTTPException

import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/api", tags=["Clients"])


def _validate_client_name(name: str) -> str:
    if not name or len(name) > 100:
        raise ValueError("client_name must be 1-100 characters")
    if not _re.match(r'^[a-zA-Z0-9_\-\.]+$', name):
        raise ValueError("client_name may only contain alphanumeric characters, underscore, hyphen, dot")
    return name


def _ensure_shared_path():
    """Ensure shared modules are on sys.path."""
    shared_parent = os.path.join(os.path.dirname(__file__), '..', '..')
    if shared_parent not in sys.path:
        sys.path.insert(0, shared_parent)


# ── Client Profile endpoints ──────────────────────────────────────────────────

@router.get("/clients/{client_name}/profile", tags=["Clients"])
async def get_client_profile(client_name: str):
    """Get the persistent ClientProfile for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")
    return profile.to_dict()


@router.get("/clients/{client_name}/profile/export", tags=["Clients"])
async def export_client_profile(client_name: str):
    """Export the full ClientProfile as a downloadable JSON file."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    from fastapi.responses import Response

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    payload = _json.dumps(profile.to_dict(), indent=2, ensure_ascii=False)
    filename = f"{client_name}_profile.json"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/clients/{client_name}/profile/import", tags=["Clients"])
async def import_client_profile(client_name: str, body: dict):
    """Import (overwrite) a ClientProfile from a JSON body."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    from shared.memory.client_profile import ClientProfile

    if body.get("client_name") != client_name:
        raise HTTPException(
            status_code=400,
            detail=f"client_name in body ('{body.get('client_name')}') does not match URL parameter ('{client_name}')",
        )

    store = get_profile_store()
    try:
        profile = ClientProfile.from_dict(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid profile data: {exc}")

    await store.save(profile)
    return {"status": "imported", "client": client_name}


@router.get("/clients/{client_name}/refinement", tags=["Clients"])
async def get_client_refinement(client_name: str):
    """Return the current refinement settings stored in the ClientProfile."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    return {
        "client_name": client_name,
        "refinement": profile.refinement or {},
    }


@router.patch("/clients/{client_name}/refinement", tags=["Clients"])
async def patch_client_refinement(client_name: str, body: dict):
    """Merge a partial refinement dict into the existing refinement settings."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    current = profile.refinement or {}
    current.update(body)
    profile.refinement = current

    profile.updated_at = datetime.utcnow().isoformat()

    await store.save(profile)
    return {
        "client_name": client_name,
        "refinement": profile.refinement,
    }


@router.get("/clients", tags=["Clients"])
async def list_clients():
    """List all clients that have profiles."""
    profile_dir = "/tmp/valinor_profiles"
    os.makedirs(profile_dir, exist_ok=True)

    clients = []
    for path in _glob.glob(os.path.join(profile_dir, "*.json")):
        try:
            data = _json.loads(open(path).read())
            clients.append({
                "client_name": data.get("client_name"),
                "run_count": data.get("run_count", 0),
                "last_run_date": data.get("last_run_date"),
                "known_findings_count": len(data.get("known_findings", {})),
            })
        except Exception:
            pass

    return {"clients": clients}


@router.get("/clients/summary", tags=["Clients"])
async def get_clients_summary():
    """Aggregated summary of all clients for operator dashboard."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    all_profiles_data = []

    try:
        pool = await store._get_pool()
        if pool:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT profile FROM client_profiles")
                for row in rows:
                    try:
                        all_profiles_data.append(_json.loads(row["profile"]))
                    except Exception:
                        pass
        else:
            raise Exception("no pool")
    except Exception:
        profile_dir = "/tmp/valinor_profiles"
        os.makedirs(profile_dir, exist_ok=True)
        for path in _glob.glob(os.path.join(profile_dir, "*.json")):
            try:
                all_profiles_data.append(_json.loads(open(path).read()))
            except Exception:
                pass

    total_critical = sum(
        sum(1 for f in p.get("known_findings", {}).values() if isinstance(f, dict) and f.get("severity") == "CRITICAL")
        for p in all_profiles_data
    )

    dq_scores = [
        e["score"]
        for p in all_profiles_data
        for e in (p.get("dq_history") or [])
        if isinstance(e, dict) and "score" in e
    ]
    avg_dq = round(sum(dq_scores) / len(dq_scores), 1) if dq_scores else None

    return {
        "total_clients": len(all_profiles_data),
        "total_critical_findings": total_critical,
        "avg_dq_score": avg_dq,
        "total_runs": sum(p.get("run_count", 0) for p in all_profiles_data),
        "clients_with_criticals": sum(
            1 for p in all_profiles_data
            if any(
                isinstance(f, dict) and f.get("severity") == "CRITICAL"
                for f in p.get("known_findings", {}).values()
            )
        ),
    }


@router.get("/clients/comparison", tags=["Clients"])
async def get_clients_comparison(clients: Optional[str] = None):
    """Compare DQ scores and trends across multiple clients."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()

    if clients:
        requested_names = [c.strip() for c in clients.split(",") if c.strip()]
    else:
        requested_names = None

    all_profiles_data: list = []
    try:
        pool = await store._get_pool()
        if pool:
            async with pool.acquire() as conn:
                if requested_names:
                    rows = await conn.fetch(
                        "SELECT profile FROM client_profiles WHERE client_name = ANY($1)",
                        requested_names,
                    )
                else:
                    rows = await conn.fetch("SELECT profile FROM client_profiles")
                for row in rows:
                    try:
                        all_profiles_data.append(_json.loads(row["profile"]))
                    except Exception:
                        pass
        else:
            raise Exception("no pool")
    except Exception:
        profile_dir = "/tmp/valinor_profiles"
        os.makedirs(profile_dir, exist_ok=True)
        for path in _glob.glob(os.path.join(profile_dir, "*.json")):
            try:
                data = _json.loads(open(path).read())
                if requested_names is None or data.get("client_name") in requested_names:
                    all_profiles_data.append(data)
            except Exception:
                pass

    def _compute_trend(dq_history: list) -> str:
        scores = [e["score"] for e in dq_history if isinstance(e, dict) and "score" in e]
        if len(scores) < 2:
            return "stable"
        first_window = scores[:3]
        last_window = scores[-3:]
        avg_first = sum(first_window) / len(first_window)
        avg_last = sum(last_window) / len(last_window)
        diff = avg_last - avg_first
        if diff > 2:
            return "improving"
        elif diff < -2:
            return "degrading"
        return "stable"

    result_clients = []
    for p in all_profiles_data:
        dq_history = p.get("dq_history") or []
        scores = [e["score"] for e in dq_history if isinstance(e, dict) and "score" in e]
        avg_dq = round(sum(scores) / len(scores), 1) if scores else None

        known_findings = p.get("known_findings") or {}
        critical_count = sum(
            1 for f in known_findings.values()
            if isinstance(f, dict) and f.get("severity") == "CRITICAL"
        )

        last_run = None
        if dq_history:
            last_entry = dq_history[-1]
            if isinstance(last_entry, dict):
                last_run = last_entry.get("timestamp") or last_entry.get("date")
        if not last_run:
            last_run = p.get("last_run_date")

        result_clients.append({
            "name": p.get("client_name"),
            "run_count": p.get("run_count", 0),
            "avg_dq_score": avg_dq,
            "dq_trend": _compute_trend(dq_history),
            "critical_findings": critical_count,
            "last_run": last_run,
            "industry": p.get("industry"),
        })

    result_clients.sort(
        key=lambda c: c["avg_dq_score"] if c["avg_dq_score"] is not None else -1,
        reverse=True,
    )

    return {
        "clients": result_clients,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/clients/{client_name}/findings", tags=["Clients"])
async def get_client_findings(client_name: str, severity_filter: Optional[str] = None):
    """Return all active findings for a client with full details."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    severity_filter_upper: Optional[str] = severity_filter.upper() if severity_filter else None

    store = get_profile_store()
    profile = await store.load(client_name)

    if profile is None:
        raise HTTPException(status_code=404, detail=f"Client '{client_name}' not found")

    known_findings: dict = profile.known_findings or {}
    findings_list = []
    resolved_count = 0
    severity_counts: dict = {}

    for finding_id, record in known_findings.items():
        if not isinstance(record, dict):
            continue
        finding_status = record.get("status", "open")
        if finding_status == "resolved":
            resolved_count += 1
            continue

        severity = record.get("severity", "UNKNOWN")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

        if severity_filter_upper and severity != severity_filter_upper:
            continue

        findings_list.append({
            "id": finding_id,
            "title": record.get("title") or record.get("description") or finding_id,
            "severity": severity,
            "agent": record.get("agent") or record.get("source_agent"),
            "first_seen": record.get("first_seen"),
            "last_seen": record.get("last_seen"),
            "runs_open": record.get("runs_open", 0),
        })

    _sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}
    findings_list.sort(key=lambda f: _sev_order.get(f["severity"], 99))

    return {
        "client": client_name,
        "findings": findings_list,
        "total": len(findings_list),
        "critical": severity_counts.get("CRITICAL", 0),
        "high": severity_counts.get("HIGH", 0),
        "resolved_count": resolved_count,
        "severity_filter": severity_filter_upper,
    }


@router.get("/clients/{client_name}/findings/{finding_id}", tags=["Clients"])
async def get_client_finding(client_name: str, finding_id: str):
    """Return a single finding by ID for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    known_findings: dict = profile.known_findings or {}

    if finding_id not in known_findings:
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found for client '{client_name}'")

    record = known_findings[finding_id]
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' has invalid format")

    return {
        "client": client_name,
        "finding": {"id": finding_id, **record},
    }


@router.get("/clients/{client_name}/costs", tags=["Clients"])
async def get_client_costs(client_name: str):
    """Return a cost summary for a client based on their run history."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    _validate_client_name(client_name)

    store = get_profile_store()
    profile = await store.load(client_name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    run_history: list = profile.run_history or []
    current_month_prefix = datetime.utcnow().strftime("%Y-%m")

    total_cost = 0.0
    cost_this_month = 0.0
    runs_this_month = 0

    for run in run_history:
        run_cost = float(run.get("estimated_cost_usd", 8.0))
        total_cost += run_cost
        ts = run.get("timestamp", "")
        if isinstance(ts, str) and ts.startswith(current_month_prefix):
            runs_this_month += 1
            cost_this_month += run_cost

    total_runs = len(run_history)
    avg_cost = round(total_cost / total_runs, 2) if total_runs else 0.0

    return {
        "client_name": client_name,
        "total_runs": total_runs,
        "estimated_total_cost_usd": round(total_cost, 2),
        "avg_cost_per_run_usd": avg_cost,
        "runs_this_month": runs_this_month,
        "cost_this_month_usd": round(cost_this_month, 2),
    }


@router.put("/clients/{client_name}/profile/false-positive")
async def mark_false_positive(client_name: str, finding_id: str):
    """Mark a finding as a false positive for this client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    if finding_id not in profile.false_positives:
        profile.false_positives.append(finding_id)

    if profile.refinement is None:
        profile.refinement = {}
    suppress = profile.refinement.get("suppress_ids", [])
    if finding_id not in suppress:
        suppress.append(finding_id)
    profile.refinement["suppress_ids"] = suppress

    await store.save(profile)
    return {"status": "ok", "finding_id": finding_id, "client": client_name}


@router.delete("/clients/{client_name}/profile")
async def reset_client_profile(client_name: str):
    """Reset (delete) a client's profile."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    from shared.memory.client_profile import ClientProfile

    store = get_profile_store()
    blank = ClientProfile.new(client_name)
    await store.save(blank)
    return {"status": "reset", "client": client_name}


@router.get("/clients/{client_name}/dq-history", tags=["Quality"])
async def get_client_dq_history(client_name: str):
    """Get historical DQ scores for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")

    dq_history = getattr(profile, 'dq_history', []) or profile.__dict__.get('dq_history', [])

    avg_score = sum(r["score"] for r in dq_history) / len(dq_history) if dq_history else None
    trend = None
    if len(dq_history) >= 2:
        recent = dq_history[-3:]
        early = dq_history[:-3] if len(dq_history) > 3 else dq_history[:1]
        recent_avg = sum(r["score"] for r in recent) / len(recent)
        early_avg = sum(r["score"] for r in early) / len(early)
        if recent_avg > early_avg + 2:
            trend = "improving"
        elif recent_avg < early_avg - 2:
            trend = "declining"
        else:
            trend = "stable"

    return {
        "client": client_name,
        "dq_history": dq_history,
        "avg_score": round(avg_score, 1) if avg_score else None,
        "trend": trend,
        "runs_with_dq": len(dq_history),
    }


@router.get("/clients/{client_name}/kpis", tags=["Clients"])
async def get_client_kpis(client_name: str):
    """Get KPI baseline history for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    _validate_client_name(client_name)

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {client_name}")

    baseline_history: dict = profile.baseline_history or {}

    all_periods: list[str] = []
    for datapoints in baseline_history.values():
        for dp in datapoints:
            period = dp.get("period")
            if period:
                all_periods.append(period)

    return {
        "client_name": client_name,
        "kpis": baseline_history,
        "kpi_count": len(baseline_history),
        "earliest_period": min(all_periods) if all_periods else None,
        "latest_period": max(all_periods) if all_periods else None,
    }


@router.get("/clients/{client_name}/stats", tags=["Clients"])
async def get_client_stats(client_name: str):
    """Get summary statistics for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for: {client_name}")

    run_history = profile.run_history[-10:]
    findings_trend = [r.get("findings_count", 0) for r in run_history]
    trend_direction = "stable"
    if len(findings_trend) >= 2:
        if findings_trend[-1] > findings_trend[0]:
            trend_direction = "increasing"
        elif findings_trend[-1] < findings_trend[0]:
            trend_direction = "decreasing"

    resolved = list(profile.resolved_findings.values())

    return {
        "client_name": client_name,
        "run_count": profile.run_count,
        "last_run_date": profile.last_run_date,
        "industry": profile.industry_inferred,
        "currency": profile.currency_detected,
        "active_findings": len(profile.known_findings),
        "resolved_findings": len(profile.resolved_findings),
        "critical_active": sum(
            1 for r in profile.known_findings.values()
            if r.get("severity", "") == "CRITICAL"
        ),
        "avg_runs_open": round(
            sum(r.get("runs_open", 1) for r in profile.known_findings.values()) /
            max(len(profile.known_findings), 1), 1
        ),
        "findings_trend": trend_direction,
        "kpi_count": len(profile.baseline_history),
        "focus_tables": profile.focus_tables[:5],
        "refinement_ready": profile.refinement is not None,
        "entity_cache_fresh": profile.is_entity_map_fresh(),
    }


@router.get("/clients/{client_name}/analytics", tags=["Clients"])
async def get_client_analytics(client_name: str):
    """Return deeper run analytics derived from the client's run_history."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for: {client_name}")

    run_history = profile.run_history or []
    total_runs = len(run_history)

    successful = sum(1 for r in run_history if r.get("success", True))
    success_rate = round(successful / total_runs * 100, 1) if total_runs else 0.0

    avg_findings = round(
        sum(r.get("findings_count", 0) for r in run_history) / max(total_runs, 1), 1
    )
    avg_new = round(
        sum(r.get("new", 0) for r in run_history) / max(total_runs, 1), 1
    )
    avg_resolved = round(
        sum(r.get("resolved", 0) for r in run_history) / max(total_runs, 1), 1
    )

    runs_by_month: dict = defaultdict(int)
    for r in run_history:
        date_str = r.get("run_date", "")
        if date_str and len(date_str) >= 7:
            month_key = date_str[:7]
            runs_by_month[month_key] += 1

    last_5 = run_history[-5:]
    velocity_counts = [r.get("findings_count", 0) for r in last_5]
    finding_velocity = "stable"
    if len(velocity_counts) >= 2:
        if velocity_counts[-1] > velocity_counts[0]:
            finding_velocity = "increasing"
        elif velocity_counts[-1] < velocity_counts[0]:
            finding_velocity = "decreasing"

    last_5_runs = [
        {
            "run_date": r.get("run_date"),
            "findings_count": r.get("findings_count", 0),
            "new": r.get("new", 0),
            "resolved": r.get("resolved", 0),
            "success": r.get("success", True),
        }
        for r in last_5
    ]

    return {
        "client_name": client_name,
        "total_runs": total_runs,
        "success_rate": success_rate,
        "avg_findings_per_run": avg_findings,
        "avg_new_findings_per_run": avg_new,
        "avg_resolved_per_run": avg_resolved,
        "runs_by_month": dict(sorted(runs_by_month.items())),
        "finding_velocity": finding_velocity,
        "last_5_runs": last_5_runs,
    }


@router.get("/clients/{client_name}/segmentation", tags=["Segmentation"])
async def get_client_segmentation(client_name: str):
    """Get latest customer segmentation for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")

    history = getattr(profile, "segmentation_history", []) or profile.__dict__.get("segmentation_history", [])
    if not history:
        return {"client": client_name, "segmentation": None, "message": "No segmentation data yet"}

    latest = history[-1]
    return {
        "client": client_name,
        "computed_at": latest.get("computed_at"),
        "total_customers": latest.get("total_customers"),
        "total_revenue": latest.get("total_revenue"),
        "segments": latest.get("segments", {}),
        "history_count": len(history),
    }


# ── Webhooks ──────────────────────────────────────────────────────────────────

@router.post("/clients/{client_name}/webhooks")
async def register_webhook(client_name: str, body: dict):
    """Register a webhook URL for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    webhook_url = body.get("url")
    if not webhook_url or not webhook_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Valid webhook URL required")

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    existing = [w for w in profile.webhooks if w.get("url") != webhook_url]
    existing.append({"url": webhook_url, "registered_at": datetime.utcnow().isoformat(), "active": True})
    profile.webhooks = existing[-5:]

    await store.save(profile)
    return {"status": "registered", "url": webhook_url, "client": client_name}


@router.get("/clients/{client_name}/webhooks")
async def list_webhooks(client_name: str):
    """List registered webhooks for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"client": client_name, "webhooks": profile.webhooks}


@router.delete("/clients/{client_name}/webhooks")
async def delete_webhook(client_name: str, url: str):
    """Remove a webhook."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store
    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="Client not found")
    profile.webhooks = [w for w in profile.webhooks if w.get("url") != url]
    await store.save(profile)
    return {"status": "removed", "remaining": len(profile.webhooks)}
