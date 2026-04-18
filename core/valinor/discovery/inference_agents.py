"""
Multi-Agent Inference + Ensemble Evaluator for FK Discovery.

Four agents analyze a database schema from different perspectives:
  A. StructuralAgent  — deterministic, 0 LLM: explicit FKs + name patterns
  B. SemanticAgent    — 1 LLM call (Haiku): column semantic types + joinable pairs
  C. DomainAgent      — deterministic, 0 LLM: hint pack pattern matching
  D. BusinessProcessAgent — 1 LLM call (Haiku): business process flow inference

An EnsembleEvaluator merges their outputs by consensus.

References:
  - SchemaGraphSQL (arXiv:2505.18363) — schema linking via graph pathfinding
  - GAIT (PAKDD 2024) — data-driven semantic type detection
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Optional, Protocol

from pydantic import BaseModel, Field

from valinor.discovery.schema_extractor import (
    ColumnTypeCategory,
    FKRelation,
    SchemaProfile,
    TableInfo,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# SHARED TYPES
# ═══════════════════════════════════════════════════════════════════════════


class RelationCandidate(BaseModel):
    """A candidate FK relationship proposed by one inference agent."""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    perspective: str  # "structural", "semantic", "domain", "process"


class EvaluatedRelation(BaseModel):
    """A relation that has been evaluated by the ensemble."""
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    confidence: float
    consensus: int  # how many perspectives agreed (1-4)
    evidence: list[str]
    perspectives: list[str]


# ═══════════════════════════════════════════════════════════════════════════
# LLM INTERFACE (mockable)
# ═══════════════════════════════════════════════════════════════════════════


class LLMClient(Protocol):
    """Protocol for LLM calls — real Anthropic or mock."""
    async def complete(self, prompt: str, system: str = "") -> str: ...


class MockLLMClient:
    """Mock LLM that returns empty JSON for testing without API keys."""

    def __init__(self, responses: Optional[dict[str, str]] = None):
        self._responses = responses or {}

    async def complete(self, prompt: str, system: str = "") -> str:
        # Check if any key in responses matches a substring of the prompt
        for key, response in self._responses.items():
            if key in prompt:
                return response
        return "[]"


# ═══════════════════════════════════════════════════════════════════════════
# AGENT A: STRUCTURAL (deterministic, 0 LLM)
# ═══════════════════════════════════════════════════════════════════════════


class StructuralAgent:
    """
    Extracts FK relationships from schema structure alone.

    1. Explicit FKs from SchemaProfile (confidence 1.0)
    2. Name pattern matching: {table}_id, cod_{table}, id_{table} (0.5-0.7)
    3. Type compatibility bonus (+0.1)
    4. PK candidate matching: same distinct count as PK of another table
    """

    PERSPECTIVE = "structural"

    # Common FK column name patterns: (regex, base_confidence)
    _FK_PATTERNS: list[tuple[str, float]] = [
        (r"^(.+)_id$", 0.6),           # {table}_id
        (r"^cod_(.+)$", 0.6),           # cod_{table}
        (r"^id_(.+)$", 0.6),            # id_{table}
        (r"^cod(.+)$", 0.5),            # Cod{Table} (no separator)
        (r"^id(.+)$", 0.5),             # Id{Table} (no separator)
        (r"^fk_(.+)$", 0.7),            # fk_{table}
        (r"^(.+)_cod$", 0.5),           # {table}_cod
    ]

    def infer(self, schema: SchemaProfile) -> list[RelationCandidate]:
        candidates: list[RelationCandidate] = []
        table_names_lower = {t.name.lower(): t.name for t in schema.tables}

        # 1. Explicit FKs
        for table in schema.tables:
            for fk in table.fks:
                for src_col, tgt_col in zip(fk.source_columns, fk.target_columns):
                    candidates.append(RelationCandidate(
                        source_table=fk.source_table,
                        source_column=src_col,
                        target_table=fk.target_table,
                        target_column=tgt_col,
                        confidence=1.0,
                        evidence=f"Explicit FK constraint: {fk.name or 'unnamed'}",
                        perspective=self.PERSPECTIVE,
                    ))

        # 2. Name pattern matching
        for table in schema.tables:
            for col in table.columns:
                col_lower = col.name.lower()
                for pattern, base_conf in self._FK_PATTERNS:
                    match = re.match(pattern, col_lower, re.IGNORECASE)
                    if not match:
                        continue
                    ref_name = match.group(1).lower()
                    # Try to match ref_name against table names
                    target_table_name = self._find_target_table(
                        ref_name, table_names_lower, table.name,
                    )
                    if not target_table_name:
                        continue

                    # Find the PK column of target table
                    target_table = next(
                        (t for t in schema.tables if t.name == target_table_name),
                        None,
                    )
                    if not target_table:
                        continue

                    target_pk_col = self._get_pk_column(target_table)
                    if not target_pk_col:
                        continue

                    # Skip if this is already an explicit FK
                    if self._is_explicit_fk(table, col.name, target_table_name):
                        continue

                    conf = base_conf
                    # Type compatibility bonus
                    target_col_info = next(
                        (c for c in target_table.columns if c.name == target_pk_col),
                        None,
                    )
                    if target_col_info and col.type_category == target_col_info.type_category:
                        conf = min(1.0, conf + 0.1)

                    candidates.append(RelationCandidate(
                        source_table=table.name,
                        source_column=col.name,
                        target_table=target_table_name,
                        target_column=target_pk_col,
                        confidence=conf,
                        evidence=f"Name pattern: {col.name} matches pattern for table {target_table_name}",
                        perspective=self.PERSPECTIVE,
                    ))

        # 3. PK candidate matching (distinct count comparison)
        pk_distinct: dict[str, dict[str, int]] = {}
        for table in schema.tables:
            pk_col_name = self._get_pk_column(table)
            if pk_col_name:
                pk_info = next((c for c in table.columns if c.name == pk_col_name), None)
                if pk_info and pk_info.distinct_count > 0:
                    pk_distinct[table.name] = {
                        "column": pk_col_name,
                        "distinct": pk_info.distinct_count,
                    }

        for table in schema.tables:
            for col in table.columns:
                if col.distinct_count <= 0:
                    continue
                if col.type_category not in (
                    ColumnTypeCategory.NUMERIC, ColumnTypeCategory.ID,
                    ColumnTypeCategory.TEXT,
                ):
                    continue
                for target_name, pk_info in pk_distinct.items():
                    if target_name == table.name:
                        continue
                    if col.distinct_count == pk_info["distinct"] and col.distinct_count > 1:
                        # Skip if already found
                        key = (table.name, col.name, target_name, pk_info["column"])
                        if any(
                            (c.source_table, c.source_column, c.target_table, c.target_column) == key
                            for c in candidates
                        ):
                            continue
                        candidates.append(RelationCandidate(
                            source_table=table.name,
                            source_column=col.name,
                            target_table=target_name,
                            target_column=pk_info["column"],
                            confidence=0.4,
                            evidence=(
                                f"PK candidate match: {col.name} distinct_count="
                                f"{col.distinct_count} matches PK {pk_info['column']} "
                                f"of {target_name}"
                            ),
                            perspective=self.PERSPECTIVE,
                        ))

        return candidates

    def _find_target_table(
        self, ref_name: str, table_names_lower: dict[str, str], source_table: str,
    ) -> str | None:
        """Find a table whose name matches the reference extracted from a column name."""
        if ref_name in table_names_lower and table_names_lower[ref_name] != source_table:
            return table_names_lower[ref_name]
        # Try plural/singular variants
        for suffix in ("s", "es"):
            plural = ref_name + suffix
            if plural in table_names_lower and table_names_lower[plural] != source_table:
                return table_names_lower[plural]
            if ref_name.endswith(suffix):
                singular = ref_name[: -len(suffix)]
                if singular in table_names_lower and table_names_lower[singular] != source_table:
                    return table_names_lower[singular]
        return None

    def _get_pk_column(self, table: TableInfo) -> str | None:
        """Get the primary key column name (single-column PKs only)."""
        if table.pk and table.pk.columns and len(table.pk.columns) == 1:
            return table.pk.columns[0]
        # Fallback: first PK candidate
        if table.pk_candidates:
            return table.pk_candidates[0].column
        return None

    def _is_explicit_fk(self, table: TableInfo, col_name: str, target_table: str) -> bool:
        """Check if this column is already declared as an FK to the target table."""
        for fk in table.fks:
            if col_name in fk.source_columns and fk.target_table == target_table:
                return True
        return False


# ═══════════════════════════════════════════════════════════════════════════
# AGENT B: SEMANTIC (1 LLM call, Haiku)
# ═══════════════════════════════════════════════════════════════════════════


class SemanticAgent:
    """
    Uses an LLM to annotate columns with semantic types and find joinable pairs.

    Sends ALL tables + columns + sample data → asks for:
      1. Semantic entity type per column
      2. Joinable column pairs with business justification
    """

    PERSPECTIVE = "semantic"

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def infer(
        self, schema: SchemaProfile, samples: Optional[dict[str, list]] = None,
    ) -> list[RelationCandidate]:
        prompt = self._build_prompt(schema, samples)
        try:
            response = await self._llm.complete(
                prompt=prompt,
                system=(
                    "You are a database schema analyst. Analyze the schema and identify "
                    "joinable column pairs. Respond ONLY with a JSON array."
                ),
            )
            return self._parse_response(response)
        except Exception as exc:
            logger.warning("SemanticAgent LLM call failed: %s", exc)
            return []

    def _build_prompt(
        self, schema: SchemaProfile, samples: Optional[dict[str, list]] = None,
    ) -> str:
        lines = ["Analyze this database schema and identify joinable column pairs.\n"]
        lines.append("## Tables and Columns\n")

        for table in schema.tables:
            cols_desc = ", ".join(
                f"{c.name} ({c.sql_type}, {c.type_category.value})"
                for c in table.columns
            )
            lines.append(f"### {table.name} ({table.row_count} rows)")
            lines.append(f"  PK: {table.pk.columns if table.pk else 'none'}")
            lines.append(f"  Columns: {cols_desc}")

            if samples and table.name in samples:
                sample_rows = samples[table.name][:3]
                if sample_rows:
                    lines.append(f"  Sample: {json.dumps(sample_rows, default=str)[:500]}")
            lines.append("")

        lines.append(
            "Respond with a JSON array of objects, each with:\n"
            '  {"source_table": "...", "source_column": "...", '
            '"target_table": "...", "target_column": "...", '
            '"confidence": 0.0-0.85, "evidence": "..."}\n'
            "Only include pairs you are confident about. Max confidence 0.85."
        )

        return "\n".join(lines)

    def _parse_response(self, response: str) -> list[RelationCandidate]:
        candidates: list[RelationCandidate] = []
        # Extract JSON array from response
        try:
            # Try to find JSON array in response
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group())
        except (json.JSONDecodeError, AttributeError):
            logger.warning("SemanticAgent: failed to parse LLM JSON response")
            return []

        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                conf = float(item.get("confidence", 0.5))
                conf = max(0.4, min(0.85, conf))  # clamp
                candidates.append(RelationCandidate(
                    source_table=item["source_table"],
                    source_column=item["source_column"],
                    target_table=item["target_table"],
                    target_column=item["target_column"],
                    confidence=conf,
                    evidence=item.get("evidence", "Semantic analysis"),
                    perspective=self.PERSPECTIVE,
                ))
            except (KeyError, ValueError) as exc:
                logger.debug("SemanticAgent: skipping malformed item: %s", exc)
                continue

        return candidates


# ═══════════════════════════════════════════════════════════════════════════
# AGENT C: DOMAIN (deterministic, 0 LLM, hint pack)
# ═══════════════════════════════════════════════════════════════════════════


class DomainAgent:
    """
    Uses ERP hint pack to match naming conventions and detect patterns.

    - Match naming conventions against schema columns
    - Detect header/detail patterns (CompCab/CompDet, Cab*/Det*)
    - Match fiscal patterns (CUIT, CondIVA, etc.)
    - Confidence based on pattern specificity
    """

    PERSPECTIVE = "domain"

    def infer(
        self, schema: SchemaProfile, hint_pack: Optional[dict] = None,
    ) -> list[RelationCandidate]:
        if not hint_pack:
            return []

        candidates: list[RelationCandidate] = []
        table_names = {t.name for t in schema.tables}
        table_names_lower = {t.name.lower(): t.name for t in schema.tables}

        # 1. Header/Detail pattern detection
        candidates.extend(
            self._detect_header_detail(schema, hint_pack, table_names_lower)
        )

        # 2. Master table FK patterns from naming conventions
        candidates.extend(
            self._detect_master_fks(schema, hint_pack, table_names_lower)
        )

        return candidates

    def _detect_header_detail(
        self,
        schema: SchemaProfile,
        hint_pack: dict,
        table_names_lower: dict[str, str],
    ) -> list[RelationCandidate]:
        """Detect header/detail table pairs using hint pack patterns."""
        candidates: list[RelationCandidate] = []
        table_patterns = hint_pack.get("table_patterns", {})
        hd_config = table_patterns.get("header_detail", {})

        header_suffixes = hd_config.get("header_suffixes", [])
        detail_suffixes = hd_config.get("detail_suffixes", [])

        if not header_suffixes or not detail_suffixes:
            return []

        # Find header/detail pairs
        for table in schema.tables:
            tname = table.name
            for h_suffix in header_suffixes:
                if not tname.endswith(h_suffix) and h_suffix.lower() not in tname.lower():
                    continue

                # Extract the base name
                if tname.endswith(h_suffix):
                    base = tname[: -len(h_suffix)]
                elif tname.lower().endswith(h_suffix.lower()):
                    base = tname[: -len(h_suffix)]
                else:
                    continue

                if not base:
                    continue

                # Look for matching detail table
                for d_suffix in detail_suffixes:
                    detail_name = base + d_suffix
                    if detail_name.lower() in table_names_lower:
                        actual_detail = table_names_lower[detail_name.lower()]
                        # Find the linking column (usually the PK of header)
                        header_pk = self._get_pk_column(table)
                        if header_pk:
                            # Check if detail table has a matching column
                            detail_table = next(
                                (t for t in schema.tables if t.name == actual_detail),
                                None,
                            )
                            if detail_table:
                                link_col = self._find_link_column(
                                    detail_table, header_pk, tname,
                                )
                                if link_col:
                                    candidates.append(RelationCandidate(
                                        source_table=actual_detail,
                                        source_column=link_col,
                                        target_table=tname,
                                        target_column=header_pk,
                                        confidence=0.8,
                                        evidence=(
                                            f"Header/detail pattern: {tname} (header) "
                                            f"↔ {actual_detail} (detail)"
                                        ),
                                        perspective=self.PERSPECTIVE,
                                    ))

        return candidates

    def _detect_master_fks(
        self,
        schema: SchemaProfile,
        hint_pack: dict,
        table_names_lower: dict[str, str],
    ) -> list[RelationCandidate]:
        """Detect FK patterns from naming conventions (id_prefixes, id_suffixes)."""
        candidates: list[RelationCandidate] = []
        naming = hint_pack.get("naming_conventions", {})
        id_prefixes = naming.get("id_prefixes", [])
        id_suffixes = naming.get("id_suffixes", [])

        # Build a map of master tables from hint pack
        table_patterns = hint_pack.get("table_patterns", {})
        master_tables = table_patterns.get("master_tables", [])

        # Map entity patterns to actual table names
        entity_to_table: dict[str, str] = {}
        for mt in master_tables:
            pattern = mt.get("pattern", "")
            if not pattern:
                continue
            # Convert glob pattern to match: "Articulo*" -> matches "Articulos", "Articulo"
            base = pattern.rstrip("*").lower()
            for tname_lower, tname in table_names_lower.items():
                if tname_lower.startswith(base):
                    entity_to_table[base] = tname

        # For each table, check if columns reference known master tables
        for table in schema.tables:
            for col in table.columns:
                col_lower = col.name.lower()
                for base_name, master_table_name in entity_to_table.items():
                    if master_table_name == table.name:
                        continue  # Skip self-references
                    # Check if column name contains the master table base
                    matched = False
                    for prefix in id_prefixes:
                        # e.g., CodCliente, IdArticulo
                        test = (prefix + base_name).lower()
                        # Handle partial matches like "codcliente" matching "cliente"
                        if col_lower == test or col_lower.startswith(test):
                            matched = True
                            break
                    if not matched:
                        for suffix in id_suffixes:
                            # e.g., cliente_id, articulo_cod
                            test = (base_name + suffix).lower()
                            if col_lower == test:
                                matched = True
                                break

                    if matched:
                        master_table_info = next(
                            (t for t in schema.tables if t.name == master_table_name),
                            None,
                        )
                        if not master_table_info:
                            continue
                        pk_col = self._get_pk_column(master_table_info)
                        if not pk_col:
                            continue
                        candidates.append(RelationCandidate(
                            source_table=table.name,
                            source_column=col.name,
                            target_table=master_table_name,
                            target_column=pk_col,
                            confidence=0.7,
                            evidence=(
                                f"Domain naming convention: {col.name} matches "
                                f"master table {master_table_name} pattern"
                            ),
                            perspective=self.PERSPECTIVE,
                        ))

        return candidates

    def _get_pk_column(self, table: TableInfo) -> str | None:
        if table.pk and table.pk.columns and len(table.pk.columns) == 1:
            return table.pk.columns[0]
        if table.pk_candidates:
            return table.pk_candidates[0].column
        return None

    def _find_link_column(
        self, detail_table: TableInfo, header_pk: str, header_name: str,
    ) -> str | None:
        """Find the column in detail table that links to header's PK."""
        col_names = [c.name for c in detail_table.columns]

        # Direct match: detail has same column name as header PK
        if header_pk in col_names:
            return header_pk

        # Pattern: header_pk named "Id" or "NroComp" → detail might have same
        header_lower = header_name.lower()
        for col_name in col_names:
            cl = col_name.lower()
            # e.g., detail has "CompCab_id" or "idCompcab"
            if header_lower in cl and ("id" in cl or "cod" in cl or "nro" in cl):
                return col_name

        return None


