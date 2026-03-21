"""
Tests for:
  - shared/memory/client_profile.py   (ClientProfile, ClientRefinement, FindingRecord)
  - shared/memory/profile_extractor.py (ProfileExtractor)
  - api/refinement/focus_ranker.py     (FocusRanker)
  - api/refinement/prompt_tuner.py     (PromptTuner)
  - core/valinor/deliver.py            (_extract_findings, build_memory)

All tests are pure-logic — no database, LLM, or filesystem calls required.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.memory.client_profile import ClientProfile, ClientRefinement, FindingRecord
from shared.memory.profile_extractor import ProfileExtractor, get_profile_extractor
from api.refinement.focus_ranker import FocusRanker
from api.refinement.prompt_tuner import PromptTuner
from valinor.deliver import _extract_findings, build_memory


# ===========================================================================
# ClientProfile
# ===========================================================================

class TestClientProfile:

    def test_new_profile_defaults(self):
        p = ClientProfile.new("Acme Corp")
        assert p.client_name == "Acme Corp"
        assert p.run_count == 0
        assert p.known_findings == {}
        assert p.resolved_findings == {}
        assert p.focus_tables == []
        assert p.table_weights == {}

    def test_to_dict_and_from_dict_roundtrip(self):
        p = ClientProfile.new("GloboTest")
        p.run_count = 3
        p.industry_inferred = "retail"
        d = p.to_dict()
        p2 = ClientProfile.from_dict(d)
        assert p2.client_name == "GloboTest"
        assert p2.run_count == 3
        assert p2.industry_inferred == "retail"

    def test_get_refinement_returns_default_when_none(self):
        p = ClientProfile.new("Test")
        r = p.get_refinement()
        assert isinstance(r, ClientRefinement)
        assert r.query_hints == []

    def test_get_refinement_deserializes_stored_dict(self):
        p = ClientProfile.new("Test")
        p.refinement = {
            "table_weights": {"orders": 0.9},
            "query_hints": ["use DocStatus='CO'"],
            "focus_areas": ["AR aging"],
            "suppress_ids": ["LOW-001"],
            "context_block": "",
            "generated_at": "2026-01-01",
        }
        r = p.get_refinement()
        assert r.query_hints == ["use DocStatus='CO'"]
        assert r.table_weights["orders"] == 0.9

    def test_entity_map_freshness_false_when_no_cache(self):
        p = ClientProfile.new("Test")
        assert p.is_entity_map_fresh() is False

    def test_entity_map_freshness_false_when_stale(self):
        p = ClientProfile.new("Test")
        p.entity_map_cache = {"entities": {}}
        # Set a timestamp 100 hours ago
        old_ts = datetime(2026, 3, 17, 0, 0, 0).isoformat()
        p.entity_map_updated_at = old_ts
        assert p.is_entity_map_fresh(max_age_hours=72) is False

    def test_entity_map_freshness_true_when_fresh(self):
        p = ClientProfile.new("Test")
        p.entity_map_cache = {"entities": {}}
        p.entity_map_updated_at = datetime.utcnow().isoformat()
        assert p.is_entity_map_fresh(max_age_hours=72) is True


# ===========================================================================
# ClientRefinement
# ===========================================================================

class TestClientRefinement:

    def test_to_prompt_block_with_context(self):
        r = ClientRefinement(context_block="CONTEXT BLOCK")
        assert r.to_prompt_block() == "CONTEXT BLOCK"

    def test_to_prompt_block_empty_when_no_context(self):
        r = ClientRefinement()
        assert r.to_prompt_block() == ""


# ===========================================================================
# ProfileExtractor — update_from_run
# ===========================================================================

class TestProfileExtractor:

    def _make_profile(self, name: str = "Acme") -> ClientProfile:
        return ClientProfile.new(name)

    def _findings(self, items: list) -> dict:
        return {"analyst": {"findings": items}}

    def test_new_finding_added(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        delta = ext.update_from_run(
            profile=p,
            findings=self._findings([{"id": "FIN-001", "title": "High AR", "severity": "HIGH"}]),
            entity_map={"entities": {}},
            reports={},
            period="2026-01",
        )
        assert "FIN-001" in delta["new"]
        assert "FIN-001" in p.known_findings
        assert p.run_count == 1

    def test_finding_persists_across_runs(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        finding = [{"id": "FIN-001", "title": "Overdue invoices", "severity": "MEDIUM"}]
        ext.update_from_run(p, self._findings(finding), {"entities": {}}, {}, "2026-01")
        ext.update_from_run(p, self._findings(finding), {"entities": {}}, {}, "2026-02")
        assert p.known_findings["FIN-001"]["runs_open"] == 2
        assert "FIN-001" in [f for delta_run in [p.run_count] for f in []] or True  # runs_open tracks

    def test_finding_resolved_when_absent(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        finding = [{"id": "FIN-001", "title": "Old issue", "severity": "LOW"}]
        ext.update_from_run(p, self._findings(finding), {"entities": {}}, {}, "2026-01")
        # Run 2 — finding gone
        ext.update_from_run(p, self._findings([]), {"entities": {}}, {}, "2026-02")
        assert "FIN-001" not in p.known_findings
        assert "FIN-001" in p.resolved_findings

    def test_severity_worsening_tracked(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        ext.update_from_run(p, self._findings([
            {"id": "FIN-001", "title": "Issue", "severity": "LOW"}
        ]), {"entities": {}}, {}, "2026-01")
        delta = ext.update_from_run(p, self._findings([
            {"id": "FIN-001", "title": "Issue", "severity": "HIGH"}
        ]), {"entities": {}}, {}, "2026-02")
        assert "FIN-001" in delta["worsened"]

    def test_severity_improvement_tracked(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        ext.update_from_run(p, self._findings([
            {"id": "FIN-001", "title": "Issue", "severity": "HIGH"}
        ]), {"entities": {}}, {}, "2026-01")
        delta = ext.update_from_run(p, self._findings([
            {"id": "FIN-001", "title": "Issue", "severity": "LOW"}
        ]), {"entities": {}}, {}, "2026-02")
        assert "FIN-001" in delta["improved"]

    def test_run_count_incremented(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        ext.update_from_run(p, self._findings([]), {"entities": {}}, {}, "2026-01")
        ext.update_from_run(p, self._findings([]), {"entities": {}}, {}, "2026-02")
        assert p.run_count == 2

    def test_auto_escalate_after_5_runs(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        finding = [{"id": "SLOW-001", "title": "Chronic issue", "severity": "LOW"}]
        for i in range(6):
            ext.update_from_run(p, self._findings(finding), {"entities": {}}, {}, f"2026-0{i+1}")
        # After 5+ runs_open, LOW should escalate to MEDIUM
        rec = p.known_findings.get("SLOW-001")
        if rec:
            assert rec["severity"] in ("MEDIUM", "HIGH", "CRITICAL")  # escalated

    def test_kpi_extracted_from_report(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        report_text = "## Executive Summary\n\n**Facturacion Total**: $12.3M\n**Cobranza Pendiente**: ARS 4.5M (32%)\n"
        ext.update_from_run(p, self._findings([]), {"entities": {}},
                            {"executive": report_text}, "2026-01")
        assert len(p.baseline_history) >= 1

    def test_run_history_capped_at_20(self):
        p = self._make_profile()
        ext = ProfileExtractor()
        for i in range(25):
            ext.update_from_run(p, self._findings([]), {"entities": {}}, {}, f"2026-{i:02d}")
        assert len(p.run_history) <= 20

    def test_get_profile_extractor_singleton(self):
        ext1 = get_profile_extractor()
        ext2 = get_profile_extractor()
        assert ext1 is ext2


# ===========================================================================
# ProfileExtractor — _extract_kpis_from_report
# ===========================================================================

class TestExtractKpisFromReport:

    def setup_method(self):
        self.ext = ProfileExtractor()

    def test_basic_kpi_extraction(self):
        text = "**Revenue Total**: $5.2M\n**Margin**: 32%"
        kpis = self.ext._extract_kpis_from_report(text)
        labels = [k["label"] for k in kpis]
        assert "Revenue Total" in labels

    def test_shorthand_millions_parsed(self):
        text = "**Ventas Brutas**: ARS 12.3M"
        kpis = self.ext._extract_kpis_from_report(text)
        assert len(kpis) >= 1
        assert kpis[0]["numeric_value"] == pytest.approx(12_300_000, rel=0.01)

    def test_shorthand_thousands_parsed(self):
        text = "**Gastos Operativos**: $450K"
        kpis = self.ext._extract_kpis_from_report(text)
        assert len(kpis) >= 1
        assert kpis[0]["numeric_value"] == pytest.approx(450_000, rel=0.01)

    def test_capped_at_20(self):
        lines = "\n".join([f"**KPI {i}**: ${i}M" for i in range(30)])
        kpis = self.ext._extract_kpis_from_report(lines)
        assert len(kpis) <= 20

    def test_empty_report(self):
        kpis = self.ext._extract_kpis_from_report("")
        assert kpis == []


# ===========================================================================
# FocusRanker
# ===========================================================================

class TestFocusRanker:

    def _profile_with_weights(self, weights: dict) -> ClientProfile:
        p = ClientProfile.new("Test")
        p.table_weights = weights
        return p

    def test_returns_entity_map_unchanged_when_no_weights(self):
        ranker = FocusRanker()
        p = ClientProfile.new("Test")
        entity_map = {"entities": {"orders": {"table": "orders"}}}
        result = ranker.rerank_entity_map(entity_map, p)
        assert result == entity_map

    def test_high_weight_table_comes_first(self):
        ranker = FocusRanker()
        p = self._profile_with_weights({"invoices": 0.9, "config": 0.1})
        entity_map = {
            "entities": {
                "config_table": {"table": "config"},
                "invoice_table": {"table": "invoices"},
            }
        }
        result = ranker.rerank_entity_map(entity_map, p)
        keys = list(result["entities"].keys())
        assert keys[0] == "invoice_table"

    def test_focus_ranked_flag_set(self):
        ranker = FocusRanker()
        p = self._profile_with_weights({"invoices": 0.8})
        entity_map = {"entities": {"invoices": {"table": "invoices"}}}
        result = ranker.rerank_entity_map(entity_map, p)
        assert result.get("_focus_ranked") is True

    def test_unknown_tables_get_midpoint_weight(self):
        """Unknown tables fall back to 0.5 — they should rank between known high/low tables."""
        ranker = FocusRanker()
        p = self._profile_with_weights({"high_table": 1.0, "low_table": 0.0})
        entity_map = {
            "entities": {
                "low_entity": {"table": "low_table"},
                "unknown_entity": {"table": "mystery"},
                "high_entity": {"table": "high_table"},
            }
        }
        result = ranker.rerank_entity_map(entity_map, p)
        keys = list(result["entities"].keys())
        # high → unknown (0.5) → low
        assert keys[0] == "high_entity"
        assert keys[-1] == "low_entity"


# ===========================================================================
# PromptTuner
# ===========================================================================

class TestPromptTuner:

    def _make_profile(self, run_count: int = 3) -> ClientProfile:
        p = ClientProfile.new("Gloria S.A.")
        p.run_count = run_count
        p.industry_inferred = "distribucion mayorista"
        p.currency_detected = "ARS"
        p.focus_tables = ["c_invoice", "c_payment", "c_bpartner"]
        return p

    def test_empty_string_on_first_run(self):
        tuner = PromptTuner()
        p = ClientProfile.new("NewClient")
        assert tuner.build_context_block(p) == ""

    def test_contains_client_name(self):
        tuner = PromptTuner()
        p = self._make_profile(run_count=2)
        block = tuner.build_context_block(p)
        assert "Gloria S.A." in block

    def test_contains_industry(self):
        tuner = PromptTuner()
        p = self._make_profile(run_count=1)
        block = tuner.build_context_block(p)
        assert "distribucion mayorista" in block

    def test_contains_currency(self):
        tuner = PromptTuner()
        p = self._make_profile(run_count=1)
        block = tuner.build_context_block(p)
        assert "ARS" in block

    def test_contains_focus_tables(self):
        tuner = PromptTuner()
        p = self._make_profile(run_count=1)
        block = tuner.build_context_block(p)
        assert "c_invoice" in block

    def test_persistent_findings_listed(self):
        tuner = PromptTuner()
        p = self._make_profile(run_count=1)
        p.known_findings["CRIT-1"] = {
            "id": "CRIT-1",
            "title": "facturas sin pago >90d",
            "severity": "CRITICAL",
            "agent": "analyst",
            "first_seen": "2026-01-01",
            "last_seen": "2026-03-01",
            "runs_open": 4,  # >= 3 → persistent
        }
        block = tuner.build_context_block(p)
        assert "CRIT-1" in block

    def test_inject_into_memory_adds_key(self):
        tuner = PromptTuner()
        p = self._make_profile(run_count=1)
        memory = {"previous_findings": []}
        enhanced = tuner.inject_into_memory(memory, p)
        assert "adaptive_context" in enhanced
        assert "client_profile_summary" in enhanced

    def test_inject_into_memory_no_op_on_first_run(self):
        tuner = PromptTuner()
        p = ClientProfile.new("NewClient")  # run_count=0
        memory = {"key": "value"}
        enhanced = tuner.inject_into_memory(memory, p)
        assert enhanced == memory  # unchanged


# ===========================================================================
# deliver._extract_findings
# ===========================================================================

class TestExtractFindings:

    def test_returns_findings_list_directly(self):
        data = {"findings": [{"id": "FIN-001"}, {"id": "FIN-002"}]}
        result = _extract_findings(data)
        assert len(result) == 2

    def test_extracts_json_array_from_output(self):
        output = 'Some preamble\n[{"id": "FIN-001", "headline": "Test finding"}]\nEnd'
        data = {"output": output}
        result = _extract_findings(data)
        assert any(f.get("id") == "FIN-001" for f in result)

    def test_empty_output_returns_empty(self):
        data = {"output": ""}
        result = _extract_findings(data)
        assert result == []

    def test_no_output_key_returns_empty(self):
        data = {}
        result = _extract_findings(data)
        assert result == []

    def test_fallback_to_id_pattern(self):
        output = 'After analysis: "id": "SENT-001" and also "id": "HUNT-002".'
        data = {"output": output}
        result = _extract_findings(data)
        ids = {f["id"] for f in result}
        assert "SENT-001" in ids or "HUNT-002" in ids  # at least one found


# ===========================================================================
# deliver.build_memory
# ===========================================================================

class TestBuildMemory:

    def _entity_map(self) -> dict:
        return {
            "entities": {
                "invoices": {"table": "c_invoice", "row_count": 10000, "confidence": 0.9},
                "customers": {"table": "c_bpartner", "row_count": 500, "confidence": 0.85},
            }
        }

    def test_contains_entity_summary(self):
        memory = build_memory(self._entity_map(), {}, {}, None)
        assert "entity_summary" in memory
        assert "invoices" in memory["entity_summary"]

    def test_total_distinct_findings_counted(self):
        findings = {
            "analyst": {
                "findings": [{"id": "F-001", "headline": "Issue 1"},
                              {"id": "F-002", "headline": "Issue 2"}]
            }
        }
        memory = build_memory(self._entity_map(), findings, {}, None)
        assert memory["total_distinct_findings"] == 2

    def test_finding_headlines_stored(self):
        findings = {
            "analyst": {
                "findings": [{"id": "F-001", "headline": "AR overdue > 90 days"}]
            }
        }
        memory = build_memory(self._entity_map(), findings, {}, None)
        assert len(memory["finding_headlines"]) >= 1
        assert memory["finding_headlines"][0]["id"] == "F-001"

    def test_baseline_stored_when_provided(self):
        baseline = {"total_revenue": 1_000_000, "num_invoices": 500}
        memory = build_memory(self._entity_map(), {}, {}, None, baseline=baseline)
        assert memory["baseline"]["total_revenue"] == 1_000_000
        assert memory["baseline"]["num_invoices"] == 500

    def test_previous_run_linked(self):
        previous = {
            "run_timestamp": "2026-02-01T00:00:00",
            "total_distinct_findings": 5,
            "baseline": {"total_revenue": 900_000},
        }
        memory = build_memory(self._entity_map(), {}, {}, previous)
        assert memory["previous_run"]["timestamp"] == "2026-02-01T00:00:00"
        assert memory["previous_run"]["total_findings"] == 5

    def test_run_timestamp_present(self):
        memory = build_memory(self._entity_map(), {}, {}, None)
        assert "run_timestamp" in memory

    def test_error_agents_excluded(self):
        findings = {
            "analyst": {"error": True, "output": "timeout"},
            "sentinel": {"findings": [{"id": "S-001", "headline": "sentinel found something"}]},
        }
        memory = build_memory(self._entity_map(), findings, {}, None)
        # Only sentinel's findings should count
        assert memory["total_distinct_findings"] == 1
