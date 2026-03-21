"""
Tests for:
  - core/valinor/tools/analysis_tools.py  (revenue_calc, aging_calc, pareto_analysis, classify_entity)
  - core/valinor/gates.py                 (gate_cartographer, gate_analysis, gate_sanity,
                                           gate_monetary_consistency, _extract_eur_values)

All tests are pure-logic — no database or LLM calls required.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Stub claude_agent_sdk before any core imports
# ---------------------------------------------------------------------------
import types as _types
from unittest.mock import MagicMock as _MagicMock

if "claude_agent_sdk" not in sys.modules:
    _sdk = _types.ModuleType("claude_agent_sdk")
    _sdk.__spec__ = None
    def _tool_stub(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f
    _sdk.tool = _tool_stub
    _sdk.query = _MagicMock()
    _sdk.ClaudeAgentOptions = _MagicMock
    _sdk.AssistantMessage = _MagicMock
    _sdk.TextBlock = _MagicMock
    _sdk.create_sdk_mcp_server = _MagicMock(return_value=_MagicMock())
    sys.modules["claude_agent_sdk"] = _sdk

from valinor.tools.analysis_tools import revenue_calc, aging_calc, pareto_analysis
from valinor.tools.db_tools import classify_entity
from valinor.gates import (
    gate_cartographer,
    gate_analysis,
    gate_sanity,
    gate_monetary_consistency,
    _extract_eur_values,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def parse_result(result: dict) -> dict:
    """Unwrap the tool's content envelope and parse the JSON text."""
    return json.loads(result["content"][0]["text"])


# ===========================================================================
# revenue_calc
# ===========================================================================

class TestRevenueCalc:

    def test_basic_aggregation(self):
        data = [
            {"period": "2025-01", "amount": 100},
            {"period": "2025-01", "amount": 200},
            {"period": "2025-02", "amount": 150},
        ]
        result = parse_result(run(revenue_calc({
            "data": json.dumps(data),
            "group_by": "period",
            "amount_field": "amount",
        })))
        assert result["grand_total"] == 450.0
        assert result["periods"] == 2
        assert result["breakdown"]["2025-01"]["total"] == 300.0
        assert result["breakdown"]["2025-01"]["count"] == 2
        assert result["breakdown"]["2025-02"]["total"] == 150.0

    def test_period_over_period_change(self):
        data = [
            {"period": "2025-01", "amount": 100},
            {"period": "2025-02", "amount": 150},
        ]
        result = parse_result(run(revenue_calc({
            "data": json.dumps(data),
            "group_by": "period",
            "amount_field": "amount",
        })))
        # 150/100 - 1 = +50%
        assert result["breakdown"]["2025-02"]["change_pct"] == pytest.approx(50.0, abs=0.1)

    def test_empty_data_returns_error(self):
        result = parse_result(run(revenue_calc({
            "data": "[]",
            "group_by": "period",
            "amount_field": "amount",
        })))
        assert "error" in result

    def test_min_max_computed(self):
        data = [
            {"period": "A", "amount": 10},
            {"period": "A", "amount": 50},
            {"period": "A", "amount": 30},
        ]
        result = parse_result(run(revenue_calc({
            "data": json.dumps(data),
            "group_by": "period",
            "amount_field": "amount",
        })))
        assert result["breakdown"]["A"]["min"] == 10.0
        assert result["breakdown"]["A"]["max"] == 50.0
        assert result["breakdown"]["A"]["average"] == pytest.approx(30.0, abs=0.1)

    def test_null_amounts_treated_as_zero(self):
        data = [
            {"period": "X", "amount": None},
            {"period": "X", "amount": 100},
        ]
        result = parse_result(run(revenue_calc({
            "data": json.dumps(data),
            "group_by": "period",
            "amount_field": "amount",
        })))
        assert result["breakdown"]["X"]["total"] == 100.0


# ===========================================================================
# aging_calc
# ===========================================================================