# ═══════════════════════════════════════════════════════════════════════════
# AGENT D: BUSINESS PROCESS (1 LLM call, Haiku)
# ═══════════════════════════════════════════════════════════════════════════


class BusinessProcessAgent:
    """
    Uses LLM to infer business process flow and table relationships.

    Sends table names + business context → asks for:
      1. Business process flow
      2. Table-to-table relationships based on process logic
    """

    PERSPECTIVE = "process"

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    async def infer(
        self,
        schema: SchemaProfile,
        business_context: Optional[dict] = None,
    ) -> list[RelationCandidate]:
        prompt = self._build_prompt(schema, business_context)
        try:
            response = await self._llm.complete(
                prompt=prompt,
                system=(
                    "You are a business process analyst. Analyze database tables "
                    "and infer business relationships. Respond ONLY with a JSON array."
                ),
            )
            return self._parse_response(response)
        except Exception as exc:
            logger.warning("BusinessProcessAgent LLM call failed: %s", exc)
            return []

    def _build_prompt(
        self,
        schema: SchemaProfile,
        business_context: Optional[dict] = None,
    ) -> str:
        lines = [
            "Analyze these database tables and infer business process relationships.\n"
        ]

        if business_context:
            lines.append("## Business Context")
            for key, val in business_context.items():
                if val:
                    lines.append(f"  {key}: {val}")
            lines.append("")

        lines.append("## Tables\n")
        for table in schema.tables:
            cols = ", ".join(c.name for c in table.columns[:20])
            lines.append(f"- {table.name} ({table.row_count} rows): [{cols}]")

        lines.append(
            "\nInfer which tables are related through business processes. "
            "For example: orders reference customers, order details reference "
            "both orders and products.\n\n"
            "Respond with a JSON array of objects:\n"
            '  {"source_table": "...", "source_column": "...", '
            '"target_table": "...", "target_column": "...", '
            '"confidence": 0.3-0.7, "evidence": "..."}\n'
            "Max confidence 0.7. Only include relationships you can justify."
        )

        return "\n".join(lines)

    def _parse_response(self, response: str) -> list[RelationCandidate]:
        candidates: list[RelationCandidate] = []
        try:
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if not match:
                return []
            data = json.loads(match.group())
        except (json.JSONDecodeError, AttributeError):
            logger.warning("BusinessProcessAgent: failed to parse LLM JSON response")
            return []

        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                conf = float(item.get("confidence", 0.5))
                conf = max(0.3, min(0.7, conf))  # clamp
                candidates.append(RelationCandidate(
                    source_table=item["source_table"],
                    source_column=item["source_column"],
                    target_table=item["target_table"],
                    target_column=item["target_column"],
                    confidence=conf,
                    evidence=item.get("evidence", "Business process analysis"),
                    perspective=self.PERSPECTIVE,
                ))
            except (KeyError, ValueError) as exc:
                logger.debug("BusinessProcessAgent: skipping malformed item: %s", exc)
                continue

        return candidates


