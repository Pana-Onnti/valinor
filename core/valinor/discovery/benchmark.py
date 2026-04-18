"""
Discovery Benchmark — Measures precision/recall/F1 of FK inference.

Runs the FKDiscovery engine against golden datasets and compares
predicted FK relations against ground truth.

Usage:
    from core.valinor.discovery.golden_dataset import load_golden_dataset, build_golden_sqlite
    from core.valinor.discovery.benchmark import DiscoveryBenchmark

    golden = load_golden_dataset("gloria_full")
    conn = build_golden_sqlite("gloria_full")
    bench = DiscoveryBenchmark(golden, conn)
    result = bench.run()
    print(result)

Refs: VAL-129
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .fk_discovery import FKCandidate, FKDiscovery
from .golden_dataset import GoldenDataset, GoldenRelation, TableClassification


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class BenchmarkResult:
    """Results from running the discovery benchmark."""
    variant: str
    # FK accuracy
    fk_precision: float = 0.0       # TP / (TP + FP)
    fk_recall: float = 0.0          # TP / (TP + FN)
    fk_f1: float = 0.0              # harmonic mean
    true_positives: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)
    total_predicted: int = 0
    total_golden: int = 0
    # Entity classification accuracy (ensemble only)
    entity_accuracy: float = 0.0
    entity_correct: list[str] = field(default_factory=list)
    entity_incorrect: list[dict] = field(default_factory=list)
    # Consensus distribution (ensemble only)
    consensus_rate_3plus: float = 0.0
    consensus_counts: dict = field(default_factory=dict)  # {1: N, 2: N, 3: N, 4: N}
    # Cost tracking
    mode: str = "fk_only"           # "fk_only" or "ensemble"
    llm_calls: int = 0
    llm_cost_usd: float = 0.0
    elapsed_seconds: float = 0.0

    def summary(self) -> str:
        """Human-readable summary."""
        base = (
            f"Benchmark [{self.variant}/{self.mode}]: "
            f"P={self.fk_precision:.2f} R={self.fk_recall:.2f} F1={self.fk_f1:.2f} "
            f"(TP={len(self.true_positives)} FP={len(self.false_positives)} "
            f"FN={len(self.false_negatives)})"
        )
        if self.mode == "ensemble":
            base += (
                f" | entity_acc={self.entity_accuracy:.2f}"
                f" | consensus>=3 rate={self.consensus_rate_3plus:.2f}"
                f" | LLM calls={self.llm_calls} (${self.llm_cost_usd:.4f})"
            )
        base += f" in {self.elapsed_seconds:.1f}s"
        return base

    def to_dict(self) -> dict:
        """Serialize for baseline.json storage."""
        return {
            "variant": self.variant,
            "mode": self.mode,
            "fk_precision": round(self.fk_precision, 4),
            "fk_recall": round(self.fk_recall, 4),
            "fk_f1": round(self.fk_f1, 4),
            "entity_accuracy": round(self.entity_accuracy, 4),
            "consensus_rate_3plus": round(self.consensus_rate_3plus, 4),
            "consensus_counts": self.consensus_counts,
            "total_predicted": self.total_predicted,
            "total_golden": self.total_golden,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "entity_correct": self.entity_correct,
            "entity_incorrect": self.entity_incorrect,
            "llm_calls": self.llm_calls,
            "llm_cost_usd": round(self.llm_cost_usd, 6),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }


# ═══════════════════════════════════════════════════════════════════════════
# RELATION KEY NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════


def _relation_key(src_table: str, src_col: str, tgt_table: str, tgt_col: str) -> str:
    """Canonical string for a FK relation (case-insensitive)."""
    return (
        f"{src_table.lower()}.{src_col.lower()}"
        f" -> "
        f"{tgt_table.lower()}.{tgt_col.lower()}"
    )


def _golden_keys(relations: list[GoldenRelation]) -> set[str]:
    """Convert golden relations to canonical key set."""
    return {
        _relation_key(r.source_table, r.source_column, r.target_table, r.target_column)
        for r in relations
    }


def _predicted_keys(candidates: list[FKCandidate]) -> set[str]:
    """Convert FK candidates to canonical key set."""
    return {
        _relation_key(c.source_table, c.source_column, c.target_table, c.target_column)
        for c in candidates
    }


# ═══════════════════════════════════════════════════════════════════════════
# METRICS
# ═══════════════════════════════════════════════════════════════════════════


def compute_precision_recall_f1(
    predicted: set[str], golden: set[str],
) -> tuple[float, float, float]:
    """Compute precision, recall, F1 from two sets of relation keys.

    Returns:
        (precision, recall, f1)
    """
    tp = predicted & golden
    fp = predicted - golden
    fn = golden - predicted

    precision = len(tp) / len(predicted) if predicted else 0.0
    recall = len(tp) / len(golden) if golden else 0.0

    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0

    return precision, recall, f1


# ═══════════════════════════════════════════════════════════════════════════
# SQLite-compatible FK Discovery
# ═══════════════════════════════════════════════════════════════════════════


class SQLiteFKDiscovery:
    """
    FK Discovery adapted for SQLite (the main FKDiscovery uses PostgreSQL SQL).

    Same algorithm as FKDiscovery but with SQLite-compatible queries:
    1. Discover PK candidates (unique, non-null columns)
    2. Check inclusion dependencies between column pairs
    3. Score by inclusion ratio + name similarity + cardinality
    """

    def __init__(
        self,
        min_inclusion_ratio: float = 0.9,
        min_name_similarity: float = 0.3,
        min_score: float = 0.4,
    ):
        self.min_inclusion_ratio = min_inclusion_ratio
        self.min_name_similarity = min_name_similarity
        self.min_score = min_score
        self._scorer = FKDiscovery()  # reuse scoring logic

    def discover_fks(
        self, conn: sqlite3.Connection, tables: list[str],
    ) -> list[FKCandidate]:
        """Discover FK relationships using SQLite queries."""
        # Step 1: get column info and PK candidates per table
        pk_columns: dict[str, set[str]] = {}
        table_columns: dict[str, list[dict]] = {}

        for table in tables:
            cols = self._get_column_stats(conn, table)
            table_columns[table] = cols
            pks = set()
            for c in cols:
                if c["is_unique"] and c["is_non_null"]:
                    pks.add(c["column_name"])
            pk_columns[table] = pks

        # Step 2: check inclusion dependencies
        candidates: list[FKCandidate] = []

        # Pre-index target stats
        tgt_stats: dict[tuple[str, str], dict] = {}
        for tbl, cols in table_columns.items():
            for c in cols:
                tgt_stats[(tbl, c["column_name"])] = c

        for src_table in tables:
            for src_col in table_columns.get(src_table, []):
                src_name = src_col["column_name"]

                # Skip PK columns as source (they reference, not are referenced)
                if src_name in pk_columns.get(src_table, set()):
                    # Exception: allow if this PK also appears as FK to another table
                    # (e.g., Stock.CodArt is PK but also FK to Articulos.CodArt)
                    pass

                if src_col["distinct_count"] < 2:
                    continue

                for tgt_table in tables:
                    if tgt_table == src_table:
                        continue
                    for tgt_pk_name in pk_columns.get(tgt_table, set()):
                        name_sim = FKDiscovery._name_similarity(src_name, tgt_pk_name)
                        if name_sim < self.min_name_similarity:
                            continue

                        # Check inclusion
                        inclusion, orphan_count = self._check_inclusion(
                            conn, src_table, src_name, tgt_table, tgt_pk_name,
                        )

                        if inclusion < self.min_inclusion_ratio:
                            continue

                        tgt_col_stats = tgt_stats.get((tgt_table, tgt_pk_name))
                        card_ratio = 0.0
                        if tgt_col_stats and tgt_col_stats["distinct_count"] > 0:
                            card_ratio = (
                                src_col["distinct_count"] / tgt_col_stats["distinct_count"]
                            )

                        candidate = FKCandidate(
                            source_table=src_table,
                            source_column=src_name,
                            target_table=tgt_table,
                            target_column=tgt_pk_name,
                            inclusion_ratio=inclusion,
                            orphan_count=orphan_count,
                            name_similarity=name_sim,
                            cardinality_ratio=min(card_ratio, 1.0),
                        )
                        candidate.score = self._scorer.score_candidate(candidate)

                        if candidate.score >= self.min_score:
                            candidates.append(candidate)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def _get_column_stats(self, conn: sqlite3.Connection, table: str) -> list[dict]:
        """Get column stats using SQLite pragma + queries."""
        cur = conn.cursor()

        # Get column info
        cur.execute(f"PRAGMA table_info({table})")
        columns_info = cur.fetchall()
        # columns_info: (cid, name, type, notnull, dflt_value, pk)

        # Get row count
        cur.execute(f"SELECT COUNT(*) FROM [{table}]")
        row_count = cur.fetchone()[0]

        results = []
        for cid, name, col_type, notnull, dflt, pk in columns_info:
            cur.execute(f"SELECT COUNT(DISTINCT [{name}]) FROM [{table}] WHERE [{name}] IS NOT NULL")
            distinct = cur.fetchone()[0]

            cur.execute(f"SELECT COUNT(*) FROM [{table}] WHERE [{name}] IS NOT NULL")
            non_null_count = cur.fetchone()[0]

            is_unique = distinct == row_count and row_count > 0
            is_non_null = non_null_count == row_count and row_count > 0

            # Also check if it's a PK
            if pk > 0:
                is_unique = True
                is_non_null = True

            results.append({
                "column_name": name,
                "data_type": col_type or "TEXT",
                "row_count": row_count,
                "distinct_count": distinct,
                "is_unique": is_unique,
                "is_non_null": is_non_null,
            })

        return results

    def _check_inclusion(
        self,
        conn: sqlite3.Connection,
        src_table: str,
        src_col: str,
        tgt_table: str,
        tgt_col: str,
    ) -> tuple[float, int]:
        """Check inclusion dependency using SQLite queries."""
        cur = conn.cursor()

        # Total distinct source values
        cur.execute(
            f"SELECT COUNT(DISTINCT [{src_col}]) FROM [{src_table}] WHERE [{src_col}] IS NOT NULL"
        )
        total_distinct = cur.fetchone()[0]

        if total_distinct == 0:
            return 0.0, 0

        # Orphans: source values not in target
        cur.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT DISTINCT [{src_col}] FROM [{src_table}] WHERE [{src_col}] IS NOT NULL
            ) s
            WHERE s.[{src_col}] NOT IN (
                SELECT DISTINCT [{tgt_col}] FROM [{tgt_table}] WHERE [{tgt_col}] IS NOT NULL
            )
        """)
        orphan_count = cur.fetchone()[0]

        inclusion_ratio = (total_distinct - orphan_count) / total_distinct
        return round(inclusion_ratio, 4), orphan_count