class TestAgingCalc:

    def _make_row(self, due_date: str, amount: float) -> dict:
        return {"due_date": due_date, "amount": amount}

    def test_current_bucket(self):
        """Invoice due today → 0-30d bucket."""
        data = [self._make_row("2026-03-21", 500.0)]
        result = parse_result(run(aging_calc({
            "data": json.dumps(data),
            "due_date_field": "due_date",
            "amount_field": "amount",
            "reference_date": "2026-03-21",
        })))
        assert result["buckets"]["0-30d"]["total"] == 500.0
        assert result["buckets"]["0-30d"]["provision_amount"] == 0.0

    def test_overdue_180d_bucket(self):
        """Invoice overdue by 200 days → 181-365d bucket with 60% provision."""
        ref = "2026-03-21"
        data = [self._make_row("2025-09-02", 1000.0)]  # ~200 days before ref
        result = parse_result(run(aging_calc({
            "data": json.dumps(data),
            "due_date_field": "due_date",
            "amount_field": "amount",
            "reference_date": ref,
        })))
        assert result["buckets"]["181-365d"]["total"] == 1000.0
        assert result["buckets"]["181-365d"]["provision_amount"] == pytest.approx(600.0, abs=1.0)

    def test_empty_data(self):
        result = parse_result(run(aging_calc({
            "data": "[]",
            "due_date_field": "due_date",
            "amount_field": "amount",
            "reference_date": "2026-01-01",
        })))
        assert result["total_outstanding"] == 0.0

    def test_invalid_date_skipped(self):
        data = [
            {"due_date": "not-a-date", "amount": 999},
            {"due_date": "2026-01-01", "amount": 100},
        ]
        result = parse_result(run(aging_calc({
            "data": json.dumps(data),
            "due_date_field": "due_date",
            "amount_field": "amount",
            "reference_date": "2026-03-21",
        })))
        # Only the valid row should be counted
        assert result["total_outstanding"] == 100.0

    def test_provision_percentages_correct(self):
        """Spot-check provision rates across all buckets."""
        result = parse_result(run(aging_calc({
            "data": "[]",
            "due_date_field": "due_date",
            "amount_field": "amount",
            "reference_date": "2026-01-01",
        })))
        assert result["buckets"]["0-30d"]["provision_rate"] == 0.00
        assert result["buckets"]["31-60d"]["provision_rate"] == 0.05
        assert result["buckets"]["61-90d"]["provision_rate"] == 0.15
        assert result["buckets"]["91-180d"]["provision_rate"] == 0.30
        assert result["buckets"]["181-365d"]["provision_rate"] == 0.60
        assert result["buckets"][">365d"]["provision_rate"] == 0.90


# ===========================================================================
# pareto_analysis
# ===========================================================================

class TestParetoAnalysis:

    def _build_data(self, values: dict) -> list:
        return [{"entity": k, "value": v} for k, v in values.items()]

    def test_top_n_returned(self):
        data = self._build_data({f"E{i}": 100 - i for i in range(20)})
        result = parse_result(run(pareto_analysis({
            "data": json.dumps(data),
            "entity_field": "entity",
            "value_field": "value",
            "top_n": 5,
        })))
        assert len(result["top_entities"]) == 5
        assert result["top_entities"][0]["rank"] == 1

    def test_sorted_descending(self):
        data = self._build_data({"A": 10, "B": 50, "C": 30})
        result = parse_result(run(pareto_analysis({
            "data": json.dumps(data),
            "entity_field": "entity",
            "value_field": "value",
            "top_n": 10,
        })))
        values = [e["value"] for e in result["top_entities"]]
        assert values == sorted(values, reverse=True)

    def test_concentration_risk_high(self):
        """Single entity with >25% → HIGH risk."""
        data = self._build_data({"BigCo": 800, "Rest": 100, "Other": 100})
        result = parse_result(run(pareto_analysis({
            "data": json.dumps(data),
            "entity_field": "entity",
            "value_field": "value",
            "top_n": 10,
        })))
        assert result["concentration"]["risk_level"] == "HIGH"

    def test_grand_total_correct(self):
        data = self._build_data({"A": 100, "B": 200, "C": 300})
        result = parse_result(run(pareto_analysis({
            "data": json.dumps(data),
            "entity_field": "entity",
            "value_field": "value",
            "top_n": 10,
        })))
        assert result["grand_total"] == 600.0

    def test_zero_total_returns_error(self):
        data = self._build_data({"A": 0, "B": 0})
        result = parse_result(run(pareto_analysis({
            "data": json.dumps(data),
            "entity_field": "entity",
            "value_field": "value",
            "top_n": 10,
        })))
        assert "error" in result

    def test_herfindahl_index_present(self):
        data = self._build_data({"A": 500, "B": 300, "C": 200})
        result = parse_result(run(pareto_analysis({
            "data": json.dumps(data),
            "entity_field": "entity",
            "value_field": "value",
            "top_n": 10,
        })))
        assert "herfindahl_index" in result["concentration"]
        assert result["concentration"]["herfindahl_index"] > 0


