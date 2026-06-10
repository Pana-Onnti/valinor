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


class TestDateMasking:
    """VAL-192 N1 Bug-2 — calendar dates/times are not numeric claims.

    Anchored on real Gloria narrator text (run 2026-05-08): deadlines like
    "viernes 10 mayo 2026" produced false-positive hallucinated numbers.
    """

    def test_day_month_deadline_not_extracted(self):
        assert extract_numbers("**Deadline: viernes 10 mayo 2026**") == []
        assert extract_numbers("lista priorizada el 12 mayo; llamadas antes del 16 mayo 2026") == []
        assert extract_numbers("retractado el 31 de mayo") == []

    def test_iso_dates_not_extracted(self):
        # "2025-01-02" must not leak "01"/"02" as claims.
        assert extract_numbers("Ventana de análisis: 2025-01-02 → 2025-03-31") == []
        assert extract_numbers("Generado por Valinor v0 — 2026-05-08T14:05:56Z") == []

    def test_slash_dates_masked_but_ratios_kept(self):
        assert extract_numbers("entregado el 12/05/2026") == []
        # "36/70 claims (51%)" — counts and percents stay countable.
        values = [n.value for n in extract_numbers("36/70 claims verificados (51%)")]
        assert 36 in values and 70 in values and 51 in values

    def test_durations_stay_countable(self):
        # "147 días" is a data claim (data_freshness.days_since_latest), not a date.
        values = [n.value for n in extract_numbers("el gap de 147 días impide confirmar")]
        assert values == [147.0]

    def test_q1_label_not_extracted(self):
        assert extract_numbers("El Q1 2025 cerró plano") == []

    def test_score_out_of_100_kept(self):
        values = [n.value for n in extract_numbers("deal_risk_score de 80,7/100")]
        assert 80.7 in values


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


class TestStringNumericGroundTruth:
    """VAL-192 N1 Bug-1 — DB drivers serialize NUMERIC as strings.

    Anchor: ISKAY PET ltv_eur="364517.30" (string) was a real, grounded number
    that the instrument marked hallucinated in the first VAL-163 datapoint.
    """

    QR = {"concentration_top_customers": {"rows": [{
        "customer_id": "159599AA4E4245AFAFF4D67D1521386F",   # hex UUID → out
        "ltv_eur": "364517.30",                               # string numeric → in
        "share_pct": "14.87",                                 # string percent → in
        "last_purchase": "2025-06-19",                        # date → out
    }]}}

    def test_string_numerics_enter_ground_truth(self):
        truth = collect_ground_truth(query_results=self.QR)
        assert 364517.30 in truth
        assert 14.87 in truth

    def test_dates_and_uuids_stay_out(self):
        truth = collect_ground_truth(query_results=self.QR)
        # "2025-06-19" must not contribute 2025/6/19; UUID contributes nothing.
        assert 19.0 not in truth
        assert 2025.0 not in truth

    def test_iskay_pet_now_grounded(self):
        truth = collect_ground_truth(query_results=self.QR)
        audit = audit_numbers("ISKAY PET concentra €364.517,30 (14,87%)", truth)
        assert audit.grounded == 2
        assert audit.ungrounded == 0

    def test_postgres_interval_grounds_duration(self):
        qr = {"data_freshness": {"rows": [{"days_since_latest": "147 days, 0:00:00"}]}}
        truth = collect_ground_truth(query_results=qr)
        assert 147.0 in truth
        assert audit_numbers("el gap de 147 días", truth).grounded == 1

    def test_negative_string_matches_magnitude(self):
        qr = {"summary": {"rows": [{"min_invoice": "-4389.05"}]}}
        truth = collect_ground_truth(query_results=qr)
        assert audit_numbers("nota de crédito de €4.389,05", truth).grounded == 1


class TestBug3Boundary:
    """VAL-192 N1 Bug-3 — the evidence-set boundary for legitimate derivations.

    Measured on the 2026-05-08 Gloria narrators: corpus-wide pairwise crediting
    grounds arbitrary planning numbers → rejected. The three rules that survive:
    findings prose is input, declared estimates aren't fabrication, and
    within-column arithmetic is opt-in (a config dimension of eval.py).
    """

    def test_findings_prose_numbers_are_ground_truth(self):
        # Sentinel wrote "doble conteo de €20,520–€51,300" inside a finding —
        # the narrator repeating it is faithful to its input, not fabricating.
        findings = {"sentinel": {"findings": [
            {"id": "DQ-001", "desc": "posible doble conteo de €20,520–€51,300 en c_invoice"},
        ]}}
        truth = collect_ground_truth(findings=findings)
        audit = audit_numbers("Estimación del doble-conteo: €20.520–€51.300", truth)
        assert audit.grounded == 2
        assert audit.ungrounded == 0

    def test_declared_estimate_not_hallucinated(self):
        audit = audit_numbers("Impacto reducción 30% volumen: -€109,355 [ESTIMADO — analyst]", [30.0])
        assert audit.declared == 1
        assert audit.ungrounded == 0
        # declared is excluded from the verifiable denominator
        assert audit.grounded_rate == 1.0

    def test_tilde_prefix_is_declared(self):
        audit = audit_numbers("Proyección base: ~981 cuentas", [])
        assert audit.declared == 1
        assert audit.ungrounded == 0

    def test_canonical_hallucination_still_flagged(self):
        # Hedging words are NOT declared markers — the €13.5M case stays caught.
        audit = audit_numbers("La deuda ronda los €13.5M aproximadamente", [3_267_365.43])
        assert audit.ungrounded == 1
        assert audit.declared == 0

    def test_grounded_beats_declared_tag(self):
        # A correct number with an [ESTIMADO] tag is still grounded.
        audit = audit_numbers("€3.27M [ESTIMADO]", [3_267_365.43])
        assert audit.grounded == 1
        assert audit.declared == 0

    def test_derived_credit_within_column_only(self):
        from valinor.quality.narrator_metrics import collect_derived_candidates
        qr = {"revenue_by_period": {"rows": [
            {"period": "2025-01-01 00:00:00", "revenue": "1831839.38"},
            {"period": "2025-03-01 00:00:00", "revenue": "1647933.00"},
        ]}}
        derived = collect_derived_candidates(qr)
        # MoM gap 1,831,839.38 − 1,647,933 = 183,906.38 is a column-mate delta
        audit = audit_numbers("Marzo se queda €183.906 por debajo de enero", [], derived_truth=derived)
        assert audit.derived_credited == 1
        assert audit.ungrounded == 0
        # without the flag it stays ungrounded (default config)
        audit_off = audit_numbers("Marzo se queda €183.906 por debajo de enero", [])
        assert audit_off.ungrounded == 1

    def test_extractor_suffix_needs_boundary(self):
        # "### 2. Base" must not parse as 2 billion; "€183.906 bajo" not as 183.906B
        values = [n.value for n in extract_numbers("### 2. Base de clientes colapsando")]
        assert 2_000_000_000 not in values
        values = [n.value for n in extract_numbers("aún €183.906 bajo enero")]
        assert values == [183906.0]


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