# ═══════════════════════════════════════════════════════════════════════════
# BENCHMARK
# ═══════════════════════════════════════════════════════════════════════════


class DiscoveryBenchmark:
    """Run FK discovery against a golden dataset and measure accuracy."""

    def __init__(
        self,
        golden: GoldenDataset,
        conn: sqlite3.Connection,
        min_inclusion_ratio: float = 0.9,
        min_name_similarity: float = 0.3,
        min_score: float = 0.4,
    ):
        self.golden = golden
        self.conn = conn
        self.discovery = SQLiteFKDiscovery(
            min_inclusion_ratio=min_inclusion_ratio,
            min_name_similarity=min_name_similarity,
            min_score=min_score,
        )

    def run(self) -> BenchmarkResult:
        """Run discovery and compute metrics against golden truth."""
        t0 = time.monotonic()

        # Get table names from golden dataset
        table_names = [t.name for t in self.golden.tables]

        # Run FK discovery
        predicted_fks = self.discovery.discover_fks(self.conn, table_names)

        # Compute metrics
        golden_set = _golden_keys(self.golden.relations)
        predicted_set = _predicted_keys(predicted_fks)

        precision, recall, f1 = compute_precision_recall_f1(predicted_set, golden_set)

        tp = sorted(predicted_set & golden_set)
        fp = sorted(predicted_set - golden_set)
        fn = sorted(golden_set - predicted_set)

        elapsed = time.monotonic() - t0

        return BenchmarkResult(
            variant=self.golden.name,
            mode="fk_only",
            fk_precision=precision,
            fk_recall=recall,
            fk_f1=f1,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            total_predicted=len(predicted_set),
            total_golden=len(golden_set),
            elapsed_seconds=elapsed,
        )