# ═══════════════════════════════════════════════════════════════════════════
# ENSEMBLE EVALUATOR (deterministic, 0 LLM)
# ═══════════════════════════════════════════════════════════════════════════


class EnsembleEvaluator:
    """
    Merges RelationCandidates from multiple agents by consensus.

    Grouping: normalize (source_table.source_column, target_table.target_column)
    Consensus-based confidence:
      4 perspectives agree -> 0.95
      3 perspectives -> max_confidence * 0.95
      2 perspectives -> max_confidence * 0.85
      1 perspective  -> confidence * 0.7
    """

    def evaluate(
        self, candidates_per_agent: list[list[RelationCandidate]],
    ) -> list[EvaluatedRelation]:
        # Flatten all candidates
        all_candidates: list[RelationCandidate] = []
        for agent_candidates in candidates_per_agent:
            all_candidates.extend(agent_candidates)

        # Group by normalized key
        groups: dict[tuple[str, str, str, str], list[RelationCandidate]] = {}
        for c in all_candidates:
            key = self._normalize_key(c)
            groups.setdefault(key, []).append(c)

        results: list[EvaluatedRelation] = []
        for key, group in groups.items():
            perspectives = list({c.perspective for c in group})
            consensus = len(perspectives)
            max_conf = max(c.confidence for c in group)
            evidence = list({c.evidence for c in group})

            if consensus >= 4:
                final_conf = 0.95
            elif consensus == 3:
                final_conf = max_conf * 0.95
            elif consensus == 2:
                final_conf = max_conf * 0.85
            else:
                final_conf = max_conf * 0.7

            # Cap at 1.0
            final_conf = min(1.0, round(final_conf, 4))

            results.append(EvaluatedRelation(
                source_table=key[0],
                source_column=key[1],
                target_table=key[2],
                target_column=key[3],
                confidence=final_conf,
                consensus=consensus,
                evidence=evidence,
                perspectives=sorted(perspectives),
            ))

        # Sort by confidence descending, then by consensus descending
        results.sort(key=lambda r: (-r.confidence, -r.consensus))
        return results

    def _normalize_key(
        self, c: RelationCandidate,
    ) -> tuple[str, str, str, str]:
        """Normalize table/column names to lowercase for grouping."""
        return (
            c.source_table.lower().strip(),
            c.source_column.lower().strip(),
            c.target_table.lower().strip(),
            c.target_column.lower().strip(),
        )


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════


