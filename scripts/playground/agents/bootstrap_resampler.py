"""
Playground Swarm — Agent 6: Bootstrap Resampler.

Scans existing datasets and creates bootstrap-resampled variations,
preserving marginal distributions while shuffling rows.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

N_VARIATIONS = 3


class BootstrapResamplerAgent(PlaygroundAgent):
    """Creates N bootstrap-resampled copies of each source dataset."""

    name = "bootstrap_resampler"
    tier = "bootstrapper"

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        datasets: List[DatasetRecord] = []
        errors: List[str] = []

        source_dirs = [
            ctx.datasets_dir / "real",
            ctx.datasets_dir / "synthetic",
        ]
        source_dbs: List[Path] = []
        for d in source_dirs:
            if d.exists():
                source_dbs.extend(d.glob("*.db"))

        if not source_dbs:
            self.logger.info("No source datasets found — skipping bootstrap.")
            return AgentResult(self.name, success=True, datasets=[], stats={"sources": 0})

        out_dir = ctx.datasets_dir / "bootstrapped"
        out_dir.mkdir(parents=True, exist_ok=True)

        for src_path in source_dbs:
            source_name = src_path.stem
            try:
                tables = self._read_tables(src_path)
                if not tables:
                    self.logger.warning("No tables in %s — skipping.", src_path.name)
                    continue

                for i in range(1, N_VARIATIONS + 1):
                    out_path = out_dir / f"boot_{source_name}_{i}.db"
                    row_counts = self._write_resampled(tables, out_path)

                    record = DatasetRecord(
                        name=out_path.stem,
                        path=str(out_path),
                        source_agent=self.name,
                        tier=self.tier,
                        created_at=datetime.utcnow().isoformat(),
                        row_counts=row_counts,
                        tags=["bootstrapped", "resampled", f"source:{source_name}"],
                        metadata={"variation": i, "source_path": str(src_path)},
                    )
                    datasets.append(record)
                    await ctx.generated_datasets.put(record)

                self.logger.info(
                    "Bootstrapped %d variations from %s", N_VARIATIONS, source_name
                )
            except Exception as exc:
                msg = f"Error resampling {src_path.name}: {exc}"
                self.logger.error(msg)
                errors.append(msg)

        return AgentResult(
            self.name,
            success=len(errors) == 0,
            datasets=datasets,
            errors=errors,
            stats={"sources": len(source_dbs), "variations": len(datasets)},
        )

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _read_tables(db_path: Path) -> Dict[str, pd.DataFrame]:
        """Read all user tables from a SQLite database."""
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
    def _write_resampled(
        tables: Dict[str, pd.DataFrame], out_path: Path
    ) -> Dict[str, int]:
        """Bootstrap-resample every table and write to a new SQLite DB."""
        row_counts: Dict[str, int] = {}
        con = sqlite3.connect(str(out_path))
        try:
            for table_name, df in tables.items():
                if df.empty:
                    resampled = df.copy()
                else:
                    indices = np.random.choice(len(df), size=len(df), replace=True)
                    resampled = df.iloc[indices].reset_index(drop=True)
                resampled.to_sql(table_name, con, if_exists="replace", index=False)
                row_counts[table_name] = len(resampled)
        finally:
            con.close()
        return row_counts
