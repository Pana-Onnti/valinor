"""
Knowledge Graph — Data-driven schema understanding.

Builds a graph representation ENTIRELY from the Cartographer's entity_map.
Zero hardcoded ERP knowledge — all semantics come from:
  1. entity_map.entities[x].probed_values  (what the Cartographer sampled)
  2. entity_map.entities[x].base_filter    (what the Cartographer decided)
  3. entity_map.relationships              (what the Cartographer discovered)

This enables:
  - Automatic JOIN path reasoning via shortest-path (BFS)
  - Discriminator awareness from probed data (not hardcoded patterns)
  - Business concept generation from entity semantics
  - Anti-pattern detection (missing filters, wrong JOINs, ambiguous columns)
  - Source-agnostic: works with ANY entity_map regardless of ERP or data source

Architecture references:
  - SchemaGraphSQL (arXiv:2505.18363) — zero-shot schema linking via graph pathfinding
  - GAIT (PAKDD 2024) — data-driven semantic type detection
  - Palantir Foundry — ontology layer between raw data and analysis
"""

from __future__ import annotations

import heapq
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ColumnProfile:
    """Statistical profile of a single column, derived from probed_values."""
    name: str
    table: str
    distinct_count: int = 0
    top_values: list[dict] = field(default_factory=list)
    is_low_cardinality: bool = False  # <=10 distinct values → likely a discriminator
    in_base_filter: bool = False       # Cartographer included this in base_filter


@dataclass
class TableNode:
    """A table in the schema graph."""
    name: str
    entity_name: str = ""
    entity_type: str = ""
    row_count: int = 0
    columns: dict[str, ColumnProfile] = field(default_factory=dict)
    pk_columns: list[str] = field(default_factory=list)
    base_filter: str = ""  # As-is from entity_map — the Cartographer's decision
    filter_columns: list[str] = field(default_factory=list)  # Columns mentioned in base_filter