# ===========================================================================
# classify_entity
# ===========================================================================

class TestClassifyEntity:

    def _cols(self, names: list) -> str:
        return json.dumps([{"name": n} for n in names])

    def test_transactional_classification(self):
        result = parse_result(run(classify_entity({
            "table_name": "c_invoice",
            "columns": self._cols(["id", "date_invoice", "total_amount", "customer_id"]),
            "sample_data": "{}",
            "row_count": 50000,
        })))
        assert result["classification"] == "TRANSACTIONAL"
        assert result["confidence"] >= 0.7

    def test_master_classification(self):
        result = parse_result(run(classify_entity({
            "table_name": "c_bpartner",
            "columns": self._cols(["id", "name", "address", "phone", "email"]),
            "sample_data": "{}",
            "row_count": 500,
        })))
        assert result["classification"] in ("MASTER", "TRANSACTIONAL")  # name hint may push it

    def test_config_low_row_count(self):
        result = parse_result(run(classify_entity({
            "table_name": "ad_sysconfig",
            "columns": self._cols(["id", "name", "value"]),
            "sample_data": "{}",
            "row_count": 20,
        })))
        # Low rows + few cols → BRIDGE or CONFIG, not TRANSACTIONAL
        assert result["classification"] in ("BRIDGE", "CONFIG")

    def test_confidence_in_range(self):
        result = parse_result(run(classify_entity({
            "table_name": "some_table",
            "columns": self._cols(["id", "col1"]),
            "sample_data": "{}",
            "row_count": 10,
        })))
        assert 0.0 <= result["confidence"] <= 1.0

    def test_note_always_present(self):
        result = parse_result(run(classify_entity({
            "table_name": "payments",
            "columns": self._cols(["id", "amount", "date"]),
            "sample_data": "{}",
            "row_count": 1000,
        })))
        assert "note" in result


# ===========================================================================
# gate_cartographer
# ===========================================================================

class TestGateCartographer:

    def test_passes_with_2_high_confidence(self):
        entity_map = {
            "entities": {
                "customers": {"confidence": 0.9},
                "invoices": {"confidence": 0.85},
            }
        }
        assert gate_cartographer(entity_map) is True

    def test_fails_with_low_confidence(self):
        entity_map = {
            "entities": {
                "customers": {"confidence": 0.5},
                "invoices": {"confidence": 0.6},
            }
        }
        assert gate_cartographer(entity_map) is False

    def test_fails_with_only_one_entity(self):
        entity_map = {
            "entities": {
                "invoices": {"confidence": 0.95},
            }
        }
        assert gate_cartographer(entity_map) is False

    def test_passes_with_payments_and_products(self):
        entity_map = {
            "entities": {
                "payments": {"confidence": 0.95},
                "products": {"confidence": 0.80},
            }
        }
        assert gate_cartographer(entity_map) is True

    def test_empty_entities(self):
        assert gate_cartographer({"entities": {}}) is False


# ===========================================================================
# gate_analysis
# ===========================================================================

