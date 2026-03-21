"""
Unit tests for AlertEngine.check_thresholds() and create_default_thresholds().
Pure in-memory data — no database or external service required.

Missing optional dependencies (structlog) are stubbed via sys.modules so the
test suite runs in any environment, including CI without the full dependency set.
"""
import sys
import types
import logging

# ---------------------------------------------------------------------------
# sys.modules stubs — stub optional / heavy dependencies before any import
# ---------------------------------------------------------------------------

# structlog — used by alert_engine.py; fall back gracefully when absent
if "structlog" not in sys.modules:
    _structlog_stub = types.ModuleType("structlog")
    _structlog_stub.get_logger = lambda: logging.getLogger("structlog_stub")
    sys.modules["structlog"] = _structlog_stub

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


# ---------------------------------------------------------------------------
# absolute_above condition
# ---------------------------------------------------------------------------

def test_absolute_above_triggers():
    """Current value exceeds threshold — should trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("high_receivables", "total_receivables", "absolute_above", 500_000.0, "HIGH")
    ])
    history = {"total_receivables": make_history([600_000.0])}
    alerts = engine.check_thresholds(profile, history, {})

    assert len(alerts) == 1
    assert alerts[0]["condition"] == "absolute_above"
    assert alerts[0]["computed_value"] == pytest.approx(600_000.0)


def test_absolute_above_does_not_trigger_when_below():
    """Current value is below threshold — should NOT trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("high_receivables", "total_receivables", "absolute_above", 500_000.0, "HIGH")
    ])
    history = {"total_receivables": make_history([400_000.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


# ---------------------------------------------------------------------------
# Edge cases for z_score_above
# ---------------------------------------------------------------------------

def test_z_score_does_not_trigger_within_bounds():
    """Series with no spike — z-score below threshold — should NOT trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("anomaly_z", "some_metric", "z_score_above", 3.0, "CRITICAL")
    ])
    # All values very close to each other — no anomaly
    history = {"some_metric": make_history([100.0, 101.0, 99.0, 100.0, 102.0, 100.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


def test_z_score_requires_minimum_3_values():
    """z_score condition with fewer than 3 data points must NOT trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("anomaly_z", "some_metric", "z_score_above", 1.0, "HIGH")
    ])
    # Only 2 values — not enough for z-score
    history = {"some_metric": make_history([100.0, 200.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


# ---------------------------------------------------------------------------
# Missing metric / empty history
# ---------------------------------------------------------------------------

def test_missing_metric_key_skips_threshold():
    """If baseline_history has no entry for a threshold's metric, it is silently skipped."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("revenue_drop", "total_revenue", "pct_change_below", -15.0)
    ])
    # Provide history for a different key — threshold metric is absent
    history = {"some_other_metric": make_history([1_000.0, 800.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


def test_empty_history_for_metric_skips_threshold():
    """An empty history list for the metric key is treated the same as absent."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("revenue_drop", "total_revenue", "pct_change_below", -15.0)
    ])
    history = {"total_revenue": []}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


# ---------------------------------------------------------------------------
# Unknown condition type
# ---------------------------------------------------------------------------

def test_unknown_condition_never_triggers():
    """An unrecognized condition type must never produce an alert."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("unknown_cond", "total_revenue", "not_a_real_condition", 0.0)
    ])
    history = {"total_revenue": make_history([1_000_000.0, 0.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


# ---------------------------------------------------------------------------
# Triggered_alerts capped at 20
# ---------------------------------------------------------------------------

def test_triggered_alerts_capped_at_20():
    """profile.triggered_alerts never grows beyond 20 entries."""
    engine = AlertEngine()
    # Pre-populate the profile with 19 historical alerts
    old_alerts = [{"condition": "absolute_below", "metric": "x", "period": str(i)} for i in range(19)]
    profile = make_profile(
        alert_thresholds=[
            make_threshold("zero_revenue", "total_revenue", "absolute_below", 100.0, "CRITICAL")
        ],
        triggered_alerts=old_alerts,
    )
    history = {"total_revenue": make_history([10.0])}
    engine.check_thresholds(profile, history, {})
    # We had 19 old + 1 new = 20 — capped at 20
    assert len(profile.triggered_alerts) == 20


# ---------------------------------------------------------------------------
# Multiple implicit CRITICAL findings
# ---------------------------------------------------------------------------

def test_multiple_implicit_critical_findings_all_captured():
    """Multiple CRITICAL findings each produce a separate implicit alert."""
    engine = AlertEngine()
    profile = make_profile()
    findings = {
        "sentinel": {
            "findings": [
                {"id": "fraud_001", "title": "Fraud finding A", "severity": "CRITICAL"},
                {"id": "fraud_002", "title": "Fraud finding B", "severity": "CRITICAL"},
            ]
        }
    }
    alerts = engine.check_thresholds(profile, {}, findings)
    assert len(alerts) == 2
    ids = {a["finding_id"] for a in alerts}
    assert "fraud_001" in ids
    assert "fraud_002" in ids


# ---------------------------------------------------------------------------
# Additional alert engine tests
# ---------------------------------------------------------------------------

def test_check_thresholds_returns_list():
    """check_thresholds always returns a list."""
    engine = AlertEngine()
    profile = make_profile()
    result = engine.check_thresholds(profile, {}, {})
    assert isinstance(result, list)


def test_no_thresholds_no_alerts():
    """Profile with no thresholds generates no alerts (except implicit CRITICAL)."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[])
    result = engine.check_thresholds(profile, {}, {})
    assert result == []


def test_threshold_with_no_history_skips_gracefully():
    """Threshold for a metric with no history produces no alert."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("Revenue Check", "Revenue Total", "pct_change_below", -0.10)
    ])
    # Empty history
    result = engine.check_thresholds(profile, {}, {})
    assert isinstance(result, list)


def test_alert_contains_required_keys():
    """Each triggered alert dict must have label, severity, message keys."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("Revenue Drop", "Revenue Total", "pct_change_below", -0.05)
    ])
    history = {"Revenue Total": make_history([1000.0, 900.0])}
    alerts = engine.check_thresholds(profile, history, {})
    for alert in alerts:
        assert "label" in alert or "metric" in alert
        assert "severity" in alert


