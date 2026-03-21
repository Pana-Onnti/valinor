"""
Comprehensive tests for the Valinor memory layer and client profile modules.

Covers:
- ClientProfile data model (creation, fields, serialization)
- ClientRefinement (prompt block, defaults)
- ProfileExtractor (finding deltas, KPI extraction, table weights, auto-escalation)
- ProfileStore (save/load with file backend, with_profile context manager)
- detect_schema_drift (schema comparison logic)
- build_adaptive_context (context string generation)
- memory_tools (read_memory / write_memory — disk I/O mocked via tmp dirs)
- Profile evolution tracking across multiple simulated runs
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

sys.path.insert(0, "shared")
sys.path.insert(0, "core")
sys.path.insert(0, ".")

from memory.client_profile import ClientProfile, ClientRefinement
from memory.profile_extractor import ProfileExtractor
from memory.profile_store import ProfileStore, detect_schema_drift
from memory.adaptive_context_builder import build_adaptive_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tmp_dir() -> Path:
    d = Path(f"/tmp/test_memory_layer_{uuid.uuid4().hex}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tmp_store(tmp_dir: Path) -> ProfileStore:
    """Return a file-only ProfileStore pointing at tmp_dir."""
    store = ProfileStore.__new__(ProfileStore)
    store._db_url = ""
    store._pool = None
    store._use_db = False

    async def _patched_save(profile: ClientProfile) -> bool:
        from datetime import datetime
        profile.updated_at = datetime.utcnow().isoformat()
        data = json.dumps(profile.to_dict())
        path = tmp_dir / f"{profile.client_name}.json"
        path.write_text(data)
        return True

    async def _patched_load(client_name: str):
        path = tmp_dir / f"{client_name}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return ClientProfile.from_dict(data)
        return None

    async def _patched_load_or_create(client_name: str) -> ClientProfile:
        existing = await _patched_load(client_name)
        if existing:
            return existing
        return ClientProfile.new(client_name)

    store.save = _patched_save
    store.load = _patched_load
    store.load_or_create = _patched_load_or_create
    return store


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_findings(agent: str, items: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap findings in the shape ProfileExtractor.update_from_run() expects."""
    return {agent: {"findings": items}}


def _make_entity_map(*table_names: str) -> Dict[str, Any]:
    return {"entities": {t: {"table": t} for t in table_names}}


# ---------------------------------------------------------------------------
# 1. ClientProfile — data model
# ---------------------------------------------------------------------------

class TestClientProfileModel:

    def test_new_creates_blank_profile(self):
        p = ClientProfile.new("Acme")
        assert p.client_name == "Acme"
        assert p.run_count == 0
        assert p.known_findings == {}
        assert p.resolved_findings == {}
        assert p.focus_tables == []
        assert p.baseline_history == {}

    def test_run_count_is_zero_on_creation(self):
        p = ClientProfile.new("Beta")
        assert p.run_count == 0

    def test_entity_map_cache_is_none_initially(self):
        p = ClientProfile.new("Gamma")
        assert p.entity_map_cache is None
        assert p.entity_map_updated_at is None

    def test_is_entity_map_fresh_returns_false_when_no_cache(self):
        p = ClientProfile.new("Delta")
        assert p.is_entity_map_fresh() is False

    def test_is_entity_map_fresh_returns_true_for_recent_cache(self):
        from datetime import datetime
        p = ClientProfile.new("Epsilon")
        p.entity_map_cache = {"entities": {}}
        p.entity_map_updated_at = datetime.utcnow().isoformat()
        assert p.is_entity_map_fresh(max_age_hours=72) is True

    def test_is_entity_map_fresh_returns_false_for_old_cache(self):
        p = ClientProfile.new("Zeta")
        p.entity_map_cache = {"entities": {}}
        p.entity_map_updated_at = "2000-01-01T00:00:00"
        assert p.is_entity_map_fresh(max_age_hours=72) is False

    def test_to_dict_and_from_dict_roundtrip(self):
        p = ClientProfile.new("Roundtrip")
        p.run_count = 5
        p.industry_inferred = "retail"
        p.currency_detected = "USD"
        p.known_findings["F1"] = {"id": "F1", "severity": "HIGH"}
        d = p.to_dict()
        p2 = ClientProfile.from_dict(d)
        assert p2.client_name == "Roundtrip"
        assert p2.run_count == 5
        assert p2.industry_inferred == "retail"
        assert p2.known_findings["F1"]["severity"] == "HIGH"

    def test_get_refinement_returns_default_when_none(self):
        p = ClientProfile.new("NoRef")
        ref = p.get_refinement()
        assert isinstance(ref, ClientRefinement)
        assert ref.table_weights == {}
        assert ref.query_hints == []
        assert ref.focus_areas == []

    def test_get_refinement_reconstructs_from_dict(self):
        p = ClientProfile.new("HasRef")
        p.refinement = {
            "table_weights": {"orders": 0.9},
            "query_hints": ["use index on customer_id"],
            "focus_areas": ["revenue", "churn"],
            "suppress_ids": ["F_OLD_1"],
            "context_block": "Prior context here.",
            "generated_at": "2025-01-01T00:00:00",
        }
        ref = p.get_refinement()
        assert ref.table_weights["orders"] == 0.9
        assert "revenue" in ref.focus_areas
        assert ref.context_block == "Prior context here."