# ═══════════════════════════════════════════════════════════════════════════
# SchemaProfile / TableProfile builders from SQLite
# ═══════════════════════════════════════════════════════════════════════════


def _classify_sqlite_type(col_type: str) -> str:
    """Map SQLite-reported type to ColumnTypeCategory value."""
    t = (col_type or "").lower()
    if any(k in t for k in ("date", "time")):
        return "datetime"
    if any(k in t for k in ("int",)):
        return "numeric"
    if any(k in t for k in ("real", "float", "double", "numeric", "decimal")):
        # "precio", "total", "subtotal" columns are real -> treat as monetary candidate
        return "numeric"
    if any(k in t for k in ("char", "text", "clob")):
        return "text"
    if any(k in t for k in ("blob", "binary")):
        return "binary"
    if "bool" in t:
        return "boolean"
    return "unknown"


def build_schema_profile_from_sqlite(
    conn: sqlite3.Connection, tables: list[str],
):
    """Build a SchemaProfile (from schema_extractor) for the ensemble.

    Reads table/column info via PRAGMA and FK info via PRAGMA foreign_key_list.
    Populates distinct_count and null_count so StructuralAgent's PK-candidate
    matching works.
    """
    from .schema_extractor import (
        ColumnInfo,
        ColumnTypeCategory,
        FKRelation,
        PKConstraint,
        SchemaProfile,
        TableInfo,
    )

    cur = conn.cursor()
    table_infos: list[TableInfo] = []
    total_rows = 0

    for tname in tables:
        # Columns
        cur.execute(f"PRAGMA table_info([{tname}])")
        col_rows = cur.fetchall()  # (cid, name, type, notnull, dflt, pk)

        # Row count
        cur.execute(f"SELECT COUNT(*) FROM [{tname}]")
        row_count = cur.fetchone()[0]

        columns: list[ColumnInfo] = []
        pk_cols: list[str] = []
        for cid, cname, ctype, notnull, _dflt, pk in col_rows:
            cur.execute(
                f"SELECT COUNT(DISTINCT [{cname}]), "
                f"       SUM(CASE WHEN [{cname}] IS NULL THEN 1 ELSE 0 END) "
                f"FROM [{tname}]"
            )
            distinct, null_cnt = cur.fetchone()
            null_cnt = null_cnt or 0
            null_density = null_cnt / row_count if row_count > 0 else 0.0
            category_val = _classify_sqlite_type(ctype)
            columns.append(ColumnInfo(
                name=cname,
                sql_type=ctype or "",
                nullable=not notnull,
                type_category=ColumnTypeCategory(category_val),
                null_count=null_cnt,
                null_density=round(null_density, 4),
                distinct_count=distinct or 0,
                is_pk_candidate=bool(pk),
            ))
            if pk:
                pk_cols.append(cname)

        # FKs (may be empty if variant is no_fks)
        fks: list[FKRelation] = []
        cur.execute(f"PRAGMA foreign_key_list([{tname}])")
        fk_rows = cur.fetchall()  # (id, seq, table, from, to, on_update, on_delete, match)
        # Group by id (composite FKs share id)
        by_id: dict[int, list[tuple[str, str, str]]] = {}
        for row in fk_rows:
            fk_id = row[0]
            ref_table = row[2]
            src_col = row[3]
            tgt_col = row[4]
            by_id.setdefault(fk_id, []).append((ref_table, src_col, tgt_col))
        for fk_id, parts in by_id.items():
            ref_table = parts[0][0]
            src_cols = [p[1] for p in parts]
            tgt_cols = [p[2] for p in parts]
            fks.append(FKRelation(
                name=f"fk_{tname}_{fk_id}",
                source_table=tname,
                source_columns=src_cols,
                target_table=ref_table,
                target_columns=tgt_cols,
            ))

        table_infos.append(TableInfo(
            name=tname,
            schema_name="",
            row_count=row_count,
            columns=columns,
            pk=PKConstraint(columns=pk_cols),
            fks=fks,
        ))
        total_rows += row_count

    return SchemaProfile(
        dialect="sqlite",
        schema_name="",
        tables=table_infos,
        table_count=len(table_infos),
        total_row_count=total_rows,
    )


