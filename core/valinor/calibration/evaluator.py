"""
Calibration Evaluator — Scores pipeline run accuracy post-hoc.

After the pipeline completes, the evaluator:
1. Compares baseline values against independent verification queries
2. Checks that all critical queries executed successfully
3. Validates cross-metric consistency (parts sum to totals, etc.)
4. Scores the run on a 0-100 scale
5. Returns structured feedback for the calibration memory

No LLM. Pure deterministic scoring.

Research basis:
  - Reflexion (NeurIPS 2023) — self-reflection for iterative improvement
  - DSPy — programmatic optimization of LM pipelines
  - Constitutional AI — principled evaluation criteria
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CheckResult:
    """Result of a single calibration check."""
    name: str
    passed: bool
    score_impact: float  # 0-20 points deducted if failed
    detail: str
    severity: str  # "critical", "warning", "info"


@dataclass
class CalibrationScore:
    """Overall calibration score for a pipeline run."""
    overall_score: float  # 0-100
    checks: list[CheckResult] = field(default_factory=list)
    query_coverage_pct: float = 0.0
    baseline_completeness_pct: float = 0.0
    verification_rate: float = 0.0
    error_rate: float = 0.0
    timestamp: str = ""
    recommendations: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# EXPECTED QUERIES AND BASELINE FIELDS
# ═══════════════════════════════════════════════════════════════════════════

EXPECTED_QUERIES = [
    "total_revenue_summary",
    "ar_outstanding_actual",
    "aging_buckets",
    "top_customers",
    "monthly_trend",
]

CRITICAL_BASELINE_FIELDS = [
    "total_revenue",
    "num_invoices",
    "distinct_customers",
    "total_outstanding",
    "avg_invoice",
]

# ═══════════════════════════════════════════════════════════════════════════
# EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════


class CalibrationEvaluator:
    """Deterministic post-run evaluator — scores pipeline accuracy 0-100."""

    def __init__(
        self,
        query_results: dict,
        baseline: dict,
        verification_report: Any | None = None,
        entity_map: dict | None = None,
    ):
        self.query_results = query_results
        self.baseline = baseline
        self.verification_report = verification_report
        self.entity_map = entity_map or {}

    def evaluate(self) -> CalibrationScore:
        """Run all calibration checks, return a score."""
        all_checks: list[CheckResult] = []

        all_checks.extend(self._check_query_coverage())
        all_checks.extend(self._check_baseline_completeness())
        all_checks.extend(self._check_cross_consistency())
        all_checks.extend(self._check_verification_coverage())
        all_checks.extend(self._check_error_rate())

        # Score: start at 100, subtract impacts for failed checks
        total_deduction = sum(c.score_impact for c in all_checks if not c.passed)
        overall = max(0.0, 100.0 - total_deduction)

        # Compute summary metrics
        query_cov = self._compute_query_coverage()
        baseline_comp = self._compute_baseline_completeness()
        verif_rate = self._compute_verification_rate()
        err_rate = self._compute_error_rate()

        recommendations = self._generate_recommendations(all_checks)

        score = CalibrationScore(
            overall_score=round(overall, 2),
            checks=all_checks,
            query_coverage_pct=round(query_cov, 4),
            baseline_completeness_pct=round(baseline_comp, 4),
            verification_rate=round(verif_rate, 4),
            error_rate=round(err_rate, 4),
            timestamp=datetime.now(timezone.utc).isoformat(),
            recommendations=recommendations,
        )

        logger.info(
            "calibration.evaluate.done",
            overall_score=score.overall_score,
            checks_passed=sum(1 for c in all_checks if c.passed),
            checks_failed=sum(1 for c in all_checks if not c.passed),
        )
        return score

    # ───────────────────────────────────────────────────────────────────
    # Individual checks
    # ───────────────────────────────────────────────────────────────────

    def _check_query_coverage(self) -> list[CheckResult]:
        """What % of expected queries actually executed?"""
        results = self.query_results.get("results", {})
        executed = [q for q in EXPECTED_QUERIES if q in results]
        coverage = len(executed) / len(EXPECTED_QUERIES) if EXPECTED_QUERIES else 1.0

        checks = []
        if coverage >= 0.8:
            checks.append(CheckResult(
                name="query_coverage",
                passed=True,
                score_impact=0,
                detail=f"{len(executed)}/{len(EXPECTED_QUERIES)} expected queries executed ({coverage:.0%})",
                severity="info",
            ))
        else:
            deduction = 20.0 * (1.0 - coverage)
            checks.append(CheckResult(
                name="query_coverage",
                passed=False,
                score_impact=round(deduction, 2),
                detail=f"Only {len(executed)}/{len(EXPECTED_QUERIES)} expected queries executed ({coverage:.0%})",
                severity="critical" if coverage < 0.5 else "warning",
            ))
        return checks

    def _check_baseline_completeness(self) -> list[CheckResult]:
        """Are all critical baseline fields populated (revenue, invoices, customers)?"""
        present = [f for f in CRITICAL_BASELINE_FIELDS if self.baseline.get(f) is not None]
        completeness = len(present) / len(CRITICAL_BASELINE_FIELDS) if CRITICAL_BASELINE_FIELDS else 1.0

        checks = []
        if completeness >= 0.8:
            checks.append(CheckResult(
                name="baseline_completeness",
                passed=True,
                score_impact=0,
                detail=f"{len(present)}/{len(CRITICAL_BASELINE_FIELDS)} baseline fields populated",
                severity="info",
            ))
        else:
            missing = [f for f in CRITICAL_BASELINE_FIELDS if f not in present]
            deduction = 15.0 * (1.0 - completeness)
            checks.append(CheckResult(
                name="baseline_completeness",
                passed=False,
                score_impact=round(deduction, 2),
                detail=f"Missing baseline fields: {', '.join(missing)}",
                severity="critical",
            ))
        return checks

    def _check_cross_consistency(self) -> list[CheckResult]:
        """Mathematical consistency checks across metrics.

        Checks:
        - avg_invoice ~ total_revenue / num_invoices
        - SUM(aging_buckets) ~ total_outstanding (total_ar)
        - top_customer_revenue <= total_revenue
        - customers_with_debt <= distinct_customers (across all periods)
        """
        checks = []

        # Check: avg_invoice ≈ total_revenue / num_invoices
        total_rev = self.baseline.get("total_revenue")
        num_inv = self.baseline.get("num_invoices")
        avg_inv = self.baseline.get("avg_invoice")

        if total_rev is not None and num_inv is not None and avg_inv is not None and num_inv > 0:
            expected_avg = total_rev / num_inv
            tolerance = max(abs(expected_avg) * 0.01, 0.01)  # 1% tolerance
            if abs(avg_inv - expected_avg) <= tolerance:
                checks.append(CheckResult(
                    name="avg_invoice_consistency",
                    passed=True,
                    score_impact=0,
                    detail=f"avg_invoice ({avg_inv:.2f}) ≈ total/count ({expected_avg:.2f})",
                    severity="info",
                ))
            else:
                checks.append(CheckResult(
                    name="avg_invoice_consistency",
                    passed=False,
                    score_impact=15.0,
                    detail=(
                        f"avg_invoice ({avg_inv:.2f}) != total_revenue/num_invoices "
                        f"({expected_avg:.2f}), diff={abs(avg_inv - expected_avg):.2f}"
                    ),
                    severity="critical",
                ))

        # Check: SUM(aging_buckets) ≈ total_outstanding
        results = self.query_results.get("results", {})
        aging = results.get("aging_buckets", {})
        aging_rows = aging.get("rows", [])
        total_outstanding = self.baseline.get("total_outstanding")

        if aging_rows and total_outstanding is not None:
            bucket_sum = sum(
                row.get("amount", row.get("bucket_amount", 0)) or 0
                for row in aging_rows
            )
            tolerance = max(abs(total_outstanding) * 0.05, 1.0)  # 5% tolerance
            if abs(bucket_sum - total_outstanding) <= tolerance:
                checks.append(CheckResult(
                    name="aging_sum_consistency",
                    passed=True,
                    score_impact=0,
                    detail=f"SUM(aging_buckets)={bucket_sum:.2f} ≈ total_outstanding={total_outstanding:.2f}",
                    severity="info",
                ))
            else:
                checks.append(CheckResult(
                    name="aging_sum_consistency",
                    passed=False,
                    score_impact=10.0,
                    detail=(
                        f"SUM(aging_buckets)={bucket_sum:.2f} != "
                        f"total_outstanding={total_outstanding:.2f}"
                    ),
                    severity="warning",
                ))

        # Check: top_customer_revenue <= total_revenue
        top_customers = results.get("top_customers", {})
        top_rows = top_customers.get("rows", [])
        if top_rows and total_rev is not None:
            max_customer_rev = max(
                (row.get("revenue", row.get("total_revenue", 0)) or 0)
                for row in top_rows
            )
            if max_customer_rev <= total_rev:
                checks.append(CheckResult(
                    name="top_customer_bounded",
                    passed=True,
                    score_impact=0,
                    detail=f"Top customer revenue ({max_customer_rev:.2f}) <= total ({total_rev:.2f})",
                    severity="info",
                ))
            else:
                checks.append(CheckResult(
                    name="top_customer_bounded",
                    passed=False,
                    score_impact=15.0,
                    detail=f"Top customer revenue ({max_customer_rev:.2f}) > total ({total_rev:.2f})",
                    severity="critical",
                ))

        # Check: customers_with_debt <= distinct_customers
        customers_debt = self.baseline.get("customers_with_debt")
        distinct_cust = self.baseline.get("distinct_customers")
        if customers_debt is not None and distinct_cust is not None:
            if customers_debt <= distinct_cust:
                checks.append(CheckResult(
                    name="debt_customers_bounded",
                    passed=True,
                    score_impact=0,
                    detail=f"customers_with_debt ({customers_debt}) <= distinct_customers ({distinct_cust})",
                    severity="info",
                ))
            else:
                checks.append(CheckResult(
                    name="debt_customers_bounded",
                    passed=False,
                    score_impact=10.0,
                    detail=f"customers_with_debt ({customers_debt}) > distinct_customers ({distinct_cust})",
                    severity="warning",
                ))

        return checks

    def _check_verification_coverage(self) -> list[CheckResult]:
        """What % of agent claims were verified?"""
        checks = []
        if self.verification_report is None:
            checks.append(CheckResult(
                name="verification_coverage",
                passed=False,
                score_impact=10.0,
                detail="No verification report provided",
                severity="warning",
            ))
            return checks

        # Support both dict and object with attributes
        if isinstance(self.verification_report, dict):
            total = self.verification_report.get("total_claims", 0)
            verified = self.verification_report.get("verified_claims", 0)
        else:
            total = getattr(self.verification_report, "total_claims", 0)
            verified = getattr(self.verification_report, "verified_claims", 0)

        rate = verified / total if total > 0 else 0.0

        if rate >= 0.7:
            checks.append(CheckResult(
                name="verification_coverage",
                passed=True,
                score_impact=0,
                detail=f"{verified}/{total} claims verified ({rate:.0%})",
                severity="info",
            ))
        else:
            deduction = 15.0 * (1.0 - rate)
            checks.append(CheckResult(
                name="verification_coverage",
                passed=False,
                score_impact=round(deduction, 2),
                detail=f"Only {verified}/{total} claims verified ({rate:.0%})",
                severity="warning" if rate >= 0.4 else "critical",
            ))
        return checks

    def _check_error_rate(self) -> list[CheckResult]:
        """What % of queries errored?"""
        results = self.query_results.get("results", {})
        errors = self.query_results.get("errors", {})
        total_queries = len(results) + len(errors)

        checks = []
        if total_queries == 0:
            checks.append(CheckResult(
                name="error_rate",
                passed=False,
                score_impact=20.0,
                detail="No queries executed at all",
                severity="critical",
            ))
            return checks

        err_rate = len(errors) / total_queries

        if err_rate <= 0.1:
            checks.append(CheckResult(
                name="error_rate",
                passed=True,
                score_impact=0,
                detail=f"{len(errors)}/{total_queries} queries errored ({err_rate:.0%})",
                severity="info",
            ))
        else:
            deduction = 20.0 * err_rate
            checks.append(CheckResult(
                name="error_rate",
                passed=False,
                score_impact=round(deduction, 2),
                detail=f"{len(errors)}/{total_queries} queries errored ({err_rate:.0%})",
                severity="critical" if err_rate >= 0.5 else "warning",
            ))
        return checks

    # ───────────────────────────────────────────────────────────────────
    # Summary metrics
    # ───────────────────────────────────────────────────────────────────

    def _compute_query_coverage(self) -> float:
        results = self.query_results.get("results", {})
        executed = [q for q in EXPECTED_QUERIES if q in results]
        return len(executed) / len(EXPECTED_QUERIES) if EXPECTED_QUERIES else 1.0

    def _compute_baseline_completeness(self) -> float:
        present = [f for f in CRITICAL_BASELINE_FIELDS if self.baseline.get(f) is not None]
        return len(present) / len(CRITICAL_BASELINE_FIELDS) if CRITICAL_BASELINE_FIELDS else 1.0

    def _compute_verification_rate(self) -> float:
        if self.verification_report is None:
            return 0.0
        if isinstance(self.verification_report, dict):
            total = self.verification_report.get("total_claims", 0)
            verified = self.verification_report.get("verified_claims", 0)
        else:
            total = getattr(self.verification_report, "total_claims", 0)
            verified = getattr(self.verification_report, "verified_claims", 0)
        return verified / total if total > 0 else 0.0

    def _compute_error_rate(self) -> float:
        results = self.query_results.get("results", {})
        errors = self.query_results.get("errors", {})
        total = len(results) + len(errors)
        return len(errors) / total if total > 0 else 0.0

    # ───────────────────────────────────────────────────────────────────
    # Recommendations
    # ───────────────────────────────────────────────────────────────────

    def _generate_recommendations(self, checks: list[CheckResult]) -> list[str]:
        """Generate human-readable improvement suggestions from check results."""
        recs = []
        failed = {c.name: c for c in checks if not c.passed}

        if "query_coverage" in failed:
            recs.append(
                "Increase query coverage: add missing expected queries to the pipeline template."
            )
        if "baseline_completeness" in failed:
            recs.append(
                "Ensure all critical baseline fields are populated before analysis begins."
            )
        if "avg_invoice_consistency" in failed:
            recs.append(
                "Investigate avg_invoice calculation — it should equal total_revenue / num_invoices."
            )
        if "aging_sum_consistency" in failed:
            recs.append(
                "Review aging bucket query — SUM of buckets should approximate total outstanding."
            )
        if "top_customer_bounded" in failed:
            recs.append(
                "Top customer revenue exceeds total — check for duplicate counting or filter issues."
            )
        if "debt_customers_bounded" in failed:
            recs.append(
                "Customers with debt exceeds total customers — verify issotrx and date filters."
            )
        if "verification_coverage" in failed:
            recs.append(
                "Increase verification coverage: add more cross-validation rules or re-execution queries."
            )
        if "error_rate" in failed:
            recs.append(
                "Reduce query error rate: review failing queries for syntax or schema issues."
            )

        return recs
