"""
Tests for SchemaExtractor — dialect-aware schema extraction + Structural Profiler.

Uses real SQLite in-memory databases (no mocks).

Refs: VAL-126
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from core.valinor.discovery.schema_extractor import (
    ColumnInfo,
    ColumnTypeCategory,
    FKRelation,
    PKCandidate,
    PKConstraint,
    SchemaExtractor,
    SchemaProfile,
    TableInfo,
    classify_sql_type,
)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sqlite_url(tmp_path) -> str:
    """Create a SQLite DB with known schema for testing."""
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)

    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                total REAL NOT NULL,
                order_date DATE NOT NULL,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """))

        # Insert test data
        conn.execute(text("""
            INSERT INTO customers (id, name, email) VALUES
            (1, 'Alice', 'alice@example.com'),
            (2, 'Bob', 'bob@example.com'),
            (3, 'Charlie', NULL)
        """))
        conn.execute(text("""
            INSERT INTO orders (id, customer_id, total, order_date, status) VALUES
            (100, 1, 99.50, '2025-01-15', 'completed'),
            (101, 1, 200.00, '2025-02-10', 'completed'),
            (102, 2, 50.75, '2025-03-01', 'pending'),
            (103, 3, 150.00, '2025-03-15', 'cancelled')
        """))
        conn.execute(text("""
            INSERT INTO order_items (id, order_id, product_name, quantity, unit_price) VALUES
            (1, 100, 'Widget A', 2, 25.00),
            (2, 100, 'Widget B', 1, 49.50),
            (3, 101, 'Widget A', 4, 50.00),
            (4, 102, 'Widget C', 1, 50.75),
            (5, 103, 'Widget A', 3, 50.00)
        """))
        conn.execute(text("""
            INSERT INTO config (key, value) VALUES
            ('currency', 'USD'),
            ('tax_rate', '0.21')
        """))
        conn.commit()

    engine.dispose()
    return url


@pytest.fixture
def extractor(sqlite_url) -> SchemaExtractor:
    """SchemaExtractor instance for the test SQLite DB."""
    ext = SchemaExtractor(sqlite_url)
    yield ext
    ext.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# DIALECT DETECTION
# ═══════════════════════════════════════════════════════════════════════════


class TestDialectDetection:
    def test_sqlite_dialect(self, extractor):
        assert extractor.dialect == "sqlite"


# ═══════════════════════════════════════════════════════════════════════════
# TYPE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════