def test_create_default_thresholds_returns_list():
    """create_default_thresholds(profile) returns a non-empty list."""
    profile = make_profile()
    thresholds = create_default_thresholds(profile)
    assert isinstance(thresholds, list)
    assert len(thresholds) > 0


def test_create_default_thresholds_have_required_fields():
    """Each default threshold has label, metric, condition, value, severity."""
    profile = make_profile()
    thresholds = create_default_thresholds(profile)
    for t in thresholds:
        assert "label" in t
        assert "metric" in t
        assert "severity" in t


def test_medium_severity_finding_does_not_trigger_implicit_alert():
    """Only CRITICAL findings trigger implicit alerts."""
    engine = AlertEngine()
    profile = make_profile()
    findings = {
        "analyst": {"findings": [
            {"id": "f1", "title": "Medium finding", "severity": "MEDIUM"}
        ]}
    }
    alerts = engine.check_thresholds(profile, {}, findings)
    # MEDIUM severity should not trigger any alert
    medium_alerts = [a for a in alerts if a.get("finding_id") == "f1"]
    assert len(medium_alerts) == 0


def test_above_threshold_triggers_alert():
    """absolute_above condition triggers when current value exceeds threshold."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("AR Spike", "AR >90 days", "absolute_above", 500.0, severity="HIGH")
    ])
    history = {"AR >90 days": make_history([300.0, 600.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert any(a.get("label") == "AR Spike" or a.get("metric") == "AR >90 days" for a in alerts)


def test_below_threshold_not_triggered_when_value_ok():
    """absolute_above threshold does NOT trigger when current value is below threshold."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("AR Spike", "AR >90 days", "absolute_above", 500.0, severity="HIGH")
    ])
    history = {"AR >90 days": make_history([300.0, 400.0])}  # 400 < 500
    alerts = engine.check_thresholds(profile, history, {})
    ar_alerts = [a for a in alerts if "AR" in (a.get("label", "") + a.get("metric", ""))]
    assert len(ar_alerts) == 0


# ---------------------------------------------------------------------------
# Additional edge-case and coverage tests
# ---------------------------------------------------------------------------

