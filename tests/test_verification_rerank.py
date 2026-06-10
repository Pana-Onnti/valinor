"""
Unit tests for the two-stage grounding module (VAL-192 N2).

Pure / no LLM: stage 1.5 enrichment is deterministic; stage 2 is exercised by
injecting llm_json_fn with hand-built proposals. The invariant under test:
the LLM proposes, the code disposes — an unconfirmable proposal can never
upgrade a claim.
"""

from __future__ import annotations

import pytest

from valinor.verification import (
    AtomicClaim,
    VerificationReport,
    VerificationResult,
)
from valinor.verification_rerank import (
    RerankOutcome,
    enrich_registry,
    rerank_unverifiable,
)

QR = {"results": {
    "concentration_top_customers": {"rows": [
        {"customer_id": "AAA", "ltv_eur": "400000.00", "share_pct": "40.00"},
        {"customer_id": "BBB", "ltv_eur": "350000.00", "share_pct": "35.00"},
        {"customer_id": "CCC", "ltv_eur": "250000.00", "share_pct": "25.00"},
    ]},
    "revenue_summary": {"rows": [
        {"total_revenue": "1000000.00", "num_invoices": 2000}
    ]},
}}


def _report_with_unverifiable(*claim_vals: float) -> tuple[VerificationReport, dict]:
    report = VerificationReport(total_claims=len(claim_vals))
    claims = {}
    for i, v in enumerate(claim_vals):
        cid = f"c{i}"
        report.results.append(VerificationResult(claim_id=cid, status="UNVERIFIABLE"))
        claims[cid] = AtomicClaim(
            claim_id=cid, finding_id=f"f{i}", claim_text=f"EUR value: {v}",
            claim_type="numeric", claimed_value=v, claimed_unit="EUR",
        )
    report.unverifiable_claims = len(claim_vals)
    return report, claims


class TestEnrichRegistry:
    def test_single_row_scalars_and_rank1_and_sums(self):
        report = VerificationReport()
        added = enrich_registry(report, QR)
        labels = set(report.number_registry)
        assert "revenue_summary.total_revenue" in labels          # single-row scalar
        assert "concentration_top_customers.ltv_eur_top1" in labels
        assert "concentration_top_customers.ltv_eur_sum" in labels
        assert report.number_registry["concentration_top_customers.ltv_eur_sum"].value == 1_000_000.0
        assert added == len(labels)

    def test_does_not_overwrite_existing_labels(self):
        report = VerificationReport()
        enrich_registry(report, QR)
        before = report.number_registry["revenue_summary.total_revenue"].value
        enrich_registry(report, QR)
        assert report.number_registry["revenue_summary.total_revenue"].value == before

    def test_cap_respected(self):
        report = VerificationReport()
        enrich_registry(report, QR, max_entries=2)
        assert len(report.number_registry) == 2

    def test_dimension_inference(self):
        report = VerificationReport()
        enrich_registry(report, QR)
        assert report.number_registry["concentration_top_customers.ltv_eur_top1"].dimension == "EUR"
        assert report.number_registry["concentration_top_customers.share_pct_top1"].dimension == "percent"


class TestRerankConfirmation:
    async def test_confirmed_sum_upgrades(self):
        report, claims = _report_with_unverifiable(1_000_000.0)

        async def llm(prompt):
            return [{"claim_id": "c0", "kind": "sum",
                     "query": "concentration_top_customers", "column": "ltv_eur",
                     "rows": "all"}]

        out = await rerank_unverifiable(report, QR, claims, llm_json_fn=llm)
        assert len(out.upgraded) == 1
        assert report.results[0].status == "VERIFIED"
        assert report.verified_claims == 1
        assert "deterministically confirmed" in report.results[0].evidence

    async def test_wrong_proposal_rejected(self):
        # LLM proposes a sum that does NOT reproduce the claimed value.
        report, claims = _report_with_unverifiable(999.0)

        async def llm(prompt):
            return [{"claim_id": "c0", "kind": "sum",
                     "query": "concentration_top_customers", "column": "ltv_eur",
                     "rows": "all"}]

        out = await rerank_unverifiable(report, QR, claims, llm_json_fn=llm)
        assert out.upgraded == []
        assert len(out.rejected) == 1
        assert report.results[0].status == "UNVERIFIABLE"

    async def test_difference_and_share(self):
        report, claims = _report_with_unverifiable(50_000.0, 40.0)
        claims["c1"].claimed_unit = "percent"

        async def llm(prompt):
            return [
                {"claim_id": "c0", "kind": "difference",
                 "a": {"query": "concentration_top_customers", "column": "ltv_eur", "row": 0},
                 "b": {"query": "concentration_top_customers", "column": "ltv_eur", "row": 1}},
                {"claim_id": "c1", "kind": "share_pct",
                 "part": {"query": "concentration_top_customers", "column": "ltv_eur", "row": 0},
                 "total_query": "concentration_top_customers", "total_column": "ltv_eur"},
            ]

        out = await rerank_unverifiable(report, QR, claims, llm_json_fn=llm)
        assert {u["claim_id"] for u in out.upgraded} == {"c0", "c1"}

    async def test_magnitude_match_credits_signed_values(self):
        # Claim 5123.40 vs stored min_invoice "-5123.40" — same fact, sign apart.
        qr = {"results": {"revenue_summary": {"rows": [{"min_invoice": "-5123.40"}]}}}
        report, claims = _report_with_unverifiable(5123.40)

        async def llm(prompt):
            return [{"claim_id": "c0", "kind": "direct",
                     "query": "revenue_summary", "column": "min_invoice", "row": 0}]

        out = await rerank_unverifiable(report, qr, claims, llm_json_fn=llm)
        assert len(out.upgraded) == 1

    async def test_contradiction_is_disputed_not_retracted(self):
        report, claims = _report_with_unverifiable(123_456.0)

        async def llm(prompt):
            return [{"claim_id": "c0", "kind": "contradicted",
                     "query": "revenue_summary", "column": "total_revenue", "row": 0}]

        out = await rerank_unverifiable(report, QR, claims, llm_json_fn=llm)
        assert report.results[0].status == "UNVERIFIABLE"   # never auto-retracted
        assert len(out.disputed) == 1
        assert report.issues and "stage-2 dispute" in report.issues[0]["description"]

    async def test_settled_claims_untouched(self):
        report, claims = _report_with_unverifiable(1_000_000.0)
        report.results.append(VerificationResult(claim_id="ok", status="VERIFIED"))
        report.total_claims = 2
        report.verified_claims = 1

        async def llm(prompt):
            return [{"claim_id": "ok", "kind": "direct",
                     "query": "revenue_summary", "column": "total_revenue", "row": 0}]

        await rerank_unverifiable(report, QR, claims, llm_json_fn=llm)
        assert report.results[1].status == "VERIFIED"
        assert report.verified_claims == 1   # unchanged: stage 2 never touches settled

    async def test_no_targets_no_llm_call(self):
        report = VerificationReport(total_claims=1)
        report.results.append(VerificationResult(claim_id="n0", status="UNVERIFIABLE"))
        claims = {"n0": AtomicClaim(claim_id="n0", finding_id="f", claim_text="negative",
                                    claim_type="negative", claimed_value=0.0)}
        called = []

        async def llm(prompt):
            called.append(1)
            return []

        out = await rerank_unverifiable(report, QR, claims, llm_json_fn=llm)
        assert called == []   # zero-value/negative claims are out of stage-2 scope
        assert isinstance(out, RerankOutcome)
