"""
Tests for Phase 4: Auto-discovery (profiler + FK + ontology).
Unit tests mock SQLAlchemy; integration test requires Gloria DB.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from core.valinor.discovery.profiler import (
    ColumnProfile,
    DiscriminatorCandidate,
    SchemaProfiler,
    SemanticType,
    TableProfile,
)
from core.valinor.discovery.fk_discovery import FKCandidate, FKDiscovery, PKCandidate
from core.valinor.discovery.ontology_builder import (
    BusinessConcept,
    BusinessOntology,
    EntityClassification,
    EntityType,
    OntologyBuilder,
)


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS — mock DB results
# ═══════════════════════════════════════════════════════════════════════════


def _make_table_profile(
    table_name: str,
    row_count: int = 1000,
    columns: dict | None = None,
    discriminators: list | None = None,
    monetary: list | None = None,
    temporal: list | None = None,
    identifiers: list | None = None,
) -> TableProfile:
    """Build a TableProfile for testing without a real DB."""
    tp = TableProfile(
        table_name=table_name,
        row_count=row_count,
        column_count=len(columns) if columns else 0,
    )
    if columns:
        tp.columns = columns
    if discriminators:
        tp.discriminators = discriminators
    if monetary:
        tp.monetary_columns = monetary
    if temporal:
        tp.temporal_columns = temporal
    if identifiers:
        tp.identifier_columns = identifiers
    return tp


def _make_column(
    name: str,
    table: str = "test_table",
    db_type: str = "character varying",
    row_count: int = 1000,
    distinct_count: int = 5,
    null_count: int = 0,
    min_value=None,
    max_value=None,
    avg_value=None,
    top_values=None,
    is_unique: bool = False,
    is_non_null: bool = True,
) -> ColumnProfile:
    cp = ColumnProfile(name=name, table=table, db_type=db_type)
    cp.row_count = row_count
    cp.distinct_count = distinct_count
    cp.null_count = null_count
    cp.null_rate = null_count / row_count if row_count > 0 else 0.0
    cp.min_value = min_value
    cp.max_value = max_value
    cp.avg_value = avg_value
    cp.top_values = top_values or []
    cp.is_unique = is_unique
    cp.is_non_null = is_non_null
    return cp


# ═══════════════════════════════════════════════════════════════════════════
# PROFILER TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestProfilerDiscriminators:
    """Test discriminator detection — no DB needed."""

    def test_detect_low_cardinality_discriminator(self):
        """Column with 3 distinct values should be flagged as discriminator."""
        profiler = SchemaProfiler()

        col = _make_column(
            name="status_col",
            db_type="character varying",
            row_count=10000,
            distinct_count=3,
            top_values=[
                {"value": "active", "count": 7000},
                {"value": "pending", "count": 2500},
                {"value": "closed", "count": 500},
            ],
        )

        tp = _make_table_profile("orders", row_count=10000, columns={"status_col": col})
        discriminators = profiler.detect_discriminators(tp)

        assert len(discriminators) >= 1
        assert discriminators[0].column == "status_col"
        assert discriminators[0].distinct_count == 3
        assert discriminators[0].recommended_value == "active"

    def test_high_cardinality_not_discriminator(self):
        """Column with 500 distinct values should NOT be a discriminator."""
        profiler = SchemaProfiler()

        col = _make_column(
            name="customer_name",
            db_type="character varying",
            row_count=10000,
            distinct_count=500,
        )

        tp = _make_table_profile("customers", row_count=10000, columns={"customer_name": col})
        discriminators = profiler.detect_discriminators(tp)
        assert len(discriminators) == 0

    def test_boolean_is_discriminator(self):
        """Boolean column with 2 values is a discriminator."""
        profiler = SchemaProfiler()

        col = _make_column(
            name="is_active",
            db_type="boolean",
            row_count=5000,
            distinct_count=2,
            top_values=[
                {"value": "true", "count": 4000},
                {"value": "false", "count": 1000},
            ],
        )

        tp = _make_table_profile("users", row_count=5000, columns={"is_active": col})
        discriminators = profiler.detect_discriminators(tp)
        assert len(discriminators) == 1
        assert discriminators[0].recommended_value == "true"
        assert discriminators[0].recommended_value_pct == pytest.approx(0.8, abs=0.01)


class TestProfilerMonetary:
    """Test monetary column detection."""

    def test_detect_monetary_column(self):
        """Numeric column with variance and non-zero avg → monetary."""
        profiler = SchemaProfiler()

        col = _make_column(
            name="total_amount",
            db_type="numeric",
            row_count=10000,
            distinct_count=8500,
            min_value=0.5,
            max_value=99999.99,
            avg_value=1500.0,
            is_unique=False,
        )

        tp = _make_table_profile("invoices", row_count=10000, columns={"total_amount": col})
        monetary = profiler.detect_monetary_columns(tp)
        assert "total_amount" in monetary

    def test_unique_numeric_not_monetary(self):
        """Unique numeric column (likely an ID) should NOT be monetary."""
        profiler = SchemaProfiler()

        col = _make_column(
            name="invoice_id",
            db_type="integer",
            row_count=10000,
            distinct_count=10000,
            min_value=1,
            max_value=10000,
            avg_value=5000.5,
            is_unique=True,
        )

        tp = _make_table_profile("invoices", row_count=10000, columns={"invoice_id": col})
        monetary = profiler.detect_monetary_columns(tp)
        assert "invoice_id" not in monetary


class TestProfilerIdentifiers:
    """Test identifier column detection."""

    def test_detect_identifier(self):
        """High cardinality unique non-null column → identifier."""
        profiler = SchemaProfiler()

        col = _make_column(
            name="record_pk",
            db_type="integer",
            row_count=10000,
            distinct_count=10000,
            is_unique=True,
            is_non_null=True,
        )

        tp = _make_table_profile("records", row_count=10000, columns={"record_pk": col})
        identifiers = profiler.detect_identifier_columns(tp)
        assert "record_pk" in identifiers

    def test_nullable_not_identifier(self):
        """Column with nulls (even if unique among non-nulls) not an identifier."""
        profiler = SchemaProfiler()

        col = _make_column(
            name="external_ref",
            db_type="character varying",
            row_count=10000,
            distinct_count=9500,
            null_count=500,
            is_unique=False,
            is_non_null=False,
        )

        tp = _make_table_profile("records", row_count=10000, columns={"external_ref": col})
        identifiers = profiler.detect_identifier_columns(tp)
        assert "external_ref" not in identifiers


class TestProfilerSemanticType:
    """Test semantic type inference."""

    def test_temporal_type(self):
        profiler = SchemaProfiler()
        col = _make_column("created_at", db_type="timestamp without time zone")
        result = profiler._infer_semantic_type(col)
        assert result == SemanticType.TEMPORAL

    def test_boolean_type(self):
        profiler = SchemaProfiler()
        col = _make_column("is_active", db_type="boolean")
        result = profiler._infer_semantic_type(col)
        assert result == SemanticType.BOOLEAN

    def test_categorical_string(self):
        profiler = SchemaProfiler()
        col = _make_column(
            "status", db_type="character varying",
            row_count=1000, distinct_count=5,
        )
        result = profiler._infer_semantic_type(col)
        assert result == SemanticType.CATEGORICAL


# ═══════════════════════════════════════════════════════════════════════════
# FK DISCOVERY TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestFKDiscovery:
    """Test FK discovery — no DB needed, tests scoring and name similarity."""

    def test_discovers_fk_by_name_and_inclusion(self):
        """When source values ⊆ target values and names match → FK candidate."""
        fk = FKCandidate(
            source_table="orders",
            source_column="customer_id",
            target_table="customers",
            target_column="customer_id",
            inclusion_ratio=1.0,
            orphan_count=0,
            name_similarity=1.0,
            cardinality_ratio=0.8,
        )

        discovery = FKDiscovery()
        score = discovery.score_candidate(fk)

        # Should be high: perfect inclusion + perfect name match
        assert score >= 0.8

    def test_rejects_non_inclusion(self):
        """When source values are NOT included in target → low score."""
        fk = FKCandidate(
            source_table="orders",
            source_column="some_col",
            target_table="other_table",
            target_column="other_col",
            inclusion_ratio=0.2,
            orphan_count=800,
            name_similarity=0.3,
            cardinality_ratio=0.1,
        )

        discovery = FKDiscovery()
        score = discovery.score_candidate(fk)

        # Should be low: poor inclusion
        assert score < 0.4

    def test_scores_by_name_similarity(self):
        """Identical column names should score higher than different ones."""
        discovery = FKDiscovery()

        # Same name
        fk_same = FKCandidate(
            source_table="a",
            source_column="partner_ref",
            target_table="b",
            target_column="partner_ref",
            inclusion_ratio=0.95,
            name_similarity=1.0,
            cardinality_ratio=0.9,
        )

        # Different name
        fk_diff = FKCandidate(
            source_table="a",
            source_column="ref_code",
            target_table="b",
            target_column="partner_ref",
            inclusion_ratio=0.95,
            name_similarity=0.3,
            cardinality_ratio=0.9,
        )

        score_same = discovery.score_candidate(fk_same)
        score_diff = discovery.score_candidate(fk_diff)

        assert score_same > score_diff

    def test_name_similarity_exact_match(self):
        """Exact name match should return 1.0."""
        sim = FKDiscovery._name_similarity("customer_id", "customer_id")
        assert sim == 1.0

    def test_name_similarity_stem_match(self):
        """Names sharing a stem before _id should have decent similarity."""
        sim = FKDiscovery._name_similarity("partner_id", "partner_id")
        assert sim == 1.0

        # Partial stem match
        sim2 = FKDiscovery._name_similarity("bp_id", "c_bpartner_id")
        assert sim2 > 0.0  # Some similarity via stem


# ═══════════════════════════════════════════════════════════════════════════
# ONTOLOGY BUILDER TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestOntologyBuilder:
    """Test ontology classification and entity_map generation."""

    def test_classifies_transactional(self):
        """Table with date + money + high rows → TRANSACTIONAL."""
        builder = OntologyBuilder()

        tp = _make_table_profile(
            "sales",
            row_count=50000,
            monetary=["total_amount", "tax_amount"],
            temporal=["created_date", "posted_date"],
            identifiers=["sales_id"],
        )

        fk_graph = {"inbound": {}, "outbound": {}}
        ec = builder.classify_entity(tp, fk_graph)

        assert ec.entity_type == EntityType.TRANSACTIONAL
        assert ec.confidence >= 0.8

    def test_classifies_master(self):
        """Table with inbound FKs → MASTER."""
        builder = OntologyBuilder()

        tp = _make_table_profile(
            "partners",
            row_count=500,
            identifiers=["partner_id"],
            temporal=[],
            monetary=[],
        )

        fk_graph = {"inbound": {"partners": 3}, "outbound": {}}
        ec = builder.classify_entity(tp, fk_graph)

        assert ec.entity_type == EntityType.MASTER

    def test_classifies_config(self):
        """Table with very few rows → CONFIG."""
        builder = OntologyBuilder()

        tp = _make_table_profile("settings", row_count=15)

        fk_graph = {"inbound": {}, "outbound": {}}
        ec = builder.classify_entity(tp, fk_graph)

        assert ec.entity_type == EntityType.CONFIG

    def test_classifies_bridge(self):
        """Table with few columns and multiple outbound FKs → BRIDGE."""
        builder = OntologyBuilder()

        tp = _make_table_profile(
            "order_product",
            row_count=5000,
            columns={
                "order_id": _make_column("order_id", db_type="integer"),
                "product_id": _make_column("product_id", db_type="integer"),
                "quantity": _make_column("quantity", db_type="integer"),
            },
        )
        tp.column_count = 3

        fk_graph = {"inbound": {}, "outbound": {"order_product": 2}}
        ec = builder.classify_entity(tp, fk_graph)

        assert ec.entity_type == EntityType.BRIDGE

    def test_suggests_base_filter(self):
        """Discriminator with Y=80%, N=20% → base_filter uses top value."""
        builder = OntologyBuilder()

        disc = DiscriminatorCandidate(
            table="invoices",
            column="doc_type",
            distinct_count=2,
            top_values=[
                {"value": "Y", "count": 8000},
                {"value": "N", "count": 2000},
            ],
            recommended_value="Y",
            recommended_value_pct=0.8,
        )

        tp = _make_table_profile("invoices", row_count=10000, discriminators=[disc])
        suggestion = builder.suggest_base_filter(tp)

        assert suggestion is not None
        assert "doc_type" in suggestion
        assert "'Y'" in suggestion

    def test_generates_entity_map_format(self):
        """Output should match expected entity_map structure."""
        builder = OntologyBuilder()

        ontology = BusinessOntology()
        ontology.entities["sales"] = EntityClassification(
            table_name="sales",
            entity_type=EntityType.TRANSACTIONAL,
            business_concept=BusinessConcept.REVENUE,
            confidence=0.9,
            monetary_columns=["amount"],
            temporal_columns=["date"],
            identifier_columns=["id"],
            discriminators=["status"],
            base_filter="status='posted'",
        )
        ontology.entities["customers"] = EntityClassification(
            table_name="customers",
            entity_type=EntityType.MASTER,
            business_concept=BusinessConcept.CUSTOMER,
            confidence=0.7,
            identifier_columns=["id"],
        )
        ontology.relationships = [
            {
                "source_table": "sales",
                "source_column": "customer_id",
                "target_table": "customers",
                "target_column": "id",
                "score": "0.85",
            }
        ]
        ontology.revenue_entities = ["sales"]
        ontology.customer_entities = ["customers"]

        entity_map = builder.generate_entity_map(ontology)

        # Structural checks
        assert "entities" in entity_map
        assert "relationships" in entity_map
        assert "metadata" in entity_map

        # Entity content
        assert "sales" in entity_map["entities"]
        sales_e = entity_map["entities"]["sales"]
        assert sales_e["type"] == "transactional"
        assert sales_e["concept"] == "revenue"
        assert "amount" in sales_e["monetary_columns"]
        assert sales_e["base_filter"] == "status='posted'"

        # Relationships
        assert len(entity_map["relationships"]) == 1
        rel = entity_map["relationships"][0]
        assert rel["from"] == "sales.customer_id"
        assert rel["to"] == "customers.id"

        # Metadata
        assert "sales" in entity_map["metadata"]["revenue_entities"]
        assert "customers" in entity_map["metadata"]["customer_entities"]


class TestOntologyBusinessConcepts:
    """Test business concept inference."""

    def test_revenue_entity_inference(self):
        """TRANSACTIONAL + monetary → REVENUE concept."""
        builder = OntologyBuilder()

        profiles = {
            "invoices": _make_table_profile(
                "invoices", row_count=10000,
                monetary=["grand_total"], temporal=["invoice_date"],
            ),
        }
        fks: list[FKCandidate] = []

        ontology = builder.build_ontology(profiles, fks)
        assert ontology.entities["invoices"].business_concept == BusinessConcept.REVENUE

    def test_customer_entity_inference(self):
        """MASTER referenced by REVENUE entity → CUSTOMER concept."""
        builder = OntologyBuilder()

        profiles = {
            "invoices": _make_table_profile(
                "invoices", row_count=10000,
                monetary=["amount"], temporal=["created"],
            ),
            "partners": _make_table_profile(
                "partners", row_count=500,
            ),
        }

        fks = [
            FKCandidate(
                source_table="invoices",
                source_column="partner_id",
                target_table="partners",
                target_column="id",
                inclusion_ratio=0.99,
                name_similarity=0.8,
                cardinality_ratio=0.9,
                score=0.9,
            ),
        ]

        ontology = builder.build_ontology(profiles, fks)
        assert ontology.entities["partners"].business_concept == BusinessConcept.CUSTOMER
        assert "partners" in ontology.customer_entities


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TEST — Gloria DB (skipped if no DB)
# ═══════════════════════════════════════════════════════════════════════════


GLORIA_DB_URL = os.environ.get("GLORIA_DB_URL", "")


@pytest.mark.skipif(
    not GLORIA_DB_URL,
    reason="GLORIA_DB_URL not set — skip integration test",
)
class TestGloriaIntegration:
    """Integration tests against the Gloria ERP database."""

    @pytest.fixture(autouse=True)
    def _setup_engine(self):
        from sqlalchemy import create_engine
        self.engine = create_engine(GLORIA_DB_URL)

    def test_profile_invoice_table(self):
        """Profile c_invoice → detect discriminators."""
        profiler = SchemaProfiler()
        tp = profiler.profile_table(self.engine, "c_invoice", schema="adempiere")

        assert tp.row_count > 0
        assert len(tp.discriminators) > 0

        disc_names = [d.column for d in tp.discriminators]
        # issotrx and docstatus are common discriminators in this table
        # but we verify they are DISCOVERED, not hardcoded
        assert len(disc_names) >= 1  # at least one discriminator found

    def test_discover_fk_invoice_to_partner(self):
        """Discover FK: c_invoice → c_bpartner."""
        discovery = FKDiscovery(min_inclusion_ratio=0.8, min_score=0.3)
        tables = ["c_invoice", "c_bpartner"]
        fks = discovery.discover_fks(self.engine, tables, schema="adempiere")

        # Should find at least one FK between these tables
        assert len(fks) >= 1
        found = any(
            fk.source_table == "c_invoice" and fk.target_table == "c_bpartner"
            for fk in fks
        )
        assert found, f"Expected FK from c_invoice to c_bpartner, got: {fks}"

    def test_build_ontology_classifies_correctly(self):
        """Build ontology → c_invoice=TRANSACTIONAL, c_bpartner=MASTER."""
        profiler = SchemaProfiler()
        discovery = FKDiscovery(min_inclusion_ratio=0.8, min_score=0.3)
        builder = OntologyBuilder()

        tables = ["c_invoice", "c_bpartner"]
        profiles = {}
        for t in tables:
            profiles[t] = profiler.profile_table(self.engine, t, schema="adempiere")

        fks = discovery.discover_fks(self.engine, tables, schema="adempiere")
        ontology = builder.build_ontology(profiles, fks)

        assert ontology.entities["c_invoice"].entity_type == EntityType.TRANSACTIONAL
        assert ontology.entities["c_bpartner"].entity_type == EntityType.MASTER