class TestTypeClassification:
    @pytest.mark.parametrize("sql_type,expected", [
        ("INTEGER", ColumnTypeCategory.NUMERIC),
        ("BIGINT", ColumnTypeCategory.NUMERIC),
        ("REAL", ColumnTypeCategory.NUMERIC),
        ("FLOAT", ColumnTypeCategory.NUMERIC),
        ("NUMERIC(10,2)", ColumnTypeCategory.NUMERIC),
        ("DECIMAL(18,4)", ColumnTypeCategory.NUMERIC),
        ("TEXT", ColumnTypeCategory.TEXT),
        ("VARCHAR(255)", ColumnTypeCategory.TEXT),
        ("NVARCHAR(100)", ColumnTypeCategory.TEXT),
        ("CHAR(10)", ColumnTypeCategory.TEXT),
        ("DATE", ColumnTypeCategory.DATETIME),
        ("TIMESTAMP", ColumnTypeCategory.DATETIME),
        ("DATETIME", ColumnTypeCategory.DATETIME),
        ("DATETIME2", ColumnTypeCategory.DATETIME),
        ("BOOLEAN", ColumnTypeCategory.BOOLEAN),
        ("BIT", ColumnTypeCategory.BOOLEAN),
        ("BLOB", ColumnTypeCategory.BINARY),
        ("BYTEA", ColumnTypeCategory.BINARY),
        ("MONEY", ColumnTypeCategory.MONETARY),
        ("SMALLMONEY", ColumnTypeCategory.MONETARY),
        ("", ColumnTypeCategory.UNKNOWN),
        ("GEOGRAPHY", ColumnTypeCategory.UNKNOWN),
    ])
    def test_classify_sql_type(self, sql_type, expected):
        assert classify_sql_type(sql_type) == expected


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemaExtraction:
    def test_extract_all_returns_schema_profile(self, extractor):
        profile = extractor.extract_all()
        assert isinstance(profile, SchemaProfile)
        assert profile.dialect == "sqlite"

    def test_extract_all_table_count(self, extractor):
        profile = extractor.extract_all()
        assert profile.table_count == 4
        table_names = {t.name for t in profile.tables}
        assert table_names == {"customers", "orders", "order_items", "config"}

    def test_extract_all_row_counts(self, extractor):
        profile = extractor.extract_all()
        counts = {t.name: t.row_count for t in profile.tables}
        assert counts["customers"] == 3
        assert counts["orders"] == 4
        assert counts["order_items"] == 5
        assert counts["config"] == 2
        assert profile.total_row_count == 14

    def test_extract_columns(self, extractor):
        profile = extractor.extract_all()
        customers = next(t for t in profile.tables if t.name == "customers")
        col_names = [c.name for c in customers.columns]
        assert "id" in col_names
        assert "name" in col_names
        assert "email" in col_names
        assert "created_at" in col_names

    def test_column_type_classification(self, extractor):
        profile = extractor.extract_all()
        orders = next(t for t in profile.tables if t.name == "orders")
        col_map = {c.name: c for c in orders.columns}

        # INTEGER -> NUMERIC
        assert col_map["id"].type_category == ColumnTypeCategory.NUMERIC
        # REAL -> NUMERIC
        assert col_map["total"].type_category == ColumnTypeCategory.NUMERIC
        # DATE -> DATETIME
        assert col_map["order_date"].type_category == ColumnTypeCategory.DATETIME
        # TEXT -> TEXT
        assert col_map["status"].type_category == ColumnTypeCategory.TEXT

    def test_extract_pks(self, extractor):
        profile = extractor.extract_all()
        customers = next(t for t in profile.tables if t.name == "customers")
        assert "id" in customers.pk.columns

    def test_extract_fks(self, extractor):
        profile = extractor.extract_all()
        orders = next(t for t in profile.tables if t.name == "orders")
        assert len(orders.fks) >= 1
        fk = orders.fks[0]
        assert isinstance(fk, FKRelation)
        assert fk.source_table == "orders"
        assert "customer_id" in fk.source_columns
        assert fk.target_table == "customers"
        assert "id" in fk.target_columns

    def test_extract_fks_order_items(self, extractor):
        profile = extractor.extract_all()
        items = next(t for t in profile.tables if t.name == "order_items")
        assert len(items.fks) >= 1
        fk_targets = {fk.target_table for fk in items.fks}
        assert "orders" in fk_targets


# ═══════════════════════════════════════════════════════════════════════════
# STRUCTURAL PROFILER
# ═══════════════════════════════════════════════════════════════════════════


