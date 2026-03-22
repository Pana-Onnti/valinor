"""
Anomaly Explainer — VAL-40: WHY not just WHAT.

Given a detected anomaly (metric, expected, actual, deviation),
generates hypotheses and drill-down queries to test each one.
Returns the most likely explanation with supporting data.

Hypothesis types:
  - Temporal: seasonality, holiday effects, month-end patterns
  - Entity: specific customer/vendor driving the anomaly
  - Category: product line, region, or segment effects

References:
  - Root Cause Analysis (RCA) pattern from AIOps literature
  - Adtributor (VLDB 2014) — multi-dimensional root cause localization
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from valinor.knowledge_graph import SchemaKnowledgeGraph

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


class HypothesisType(str, Enum):
    """Category of anomaly hypothesis."""
    TEMPORAL = "temporal"
    ENTITY = "entity"
    CATEGORY = "category"
    DATA_QUALITY = "data_quality"


class HypothesisStatus(str, Enum):
    """Status of a hypothesis after testing."""
    UNTESTED = "untested"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


@dataclass
class Anomaly:
    """An anomaly to explain."""
    metric: str
    expected: float
    actual: float
    deviation_pct: float
    table: str = ""
    column: str = ""
    period: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def direction(self) -> str:
        """Whether the anomaly is above or below expected."""
        return "above" if self.actual > self.expected else "below"

    @property
    def abs_deviation_pct(self) -> float:
        return abs(self.deviation_pct)


@dataclass
class DrillDownQuery:
    """A SQL query designed to test a specific hypothesis."""
    sql: str
    description: str
    hypothesis_id: str


@dataclass
class Hypothesis:
    """A single hypothesis about what caused the anomaly."""
    hypothesis_id: str
    hypothesis_type: HypothesisType
    description: str
    drill_down_query: DrillDownQuery | None = None
    status: HypothesisStatus = HypothesisStatus.UNTESTED
    evidence: str = ""
    confidence: float = 0.0


@dataclass
class AnomalyExplanation:
    """Complete explanation of an anomaly."""
    anomaly: Anomaly
    hypotheses: list[Hypothesis] = field(default_factory=list)
    best_hypothesis: Hypothesis | None = None
    summary: str = ""

    @property
    def explained(self) -> bool:
        """True if at least one hypothesis is supported."""
        return any(h.status == HypothesisStatus.SUPPORTED for h in self.hypotheses)


# ═══════════════════════════════════════════════════════════════════════════
# ANOMALY EXPLAINER
# ═══════════════════════════════════════════════════════════════════════════


class AnomalyExplainer:
    """
    Generates and tests hypotheses for anomalies.

    Given an anomaly, produces:
      1. Temporal hypotheses (seasonality, trend shifts)
      2. Entity hypotheses (specific customer/vendor driving deviation)
      3. Category hypotheses (product line, region)
      4. Data quality hypotheses (nulls, duplicates)
    """

    def __init__(
        self,
        kg: SchemaKnowledgeGraph | None = None,
        entity_map: dict | None = None,
    ) -> None:
        self.kg = kg
        self.entity_map = entity_map or {}
        self._entities = self.entity_map.get("entities", {})

    def explain(self, anomaly: Anomaly) -> AnomalyExplanation:
        """
        Generate hypotheses for an anomaly and build drill-down queries.

        Args:
            anomaly: The anomaly to explain.

        Returns:
            AnomalyExplanation with ranked hypotheses and drill-down queries.
        """
        explanation = AnomalyExplanation(anomaly=anomaly)

        # Generate all hypothesis types
        explanation.hypotheses.extend(self._generate_temporal_hypotheses(anomaly))
        explanation.hypotheses.extend(self._generate_entity_hypotheses(anomaly))
        explanation.hypotheses.extend(self._generate_category_hypotheses(anomaly))
        explanation.hypotheses.extend(self._generate_data_quality_hypotheses(anomaly))

        # Build summary
        if explanation.hypotheses:
            explanation.summary = (
                f"Generated {len(explanation.hypotheses)} hypotheses for "
                f"{anomaly.metric} anomaly ({anomaly.deviation_pct:+.1f}% deviation). "
                f"Drill-down queries available for testing."
            )
        else:
            explanation.summary = (
                f"No hypotheses generated for {anomaly.metric} anomaly. "
                f"Insufficient schema context."
            )

        logger.info(
            "anomaly_explanation_generated",
            metric=anomaly.metric,
            deviation_pct=anomaly.deviation_pct,
            num_hypotheses=len(explanation.hypotheses),
        )

        return explanation

    def evaluate_hypothesis(
        self,
        hypothesis: Hypothesis,
        query_result: dict[str, Any],
    ) -> Hypothesis:
        """
        Evaluate a hypothesis given the result of its drill-down query.

        Args:
            hypothesis: The hypothesis to evaluate.
            query_result: Dict with 'rows' and 'columns' from query execution.

        Returns:
            Updated hypothesis with status and evidence.
        """
        rows = query_result.get("rows", [])
        if not rows:
            hypothesis.status = HypothesisStatus.INCONCLUSIVE
            hypothesis.evidence = "Drill-down query returned no rows."
            hypothesis.confidence = 0.1
            return hypothesis

        # For temporal: check if specific periods show outsized deviation
        if hypothesis.hypothesis_type == HypothesisType.TEMPORAL:
            return self._evaluate_temporal(hypothesis, rows)

        # For entity: check if a single entity dominates the deviation
        if hypothesis.hypothesis_type == HypothesisType.ENTITY:
            return self._evaluate_entity(hypothesis, rows)

        # For category: check if a category shows outsized deviation
        if hypothesis.hypothesis_type == HypothesisType.CATEGORY:
            return self._evaluate_category(hypothesis, rows)

        # For data quality: check if null/duplicate rate is significant
        if hypothesis.hypothesis_type == HypothesisType.DATA_QUALITY:
            return self._evaluate_data_quality(hypothesis, rows)

        return hypothesis

    def select_best_hypothesis(
        self, explanation: AnomalyExplanation,
    ) -> AnomalyExplanation:
        """
        Select the best hypothesis from those already evaluated.

        Updates explanation.best_hypothesis with the highest-confidence
        supported hypothesis.
        """
        supported = [
            h for h in explanation.hypotheses
            if h.status == HypothesisStatus.SUPPORTED
        ]
        if supported:
            explanation.best_hypothesis = max(supported, key=lambda h: h.confidence)
        elif explanation.hypotheses:
            # Fall back to highest confidence even if inconclusive
            explanation.best_hypothesis = max(
                explanation.hypotheses, key=lambda h: h.confidence,
            )

        return explanation

    # ── HYPOTHESIS GENERATORS ──────────────────────────────────────────

    def _generate_temporal_hypotheses(
        self, anomaly: Anomaly,
    ) -> list[Hypothesis]:
        """Generate temporal hypotheses: seasonality, trend shift."""
        hypotheses: list[Hypothesis] = []
        table = anomaly.table
        if not table:
            table = self._find_transactional_table()
        if not table:
            return hypotheses

        date_col = self._find_date_column(table)
        amount_col = self._find_amount_column(table)
        if not date_col or not amount_col:
            return hypotheses

        base_filter = self._get_base_filter(table)
        filter_clause = f"AND {base_filter}" if base_filter else ""

        # Hypothesis 1: Seasonality — compare same month across years
        h_season = Hypothesis(
            hypothesis_id=f"temporal_seasonality_{anomaly.metric}",
            hypothesis_type=HypothesisType.TEMPORAL,
            description=(
                f"The {anomaly.direction} deviation in {anomaly.metric} may be "
                f"seasonal (same pattern in prior years)."
            ),
            drill_down_query=DrillDownQuery(
                sql=(
                    f"SELECT EXTRACT(YEAR FROM {date_col}) AS year, "
                    f"EXTRACT(MONTH FROM {date_col}) AS month, "
                    f"SUM({amount_col}) AS total, COUNT(*) AS cnt "
                    f"FROM {table} "
                    f"WHERE 1=1 {filter_clause} "
                    f"GROUP BY 1, 2 ORDER BY 1, 2"
                ),
                description="Monthly totals by year to detect seasonal patterns",
                hypothesis_id=f"temporal_seasonality_{anomaly.metric}",
            ),
        )
        hypotheses.append(h_season)

        # Hypothesis 2: Recent trend shift — last 3 months vs prior 3
        h_trend = Hypothesis(
            hypothesis_id=f"temporal_trend_{anomaly.metric}",
            hypothesis_type=HypothesisType.TEMPORAL,
            description=(
                f"The {anomaly.direction} deviation may reflect a recent trend shift "
                f"(last 3 months vs prior 3)."
            ),
            drill_down_query=DrillDownQuery(
                sql=(
                    f"SELECT "
                    f"CASE WHEN {date_col} >= CURRENT_DATE - INTERVAL '3 months' "
                    f"     THEN 'recent' ELSE 'prior' END AS period, "
                    f"SUM({amount_col}) AS total, COUNT(*) AS cnt, "
                    f"AVG({amount_col}) AS avg_val "
                    f"FROM {table} "
                    f"WHERE {date_col} >= CURRENT_DATE - INTERVAL '6 months' "
                    f"{filter_clause} "
                    f"GROUP BY 1"
                ),
                description="Compare last 3 months vs prior 3 months",
                hypothesis_id=f"temporal_trend_{anomaly.metric}",
            ),
        )
        hypotheses.append(h_trend)

        return hypotheses

    def _generate_entity_hypotheses(
        self, anomaly: Anomaly,
    ) -> list[Hypothesis]:
        """Generate entity hypotheses: specific customer/partner driving anomaly."""
        hypotheses: list[Hypothesis] = []
        table = anomaly.table
        if not table:
            table = self._find_transactional_table()
        if not table:
            return hypotheses

        amount_col = self._find_amount_column(table)
        date_col = self._find_date_column(table)
        customer_fk = self._find_customer_fk(table)
        if not amount_col or not customer_fk:
            return hypotheses

        base_filter = self._get_base_filter(table)
        filter_clause = f"AND {base_filter}" if base_filter else ""
        date_clause = (
            f"AND {date_col} >= CURRENT_DATE - INTERVAL '6 months'"
            if date_col else ""
        )

        # Hypothesis: single entity concentration
        h_entity = Hypothesis(
            hypothesis_id=f"entity_concentration_{anomaly.metric}",
            hypothesis_type=HypothesisType.ENTITY,
            description=(
                f"A single customer/entity may be driving the "
                f"{anomaly.direction} deviation in {anomaly.metric}."
            ),
            drill_down_query=DrillDownQuery(
                sql=(
                    f"SELECT {customer_fk}, "
                    f"SUM({amount_col}) AS entity_total, "
                    f"COUNT(*) AS entity_count, "
                    f"SUM({amount_col}) * 100.0 / NULLIF("
                    f"(SELECT SUM({amount_col}) FROM {table} WHERE 1=1 "
                    f"{filter_clause} {date_clause}), 0) AS pct_of_total "
                    f"FROM {table} "
                    f"WHERE 1=1 {filter_clause} {date_clause} "
                    f"GROUP BY {customer_fk} "
                    f"ORDER BY entity_total DESC LIMIT 10"
                ),
                description="Top entities by contribution to identify concentration",
                hypothesis_id=f"entity_concentration_{anomaly.metric}",
            ),
        )
        hypotheses.append(h_entity)

        return hypotheses

    def _generate_category_hypotheses(
        self, anomaly: Anomaly,
    ) -> list[Hypothesis]:
        """Generate category hypotheses from low-cardinality columns."""
        hypotheses: list[Hypothesis] = []
        table = anomaly.table
        if not table:
            table = self._find_transactional_table()
        if not table:
            return hypotheses

        amount_col = self._find_amount_column(table)
        if not amount_col:
            return hypotheses

        # Find low-cardinality columns from KG
        category_cols = self._find_category_columns(table)
        base_filter = self._get_base_filter(table)
        filter_clause = f"AND {base_filter}" if base_filter else ""

        for cat_col in category_cols[:3]:  # Limit to top 3 categories
            h_cat = Hypothesis(
                hypothesis_id=f"category_{cat_col}_{anomaly.metric}",
                hypothesis_type=HypothesisType.CATEGORY,
                description=(
                    f"The anomaly in {anomaly.metric} may be driven by a specific "
                    f"value in {cat_col}."
                ),
                drill_down_query=DrillDownQuery(
                    sql=(
                        f"SELECT {cat_col}, "
                        f"SUM({amount_col}) AS category_total, "
                        f"COUNT(*) AS category_count "
                        f"FROM {table} "
                        f"WHERE 1=1 {filter_clause} "
                        f"GROUP BY {cat_col} "
                        f"ORDER BY category_total DESC"
                    ),
                    description=f"Breakdown by {cat_col} to identify category effect",
                    hypothesis_id=f"category_{cat_col}_{anomaly.metric}",
                ),
            )
            hypotheses.append(h_cat)

        return hypotheses

    def _generate_data_quality_hypotheses(
        self, anomaly: Anomaly,
    ) -> list[Hypothesis]:
        """Generate data quality hypotheses: nulls, duplicates."""
        hypotheses: list[Hypothesis] = []
        table = anomaly.table
        if not table:
            table = self._find_transactional_table()
        if not table:
            return hypotheses

        amount_col = self._find_amount_column(table)
        if not amount_col:
            return hypotheses

        base_filter = self._get_base_filter(table)
        filter_clause = f"WHERE {base_filter}" if base_filter else ""

        # Hypothesis: null values in amount column
        h_nulls = Hypothesis(
            hypothesis_id=f"dq_nulls_{anomaly.metric}",
            hypothesis_type=HypothesisType.DATA_QUALITY,
            description=(
                f"NULL values in {amount_col} may be distorting {anomaly.metric}."
            ),
            drill_down_query=DrillDownQuery(
                sql=(
                    f"SELECT COUNT(*) AS total_rows, "
                    f"SUM(CASE WHEN {amount_col} IS NULL THEN 1 ELSE 0 END) AS null_count, "
                    f"ROUND(SUM(CASE WHEN {amount_col} IS NULL THEN 1 ELSE 0 END) * 100.0 "
                    f"/ NULLIF(COUNT(*), 0), 2) AS null_pct "
                    f"FROM {table} {filter_clause}"
                ),
                description=f"Check null rate in {amount_col}",
                hypothesis_id=f"dq_nulls_{anomaly.metric}",
            ),
        )
        hypotheses.append(h_nulls)

        return hypotheses

    # ── HYPOTHESIS EVALUATORS ──────────────────────────────────────────

    def _evaluate_temporal(
        self, hypothesis: Hypothesis, rows: list[dict],
    ) -> Hypothesis:
        """Evaluate a temporal hypothesis from drill-down results."""
        if len(rows) < 2:
            hypothesis.status = HypothesisStatus.INCONCLUSIVE
            hypothesis.evidence = "Insufficient temporal data points."
            hypothesis.confidence = 0.1
            return hypothesis

        # Check for period comparison (recent vs prior)
        if any("period" in str(row) for row in rows):
            totals = {
                row.get("period", ""): float(row.get("total", 0))
                for row in rows
            }
            recent = totals.get("recent", 0)
            prior = totals.get("prior", 0)
            if prior > 0:
                change_pct = (recent - prior) / prior * 100
                if abs(change_pct) > 10:
                    hypothesis.status = HypothesisStatus.SUPPORTED
                    hypothesis.evidence = (
                        f"Recent period total ({recent:,.0f}) differs from "
                        f"prior ({prior:,.0f}) by {change_pct:+.1f}%."
                    )
                    hypothesis.confidence = min(0.9, abs(change_pct) / 100)
                    return hypothesis

        hypothesis.status = HypothesisStatus.INCONCLUSIVE
        hypothesis.evidence = "No clear temporal pattern detected."
        hypothesis.confidence = 0.2
        return hypothesis

    def _evaluate_entity(
        self, hypothesis: Hypothesis, rows: list[dict],
    ) -> Hypothesis:
        """Evaluate an entity hypothesis — check for concentration."""
        if not rows:
            hypothesis.status = HypothesisStatus.INCONCLUSIVE
            hypothesis.confidence = 0.1
            return hypothesis

        # Check if top entity has >30% of total
        top_row = rows[0]
        pct = float(top_row.get("pct_of_total", 0))
        if pct > 30:
            hypothesis.status = HypothesisStatus.SUPPORTED
            hypothesis.evidence = (
                f"Top entity accounts for {pct:.1f}% of total — "
                f"high concentration suggests entity-driven anomaly."
            )
            hypothesis.confidence = min(0.95, pct / 100)
            return hypothesis

        hypothesis.status = HypothesisStatus.REFUTED
        hypothesis.evidence = (
            f"Top entity only accounts for {pct:.1f}% — "
            f"no single entity dominates."
        )
        hypothesis.confidence = 0.3
        return hypothesis

    def _evaluate_category(
        self, hypothesis: Hypothesis, rows: list[dict],
    ) -> Hypothesis:
        """Evaluate a category hypothesis — check for outsized segment."""
        if len(rows) < 2:
            hypothesis.status = HypothesisStatus.INCONCLUSIVE
            hypothesis.confidence = 0.1
            return hypothesis

        totals = [float(r.get("category_total", 0)) for r in rows]
        grand_total = sum(totals)
        if grand_total > 0 and totals:
            top_pct = totals[0] / grand_total * 100
            if top_pct > 60:
                hypothesis.status = HypothesisStatus.SUPPORTED
                hypothesis.evidence = (
                    f"Top category accounts for {top_pct:.1f}% — "
                    f"category concentration detected."
                )
                hypothesis.confidence = min(0.9, top_pct / 100)
                return hypothesis

        hypothesis.status = HypothesisStatus.REFUTED
        hypothesis.evidence = "No outsized category segment found."
        hypothesis.confidence = 0.2
        return hypothesis

    def _evaluate_data_quality(
        self, hypothesis: Hypothesis, rows: list[dict],
    ) -> Hypothesis:
        """Evaluate a data quality hypothesis — check null rate."""
        if not rows:
            hypothesis.status = HypothesisStatus.INCONCLUSIVE
            hypothesis.confidence = 0.1
            return hypothesis

        null_pct = float(rows[0].get("null_pct", 0))
        if null_pct > 5:
            hypothesis.status = HypothesisStatus.SUPPORTED
            hypothesis.evidence = (
                f"Null rate is {null_pct:.1f}% — likely distorting aggregations."
            )
            hypothesis.confidence = min(0.85, null_pct / 50)
            return hypothesis

        hypothesis.status = HypothesisStatus.REFUTED
        hypothesis.evidence = f"Null rate is only {null_pct:.1f}% — negligible."
        hypothesis.confidence = 0.1
        return hypothesis

    # ── HELPERS ────────────────────────────────────────────────────────

    def _find_transactional_table(self) -> str | None:
        """Find the primary transactional table from entity_map."""
        for name, entity in self._entities.items():
            if entity.get("type") == "TRANSACTIONAL":
                kc = entity.get("key_columns", {})
                if any(k in kc for k in ("amount_col", "grand_total", "amount")):
                    return entity.get("table", "")
        return None

    def _find_date_column(self, table: str) -> str | None:
        """Find the date column for a table."""
        for name, entity in self._entities.items():
            if entity.get("table") == table:
                kc = entity.get("key_columns", {})
                for key in ("invoice_date", "date_col", "date"):
                    if key in kc:
                        return kc[key]
        return None

    def _find_amount_column(self, table: str) -> str | None:
        """Find the amount column for a table."""
        for name, entity in self._entities.items():
            if entity.get("table") == table:
                kc = entity.get("key_columns", {})
                for key in ("amount_col", "grand_total", "amount"):
                    if key in kc:
                        return kc[key]
        return None

    def _find_customer_fk(self, table: str) -> str | None:
        """Find the customer FK column for a table."""
        for name, entity in self._entities.items():
            if entity.get("table") == table:
                kc = entity.get("key_columns", {})
                for key in ("customer_fk", "partner_fk"):
                    if key in kc:
                        return kc[key]
        return None

    def _find_category_columns(self, table: str) -> list[str]:
        """Find low-cardinality columns suitable for category breakdown."""
        if self.kg:
            lc_cols = self.kg.get_low_cardinality_columns(table)
            # Exclude columns already in base_filter (they're filters, not categories)
            filter_cols = set(self.kg.get_filter_columns_for_table(table))
            return [c.name for c in lc_cols if c.name not in filter_cols]
        return []

    def _get_base_filter(self, table: str) -> str:
        """Get the base filter for a table from entity_map."""
        for name, entity in self._entities.items():
            if entity.get("table") == table:
                return entity.get("base_filter", "")
        return ""