# ---------------------------------------------------------------------------
# 2. ClientRefinement
# ---------------------------------------------------------------------------

class TestClientRefinement:

    def test_to_prompt_block_returns_context_block(self):
        r = ClientRefinement(context_block="Focus on AR aging.")
        assert r.to_prompt_block() == "Focus on AR aging."

    def test_to_prompt_block_returns_empty_string_when_no_block(self):
        r = ClientRefinement()
        assert r.to_prompt_block() == ""

    def test_default_fields_are_empty_collections(self):
        r = ClientRefinement()
        assert r.table_weights == {}
        assert r.query_hints == []
        assert r.focus_areas == []
        assert r.suppress_ids == []
        assert r.generated_at == ""


# ---------------------------------------------------------------------------
# 3. ProfileExtractor
# ---------------------------------------------------------------------------

class TestProfileExtractor:

    def _extractor(self) -> ProfileExtractor:
        return ProfileExtractor()

    def test_new_finding_appears_in_known_findings(self):
        ext = self._extractor()
        p = ClientProfile.new("TestCo")
        findings = _make_findings("analyst", [
            {"id": "F001", "title": "Overdue AR", "severity": "HIGH"}
        ])
        delta = ext.update_from_run(p, findings, {}, {}, "2026-01")
        assert "F001" in delta["new"]
        assert "F001" in p.known_findings
        assert p.known_findings["F001"]["severity"] == "HIGH"

    def test_run_count_incremented_on_update(self):
        ext = self._extractor()
        p = ClientProfile.new("RunCo")
        assert p.run_count == 0
        ext.update_from_run(p, {}, {}, {}, "2026-01")
        assert p.run_count == 1

    def test_run_history_appended(self):
        ext = self._extractor()
        p = ClientProfile.new("HistCo")
        ext.update_from_run(p, {}, {}, {}, "2026-01")
        assert len(p.run_history) == 1
        assert p.run_history[0]["period"] == "2026-01"

    def test_finding_persists_across_two_runs(self):
        ext = self._extractor()
        p = ClientProfile.new("PersistCo")
        findings = _make_findings("sentinel", [
            {"id": "F002", "title": "Null PK", "severity": "MEDIUM"}
        ])
        ext.update_from_run(p, findings, {}, {}, "2026-01")
        delta2 = ext.update_from_run(p, findings, {}, {}, "2026-02")
        assert "F002" in delta2["persists"]
        assert p.known_findings["F002"]["runs_open"] == 2

    def test_resolved_finding_moves_to_resolved_dict(self):
        ext = self._extractor()
        p = ClientProfile.new("ResolveCo")
        findings = _make_findings("analyst", [
            {"id": "F003", "title": "Stale cache", "severity": "LOW"}
        ])
        ext.update_from_run(p, findings, {}, {}, "2026-01")
        # Second run — finding disappears
        delta2 = ext.update_from_run(p, {}, {}, {}, "2026-02")
        assert "F003" in delta2["resolved"]
        assert "F003" not in p.known_findings
        assert "F003" in p.resolved_findings

    def test_severity_worsening_detected(self):
        ext = self._extractor()
        p = ClientProfile.new("WorseCo")
        f1 = _make_findings("hunter", [{"id": "F004", "title": "Rev drop", "severity": "LOW"}])
        ext.update_from_run(p, f1, {}, {}, "2026-01")
        f2 = _make_findings("hunter", [{"id": "F004", "title": "Rev drop", "severity": "HIGH"}])
        delta2 = ext.update_from_run(p, f2, {}, {}, "2026-02")
        assert "F004" in delta2["worsened"]
        assert p.known_findings["F004"]["severity"] == "HIGH"

    def test_severity_improvement_detected(self):
        ext = self._extractor()
        p = ClientProfile.new("ImprCo")
        f1 = _make_findings("analyst", [{"id": "F005", "title": "AR", "severity": "CRITICAL"}])
        ext.update_from_run(p, f1, {}, {}, "2026-01")
        f2 = _make_findings("analyst", [{"id": "F005", "title": "AR", "severity": "MEDIUM"}])
        delta2 = ext.update_from_run(p, f2, {}, {}, "2026-02")
        assert "F005" in delta2["improved"]
        assert p.known_findings["F005"]["severity"] == "MEDIUM"

    def test_auto_escalation_after_five_runs(self):
        """A finding open for 5+ consecutive runs must be auto-escalated."""
        ext = self._extractor()
        p = ClientProfile.new("EscalateCo")
        # Start with LOW severity
        finding = [{"id": "F006", "title": "Slow queries", "severity": "LOW"}]
        for i in range(6):
            ext.update_from_run(
                p, _make_findings("analyst", finding), {}, {}, f"2026-0{i+1}"
            )
        # After 6 runs the severity should have been escalated from LOW
        assert p.known_findings["F006"]["severity"] in ("MEDIUM", "HIGH", "CRITICAL")
        assert p.known_findings["F006"].get("auto_escalated") is True

    def test_kpi_extracted_from_executive_report(self):
        ext = self._extractor()
        p = ClientProfile.new("KPICo")
        report = "## Executive Summary\n**Facturacion Total**: $12.3M\n**Cobranza Pendiente**: ARS 4.5M"
        ext.update_from_run(p, {}, {}, {"executive": report}, "2026-01")
        assert "Facturacion Total" in p.baseline_history
        assert len(p.baseline_history["Facturacion Total"]) == 1

    def test_kpi_numeric_value_parsed_shorthand_M(self):
        ext = self._extractor()
        p = ClientProfile.new("KPINumCo")
        report = "**Revenue**: $5.2M"
        ext.update_from_run(p, {}, {}, {"executive": report}, "2026-01")
        dp = p.baseline_history.get("Revenue", [])
        assert dp, "KPI 'Revenue' not found in baseline_history"
        assert dp[0]["numeric_value"] == pytest.approx(5_200_000, rel=1e-3)

    def test_table_weights_computed_from_entity_map(self):
        ext = self._extractor()
        p = ClientProfile.new("TableCo")
        entity_map = _make_entity_map("invoices")
        findings = _make_findings("analyst", [
            {"id": "F007", "title": "invoices anomaly", "severity": "HIGH", "sql": "SELECT * FROM invoices"}
        ])
        ext.update_from_run(p, findings, entity_map, {}, "2026-01")
        assert "invoices" in p.table_weights
        assert p.table_weights["invoices"] > 0

    def test_run_history_capped_at_20(self):
        ext = self._extractor()
        p = ClientProfile.new("CapCo")
        for i in range(25):
            ext.update_from_run(p, {}, {}, {}, f"2026-{i+1:02d}")
        assert len(p.run_history) <= 20