def build_table_profiles_from_sqlite(
    conn: sqlite3.Connection, tables: list[str],
):
    """Build TableProfile dict for OntologyBuilder.

    Heuristics:
      - monetary_columns: REAL/NUMERIC columns with names containing
        precio/total/subtotal/costo/cantidad/importe.
      - temporal_columns: columns with "date", "time", or name containing fecha.
      - identifier_columns: PK columns + single-column candidates (distinct == row_count).
    """
    from .profiler import TableProfile, ColumnProfile, SemanticType

    cur = conn.cursor()
    profiles: dict = {}

    monetary_kw = ("precio", "total", "subtotal", "costo", "importe", "monto")
    temporal_kw = ("fecha", "date", "timestamp", "time")

    for tname in tables:
        cur.execute(f"SELECT COUNT(*) FROM [{tname}]")
        row_count = cur.fetchone()[0]

        cur.execute(f"PRAGMA table_info([{tname}])")
        col_rows = cur.fetchall()

        monetary: list[str] = []
        temporal: list[str] = []
        identifier: list[str] = []
        columns: dict[str, ColumnProfile] = {}

        for cid, cname, ctype, notnull, _dflt, pk in col_rows:
            cname_lower = cname.lower()
            ctype_lower = (ctype or "").lower()

            cur.execute(f"SELECT COUNT(DISTINCT [{cname}]) FROM [{tname}]")
            distinct = cur.fetchone()[0] or 0

            sem = SemanticType.UNKNOWN
            is_monetary = any(kw in cname_lower for kw in monetary_kw) and any(
                k in ctype_lower for k in ("real", "numeric", "decimal", "float")
            )
            is_temporal = any(kw in cname_lower for kw in temporal_kw) or any(
                k in ctype_lower for k in ("date", "time")
            )

            if is_monetary:
                monetary.append(cname)
                sem = SemanticType.MONETARY
            elif is_temporal:
                temporal.append(cname)
                sem = SemanticType.TEMPORAL
            elif pk or (distinct == row_count and row_count > 0):
                identifier.append(cname)
                sem = SemanticType.IDENTIFIER
            elif "int" in ctype_lower:
                sem = SemanticType.NUMERIC
            elif any(k in ctype_lower for k in ("char", "text")):
                sem = SemanticType.TEXT

            columns[cname] = ColumnProfile(
                name=cname,
                table=tname,
                db_type=ctype or "",
                row_count=row_count,
                distinct_count=distinct,
                null_count=0,
                null_rate=0.0,
                semantic_type=sem,
                is_unique=(distinct == row_count and row_count > 0),
                is_non_null=bool(notnull),
            )

        profiles[tname] = TableProfile(
            table_name=tname,
            schema="",
            row_count=row_count,
            column_count=len(col_rows),
            columns=columns,
            monetary_columns=monetary,
            temporal_columns=temporal,
            identifier_columns=identifier,
        )

    return profiles


