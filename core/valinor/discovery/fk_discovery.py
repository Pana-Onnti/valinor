"""
FK Discovery — Finds implicit foreign key relationships.
Phase 1: Statistical IND (Inclusion Dependency) detection.
No LLM. Compares column value sets across tables.

Algorithm:
1. For each table, identify potential PK columns (unique, non-null, high cardinality)
2. For each pair (table_A.col_X, table_B.col_Y):
   - If col_X values ⊆ col_Y values (inclusion dependency)
   - AND col_Y is a PK candidate
   - AND col_X has same/similar name as col_Y
   → Candidate FK relationship
3. Score candidates by: name similarity + inclusion ratio + cardinality match
4. Return ranked list of FK candidates

References:
  - LLM-FK (arXiv:2603.07278) — Phase 1 statistical approach
  - RIGOR (arXiv:2506.01232) — schema relationship validation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class PKCandidate:
    """A column that may be a primary key."""
    table: str
    column: str
    distinct_count: int = 0
    row_count: int = 0
    is_unique: bool = False
    is_non_null: bool = False
    confidence: float = 0.0


@dataclass
class FKCandidate:
    """A candidate foreign key relationship."""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    inclusion_ratio: float = 0.0   # % of source values found in target
    orphan_count: int = 0          # source values NOT in target
    name_similarity: float = 0.0   # 0-1 string similarity
    cardinality_ratio: float = 0.0 # source_distinct / target_distinct
    score: float = 0.0             # overall confidence score


# ═══════════════════════════════════════════════════════════════════════════
# FK DISCOVERY ENGINE
# ═══════════════════════════════════════════════════════════════════════════


class FKDiscovery:
    """
    Discovers foreign key relationships using inclusion dependency detection.
    Zero hardcoded knowledge — all from statistical column comparison.
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

    def discover_pks(
        self,
        engine,
        tables: list[str],
        schema: str = "public",
    ) -> dict[str, list[PKCandidate]]:
        """Discover potential primary key columns for each table."""
        result: dict[str, list[PKCandidate]] = {}

        for table in tables:
            candidates = []
            try:
                cols = self._get_column_stats(engine, table, schema)
                for col in cols:
                    if col["is_unique"] and col["is_non_null"]:
                        confidence = 1.0
                    elif col["is_unique"]:
                        confidence = 0.8
                    elif col["row_count"] > 0:
                        uniqueness = col["distinct_count"] / col["row_count"]
                        if uniqueness >= 0.95 and col["is_non_null"]:
                            confidence = 0.7
                        else:
                            continue
                    else:
                        continue

                    candidates.append(PKCandidate(
                        table=table,
                        column=col["column_name"],
                        distinct_count=col["distinct_count"],
                        row_count=col["row_count"],
                        is_unique=col["is_unique"],
                        is_non_null=col["is_non_null"],
                        confidence=confidence,
                    ))
            except Exception as exc:
                logger.warning("fk_discovery.pk_error", table=table, error=str(exc))

            result[table] = candidates

        return result

    def discover_fks(
        self,
        engine,
        tables: list[str],
        schema: str = "public",
    ) -> list[FKCandidate]:
        """
        Discover foreign key relationships between tables.
        Compares all column pairs across tables for inclusion dependencies.
        """
        # Step 1: Discover PKs
        pk_map = self.discover_pks(engine, tables, schema)

        # Build flat list of PK columns for quick lookup
        pk_columns: dict[str, set[str]] = {}
        for table, pks in pk_map.items():
            pk_columns[table] = {pk.column for pk in pks}

        # Step 2: Get all columns per table
        table_columns: dict[str, list[dict]] = {}
        for table in tables:
            try:
                table_columns[table] = self._get_column_stats(engine, table, schema)
            except Exception as exc:
                logger.warning("fk_discovery.cols_error", table=table, error=str(exc))
                table_columns[table] = []

        # Step 3: Collect all candidate pairs (cheap name-similarity filter first),
        #         then batch-check inclusion dependencies
        candidates: list[FKCandidate] = []

        # Pre-index target column stats for cardinality ratio lookups
        tgt_stats_idx: dict[tuple[str, str], dict] = {}
        for tbl, cols in table_columns.items():
            for c in cols:
                tgt_stats_idx[(tbl, c["column_name"])] = c

        # Collect pairs that pass the cheap name-similarity filter
        pairs_to_check: list[tuple[str, str, str, str, float, dict]] = []
        for src_table in tables:
            for src_col in table_columns.get(src_table, []):
                src_name = src_col["column_name"]

                if src_name in pk_columns.get(src_table, set()):
                    continue
                if src_col["distinct_count"] < 2:
                    continue

                for tgt_table in tables:
                    if tgt_table == src_table:
                        continue
                    for tgt_pk_name in pk_columns.get(tgt_table, set()):
                        name_sim = self._name_similarity(src_name, tgt_pk_name)
                        if name_sim < self.min_name_similarity:
                            continue
                        pairs_to_check.append(
                            (src_table, src_name, tgt_table, tgt_pk_name, name_sim, src_col)
                        )

        # Batch-check all inclusion dependencies in a single connection
        if pairs_to_check:
            with engine.connect() as conn:
                for src_table, src_name, tgt_table, tgt_pk_name, name_sim, src_col in pairs_to_check:
                    try:
                        inclusion, orphan_count = self._check_inclusion_conn(
                            conn, src_table, src_name,
                            tgt_table, tgt_pk_name, schema,
                        )
                    except Exception as exc:
                        logger.debug(
                            "fk_discovery.inclusion_error",
                            src=f"{src_table}.{src_name}",
                            tgt=f"{tgt_table}.{tgt_pk_name}",
                            error=str(exc),
                        )
                        continue

                    if inclusion < self.min_inclusion_ratio:
                        continue

                    tgt_col_stats = tgt_stats_idx.get((tgt_table, tgt_pk_name))
                    card_ratio = 0.0
                    if tgt_col_stats and tgt_col_stats["distinct_count"] > 0:
                        card_ratio = (
                            src_col["distinct_count"]
                            / tgt_col_stats["distinct_count"]
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
                    candidate.score = self.score_candidate(candidate)

                    if candidate.score >= self.min_score:
                        candidates.append(candidate)

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def score_candidate(self, candidate: FKCandidate) -> float:
        """
        Score a FK candidate on [0, 1].
        Weighted combination of inclusion ratio, name similarity, cardinality.
        """
        w_inclusion = 0.5
        w_name = 0.3
        w_cardinality = 0.2

        score = (
            w_inclusion * candidate.inclusion_ratio
            + w_name * candidate.name_similarity
            + w_cardinality * candidate.cardinality_ratio
        )
        return round(min(score, 1.0), 4)

    # ─── Internal helpers ─────────────────────────────────────────────

    def _get_column_stats(
        self, engine, table: str, schema: str,
    ) -> list[dict[str, Any]]:
        """Get basic stats for all columns in a table (single query)."""
        meta_sql = """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
        """
        with engine.connect() as conn:
            meta_rows = conn.execute(_text(meta_sql), {"schema": schema, "table": table}).fetchall()

        if not meta_rows:
            return []

        # Build a single query that computes stats for ALL columns at once
        fqn = f'"{schema}"."{table}"'
        agg_parts = []
        for col_name, _ in meta_rows:
            cq = f'"{col_name}"'
            agg_parts.append(f"COUNT(DISTINCT {cq})")
            agg_parts.append(f"COUNT({cq})")

        stats_sql = f"SELECT COUNT(*), {', '.join(agg_parts)} FROM {fqn}"

        with engine.connect() as conn:
            row = conn.execute(_text(stats_sql)).fetchone()

        if not row:
            return []

        total = row[0]
        results = []
        for i, (col_name, data_type) in enumerate(meta_rows):
            distinct = row[1 + i * 2]
            non_null = row[2 + i * 2]
            results.append({
                "column_name": col_name,
                "data_type": data_type,
                "row_count": total,
                "distinct_count": distinct,
                "is_unique": distinct == total and total > 0,
                "is_non_null": non_null == total and total > 0,
            })
        return results

    def _check_inclusion_conn(
        self,
        conn,
        src_table: str,
        src_col: str,
        tgt_table: str,
        tgt_col: str,
        schema: str,
    ) -> tuple[float, int]:
        """
        Check inclusion dependency using an existing connection.
        Returns (inclusion_ratio, orphan_count).
        Single query computes both orphan count and total distinct.
        """
        src_fqn = f'"{schema}"."{src_table}"'
        tgt_fqn = f'"{schema}"."{tgt_table}"'
        src_cq = f'"{src_col}"'
        tgt_cq = f'"{tgt_col}"'

        # Single query: total distinct + orphan count via LEFT JOIN
        sql = f"""
            SELECT
                COUNT(*) AS total_distinct,
                COUNT(*) FILTER (WHERE t.{tgt_cq} IS NULL) AS orphan_count
            FROM (
                SELECT DISTINCT {src_cq} FROM {src_fqn} WHERE {src_cq} IS NOT NULL
            ) s
            LEFT JOIN (
                SELECT DISTINCT {tgt_cq} FROM {tgt_fqn} WHERE {tgt_cq} IS NOT NULL
            ) t ON s.{src_cq}::text = t.{tgt_cq}::text
        """

        row = conn.execute(_text(sql)).fetchone()
        total_distinct = row[0]
        orphan_count = row[1]

        if total_distinct == 0:
            return 0.0, 0

        inclusion_ratio = (total_distinct - orphan_count) / total_distinct
        return round(inclusion_ratio, 4), orphan_count

    def _check_inclusion(
        self,
        engine,
        src_table: str,
        src_col: str,
        tgt_table: str,
        tgt_col: str,
        schema: str,
    ) -> tuple[float, int]:
        """Check inclusion dependency (opens its own connection)."""
        with engine.connect() as conn:
            return self._check_inclusion_conn(
                conn, src_table, src_col, tgt_table, tgt_col, schema,
            )

    @staticmethod
    def _name_similarity(name_a: str, name_b: str) -> float:
        """
        Compute name similarity between two column names.
        Uses SequenceMatcher + special handling for _id suffix patterns.
        """
        a_lower = name_a.lower()
        b_lower = name_b.lower()

        # Exact match
        if a_lower == b_lower:
            return 1.0

        # If source ends with target name (e.g., "customer_id" matches "id")
        # BUT we want higher score when names are more specific
        base_sim = SequenceMatcher(None, a_lower, b_lower).ratio()

        # Bonus: if both share a common prefix before _id
        # e.g., c_bpartner_id and c_bpartner_id → perfect match
        # e.g., partner_id and c_bpartner_id → partial match
        a_stem = a_lower.replace("_id", "").replace("id", "")
        b_stem = b_lower.replace("_id", "").replace("id", "")
        if a_stem and b_stem:
            stem_sim = SequenceMatcher(None, a_stem, b_stem).ratio()
            base_sim = max(base_sim, stem_sim)

        return round(base_sim, 4)


# ═══════════════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════════════

def _text(sql: str):
    """Wrap SQL string for SQLAlchemy execution."""
    try:
        from sqlalchemy import text
        return text(sql)
    except ImportError:
        return sql
