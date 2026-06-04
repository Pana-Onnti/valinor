"""
Unit tests for the narrator grounding metrics (VAL-163 measurement instrument).

Pure / no LLM: every test builds narrator text + ground truth by hand and asserts
the deterministic grounded-rate / hallucination / hedging scoring. The anchor case
is the real Gloria hallucination — €13.5M AR (invented) vs €3.27M AR (verified).
"""

from __future__ import annotations

import pytest

from valinor.quality.narrator_metrics import (
    audit_hedging,
    audit_numbers,
    collect_ground_truth,
    extract_numbers,
    score_narrator_output,
)
from valinor.verification import NumberRegistryEntry, VerificationReport


# ── number extraction ──────────────────────────────────────────────────────

class TestExtractNumbers:
    @pytest.mark.parametrize("text,expected", [
        ("€1.2M", 1_200_000),
        ("€250K", 250_000),
        ("€1,500,000", 1_500_000),
        ("€3.27M", 3_270_000),
        ("€13.5M", 13_500_000),
        ("3 millones", 3_000_000),
        ("5 mil", 5_000),
    ])
    def test_currency_and_suffix(self, text, expected):
        nums = extract_numbers(text)
        assert nums, f"nothing extracted from {text!r}"
        assert nums[0].value == pytest.approx(expected)

    def test_european_decimal_format(self):
        # 1.631.559,62 — dots group, comma decimal
        nums = extract_numbers("La facturación fue 1.631.559,62 EUR")
        assert any(n.value == pytest.approx(1_631_559.62) for n in nums)

    def test_anglo_decimal_format(self):
        nums = extract_numbers("revenue 1,234,567.89")
        assert any(n.value == pytest.approx(1_234_567.89) for n in nums)

    def test_thousands_vs_decimal(self):
        assert extract_numbers("3,139")[0].value == pytest.approx(3139)
        assert extract_numbers("519,77")[0].value == pytest.approx(519.77)

    def test_percent_flagged(self):
        nums = extract_numbers("concentración del 45% y 12.5%")
        pcts = [n for n in nums if n.is_percent]
        assert {round(n.value, 1) for n in pcts} == {45.0, 12.5}

    def test_years_are_skipped(self):
        # "2024" is a year, not a financial figure → not extracted; 616 is.
        nums = extract_numbers("En diciembre de 2024 hubo 616 clientes")
        values = [n.value for n in nums]
        assert 2024 not in values
        assert 616 in values


# ── ground truth ───────────────────────────────────────────────────────────

class TestCollectGroundTruth:
    def test_from_verification_report_registry(self):
        report = VerificationReport(number_registry={
            "ar_outstanding": NumberRegistryEntry(label="ar_outstanding", value=3_267_365.43),
            "revenue": NumberRegistryEntry(label="revenue", value=1_631_559.62),
        })
        truth = collect_ground_truth(verification_report=report)
        assert 3_267_365.43 in truth
        assert 1_631_559.62 in truth

    def test_from_query_results_and_findings(self):
        qr = {"results": {"ar": {"rows": [{"total_outstanding": 3_267_365.43, "customers": 616}]}}}
        findings = {"analyst": {"findings": [{"id": "FIN-001", "value_eur": 1_631_559.62}]}}
        truth = collect_ground_truth(query_results=qr, findings=findings)
        assert 3_267_365.43 in truth
        assert 616 in truth
        assert 1_631_559.62 in truth

    def test_drops_sub_unit_noise(self):
        truth = collect_ground_truth(query_results={"results": {"x": {"rows": [{"a": 0.5, "b": 42}]}}})
        assert 0.5 not in truth
        assert 42 in truth


# ── grounding classification (the moat signal) ─────────────────────────────

class TestAuditNumbers:
    GROUND = [3_267_365.43, 1_631_559.62, 3139.0, 616.0, 1223.0]

    def test_grounded_within_tolerance(self):
        # €3.27M is within 0.5% of 3,267,365.43 → grounded; 616 exact → grounded.
        audit = audit_numbers("Cartera vencida €3.27M sobre 616 clientes", self.GROUND)
        assert audit.total == 2
        assert audit.grounded == 2
        assert audit.ungrounded == 0

    def test_hallucinated_number_flagged(self):
        # €13.5M matches nothing in the ground truth → ungrounded (the real bug).
        audit = audit_numbers("La deuda asciende a €13.5M", self.GROUND)
        assert audit.total == 1
        assert audit.ungrounded == 1
        assert audit.grounded == 0

    def test_percent_tolerance(self):
        # ground-truth percent value 45; 47 within ±2 (grounded), 48 outside.
        assert audit_numbers("47%", [45.0]).grounded == 1
        assert audit_numbers("48%", [45.0]).ungrounded == 1

    def test_count_must_match_exactly(self):
        assert audit_numbers("3139 facturas", [3139.0]).grounded == 1
        assert audit_numbers("3200 facturas", [3139.0]).ungrounded == 1


# ── hedging ────────────────────────────────────────────────────────────────

class TestAuditHedging:
    def test_counts_spanish_and_english(self):
        audit = audit_hedging("La deuda ronda aproximadamente €13M y podría aumentar; roughly stable")
        assert audit.count >= 3  # aproximadamente, podría, roughly
        assert audit.word_count > 0

    def test_grounded_text_has_no_hedging(self):
        audit = audit_hedging("La cartera vencida es €3.27M sobre 616 clientes.")
        assert audit.count == 0

    def test_per_100_words_normalized(self):
        audit = audit_hedging("aproximadamente " * 1 + "uno dos tres cuatro cinco seis siete ocho nueve")
        assert audit.per_100_words == pytest.approx(audit.count / audit.word_count * 100)


# ── end-to-end A/B contrast ────────────────────────────────────────────────

class TestScoreNarratorOutput:
    """Treatment (registry available, numbers cited) must score higher grounding
    and lower hedging than control (no registry, invented numbers)."""

    def _report(self):
        return VerificationReport(number_registry={
            "ar_outstanding": NumberRegistryEntry(label="ar_outstanding", value=3_267_365.43),
            "revenue": NumberRegistryEntry(label="revenue", value=1_631_559.62),
            "customers_with_debt": NumberRegistryEntry(
                label="customers_with_debt", value=616, unit="count"),
        })

    def test_treatment_beats_control(self):
        report = self._report()
        control = "La deuda ronda los €13.5M aproximadamente y podría crecer."
        treatment = "La cartera vencida es €3.27M sobre 616 clientes; facturación €1.63M."

        m_control = score_narrator_output(control, verification_report=report)
        m_treat = score_narrator_output(treatment, verification_report=report)

        assert m_treat.numbers.grounded_rate > m_control.numbers.grounded_rate
        assert m_treat.numbers.grounded_rate == pytest.approx(1.0)
        assert m_control.numbers.grounded_rate == pytest.approx(0.0)
        assert m_control.hedging.count > m_treat.hedging.count

    def test_to_dict_shape(self):
        m = score_narrator_output("€3.27M", verification_report=self._report())
        d = m.to_dict()
        assert set(d) >= {
            "grounded_rate", "hallucinated_rate", "hedging_per_100_words",
            "numbers_total", "word_count",
        }
