"""
Playground Swarm — Agent 7: Perturbation Engine.

Takes existing datasets and applies controlled mutations (noise, nulls,
duplicates, FK corruption, currency swaps, column shuffles) to stress-test
the analysis pipeline.
"""

import random
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

MAX_SOURCES_PER_RUN = 3

CORRUPTION_LEVELS = [0.05, 0.10, 0.20, 0.50]

MUTATION_REGISTRY: List[str] = [
    "gaussian_noise",
    "null_injection",
    "row_duplication",
    "fk_corruption",
    "currency_swap",
    "column_shuffle",
]


class PerturbationEngineAgent(PlaygroundAgent):
    """Applies controlled mutations to existing datasets."""

    name = "perturbation_engine"
    tier = "bootstrapper"

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        datasets: List[DatasetRecord] = []
        errors: List[str] = []

        source_dirs = [ctx.datasets_dir / "real", ctx.datasets_dir / "synthetic"]
        source_dbs: List[Path] = []
        for d in source_dirs:
            if d.exists():
                source_dbs.extend(d.glob("*.db"))

        if not source_dbs:
            self.logger.info("No source datasets found — skipping perturbation.")
            return AgentResult(self.name, success=True, datasets=[], stats={"sources": 0})

        picked = random.sample(source_dbs, min(MAX_SOURCES_PER_RUN, len(source_dbs)))
        out_dir = ctx.datasets_dir / "bootstrapped"
        out_dir.mkdir(parents=True, exist_ok=True)

        for src_path in picked:
            source_name = src_path.stem
            try:
                # Choose a random subset of mutations (at least 1)
                k = random.randint(1, len(MUTATION_REGISTRY))
                chosen_mutations = random.sample(MUTATION_REGISTRY, k)

                tables = self._read_tables(src_path)
                if not tables:
                    continue

                for mutation in chosen_mutations:
                    tables = self._apply_mutation(mutation, tables)

                suffix = "_".join(sorted(chosen_mutations))
                out_path = out_dir / f"perturb_{source_name}_{suffix}.db"
                row_counts = self._write_tables(tables, out_path)

                tags = ["perturbed"] + [f"mutation:{m}" for m in chosen_mutations]
                record = DatasetRecord(
                    name=out_path.stem,
                    path=str(out_path),
                    source_agent=self.name,
                    tier=self.tier,
                    created_at=datetime.utcnow().isoformat(),
                    row_counts=row_counts,
                    tags=tags,
                    metadata={
                        "mutations_applied": chosen_mutations,
                        "source_path": str(src_path),
                    },
                )
                datasets.append(record)
                await ctx.generated_datasets.put(record)

                self.logger.info(
                    "Perturbed %s with [%s]", source_name, ", ".join(chosen_mutations)
                )
            except Exception as exc:
                msg = f"Error perturbing {src_path.name}: {exc}"
                self.logger.error(msg)
                errors.append(msg)

        return AgentResult(
            self.name,
            success=len(errors) == 0,
            datasets=datasets,
            errors=errors,
            stats={"sources": len(picked), "datasets_created": len(datasets)},
        )

    # ── mutation implementations ──────────────────────────────────────

    def _apply_mutation(
        self, mutation: str, tables: Dict[str, pd.DataFrame]
    ) -> Dict[str, pd.DataFrame]:
        dispatch = {
            "gaussian_noise": self._gaussian_noise,
            "null_injection": self._null_injection,
            "row_duplication": self._row_duplication,
            "fk_corruption": self._fk_corruption,
            "currency_swap": self._currency_swap,
            "column_shuffle": self._column_shuffle,
        }
        fn = dispatch.get(mutation)
        if fn is None:
            self.logger.warning("Unknown mutation: %s", mutation)
            return tables
        return fn(tables)

    @staticmethod
    def _gaussian_noise(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        level = random.choice(CORRUPTION_LEVELS)
        result: Dict[str, pd.DataFrame] = {}
        for name, df in tables.items():
            df = df.copy()
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            for col in numeric_cols:
                std = df[col].std()
                if pd.notna(std) and std > 0:
                    noise = np.random.normal(0, std * level, size=len(df))
                    df[col] = df[col] + noise
            result[name] = df
        return result

    @staticmethod
    def _null_injection(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        rate = random.uniform(0.05, 0.30)
        result: Dict[str, pd.DataFrame] = {}
        for name, df in tables.items():
            df = df.copy()
            mask = np.random.random(df.shape) < rate
            df = df.mask(mask)
            result[name] = df
        return result

    @staticmethod
    def _row_duplication(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        rate = random.uniform(0.05, 0.20)
        result: Dict[str, pd.DataFrame] = {}
        for name, df in tables.items():
            if df.empty:
                result[name] = df
                continue
            n_dup = max(1, int(len(df) * rate))
            dup_indices = np.random.choice(len(df), size=n_dup, replace=True)
            df = pd.concat([df, df.iloc[dup_indices]], ignore_index=True)
            result[name] = df
        return result

    @staticmethod
    def _fk_corruption(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        result: Dict[str, pd.DataFrame] = {}
        for name, df in tables.items():
            df = df.copy()
            id_cols = [c for c in df.columns if c.endswith("_id")]
            for col in id_cols:
                n_corrupt = max(1, int(len(df) * 0.10))
                indices = np.random.choice(len(df), size=n_corrupt, replace=False)
                df.loc[indices, col] = np.random.randint(900_000, 999_999, size=n_corrupt)
            result[name] = df
        return result

    @staticmethod
    def _currency_swap(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        rate = random.uniform(0.01, 100.0)
        result: Dict[str, pd.DataFrame] = {}
        monetary_hints = {"amount", "total", "price", "cost", "revenue", "balance", "debit", "credit"}
        for name, df in tables.items():
            df = df.copy()
            for col in df.columns:
                if any(hint in col.lower() for hint in monetary_hints):
                    if pd.api.types.is_numeric_dtype(df[col]):
                        df[col] = df[col] * rate
            result[name] = df
        return result

    @staticmethod
    def _column_shuffle(tables: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        result: Dict[str, pd.DataFrame] = {}
        for name, df in tables.items():
            df = df.copy()
            if len(df.columns) >= 2:
                col_a, col_b = random.sample(list(df.columns), 2)
                df[col_a], df[col_b] = df[col_b].copy(), df[col_a].copy()
            result[name] = df
        return result

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
