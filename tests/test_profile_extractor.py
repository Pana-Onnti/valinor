"""
Dedicated tests for shared/memory/profile_extractor.py — ProfileExtractor.

Stubs out heavy optional dependencies before any project imports so that the
test module works in a clean virtualenv that may be missing supabase, slowapi,
structlog, celery, claude_agent_sdk, or anthropic.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub missing heavy/optional dependencies before any project code is loaded
# ---------------------------------------------------------------------------

def _stub(name: str, **attrs: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


for _name in [
    "supabase",
    "slowapi",
    "slowapi.util",
    "slowapi.errors",
    "structlog",
    "celery",
    "celery.utils",
    "celery.utils.log",
    "claude_agent_sdk",
    "anthropic",
]:
    if _name not in sys.modules:
        sys.modules[_name] = _stub(_name)

# structlog needs a callable get_logger
_structlog_mod = sys.modules["structlog"]
_structlog_mod.get_logger = lambda *a, **kw: MagicMock()  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "shared"))
sys.path.insert(0, str(_ROOT / "core"))
sys.path.insert(0, str(_ROOT))

from memory.profile_extractor import ProfileExtractor, get_profile_extractor  # noqa: E402
from memory.client_profile import ClientProfile  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(name: str = "TestClient") -> ClientProfile:
    return ClientProfile.new(name)


def _findings_from(agent: str, items: list) -> dict:
    return {agent: {"findings": items}}


def _finding(fid: str, title: str = "Test Finding", severity: str = "MEDIUM") -> dict:
    return {"id": fid, "title": title, "severity": severity}


# ===========================================================================
# 1. Basic instantiation and singleton
# ===========================================================================

class TestSingleton:

    def test_get_profile_extractor_returns_instance(self):
        ext = get_profile_extractor()
        assert isinstance(ext, ProfileExtractor)

    def test_singleton_is_same_object(self):
        a = get_profile_extractor()
        b = get_profile_extractor()
        assert a is b

    def test_direct_instantiation_works(self):
        ext = ProfileExtractor()
        assert isinstance(ext, ProfileExtractor)


# ===========================================================================
# 2. update_from_run — delta structure
# ===========================================================================

class TestDeltaKeys:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def test_delta_has_all_required_keys(self):
        delta = self.ext.update_from_run(
            self.profile, {}, {"entities": {}}, {}, "2026-01"
        )
        assert set(delta.keys()) == {"new", "persists", "resolved", "worsened", "improved"}

    def test_all_delta_values_are_lists(self):
        delta = self.ext.update_from_run(
            self.profile, {}, {"entities": {}}, {}, "2026-01"
        )
        for v in delta.values():
            assert isinstance(v, list)

    def test_empty_run_produces_empty_delta(self):
        delta = self.ext.update_from_run(
            self.profile, {}, {"entities": {}}, {}, "2026-01"
        )
        for v in delta.values():
            assert v == []


# ===========================================================================
# 3. update_from_run — new findings
# ===========================================================================

class TestNewFindings:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def test_new_finding_appears_in_delta_new(self):
        delta = self.ext.update_from_run(
            self.profile,
            _findings_from("analyst", [_finding("FIN-001")]),
            {"entities": {}}, {}, "2026-01",
        )
        assert "FIN-001" in delta["new"]

    def test_new_finding_stored_in_known_findings(self):
        self.ext.update_from_run(
            self.profile,
            _findings_from("analyst", [_finding("FIN-002", severity="HIGH")]),
            {"entities": {}}, {}, "2026-01",
        )
        assert "FIN-002" in self.profile.known_findings

    def test_new_finding_has_correct_runs_open(self):
        self.ext.update_from_run(
            self.profile,
            _findings_from("analyst", [_finding("FIN-003")]),
            {"entities": {}}, {}, "2026-01",
        )
        assert self.profile.known_findings["FIN-003"]["runs_open"] == 1

    def test_new_finding_stores_severity(self):
        self.ext.update_from_run(
            self.profile,
            _findings_from("analyst", [_finding("FIN-004", severity="CRITICAL")]),
            {"entities": {}}, {}, "2026-01",
        )
        assert self.profile.known_findings["FIN-004"]["severity"] == "CRITICAL"

    def test_new_finding_stores_title(self):
        self.ext.update_from_run(
            self.profile,
            _findings_from("analyst", [_finding("FIN-005", title="AR 90d overdue")]),
            {"entities": {}}, {}, "2026-01",
        )
        assert self.profile.known_findings["FIN-005"]["title"] == "AR 90d overdue"

    def test_multiple_new_findings_all_captured(self):
        findings = [_finding(f"F-{i:03d}") for i in range(5)]
        delta = self.ext.update_from_run(
            self.profile,
            _findings_from("analyst", findings),
            {"entities": {}}, {}, "2026-01",
        )
        assert len(delta["new"]) == 5

    def test_finding_id_via_finding_id_key(self):
        """Findings may use 'finding_id' instead of 'id'."""
        f = {"finding_id": "ALT-001", "title": "Alt key finding", "severity": "LOW"}
        delta = self.ext.update_from_run(
            self.profile,
            {"sentinel": {"findings": [f]}},
            {"entities": {}}, {}, "2026-01",
        )
        assert "ALT-001" in delta["new"]

    def test_finding_without_id_ignored(self):
        f = {"title": "No id here", "severity": "LOW"}
        delta = self.ext.update_from_run(
            self.profile,
            {"analyst": {"findings": [f]}},
            {"entities": {}}, {}, "2026-01",
        )
        assert delta["new"] == []

    def test_multi_agent_findings_merged(self):
        findings = {
            "analyst": {"findings": [_finding("A-001")]},
            "sentinel": {"findings": [_finding("S-001")]},
            "hunter": {"findings": [_finding("H-001")]},
        }
        delta = self.ext.update_from_run(
            self.profile, findings, {"entities": {}}, {}, "2026-01"
        )
        assert set(delta["new"]) == {"A-001", "S-001", "H-001"}


# ===========================================================================
# 4. update_from_run — persistent and resolved findings
# ===========================================================================

class TestPersistsAndResolved:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def test_same_finding_persists_second_run(self):
        f = [_finding("PERSIST-001")]
        self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-01")
        delta = self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-02")
        assert "PERSIST-001" in delta["persists"]

    def test_persisting_finding_increments_runs_open(self):
        f = [_finding("PERSIST-002")]
        for i in range(3):
            self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, f"2026-0{i+1}")
        assert self.profile.known_findings["PERSIST-002"]["runs_open"] == 3

    def test_absent_finding_goes_to_resolved(self):
        f = [_finding("RES-001")]
        self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-01")
        delta = self.ext.update_from_run(self.profile, _findings_from("a", []), {"entities": {}}, {}, "2026-02")
        assert "RES-001" in delta["resolved"]

    def test_resolved_finding_removed_from_known(self):
        f = [_finding("RES-002")]
        self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-01")
        self.ext.update_from_run(self.profile, _findings_from("a", []), {"entities": {}}, {}, "2026-02")
        assert "RES-002" not in self.profile.known_findings

    def test_resolved_finding_stored_in_resolved_dict(self):
        f = [_finding("RES-003")]
        self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-01")
        self.ext.update_from_run(self.profile, _findings_from("a", []), {"entities": {}}, {}, "2026-02")
        assert "RES-003" in self.profile.resolved_findings

    def test_resolved_finding_has_resolved_at_timestamp(self):
        f = [_finding("RES-004")]
        self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-01")
        self.ext.update_from_run(self.profile, _findings_from("a", []), {"entities": {}}, {}, "2026-02")
        assert "resolved_at" in self.profile.resolved_findings["RES-004"]

    def test_reappearing_finding_back_in_known(self):
        f = [_finding("REAPP-001")]
        self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-01")
        self.ext.update_from_run(self.profile, _findings_from("a", []), {"entities": {}}, {}, "2026-02")
        assert "REAPP-001" in self.profile.resolved_findings
        # Finding reappears — should be treated as new and added back to known_findings
        delta = self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, "2026-03")
        assert "REAPP-001" in self.profile.known_findings
        # It comes back as a "new" finding since it was removed from known_findings
        assert "REAPP-001" in delta["new"]


# ===========================================================================
# 5. update_from_run — severity tracking
# ===========================================================================

class TestSeverityTracking:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def _run_twice(self, sev1: str, sev2: str) -> dict:
        f1 = [_finding("SEV-001", severity=sev1)]
        f2 = [_finding("SEV-001", severity=sev2)]
        self.ext.update_from_run(self.profile, _findings_from("a", f1), {"entities": {}}, {}, "2026-01")
        return self.ext.update_from_run(self.profile, _findings_from("a", f2), {"entities": {}}, {}, "2026-02")

    def test_low_to_high_is_worsened(self):
        delta = self._run_twice("LOW", "HIGH")
        assert "SEV-001" in delta["worsened"]

    def test_high_to_low_is_improved(self):
        delta = self._run_twice("HIGH", "LOW")
        assert "SEV-001" in delta["improved"]

    def test_medium_to_medium_is_persists(self):
        delta = self._run_twice("MEDIUM", "MEDIUM")
        assert "SEV-001" in delta["persists"]

    def test_info_to_critical_is_worsened(self):
        delta = self._run_twice("INFO", "CRITICAL")
        assert "SEV-001" in delta["worsened"]

    def test_critical_to_info_is_improved(self):
        delta = self._run_twice("CRITICAL", "INFO")
        assert "SEV-001" in delta["improved"]

    def test_worsened_finding_severity_updated_in_profile(self):
        self._run_twice("LOW", "CRITICAL")
        assert self.profile.known_findings["SEV-001"]["severity"] == "CRITICAL"

    def test_improved_finding_severity_updated_in_profile(self):
        self._run_twice("HIGH", "LOW")
        assert self.profile.known_findings["SEV-001"]["severity"] == "LOW"


# ===========================================================================
# 6. update_from_run — run stats
# ===========================================================================

class TestRunStats:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def test_run_count_starts_at_zero(self):
        assert self.profile.run_count == 0

    def test_run_count_incremented_per_call(self):
        for i in range(4):
            self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, f"2026-0{i+1}")
        assert self.profile.run_count == 4

    def test_last_run_date_set(self):
        self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, "2026-01")
        assert self.profile.last_run_date is not None

    def test_run_history_entry_added(self):
        self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, "2026-01")
        assert len(self.profile.run_history) == 1

    def test_run_history_entry_has_period(self):
        self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, "2026-03")
        assert self.profile.run_history[0]["period"] == "2026-03"

    def test_run_history_capped_at_20(self):
        for i in range(25):
            self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, f"period-{i:03d}")
        assert len(self.profile.run_history) == 20

    def test_run_history_keeps_most_recent(self):
        for i in range(22):
            self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, f"period-{i:03d}")
        last_period = self.profile.run_history[-1]["period"]
        assert last_period == "period-021"

    def test_run_success_stored_in_history(self):
        self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, "2026-01", run_success=False)
        assert self.profile.run_history[0]["success"] is False

    def test_findings_count_in_history(self):
        findings = _findings_from("a", [_finding("F-001"), _finding("F-002")])
        self.ext.update_from_run(self.profile, findings, {"entities": {}}, {}, "2026-01")
        assert self.profile.run_history[0]["findings_count"] == 2


# ===========================================================================
# 7. _auto_escalate_persistent
# ===========================================================================

class TestAutoEscalate:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def _run_n_times(self, n: int, fid: str = "CHRONIC-001", severity: str = "LOW") -> None:
        f = [_finding(fid, severity=severity)]
        for i in range(n):
            self.ext.update_from_run(self.profile, _findings_from("a", f), {"entities": {}}, {}, f"run-{i:03d}")

    def test_no_escalation_before_5_runs(self):
        self._run_n_times(4)
        rec = self.profile.known_findings.get("CHRONIC-001", {})
        assert rec.get("auto_escalated") is not True

    def test_escalation_triggered_after_5_runs(self):
        self._run_n_times(6)
        rec = self.profile.known_findings.get("CHRONIC-001", {})
        # LOW (1 run_open increment per run) should have been escalated to at least MEDIUM
        assert rec.get("severity", "LOW") in ("MEDIUM", "HIGH", "CRITICAL")

    def test_escalation_sets_auto_escalated_flag(self):
        self._run_n_times(6)
        rec = self.profile.known_findings.get("CHRONIC-001", {})
        assert rec.get("auto_escalated") is True

    def test_critical_finding_not_escalated_beyond_critical(self):
        self._run_n_times(7, fid="CRIT-X", severity="CRITICAL")
        rec = self.profile.known_findings.get("CRIT-X", {})
        assert rec.get("severity") == "CRITICAL"


# ===========================================================================
# 8. Table weights via entity_map
# ===========================================================================

class TestTableWeights:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def test_table_weight_set_when_finding_references_table(self):
        entity_map = {"entities": {"orders": {"table": "c_order"}}}
        findings = {"analyst": {"findings": [
            {"id": "F-001", "title": "Order issue", "severity": "HIGH", "sql": "SELECT * FROM c_order"}
        ]}}
        self.ext.update_from_run(self.profile, findings, entity_map, {}, "2026-01")
        assert "c_order" in self.profile.table_weights

    def test_table_weight_is_between_0_and_1(self):
        entity_map = {"entities": {"inv": {"table": "invoice"}}}
        findings = {"analyst": {"findings": [
            {"id": "F-001", "title": "Invoice problem", "severity": "MEDIUM", "sql": "FROM invoice"}
        ]}}
        self.ext.update_from_run(self.profile, findings, entity_map, {}, "2026-01")
        for w in self.profile.table_weights.values():
            assert 0.0 <= w <= 1.0

    def test_max_weight_table_gets_1_0(self):
        entity_map = {
            "entities": {
                "tbl_a": {"table": "table_a"},
                "tbl_b": {"table": "table_b"},
            }
        }
        findings = {"analyst": {"findings": [
            {"id": "F-001", "title": "table_a issue", "severity": "HIGH", "sql": "FROM table_a"},
            {"id": "F-002", "title": "table_a issue 2", "severity": "HIGH", "sql": "FROM table_a"},
            {"id": "F-003", "title": "table_b issue", "severity": "LOW", "sql": "FROM table_b"},
        ]}}
        self.ext.update_from_run(self.profile, findings, entity_map, {}, "2026-01")
        assert self.profile.table_weights.get("table_a") == 1.0

    def test_focus_tables_populated(self):
        entity_map = {"entities": {"orders": {"table": "c_order"}}}
        findings = {"analyst": {"findings": [
            {"id": "F-001", "title": "Order issue", "severity": "HIGH", "sql": "FROM c_order"}
        ]}}
        self.ext.update_from_run(self.profile, findings, entity_map, {}, "2026-01")
        assert "c_order" in self.profile.focus_tables

    def test_focus_tables_capped_at_10(self):
        entities = {f"tbl_{i}": {"table": f"tbl_{i}"} for i in range(15)}
        entity_map = {"entities": entities}
        findings_list = [
            {"id": f"F-{i:03d}", "title": f"tbl_{i} issue", "severity": "MEDIUM", "sql": f"FROM tbl_{i}"}
            for i in range(15)
        ]
        findings = {"analyst": {"findings": findings_list}}
        self.ext.update_from_run(self.profile, findings, entity_map, {}, "2026-01")
        assert len(self.profile.focus_tables) <= 10


# ===========================================================================
# 9. _extract_kpis_from_report
# ===========================================================================

class TestExtractKpis:

    def setup_method(self):
        self.ext = ProfileExtractor()

    def test_empty_string_returns_empty_list(self):
        assert self.ext._extract_kpis_from_report("") == []

    def test_no_bold_patterns_returns_empty(self):
        assert self.ext._extract_kpis_from_report("plain text without markdown") == []

    def test_basic_bold_kv_extracted(self):
        text = "**Revenue Total**: $5M"
        kpis = self.ext._extract_kpis_from_report(text)
        assert len(kpis) == 1
        assert kpis[0]["label"] == "Revenue Total"

    def test_millions_suffix_numeric_value(self):
        text = "**Ventas Brutas**: 12.3M"
        kpis = self.ext._extract_kpis_from_report(text)
        assert kpis[0]["numeric_value"] == pytest.approx(12_300_000, rel=0.01)

    def test_thousands_suffix_numeric_value(self):
        text = "**Gastos**: 450K"
        kpis = self.ext._extract_kpis_from_report(text)
        assert kpis[0]["numeric_value"] == pytest.approx(450_000, rel=0.01)

    def test_billions_suffix_numeric_value(self):
        text = "**Market Cap**: 2B"
        kpis = self.ext._extract_kpis_from_report(text)
        assert kpis[0]["numeric_value"] == pytest.approx(2_000_000_000, rel=0.01)

    def test_plain_integer_extracted(self):
        text = "**Clientes Activos**: 1234"
        kpis = self.ext._extract_kpis_from_report(text)
        assert kpis[0]["numeric_value"] == pytest.approx(1234)

    def test_numeric_value_none_when_no_number(self):
        text = "**Estado**: Excelente"
        kpis = self.ext._extract_kpis_from_report(text)
        assert kpis[0]["numeric_value"] is None

    def test_capped_at_20_kpis(self):
        lines = "\n".join(f"**KPI Metric {i:02d}**: {i}M" for i in range(30))
        kpis = self.ext._extract_kpis_from_report(lines)
        assert len(kpis) == 20

    def test_multiple_kpis_in_one_report(self):
        text = (
            "## Report\n"
            "**Facturacion Total**: $12.3M\n"
            "**Cobranza Pendiente**: ARS 4.5M (32%)\n"
            "**Clientes Activos**: 123\n"
        )
        kpis = self.ext._extract_kpis_from_report(text)
        labels = [k["label"] for k in kpis]
        assert "Facturacion Total" in labels
        assert "Cobranza Pendiente" in labels
        assert "Clientes Activos" in labels

    def test_value_string_preserved(self):
        text = "**Margen Bruto**: 32%"
        kpis = self.ext._extract_kpis_from_report(text)
        assert kpis[0]["value"] == "32%"


# ===========================================================================
# 10. KPI baseline history accumulation
# ===========================================================================

class TestKpiBaseline:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def _run_with_report(self, period: str, report: str) -> None:
        self.ext.update_from_run(self.profile, {}, {"entities": {}}, {"executive": report}, period)

    def test_kpi_stored_in_baseline_history(self):
        self._run_with_report("2026-01", "**Revenue**: $5M")
        assert "Revenue" in self.profile.baseline_history

    def test_duplicate_period_not_added(self):
        self._run_with_report("2026-01", "**Revenue**: $5M")
        self._run_with_report("2026-01", "**Revenue**: $5M")
        assert len(self.profile.baseline_history["Revenue"]) == 1

    def test_different_periods_both_added(self):
        self._run_with_report("2026-01", "**Revenue**: $5M")
        self._run_with_report("2026-02", "**Revenue**: $6M")
        assert len(self.profile.baseline_history["Revenue"]) == 2

    def test_baseline_history_capped_at_24(self):
        for i in range(30):
            self._run_with_report(f"2026-{i:02d}", f"**Revenue**: ${i}M")
        assert len(self.profile.baseline_history["Revenue"]) <= 24

    def test_no_report_leaves_baseline_unchanged(self):
        self.ext.update_from_run(self.profile, {}, {"entities": {}}, {}, "2026-01")
        assert self.profile.baseline_history == {}


# ===========================================================================
# 11. Edge cases and robustness
# ===========================================================================

class TestEdgeCases:

    def setup_method(self):
        self.ext = ProfileExtractor()
        self.profile = _make_profile()

    def test_non_dict_agent_result_skipped(self):
        delta = self.ext.update_from_run(
            self.profile,
            {"analyst": "not a dict"},
            {"entities": {}}, {}, "2026-01",
        )
        assert delta["new"] == []

    def test_agent_result_with_no_findings_key(self):
        delta = self.ext.update_from_run(
            self.profile,
            {"analyst": {"data": "something else"}},
            {"entities": {}}, {}, "2026-01",
        )
        assert delta["new"] == []

    def test_empty_entity_map_no_crash(self):
        delta = self.ext.update_from_run(
            self.profile, {}, {}, {}, "2026-01"
        )
        assert isinstance(delta, dict)

    def test_entity_map_without_entities_key(self):
        delta = self.ext.update_from_run(
            self.profile,
            _findings_from("a", [_finding("F-001")]),
            {"other_key": {}}, {}, "2026-01",
        )
        # Should not crash; finding is new
        assert "F-001" in delta["new"]

    def test_profile_name_preserved_through_updates(self):
        p = _make_profile("SpecialClient")
        for i in range(3):
            self.ext.update_from_run(p, {}, {"entities": {}}, {}, f"2026-0{i+1}")
        assert p.client_name == "SpecialClient"

    def test_failed_run_still_increments_run_count(self):
        self.ext.update_from_run(
            self.profile, {}, {"entities": {}}, {}, "2026-01", run_success=False
        )
        assert self.profile.run_count == 1

    def test_info_severity_finding_tracked(self):
        delta = self.ext.update_from_run(
            self.profile,
            _findings_from("a", [_finding("INFO-001", severity="INFO")]),
            {"entities": {}}, {}, "2026-01",
        )
        assert "INFO-001" in delta["new"]

    def test_multiple_calls_accumulate_correctly(self):
        ext = ProfileExtractor()
        p = _make_profile()
        for i in range(10):
            findings = _findings_from("a", [_finding(f"F-{i:03d}")])
            ext.update_from_run(p, findings, {"entities": {}}, {}, f"period-{i:03d}")
        assert p.run_count == 10
        # Each run introduced one new finding that was then resolved the next run
        # After all runs, only the last finding should still be known
        assert len(p.known_findings) == 1
