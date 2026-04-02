"""
Playground Swarm — Agent 8: Time Warp Generator.

Takes a single-period dataset and generates 6 monthly periods with
growth trends, seasonality, customer churn, and new products.
"""

import json
import math
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

N_PERIODS = 6
GROWTH_RATE = 0.05          # 5 % monthly
SEASONALITY_AMP = 0.15      # ±15 %
CHURN_RATE = 0.05           # 5 % per period
NEW_CUSTOMER_RATE = 0.03    # 3 % per period
NEW_PRODUCTS_PER_PERIOD = (2, 3)


class TimeWarpGeneratorAgent(PlaygroundAgent):
    """Generates multi-period time-series datasets from a single source."""

    name = "time_warp_generator"
    tier = "bootstrapper"

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        datasets: List[DatasetRecord] = []
        errors: List[str] = []

        synth_dir = ctx.datasets_dir / "synthetic"
        if not synth_dir.exists():
            self.logger.info("No synthetic datasets dir — skipping time warp.")
            return AgentResult(self.name, success=True, datasets=[], stats={"sources": 0})

        source_dbs = list(synth_dir.glob("*.db"))
        if not source_dbs:
            self.logger.info("No synthetic source DBs found — skipping.")
            return AgentResult(self.name, success=True, datasets=[], stats={"sources": 0})

        # Pick one source
        src_path = random.choice(source_dbs)
        source_name = src_path.stem
        out_dir = ctx.datasets_dir / "bootstrapped"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            base_tables = self._read_tables(src_path)
            if not base_tables:
                return AgentResult(self.name, success=True, datasets=[], stats={"sources": 0})

            manifest_entries: List[Dict[str, Any]] = []

            for period in range(1, N_PERIODS + 1):
                evolved = self._evolve_period(base_tables, period)
                out_path = out_dir / f"timewarp_{source_name}_{period}.db"
                row_counts = self._write_tables(evolved, out_path)

                record = DatasetRecord(
                    name=out_path.stem,
                    path=str(out_path),
                    source_agent=self.name,
                    tier=self.tier,
                    created_at=datetime.utcnow().isoformat(),
                    row_counts=row_counts,
                    tags=["time_series", f"period:{period}", f"source:{source_name}"],
                    metadata={
                        "period": period,
                        "source_path": str(src_path),
                        "total_periods": N_PERIODS,
                    },
                )
                datasets.append(record)
                await ctx.generated_datasets.put(record)

                manifest_entries.append({
                    "period": period,
                    "path": str(out_path),
                    "row_counts": row_counts,
                })

            # Write manifest
            manifest_path = out_dir / f"timewarp_{source_name}_manifest.json"
            manifest_path.write_text(json.dumps({
                "source": str(src_path),
                "source_name": source_name,
                "total_periods": N_PERIODS,
                "created_at": datetime.utcnow().isoformat(),
                "periods": manifest_entries,
            }, indent=2, default=str))

            self.logger.info(
                "Generated %d time-warp periods from %s", N_PERIODS, source_name
            )
        except Exception as exc:
            msg = f"Error in time warp for {src_path.name}: {exc}"
            self.logger.error(msg)
            errors.append(msg)

        return AgentResult(
            self.name,
            success=len(errors) == 0,
            datasets=datasets,
            errors=errors,
            stats={"source": source_name, "periods_generated": len(datasets)},
        )

    # ── period evolution ──────────────────────────────────────────────

    def _evolve_period(
        self, base_tables: Dict[str, pd.DataFrame], period: int
    ) -> Dict[str, pd.DataFrame]:
        """Create an evolved copy of base tables for a given period."""
        result: Dict[str, pd.DataFrame] = {}
        for table_name, df in base_tables.items():
            df = df.copy()

            # Adjust dates
            df = self._shift_dates(df, period)

            # Growth: scale monetary / numeric amounts
            df = self._apply_growth(df, period)

            # Seasonality
            df = self._apply_seasonality(df, period)

            # Customer churn & new customers
            if self._looks_like_customer_table(table_name, df):
                df = self._apply_churn_and_growth(df, period)

            # New products
            if self._looks_like_product_table(table_name, df):
                df = self._add_new_products(df, period)

            result[table_name] = df.reset_index(drop=True)
        return result

    @staticmethod
    def _shift_dates(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """Shift all date-like columns forward by (period-1) months."""
        date_cols = [
            c for c in df.columns
            if any(hint in c.lower() for hint in ("date", "created", "updated", "timestamp"))
        ]
        offset = timedelta(days=30 * (period - 1))
        for col in date_cols:
            try:
                parsed = pd.to_datetime(df[col], errors="coerce")
                valid = parsed.notna()
                if valid.any():
                    df.loc[valid, col] = (parsed[valid] + offset).astype(str)
            except Exception:
                pass
        return df

    @staticmethod
    def _apply_growth(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """Linear 5 % monthly growth on monetary columns."""
        monetary_hints = {"amount", "total", "price", "cost", "revenue", "balance", "debit", "credit"}
        growth_factor = 1.0 + GROWTH_RATE * (period - 1)
        for col in df.columns:
            if any(h in col.lower() for h in monetary_hints):
                if pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col] * growth_factor
        return df

    @staticmethod
    def _apply_seasonality(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """Cosine seasonality with peaks at months 3 and 6."""
        # cos peaks at 0, 2pi; we want peaks at period 3 and 6
        season_factor = 1.0 + SEASONALITY_AMP * math.cos(2 * math.pi * (period - 3) / 3)
        monetary_hints = {"amount", "total", "price", "revenue"}
        for col in df.columns:
            if any(h in col.lower() for h in monetary_hints):
                if pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col] * season_factor
        return df

    @staticmethod
    def _looks_like_customer_table(name: str, df: pd.DataFrame) -> bool:
        hints = {"customer", "client", "partner", "contact"}
        return any(h in name.lower() for h in hints) or any(
            h in c.lower() for c in df.columns for h in hints
        )

    @staticmethod
    def _looks_like_product_table(name: str, df: pd.DataFrame) -> bool:
        hints = {"product", "item", "article", "sku"}
        return any(h in name.lower() for h in hints)

    @staticmethod
    def _apply_churn_and_growth(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """Remove churned customers and add new ones each period."""
        if period == 1 or df.empty:
            return df

        # Churn
        n_churn = max(0, int(len(df) * CHURN_RATE * (period - 1)))
        n_churn = min(n_churn, len(df) - 1)  # keep at least 1
        if n_churn > 0:
            drop_idx = np.random.choice(df.index, size=n_churn, replace=False)
            df = df.drop(drop_idx)

        # New customers
        n_new = max(1, int(len(df) * NEW_CUSTOMER_RATE))
        if len(df) > 0:
            new_rows = df.sample(n=n_new, replace=True).copy()
            # Give them new IDs where possible
            for col in new_rows.columns:
                if "id" in col.lower() and pd.api.types.is_numeric_dtype(new_rows[col]):
                    max_id = int(df[col].max()) if df[col].notna().any() else 0
                    new_rows[col] = range(max_id + 1, max_id + 1 + n_new)
                elif "name" in col.lower():
                    new_rows[col] = [f"NewCustomer_{period}_{i}" for i in range(n_new)]
            df = pd.concat([df, new_rows], ignore_index=True)

        return df

    @staticmethod
    def _add_new_products(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """Add 2-3 new products per period (starting period 2)."""
        if period == 1 or df.empty:
            return df

        n_new = random.randint(*NEW_PRODUCTS_PER_PERIOD)
        new_rows = df.sample(n=min(n_new, len(df)), replace=True).copy()
        for col in new_rows.columns:
            if "id" in col.lower() and pd.api.types.is_numeric_dtype(new_rows[col]):
                max_id = int(df[col].max()) if df[col].notna().any() else 0
                new_rows[col] = range(max_id + 1, max_id + 1 + len(new_rows))
            elif "name" in col.lower():
                new_rows[col] = [
                    f"Product_P{period}_{i}" for i in range(len(new_rows))
                ]
        return pd.concat([df, new_rows], ignore_index=True)

    # ── I/O helpers ───────────────────────────────────────────────────

    @staticmethod
    def _read_tables(db_path: Path) -> Dict[str, pd.DataFrame]:
        tables: Dict[str, pd.DataFrame] = {}
        con = sqlite3.connect(str(db_path))
        try:
            cursor = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
            for (table_name,) in cursor.fetchall():
                tables[table_name] = pd.read_sql_query(
                    f'SELECT * FROM "{table_name}"', con
                )
        finally:
            con.close()
        return tables

    @staticmethod
    def _write_tables(
        tables: Dict[str, pd.DataFrame], out_path: Path
    ) -> Dict[str, int]:
        row_counts: Dict[str, int] = {}
        con = sqlite3.connect(str(out_path))
        try:
            for table_name, df in tables.items():
                df.to_sql(table_name, con, if_exists="replace", index=False)
                row_counts[table_name] = len(df)
        finally:
            con.close()
        return row_counts
