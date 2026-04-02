"""
Playground Swarm — Agent 2: Real Company Harvester.

Tier: hunter — uses yfinance to fetch real financial data for public companies
and maps it into ERP-like SQLite databases.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "JPM", "WMT", "JNJ", "PG"]


class RealCompanyHarvesterAgent(PlaygroundAgent):
    """Fetches real financial data via yfinance and maps to ERP-like schema."""

    def __init__(self) -> None:
        self.name = "real_company_harvester"
        self.tier = "hunter"
        super().__init__()

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        try:
            import yfinance as yf
        except ImportError:
            return AgentResult(
                agent_name=self.name,
                success=False,
                errors=["yfinance not installed — run: pip install yfinance"],
            )

        datasets: List[DatasetRecord] = []
        errors: List[str] = []

        for ticker in TICKERS:
            try:
                ds = self._process_ticker(ctx, yf, ticker)
                if ds:
                    datasets.append(ds)
                    await ctx.generated_datasets.put(ds)
            except Exception as exc:
                msg = f"Failed to process {ticker}: {exc}"
                self.logger.warning(msg)
                errors.append(msg)

        self._datasets_produced += len(datasets)
        return AgentResult(
            agent_name=self.name,
            success=len(datasets) > 0,
            datasets=datasets,
            errors=errors if errors else None,
            stats={
                "tickers_attempted": len(TICKERS),
                "tickers_succeeded": len(datasets),
            },
        )

    def _process_ticker(self, ctx: PlaygroundContext, yf: Any, ticker: str) -> Optional[DatasetRecord]:
        stock = yf.Ticker(ticker)

        # Fetch quarterly financials
        income_stmt = stock.quarterly_financials
        balance_sheet = stock.quarterly_balance_sheet

        if income_stmt is None or income_stmt.empty:
            self.logger.warning("%s: no income statement data available", ticker)
            return None

        db_path = ctx.datasets_dir / "real" / f"company_{ticker.lower()}.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        now = datetime.utcnow().isoformat()

        row_counts: Dict[str, int] = {}

        # ── c_bpartner: company as customer ───────────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS c_bpartner (
                c_bpartner_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                ticker TEXT,
                is_customer TEXT DEFAULT 'Y',
                is_vendor TEXT DEFAULT 'N',
                taxid TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM c_bpartner")
        info = stock.info or {}
        conn.execute(
            "INSERT INTO c_bpartner (c_bpartner_id, name, ticker, taxid, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                1,
                info.get("longName", info.get("shortName", ticker)),
                ticker,
                info.get("uuid", f"TAX-{ticker}"),
                now,
            ),
        )
        row_counts["c_bpartner"] = 1

        # ── c_invoice: derived from revenue data ─────────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS c_invoice (
                c_invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
                c_bpartner_id INTEGER,
                documentno TEXT,
                dateinvoiced TEXT,
                totallines REAL,
                grandtotal REAL,
                currency TEXT DEFAULT 'USD',
                docstatus TEXT DEFAULT 'CO',
                description TEXT,
                FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id)
            )
            """
        )
        conn.execute("DELETE FROM c_invoice")

        invoice_count = 0
        if income_stmt is not None and not income_stmt.empty:
            for col_date in income_stmt.columns:
                date_str = col_date.strftime("%Y-%m-%d") if hasattr(col_date, "strftime") else str(col_date)
                revenue = self._safe_float(income_stmt, "Total Revenue", col_date)
                cost = self._safe_float(income_stmt, "Cost Of Revenue", col_date)
                gross_profit = self._safe_float(income_stmt, "Gross Profit", col_date)
                net_income = self._safe_float(income_stmt, "Net Income", col_date)

                # Create an invoice-like record for each quarter's revenue
                if revenue is not None and revenue != 0:
                    conn.execute(
                        "INSERT INTO c_invoice "
                        "(c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, description) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            1,
                            f"INV-{ticker}-{date_str}",
                            date_str,
                            revenue,
                            revenue,
                            f"Quarterly revenue — COGS: {cost}, GP: {gross_profit}, NI: {net_income}",
                        ),
                    )
                    invoice_count += 1

        row_counts["c_invoice"] = invoice_count

        # ── c_balance_sheet: balance sheet snapshot ───────────────────
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS c_balance_sheet (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                c_bpartner_id INTEGER,
                report_date TEXT,
                total_assets REAL,
                total_liabilities REAL,
                total_equity REAL,
                cash_and_equivalents REAL,
                total_debt REAL,
                FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id)
            )
            """
        )
        conn.execute("DELETE FROM c_balance_sheet")

        bs_count = 0
        if balance_sheet is not None and not balance_sheet.empty:
            for col_date in balance_sheet.columns:
                date_str = col_date.strftime("%Y-%m-%d") if hasattr(col_date, "strftime") else str(col_date)
                conn.execute(
                    "INSERT INTO c_balance_sheet "
                    "(c_bpartner_id, report_date, total_assets, total_liabilities, "
                    "total_equity, cash_and_equivalents, total_debt) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        1,
                        date_str,
                        self._safe_float(balance_sheet, "Total Assets", col_date),
                        self._safe_float(balance_sheet, "Total Liabilities Net Minority Interest", col_date),
                        self._safe_float(balance_sheet, "Stockholders Equity", col_date),
                        self._safe_float(balance_sheet, "Cash And Cash Equivalents", col_date),
                        self._safe_float(balance_sheet, "Total Debt", col_date),
                    ),
                )
                bs_count += 1

        row_counts["c_balance_sheet"] = bs_count

        conn.commit()
        conn.close()

        total_rows = sum(row_counts.values())
        if total_rows == 0:
            self.logger.warning("%s: no data extracted", ticker)
            return None

        self.logger.info("%s: extracted %d rows across %d tables", ticker, total_rows, len(row_counts))
        return DatasetRecord(
            name=f"company_{ticker.lower()}",
            path=str(db_path),
            source_agent=self.name,
            tier=self.tier,
            created_at=now,
            row_counts=row_counts,
            tags=["real", "finance", "public_company", ticker],
            metadata={
                "ticker": ticker,
                "company_name": info.get("longName", ticker),
                "sector": info.get("sector", "unknown"),
                "industry": info.get("industry", "unknown"),
            },
        )

    @staticmethod
    def _safe_float(df: Any, row_label: str, col: Any) -> Optional[float]:
        """Safely extract a float from a DataFrame cell."""
        try:
            if row_label in df.index:
                val = df.loc[row_label, col]
                if val is not None:
                    import math

                    fval = float(val)
                    return fval if not math.isnan(fval) else None
        except (KeyError, ValueError, TypeError):
            pass
        return None