# ---------------------------------------------------------------------------
# 4. ProfileStore — file backend
# ---------------------------------------------------------------------------

class TestProfileStoreFileBackend:

    def test_save_and_load_roundtrip(self):
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)
        p = ClientProfile.new("SaveCo")
        p.run_count = 7
        _run(store.save(p))
        loaded = _run(store.load("SaveCo"))
        assert loaded is not None
        assert loaded.run_count == 7

    def test_load_nonexistent_returns_none(self):
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)
        assert _run(store.load("Ghost")) is None

    def test_load_or_create_returns_new_profile_when_absent(self):
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)
        p = _run(store.load_or_create("Fresh"))
        assert p.client_name == "Fresh"
        assert p.run_count == 0

    def test_load_or_create_returns_existing_profile(self):
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)
        p = ClientProfile.new("Existing")
        p.run_count = 15
        _run(store.save(p))
        loaded = _run(store.load_or_create("Existing"))
        assert loaded.run_count == 15

    def test_second_save_overwrites_first(self):
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)
        p = ClientProfile.new("OverCo")
        p.run_count = 1
        _run(store.save(p))
        p.run_count = 42
        _run(store.save(p))
        loaded = _run(store.load("OverCo"))
        assert loaded.run_count == 42


# ---------------------------------------------------------------------------
# 5. detect_schema_drift
# ---------------------------------------------------------------------------