# ═══════════════════════════════════════════════════════════════════════════
# ENSEMBLE BENCHMARK (4 agents + consensus + entity classification)
# ═══════════════════════════════════════════════════════════════════════════


# Map golden TableClassification -> ontology_builder.EntityType value
_GOLDEN_TO_ENTITY: dict[TableClassification, str] = {
    TableClassification.MASTER: "master",
    TableClassification.TRANSACTIONAL: "transactional",
    TableClassification.CONFIG: "config",
    TableClassification.BRIDGE: "bridge",
}


class EnsembleBenchmark:
    """
    Runs the 4-agent ensemble (VAL-127) against a golden dataset and measures:
      - FK precision/recall/F1 (confidence-threshold filtered)
      - consensus_rate_3plus (share of relations with consensus >= 3)
      - entity_accuracy (ontology classification vs golden ground truth)
      - LLM call count + estimated cost

    Uses MockLLMClient by default so the benchmark is deterministic and free.
    """

    # Haiku 3.5 approx cost (input+output averaged) — used if no real client
    _HAIKU_COST_PER_CALL_USD = 0.008

    def __init__(
        self,
        golden: GoldenDataset,
        conn: sqlite3.Connection,
        min_confidence: float = 0.5,
        llm_client: Optional[object] = None,
    ):
        self.golden = golden
        self.conn = conn
        self.min_confidence = min_confidence
        self.llm_client = llm_client  # None -> MockLLMClient inside run_multi_agent_inference

    def run(self) -> BenchmarkResult:
        return asyncio.run(self._run_async())

    async def _run_async(self) -> BenchmarkResult:
        from .inference_agents import run_multi_agent_inference
        from .ontology_builder import OntologyBuilder

        t0 = time.monotonic()

        table_names = [t.name for t in self.golden.tables]

        # Build SchemaProfile for ensemble
        schema = build_schema_profile_from_sqlite(self.conn, table_names)

        # Run 4-agent ensemble
        evaluated = await run_multi_agent_inference(
            schema=schema,
            business_context={
                "company_name": "Golden PyME",
                "industry": self.golden.description,
                "country": "AR",
                "erp_type": "gestion_pyme_argentina",
            },
            hint_pack=None,
            samples=None,
            llm_client=self.llm_client,
        )

        # Filter by confidence threshold for FK comparison
        predicted_relations = [
            r for r in evaluated if r.confidence >= self.min_confidence
        ]
        predicted_set = {
            _relation_key(r.source_table, r.source_column, r.target_table, r.target_column)
            for r in predicted_relations
        }

        golden_set = _golden_keys(self.golden.relations)
        precision, recall, f1 = compute_precision_recall_f1(predicted_set, golden_set)

        tp = sorted(predicted_set & golden_set)
        fp = sorted(predicted_set - golden_set)
        fn = sorted(golden_set - predicted_set)

        # Consensus distribution
        consensus_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for r in evaluated:
            level = min(max(r.consensus, 1), 4)
            consensus_counts[level] = consensus_counts.get(level, 0) + 1
        total_evaluated = sum(consensus_counts.values())
        consensus_rate_3plus = (
            (consensus_counts.get(3, 0) + consensus_counts.get(4, 0)) / total_evaluated
            if total_evaluated > 0 else 0.0
        )

        # Entity classification accuracy
        table_profiles = build_table_profiles_from_sqlite(self.conn, table_names)
        # FKCandidate list for ontology builder FK graph (use predicted relations)
        fk_candidates = [
            FKCandidate(
                source_table=r.source_table,
                source_column=r.source_column,
                target_table=r.target_table,
                target_column=r.target_column,
                inclusion_ratio=1.0,
                orphan_count=0,
                name_similarity=1.0,
                cardinality_ratio=1.0,
                score=r.confidence,
            )
            for r in predicted_relations
        ]
        ontology = OntologyBuilder().build_ontology(table_profiles, fk_candidates)

        correct: list[str] = []
        incorrect: list[dict] = []
        for gt in self.golden.tables:
            expected = _GOLDEN_TO_ENTITY[gt.classification]
            predicted = ontology.entities.get(gt.name)
            predicted_type = predicted.entity_type.value if predicted else "missing"
            if predicted_type == expected:
                correct.append(gt.name)
            else:
                incorrect.append({
                    "table": gt.name,
                    "expected": expected,
                    "predicted": predicted_type,
                })
        total_tables = len(self.golden.tables)
        entity_accuracy = len(correct) / total_tables if total_tables > 0 else 0.0

        # LLM cost estimate — MockLLMClient = 0, real = 2 calls (semantic + process)
        llm_calls = 0 if self.llm_client is None else 2
        llm_cost = llm_calls * self._HAIKU_COST_PER_CALL_USD

        elapsed = time.monotonic() - t0

        return BenchmarkResult(
            variant=self.golden.name,
            mode="ensemble",
            fk_precision=precision,
            fk_recall=recall,
            fk_f1=f1,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            total_predicted=len(predicted_set),
            total_golden=len(golden_set),
            entity_accuracy=entity_accuracy,
            entity_correct=correct,
            entity_incorrect=incorrect,
            consensus_rate_3plus=round(consensus_rate_3plus, 4),
            consensus_counts=consensus_counts,
            llm_calls=llm_calls,
            llm_cost_usd=llm_cost,
            elapsed_seconds=elapsed,
        )