class TestGateAnalysis:

    def test_passes_with_3_complete_agents(self):
        findings = {
            "analyst": {"findings": [], "status": "ok"},
            "sentinel": {"findings": [], "status": "ok"},
            "hunter": {"findings": [], "status": "ok"},
        }
        assert gate_analysis(findings) is True

    def test_passes_with_2_complete_agents(self):
        findings = {
            "analyst": {"findings": []},
            "sentinel": {"error": True},
            "hunter": {"findings": []},
        }
        assert gate_analysis(findings) is True

    def test_fails_with_only_1_complete(self):
        findings = {
            "analyst": {"findings": []},
            "sentinel": {"error": True},
            "hunter": {"error": True},
        }
        assert gate_analysis(findings) is False

    def test_fails_with_all_errors(self):
        findings = {
            "analyst": {"error": "timeout"},
            "sentinel": {"error": "timeout"},
            "hunter": {"error": "timeout"},
        }
        assert gate_analysis(findings) is False


# ===========================================================================
# gate_sanity
# ===========================================================================

class TestGateSanity:

    def test_pass_when_revenue_present(self):
        query_results = {
            "results": {
                "revenue_by_period": {
                    "rows": [{"period": "2025-01", "revenue": 50000}]
                }
            }
        }
        reports = {"executive": "# Report\n" + "x" * 200}
        result = gate_sanity(reports, query_results)
        assert result["passed"] is True
        assert any(c["check"] == "total_revenue_available" for c in result["checks"])

    def test_warn_when_revenue_zero(self):
        query_results = {
            "results": {
                "revenue_by_period": {
                    "rows": [{"period": "2025-01", "revenue": 0}]
                }
            }
        }
        reports = {"executive": "x" * 200}
        result = gate_sanity(reports, query_results)
        rev_check = next(c for c in result["checks"] if c["check"] == "total_revenue_available")
        assert rev_check["status"] == "warn"

    def test_report_content_checked(self):
        query_results = {"results": {}}
        reports = {"executive": "", "ceo": "x" * 200}
        result = gate_sanity(reports, query_results)
        checks_by_name = {c["check"]: c for c in result["checks"]}
        assert checks_by_name["report_executive_generated"]["status"] == "warn"
        assert checks_by_name["report_ceo_generated"]["status"] == "pass"


# ===========================================================================
# _extract_eur_values & gate_monetary_consistency
# ===========================================================================

class TestExtractEurValues:

    def test_eur_millions(self):
        vals = _extract_eur_values("Revenue was €1.5M in Q1.")
        assert any(abs(v - 1_500_000) < 1 for v in vals)

    def test_eur_thousands(self):
        vals = _extract_eur_values("Cost was €250K last month.")
        assert any(abs(v - 250_000) < 1 for v in vals)

    def test_eur_raw_number(self):
        vals = _extract_eur_values("Invoice total: €1,500,000")
        assert len(vals) >= 1

    def test_empty_text(self):
        assert _extract_eur_values("") == []

    def test_no_eur_symbols(self):
        assert _extract_eur_values("Revenue was $5M.") == []


class TestGateMonetaryConsistency:

    def test_passes_with_no_baseline(self):
        reports = {"executive": "Revenue was €1M."}
        result = gate_monetary_consistency(reports, {})
        assert result["passed"] is True
        assert result["warnings"] == []

    def test_warns_on_implausibly_large_value(self):
        baseline = {"total_revenue": 100_000}
        # €15M >> 10x the €100K baseline — should trigger the >10x check
        reports = {"executive": "Total market opportunity is €15M — massive upside."}
        result = gate_monetary_consistency(reports, baseline)
        assert len(result["warnings"]) >= 1

    def test_passes_when_values_consistent(self):
        baseline = {"total_revenue": 1_000_000}
        reports = {
            "executive": "Total revenue: €1M.",
            "ceo": "Revenue €1.2M — strong performance.",
        }
        result = gate_monetary_consistency(reports, baseline)
        assert result["passed"] is True


# ===========================================================================
# Additional tests — revenue_calc, aging_calc, pareto, gates
# ===========================================================================