class TestStructuralProfiler:
    def test_profile_table_null_density(self, extractor):
        ti = extractor.profile_table("customers")
        col_map = {c.name: c for c in ti.columns}

        # email has 1 NULL out of 3 rows
        assert col_map["email"].null_count == 1
        assert abs(col_map["email"].null_density - 1 / 3) < 0.01

        # name has 0 NULLs
        assert col_map["name"].null_count == 0
        assert col_map["name"].null_density == 0.0

    def test_profile_table_distinct_counts(self, extractor):
        ti = extractor.profile_table("orders")
        col_map = {c.name: c for c in ti.columns}

        # 4 distinct order IDs
        assert col_map["id"].distinct_count == 4
        # 3 distinct customer_ids (1, 2, 3)
        assert col_map["customer_id"].distinct_count == 3
        # 3 distinct statuses: completed, pending, cancelled
        assert col_map["status"].distinct_count == 3

    def test_pk_candidate_detection(self, extractor):
        ti = extractor.profile_table("customers")
        # 'id' is already a declared PK, so should NOT appear as candidate
        pk_candidate_cols = {c.column for c in ti.pk_candidates}
        assert "id" not in pk_candidate_cols

        # 'name' is unique (3 distinct, 3 rows, non-null) -> should be candidate
        assert "name" in pk_candidate_cols

    def test_pk_candidate_uniqueness_score(self, extractor):
        ti = extractor.profile_table("customers")
        name_candidate = next(
            (c for c in ti.pk_candidates if c.column == "name"), None
        )
        assert name_candidate is not None
        assert name_candidate.uniqueness_score == 1.0

    def test_pk_candidate_not_for_non_unique(self, extractor):
        ti = extractor.profile_table("orders")
        pk_candidate_cols = {c.column for c in ti.pk_candidates}
        # customer_id is NOT unique (3 distinct, 4 rows) -> not a candidate
        assert "customer_id" not in pk_candidate_cols
        # status is NOT unique -> not a candidate
        assert "status" not in pk_candidate_cols

    def test_profile_empty_table(self, sqlite_url):
        """Test profiling a table with 0 rows."""
        engine = create_engine(sqlite_url)
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE empty_tbl (id INTEGER PRIMARY KEY, val TEXT)"))
            conn.commit()
        engine.dispose()

        ext = SchemaExtractor(sqlite_url)
        try:
            ti = ext.profile_table("empty_tbl")
            assert ti.row_count == 0
            assert len(ti.pk_candidates) == 0
            for col in ti.columns:
                assert col.null_density == 0.0
                assert col.distinct_count == 0
        finally:
            ext.dispose()

    def test_profile_table_row_count(self, extractor):
        ti = extractor.profile_table("order_items")
        assert ti.row_count == 5


# ═══════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════


class TestPydanticModels:
    def test_schema_profile_serialization(self, extractor):
        profile = extractor.extract_all()
        data = profile.model_dump()
        assert isinstance(data, dict)
        assert data["dialect"] == "sqlite"
        assert len(data["tables"]) == 4

    def test_table_info_serialization(self, extractor):
        ti = extractor.profile_table("orders")
        data = ti.model_dump()
        assert data["name"] == "orders"
        assert data["row_count"] == 4
        assert isinstance(data["columns"], list)
        assert isinstance(data["fks"], list)

    def test_roundtrip_schema_profile(self, extractor):
        profile = extractor.extract_all()
        data = profile.model_dump()
        restored = SchemaProfile.model_validate(data)
        assert restored.dialect == profile.dialect
        assert restored.table_count == profile.table_count


# ═══════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_in_memory_sqlite(self):
        """Test with pure in-memory SQLite (no file)."""
        url = "sqlite://"
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)"
            ))
            conn.execute(text("INSERT INTO t VALUES (1, 'a'), (2, 'b')"))
            conn.commit()
        engine.dispose()

        # SchemaExtractor creates its own engine, so in-memory won't have
        # the table. This tests that the extractor handles empty schemas.
        ext = SchemaExtractor(url)
        try:
            profile = ext.extract_all()
            assert isinstance(profile, SchemaProfile)
            assert profile.table_count == 0  # empty in-memory DB
        finally:
            ext.dispose()

    def test_config_table_has_no_fks(self, extractor):
        profile = extractor.extract_all()
        config = next(t for t in profile.tables if t.name == "config")
        assert len(config.fks) == 0

    def test_dialect_helper_fqn(self, extractor):
        # SQLite should not prefix schema
        fqn = extractor._fqn("mytable", None)
        assert fqn == '"mytable"'

    def test_dialect_helper_limit_sql(self, extractor):
        limited = extractor._limit_sql("SELECT * FROM t", 10)
        assert limited == "SELECT * FROM t LIMIT 10"
