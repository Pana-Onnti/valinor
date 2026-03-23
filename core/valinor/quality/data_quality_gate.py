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

try:
    from statsmodels.tsa.seasonal import STL
    from statsmodels.tsa.stattools import coint
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False

from shared.utils.sql_sanitizer import sanitize_base_filter  # VAL-49


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
        "schema_integrity":              15,
        "null_density":                  15,
        "duplicate_rate":                10,
        "accounting_balance":            20,
        "cross_table_reconcile":         15,
        "outlier_screen":                10,
        "benford_compliance":             5,
        "temporal_consistency":          10,
        "receivables_cointegration":      5,
    }

    # ERP → required tables for schema integrity check
    ERP_CORE_TABLES = {
        "odoo": {
            "tables": ["account_move", "account_move_line", "account_account", "res_partner"],
            "columns": {
                "account_move_line": ["debit", "credit", "date", "account_id", "move_id"],
                "account_move":      ["state", "partner_id", "invoice_date", "currency_id", "move_type", "name"],
                "account_account":   ["code", "account_type"],
            },
        },
        "openbravo": {
            "tables": ["c_invoice", "c_bpartner", "m_product", "c_order"],
            "columns": {
                "c_invoice":  ["c_bpartner_id", "dateinvoiced", "grandtotal", "issotrx"],
                "c_bpartner": ["name", "iscustomer", "isvendor"],
            },
        },
        "sap": {
            "tables": ["BKPF", "BSEG", "KNA1"],
            "columns": {},
        },
        # Generic / unknown: skip schema check
    }

    def __init__(self, engine, period_start: str, period_end: str,
                 erp: str = None, entity_map: dict | None = None,
                 db_schema: str = "public"):
        self.engine = engine
        self.period_start = period_start
        self.period_end = period_end
        self.erp = (erp or "").lower().strip()
        self.entity_map = entity_map or {}
        self.db_schema = db_schema or "public"

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    def run(self) -> DataQualityReport:
        """Run all checks and return a DataQualityReport."""
        import structlog
        logger = structlog.get_logger()

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
            self._check_receivables_revenue_cointegration,
        ]

        try:
            from api.metrics import DQ_CHECKS_TOTAL
            _dq_metrics = True
        except ImportError:
            _dq_metrics = False

        for method in check_methods:
            try:
                check = method()
            except Exception as e:
                import structlog as _sl
                _sl.get_logger().warning(
                    "dq_gate.check_error",
                    check=method.__name__,
                    error=str(e),
                )
                check = QualityCheckResult(
                    check_name=method.__name__.replace("_check_", ""),
                    passed=False,
                    score_impact=self.SCORE_WEIGHTS.get(
                        method.__name__.replace("_check_", ""), 5
                    ) // 3,  # Partial deduction for crashed checks
                    severity="WARNING",
                    detail=f"Check crashed (error treated as warning): {e}",
                    recommendation="Investigate why this check failed. "
                                   "The check may need schema or config adjustments.",
                )

            if _dq_metrics:
                result_label = "passed" if check.passed else "failed"
                DQ_CHECKS_TOTAL.labels(
                    check_name=check.check_name,
                    result=result_label,
                ).inc()

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

    def _find_transaction_table(self) -> Dict[str, Any]:
        """Find the primary transaction table from entity_map.

        Returns dict with table, amount_col, date_col, name_col, base_filter
        or empty dict if not found.
        """
        entities = self.entity_map.get("entities", {})
        for entity_name, entity in entities.items():
            if entity.get("type") == "TRANSACTIONAL":
                key_cols = entity.get("key_columns", {})
                amount_col = key_cols.get("amount_col")
                date_col = key_cols.get("date_col")
                if amount_col and date_col:
                    # VAL-49: sanitize base_filter at extraction point
                    try:
                        safe_filter = sanitize_base_filter(
                            entity.get("base_filter", ""),
                            context=f"dq_gate:{entity_name}",
                        )
                    except ValueError:
                        safe_filter = ""  # reject unsafe filters silently
                    return {
                        "table": entity.get("table", ""),
                        "amount_col": amount_col,
                        "date_col": date_col,
                        "name_col": key_cols.get("name") or key_cols.get("document_no"),
                        "base_filter": safe_filter,
                    }
        return {}

    def _scalar(self, conn, sql: str, params: dict = None) -> Any:
        """Execute a scalar SQL query and return the first column of the first row."""
        result = conn.execute(text(sql), params or {})
        row = result.fetchone()
        return row[0] if row is not None else None

    def _table_exists(self, conn, table_name: str) -> bool:
        sql = """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_name = :tname
        """
        count = self._scalar(conn, sql, {"schema": self.db_schema, "tname": table_name})
        return (count or 0) > 0

    def _column_exists(self, conn, table_name: str, column_name: str) -> bool:
        sql = """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name   = :tname
              AND column_name  = :cname
        """
        count = self._scalar(conn, sql, {"schema": self.db_schema, "tname": table_name, "cname": column_name})
        return (count or 0) > 0

    # -----------------------------------------------------------------------
    # Check 1 — Schema Integrity
    # -----------------------------------------------------------------------

    def _check_schema_integrity(self) -> QualityCheckResult:
        """Verify required tables and key columns exist.

        Uses entity_map when available (schema-agnostic), falls back to
        ERP_CORE_TABLES for backward compatibility.
        """
        # Prefer entity_map-driven check (schema-agnostic)
        entities = self.entity_map.get("entities", {})
        if entities:
            return self._check_schema_integrity_from_entity_map(entities)

        # Fallback: legacy ERP-specific check
        erp_spec = self.ERP_CORE_TABLES.get(self.erp)
        if erp_spec is None:
            return QualityCheckResult(
                check_name="schema_integrity",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail=f"Schema check skipped for ERP '{self.erp or 'unknown'}' — no required-table definition.",
            )

        required_tables = erp_spec["tables"]
        required_columns = erp_spec["columns"]

        with self.engine.connect() as conn:
            missing_tables = [t for t in required_tables if not self._table_exists(conn, t)]
            if missing_tables:
                return QualityCheckResult(
                    check_name="schema_integrity",
                    passed=False,
                    score_impact=self.SCORE_WEIGHTS["schema_integrity"],
                    severity="FATAL",
                    detail=f"Core tables missing for {self.erp}: {missing_tables}",
                    recommendation=f"Verify this is a {self.erp} database and the schema is accessible.",
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
                recommendation=f"Schema may be a non-standard {self.erp} version. Map column names before analysis.",
            )

        return QualityCheckResult(
            check_name="schema_integrity",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail="All required tables and columns present.",
        )

    def _check_schema_integrity_from_entity_map(self, entities: dict) -> QualityCheckResult:
        """Schema integrity check driven by entity_map — zero hardcoded ERP knowledge."""
        missing_tables = []
        missing_cols = []

        with self.engine.connect() as conn:
            for entity_name, entity in entities.items():
                table = entity.get("table", "")
                if not table:
                    continue
                if not self._table_exists(conn, table):
                    missing_tables.append(f"{entity_name} → {table}")
                    continue
                # Check key_columns exist
                for col_role, col_name in entity.get("key_columns", {}).items():
                    if col_name and not self._column_exists(conn, table, col_name):
                        missing_cols.append(f"{table}.{col_name} ({col_role})")

        if missing_tables:
            return QualityCheckResult(
                check_name="schema_integrity",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["schema_integrity"],
                severity="FATAL",
                detail=f"Entity tables missing: {missing_tables}",
                recommendation="Verify entity_map table names match the actual database schema.",
            )

        if missing_cols:
            return QualityCheckResult(
                check_name="schema_integrity",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["schema_integrity"],
                severity="FATAL",
                detail=f"Key columns missing: {missing_cols}",
                recommendation="Verify key_columns in entity_map. Column may have been renamed.",
            )

        return QualityCheckResult(
            check_name="schema_integrity",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=f"All {len(entities)} entity tables and key columns present.",
        )

    # -----------------------------------------------------------------------
    # Check 2 — Null Density
    # -----------------------------------------------------------------------

    def _check_null_density(self) -> QualityCheckResult:
        """Check null rates on critical columns.

        Uses entity_map key_columns when available (schema-agnostic),
        falls back to hardcoded Odoo columns for backward compatibility.
        """
        # Build thresholds from entity_map or legacy hardcoded values
        thresholds: Dict[tuple, float] = {}
        entities = self.entity_map.get("entities", {})
        if entities:
            # Entity-map-driven: check all key_columns
            for entity_name, entity in entities.items():
                table = entity.get("table", "")
                if not table:
                    continue
                for col_role, col_name in entity.get("key_columns", {}).items():
                    if not col_name:
                        continue
                    # Monetary and date columns are critical (low tolerance)
                    if "amount" in col_role or "total" in col_role:
                        thresholds[(table, col_name)] = 0.01
                    elif "date" in col_role:
                        thresholds[(table, col_name)] = 0.05
                    else:
                        thresholds[(table, col_name)] = 0.10
        else:
            # Legacy fallback: hardcoded Odoo columns
            thresholds = {
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
                if not self._table_exists(conn, table) or not self._column_exists(conn, table, col):
                    continue

                total = self._scalar(conn, f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                if not total or total == 0:
                    continue

                null_count = self._scalar(
                    conn,
                    f"SELECT COUNT(*) FROM {table} WHERE \"{col}\" IS NULL",  # noqa: S608
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
        """Detect duplicate invoice names in the analysis period.

        Uses entity_map for table/column discovery when available.
        """
        txn = self._find_transaction_table()
        if txn:
            table = txn["table"]
            date_col = txn["date_col"]
            name_col = txn.get("name_col")
            base_filter = txn.get("base_filter", "")
            if not name_col:
                return QualityCheckResult(
                    check_name="duplicate_rate",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail="No document name column in entity_map; duplicate check skipped.",
                )
            where_parts = [f"{date_col} BETWEEN :period_start AND :period_end",
                           f"{name_col} IS NOT NULL"]
            if base_filter:
                where_parts.insert(0, base_filter)
            where_clause = " AND ".join(where_parts)
            sql = f"""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) - COUNT(DISTINCT {name_col}) AS duplicates
                FROM {table}
                WHERE {where_clause}
            """
        else:
            # Legacy Odoo fallback
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
            table = "account_move"
        with self.engine.connect() as conn:
            if not self._table_exists(conn, table):
                return QualityCheckResult(
                    check_name="duplicate_rate",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail=f"{table} table not found; check skipped.",
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
        txn = self._find_transaction_table()
        if txn:
            table = txn["table"]
            amount_col = txn["amount_col"]
            date_col = txn["date_col"]
            base_filter = txn.get("base_filter", "")
            where_parts = [f"{date_col} BETWEEN :period_start AND :period_end",
                           f"{amount_col} > 0"]
            if base_filter:
                where_parts.insert(0, base_filter)
            sql = f"SELECT {amount_col} FROM {table} WHERE {' AND '.join(where_parts)}"
        else:
            table = "account_move"
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
            if not self._table_exists(conn, table):
                return QualityCheckResult(
                    check_name="outlier_screen",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail=f"{table} table not found; outlier check skipped.",
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

        txn = self._find_transaction_table()
        if txn:
            table = txn["table"]
            amount_col = txn["amount_col"]
            date_col = txn["date_col"]
            base_filter = txn.get("base_filter", "")
            where_parts = [f"{date_col} BETWEEN :period_start AND :period_end",
                           f"{amount_col} > 0"]
            if base_filter:
                where_parts.insert(0, base_filter)
            sql = f"SELECT {amount_col} FROM {table} WHERE {' AND '.join(where_parts)}"
        else:
            table = "account_move"
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
            if not self._table_exists(conn, table):
                return QualityCheckResult(
                    check_name="benford_compliance",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail=f"{table} table not found; Benford check skipped.",
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

    def _detect_structural_break(self, series: list, threshold: float = 5.0) -> bool:
        """
        Simple CUSUM test for structural break.
        Returns True if the cumulative sum of deviations from mean exceeds threshold * std.
        """
        if len(series) < 6:
            return False
        arr = np.array(series)
        mean = arr[:-2].mean()  # exclude last 2 periods from baseline
        std = arr[:-2].std()
        if std == 0:
            return False
        cusum = np.cumsum((arr - mean) / std)
        # Flag if CUSUM crosses threshold in the last 2 periods
        return bool(abs(cusum[-1]) > threshold or abs(cusum[-2]) > threshold)

    def _check_temporal_consistency(self) -> QualityCheckResult:
        """
        Temporal anomaly detection on monthly revenue history.

        If statsmodels is available and >= 12 months of history exist, uses STL
        decomposition to isolate the residual component before z-scoring — preventing
        legitimate Q4 seasonality from triggering false positives.

        Falls back to a simple z-score when statsmodels is unavailable or history
        is shorter than 12 months.

        Additionally runs a CUSUM structural-break test on the full history series.
        """
        txn = self._find_transaction_table()
        if txn:
            table = txn["table"]
            amount_col = txn["amount_col"]
            date_col = txn["date_col"]
            base_filter = txn.get("base_filter", "")
            hist_where = f"WHERE {base_filter} AND" if base_filter else "WHERE"
            sql_history = f"""
                SELECT
                    DATE_TRUNC('month', {date_col}) AS month,
                    SUM({amount_col}) AS revenue
                FROM {table}
                {hist_where} {date_col} < :period_start
                GROUP BY 1 ORDER BY 1 ASC LIMIT 24
            """
            sql_current = f"""
                SELECT COALESCE(SUM({amount_col}), 0)
                FROM {table}
                {hist_where} {date_col} BETWEEN :period_start AND :period_end
            """
        else:
            table = "account_move"
            sql_history = """
                SELECT
                    DATE_TRUNC('month', invoice_date) AS month,
                    SUM(amount_untaxed)               AS revenue
                FROM account_move
                WHERE move_type   = 'out_invoice'
                  AND state        = 'posted'
                  AND invoice_date < :period_start
                GROUP BY 1
                ORDER BY 1 ASC
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
            if not self._table_exists(conn, table):
                return QualityCheckResult(
                    check_name="temporal_consistency",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail=f"{table} table not found; temporal check skipped.",
                )

            history_rows = conn.execute(text(sql_history), params).fetchall()
            current_rev  = float(conn.execute(text(sql_current), params).scalar() or 0)

        # history_rows ordered ASC — chronological order for STL / CUSUM
        history_vals = [float(r[1]) for r in history_rows if r[1] is not None]

        if len(history_vals) < 6:
            return QualityCheckResult(
                check_name="temporal_consistency",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail=f"Insufficient history ({len(history_vals)} months) for temporal check.",
            )

        # ---- Choose z-score method ----------------------------------------
        method_label = "simple z-score"
        full_series = history_vals + [current_rev]

        if STATSMODELS_AVAILABLE and len(history_vals) >= 12:
            # STL decomposition — extract residual, then z-score the residual
            try:
                import pandas as pd
                series_arr = np.array(full_series, dtype=float)
                stl = STL(series_arr, period=12, robust=True)
                stl_result = stl.fit()
                residuals = stl_result.resid

                # Baseline residuals = all except last (current period)
                baseline_resid = residuals[:-1]
                current_resid  = residuals[-1]

                mean_r = float(np.mean(baseline_resid))
                std_r  = float(np.std(baseline_resid, ddof=1))

                if std_r < 1e-6:
                    z_score = 0.0
                else:
                    z_score = abs(current_resid - mean_r) / std_r

                method_label = "STL-residual z-score"
            except Exception:
                # Fall back to simple z-score if STL fails for any reason
                hist_arr  = np.array(history_vals)
                mean_hist = float(np.mean(hist_arr))
                std_hist  = float(np.std(hist_arr, ddof=1))
                z_score   = abs(current_rev - mean_hist) / std_hist if std_hist > 1e-6 else 0.0
        else:
            hist_arr  = np.array(history_vals)
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

        # ---- CUSUM structural-break test ----------------------------------
        struct_break = self._detect_structural_break(full_series)
        struct_break_suffix = " | CUSUM structural break detected in last 2 periods." if struct_break else ""

        if z_score > 3.0:
            return QualityCheckResult(
                check_name="temporal_consistency",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["temporal_consistency"],
                severity="WARNING",
                detail=(
                    f"Current period revenue anomalous: z={z_score:.2f} [{method_label}] "
                    f"(current={current_rev:,.0f}, n_history={len(history_vals)})"
                    f"{struct_break_suffix}"
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
                f"Revenue temporally consistent: z={z_score:.2f} [{method_label}] "
                f"(current={current_rev:,.0f}, n_history={len(history_vals)})"
                f"{struct_break_suffix}"
            ),
        )

    # -----------------------------------------------------------------------
    # Check 9 — Receivables / Revenue Cointegration
    # -----------------------------------------------------------------------

    def _check_receivables_revenue_cointegration(self) -> QualityCheckResult:
        """
        Test if receivables and revenue are cointegrated.
        If they should move together but diverge, either:
        a) A genuine business problem (collection failure) — legitimate finding
        b) A data quality problem — one of the series is wrong

        This check is WARNING only — divergence may be the actual insight.
        """
        sql_revenue = """
            SELECT DATE_TRUNC('month', invoice_date) as month, SUM(amount_untaxed) as revenue
            FROM account_move WHERE move_type='out_invoice' AND state='posted'
            AND invoice_date >= CURRENT_DATE - INTERVAL '13 months'
            GROUP BY 1 ORDER BY 1
        """
        sql_receivables = """
            SELECT DATE_TRUNC('month', date) as month, SUM(debit - credit) as receivables
            FROM account_move_line aml
            JOIN account_account aa ON aml.account_id = aa.id
            WHERE aa.account_type = 'asset_receivable' AND aml.date >= CURRENT_DATE - INTERVAL '13 months'
            GROUP BY 1 ORDER BY 1
        """

        with self.engine.connect() as conn:
            for tbl in ("account_move", "account_move_line", "account_account"):
                if not self._table_exists(conn, tbl):
                    return QualityCheckResult(
                        check_name="receivables_cointegration",
                        passed=True,
                        score_impact=0,
                        severity="INFO",
                        detail=f"Table {tbl} not found; cointegration check skipped.",
                    )

            rev_rows = conn.execute(text(sql_revenue)).fetchall()
            rec_rows = conn.execute(text(sql_receivables)).fetchall()

        # Align on common months
        rev_dict = {r[0]: float(r[1]) for r in rev_rows if r[1] is not None}
        rec_dict = {r[0]: float(r[1]) for r in rec_rows if r[1] is not None}
        common_months = sorted(set(rev_dict.keys()) & set(rec_dict.keys()))

        if len(common_months) < 8:
            return QualityCheckResult(
                check_name="receivables_cointegration",
                passed=True,
                score_impact=0,
                severity="INFO",
                detail=(
                    f"Insufficient overlapping months ({len(common_months)}) "
                    "for cointegration check (need >= 8)."
                ),
            )

        revenue     = np.array([rev_dict[m] for m in common_months])
        receivables = np.array([rec_dict[m] for m in common_months])

        if STATSMODELS_AVAILABLE:
            try:
                _, p_value, _ = coint(revenue, receivables)
                if p_value > 0.10:
                    return QualityCheckResult(
                        check_name="receivables_cointegration",
                        passed=False,
                        score_impact=self.SCORE_WEIGHTS["receivables_cointegration"],
                        severity="WARNING",
                        detail=(
                            f"Receivables and revenue are NOT cointegrated (p={p_value:.3f}). "
                            "Receivables are diverging from revenue pattern — "
                            "possible collection failure or data quality issue."
                        ),
                        recommendation="Compare DSO trend and review collection aging report. "
                                       "If intentional, this is a key executive finding.",
                    )
                return QualityCheckResult(
                    check_name="receivables_cointegration",
                    passed=True,
                    score_impact=0,
                    severity="INFO",
                    detail=(
                        f"Receivables and revenue are cointegrated (p={p_value:.3f}). "
                        "Series move together as expected."
                    ),
                )
            except Exception as exc:
                # Fallback to correlation if coint fails
                pass

        # Fallback: simple Pearson correlation
        corr = float(np.corrcoef(revenue, receivables)[0, 1])
        if corr < 0.3:
            return QualityCheckResult(
                check_name="receivables_cointegration",
                passed=False,
                score_impact=self.SCORE_WEIGHTS["receivables_cointegration"],
                severity="WARNING",
                detail=(
                    f"Low correlation between receivables and revenue (r={corr:.2f}). "
                    "Series are diverging — possible collection failure or data quality issue."
                ),
                recommendation="Review collection aging and DSO trend. "
                               "If receivables growing while revenue flat, flag for executive report.",
            )

        return QualityCheckResult(
            check_name="receivables_cointegration",
            passed=True,
            score_impact=0,
            severity="INFO",
            detail=(
                f"Receivables/revenue correlation adequate (r={corr:.2f}, "
                "statsmodels unavailable — using Pearson fallback)."
            ),
        )