# ═══════════════════════════════════════════════════════════════════════════
# BASELINE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════


def save_baseline(results: list[BenchmarkResult], path: Path) -> None:
    """Persist benchmark results as the baseline for regression checks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "generated_at": int(time.time()),
        "results": [r.to_dict() for r in results],
    }
    path.write_text(json.dumps(payload, indent=2))


def load_baseline(path: Path) -> dict:
    """Load a previously saved baseline."""
    return json.loads(path.read_text())


def compare_to_baseline(
    current: BenchmarkResult,
    baseline: dict,
    recall_tolerance: float = 0.05,
) -> tuple[bool, str]:
    """Compare a current run against the baseline for its (variant, mode).

    Returns (ok, message). ok=False if FK recall dropped by more than
    `recall_tolerance` vs the baseline for the same (variant, mode).
    """
    match = next(
        (
            r for r in baseline.get("results", [])
            if r.get("variant") == current.variant and r.get("mode") == current.mode
        ),
        None,
    )
    if match is None:
        return True, f"no baseline for {current.variant}/{current.mode}"
    baseline_recall = match.get("fk_recall", 0.0)
    drop = baseline_recall - current.fk_recall
    if drop > recall_tolerance:
        return False, (
            f"FK recall regressed for {current.variant}/{current.mode}: "
            f"baseline={baseline_recall:.3f} current={current.fk_recall:.3f} "
            f"(drop={drop:.3f} > tolerance={recall_tolerance})"
        )
    return True, (
        f"{current.variant}/{current.mode}: recall {current.fk_recall:.3f} "
        f"(baseline {baseline_recall:.3f}, drop {drop:+.3f})"
    )


# ═══════════════════════════════════════════════════════════════════════════
# CLI ENTRYPOINT — run all variants and persist baseline
# ═══════════════════════════════════════════════════════════════════════════


def run_all_variants(mode: str = "both") -> list[BenchmarkResult]:
    """Run benchmark for all 3 golden variants.

    Args:
        mode: "fk_only", "ensemble", or "both".
    """
    from .golden_dataset import build_golden_sqlite, load_golden_dataset

    results: list[BenchmarkResult] = []
    variants = ["gloria_full", "gloria_no_fks", "gloria_obfuscated"]
    for variant in variants:
        golden = load_golden_dataset(variant)
        conn = build_golden_sqlite(variant)
        try:
            if mode in ("fk_only", "both"):
                results.append(DiscoveryBenchmark(golden, conn).run())
            if mode in ("ensemble", "both"):
                results.append(EnsembleBenchmark(golden, conn).run())
        finally:
            conn.close()
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run discovery benchmark suite")
    parser.add_argument(
        "--mode", choices=["fk_only", "ensemble", "both"], default="both",
    )
    parser.add_argument(
        "--save-baseline", type=Path, default=None,
        help="If given, write the results to this path as the new baseline",
    )
    args = parser.parse_args()

    results = run_all_variants(args.mode)
    for r in results:
        print(r.summary())

    if args.save_baseline:
        save_baseline(results, args.save_baseline)
        print(f"\nBaseline saved to {args.save_baseline}")
