"""
Ontology Builder — Generates a business ontology from discovered metadata.
No LLM. Pure rules-based inference from profiler + FK results.

Infers:
- Entity type (TRANSACTIONAL vs MASTER vs BRIDGE vs CONFIG)
  - TRANSACTIONAL: has date columns + monetary columns + high row count
  - MASTER: moderate row count, referenced by many FKs, has name/description columns
  - BRIDGE: low column count, two FK columns, exists to connect two other tables
  - CONFIG: low row count (<100), low cardinality columns
- Business concepts (revenue entity, customer entity, payment entity)
  - Revenue entity: TRANSACTIONAL + has monetary column + has date column
  - Customer entity: MASTER + referenced by revenue entity via FK
- Recommended base_filter for each entity
  - Use discriminator columns from profiler
  - Pick the value with highest count as default filter value

References:
  - Palantir Foundry — ontology layer between raw data and analysis
  - RIGOR (arXiv:2506.01232) — business rule inference
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from .fk_discovery import FKCandidate
from .profiler import TableProfile, SemanticType

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


class EntityType(str, Enum):
    """Classification of a database table by its business role."""
    TRANSACTIONAL = "transactional"
    MASTER = "master"
    BRIDGE = "bridge"
    CONFIG = "config"
    UNKNOWN = "unknown"


class BusinessConcept(str, Enum):
    """High-level business concept inferred from entity patterns."""
    REVENUE = "revenue"
    CUSTOMER = "customer"
    PRODUCT = "product"
    PAYMENT = "payment"
    GENERIC_TRANSACTION = "generic_transaction"
    GENERIC_MASTER = "generic_master"
    GENERIC_BRIDGE = "generic_bridge"
    GENERIC_CONFIG = "generic_config"
    UNKNOWN = "unknown"


@dataclass
class EntityClassification:
    """Classification result for a single table."""
    table_name: str
    entity_type: EntityType = EntityType.UNKNOWN
    business_concept: BusinessConcept = BusinessConcept.UNKNOWN
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    base_filter: str | None = None
    monetary_columns: list[str] = field(default_factory=list)
    temporal_columns: list[str] = field(default_factory=list)
    identifier_columns: list[str] = field(default_factory=list)
    discriminators: list[str] = field(default_factory=list)
    inbound_fk_count: int = 0   # how many tables reference this one
    outbound_fk_count: int = 0  # how many tables this one references


@dataclass
class BusinessOntology:
    """Complete business ontology for a set of tables."""
    entities: dict[str, EntityClassification] = field(default_factory=dict)
    relationships: list[dict[str, str]] = field(default_factory=list)
    revenue_entities: list[str] = field(default_factory=list)
    customer_entities: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# THRESHOLDS — configurable, not hardcoded to any ERP
# ═══════════════════════════════════════════════════════════════════════════

_CONFIG_MAX_ROWS = 100
_BRIDGE_MAX_COLUMNS = 6
_BRIDGE_MIN_FK_RATIO = 0.5  # at least half of columns are FK-like
_TRANSACTIONAL_MIN_ROWS = 100


# ═══════════════════════════════════════════════════════════════════════════
# ONTOLOGY BUILDER
# ═══════════════════════════════════════════════════════════════════════════


class OntologyBuilder:
    """
    Builds a business ontology from profiler results + FK candidates.
    Zero hardcoded ERP knowledge — all from statistical patterns.
    """

    def build_ontology(
        self,
        table_profiles: dict[str, TableProfile],
        fk_candidates: list[FKCandidate],
    ) -> BusinessOntology:
        """Build complete business ontology."""
        ontology = BusinessOntology()

        # Build FK graph for reference counting
        fk_graph = self._build_fk_graph(fk_candidates)

        # Classify each entity
        for table_name, profile in table_profiles.items():
            classification = self.classify_entity(profile, fk_graph)
            ontology.entities[table_name] = classification

        # Build relationship list
        for fk in fk_candidates:
            ontology.relationships.append({
                "source_table": fk.source_table,
                "source_column": fk.source_column,
                "target_table": fk.target_table,
                "target_column": fk.target_column,
                "score": str(fk.score),
            })

        # Infer business concepts
        self._infer_business_concepts(ontology, fk_candidates)

        return ontology

    def classify_entity(
        self,
        table_profile: TableProfile,
        fk_graph: dict[str, dict[str, int]],
    ) -> EntityClassification:
        """Classify a single table into an entity type."""
        ec = EntityClassification(table_name=table_profile.table_name)

        # Copy discovered attributes
        ec.monetary_columns = list(table_profile.monetary_columns)
        ec.temporal_columns = list(table_profile.temporal_columns)
        ec.identifier_columns = list(table_profile.identifier_columns)
        ec.discriminators = [d.column for d in table_profile.discriminators]

        # FK reference counts
        ec.inbound_fk_count = fk_graph.get("inbound", {}).get(
            table_profile.table_name, 0
        )
        ec.outbound_fk_count = fk_graph.get("outbound", {}).get(
            table_profile.table_name, 0
        )

        # Suggest base filter
        ec.base_filter = self.suggest_base_filter(table_profile)

        # ─── Classification rules (order matters) ─────────────────────
        has_temporal = len(ec.temporal_columns) > 0
        has_monetary = len(ec.monetary_columns) > 0
        row_count = table_profile.row_count
        col_count = table_profile.column_count

        # CONFIG: very few rows
        if row_count <= _CONFIG_MAX_ROWS and row_count > 0:
            ec.entity_type = EntityType.CONFIG
            ec.confidence = 0.8
            ec.reasons.append(f"low row count ({row_count} <= {_CONFIG_MAX_ROWS})")

        # BRIDGE: few columns, most are FK-like
        elif col_count <= _BRIDGE_MAX_COLUMNS and ec.outbound_fk_count >= 2:
            fk_ratio = ec.outbound_fk_count / col_count if col_count > 0 else 0
            if fk_ratio >= _BRIDGE_MIN_FK_RATIO:
                ec.entity_type = EntityType.BRIDGE
                ec.confidence = 0.7
                ec.reasons.append(
                    f"low column count ({col_count}), "
                    f"{ec.outbound_fk_count} outbound FKs"
                )

        # TRANSACTIONAL: has dates + monetary + high row count
        elif has_temporal and has_monetary and row_count >= _TRANSACTIONAL_MIN_ROWS:
            ec.entity_type = EntityType.TRANSACTIONAL
            ec.confidence = 0.9
            ec.reasons.append("has temporal + monetary columns + high row count")

        # MASTER: referenced by others, moderate row count
        elif ec.inbound_fk_count >= 1:
            ec.entity_type = EntityType.MASTER
            ec.confidence = 0.7
            ec.reasons.append(f"referenced by {ec.inbound_fk_count} tables via FK")

        # Fallback: use heuristics
        elif has_temporal and row_count >= _TRANSACTIONAL_MIN_ROWS:
            ec.entity_type = EntityType.TRANSACTIONAL
            ec.confidence = 0.5
            ec.reasons.append("has temporal columns + high row count (no monetary)")

        else:
            ec.entity_type = EntityType.UNKNOWN
            ec.confidence = 0.3
            ec.reasons.append("no clear pattern detected")

        return ec

    def suggest_base_filter(self, table_profile: TableProfile) -> str | None:
        """
        Suggest a base_filter using the best discriminator column.
        Picks the discriminator whose top value has highest percentage.
        """
        if not table_profile.discriminators:
            return None

        best = max(
            table_profile.discriminators,
            key=lambda d: d.recommended_value_pct,
        )

        if best.recommended_value is None:
            return None

        # Format: column='value'
        return f"{best.column}='{best.recommended_value}'"

    def generate_entity_map(self, ontology: BusinessOntology) -> dict[str, Any]:
        """
        Generate an entity_map dict compatible with Cartographer format.
        This is the bridge between discovery and the existing pipeline.
        """
        entities = {}
        for table_name, ec in ontology.entities.items():
            entity = {
                "table": table_name,
                "type": ec.entity_type.value,
                "concept": ec.business_concept.value,
                "confidence": ec.confidence,
                "monetary_columns": ec.monetary_columns,
                "temporal_columns": ec.temporal_columns,
                "identifier_columns": ec.identifier_columns,
                "discriminators": ec.discriminators,
            }
            if ec.base_filter:
                entity["base_filter"] = ec.base_filter
            entities[table_name] = entity

        relationships = []
        for rel in ontology.relationships:
            relationships.append({
                "from": f"{rel['source_table']}.{rel['source_column']}",
                "to": f"{rel['target_table']}.{rel['target_column']}",
                "type": "fk",
                "score": rel.get("score", "0"),
            })

        return {
            "entities": entities,
            "relationships": relationships,
            "metadata": {
                "generated_by": "auto-discovery",
                "revenue_entities": ontology.revenue_entities,
                "customer_entities": ontology.customer_entities,
            },
        }

    # ─── Internal helpers ─────────────────────────────────────────────

    def _build_fk_graph(
        self, fk_candidates: list[FKCandidate],
    ) -> dict[str, dict[str, int]]:
        """Build inbound/outbound FK reference counts."""
        inbound: dict[str, int] = {}
        outbound: dict[str, int] = {}

        for fk in fk_candidates:
            inbound[fk.target_table] = inbound.get(fk.target_table, 0) + 1
            outbound[fk.source_table] = outbound.get(fk.source_table, 0) + 1

        return {"inbound": inbound, "outbound": outbound}

    def _infer_business_concepts(
        self,
        ontology: BusinessOntology,
        fk_candidates: list[FKCandidate],
    ) -> None:
        """Infer business concepts from entity types and FK relationships."""
        # Step 1: Find revenue entities (TRANSACTIONAL + monetary + temporal)
        for name, ec in ontology.entities.items():
            if ec.entity_type == EntityType.TRANSACTIONAL and ec.monetary_columns:
                ec.business_concept = BusinessConcept.REVENUE
                ontology.revenue_entities.append(name)
            elif ec.entity_type == EntityType.TRANSACTIONAL:
                ec.business_concept = BusinessConcept.GENERIC_TRANSACTION
            elif ec.entity_type == EntityType.BRIDGE:
                ec.business_concept = BusinessConcept.GENERIC_BRIDGE
            elif ec.entity_type == EntityType.CONFIG:
                ec.business_concept = BusinessConcept.GENERIC_CONFIG

        # Step 2: Find customer entities (MASTER + referenced by revenue entity)
        revenue_set = set(ontology.revenue_entities)
        for fk in fk_candidates:
            if fk.source_table in revenue_set:
                tgt = fk.target_table
                if tgt in ontology.entities:
                    tgt_ec = ontology.entities[tgt]
                    if tgt_ec.entity_type == EntityType.MASTER:
                        if tgt_ec.business_concept == BusinessConcept.UNKNOWN:
                            tgt_ec.business_concept = BusinessConcept.CUSTOMER
                            ontology.customer_entities.append(tgt)

        # Step 3: Remaining MASTER entities
        for name, ec in ontology.entities.items():
            if ec.entity_type == EntityType.MASTER and ec.business_concept == BusinessConcept.UNKNOWN:
                ec.business_concept = BusinessConcept.GENERIC_MASTER
