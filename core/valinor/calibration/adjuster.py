"""
Calibration Adjuster — Suggests improvements based on calibration results.

Analyzes patterns in calibration failures and generates actionable recommendations.
Does NOT auto-apply changes — produces a recommendation report.

Anti-overfitting: suggestions are GENERIC patterns, not client-specific fixes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from valinor.calibration.evaluator import CalibrationScore
from valinor.calibration.memory import CalibrationMemory

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Suggestion:
    """A single improvement suggestion."""
    category: str  # "query", "filter", "verification", "discovery"
    description: str
    affected_module: str  # e.g. "query_builder.py", "verification.py"
    confidence: float  # 0-1
    is_generic: bool  # True = applies to all clients, False = client-specific


@dataclass
class AdjustmentReport:
    """Full adjustment report for a calibration run."""
    suggestions: list[Suggestion] = field(default_factory=list)
    regression_detected: bool = False
    trend: str = "unknown"  # "improving", "stable", "degrading"
    overfitting_warnings: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# ADJUSTER
# ═══════════════════════════════════════════════════════════════════════════


class CalibrationAdjuster:
    """Analyzes calibration results and suggests generic improvements.

    Key principle: suggestions must benefit ALL clients, not just the current one.
    Client-specific fixes are flagged as potential overfitting.
    """

    def __init__(self, memory: CalibrationMemory):
        self.memory = memory

    def analyze(self, client: str, score: CalibrationScore) -> AdjustmentReport:
        """Analyze calibration results and suggest improvements."""
        suggestions: list[Suggestion] = []
        overfitting_warnings: list[str] = []

        # Gather suggestions from each analyzer
        suggestions.extend(self._suggest_query_fixes(score))
        suggestions.extend(self._suggest_filter_improvements(score))
        suggestions.extend(self._suggest_verification_improvements(score))

        # Check each suggestion for overfitting
        for s in suggestions:
            if self._check_overfitting(client, s):
                s.is_generic = False
                overfitting_warnings.append(
                    f"Suggestion '{s.description}' may only help client '{client}' — "
                    f"flagged as potential overfitting."
                )

        # Detect regression
        regression = self.memory.detect_regression(client, score)

        # Get trend
        trend_info = self.memory.get_trend(client)
        trend = trend_info.get("trend", "unknown")

        report = AdjustmentReport(
            suggestions=suggestions,
            regression_detected=regression is not None,
            trend=trend,
            overfitting_warnings=overfitting_warnings,
        )

        logger.info(
            "calibration.adjuster.analyzed",
            client=client,
            num_suggestions=len(suggestions),
            regression=report.regression_detected,
            trend=trend,
            overfitting_warnings=len(overfitting_warnings),
        )

        return report

    def _suggest_query_fixes(self, score: CalibrationScore) -> list[Suggestion]:
        """If queries consistently fail, suggest template/generator improvements."""
        suggestions = []

        if score.error_rate > 0.2:
            suggestions.append(Suggestion(
                category="query",
                description=(
                    "High query error rate detected. Review query templates for "
                    "schema compatibility and add defensive column-existence checks."
                ),
                affected_module="query_builder.py",
                confidence=min(score.error_rate, 1.0),
                is_generic=True,
            ))

        if score.query_coverage_pct < 0.8:
            suggestions.append(Suggestion(
                category="query",
                description=(
                    "Low query coverage. Ensure the pipeline template includes all "
                    "expected queries (revenue summary, AR, aging, top customers, trends)."
                ),
                affected_module="query_builder.py",
                confidence=0.8,
                is_generic=True,
            ))

        return suggestions

    def _suggest_filter_improvements(self, score: CalibrationScore) -> list[Suggestion]:
        """If verification shows missing filters, suggest Cartographer adjustments."""
        suggestions = []

        # Look for specific failing checks
        failed_checks = {c.name for c in score.checks if not c.passed}

        if "debt_customers_bounded" in failed_checks:
            suggestions.append(Suggestion(
                category="filter",
                description=(
                    "Customers with debt exceeds total customers. "
                    "Verify issotrx filter and date range consistency across queries."
                ),
                affected_module="cartographer.py",
                confidence=0.9,
                is_generic=True,
            ))

        if "top_customer_bounded" in failed_checks:
            suggestions.append(Suggestion(
                category="filter",
                description=(
                    "Top customer revenue exceeds total revenue. "
                    "Check for duplicate counting or missing WHERE clause filters."
                ),
                affected_module="cartographer.py",
                confidence=0.85,
                is_generic=True,
            ))

        if "aging_sum_consistency" in failed_checks:
            suggestions.append(Suggestion(
                category="filter",
                description=(
                    "Aging buckets do not sum to total outstanding. "
                    "Ensure aging query uses the same base filter as AR outstanding query."
                ),
                affected_module="query_builder.py",
                confidence=0.8,
                is_generic=True,
            ))

        return suggestions

    def _suggest_verification_improvements(self, score: CalibrationScore) -> list[Suggestion]:
        """If verification rate is low, suggest adding more cross-validation rules."""
        suggestions = []

        if score.verification_rate < 0.7:
            suggestions.append(Suggestion(
                category="verification",
                description=(
                    "Low verification rate. Add more re-execution queries to "
                    "cross-validate key metrics (revenue, AR, customer counts)."
                ),
                affected_module="verification.py",
                confidence=0.75,
                is_generic=True,
            ))

        if score.baseline_completeness_pct < 0.8:
            suggestions.append(Suggestion(
                category="discovery",
                description=(
                    "Incomplete baseline. Ensure the discovery phase populates all "
                    "critical fields before analysis begins."
                ),
                affected_module="discovery.py",
                confidence=0.7,
                is_generic=True,
            ))

        return suggestions

    def _check_overfitting(self, client: str, suggestion: Suggestion) -> bool:
        """Check if a suggestion would only help this client.

        If other clients have different patterns, flag as potential overfitting.
        A suggestion is considered overfitting if:
        - It's about a specific check failure, AND
        - Other clients do NOT have the same failure pattern
        """
        summary = self.memory.get_cross_client_summary()

        # If we have fewer than 2 clients, we can't detect overfitting
        if len(summary) < 2:
            return False

        # For filter-category suggestions, check if other clients have similar issues
        # by looking at their error rates
        if suggestion.category == "filter":
            other_clients = {c: s for c, s in summary.items() if c != client}
            if not other_clients:
                return False

            # If all other clients have good scores, this fix might be overfitting
            other_scores = [s["overall_score"] for s in other_clients.values()]
            avg_other = sum(other_scores) / len(other_scores)

            # If other clients average > 90 but this client is struggling,
            # the suggestion might be too specific
            if avg_other > 90:
                return True

        return False
