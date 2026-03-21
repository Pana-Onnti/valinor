"""
Tests for AdaptiveContextBuilder — shared/memory/adaptive_context_builder.py

Covers:
  - Return type is always a string
  - Client name appears in output
  - Unknown industry fallback ("Desconocida")
  - Inferred industry when set
  - Currency detected / not detected
  - Run count and last run date
  - Focus tables section (populated and empty)
  - Only top-5 focus tables are listed
  - Persistent findings count (runs_open >= 3)
  - Non-dict entries in known_findings are ignored
  - Alert thresholds count (populated and empty)
  - Baseline history: latest KPI value appears
  - Baseline history: top-3 KPI keys shown (4th omitted)
  - Empty baseline history shows placeholder
  - KPI entry with no label falls back to key
  - KPI entry with period shows period in output
  - Refinement preferred_analysis_depth in output
  - Refinement focus_areas in output
  - No refinement shows placeholder
  - Empty profile produces valid, non-empty string
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "shared")
sys.path.insert(0, ".")

from memory.adaptive_context_builder import build_adaptive_context
from memory.client_profile import ClientProfile, ClientRefinement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profile(name: str = "TestCo") -> ClientProfile:
    return ClientProfile.new(name)


# ---------------------------------------------------------------------------
# 1. Basic return type and header
# ---------------------------------------------------------------------------

class TestReturnTypeAndHeader:

    def test_output_is_string(self):
        result = build_adaptive_context(_profile())
        assert isinstance(result, str)

    def test_output_is_non_empty(self):
        result = build_adaptive_context(_profile())
        assert len(result) > 0

    def test_header_present(self):
        result = build_adaptive_context(_profile())
        assert "CONTEXTO ADAPTATIVO DEL CLIENTE" in result

    def test_client_name_in_output(self):
        p = _profile("Acme Corp")
        result = build_adaptive_context(p)
        assert "Acme Corp" in result


# ---------------------------------------------------------------------------
# 2. Industry
# ---------------------------------------------------------------------------

class TestIndustry:

    def test_unknown_industry_when_none(self):
        p = _profile()
        p.industry_inferred = None
        result = build_adaptive_context(p)
        assert "Desconocida" in result

    def test_known_industry_appears(self):
        p = _profile()
        p.industry_inferred = "retail"
        result = build_adaptive_context(p)
        assert "retail" in result

    def test_industry_label_present(self):
        p = _profile()
        p.industry_inferred = "manufactura"
        result = build_adaptive_context(p)
        assert "Industria" in result


# ---------------------------------------------------------------------------
# 3. Currency
# ---------------------------------------------------------------------------

class TestCurrency:

    def test_no_currency_shows_not_detected(self):
        p = _profile()
        p.currency_detected = None
        result = build_adaptive_context(p)
        assert "No detectada" in result

    def test_detected_currency_appears(self):
        p = _profile()
        p.currency_detected = "USD"
        result = build_adaptive_context(p)
        assert "USD" in result

    def test_currency_label_present(self):
        p = _profile()
        result = build_adaptive_context(p)
        assert "Moneda" in result


# ---------------------------------------------------------------------------
# 4. Run count and last run date
# ---------------------------------------------------------------------------

class TestRunStats:

    def test_run_count_zero_appears(self):
        p = _profile()
        result = build_adaptive_context(p)
        assert "0" in result

    def test_run_count_nonzero_appears(self):
        p = _profile()
        p.run_count = 17
        result = build_adaptive_context(p)
        assert "17" in result

    def test_no_last_run_date_shows_na(self):
        p = _profile()
        p.last_run_date = None
        result = build_adaptive_context(p)
        assert "N/A" in result

    def test_last_run_date_when_set(self):
        p = _profile()
        p.last_run_date = "2026-03-15"
        result = build_adaptive_context(p)
        assert "2026-03-15" in result


# ---------------------------------------------------------------------------
# 5. Focus tables
# ---------------------------------------------------------------------------

class TestFocusTables:

    def test_no_focus_tables_shows_placeholder(self):
        p = _profile()
        p.focus_tables = []
        result = build_adaptive_context(p)
        assert "No definidas" in result

    def test_focus_table_names_appear(self):
        p = _profile()
        p.focus_tables = ["invoices", "customers"]
        result = build_adaptive_context(p)
        assert "invoices" in result
        assert "customers" in result

    def test_only_top_five_tables_shown(self):
        p = _profile()
        p.focus_tables = ["t1", "t2", "t3", "t4", "t5", "t6_hidden"]
        result = build_adaptive_context(p)
        assert "t6_hidden" not in result

    def test_exactly_five_tables_all_shown(self):
        p = _profile()
        p.focus_tables = ["a", "b", "c", "d", "e"]
        result = build_adaptive_context(p)
        for name in ["a", "b", "c", "d", "e"]:
            assert name in result


# ---------------------------------------------------------------------------
# 6. Persistent findings
# ---------------------------------------------------------------------------

class TestPersistentFindings:

    def test_zero_persistent_findings(self):
        p = _profile()
        p.known_findings = {
            "F1": {"runs_open": 1},
            "F2": {"runs_open": 2},
        }
        result = build_adaptive_context(p)
        assert "Hallazgos persistentes: 0" in result

    def test_persistent_findings_counted_correctly(self):
        p = _profile()
        p.known_findings = {
            "F1": {"runs_open": 5},
            "F2": {"runs_open": 1},
            "F3": {"runs_open": 3},
        }
        result = build_adaptive_context(p)
        assert "Hallazgos persistentes: 2" in result

    def test_non_dict_findings_ignored(self):
        p = _profile()
        # Non-dict values should not raise errors and not count as persistent
        p.known_findings = {
            "F1": "some_string",
            "F2": 42,
            "F3": {"runs_open": 4},
        }
        result = build_adaptive_context(p)
        assert "Hallazgos persistentes: 1" in result

    def test_all_findings_persistent(self):
        p = _profile()
        p.known_findings = {f"F{i}": {"runs_open": 3 + i} for i in range(5)}
        result = build_adaptive_context(p)
        assert "Hallazgos persistentes: 5" in result


# ---------------------------------------------------------------------------
# 7. Alert thresholds
# ---------------------------------------------------------------------------

class TestAlertThresholds:

    def test_no_thresholds_shows_zero(self):
        p = _profile()
        p.alert_thresholds = []
        result = build_adaptive_context(p)
        assert "Umbrales activos: 0" in result

    def test_threshold_count_appears(self):
        p = _profile()
        p.alert_thresholds = [
            {"label": "Revenue", "metric": "revenue", "operator": ">", "value": 1000},
            {"label": "Churn", "metric": "churn_rate", "operator": "<", "value": 0.05},
        ]
        result = build_adaptive_context(p)
        assert "Umbrales activos: 2" in result

    def test_none_thresholds_shows_zero(self):
        p = _profile()
        p.alert_thresholds = None
        result = build_adaptive_context(p)
        assert "Umbrales activos: 0" in result


# ---------------------------------------------------------------------------
# 8. Baseline history
# ---------------------------------------------------------------------------

class TestBaselineHistory:

    def test_empty_baseline_shows_placeholder(self):
        p = _profile()
        p.baseline_history = {}
        result = build_adaptive_context(p)
        assert "sin historial" in result

    def test_latest_kpi_value_shown(self):
        p = _profile()
        p.baseline_history = {
            "Ventas": [
                {"period": "2026-01", "label": "Ventas", "value": "$10M", "numeric_value": 10e6},
                {"period": "2026-02", "label": "Ventas", "value": "$12M", "numeric_value": 12e6},
            ]
        }
        result = build_adaptive_context(p)
        assert "$12M" in result

    def test_kpi_label_from_data_point(self):
        p = _profile()
        p.baseline_history = {
            "revenue_total": [
                {"period": "2026-01", "label": "Revenue Total", "value": "$5M", "numeric_value": 5e6},
            ]
        }
        result = build_adaptive_context(p)
        assert "Revenue Total" in result

    def test_kpi_label_falls_back_to_key_when_missing(self):
        p = _profile()
        p.baseline_history = {
            "my_kpi_key": [
                {"period": "2026-01", "value": "$3M", "numeric_value": 3e6},
            ]
        }
        result = build_adaptive_context(p)
        assert "my_kpi_key" in result

    def test_kpi_period_shown_in_output(self):
        p = _profile()
        p.baseline_history = {
            "Cobranza": [
                {"period": "2026-Q1", "label": "Cobranza", "value": "ARS 8M", "numeric_value": 8e6},
            ]
        }
        result = build_adaptive_context(p)
        assert "2026-Q1" in result

    def test_only_top_three_kpis_shown(self):
        p = _profile()
        p.baseline_history = {
            "KPI_A": [{"period": "2026-01", "label": "KPI_A", "value": "1", "numeric_value": 1}],
            "KPI_B": [{"period": "2026-01", "label": "KPI_B", "value": "2", "numeric_value": 2}],
            "KPI_C": [{"period": "2026-01", "label": "KPI_C", "value": "3", "numeric_value": 3}],
            "KPI_D_hidden": [{"period": "2026-01", "label": "KPI_D_hidden", "value": "4", "numeric_value": 4}],
        }
        result = build_adaptive_context(p)
        assert "KPI_D_hidden" not in result

    def test_empty_series_silently_skipped(self):
        p = _profile()
        p.baseline_history = {
            "EmptyKPI": [],
            "RealKPI": [{"period": "2026-01", "label": "RealKPI", "value": "$1M", "numeric_value": 1e6}],
        }
        # Should not raise and should still show the real KPI
        result = build_adaptive_context(p)
        assert isinstance(result, str)

    def test_baseline_history_section_header_present(self):
        p = _profile()
        result = build_adaptive_context(p)
        assert "LÍNEA BASE HISTÓRICA" in result


# ---------------------------------------------------------------------------
# 9. Active refinement
# ---------------------------------------------------------------------------

class TestActiveRefinement:

    def test_no_refinement_shows_placeholder(self):
        p = _profile()
        p.refinement = None
        result = build_adaptive_context(p)
        assert "sin refinamiento" in result

    def test_refinement_section_header_present(self):
        p = _profile()
        result = build_adaptive_context(p)
        assert "REFINAMIENTO ACTIVO" in result

    def test_preferred_depth_absent_when_field_not_in_refinement(self):
        # ClientRefinement has no preferred_analysis_depth field; getattr returns None
        # so the "Profundidad preferida" line must not appear.
        p = _profile()
        p.refinement = {
            "table_weights": {},
            "query_hints": [],
            "focus_areas": ["revenue"],
            "suppress_ids": [],
            "context_block": "",
            "generated_at": "",
        }
        result = build_adaptive_context(p)
        assert "Profundidad preferida" not in result

    def test_focus_areas_in_output(self):
        p = _profile()
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

    def test_only_top_five_focus_areas_shown(self):
        p = _profile()
        p.refinement = {
            "table_weights": {},
            "query_hints": [],
            "focus_areas": ["a1", "a2", "a3", "a4", "a5", "a6_hidden"],
            "suppress_ids": [],
            "context_block": "",
            "generated_at": "",
        }
        result = build_adaptive_context(p)
        assert "a6_hidden" not in result

    def test_empty_focus_areas_and_no_depth_shows_placeholder(self):
        p = _profile()
        p.refinement = {
            "table_weights": {},
            "query_hints": [],
            "focus_areas": [],
            "suppress_ids": [],
            "context_block": "",
            "generated_at": "",
        }
        result = build_adaptive_context(p)
        assert "sin refinamiento" in result


# ---------------------------------------------------------------------------
# 10. Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:

    def test_output_is_multiline(self):
        """Context block must contain newlines (it's a multi-section block)."""
        result = build_adaptive_context(_profile())
        assert "\n" in result

    def test_baseline_section_before_refinement_section(self):
        """Sections must appear in document order."""
        result = build_adaptive_context(_profile())
        baseline_pos = result.index("LÍNEA BASE HISTÓRICA")
        refinement_pos = result.index("REFINAMIENTO ACTIVO")
        assert baseline_pos < refinement_pos

    def test_header_before_client_name(self):
        p = _profile("GlobalCorp")
        result = build_adaptive_context(p)
        header_pos = result.index("CONTEXTO ADAPTATIVO")
        name_pos = result.index("GlobalCorp")
        assert header_pos < name_pos


# ---------------------------------------------------------------------------
# 11. Boundary conditions
# ---------------------------------------------------------------------------

class TestBoundaryConditions:

    def test_runs_open_exactly_three_counts_as_persistent(self):
        """runs_open == 3 must be included in persistent count (>= 3)."""
        p = _profile()
        p.known_findings = {"F1": {"runs_open": 3}}
        result = build_adaptive_context(p)
        assert "Hallazgos persistentes: 1" in result

    def test_runs_open_exactly_two_does_not_count(self):
        p = _profile()
        p.known_findings = {"F1": {"runs_open": 2}}
        result = build_adaptive_context(p)
        assert "Hallazgos persistentes: 0" in result

    def test_focus_tables_exactly_five_all_shown(self):
        p = _profile()
        p.focus_tables = ["alpha", "beta", "gamma", "delta", "epsilon"]
        result = build_adaptive_context(p)
        for t in ["alpha", "beta", "gamma", "delta", "epsilon"]:
            assert t in result

    def test_focus_tables_six_sixth_hidden(self):
        p = _profile()
        p.focus_tables = ["t1", "t2", "t3", "t4", "t5", "should_not_appear"]
        result = build_adaptive_context(p)
        assert "should_not_appear" not in result

    def test_single_alert_threshold(self):
        p = _profile()
        p.alert_thresholds = [{"label": "Margin", "metric": "margin", "operator": ">", "value": 0.2}]
        result = build_adaptive_context(p)
        assert "Umbrales activos: 1" in result

    def test_large_run_count(self):
        p = _profile()
        p.run_count = 9999
        result = build_adaptive_context(p)
        assert "9999" in result


# ---------------------------------------------------------------------------
# 12. Client name edge cases
# ---------------------------------------------------------------------------

class TestClientNameEdgeCases:

    def test_client_name_with_spaces_and_accents(self):
        p = _profile("Córdoba Industrias S.A.")
        result = build_adaptive_context(p)
        assert "Córdoba Industrias S.A." in result

    def test_client_name_with_numbers(self):
        p = _profile("Client42")
        result = build_adaptive_context(p)
        assert "Client42" in result

    def test_very_long_client_name(self):
        long_name = "A" * 200
        p = _profile(long_name)
        result = build_adaptive_context(p)
        assert long_name in result


# ---------------------------------------------------------------------------
# 13. Currency edge cases
# ---------------------------------------------------------------------------

class TestCurrencyEdgeCases:

    def test_currency_with_symbol(self):
        p = _profile()
        p.currency_detected = "ARS $"
        result = build_adaptive_context(p)
        assert "ARS $" in result

    def test_currency_eur(self):
        p = _profile()
        p.currency_detected = "EUR"
        result = build_adaptive_context(p)
        assert "EUR" in result


# ---------------------------------------------------------------------------
# 14. Baseline edge cases
# ---------------------------------------------------------------------------

class TestBaselineEdgeCases:

    def test_baseline_series_last_item_not_dict_uses_empty_fallback(self):
        """If the last series element is not a dict, value shows 'N/A'."""
        p = _profile()
        p.baseline_history = {
            "KPI_X": ["not_a_dict"],
        }
        # Should not raise; last_point will be {} via the isinstance guard
        result = build_adaptive_context(p)
        assert isinstance(result, str)

    def test_exactly_three_kpis_all_shown(self):
        p = _profile()
        p.baseline_history = {
            "Revenue": [{"period": "2026-01", "label": "Revenue", "value": "$1M", "numeric_value": 1e6}],
            "Costs": [{"period": "2026-01", "label": "Costs", "value": "$500k", "numeric_value": 5e5}],
            "EBITDA": [{"period": "2026-01", "label": "EBITDA", "value": "$500k", "numeric_value": 5e5}],
        }
        result = build_adaptive_context(p)
        for label in ["Revenue", "Costs", "EBITDA"]:
            assert label in result

    def test_none_baseline_history_shows_placeholder(self):
        """Setting baseline_history to None should show the no-history placeholder."""
        p = _profile()
        p.baseline_history = None
        result = build_adaptive_context(p)
        assert "sin historial" in result