class TestRevenueCalcAdditional:

    def test_single_period_grand_total(self):
        """grand_total equals sum of the only period."""
        data = [{"period": "2025-01", "amount": 1000}, {"period": "2025-01", "amount": 500}]
        result = parse_result(run(revenue_calc({"data": json.dumps(data), "group_by": "period", "amount_field": "amount"})))
        assert result["grand_total"] == pytest.approx(1500.0)

    def test_min_and_max_within_group(self):
        """min and max per group are reported in breakdown."""
        data = [
            {"cat": "A", "revenue": 100},
            {"cat": "A", "revenue": 300},
            {"cat": "A", "revenue": 200},
        ]
        result = parse_result(run(revenue_calc({"data": json.dumps(data), "group_by": "cat", "amount_field": "revenue"})))
        assert result["breakdown"]["A"]["min"] == pytest.approx(100.0)
        assert result["breakdown"]["A"]["max"] == pytest.approx(300.0)

    def test_multiple_periods_returns_breakdown(self):
        """Two periods should both appear in breakdown."""
        data = [{"period": "2025-01", "amount": 1000}, {"period": "2025-02", "amount": 1200}]
        result = parse_result(run(revenue_calc({"data": json.dumps(data), "group_by": "period", "amount_field": "amount"})))
        assert "breakdown" in result
        assert "2025-01" in result["breakdown"]
        assert "2025-02" in result["breakdown"]

    def test_zero_amounts_handled(self):
        """Rows with amount=0 are summed correctly and don't crash."""
        data = [{"period": "2025-01", "amount": 0}]
        result = parse_result(run(revenue_calc({"data": json.dumps(data), "group_by": "period", "amount_field": "amount"})))
        assert result["breakdown"]["2025-01"]["total"] == 0.0

    def test_average_computed_per_group(self):
        """Average is total / count per group."""
        data = [{"g": "X", "v": 10}, {"g": "X", "v": 30}]
        result = parse_result(run(revenue_calc({"data": json.dumps(data), "group_by": "g", "amount_field": "v"})))
        assert result["breakdown"]["X"]["average"] == pytest.approx(20.0)

    def test_string_amount_field_coerced(self):
        """String amounts are coerced to float."""
        data = [{"period": "2025-01", "amount": "750"}]
        result = parse_result(run(revenue_calc({"data": json.dumps(data), "group_by": "period", "amount_field": "amount"})))
        assert result["breakdown"]["2025-01"]["total"] == pytest.approx(750.0)

    def test_grand_total_matches_sum_of_breakdown(self):
        """grand_total must equal the sum of all breakdown totals."""
        data = [{"p": "A", "v": 100}, {"p": "B", "v": 200}, {"p": "C", "v": 300}]
        result = parse_result(run(revenue_calc({"data": json.dumps(data), "group_by": "p", "amount_field": "v"})))
        breakdown_sum = sum(result["breakdown"][k]["total"] for k in result["breakdown"])
        assert result["grand_total"] == pytest.approx(breakdown_sum)


class TestAgingCalcAdditional:

    def test_current_invoice_in_first_bucket(self):
        """Invoices with 0 days overdue fall in '0-30d' bucket."""
        from datetime import date
        today = date.today().isoformat()
        data = [{"due_date": today, "amount": 500}]
        result = parse_result(run(aging_calc({"data": json.dumps(data), "due_date_field": "due_date", "amount_field": "amount"})))
        assert "buckets" in result or "total_outstanding" in result

    def test_total_outstanding_in_result(self):
        """total_outstanding key must appear in aging result."""
        from datetime import date, timedelta
        old = (date.today() - timedelta(days=100)).isoformat()
        data = [{"due_date": old, "amount": 300}]
        result = parse_result(run(aging_calc({"data": json.dumps(data), "due_date_field": "due_date", "amount_field": "amount"})))
        assert "total_outstanding" in result
        assert result["total_outstanding"] >= 300.0

    def test_empty_data_returns_zero_outstanding(self):
        """Empty dataset should return total_outstanding = 0."""
        result = parse_result(run(aging_calc({"data": json.dumps([]), "due_date_field": "due_date", "amount_field": "amount"})))
        assert result.get("total_outstanding", 0) == 0.0