@dataclass
class FKEdge:
    """A foreign key relationship edge in the graph."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    cardinality: str = "N:1"
    confidence: float = 1.0  # 0.0-1.0: evidence strength for this relationship
    weight: float = 0.0      # Dijkstra weight: lower = preferred (auto-computed)

    def __post_init__(self):
        # Weight inversely proportional to confidence: prefer high-confidence paths
        if self.weight == 0.0:
            self.weight = max(0.01, 1.0 - self.confidence)


@dataclass
class JoinPath:
    """A resolved JOIN path between two tables."""
    tables: list[str]
    edges: list[FKEdge]
    total_weight: float = 0.0

    @property
    def hop_count(self) -> int:
        return len(self.edges)

    @property
    def sql_fragment(self) -> str:
        return "\n".join(
            f"JOIN {e.to_table} ON {e.from_table}.{e.from_column} = {e.to_table}.{e.to_column}"
            for e in self.edges
        )


@dataclass
class BusinessConcept:
    """A business concept derived from entity semantics."""
    name: str
    description: str
    primary_table: str
    required_tables: list[str] = field(default_factory=list)
    required_filters: list[str] = field(default_factory=list)
    source: str = "entity_map"


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA KNOWLEDGE GRAPH
# ═══════════════════════════════════════════════════════════════════════════


class SchemaKnowledgeGraph:
    """
    Graph-based schema understanding — 100% data-driven.

    All knowledge comes from the Cartographer's entity_map.
    No hardcoded ERP patterns, table names, or column semantics.
    """

    def __init__(self) -> None:
        self.tables: dict[str, TableNode] = {}
        self.edges: list[FKEdge] = []
        self._adjacency: dict[str, list[FKEdge]] = defaultdict(list)
        self._reverse_adjacency: dict[str, list[FKEdge]] = defaultdict(list)
        self.concepts: dict[str, BusinessConcept] = {}
        self._entity_to_table: dict[str, str] = {}  # "invoices" → "c_invoice"

    # ── BUILD FROM ENTITY MAP ──────────────────────────────────────────

    def build_from_entity_map(self, entity_map: dict) -> None:
        """
        Construct the knowledge graph from a Cartographer entity_map.

        Everything is derived from what the Cartographer discovered:
          - Tables/columns from entities
          - Discriminators from probed_values + base_filter
          - Relationships from the relationships list
          - Concepts from entity semantics (type, key_columns)
        """
        entities = entity_map.get("entities", {})
        relationships = entity_map.get("relationships", [])

        # Build table nodes
        for entity_name, entity in entities.items():
            table_name = entity.get("table", "")
            if not table_name:
                continue

            self._entity_to_table[entity_name] = table_name

            node = TableNode(
                name=table_name,
                entity_name=entity_name,
                entity_type=entity.get("type", "UNKNOWN"),
                row_count=entity.get("row_count", 0),
                pk_columns=self._extract_pk(entity),
                base_filter=entity.get("base_filter", ""),
            )

            # Extract which columns are in the base_filter
            if node.base_filter:
                node.filter_columns = self._extract_filter_columns(node.base_filter)

            # Build column profiles from key_columns
            for semantic_name, col_name in entity.get("key_columns", {}).items():
                node.columns[col_name] = ColumnProfile(name=col_name, table=table_name)

            # Build column profiles from probed_values (the Cartographer's sampling)
            probed = entity.get("probed_values", {})
            for col_name, values in probed.items():
                if col_name not in node.columns:
                    node.columns[col_name] = ColumnProfile(name=col_name, table=table_name)

                profile = node.columns[col_name]

                if isinstance(values, dict):
                    profile.top_values = [
                        {"value": str(k), "count": v} for k, v in values.items()
                    ]
                elif isinstance(values, list):
                    profile.top_values = values

                profile.distinct_count = len(profile.top_values)
                profile.is_low_cardinality = profile.distinct_count <= 10
                profile.in_base_filter = col_name in node.filter_columns

            self.tables[table_name] = node

        # Build FK edges from relationships
        for rel in relationships:
            from_entity = rel.get("from", "")
            to_entity = rel.get("to", "")
            via_col = rel.get("via", "")
            cardinality = rel.get("cardinality", "N:1")
            # Accept confidence from FK discovery (if available)
            confidence = float(rel.get("confidence", 1.0))

            from_table = entities.get(from_entity, {}).get("table", "")
            to_table = entities.get(to_entity, {}).get("table", "")

            if not from_table or not to_table or not via_col:
                continue

            to_pk = self._get_pk_for_fk(entities.get(to_entity, {}), via_col)

            edge = FKEdge(
                from_table=from_table,
                from_column=via_col,
                to_table=to_table,
                to_column=to_pk or via_col,
                cardinality=cardinality,
                confidence=confidence,
            )

            self.edges.append(edge)
            self._adjacency[from_table].append(edge)
            self._reverse_adjacency[to_table].append(edge)

        # Auto-generate business concepts from entity semantics
        self._generate_concepts(entities)

        logger.info(
            "Knowledge graph built",
            tables=len(self.tables),
            edges=len(self.edges),
            concepts=len(self.concepts),
            filter_columns=sum(len(t.filter_columns) for t in self.tables.values()),
        )

    # ── JOIN PATH REASONING ────────────────────────────────────────────

    def find_join_path(self, from_table: str, to_table: str) -> JoinPath | None:
        """
        Find the optimal JOIN path between two tables using Dijkstra.

        Uses confidence-weighted edges: high-confidence FK relationships
        are preferred over speculative ones. This is the core
        anti-hallucination mechanism for JOINs.

        Weight = 1 - confidence, so high-confidence edges have low weight.
        """
        if from_table == to_table:
            return JoinPath(tables=[from_table], edges=[], total_weight=0)

        # Dijkstra with (cost, counter, current_table, path)
        # counter breaks ties deterministically
        counter = 0
        dist: dict[str, float] = {from_table: 0.0}
        heap: list[tuple[float, int, str, list[FKEdge]]] = [(0.0, counter, from_table, [])]

        while heap:
            cost, _, current, path = heapq.heappop(heap)

            if current == to_table:
                return self._build_join_path(from_table, path)

            if cost > dist.get(current, float("inf")):
                continue

            # Forward edges
            for edge in self._adjacency.get(current, []):
                neighbor = edge.to_table
                new_cost = cost + edge.weight
                if new_cost < dist.get(neighbor, float("inf")):
                    dist[neighbor] = new_cost
                    counter += 1
                    heapq.heappush(heap, (new_cost, counter, neighbor, path + [edge]))

            # Reverse edges
            for edge in self._reverse_adjacency.get(current, []):
                neighbor = edge.from_table
                new_cost = cost + edge.weight
                if new_cost < dist.get(neighbor, float("inf")):
                    dist[neighbor] = new_cost
                    counter += 1
                    heapq.heappush(heap, (new_cost, counter, neighbor, path + [edge]))

        return None

    # ── FILTER & COLUMN REASONING ──────────────────────────────────────

    def get_required_filters(self, table_name: str, context: str = "") -> list[str]:
        """
        Return the filter fragments the Cartographer defined for this table.

        These come directly from entity.base_filter — no hardcoded logic.
        The Cartographer already decided what filters are needed based on
        its Phase 1 pre-scan + Phase 2 analysis.
        """
        node = self.tables.get(table_name)
        if not node or not node.base_filter:
            return []

        # Parse base_filter into individual fragments, qualified with table name
        return self._qualify_filter(node.base_filter, table_name)

    def get_ambiguous_columns(self, tables: list[str]) -> dict[str, list[str]]:
        """
        Find columns that appear in multiple tables being joined.
        Every column in the result MUST be table-qualified in SQL.
        """
        col_tables: dict[str, list[str]] = defaultdict(list)

        for table_name in tables:
            node = self.tables.get(table_name)
            if not node:
                continue
            for col_name in node.columns:
                col_tables[col_name].append(table_name)

        return {col: tbls for col, tbls in col_tables.items() if len(tbls) > 1}

    def get_filter_columns_for_table(self, table_name: str) -> list[str]:
        """Return columns that the Cartographer included in base_filter."""
        node = self.tables.get(table_name)
        return node.filter_columns if node else []

    def get_low_cardinality_columns(self, table_name: str) -> list[ColumnProfile]:
        """
        Return columns with <=10 distinct values (from probed_values).
        These are likely discriminators that should appear in WHERE clauses.
        """
        node = self.tables.get(table_name)
        if not node:
            return []
        return [p for p in node.columns.values() if p.is_low_cardinality]

    # ── QUERY VALIDATION ───────────────────────────────────────────────

    def validate_query(self, sql: str, tables_used: list[str]) -> list[dict]:
        """
        Validate a SQL query against the knowledge graph.

        Checks (all data-driven, no hardcoded column names):
          1. Missing filter columns: Cartographer said this table needs base_filter,
             but the query doesn't reference those columns
          2. Ambiguous column references in multi-table queries
        """
        issues = []
        sql_lower = sql.lower()

        # 1. Missing filter columns
        for table_name in tables_used:
            node = self.tables.get(table_name)
            if not node:
                continue

            for filter_col in node.filter_columns:
                if filter_col.lower() not in sql_lower:
                    # The Cartographer said this column should be in the filter,
                    # but the query doesn't reference it
                    col_profile = node.columns.get(filter_col)
                    values_hint = ""
                    if col_profile and col_profile.top_values:
                        values_hint = ", ".join(
                            f"{v['value']}={v['count']}" for v in col_profile.top_values[:5]
                        )

                    issues.append({
                        "type": "MISSING_FILTER_COLUMN",
                        "severity": "critical" if col_profile and col_profile.is_low_cardinality else "warning",
                        "table": table_name,
                        "column": filter_col,
                        "probed_values": values_hint,
                        "fix": f"Add WHERE {table_name}.{filter_col} = '<value>' "
                               f"(Cartographer base_filter: {node.base_filter})",
                    })

        # 2. Ambiguous columns in multi-table queries
        if len(tables_used) > 1:
            ambiguous = self.get_ambiguous_columns(tables_used)
            for col, tbls in ambiguous.items():
                bare_pattern = re.compile(
                    rf'(?<![.\w]){re.escape(col)}(?![.\w])', re.IGNORECASE
                )
                qualified_pattern = re.compile(
                    rf'\w+\.{re.escape(col)}', re.IGNORECASE
                )
                if bare_pattern.search(sql) and not qualified_pattern.search(sql):
                    issues.append({
                        "type": "AMBIGUOUS_COLUMN",
                        "severity": "critical",
                        "column": col,
                        "tables": tbls,
                        "fix": f"Qualify '{col}' with table name: {tbls[0]}.{col}",
                    })

        return issues

    # ── BUSINESS CONCEPTS ──────────────────────────────────────────────

    def get_concept(self, name: str) -> BusinessConcept | None:
        return self.concepts.get(name)

    def get_all_concepts(self) -> dict[str, BusinessConcept]:
        return self.concepts

    # ── PROMPT CONTEXT ─────────────────────────────────────────────────

    def to_prompt_context(self) -> str:
        """
        Serialize the knowledge graph for injection into agent prompts.

        Replaces raw schema dumps with semantically enriched context
        that includes filter requirements and JOIN paths.
        """
        lines = ["## SCHEMA KNOWLEDGE GRAPH\n"]

        lines.append("### Tables & Required Filters (from Cartographer)")
        for table_name, node in self.tables.items():
            filter_info = f" — FILTER: {node.base_filter}" if node.base_filter else ""
            lines.append(f"- **{table_name}** ({node.entity_name}, {node.entity_type})"
                         f"{filter_info}")

            # Show low-cardinality columns with their values
            for col in node.columns.values():
                if col.is_low_cardinality and col.top_values:
                    vals = ", ".join(f"{v['value']}={v['count']}" for v in col.top_values[:5])
                    marker = " [IN FILTER]" if col.in_base_filter else ""
                    lines.append(f"  - {col.name}: [{vals}]{marker}")

        lines.append("\n### JOIN Paths (confidence-weighted Dijkstra)")
        shown = set()
        for edge in self.edges:
            pair = (edge.from_table, edge.to_table)
            if pair not in shown:
                conf_tag = f" [conf={edge.confidence:.0%}]" if edge.confidence < 1.0 else ""
                lines.append(
                    f"- {edge.from_table}.{edge.from_column} → "
                    f"{edge.to_table}.{edge.to_column} ({edge.cardinality}){conf_tag}"
                )
                shown.add(pair)

        if self.concepts:
            lines.append("\n### Business Concepts")
            for name, concept in self.concepts.items():
                filters = ", ".join(concept.required_filters) if concept.required_filters else "none"
                lines.append(f"- **{name}**: {concept.description}")
                lines.append(f"  Tables: {', '.join(concept.required_tables)} | Filters: {filters}")

        return "\n".join(lines)

    # ── PRIVATE HELPERS ────────────────────────────────────────────────

    def _extract_pk(self, entity: dict) -> list[str]:
        key_cols = entity.get("key_columns", {})
        for key in ("pk", "invoice_pk", "customer_pk", "order_pk", "payment_pk"):
            if key in key_cols:
                return [key_cols[key]]
        return []

    def _get_pk_for_fk(self, entity: dict, fk_col: str) -> str | None:
        key_cols = entity.get("key_columns", {})
        for key in ("pk", "customer_pk", "invoice_pk", "order_pk"):
            if key in key_cols:
                return key_cols[key]
        return fk_col

    def _extract_filter_columns(self, base_filter: str) -> list[str]:
        """
        Extract column names referenced in a base_filter string.

        "issotrx='Y' AND docstatus='CO'" → ["issotrx", "docstatus"]
        "move_type IN ('out_invoice') AND state='posted'" → ["move_type", "state"]
        """
        cols = []
        # Match: column_name followed by operator (=, <, >, !, IN, BETWEEN, LIKE, IS)
        for match in re.finditer(r'(\w+)\s*(?:[=<>!]+|IN\s*\(|BETWEEN\b|LIKE\b|IS\b)', base_filter, re.IGNORECASE):
            col = match.group(1)
            # Skip SQL keywords
            if col.upper() in ("AND", "OR", "NOT", "WHERE", "NULL",
                                "TRUE", "FALSE", "CURRENT_DATE", "CASE", "WHEN", "THEN"):
                continue
            # Skip already-qualified (table.col)
            if "." in col:
                col = col.split(".")[-1]
            if col not in cols:
                cols.append(col)
        return cols

    def _qualify_filter(self, base_filter: str, table_name: str) -> list[str]:
        """Ensure all column references in a base_filter are table-qualified."""
        fragments = []
        parts = re.split(r'\bAND\b', base_filter, flags=re.IGNORECASE)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if "." not in part.split("=")[0].split("<")[0].split(">")[0]:
                part = f"{table_name}.{part}"
            fragments.append(part)
        return fragments

    def _build_join_path(self, start_table: str, edges: list[FKEdge]) -> JoinPath:
        tables = [start_table]
        for edge in edges:
            next_table = edge.to_table if edge.from_table in tables else edge.from_table
            if next_table not in tables:
                tables.append(next_table)
        return JoinPath(
            tables=tables,
            edges=edges,
            total_weight=sum(e.weight for e in edges),
        )

    def _generate_concepts(self, entities: dict) -> None:
        """
        Auto-generate business concepts from entity semantics.

        Uses entity type + base_filter to infer what each entity represents.
        No hardcoded ERP knowledge — the Cartographer already classified
        entities and set their filters.
        """
        for entity_name, entity in entities.items():
            table = entity.get("table", "")
            etype = entity.get("type", "")
            base_filter = entity.get("base_filter", "")
            key_cols = entity.get("key_columns", {})

            if not table:
                continue

            # Every entity with a base_filter gets a concept
            # "To query <entity_name>, you MUST apply these filters"
            if base_filter:
                filters = self._qualify_filter(base_filter, table)
                self.concepts[f"{entity_name}_filtered"] = BusinessConcept(
                    name=f"{entity_name}_filtered",
                    description=f"Query {entity_name} ({table}) with required filters: {base_filter}",
                    primary_table=table,
                    required_tables=[table],
                    required_filters=filters,
                )

            # TRANSACTIONAL entities with amount columns get revenue/total concepts
            amount_col = key_cols.get("amount_col") or key_cols.get("grand_total") or key_cols.get("amount")
            if etype == "TRANSACTIONAL" and amount_col:
                filters = self._qualify_filter(base_filter, table) if base_filter else []
                self.concepts[f"{entity_name}_total"] = BusinessConcept(
                    name=f"{entity_name}_total",
                    description=f"SUM({amount_col}) from {entity_name} with filters applied",
                    primary_table=table,
                    required_tables=[table],
                    required_filters=filters,
                )

            # Entities that need cross-table filtering
            # (e.g., payment_schedule needs invoice for direction)
            # Detect this by checking if base_filter references columns
            # that DON'T exist in this entity's key_columns
            if base_filter:
                filter_cols = self._extract_filter_columns(base_filter)
                own_cols = set(key_cols.values()) | set(key_cols.keys())
                # Also include probed columns
                own_cols.update(entity.get("probed_values", {}).keys())
                missing_filter_cols = [c for c in filter_cols if c not in own_cols]
                if missing_filter_cols:
                    # This entity's filter references columns it doesn't have
                    # → needs a JOIN to another table to apply the filter
                    self.concepts[f"{entity_name}_needs_join"] = BusinessConcept(
                        name=f"{entity_name}_needs_join",
                        description=(
                            f"{entity_name} filter references columns not in this table: "
                            f"{missing_filter_cols}. Must JOIN to the table that has them."
                        ),
                        primary_table=table,
                        required_tables=[table],
                        required_filters=filters if base_filter else [],
                    )


def build_knowledge_graph(entity_map: dict) -> SchemaKnowledgeGraph:
    """Convenience function: build and return a populated knowledge graph."""
    kg = SchemaKnowledgeGraph()
    kg.build_from_entity_map(entity_map)
    return kg
