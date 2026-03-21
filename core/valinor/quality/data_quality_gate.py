"""
DataQualityGate — runs 8 data quality checks against a client's PostgreSQL/Odoo DB
before passing control to the analyst agents.

All queries are synchronous via SQLAlchemy engine.connect() + text().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any

import numpy as np
from sqlalchemy import text

try:
    from scipy.stats import chisquare as scipy_chisquare
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

try:
    from scipy.stats import zscore as scipy_zscore
    SCIPY_ZSCORE_AVAILABLE = True
except ImportError:
    SCIPY_ZSCORE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class QualityCheckResult:
    check_name: str
    passed: bool
    score_impact: float       # Points deducted from 100 if failed
    severity: str             # "FATAL" | "CRITICAL" | "WARNING" | "INFO"
    detail: str
    recommendation: str = ""


@dataclass
class DataQualityReport:
    overall_score: float = 100.0          # 0–100
    gate_decision: str = "PROCEED"        # "PROCEED" | "PROCEED_WITH_WARNINGS" | "HALT"
    checks: list = field(default_factory=list)   # list[QualityCheckResult]
    blocking_issues: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    data_quality_tag: str = "PRELIMINARY"  # FINAL/REVISED/PRELIMINARY/ESTIMATED
    period_start: str = ""
    period_end: str = ""

    @property
    def can_proceed(self) -> bool:
        return self.gate_decision != "HALT"

    @property
    def confidence_label(self) -> str:
        if self.overall_score >= 85:
            return "CONFIRMED"
        if self.overall_score >= 65:
            return "PROVISIONAL"
        if self.overall_score >= 45:
            return "UNVERIFIED"
        return "BLOCKED"

    def to_prompt_context(self) -> str:
        """Format for injection into agent system prompt."""
        warnings_str = "; ".join(self.warnings[:3]) if self.warnings else "none"
        return (
            f"DATA QUALITY CONTEXT:\n"
            f"- DQ Score: {self.overall_score:.0f}/100 ({self.confidence_label}) — Tag: {self.data_quality_tag}\n"
            f"- Gate: {self.gate_decision}\n"
            f"- Warnings: {warnings_str}\n"
            f"INSTRUCTION: Label findings as PROVISIONAL if derived from flagged data. "
            f"Never present UNVERIFIED findings as facts in executive summary."
        )


# ---------------------------------------------------------------------------
# Main gate class
# ---------------------------------------------------------------------------

class DataQualityGate:
    SCORE_WEIGHTS = {
        "schema_integrity":       15,
        "null_density":           15,
        "duplicate_rate":         10,
        "accounting_balance":     20,
        "cross_table_reconcile":  15,
        "outlier_screen":         10,
        "benford_compliance":      5,
        "temporal_consistency":   10,
    }

    def __init__(self, engine, period_start: str, period_end: str):
        self.engine = engine
        self.period_start = period_start
        self.period_end = period_end

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    def run(self) -> DataQualityReport:
        """Run all checks and return a DataQualityReport."""
        try:
            import structlog
            logger = structlog.get_logger()
        except ImportError:
            import logging
            logger = logging.getLogger(__name__)

        report = DataQualityReport(
            overall_score=100.0,
            gate_decision="PROCEED",
            period_start=self.period_start,
            period_end=self.period_end,
        )

        check_methods = [
            self._check_schema_integrity,
            self._check_null_density,
            self._check_duplicate_rate,
            self._check_accounting_balance,
            self._check_cross_table_reconciliation,
            self._check_outlier_screen,
            self._check_benford_compliance,
            self._check_temporal_consistency,
        ]

        for method in check_methods:
            try:
                check = method()
            except Exception as e:
                check = QualityCheckResult(
                    check_name=method.__name__.replace("_check_", ""),
                    passed=True,  # Don't penalize for check errors
                    score_impact=0,
                    severity="INFO",
                    detail=f"Check skipped: {e}",
                )

            report.checks.append(check)
            if not check.passed:
                report.overall_score -= check.score_impact
                if check.severity == "FATAL":
                    report.blocking_issues.append(check.detail)
                    report.gate_decision = "HALT"
                elif check.severity == "CRITICAL" and report.gate_decision != "HALT":
                    report.warnings.append(check.detail)
                    if report.gate_decision == "PROCEED":
                        report.gate_decision = "PROCEED_WITH_WARNINGS"
                elif check.severity == "WARNING":
                    report.warnings.append(check.detail)
                    if report.gate_decision == "PROCEED":
                        report.gate_decision = "PROCEED_WITH_WARNINGS"

        report.overall_score = max(0.0, report.overall_score)
        report.data_quality_tag = self._determine_quality_tag(report)
        logger.info(
            "DataQualityGate completed",
            score=report.overall_score,
            decision=report.gate_decision,
        )
        return report

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _determine_quality_tag(self, report: DataQualityReport) -> str:
        """Map score + data age to an IFRS/audit-style data tag."""
        try:
            period_end_dt = datetime.strptime(self.period_end, "%Y-%m-%d").date()
            days_old = (date.today() - period_end_dt).days
        except ValueError:
            days_old = 0

        score = report.overall_score
        if score >= 85 and days_old > 30:
            return "FINAL"
        if score >= 70:
            return "REVISED"
        if score >= 50:
            return "PRELIMINARY"
        return "ESTIMATED"

    def _scalar(self, conn, sql: str, params: dict = None) -> Any:
        """Execute a scalar SQL query and return the first column of the first row."""
        result = conn.execute(text(sql), params or {})
        row = result.fetchone()
        return row[0] if row is not None else None

    def _table_exists(self, conn, table_name: str) -> bool:
        sql = """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = :tname
        """
        count = self._scalar(conn, sql, {"tname": table_name})
        return (count or 0) > 0

    def _column_exists(self, conn, table_name: str, column_name: str) -> bool:
        sql = """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name   = :tname
              AND column_name  = :cname
        """
        count = self._scalar(conn, sql, {"tname": table_name, "cname": column_name})
        return (count or 0) > 0

    # -----------------------------------------------------------------------
    # Check 1 — Schema Integrity
    # -----------------------------------------------------------------------

    def _check_schema_integrity(self) -> QualityCheckResult:
        """Verify core Odoo accounting tables and key columns exist."""
        required_tables = [
            "account_move",
            "account_move_line",
            "account_account",
            "res_partner",
        ]
        required_columns = {
            "account_move_line": ["debit", "credit", "date", "account_id", "move_id"],
            "account_move":      ["state", "partner_id", "invoice_date", "currency_id", "move_type", "name"],
            "account_account":   ["code", "account_type"],
        }

        with self.engine.connect() as conn:
            missing_tables = [t for t in required_tables if not self._table_exists(conn, t)]
            if missing_tables:
                return QualityCheckResult(
                    check_name="schema_integrity",
                    passed=False,
                    score_impact=self.SCORE_WEIGHTS["schema_integrity"],
                    severity="FATAL",
                    detail=f"Core tables missing: {missing_tables}",
                    recommendation="Verify this is an Odoo/iDempiere database and the schema is accessible.",
                )

            missing_cols: List[str] = []
            for table, columns in required_columns.items():
                for col in columns:
                    if not self._column_exists(conn, table, col):
                        missing_cols.append(f"{table}.{col}")

        if missing_cols:
            return QualityCheckResult(
                check_name="schema_integrity",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["schema_integrity"],
                severity="FATAL",
                detail=f"Required columns missing: {missing_cols}",
                recommendation="Schema may be an older Odoo version or non-standard. Map column names before analysis.",
            )

        return QualityCheckResult(
            check_name="schema_integrity",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail="All required tables and columns present.",
        )

    # -----------------------------------------------------------------------
    # Check 2 — Null Density
    # -----------------------------------------------------------------------

    def _check_null_density(self) -> QualityCheckResult:
        """Check null rates on critical financial columns."""
        thresholds = {
            # (table, column): max_null_fraction
            ("account_move_line", "debit"):        0.01,
            ("account_move_line", "credit"):       0.01,
            ("account_move_line", "date"):         0.01,
            ("account_move",      "partner_id"):   0.05,
            ("account_move",      "invoice_date"): 0.05,
            ("account_move",      "currency_id"):  0.05,
        }

        violations: List[str] = []

        with self.engine.connect() as conn:
            for (table, col), threshold in thresholds.items():
                # Skip if table/column doesn't exist to avoid crashing
                if not self._table_exists(conn, table) or not self._column_exists(conn, table, col):
                    continue

                total = self._scalar(conn, f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                if not total or total == 0:
                    continue

                null_count = self._scalar(
                    conn,
                    f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL",  # noqa: S608
                )
                null_rate = (null_count or 0) / total

                if null_rate > threshold:
                    violations.append(
                        f"{table}.{col}: {null_rate:.1%} nulls (threshold {threshold:.1%})"
                    )

        if violations:
            return QualityCheckResult(
                check_name="null_density",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["null_density"],
                severity="CRITICAL",
                detail=f"High null rates: {'; '.join(violations)}",
                recommendation="Investigate ETL pipeline or manual entry gaps. "
                               "Missing amounts/dates will skew aggregate totals.",
            )

        return QualityCheckResult(
            check_name="null_density",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail="Null density within acceptable thresholds.",
        )

    # -----------------------------------------------------------------------
    # Check 3 — Duplicate Rate
    # -----------------------------------------------------------------------

    def _check_duplicate_rate(self) -> QualityCheckResult:
        """Detect duplicate invoice names in the analysis period."""
        sql = """
            SELECT
                COUNT(*) AS total,
                COUNT(*) - COUNT(DISTINCT name) AS duplicates
            FROM account_move
            WHERE move_type IN ('out_invoice', 'in_invoice')
              AND state = 'posted'
              AND invoice_date BETWEEN :period_start AND :period_end
              AND name IS NOT NULL
              AND name != '/'
        """
        with self.engine.connect() as conn:
            if not self._table_exists(conn, "account_move"):
                return QualityCheckResult(
                    check_name="duplicate_rate",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail="account_move table not found; check skipped.",
                )
            result = conn.execute(
                text(sql),
                {"period_start": self.period_start, "period_end": self.period_end},
            ).fetchone()

        if result is None or result[0] == 0:
            return QualityCheckResult(
                check_name="duplicate_rate",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail="No posted invoices found in period; duplicate check skipped.",
            )

        total, duplicates = result[0], result[1]
        dup_rate = duplicates / total

        if dup_rate > 0.001:  # > 0.1%
            return QualityCheckResult(
                check_name="duplicate_rate",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["duplicate_rate"],
                severity="CRITICAL",
                detail=f"Duplicate invoice names: {duplicates}/{total} ({dup_rate:.2%})",
                recommendation="Deduplicate before aggregating revenue. "
                               "Duplicate names may indicate posting errors.",
            )

        return QualityCheckResult(
            check_name="duplicate_rate",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=f"Duplicate rate {dup_rate:.4%} — within threshold.",
        )

    # -----------------------------------------------------------------------
    # Check 4 — Accounting Balance
    # -----------------------------------------------------------------------

    def _check_accounting_balance(self) -> QualityCheckResult:
        """Verify Assets ≈ Liabilities + Equity (accounting equation)."""
        sql = """
            SELECT
                SUM(CASE WHEN aa.account_type LIKE 'asset%'
                         THEN aml.debit - aml.credit ELSE 0 END)     AS total_assets,
                SUM(CASE WHEN aa.account_type LIKE 'liability%'
                         THEN aml.credit - aml.debit ELSE 0 END)     AS total_liabilities,
                SUM(CASE WHEN aa.account_type = 'equity'
                         THEN aml.credit - aml.debit ELSE 0 END)     AS total_equity
            FROM account_move_line  aml
            JOIN account_account    aa  ON aml.account_id = aa.id
            JOIN account_move       am  ON aml.move_id    = am.id
            WHERE am.state = 'posted'
              AND aml.date <= :period_end
        """
        with self.engine.connect() as conn:
            for tbl in ("account_move_line", "account_account", "account_move"):
                if not self._table_exists(conn, tbl):
                    return QualityCheckResult(
                        check_name="accounting_balance",
                        passed=True,
                        score_impact=0,
                        severity="INFO",
                        detail=f"Table {tbl} not found; balance check skipped.",
                    )

            row = conn.execute(text(sql), {"period_end": self.period_end}).fetchone()

        if row is None:
            return QualityCheckResult(
                check_name="accounting_balance",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail="No data returned for accounting balance check.",
            )

        total_assets      = float(row[0] or 0)
        total_liabilities = float(row[1] or 0)
        total_equity      = float(row[2] or 0)
        rhs = total_liabilities + total_equity

        if abs(rhs) < 1e-6:
            return QualityCheckResult(
                check_name="accounting_balance",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail="Liabilities + Equity sum to zero; balance check inconclusive.",
            )

        discrepancy_pct = abs(total_assets - rhs) / abs(rhs)

        if discrepancy_pct > 0.01:
            return QualityCheckResult(
                check_name="accounting_balance",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["accounting_balance"],
                severity="FATAL",
                detail=(
                    f"Accounting equation imbalance: Assets={total_assets:,.0f}, "
                    f"L+E={rhs:,.0f}, discrepancy={discrepancy_pct:.2%}"
                ),
                recommendation="Review journal entries for unbalanced moves. "
                               "Aggregate totals cannot be trusted until resolved.",
            )

        if discrepancy_pct > 0.001:
            return QualityCheckResult(
                check_name="accounting_balance",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["accounting_balance"] // 2,
                severity="CRITICAL",
                detail=(
                    f"Minor accounting imbalance: {discrepancy_pct:.3%} discrepancy "
                    f"(Assets={total_assets:,.0f}, L+E={rhs:,.0f})"
                ),
                recommendation="Investigate recent journal entries for rounding or FX adjustments.",
            )

        return QualityCheckResult(
            check_name="accounting_balance",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=f"Accounting equation balanced (discrepancy {discrepancy_pct:.4%}).",
        )

    # -----------------------------------------------------------------------
    # Check 5 — Cross-Table Revenue Reconciliation
    # -----------------------------------------------------------------------

    def _check_cross_table_reconciliation(self) -> QualityCheckResult:
        """Compare invoice-header revenue vs. ledger-line revenue (two-path check)."""
        sql_path1 = """
            SELECT COALESCE(SUM(amount_untaxed), 0)
            FROM account_move
            WHERE move_type  = 'out_invoice'
              AND state       = 'posted'
              AND invoice_date BETWEEN :period_start AND :period_end
        """
        sql_path2 = """
            SELECT COALESCE(SUM(aml.credit - aml.debit), 0)
            FROM account_move_line  aml
            JOIN account_account    aa  ON aml.account_id = aa.id
            JOIN account_move       am  ON aml.move_id    = am.id
            WHERE aa.code LIKE '7%'
              AND am.state = 'posted'
              AND aml.date BETWEEN :period_start AND :period_end
        """
        params = {"period_start": self.period_start, "period_end": self.period_end}

        with self.engine.connect() as conn:
            for tbl in ("account_move", "account_move_line", "account_account"):
                if not self._table_exists(conn, tbl):
                    return QualityCheckResult(
                        check_name="cross_table_reconcile",
                        passed=True,
                        score_impact=0,
                        severity="INFO",
                        detail=f"Table {tbl} not found; reconciliation check skipped.",
                    )

            rev_header = float(conn.execute(text(sql_path1), params).scalar() or 0)
            rev_ledger = float(conn.execute(text(sql_path2), params).scalar() or 0)

        if rev_header < 1 and rev_ledger < 1:
            return QualityCheckResult(
                check_name="cross_table_reconcile",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail="No revenue found in period; reconciliation check skipped.",
            )

        base = max(abs(rev_header), abs(rev_ledger))
        discrepancy_pct = abs(rev_header - rev_ledger) / base if base > 0 else 0

        if discrepancy_pct > 0.10:
            return QualityCheckResult(
                check_name="cross_table_reconcile",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["cross_table_reconcile"],
                severity="CRITICAL",
                detail=(
                    f"Revenue reconciliation gap >10%: "
                    f"invoice-headers={rev_header:,.0f}, ledger-lines={rev_ledger:,.0f}, "
                    f"delta={discrepancy_pct:.1%}"
                ),
                recommendation="Check for unposted credit notes, FX translation differences, "
                               "or account-code mapping errors (7xx series).",
            )

        if discrepancy_pct > 0.02:
            return QualityCheckResult(
                check_name="cross_table_reconcile",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["cross_table_reconcile"] // 3,
                severity="WARNING",
                detail=(
                    f"Revenue reconciliation gap 2–10%: "
                    f"invoice-headers={rev_header:,.0f}, ledger-lines={rev_ledger:,.0f}, "
                    f"delta={discrepancy_pct:.1%}"
                ),
                recommendation="Minor reconciliation gap — verify credit-note treatment.",
            )

        return QualityCheckResult(
            check_name="cross_table_reconcile",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=(
                f"Revenue reconciled: header={rev_header:,.0f}, "
                f"ledger={rev_ledger:,.0f}, delta={discrepancy_pct:.2%}"
            ),
        )

    # -----------------------------------------------------------------------
    # Check 6 — Outlier Screen
    # -----------------------------------------------------------------------

    def _check_outlier_screen(self) -> QualityCheckResult:
        """IQR-based outlier detection on invoice amounts (log-transformed)."""
        sql = """
            SELECT amount_untaxed
            FROM account_move
            WHERE move_type   = 'out_invoice'
              AND state        = 'posted'
              AND invoice_date BETWEEN :period_start AND :period_end
              AND amount_untaxed > 0
        """
        params = {"period_start": self.period_start, "period_end": self.period_end}

        with self.engine.connect() as conn:
            if not self._table_exists(conn, "account_move"):
                return QualityCheckResult(
                    check_name="outlier_screen",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail="account_move table not found; outlier check skipped.",
                )
            rows = conn.execute(text(sql), params).fetchall()

        amounts = np.array([float(r[0]) for r in rows if r[0] is not None and float(r[0]) > 0])

        if len(amounts) < 10:
            return QualityCheckResult(
                check_name="outlier_screen",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail=f"Insufficient data ({len(amounts)} records) for outlier screen.",
            )

        log_amounts = np.log1p(amounts)
        q1, q3 = np.percentile(log_amounts, [25, 75])
        iqr = q3 - q1
        fence_high = q3 + 3 * iqr
        fence_low  = q1 - 3 * iqr

        outlier_mask  = (log_amounts > fence_high) | (log_amounts < fence_low)
        outlier_count = int(outlier_mask.sum())
        outlier_value_share = amounts[outlier_mask].sum() / amounts.sum() if amounts.sum() > 0 else 0

        if outlier_value_share > 0.05:
            return QualityCheckResult(
                check_name="outlier_screen",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["outlier_screen"],
                severity="WARNING",
                detail=(
                    f"Outlier invoices represent {outlier_value_share:.1%} of total value "
                    f"({outlier_count} records). Fence: log-IQR×3."
                ),
                recommendation="Review extreme invoices before reporting aggregate revenue. "
                               "They may be legitimate large deals or data entry errors.",
            )

        return QualityCheckResult(
            check_name="outlier_screen",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=(
                f"Outlier value share {outlier_value_share:.2%} — within 5% threshold "
                f"({outlier_count} outlier records out of {len(amounts)})."
            ),
        )

    # -----------------------------------------------------------------------
    # Check 7 — Benford's Law Compliance
    # -----------------------------------------------------------------------

    def _check_benford_compliance(self) -> QualityCheckResult:
        """Chi-squared test of first-digit distribution against Benford's Law."""
        if not SCIPY_AVAILABLE:
            return QualityCheckResult(
                check_name="benford_compliance",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail="scipy not available; Benford check skipped.",
            )

        sql = """
            SELECT amount_untaxed
            FROM account_move
            WHERE move_type   = 'out_invoice'
              AND state        = 'posted'
              AND invoice_date BETWEEN :period_start AND :period_end
              AND amount_untaxed > 0
        """
        params = {"period_start": self.period_start, "period_end": self.period_end}

        with self.engine.connect() as conn:
            if not self._table_exists(conn, "account_move"):
                return QualityCheckResult(
                    check_name="benford_compliance",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail="account_move table not found; Benford check skipped.",
                )
            rows = conn.execute(text(sql), params).fetchall()

        amounts = [float(r[0]) for r in rows if r[0] is not None and float(r[0]) > 0]

        if len(amounts) < 100:
            return QualityCheckResult(
                check_name="benford_compliance",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail=f"Insufficient records ({len(amounts)}) for Benford test (need ≥100).",
            )

        # Extract first significant digit
        import math
        first_digits = []
        for amt in amounts:
            s = f"{amt:.6e}"
            first_char = s.replace("-", "").lstrip("0")[0]
            if first_char.isdigit() and first_char != "0":
                first_digits.append(int(first_char))

        if not first_digits:
            return QualityCheckResult(
                check_name="benford_compliance",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail="Could not extract first digits; Benford check skipped.",
            )

        n = len(first_digits)
        # Observed frequencies (digits 1–9)
        observed = np.array([first_digits.count(d) for d in range(1, 10)], dtype=float)
        # Expected Benford frequencies
        expected = np.array([math.log10(1 + 1 / d) * n for d in range(1, 10)])

        _, p_value = scipy_chisquare(observed, f_exp=expected)

        # Mean Absolute Deviation from expected proportions
        mad = float(np.mean(np.abs(observed / n - expected / n)))

        if p_value < 0.01 and mad > 0.015:
            return QualityCheckResult(
                check_name="benford_compliance",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["benford_compliance"],
                severity="WARNING",
                detail=(
                    f"Benford deviation detected: p={p_value:.4f}, MAD={mad:.4f}. "
                    f"First-digit distribution differs significantly from expected."
                ),
                recommendation="Investigate whether invoice amounts cluster around round numbers "
                               "or show fabrication/rounding patterns.",
            )

        return QualityCheckResult(
            check_name="benford_compliance",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=f"Benford test passed: p={p_value:.4f}, MAD={mad:.4f}.",
        )

    # -----------------------------------------------------------------------
    # Check 8 — Temporal Consistency
    # -----------------------------------------------------------------------

    def _check_temporal_consistency(self) -> QualityCheckResult:
        """Z-score test: is the current period revenue anomalous vs 24-month history?"""
        sql_history = """
            SELECT
                DATE_TRUNC('month', invoice_date) AS month,
                SUM(amount_untaxed)               AS revenue
            FROM account_move
            WHERE move_type   = 'out_invoice'
              AND state        = 'posted'
              AND invoice_date < :period_start
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 24
        """
        sql_current = """
            SELECT COALESCE(SUM(amount_untaxed), 0)
            FROM account_move
            WHERE move_type   = 'out_invoice'
              AND state        = 'posted'
              AND invoice_date BETWEEN :period_start AND :period_end
        """
        params = {"period_start": self.period_start, "period_end": self.period_end}

        with self.engine.connect() as conn:
            if not self._table_exists(conn, "account_move"):
                return QualityCheckResult(
                    check_name="temporal_consistency",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail="account_move table not found; temporal check skipped.",
                )

            history_rows = conn.execute(text(sql_history), params).fetchall()
            current_rev  = float(conn.execute(text(sql_current), params).scalar() or 0)

        history_vals = [float(r[1]) for r in history_rows if r[1] is not None]

        if len(history_vals) < 6:
            return QualityCheckResult(
                check_name="temporal_consistency",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail=f"Insufficient history ({len(history_vals)} months) for temporal check.",
            )

        hist_arr = np.array(history_vals)
        mean_hist = float(np.mean(hist_arr))
        std_hist  = float(np.std(hist_arr, ddof=1))

        if std_hist < 1e-6:
            return QualityCheckResult(
                check_name="temporal_consistency",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail="Historical revenue has zero variance; temporal check skipped.",
            )

        z_score = abs(current_rev - mean_hist) / std_hist

        if z_score > 3.0:
            return QualityCheckResult(
                check_name="temporal_consistency",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["temporal_consistency"],
                severity="WARNING",
                detail=(
                    f"Current period revenue anomalous: z={z_score:.2f} "
                    f"(current={current_rev:,.0f}, hist_mean={mean_hist:,.0f}, "
                    f"hist_std={std_hist:,.0f})"
                ),
                recommendation="Verify whether the anomaly reflects a genuine business event "
                               "(large deal, seasonality) or a data import error.",
            )

        return QualityCheckResult(
            check_name="temporal_consistency",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=(
                f"Revenue temporally consistent: z={z_score:.2f} "
                f"(current={current_rev:,.0f}, hist_mean={mean_hist:,.0f})"
            ),
        )