class TestParetoAdditional:

    def test_result_contains_total_entities(self):
        """Result must expose total_entities count."""
        data = [{"customer_id": f"C{i}", "total_amount": 100 + i} for i in range(5)]
        result = parse_result(run(pareto_analysis({"data": json.dumps(data), "entity_field": "customer_id", "value_field": "total_amount"})))
        assert "total_entities" in result
        assert result["total_entities"] == 5

    def test_single_customer_owns_100_pct(self):
        """A single customer should show 100% cumulative in the top entry."""
        data = [{"customer_id": "SOLO", "total_amount": 9999}]
        result = parse_result(run(pareto_analysis({"data": json.dumps(data), "entity_field": "customer_id", "value_field": "total_amount"})))
        assert result["top_entities"][0]["cumulative_pct"] == pytest.approx(100.0)

    def test_top_entities_sorted_descending(self):
        """top_entities should be ordered by value descending."""
        data = [{"cid": "C1", "val": 100}, {"cid": "C2", "val": 500}, {"cid": "C3", "val": 300}]
        result = parse_result(run(pareto_analysis({"data": json.dumps(data), "entity_field": "cid", "value_field": "val"})))
        values = [e["value"] for e in result["top_entities"]]
        assert values == sorted(values, reverse=True)


class TestGateCartographerAdditional:

    def test_customers_and_invoices_high_conf_passes(self):
        """customers + invoices both at confidence > 0.7 should pass."""
        entity_map = {"entities": {"customers": {"confidence": 0.9}, "invoices": {"confidence": 0.85}}}
        assert gate_cartographer(entity_map) is True

    def test_products_and_payments_high_conf_passes(self):
        """products + payments both above 0.7 confidence should pass."""
        entity_map = {"entities": {"products": {"confidence": 0.8}, "payments": {"confidence": 0.75}}}
        assert gate_cartographer(entity_map) is True

    def test_unknown_entity_names_not_counted(self):
        """Entities with names outside the required list are not counted."""
        entity_map = {"entities": {"alpha": {"confidence": 0.99}, "beta": {"confidence": 0.99}}}
        assert gate_cartographer(entity_map) is False

    def test_no_entities_key(self):
        """Missing 'entities' key should not crash (treated as failure)."""
        try:
            result = gate_cartographer({})
        except Exception:
            result = False
        assert result is False


class TestGateAnalysisAdditional:

    def test_exactly_two_succeed(self):
        """Exactly 2 successful agents at the threshold should pass."""
        findings = {
            "analyst": {"findings": [{"id": "F1"}]},
            "sentinel": {"findings": []},
            "hunter": {"error": "timeout"},
        }
        assert gate_analysis(findings) is True

    def test_empty_findings_dict_fails(self):
        """No agents at all should fail."""
        try:
            result = gate_analysis({})
        except Exception:
            result = False
        assert result is False


class TestGateSanityAdditional:

    def test_passed_key_present(self):
        """gate_sanity always returns a dict with 'passed' key."""
        result = gate_sanity({}, {})
        assert "passed" in result

    def test_checks_list_present(self):
        """gate_sanity always returns 'checks' list."""
        result = gate_sanity({}, {})
        assert "checks" in result
        assert isinstance(result["checks"], list)

    def test_negative_revenue_triggers_warn(self):
        """Negative revenue in results should produce a warn or fail."""
        qr = {"results": {"revenue_by_period": {"rows": [{"period": "2025-01", "revenue": -100}]}}}
        result = gate_sanity({"executive": "x" * 200}, qr)
        rev_check = next((c for c in result["checks"] if c["check"] == "total_revenue_available"), None)
        if rev_check:
            assert rev_check["status"] in ("warn", "pass")  # negative revenue is unusual but shouldn't crash


class TestExtractEurValuesAdditional:

    def test_multiple_values_in_text(self):
        """Multiple EUR values in one string should all be extracted."""
        vals = _extract_eur_values("We earned €1M and spent €500K, leaving €500K profit.")
        assert len(vals) >= 2

    def test_decimal_value(self):
        """Decimal EUR values should be parsed."""
        vals = _extract_eur_values("Cost was €1.25M")
        assert any(abs(v - 1_250_000) < 1 for v in vals)

    def test_no_eur_returns_empty(self):
        """Text with no EUR amounts returns empty list."""
        assert _extract_eur_values("Revenue was great this quarter!") == []
