"""
SchemaExtractor — Dialect-aware schema extraction + Structural Profiler.

Uses SQLAlchemy Inspector to support multiple database dialects
(PostgreSQL, SQL Server, SQLite) with a unified output model.

Structural Profiler adds:
  - PK candidate detection (uniqueness-based)
  - Column type classification (SQL types -> semantic categories)
  - Null density & distinct counts
  - Dialect-aware SQL for sampling

References:
  - SQLAlchemy Inspector API (2.0+)
  - ydata-profiling — statistical profiling patterns
  - GAIT (PAKDD 2024) — data-driven semantic type detection
"""

from __future__ import annotations

from enum import Enum

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, Inspector

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════


class ColumnTypeCategory(str, Enum):
    """Semantic category inferred from SQL column type."""
    ID = "id"
    DATETIME = "datetime"
    MONETARY = "monetary"
    TEXT = "text"
    CATEGORICAL = "categorical"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    BINARY = "binary"
    UNKNOWN = "unknown"


class ColumnInfo(BaseModel):
    """Per-column metadata with type classification and structural stats."""
    name: str
    sql_type: str = ""
    nullable: bool = True
    default: str | None = None
    type_category: ColumnTypeCategory = ColumnTypeCategory.UNKNOWN
    # Structural profiler stats (populated by profile_table)
    null_count: int = 0
    null_density: float = 0.0
    distinct_count: int = 0
    is_pk_candidate: bool = False


class PKConstraint(BaseModel):
    """Primary key constraint for a table."""
    name: str | None = None
    columns: list[str] = Field(default_factory=list)


class PKCandidate(BaseModel):
    """A column detected as a potential primary key via uniqueness check."""
    table: str
    column: str
    uniqueness_score: float = 0.0  # 1.0 = perfectly unique


class FKRelation(BaseModel):
    """Foreign key relationship (from Inspector or discovered)."""
    name: str | None = None
    source_table: str
    source_columns: list[str]
    target_table: str
    target_columns: list[str]
    target_schema: str | None = None


class TableInfo(BaseModel):
    """Per-table metadata including columns, constraints, and row count."""
    name: str
    schema_name: str = ""
    row_count: int = 0
    columns: list[ColumnInfo] = Field(default_factory=list)
    pk: PKConstraint = Field(default_factory=lambda: PKConstraint())
    fks: list[FKRelation] = Field(default_factory=list)
    pk_candidates: list[PKCandidate] = Field(default_factory=list)


class SchemaProfile(BaseModel):
    """Top-level result from SchemaExtractor.extract_all()."""
    dialect: str = ""
    schema_name: str = ""
    tables: list[TableInfo] = Field(default_factory=list)
    table_count: int = 0
    total_row_count: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# TYPE CLASSIFICATION — SQL type string -> ColumnTypeCategory
# ═══════════════════════════════════════════════════════════════════════════

# Patterns matched against the lowercased str(column_type)
_TYPE_MAP: list[tuple[list[str], ColumnTypeCategory]] = [
    # Datetime
    (
        ["date", "timestamp", "time", "interval", "datetime", "datetime2",
         "smalldatetime", "datetimeoffset"],
        ColumnTypeCategory.DATETIME,
    ),
    # Boolean
    (
        ["bool", "boolean", "bit"],
        ColumnTypeCategory.BOOLEAN,
    ),
    # Monetary — specific numeric types often used for money
    (
        ["money", "smallmoney"],
        ColumnTypeCategory.MONETARY,
    ),
    # Numeric (general)
    (
        ["int", "integer", "smallint", "bigint", "tinyint", "mediumint",
         "numeric", "decimal", "real", "float", "double", "number"],
        ColumnTypeCategory.NUMERIC,
    ),
    # Text
    (
        ["char", "varchar", "text", "nchar", "nvarchar", "ntext",
         "clob", "string", "name", "bpchar", "citext"],
        ColumnTypeCategory.TEXT,
    ),
    # Binary
    (
        ["blob", "binary", "varbinary", "bytea", "image"],
        ColumnTypeCategory.BINARY,
    ),
]


def classify_sql_type(sql_type_str: str) -> ColumnTypeCategory:
    """Map a SQL type string to a ColumnTypeCategory."""
    lower = sql_type_str.lower().strip()
    if not lower:
        return ColumnTypeCategory.UNKNOWN
    for keywords, category in _TYPE_MAP:
        for kw in keywords:
            if kw in lower:
                return category
    return ColumnTypeCategory.UNKNOWN


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════


