"""
Tests for narrator agent system prompts and narrator modules.

Covers build_executive_system_prompt() — verifying Output KO methodology
injection, DQ/factor context, currency detection, supplementary sections
(Benford, CUSUM, Sentinel, Segmentation, Currency, Persistent Findings,
Query Evolution) and all edge cases defined in the spec.

Also covers:
- All narrator agent modules (executive, ceo, controller, sales, quality_certifier)
- system_prompts.py constants and build_* functions
- Edge cases: empty inputs, None values, very long strings, unicode characters
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest

# ---------------------------------------------------------------------------
# Stub claude_agent_sdk before importing any narrator modules
# ---------------------------------------------------------------------------

if "claude_agent_sdk" not in sys.modules:
    _sdk = types.ModuleType("claude_agent_sdk")
    _sdk.__spec__ = None

    def _tool_stub(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f

    async def _query_stub(*args, **kwargs):
        return
        yield  # make it an async generator

    class _ClaudeAgentOptions:
        def __init__(self, model="sonnet", system_prompt="", max_turns=20, **kwargs):
            self.model = model
            self.system_prompt = system_prompt
            self.max_turns = max_turns

    class _TextBlock:
        def __init__(self, text: str = ""):
            self.text = text

    class _AssistantMessage:
        def __init__(self, content=None):
            self.content = content or []

    _sdk.tool = _tool_stub
    _sdk.query = _query_stub
    _sdk.ClaudeAgentOptions = _ClaudeAgentOptions
    _sdk.AssistantMessage = _AssistantMessage
    _sdk.TextBlock = _TextBlock
    _sdk.create_sdk_mcp_server = MagicMock(return_value=MagicMock())
    sys.modules["claude_agent_sdk"] = _sdk

from valinor.agents.narrators.system_prompts import (  # noqa: E402
    build_executive_system_prompt,
    OUTPUT_KO_PRINCIPLES,
    DATA_QUALITY_INSTRUCTION,
    FACTOR_MODEL_INSTRUCTION,
    EXECUTIVE_SYSTEM_PROMPT,
)
from valinor.agents.narrators.quality_certifier import certify_report  # noqa: E402


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


# ---------------------------------------------------------------------------
# TestSystemPromptsEdgeCases
# ---------------------------------------------------------------------------

class TestSystemPromptsEdgeCases:
    """Edge cases for build_executive_system_prompt()."""

    # 16. None values for all optional memory keys are handled gracefully
    def test_none_values_do_not_raise(self):
        memory = {
            "data_quality_context": None,
            "factor_model_context": None,
            "adaptive_context": None,
            "run_history_summary": None,
            "currency_context": None,
            "segmentation_context": None,
            "sentinel_patterns": None,
            "cusum_warning": None,
            "benford_warning": None,
            "query_evolution_context": None,
            "statistical_anomalies": None,
        }
        try:
            result = build_executive_system_prompt(memory)
        except Exception as exc:
            pytest.fail(f"build_executive_system_prompt raised with None values: {exc}")
        assert isinstance(result, str)
        assert len(result) > 0

    # 17. Very long dq_context string is included verbatim
    def test_very_long_dq_context_included(self):
        long_ctx = "DQ check: " + ("x" * 5000)
        memory = {"data_quality_context": long_ctx}
        result = build_executive_system_prompt(memory)
        assert long_ctx in result

    # 18. Unicode characters in context are preserved
    def test_unicode_in_context_preserved(self):
        memory = {
            "data_quality_context": "Verificación: ✓ datos válidos — «calidad alta»",
            "segmentation_context": "Champions: 日本語テスト",
        }
        result = build_executive_system_prompt(memory)
        assert "✓" in result
        assert "日本語テスト" in result

    # 19. adaptive_context as non-dict string leaves currency as EUR (default)
    def test_adaptive_context_as_non_dict_string_defaults_eur(self):
        memory = {"adaptive_context": "some raw string without structure"}
        result = build_executive_system_prompt(memory)
        assert "EUR" in result

    # 20. run_history_summary with empty persistent_findings list → no HALLAZGOS section
    def test_empty_persistent_findings_no_section(self):
        memory = {"run_history_summary": {"persistent_findings": []}}
        result = build_executive_system_prompt(memory)
        assert "HALLAZGOS PERSISTENTES" not in result

    # 21. Multiple supplementary sections all appear in a single call
    def test_all_supplementary_sections_simultaneously(self):
        memory = {
            "benford_warning": "Benford alert",
            "cusum_warning": "CUSUM break",
            "sentinel_patterns": "Fraud pattern",
            "segmentation_context": "Segment data",
            "currency_context": "Multi-currency",
        }
        result = build_executive_system_prompt(memory)
        assert "ALERTA LEY DE BENFORD" in result
        assert "RUPTURA ESTRUCTURAL" in result
        assert "PATRONES DE FRAUDE" in result
        assert "SEGMENTACIÓN" in result
        assert "CONTEXTO DE MONEDA" in result

    # 22. query_evolution_context dict with ONLY empty_queries (no high_value_tables)
    def test_query_evolution_dict_only_empty_queries(self):
        memory = {"query_evolution_context": {"empty_queries": ["qA", "qB", "qC"]}}
        result = build_executive_system_prompt(memory)
        assert "EVOLUCIÓN DE CONSULTAS" in result
        assert "qA" in result

    # 23. query_evolution_context dict with ONLY high_value_tables (no empty_queries)
    def test_query_evolution_dict_only_high_value_tables(self):
        memory = {"query_evolution_context": {"high_value_tables": ["ventas", "compras"]}}
        result = build_executive_system_prompt(memory)
        assert "EVOLUCIÓN DE CONSULTAS" in result
        assert "ventas" in result

    # 24. query_evolution_context dict with empty lists → section NOT added
    def test_query_evolution_dict_all_empty_lists_no_section(self):
        memory = {"query_evolution_context": {"empty_queries": [], "high_value_tables": []}}
        result = build_executive_system_prompt(memory)
        assert "EVOLUCIÓN DE CONSULTAS" not in result

    # 25. persistent_findings with missing title key is handled without crash
    def test_persistent_findings_missing_title_no_crash(self):
        memory = {
            "run_history_summary": {
                "persistent_findings": [
                    {"runs_open": 3},  # no 'title' key
                    {"title": "Valid finding", "runs_open": 5},
                ]
            }
        }
        try:
            result = build_executive_system_prompt(memory)
        except Exception as exc:
            pytest.fail(f"Raised on missing title: {exc}")
        assert "Valid finding" in result


# ---------------------------------------------------------------------------
# TestSystemPromptsConstants
# ---------------------------------------------------------------------------

class TestSystemPromptsConstants:
    """Tests that verify the module-level constant strings."""

    # 26. OUTPUT_KO_PRINCIPLES is a non-empty string
    def test_output_ko_principles_is_non_empty_string(self):
        assert isinstance(OUTPUT_KO_PRINCIPLES, str)
        assert len(OUTPUT_KO_PRINCIPLES) > 0

    # 27. OUTPUT_KO_PRINCIPLES contains the three obligatory steps
    def test_output_ko_principles_has_three_steps(self):
        assert "CONCLUSIÓN PRIMERO" in OUTPUT_KO_PRINCIPLES
        assert "EVIDENCIA" in OUTPUT_KO_PRINCIPLES
        assert "ACCIÓN RECOMENDADA" in OUTPUT_KO_PRINCIPLES

    # 28. DATA_QUALITY_INSTRUCTION template has {dq_context} placeholder
    def test_dq_instruction_has_placeholder(self):
        assert "{dq_context}" in DATA_QUALITY_INSTRUCTION

    # 29. DATA_QUALITY_INSTRUCTION describes the DQ score thresholds
    def test_dq_instruction_mentions_score_thresholds(self):
        assert "65" in DATA_QUALITY_INSTRUCTION
        assert "85" in DATA_QUALITY_INSTRUCTION

    # 30. FACTOR_MODEL_INSTRUCTION template has {factor_context} placeholder
    def test_factor_instruction_has_placeholder(self):
        assert "{factor_context}" in FACTOR_MODEL_INSTRUCTION

    # 31. EXECUTIVE_SYSTEM_PROMPT has all required format placeholders
    def test_executive_prompt_has_all_placeholders(self):
        for placeholder in ("{output_ko}", "{dq_instruction}", "{factor_instruction}", "{currency}"):
            assert placeholder in EXECUTIVE_SYSTEM_PROMPT, (
                f"Missing placeholder {placeholder} in EXECUTIVE_SYSTEM_PROMPT"
            )


# ---------------------------------------------------------------------------
# TestQualityCertifierExtended
# ---------------------------------------------------------------------------

class TestQualityCertifierExtended:
    """Additional tests for certify_report() edge cases."""

    _REPORT = "## Análisis\n\n**Revenue**: €50,000 (Q1-2025)."

    # 32. Score exactly 65 adds footer (boundary condition)
    def test_score_exactly_65_adds_footer(self):
        result = certify_report(self._REPORT, "PROVISIONAL", dq_score=65.0)
        assert "---" in result
        assert "65" in result

    # 33. Score exactly 85 adds footer with supplied confidence_label
    def test_score_exactly_85_uses_supplied_label(self):
        result = certify_report(self._REPORT, "CONFIRMED", dq_score=85.0)
        assert "CONFIRMED" in result

    # 34. Score just below 65 (64.9) → no footer added
    def test_score_below_65_no_footer(self):
        result = certify_report(self._REPORT, "UNVERIFIED", dq_score=64.9)
        assert result == self._REPORT

    # 35. Score 0 → no footer added (below threshold)
    def test_score_zero_no_footer(self):
        result = certify_report(self._REPORT, "BLOCKED", dq_score=0.0)
        assert result == self._REPORT

    # 36. Score 100 → footer contains 9/9
    def test_score_100_footer_contains_nine_of_nine(self):
        result = certify_report(self._REPORT, "CONFIRMED", dq_score=100.0)
        assert "9/9" in result

    # 37. certify_report with unicode report text preserves content
    def test_unicode_report_preserved(self):
        unicode_report = "## Reporte\n\n**Facturación**: €840K — clientes Champions ✓"
        result = certify_report(unicode_report, "CONFIRMED", dq_score=90.0)
        assert unicode_report in result
        assert "✓" in result

    # 38. certify_report footer format: score, label, and controls count all present
    def test_footer_format_complete(self):
        result = certify_report(self._REPORT, "CONFIRMED", dq_score=90.0)
        assert "Calidad de datos" in result
        assert "90" in result
        assert "CONFIRMED" in result
        assert "9/9" in result


# ---------------------------------------------------------------------------
# TestNarratorAgentImports
# ---------------------------------------------------------------------------

class TestNarratorAgentImports:
    """Smoke-tests that all narrator modules import and expose their public API."""

    # 39. executive.py imports and exposes narrate_executive as a coroutine function
    def test_executive_module_imports(self):
        import asyncio
        from valinor.agents.narrators.executive import narrate_executive
        assert asyncio.iscoroutinefunction(narrate_executive)

    # 40. ceo.py imports and exposes narrate_ceo as a coroutine function
    def test_ceo_module_imports(self):
        import asyncio
        from valinor.agents.narrators.ceo import narrate_ceo
        assert asyncio.iscoroutinefunction(narrate_ceo)

    # 41. controller.py imports and exposes narrate_controller as a coroutine function
    def test_controller_module_imports(self):
        import asyncio
        from valinor.agents.narrators.controller import narrate_controller
        assert asyncio.iscoroutinefunction(narrate_controller)

    # 42. sales.py imports and exposes narrate_sales as a coroutine function
    def test_sales_module_imports(self):
        import asyncio
        from valinor.agents.narrators.sales import narrate_sales
        assert asyncio.iscoroutinefunction(narrate_sales)

    # 43. quality_certifier.py exports certify_report as a callable
    def test_quality_certifier_imports(self):
        from valinor.agents.narrators.quality_certifier import certify_report
        assert callable(certify_report)


# ---------------------------------------------------------------------------
# TestNarratorAgentStubBehavior
# ---------------------------------------------------------------------------

class TestNarratorAgentStubBehavior:
    """
    Tests that narrator agents return an empty string (not raise) when the
    claude_agent_sdk stub yields no messages — the expected no-SDK behavior.
    """

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _minimal_client_config(self):
        return {
            "name": "Test Client",
            "display_name": "Test Client S.A.",
            "sector": "distribución",
            "currency": "EUR",
            "language": "es",
        }

    def _minimal_baseline(self):
        return {
            "data_available": False,
            "total_revenue": None,
            "_provenance": {},
        }

    # 44. narrate_executive returns a string (possibly empty) without raising
    def test_executive_returns_string_with_stub(self):
        from valinor.agents.narrators.executive import narrate_executive
        result = self._run(narrate_executive(
            findings={},
            entity_map={"entities": {}},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
        ))
        assert isinstance(result, str)

    # 45. narrate_ceo returns a string (possibly empty) without raising
    def test_ceo_returns_string_with_stub(self):
        from valinor.agents.narrators.ceo import narrate_ceo
        result = self._run(narrate_ceo(
            findings={},
            entity_map={"entities": {}},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
        ))
        assert isinstance(result, str)

    # 46. narrate_controller returns a string (possibly empty) without raising
    def test_controller_returns_string_with_stub(self):
        from valinor.agents.narrators.controller import narrate_controller
        result = self._run(narrate_controller(
            findings={},
            entity_map={"entities": {}},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
            query_results={"results": {}, "errors": {}},
        ))
        assert isinstance(result, str)

    # 47. narrate_sales returns a string (possibly empty) without raising
    def test_sales_returns_string_with_stub(self):
        from valinor.agents.narrators.sales import narrate_sales
        result = self._run(narrate_sales(
            findings={},
            entity_map={"entities": {}},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
            query_results={"results": {}, "errors": {}},
        ))
        assert isinstance(result, str)

    # 48. narrate_executive with memory dict does not raise
    def test_executive_with_memory_does_not_raise(self):
        from valinor.agents.narrators.executive import narrate_executive
        memory = {
            "adaptive_context": {"currency": "USD"},
            "data_quality_context": "DQ Score: 88",
            "run_history_summary": {"persistent_findings": [
                {"title": "Overdue AR", "runs_open": 4}
            ]},
        }
        result = self._run(narrate_executive(
            findings={"analyst": {"findings": []}},
            entity_map={"entities": {}},
            memory=memory,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
        ))
        assert isinstance(result, str)

    # 49. narrate_ceo with memory dict does not raise
    def test_ceo_with_memory_does_not_raise(self):
        from valinor.agents.narrators.ceo import narrate_ceo
        result = self._run(narrate_ceo(
            findings={"analyst": {"findings": [{"id": "F1", "severity": "HIGH"}]}},
            entity_map={"entities": {"invoices": {"table": "account_move"}}},
            memory={"run_history_summary": {"currency": "MXN"}},
            client_config=self._minimal_client_config(),
            baseline={
                "data_available": True,
                "total_revenue": 250_000.0,
                "_provenance": {"total_revenue": {"source_query": "rev", "confidence": "measured"}},
            },
        ))
        assert isinstance(result, str)

    # 50. narrate_controller with query_results containing actual key data
    def test_controller_with_key_query_results(self):
        from valinor.agents.narrators.controller import narrate_controller
        qr = {
            "results": {
                "total_revenue_summary": {
                    "rows": [{"total_revenue": 100_000.0}],
                    "columns": ["total_revenue"],
                    "row_count": 1,
                },
                "ar_outstanding_actual": {
                    "rows": [{"total_outstanding": 15_000.0}],
                    "columns": ["total_outstanding"],
                    "row_count": 1,
                },
            },
            "errors": {},
        }
        result = self._run(narrate_controller(
            findings={},
            entity_map={"entities": {}},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
            query_results=qr,
        ))
        assert isinstance(result, str)

    # 51. narrate_sales with customer query results
    def test_sales_with_customer_query_results(self):
        from valinor.agents.narrators.sales import narrate_sales
        qr = {
            "results": {
                "dormant_customer_list": {
                    "rows": [
                        {"name": "Acme Corp", "id": 1, "days_since_purchase": 120},
                    ],
                    "columns": ["name", "id", "days_since_purchase"],
                    "row_count": 1,
                }
            },
            "errors": {},
        }
        result = self._run(narrate_sales(
            findings={},
            entity_map={"entities": {}},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
            query_results=qr,
        ))
        assert isinstance(result, str)

    # 52. narrate_executive with unicode client name does not raise
    def test_executive_unicode_client_name(self):
        from valinor.agents.narrators.executive import narrate_executive
        client = dict(self._minimal_client_config())
        client["display_name"] = "Distribuidora Ñoño & Cía. Ltda."
        result = self._run(narrate_executive(
            findings={},
            entity_map={},
            memory=None,
            client_config=client,
            baseline=self._minimal_baseline(),
        ))
        assert isinstance(result, str)

    # 53. narrate_ceo with empty entity_map and findings does not raise
    def test_ceo_empty_entity_map(self):
        from valinor.agents.narrators.ceo import narrate_ceo
        result = self._run(narrate_ceo(
            findings={},
            entity_map={},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
        ))
        assert isinstance(result, str)

    # 54. narrate_controller with fiscal_context field in client_config
    def test_controller_with_fiscal_context(self):
        from valinor.agents.narrators.controller import narrate_controller
        client = dict(self._minimal_client_config())
        client["fiscal_context"] = "Argentina NIIF"
        result = self._run(narrate_controller(
            findings={},
            entity_map={"entities": {}},
            memory=None,
            client_config=client,
            baseline=self._minimal_baseline(),
            query_results={"results": {}, "errors": {}},
        ))
        assert isinstance(result, str)

    # 55. narrate_sales with empty query results falls back to agent findings
    def test_sales_empty_query_results_no_customer_data(self):
        from valinor.agents.narrators.sales import narrate_sales
        result = self._run(narrate_sales(
            findings={"analyst": {"findings": [{"id": "S1", "headline": "Dormant clients"}]}},
            entity_map={"entities": {}},
            memory=None,
            client_config=self._minimal_client_config(),
            baseline=self._minimal_baseline(),
            query_results={"results": {}, "errors": {}},
        ))
        assert isinstance(result, str)

    # 56. build_executive_system_prompt with statistical_anomalies section
    def test_statistical_anomalies_section_injected(self):
        memory = {"statistical_anomalies": "Outlier: 3 invoices at 1000x average"}
        result = build_executive_system_prompt(memory)
        assert "ANOMALÍAS ESTADÍSTICAS" in result
        assert "Outlier: 3 invoices" in result

    # 57. build_executive_system_prompt with adaptive_context as dict with extra keys
    def test_adaptive_context_dict_extra_keys_ignored(self):
        memory = {
            "adaptive_context": {
                "currency": "JPY",
                "unknown_field": "value_xyz",
                "another_unknown": 42,
            }
        }
        result = build_executive_system_prompt(memory)
        assert "JPY" in result