async def run_multi_agent_inference(
    schema: SchemaProfile,
    business_context: Optional[dict] = None,
    hint_pack: Optional[dict] = None,
    samples: Optional[dict[str, list]] = None,
    llm_client: Optional[LLMClient] = None,
) -> list[EvaluatedRelation]:
    """
    Run all four inference agents and merge results via ensemble evaluation.

    Agents A+C (deterministic) and B+D (LLM) run in parallel.
    Then the EnsembleEvaluator merges by consensus.

    Args:
        schema: SchemaProfile from SchemaExtractor
        business_context: Optional dict with company_name, industry, country, etc.
        hint_pack: Optional ERP hint pack from load_hint_pack()
        samples: Optional sample data per table {table_name: [row_dicts]}
        llm_client: Optional LLM client. Uses MockLLMClient if None.
    """
    if llm_client is None:
        llm_client = MockLLMClient()

    # Deterministic agents
    structural = StructuralAgent()
    domain = DomainAgent()

    # LLM agents
    semantic = SemanticAgent(llm_client)
    process = BusinessProcessAgent(llm_client)

    # Run in parallel: deterministic + LLM
    structural_result = structural.infer(schema)
    domain_result = domain.infer(schema, hint_pack)

    semantic_coro = semantic.infer(schema, samples)
    process_coro = process.infer(schema, business_context)
    semantic_result, process_result = await asyncio.gather(
        semantic_coro, process_coro,
    )

    # Ensemble evaluation
    evaluator = EnsembleEvaluator()
    return evaluator.evaluate([
        structural_result,
        semantic_result,
        domain_result,
        process_result,
    ])
