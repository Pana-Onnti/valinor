"""
Unit tests for AlertEngine.check_thresholds() and create_default_thresholds().
No mocking — pure in-memory data.
"""
import pytest
from shared.memory.alert_engine import AlertEngine, create_default_thresholds
from shared.memory.client_profile import ClientProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_profile(**kwargs) -> ClientProfile:
    """Return a minimal ClientProfile with sensible defaults."""
    return ClientProfile(client_name="Test Corp", **kwargs)


def make_history(values):
    """Build a baseline_history entry list from a plain list of floats."""
    return [{"period": f"2026-0{i+1}", "numeric_value": v} for i, v in enumerate(values)]


def make_threshold(label, metric, condition, value, severity="HIGH"):
    return {
        "label": label,
        "metric": metric,
        "condition": condition,
        "value": value,
        "severity": severity,
        "message": f"Threshold {label}",
    }


# ---------------------------------------------------------------------------
# pct_change_below — revenue drop
# ---------------------------------------------------------------------------

def test_pct_change_below_triggers_on_revenue_drop():
    """Revenue drops 20% — threshold is -15% — should trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("revenue_drop", "total_revenue", "pct_change_below", -15.0, "HIGH")
    ])
    # prev=1_000_000, curr=800_000 → pct_change = -20%
    history = {"total_revenue": make_history([1_000_000.0, 800_000.0])}
    alerts = engine.check_thresholds(profile, history, {})

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["condition"] == "pct_change_below"
    assert alert["threshold_label"] == "revenue_drop"
    assert alert["severity"] == "HIGH"
    assert alert["computed_value"] == pytest.approx(-20.0, rel=1e-4)


# ---------------------------------------------------------------------------
# pct_change_above — receivables spike
# ---------------------------------------------------------------------------

def test_pct_change_above_triggers_on_receivables_spike():
    """Receivables grow 30% — threshold is 25% — should trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("receivables_spike", "total_receivables", "pct_change_above", 25.0, "HIGH")
    ])
    # prev=100_000, curr=130_000 → pct_change = +30%
    history = {"total_receivables": make_history([100_000.0, 130_000.0])}
    alerts = engine.check_thresholds(profile, history, {})

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["condition"] == "pct_change_above"
    assert alert["computed_value"] == pytest.approx(30.0, rel=1e-4)


# ---------------------------------------------------------------------------
# z_score_above — statistical anomaly
# ---------------------------------------------------------------------------

def test_z_score_above_triggers_when_last_value_is_4_std_devs():
    """Last value is ~4 std devs above the mean of the rest — threshold=3 — should trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("anomaly_z", "some_metric", "z_score_above", 3.0, "CRITICAL")
    ])
    # Stable series with a huge spike at the end
    base = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]
    spike = [600.0]  # z-score will be far above 4
    history = {"some_metric": make_history(base + spike)}
    alerts = engine.check_thresholds(profile, history, {})

    assert len(alerts) == 1
    assert alerts[0]["condition"] == "z_score_above"
    assert abs(alerts[0]["computed_value"]) > 3.0


# ---------------------------------------------------------------------------
# absolute_below
# ---------------------------------------------------------------------------

def test_absolute_below_triggers():
    """Current revenue is 50 — threshold is 100 — should trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("zero_revenue", "total_revenue", "absolute_below", 100.0, "CRITICAL")
    ])
    history = {"total_revenue": make_history([50.0])}
    alerts = engine.check_thresholds(profile, history, {})

    assert len(alerts) == 1
    assert alerts[0]["condition"] == "absolute_below"
    assert alerts[0]["severity"] == "CRITICAL"
    assert alerts[0]["computed_value"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# NO trigger when within threshold
# ---------------------------------------------------------------------------

def test_no_trigger_when_within_threshold():
    """Revenue drops only 5% — threshold is -15% — should NOT trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("revenue_drop", "total_revenue", "pct_change_below", -15.0)
    ])
    # prev=1_000_000, curr=950_000 → pct_change = -5%
    history = {"total_revenue": make_history([1_000_000.0, 950_000.0])}
    alerts = engine.check_thresholds(profile, history, {})

    assert alerts == []


def test_no_trigger_when_receivables_within_threshold():
    """Receivables grow only 10% — threshold is 25% — should NOT trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("receivables_spike", "total_receivables", "pct_change_above", 25.0)
    ])
    history = {"total_receivables": make_history([100_000.0, 110_000.0])}
    alerts = engine.check_thresholds(profile, history, {})

    assert alerts == []


# ---------------------------------------------------------------------------
# Implicit CRITICAL finding creates an alert
# ---------------------------------------------------------------------------

def test_implicit_critical_finding_creates_alert():
    """A CRITICAL finding in agent results must produce an implicit alert."""
    engine = AlertEngine()
    profile = make_profile()  # no explicit thresholds
    findings = {
        "sentinel": {
            "findings": [
                {"id": "ghost_vendor_001", "title": "Ghost vendor detected", "severity": "CRITICAL"},
            ]
        }
    }
    alerts = engine.check_thresholds(profile, {}, findings)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["condition"] == "implicit"
    assert alert["severity"] == "CRITICAL"
    assert alert["metric"] == "finding_severity"
    assert "ghost_vendor_001" in alert["threshold_label"] or alert["finding_id"] == "ghost_vendor_001"


def test_non_critical_finding_does_not_create_alert():
    """A HIGH finding should NOT create an implicit alert."""
    engine = AlertEngine()
    profile = make_profile()
    findings = {
        "sentinel": {
            "findings": [
                {"id": "high_001", "title": "Some high finding", "severity": "HIGH"},
            ]
        }
    }
    alerts = engine.check_thresholds(profile, {}, findings)
    assert alerts == []


# ---------------------------------------------------------------------------
# triggered_alerts capped at 20 and stored on profile
# ---------------------------------------------------------------------------

def test_triggered_alerts_stored_on_profile():
    """Alerts are persisted to profile.triggered_alerts."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("zero_revenue", "total_revenue", "absolute_below", 100.0, "CRITICAL")
    ])
    history = {"total_revenue": make_history([10.0])}
    alerts = engine.check_thresholds(profile, history, {})

    assert len(profile.triggered_alerts) == 1
    assert profile.triggered_alerts[0]["condition"] == "absolute_below"


# ---------------------------------------------------------------------------
# create_default_thresholds
# ---------------------------------------------------------------------------

def test_create_default_thresholds_returns_at_least_one():
    """create_default_thresholds always returns at least 1 threshold."""
    profile = make_profile()
    thresholds = create_default_thresholds(profile)
    assert len(thresholds) >= 1


def test_create_default_thresholds_includes_zero_revenue_check():
    """The universal zero-revenue threshold must always be included."""
    profile = make_profile()
    thresholds = create_default_thresholds(profile)
    labels = [t["label"] for t in thresholds]
    assert "consecutive_zero_revenue" in labels


def test_create_default_thresholds_extra_for_distribucion_mayorista():
    """distribución mayorista industry gets additional revenue/receivables thresholds."""
    profile = make_profile()
    profile.industry_inferred = "distribución mayorista"
    thresholds = create_default_thresholds(profile)
    labels = [t["label"] for t in thresholds]
    assert "revenue_drop" in labels
    assert "receivables_spike" in labels
    assert len(thresholds) >= 3