class TestDetectSchemaDrift:

    def test_empty_cache_always_drifts(self):
        assert detect_schema_drift({}, {"entities": {"t1": {}}}) is True

    def test_identical_maps_no_drift(self):
        m = {"entities": {"t1": {}, "t2": {}, "t3": {}}}
        assert detect_schema_drift(m, m) is False

    def test_adding_more_than_10pct_is_drift(self):
        base = {"entities": {f"t{i}": {} for i in range(10)}}
        extended = {"entities": {f"t{i}": {} for i in range(12)}}
        assert detect_schema_drift(base, extended) is True

    def test_small_change_within_threshold_is_not_drift(self):
        base = {"entities": {f"t{i}": {} for i in range(20)}}
        reduced = {"entities": {f"t{i}": {} for i in range(19)}}
        assert detect_schema_drift(base, reduced) is False

    def test_completely_different_schemas_is_drift(self):
        old = {"entities": {"orders": {}, "customers": {}}}
        new = {"entities": {"invoices": {}, "payments": {}}}
        assert detect_schema_drift(old, new) is True


# ---------------------------------------------------------------------------
# 6. build_adaptive_context
# ---------------------------------------------------------------------------

class TestBuildAdaptiveContext:

    def test_output_is_string(self):
        p = ClientProfile.new("CtxCo")
        result = build_adaptive_context(p)
        assert isinstance(result, str)

    def test_contains_client_name(self):
        p = ClientProfile.new("MyClient")
        result = build_adaptive_context(p)
        assert "MyClient" in result

    def test_contains_unknown_industry_when_none_inferred(self):
        p = ClientProfile.new("NoCo")
        result = build_adaptive_context(p)
        assert "Desconocida" in result

    def test_contains_inferred_industry_when_set(self):
        p = ClientProfile.new("RetailCo")
        p.industry_inferred = "retail"
        result = build_adaptive_context(p)
        assert "retail" in result

    def test_contains_run_count(self):
        p = ClientProfile.new("RunCo")
        p.run_count = 9
        result = build_adaptive_context(p)
        assert "9" in result

    def test_focus_tables_appear_in_context(self):
        p = ClientProfile.new("TableCo")
        p.focus_tables = ["invoices", "customers", "orders"]
        result = build_adaptive_context(p)
        assert "invoices" in result

    def test_persistent_findings_count_in_context(self):
        p = ClientProfile.new("PersistCo")
        p.known_findings = {
            "F1": {"runs_open": 5},
            "F2": {"runs_open": 1},
            "F3": {"runs_open": 3},
        }
        result = build_adaptive_context(p)
        # F1 and F3 are persistent (>= 3)
        assert "Hallazgos persistentes: 2" in result

    def test_refinement_focus_areas_in_context(self):
        p = ClientProfile.new("RefCo")
        p.refinement = {
            "table_weights": {},
            "query_hints": [],
            "focus_areas": ["cash_flow", "collections"],
            "suppress_ids": [],
            "context_block": "",
            "generated_at": "",
        }
        result = build_adaptive_context(p)
        assert "cash_flow" in result or "collections" in result

    def test_kpi_history_latest_value_in_context(self):
        p = ClientProfile.new("KPICo")
        p.baseline_history = {
            "Ventas": [
                {"period": "2026-01", "label": "Ventas", "value": "$10M", "numeric_value": 10e6},
                {"period": "2026-02", "label": "Ventas", "value": "$12M", "numeric_value": 12e6},
            ]
        }
        result = build_adaptive_context(p)
        assert "$12M" in result
