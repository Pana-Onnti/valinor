"""
Tests for narrator agent system prompts.

Covers build_executive_system_prompt() — verifying Output KO methodology
injection, DQ/factor context, currency detection, supplementary sections
(Benford, CUSUM, Sentinel, Segmentation, Currency, Persistent Findings,
Query Evolution) and all edge cases defined in the spec.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest

from valinor.agents.narrators.system_prompts import build_executive_system_prompt


# ---------------------------------------------------------------------------
# TestSystemPrompts
# ---------------------------------------------------------------------------

class TestSystemPrompts:
    """Tests for build_executive_system_prompt(memory: dict) -> str."""

    # 1. Empty memory returns a non-empty string
    def test_empty_memory_returns_non_empty_string(self):
        result = build_executive_system_prompt({})
        assert isinstance(result, str)
        assert len(result) > 0

    # 2. Output KO principles section is included
    def test_output_ko_principles_included(self):
        result = build_executive_system_prompt({})
        assert "CONCLUSIÓN PRIMERO" in result

    # 3. Default currency is EUR when memory has no currency info
    def test_currency_eur_default(self):
        result = build_executive_system_prompt({})
        assert "EUR" in result

    # 4. Currency is extracted from adaptive_context dict
    def test_currency_extracted_from_adaptive_context(self):
        memory = {"adaptive_context": {"currency": "USD"}}
        result = build_executive_system_prompt(memory)
        assert "USD" in result

    # 5. data_quality_context is injected into the prompt
    def test_dq_context_injected(self):
        memory = {"data_quality_context": "DQ Score: 72"}
        result = build_executive_system_prompt(memory)
        assert "DQ Score: 72" in result

    # 6. factor_model_context is injected into the prompt
    def test_factor_context_injected(self):
        memory = {"factor_model_context": "Revenue decomp"}
        result = build_executive_system_prompt(memory)
        assert "Revenue decomp" in result

    # 7. benford_warning triggers ALERTA LEY DE BENFORD section
    def test_benford_warning_injected(self):
        memory = {"benford_warning": "Benford alert"}
        result = build_executive_system_prompt(memory)
        assert "ALERTA LEY DE BENFORD" in result
        assert "Benford alert" in result

    # 8. cusum_warning triggers RUPTURA ESTRUCTURAL section
    def test_cusum_warning_injected(self):
        memory = {"cusum_warning": "Structural break"}
        result = build_executive_system_prompt(memory)
        assert "RUPTURA ESTRUCTURAL" in result
        assert "Structural break" in result

    # 9. sentinel_patterns triggers PATRONES DE FRAUDE section
    def test_sentinel_patterns_injected(self):
        memory = {"sentinel_patterns": "Fraud detected"}
        result = build_executive_system_prompt(memory)
        assert "PATRONES DE FRAUDE" in result
        assert "Fraud detected" in result

    # 10. segmentation_context triggers SEGMENTACIÓN section
    def test_segmentation_context_injected(self):
        memory = {"segmentation_context": "50 champions"}
        result = build_executive_system_prompt(memory)
        assert "SEGMENTACIÓN" in result
        assert "50 champions" in result

    # 11. currency_context triggers CONTEXTO DE MONEDA section
    def test_currency_context_injected(self):
        memory = {"currency_context": "multi-currency"}
        result = build_executive_system_prompt(memory)
        assert "CONTEXTO DE MONEDA" in result
        assert "multi-currency" in result

    # 12. persistent_findings in run_history_summary triggers HALLAZGOS PERSISTENTES section
    def test_persistent_findings_injected(self):
        memory = {
            "run_history_summary": {
                "persistent_findings": [
                    {"title": "Low cash", "runs_open": 5}
                ]
            }
        }
        result = build_executive_system_prompt(memory)
        assert "HALLAZGOS PERSISTENTES" in result
        assert "Low cash" in result

    # 13. query_evolution_context as dict triggers EVOLUCIÓN DE CONSULTAS section
    def test_query_evolution_dict_injected(self):
        memory = {
            "query_evolution_context": {
                "empty_queries": ["q1"],
                "high_value_tables": ["ventas"],
            }
        }
        result = build_executive_system_prompt(memory)
        assert "EVOLUCIÓN DE CONSULTAS" in result
        assert "q1" in result
        assert "ventas" in result

    # 14. query_evolution_context as string is included in the prompt
    def test_query_evolution_string_injected(self):
        memory = {"query_evolution_context": "empty: q1"}
        result = build_executive_system_prompt(memory)
        assert "empty: q1" in result

    # 15. Currency from run_history_summary overrides the default
    def test_currency_from_run_history_summary(self):
        memory = {"run_history_summary": {"currency": "BRL"}}
        result = build_executive_system_prompt(memory)
        assert "BRL" in result