class SchemaExtractor:
    """Dialect-aware schema extraction using SQLAlchemy Inspector."""

    def __init__(self, connection_string: str):
        self._connection_string = connection_string
        self._engine: Engine = create_engine(connection_string)
        self._inspector: Inspector = inspect(self._engine)
        self._dialect: str = self._engine.dialect.name

    @property
    def dialect(self) -> str:
        return self._dialect

    @property
    def engine(self) -> Engine:
        return self._engine

    def dispose(self) -> None:
        """Dispose the engine and release connections."""
        self._engine.dispose()

    # ─── Public API ───────────────────────────────────────────────────

    def extract_all(self, schema: str | None = None) -> SchemaProfile:
        """
        Extract unified SchemaProfile regardless of dialect.

        Args:
            schema: Database schema to inspect. Defaults to dialect-appropriate
                    default (e.g., 'public' for PostgreSQL, 'dbo' for SQL Server,
                    None for SQLite).
        """
        schema = self._resolve_schema(schema)

        tables = self._extract_tables(schema)
        table_infos: list[TableInfo] = []
        total_rows = 0

        for table_name in tables:
            ti = TableInfo(name=table_name, schema_name=schema or "")
            ti.columns = self._extract_columns(table_name, schema)
            ti.pk = self._extract_pks(table_name, schema)
            ti.fks = self._extract_fks(table_name, schema)
            table_infos.append(ti)

        # Batch row counts
        row_counts = self._extract_row_counts(tables, schema)
        for ti in table_infos:
            ti.row_count = row_counts.get(ti.name, 0)
            total_rows += ti.row_count

        profile = SchemaProfile(
            dialect=self._dialect,
            schema_name=schema or "",
            tables=table_infos,
            table_count=len(table_infos),
            total_row_count=total_rows,
        )

        logger.info(
            "schema_extracted",
            dialect=self._dialect,
            schema=schema,
            tables=len(table_infos),
            total_rows=total_rows,
        )

        return profile

    def profile_table(self, table_name: str, schema: str | None = None) -> TableInfo:
        """
        Structural profiling for a single table: null density, distinct counts,
        PK candidate detection. Requires a prior extract or standalone call.
        """
        schema = self._resolve_schema(schema)

        ti = TableInfo(name=table_name, schema_name=schema or "")
        ti.columns = self._extract_columns(table_name, schema)
        ti.pk = self._extract_pks(table_name, schema)
        ti.fks = self._extract_fks(table_name, schema)

        row_counts = self._extract_row_counts([table_name], schema)
        ti.row_count = row_counts.get(table_name, 0)

        if ti.row_count == 0:
            return ti

        # Structural stats per column
        fqn = self._fqn(table_name, schema)
        col_names = [c.name for c in ti.columns]

        if not col_names:
            return ti

        # Build a single query for all columns: COUNT(DISTINCT col), COUNT(col)
        agg_parts: list[str] = []
        for col in col_names:
            cq = self._quote_ident(col)
            agg_parts.append(f"COUNT(DISTINCT {cq})")
            agg_parts.append(f"COUNT({cq})")

        sql = f"SELECT COUNT(*), {', '.join(agg_parts)} FROM {fqn}"

        try:
            with self._engine.connect() as conn:
                row = conn.execute(text(sql)).fetchone()
        except Exception as exc:
            logger.warning("profile_table.stats_error", table=table_name, error=str(exc))
            return ti

        if not row:
            return ti

        total = row[0]
        pk_columns_set = set(ti.pk.columns)

        for i, col_info in enumerate(ti.columns):
            distinct = row[1 + i * 2]
            non_null = row[2 + i * 2]
            null_count = total - non_null

            col_info.distinct_count = distinct
            col_info.null_count = null_count
            col_info.null_density = null_count / total if total > 0 else 0.0

            # PK candidate: unique + non-null + not already declared PK
            is_unique = distinct == total and total > 0
            is_non_null = null_count == 0
            if is_unique and is_non_null and col_info.name not in pk_columns_set:
                col_info.is_pk_candidate = True
                ti.pk_candidates.append(PKCandidate(
                    table=table_name,
                    column=col_info.name,
                    uniqueness_score=1.0,
                ))
            elif total > 0 and is_non_null and distinct / total >= 0.95 and col_info.name not in pk_columns_set:
                # Near-unique candidate
                score = distinct / total
                col_info.is_pk_candidate = True
                ti.pk_candidates.append(PKCandidate(
                    table=table_name,
                    column=col_info.name,
                    uniqueness_score=round(score, 4),
                ))

        return ti

    # ─── Internal extraction methods ──────────────────────────────────

    def _extract_tables(self, schema: str | None) -> list[str]:
        """Get table names for the given schema."""
        try:
            if self._dialect == "sqlite":
                return self._inspector.get_table_names()
            return self._inspector.get_table_names(schema=schema)
        except Exception as exc:
            logger.warning("extract_tables.error", schema=schema, error=str(exc))
            return []

    def _extract_columns(self, table: str, schema: str | None) -> list[ColumnInfo]:
        """Extract column metadata using Inspector."""
        try:
            kwargs = {} if self._dialect == "sqlite" else {"schema": schema}
            raw_cols = self._inspector.get_columns(table, **kwargs)
        except Exception as exc:
            logger.warning("extract_columns.error", table=table, error=str(exc))
            return []

        columns: list[ColumnInfo] = []
        for col in raw_cols:
            sql_type_str = str(col.get("type", ""))
            columns.append(ColumnInfo(
                name=col["name"],
                sql_type=sql_type_str,
                nullable=col.get("nullable", True),
                default=str(col["default"]) if col.get("default") is not None else None,
                type_category=classify_sql_type(sql_type_str),
            ))

        return columns

    def _extract_pks(self, table: str, schema: str | None) -> PKConstraint:
        """Extract primary key constraint."""
        try:
            kwargs = {} if self._dialect == "sqlite" else {"schema": schema}
            pk_info = self._inspector.get_pk_constraint(table, **kwargs)
        except Exception as exc:
            logger.warning("extract_pks.error", table=table, error=str(exc))
            return PKConstraint()

        return PKConstraint(
            name=pk_info.get("name"),
            columns=pk_info.get("constrained_columns", []),
        )

    def _extract_fks(self, table: str, schema: str | None) -> list[FKRelation]:
        """Extract foreign key relationships."""
        try:
            kwargs = {} if self._dialect == "sqlite" else {"schema": schema}
            raw_fks = self._inspector.get_foreign_keys(table, **kwargs)
        except Exception as exc:
            logger.warning("extract_fks.error", table=table, error=str(exc))
            return []

        fks: list[FKRelation] = []
        for fk in raw_fks:
            fks.append(FKRelation(
                name=fk.get("name"),
                source_table=table,
                source_columns=fk.get("constrained_columns", []),
                target_table=fk.get("referred_table", ""),
                target_columns=fk.get("referred_columns", []),
                target_schema=fk.get("referred_schema"),
            ))

        return fks

    def _extract_row_counts(
        self, tables: list[str], schema: str | None,
    ) -> dict[str, int]:
        """Get row counts for each table using dialect-aware SQL."""
        counts: dict[str, int] = {}
        try:
            with self._engine.connect() as conn:
                for table in tables:
                    fqn = self._fqn(table, schema)
                    sql = f"SELECT COUNT(*) FROM {fqn}"
                    result = conn.execute(text(sql)).fetchone()
                    counts[table] = result[0] if result else 0
        except Exception as exc:
            logger.warning("extract_row_counts.error", error=str(exc))

        return counts

    # ─── Dialect helpers ──────────────────────────────────────────────

    def _resolve_schema(self, schema: str | None) -> str | None:
        """Resolve schema to a dialect-appropriate default."""
        if schema is not None:
            return schema
        if self._dialect == "sqlite":
            return None
        if self._dialect == "mssql":
            return "dbo"
        return "public"

    def _fqn(self, table: str, schema: str | None) -> str:
        """Build a fully-qualified table name with quoting."""
        tq = self._quote_ident(table)
        if schema and self._dialect != "sqlite":
            return f"{self._quote_ident(schema)}.{tq}"
        return tq

    def _quote_ident(self, name: str) -> str:
        """Quote an identifier for the current dialect."""
        if self._dialect == "mssql":
            return f"[{name}]"
        return f'"{name}"'

    def _limit_sql(self, base_sql: str, n: int) -> str:
        """Append dialect-appropriate row limit."""
        if self._dialect == "mssql":
            # SQL Server: inject TOP N after SELECT
            return base_sql.replace("SELECT ", f"SELECT TOP {n} ", 1)
        return f"{base_sql} LIMIT {n}"
