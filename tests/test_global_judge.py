"""
Unit tests for the N3 two-layer judge (VAL-192 N3). Pure offline: layer 0 is
deterministic; layer 1 is exercised with an injected judge_llm_fn.
"""

from __future__ import annotations

import pytest

from valinor.quality.global_judge import (
    evaluate_gate,
    judge_layer0,
    judge_layer1,
    resolve_placeholder,
)

REFS = {"q1": {
    "exposed_eur": 945000.0,
    "exposed_share_pct": 39.38,
    "exposed_customers": ["DISTRIBUIDORA ANDINA SRL", "VIVERO LAS LOMAS SRL"],
    "naive_double_count_eur": 1770000.0,
}}

QUESTION = {
    "id": "q1-exposicion-compuesta",
    "question": "¿Qué % de la facturación está en clientes con churn o dormancia?",
    "required_facts": [
        {"fact": "share expuesto", "expected": "{REF:q1.exposed_share_pct}", "tolerance_pct": 2.0},
        {"fact": "monto expuesto", "expected": "{REF:q1.exposed_eur}", "tolerance_pct": 1.0},
        {"fact": "clientes expuestos", "expected": "{REF:q1.exposed_customers}", "kind": "labels"},
    ],
    "must_not_include": ["{REF:q1.naive_double_count_eur}"],
}


class TestPlaceholders:
    def test_resolves(self):
        assert resolve_placeholder("{REF:q1.exposed_eur}", "q1", REFS) == 945000.0

    def test_verbatim_passthrough(self):
        assert resolve_placeholder("literal", "q1", REFS) == "literal"


class TestLayer0:
    GOOD = ("El 39.4% de la facturación (€945.000) está expuesto: "
            "DISTRIBUIDORA ANDINA SRL y VIVERO LAS LOMAS SRL en riesgo.")
    BAD = "La exposición ronda el 12% (€300.000) y afecta a clientes varios."
    TRAP = ("Sumando churn (€1.050.000) y dormancia (€720.000) la exposición "
            "total es €1.770.000 en DISTRIBUIDORA ANDINA SRL y VIVERO LAS "
            "LOMAS SRL.")
    TRAP_WITH_CORRECT = ("La exposición deduplicada es €945.000 (39.38%) — "
                         "nota: la suma naive sin dedup daría €1.770.000 — "
                         "DISTRIBUIDORA ANDINA SRL, VIVERO LAS LOMAS SRL.")

    def test_good_answer_scores_full(self):
        res = judge_layer0(self.GOOD, QUESTION, REFS)
        assert res.facts_total == 3
        assert res.score == pytest.approx(1.0)
        assert res.forbidden_hits == 0

    def test_bad_answer_scores_zero(self):
        res = judge_layer0(self.BAD, QUESTION, REFS)
        assert res.score == pytest.approx(0.0)

    def test_forbidden_trap_is_substitution(self):
        # Trap number INSTEAD of the right one → hit.
        res = judge_layer0(self.TRAP, QUESTION, REFS)
        assert res.forbidden_hits == 1

    def test_trap_with_correct_facts_is_context_not_hit(self):
        # v3 rule: co-occurrence next to the correct facts is legitimate
        # context, not a substitution error.
        res = judge_layer0(self.TRAP_WITH_CORRECT, QUESTION, REFS)
        assert res.forbidden_hits == 0

    def test_partial_labels(self):
        res = judge_layer0(
            "39.38% — €945.000 — sólo DISTRIBUIDORA ANDINA SRL", QUESTION, REFS)
        # 2 numeric full + 1/2 labels
        assert res.facts_present == pytest.approx(2.5)


class TestLayer1:
    async def test_median_over_reps_and_clamping(self):
        verdicts = iter([
            {"facts": [{"fact": "a", "score": 2}, {"fact": "b", "score": 9}], "forbidden_hits": 0},
            {"facts": [{"fact": "a", "score": 0}, {"fact": "b", "score": 0}], "forbidden_hits": 1},
            {"facts": [{"fact": "a", "score": 2}, {"fact": "b", "score": 1}], "forbidden_hits": 0},
        ])

        async def judge(prompt):
            return next(verdicts)

        out = await judge_layer1("respuesta", QUESTION, REFS, judge_llm_fn=judge, reps=3)
        assert out["max_points"] == 6
        # rep points: [4 (2+clamped 2), 0, 3] → median 3; forbidden median 0
        assert out["points"] == 3
        assert out["forbidden_hits"] == 0

    async def test_no_facts_no_call(self):
        called = []

        async def judge(prompt):
            called.append(1)
            return {}

        out = await judge_layer1("x", {"id": "q9-x", "question": "?", "required_facts": []},
                                 {}, judge_llm_fn=judge)
        assert called == []
        assert out["max_points"] == 0


class TestGate:
    def test_gate_logic(self):
        per_q = {
            "q1": {"flat": 0.2, "community": 0.9, "community_forbidden": 0},   # win
            "q2": {"flat": 0.3, "community": 0.85, "community_forbidden": 0},  # win
            "q3": {"flat": 0.4, "community": 0.95, "community_forbidden": 1},  # forbidden → no win
            "q4": {"flat": 0.6, "community": 0.9, "community_forbidden": 0},   # flat ok → not global
            "q5": {"flat": 0.1, "community": 0.7, "community_forbidden": 0},   # community weak
            "q7": {"flat": 0.0, "community": 1.0, "community_forbidden": 0},   # win
            "q8": {"flat": 0.2, "community": 0.8, "community_forbidden": 0},   # win
        }
        gate = evaluate_gate(per_q, min_wins=5)
        assert gate["wins"] == ["q1", "q2", "q7", "q8"]
        assert not gate["gate_passed"]
        gate4 = evaluate_gate(per_q, min_wins=4)
        assert gate4["gate_passed"]