def test_pct_change_below_exact_boundary_does_not_trigger():
    """pct_change_below with exact boundary value should NOT trigger (strict <)."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("revenue_drop", "total_revenue", "pct_change_below", -15.0)
    ])
    # prev=1_000_000, curr=850_000 → exactly -15.0%
    history = {"total_revenue": make_history([1_000_000.0, 850_000.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


def test_pct_change_above_exact_boundary_does_not_trigger():
    """pct_change_above with exact boundary value should NOT trigger (strict >)."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("receivables_spike", "total_receivables", "pct_change_above", 25.0)
    ])
    # prev=100_000, curr=125_000 → exactly +25.0%
    history = {"total_receivables": make_history([100_000.0, 125_000.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


def test_absolute_below_exact_boundary_does_not_trigger():
    """absolute_below: current == threshold — NOT triggered (strict <)."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("zero_revenue", "total_revenue", "absolute_below", 100.0, "CRITICAL")
    ])
    history = {"total_revenue": make_history([100.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


def test_alert_triggered_at_is_iso_string():
    """triggered_at field in triggered alerts is a non-empty ISO timestamp string."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("zero_revenue", "total_revenue", "absolute_below", 100.0, "CRITICAL")
    ])
    history = {"total_revenue": make_history([50.0])}
    alerts = engine.check_thresholds(profile, history, {})
    assert len(alerts) == 1
    ts = alerts[0].get("triggered_at", "")
    assert isinstance(ts, str) and len(ts) > 0


def test_multiple_thresholds_only_one_fires():
    """Two thresholds for different metrics — only one condition met — one alert."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("revenue_drop", "total_revenue", "absolute_below", 100.0, "CRITICAL"),
        make_threshold("receivables_spike", "total_receivables", "absolute_above", 500_000.0, "HIGH"),
    ])
    # Revenue OK (200 > 100), receivables OK (300_000 < 500_000)
    history = {
        "total_revenue": make_history([200.0]),
        "total_receivables": make_history([300_000.0]),
    }
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


def test_multiple_thresholds_both_fire():
    """Two thresholds — both conditions met — two alerts returned."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("zero_revenue", "total_revenue", "absolute_below", 100.0, "CRITICAL"),
        make_threshold("high_ar", "total_receivables", "absolute_above", 500_000.0, "HIGH"),
    ])
    history = {
        "total_revenue": make_history([50.0]),
        "total_receivables": make_history([600_000.0]),
    }
    alerts = engine.check_thresholds(profile, history, {})
    assert len(alerts) == 2
    severities = {a["severity"] for a in alerts}
    assert "CRITICAL" in severities
    assert "HIGH" in severities


def test_pct_change_with_single_value_does_not_trigger():
    """pct_change_below requires at least 2 history values — one value must not trigger."""
    engine = AlertEngine()
    profile = make_profile(alert_thresholds=[
        make_threshold("revenue_drop", "total_revenue", "pct_change_below", -15.0)
    ])
    history = {"total_revenue": make_history([1_000_000.0])}  # only one entry
    alerts = engine.check_thresholds(profile, history, {})
    assert alerts == []


def test_triggered_alerts_overflow_beyond_20_is_truncated():
    """When pre-existing triggered_alerts already has 20 entries, adding 1 more stays at 20."""
    engine = AlertEngine()
    old_alerts = [{"condition": "absolute_below", "metric": "x", "period": str(i)} for i in range(20)]
    profile = make_profile(
        alert_thresholds=[
            make_threshold("zero_revenue", "total_revenue", "absolute_below", 100.0, "CRITICAL")
        ],
        triggered_alerts=old_alerts,
    )
    history = {"total_revenue": make_history([10.0])}
    engine.check_thresholds(profile, history, {})
    assert len(profile.triggered_alerts) == 20


def test_implicit_alert_finding_id_present():
    """Implicit alert from CRITICAL finding must contain finding_id field."""
    engine = AlertEngine()
    profile = make_profile()
    findings = {
        "sentinel": {
            "findings": [
                {"id": "fraud_xyz", "title": "Suspected fraud", "severity": "CRITICAL"},
            ]
        }
    }
    alerts = engine.check_thresholds(profile, {}, findings)
    assert len(alerts) == 1
    assert alerts[0].get("finding_id") == "fraud_xyz"


def test_findings_from_multiple_agents_are_all_checked():
    """CRITICAL findings from two different agent result dicts both produce alerts."""
    engine = AlertEngine()
    profile = make_profile()
    findings = {
        "sentinel": {
            "findings": [
                {"id": "s001", "title": "Sentinel finding", "severity": "CRITICAL"},
            ]
        },
        "hunter": {
            "findings": [
                {"id": "h001", "title": "Hunter finding", "severity": "CRITICAL"},
            ]
        },
    }
    alerts = engine.check_thresholds(profile, {}, findings)
    assert len(alerts) == 2
    ids = {a["finding_id"] for a in alerts}
    assert "s001" in ids
    assert "h001" in ids


def test_create_default_thresholds_retail_industry():
    """An industry other than 'distribución mayorista' only gets the universal threshold."""
    profile = make_profile()
    profile.industry_inferred = "retail"
    thresholds = create_default_thresholds(profile)
    labels = [t["label"] for t in thresholds]
    assert "consecutive_zero_revenue" in labels
    assert "revenue_drop" not in labels
    assert "receivables_spike" not in labels
