"""
Statistical Profiler — Phase 1 of auto-discovery.
Pure deterministic analysis. No LLM. No hardcoded ERP knowledge.
Discovers column semantics from data patterns:
  - Cardinality (distinct values count)
  - Null rate
  - Value distribution (top values)
  - Statistical type inference (monetary, temporal, categorical, identifier, text)
  - Potential discriminator detection (low cardinality + in WHERE patterns)

References:
  - ydata-profiling — statistical profiling patterns
  - GAIT (PAKDD 2024) — data-driven semantic type detection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


class SemanticType(str, Enum):
    """Inferred semantic type of a column — discovered from data, not hardcoded."""
    MONETARY = "monetary"
    TEMPORAL = "temporal"
    CATEGORICAL = "categorical"
    IDENTIFIER = "identifier"
    TEXT = "text"
    BOOLEAN = "boolean"
    NUMERIC = "numeric"
    UNKNOWN = "unknown"


@dataclass
class ColumnProfile:
    """Statistical profile of a single column."""
    name: str
    table: str
    db_type: str = ""
    row_count: int = 0
    distinct_count: int = 0
    null_count: int = 0
    null_rate: float = 0.0
    min_value: Any = None
    max_value: Any = None
    avg_value: float | None = None
    top_values: list[dict[str, Any]] = field(default_factory=list)
    semantic_type: SemanticType = SemanticType.UNKNOWN
    is_unique: bool = False
    is_non_null: bool = False


@dataclass
class DiscriminatorCandidate:
    """A column that may serve as a discriminator / filter column."""
    table: str
    column: str
    distinct_count: int
    top_values: list[dict[str, Any]]
    recommended_value: str | None = None
    recommended_value_pct: float = 0.0


@dataclass
class TableProfile:
    """Complete statistical profile of a table."""
    table_name: str
    schema: str = "public"
    row_count: int = 0
    column_count: int = 0
    columns: dict[str, ColumnProfile] = field(default_factory=dict)
    discriminators: list[DiscriminatorCandidate] = field(default_factory=list)
    monetary_columns: list[str] = field(default_factory=list)
    temporal_columns: list[str] = field(default_factory=list)
    identifier_columns: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# TYPE MAPPING — PostgreSQL types → semantic categories
# ═══════════════════════════════════════════════════════════════════════════

# These are standard SQL type families, NOT ERP-specific
_TEMPORAL_TYPES = frozenset({
    "date", "timestamp", "timestamptz", "timestamp without time zone",
    "timestamp with time zone", "time", "time without time zone",
    "time with time zone", "interval",
})

_NUMERIC_TYPES = frozenset({
    "integer", "int", "int4", "int8", "int2", "smallint", "bigint",
    "numeric", "decimal", "real", "float4", "float8",
    "double precision", "money",
})

_STRING_TYPES = frozenset({
    "character varying", "varchar", "text", "char", "character",
    "bpchar", "name",
})

_BOOLEAN_TYPES = frozenset({"boolean", "bool"})

# Maximum distinct values to be considered a discriminator
_DISCRIMINATOR_MAX_CARDINALITY = 10

# Minimum uniqueness ratio to be considered an identifier
_IDENTIFIER_UNIQUENESS_THRESHOLD = 0.95


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA PROFILER
# ═══════════════════════════════════════════════════════════════════════════


class SchemaProfiler:
    """
    Profiles database tables using pure statistical queries.
    Zero hardcoded business knowledge — all inference from data patterns.
    """

    def profile_table(
        self,
        engine,
        table_name: str,
        schema: str = "public",
        sample_size: int = 1000,
    ) -> TableProfile:
        """Profile all columns in a table."""
        profile = TableProfile(table_name=table_name, schema=schema)

        try:
            columns_meta = self._get_columns_metadata(engine, table_name, schema)
            if not columns_meta:
                logger.warning("profiler.no_columns", table=table_name, schema=schema)
                return profile

            # Get row count
            profile.row_count = self._get_row_count(engine, table_name, schema)
            profile.column_count = len(columns_meta)

            for col_meta in columns_meta:
                col_name = col_meta["column_name"]
                col_profile = self.profile_column(
                    engine, table_name, col_name, schema,
                    db_type=col_meta.get("data_type", ""),
                    row_count=profile.row_count,
                    sample_size=sample_size,
                )
                profile.columns[col_name] = col_profile

            # Detect semantics
            profile.discriminators = self.detect_discriminators(profile)
            profile.monetary_columns = self.detect_monetary_columns(profile)
            profile.temporal_columns = self.detect_temporal_columns(profile)
            profile.identifier_columns = self.detect_identifier_columns(profile)

        except Exception as exc:
            logger.error("profiler.table_error", table=table_name, error=str(exc))

        return profile

    def profile_column(
        self,
        engine,
        table_name: str,
        column_name: str,
        schema: str = "public",
        db_type: str = "",
        row_count: int | None = None,
        sample_size: int = 1000,
    ) -> ColumnProfile:
        """Profile a single column with statistical queries."""
        col = ColumnProfile(name=column_name, table=table_name, db_type=db_type)

        try:
            fqn = f'"{schema}"."{table_name}"'
            cq = f'"{column_name}"'

            with engine.connect() as conn:
                # Basic stats
                stats_sql = f"""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(DISTINCT {cq}) AS distinct_count,
                        COUNT(*) - COUNT({cq}) AS null_count
                    FROM {fqn}
                """
                result = conn.execute(_text(stats_sql)).fetchone()
                if result:
                    col.row_count = result[0]
                    col.distinct_count = result[1]
                    col.null_count = result[2]
                    col.null_rate = (
                        col.null_count / col.row_count if col.row_count > 0 else 0.0
                    )
                    col.is_unique = col.distinct_count == col.row_count and col.row_count > 0
                    col.is_non_null = col.null_count == 0

                # Min/Max/Avg for numeric types
                db_type_lower = db_type.lower()
                if db_type_lower in _NUMERIC_TYPES:
                    num_sql = f"""
                        SELECT MIN({cq}), MAX({cq}), AVG({cq}::double precision)
                        FROM {fqn}
                        WHERE {cq} IS NOT NULL
                    """
                    num_result = conn.execute(_text(num_sql)).fetchone()
                    if num_result:
                        col.min_value = num_result[0]
                        col.max_value = num_result[1]
                        col.avg_value = float(num_result[2]) if num_result[2] is not None else None

                # Top values (value distribution)
                top_sql = f"""
                    SELECT {cq}::text AS val, COUNT(*) AS cnt
                    FROM {fqn}
                    WHERE {cq} IS NOT NULL
                    GROUP BY {cq}
                    ORDER BY COUNT(*) DESC
                    LIMIT 10
                """
                top_result = conn.execute(_text(top_sql)).fetchall()
                col.top_values = [
                    {"value": str(row[0]), "count": int(row[1])}
                    for row in top_result
                ]

            # Infer semantic type
            col.semantic_type = self._infer_semantic_type(col)

        except Exception as exc:
            logger.warning(
                "profiler.column_error",
                table=table_name, column=column_name, error=str(exc),
            )

        return col

    def detect_discriminators(self, table_profile: TableProfile) -> list[DiscriminatorCandidate]:
        """
        Detect discriminator columns: low cardinality + string/bool/int type.
        A discriminator is useful as a WHERE filter to segment data.
        """
        candidates = []
        for col in table_profile.columns.values():
            if col.distinct_count < 1 or col.distinct_count > _DISCRIMINATOR_MAX_CARDINALITY:
                continue
            if col.row_count == 0:
                continue

            db_lower = col.db_type.lower()
            is_eligible = (
                db_lower in _STRING_TYPES
                or db_lower in _BOOLEAN_TYPES
                or db_lower in _NUMERIC_TYPES
            )
            if not is_eligible:
                continue

            # Don't pick identifiers as discriminators
            uniqueness = col.distinct_count / col.row_count if col.row_count > 0 else 0
            if uniqueness > 0.5:
                continue

            # Find the most common value
            rec_value = None
            rec_pct = 0.0
            if col.top_values:
                top = col.top_values[0]
                rec_value = top["value"]
                rec_pct = top["count"] / col.row_count if col.row_count > 0 else 0.0

            candidates.append(DiscriminatorCandidate(
                table=table_profile.table_name,
                column=col.name,
                distinct_count=col.distinct_count,
                top_values=col.top_values,
                recommended_value=rec_value,
                recommended_value_pct=rec_pct,
            ))

        # Sort by distinctness (fewer values = stronger discriminator)
        candidates.sort(key=lambda c: c.distinct_count)
        return candidates

    def detect_monetary_columns(self, table_profile: TableProfile) -> list[str]:
        """
        Detect monetary columns: numeric, large variance, not an ID.
        Monetary = numeric + not unique + not identifier-like.
        """
        monetary = []
        for col in table_profile.columns.values():
            if col.db_type.lower() not in _NUMERIC_TYPES:
                continue
            if col.is_unique:
                continue
            # Skip likely identifiers (high cardinality relative to row count)
            if col.row_count > 0:
                uniqueness = col.distinct_count / col.row_count
                if uniqueness > _IDENTIFIER_UNIQUENESS_THRESHOLD:
                    continue
            # Must have some variance (min != max)
            if col.min_value is not None and col.max_value is not None:
                try:
                    min_v = float(col.min_value)
                    max_v = float(col.max_value)
                    if min_v == max_v:
                        continue
                    # Monetary columns typically have a meaningful average
                    if col.avg_value is not None and col.avg_value != 0:
                        monetary.append(col.name)
                except (ValueError, TypeError):
                    continue
        return monetary

    def detect_temporal_columns(self, table_profile: TableProfile) -> list[str]:
        """Detect temporal columns from PostgreSQL data types."""
        return [
            col.name for col in table_profile.columns.values()
            if col.db_type.lower() in _TEMPORAL_TYPES
        ]

    def detect_identifier_columns(self, table_profile: TableProfile) -> list[str]:
        """
        Detect identifier columns: high cardinality, unique or near-unique.
        Often column names end in _id but we don't require it — we detect from data.
        """
        identifiers = []
        for col in table_profile.columns.values():
            if col.row_count == 0:
                continue
            uniqueness = col.distinct_count / col.row_count
            if uniqueness >= _IDENTIFIER_UNIQUENESS_THRESHOLD and col.is_non_null:
                identifiers.append(col.name)
        return identifiers

    # ─── Internal helpers ─────────────────────────────────────────────

    def _get_columns_metadata(
        self, engine, table_name: str, schema: str,
    ) -> list[dict[str, Any]]:
        """Get column metadata from information_schema."""
        sql = """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
        """
        with engine.connect() as conn:
            result = conn.execute(_text(sql), {"schema": schema, "table": table_name})
            return [
                {
                    "column_name": row[0],
                    "data_type": row[1],
                    "is_nullable": row[2],
                    "column_default": row[3],
                }
                for row in result.fetchall()
            ]

    def _get_row_count(self, engine, table_name: str, schema: str) -> int:
        """Get approximate row count."""
        fqn = f'"{schema}"."{table_name}"'
        sql = f"SELECT COUNT(*) FROM {fqn}"
        with engine.connect() as conn:
            result = conn.execute(_text(sql)).fetchone()
            return result[0] if result else 0

    def _infer_semantic_type(self, col: ColumnProfile) -> SemanticType:
        """Infer semantic type purely from data statistics and DB type."""
        db_lower = col.db_type.lower()

        if db_lower in _TEMPORAL_TYPES:
            return SemanticType.TEMPORAL

        if db_lower in _BOOLEAN_TYPES:
            return SemanticType.BOOLEAN

        if db_lower in _NUMERIC_TYPES:
            # Identifier: unique, non-null
            if col.is_unique and col.is_non_null:
                return SemanticType.IDENTIFIER
            # Monetary: has variance, not unique
            if col.min_value is not None and col.max_value is not None:
                try:
                    if float(col.min_value) != float(col.max_value) and col.avg_value:
                        return SemanticType.MONETARY
                except (ValueError, TypeError):
                    pass
            return SemanticType.NUMERIC

        if db_lower in _STRING_TYPES:
            if col.distinct_count <= _DISCRIMINATOR_MAX_CARDINALITY and col.row_count > 0:
                return SemanticType.CATEGORICAL
            if col.is_unique and col.is_non_null:
                return SemanticType.IDENTIFIER
            return SemanticType.TEXT

        return SemanticType.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# HELPER: SQLAlchemy text() wrapper
# ═══════════════════════════════════════════════════════════════════════════

def _text(sql: str):
    """Wrap SQL string for SQLAlchemy execution."""
    try:
        from sqlalchemy import text
        return text(sql)
    except ImportError:
        # Fallback for environments without sqlalchemy
        return sql
