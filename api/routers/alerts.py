"""
Alerts router — Alert threshold CRUD and triggered alerts.

Extracted from main.py for better modularity.
"""

import os
import sys
from datetime import datetime

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["Alerts"])


def _ensure_shared_path():
    shared_parent = os.path.join(os.path.dirname(__file__), '..', '..')
    if shared_parent not in sys.path:
        sys.path.insert(0, shared_parent)


_VALID_CONDITIONS = {
    "pct_change_below",
    "pct_change_above",
    "absolute_below",
    "absolute_above",
    "z_score_above",
}


@router.get("/clients/{client_name}/alerts", tags=["Alerts"])
async def get_client_alerts(client_name: str):
    """Get alert thresholds and recent triggers for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(client_name)
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found")

    return {
        "client_name": client_name,
        "thresholds": profile.alert_thresholds,
        "triggered_alerts": (profile.triggered_alerts or [])[-10:],
    }


@router.post("/clients/{client_name}/alerts")
async def add_alert_threshold(client_name: str, threshold: dict):
    """Add an alert threshold for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    required = ["label", "metric", "operator", "value"]
    if not all(k in threshold for k in required):
        raise HTTPException(status_code=400, detail=f"Required fields: {required}")

    store = get_profile_store()
    profile = await store.load_or_create(client_name)

    existing = [t for t in profile.alert_thresholds if t.get("label") == threshold["label"]]
    if existing:
        for t in profile.alert_thresholds:
            if t.get("label") == threshold["label"]:
                t.update(threshold)
    else:
        profile.alert_thresholds.append({**threshold, "triggered": False, "created_at": datetime.utcnow().isoformat()})

    await store.save(profile)
    return {"status": "ok", "thresholds_count": len(profile.alert_thresholds)}


@router.delete("/clients/{client_name}/alerts/{alert_label}")
async def delete_alert_threshold(client_name: str, alert_label: str):
    """Remove an alert threshold."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load_or_create(client_name)
    profile.alert_thresholds = [t for t in profile.alert_thresholds if t.get("label") != alert_label]
    await store.save(profile)
    return {"status": "deleted"}


@router.get("/clients/{name}/alerts/thresholds", tags=["Alerts"])
async def get_alert_thresholds(name: str):
    """Return the client's alert thresholds keyed by metric name."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {name}")

    thresholds = profile.alert_thresholds or []
    return {"thresholds": thresholds, "count": len(thresholds)}


@router.post("/clients/{name}/alerts/thresholds", tags=["Alerts"])
async def upsert_alert_threshold(name: str, body: dict):
    """Create or update an alert threshold for a client."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    required = ["metric", "condition", "threshold_value", "severity"]
    missing = [f for f in required if f not in body]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required fields: {missing}")

    condition = body["condition"]
    if condition not in _VALID_CONDITIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid condition '{condition}'. Must be one of: {sorted(_VALID_CONDITIONS)}",
        )

    metric = body["metric"]
    new_threshold = {
        "metric":          metric,
        "condition":       condition,
        "value":           float(body["threshold_value"]),
        "severity":        body["severity"],
        "description":     body.get("description", ""),
        "label":           metric,
        "triggered":       False,
        "created_at":      datetime.utcnow().isoformat(),
    }

    store = get_profile_store()
    profile = await store.load_or_create(name)

    updated = False
    for i, t in enumerate(profile.alert_thresholds):
        if t.get("metric") == metric:
            profile.alert_thresholds[i] = {**t, **new_threshold}
            new_threshold = profile.alert_thresholds[i]
            updated = True
            break
    if not updated:
        profile.alert_thresholds.append(new_threshold)

    await store.save(profile)
    return {"status": "ok", "threshold": new_threshold, "upserted": True}


@router.delete("/clients/{name}/alerts/thresholds/{metric}", tags=["Alerts"])
async def delete_alert_threshold_by_metric(name: str, metric: str):
    """Remove an alert threshold identified by its metric key."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load_or_create(name)
    before = len(profile.alert_thresholds)
    profile.alert_thresholds = [t for t in profile.alert_thresholds if t.get("metric") != metric]
    if len(profile.alert_thresholds) == before:
        raise HTTPException(status_code=404, detail=f"No threshold found for metric: {metric}")
    await store.save(profile)
    return {"deleted": True, "metric": metric}


@router.get("/clients/{name}/alerts/triggered", tags=["Alerts"])
async def get_triggered_alerts(name: str):
    """Return triggered alerts stored from the last analysis run."""
    _ensure_shared_path()
    from shared.memory.profile_store import get_profile_store

    store = get_profile_store()
    profile = await store.load(name)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile found for client: {name}")

    triggered = profile.metadata.get("last_triggered_alerts", [])
    return {"triggered": triggered}
