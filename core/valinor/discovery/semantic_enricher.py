"""
Semantic Column Enricher — VAL-42: Name + data pattern fusion.

Classifies columns semantically by combining:
  1. Name heuristics ("total", "amount", "price" -> AMOUNT)
  2. Data pattern analysis (all floats with 2 decimals -> likely AMOUNT)

Returns enriched column metadata that can be used by:
  - Query generator for column disambiguation
  - Zero-row reformulator for alternative column names
  - Ontology builder for richer entity classification

Architecture references:
  - GAIT (PAKDD 2024) — data-driven semantic type detection
  - Sherlock (KDD 2019) — deep learning for column type inference
  - Sato (VLDB 2020) — context-aware column type prediction
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# SEMANTIC TYPES
# ═══════════════════════════════════════════════════════════════════════════


class SemanticColumnType(str, Enum):
    """High-level semantic classification of a column."""
    DATE = "DATE"
    AMOUNT = "AMOUNT"
    IDENTIFIER = "IDENTIFIER"
    NAME = "NAME"
    STATUS = "STATUS"
    CATEGORY = "CATEGORY"
    QUANTITY = "QUANTITY"
    PERCENTAGE = "PERCENTAGE"
    DESCRIPTION = "DESCRIPTION"
    FLAG = "FLAG"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    UNKNOWN = "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════════
# NAME HEURISTICS — pattern → semantic type mapping
# ═══════════════════════════════════════════════════════════════════════════

# Each entry: (compiled regex for column name, semantic type, confidence boost)
_NAME_PATTERNS: list[tuple[re.Pattern, SemanticColumnType, float]] = [
    # DATE patterns
    (re.compile(r'(date|fecha|_dt$|_at$|created|updated|modified|timestamp)', re.I),
     SemanticColumnType.DATE, 0.8),

    # AMOUNT patterns
    (re.compile(r'(amount|total|price|cost|revenue|grand_?total|subtotal|tax|discount|balance|outstanding|paid|credit|debit|fee|charge|salary|wage|monto|importe|saldo)', re.I),
     SemanticColumnType.AMOUNT, 0.8),

    # IDENTIFIER patterns
    (re.compile(r'(_id$|_pk$|_fk$|_key$|_code$|_num$|_no$|^id$|uuid|guid)', re.I),
     SemanticColumnType.IDENTIFIER, 0.9),

    # NAME patterns
    (re.compile(r'(name|nombre|title|label|description|comment|note|remark)', re.I),
     SemanticColumnType.NAME, 0.7),

    # STATUS patterns
    (re.compile(r'(status|state|stage|phase|docstatus|doc_status)', re.I),
     SemanticColumnType.STATUS, 0.85),

    # CATEGORY patterns
    (re.compile(r'(category|type|class|group|segment|kind|genre|familia)', re.I),
     SemanticColumnType.CATEGORY, 0.7),

    # QUANTITY patterns
    (re.compile(r'(qty|quantity|count|num_|number_of|units|pieces|stock)', re.I),
     SemanticColumnType.QUANTITY, 0.75),

    # PERCENTAGE patterns
    (re.compile(r'(pct|percent|ratio|rate|_pct$|_rate$)', re.I),
     SemanticColumnType.PERCENTAGE, 0.8),

    # FLAG patterns
    (re.compile(r'(^is_|^has_|^can_|^is[a-z]+$|active|enabled|deleted|flag)', re.I),
     SemanticColumnType.FLAG, 0.85),

    # EMAIL patterns
    (re.compile(r'(email|e_mail|correo)', re.I),
     SemanticColumnType.EMAIL, 0.9),

    # PHONE patterns
    (re.compile(r'(phone|tel|fax|mobile|celular)', re.I),
     SemanticColumnType.PHONE, 0.85),

    # ADDRESS patterns
    (re.compile(r'(address|addr|street|city|state|zip|postal|country|region|provincia)', re.I),
     SemanticColumnType.ADDRESS, 0.75),

    # DESCRIPTION patterns (longer text)
    (re.compile(r'(desc|description|comment|note|remark|memo|observation|texto)', re.I),
     SemanticColumnType.DESCRIPTION, 0.7),
]


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class EnrichedColumn:
    """A column with semantic enrichment metadata."""
    name: str
    table: str
    semantic_type: SemanticColumnType = SemanticColumnType.UNKNOWN
    confidence: float = 0.0
    name_signal: SemanticColumnType | None = None
    data_signal: SemanticColumnType | None = None
    name_confidence: float = 0.0
    data_confidence: float = 0.0
    alternative_names: list[str] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    db_type: str = ""


@dataclass
class TableEnrichment:
    """Enriched metadata for all columns in a table."""
    table_name: str
    columns: dict[str, EnrichedColumn] = field(default_factory=dict)
    date_columns: list[str] = field(default_factory=list)
    amount_columns: list[str] = field(default_factory=list)
    identifier_columns: list[str] = field(default_factory=list)
    name_columns: list[str] = field(default_factory=list)
    status_columns: list[str] = field(default_factory=list)
    category_columns: list[str] = field(default_factory=list)

    def get_columns_by_type(self, semantic_type: SemanticColumnType) -> list[str]:
        """Get all column names matching a semantic type."""
        return [
            name for name, col in self.columns.items()
            if col.semantic_type == semantic_type
        ]


# ═══════════════════════════════════════════════════════════════════════════
# DATA PATTERN DETECTORS
# ═══════════════════════════════════════════════════════════════════════════

_DATE_PATTERN = re.compile(
    r'^\d{4}[-/]\d{2}[-/]\d{2}'  # 2024-01-15 or 2024/01/15
    r'|^\d{2}[-/]\d{2}[-/]\d{4}'  # 15-01-2024
)

_AMOUNT_PATTERN = re.compile(
    r'^-?\d{1,12}(\.\d{1,4})?$'  # numeric with optional decimals
)

_INTEGER_ID_PATTERN = re.compile(
    r'^\d+$'  # pure integer
)

_EMAIL_PATTERN = re.compile(
    r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
)

_BOOLEAN_PATTERN = re.compile(
    r'^(Y|N|true|false|yes|no|1|0|T|F|SI|NO)$', re.I
)


def _detect_data_pattern(
    values: list[str],
) -> tuple[SemanticColumnType | None, float]:
    """
    Analyze sample values to infer semantic type from data patterns.

    Returns (semantic_type, confidence) or (None, 0.0) if no pattern found.
    """
    if not values:
        return None, 0.0

    clean = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if not clean:
        return None, 0.0

    n = len(clean)

    # Check for boolean/flag pattern
    bool_count = sum(1 for v in clean if _BOOLEAN_PATTERN.match(v))
    if bool_count / n > 0.8:
        return SemanticColumnType.FLAG, 0.85

    # Check for date pattern
    date_count = sum(1 for v in clean if _DATE_PATTERN.match(v))
    if date_count / n > 0.7:
        return SemanticColumnType.DATE, 0.8

    # Check for email pattern
    email_count = sum(1 for v in clean if _EMAIL_PATTERN.match(v))
    if email_count / n > 0.5:
        return SemanticColumnType.EMAIL, 0.9

    # Check for amount pattern (numeric with decimals)
    amount_count = sum(1 for v in clean if _AMOUNT_PATTERN.match(v))
    if amount_count / n > 0.8:
        # Distinguish AMOUNT from QUANTITY/ID by checking for decimals
        decimal_count = sum(1 for v in clean if '.' in v)
        if decimal_count / n > 0.3:
            return SemanticColumnType.AMOUNT, 0.6
        # Pure integers with high cardinality -> IDENTIFIER
        unique_ratio = len(set(clean)) / n if n > 0 else 0
        if unique_ratio > 0.8:
            return SemanticColumnType.IDENTIFIER, 0.5
        return SemanticColumnType.QUANTITY, 0.5

    # Check for low cardinality (category/status)
    unique = len(set(clean))
    if unique <= 10 and n > 5:
        avg_len = sum(len(v) for v in clean) / n
        if avg_len <= 20:
            return SemanticColumnType.CATEGORY, 0.5
        return SemanticColumnType.STATUS, 0.4

    # Long text -> DESCRIPTION
    avg_len = sum(len(v) for v in clean) / n
    if avg_len > 50:
        return SemanticColumnType.DESCRIPTION, 0.5

    return None, 0.0


# ═══════════════════════════════════════════════════════════════════════════
# SEMANTIC ENRICHER
# ═══════════════════════════════════════════════════════════════════════════


class SemanticEnricher:
    """
    Enriches column metadata by fusing name heuristics + data patterns.

    The final semantic type is determined by combining signals:
      - If both name and data agree → high confidence
      - If only name matches → use name signal with moderate confidence
      - If only data matches → use data signal with lower confidence
      - If they conflict → prefer name signal (more reliable for known patterns)
    """

    def enrich_column(
        self,
        column_name: str,
        table_name: str,
        sample_values: list[Any] | None = None,
        db_type: str = "",
    ) -> EnrichedColumn:
        """
        Classify a single column semantically.

        Args:
            column_name: The column name.
            table_name: The table this column belongs to.
            sample_values: Optional list of sample values for data pattern analysis.
            db_type: Optional PostgreSQL data type (e.g., "numeric", "timestamp").

        Returns:
            EnrichedColumn with semantic classification.
        """
        col = EnrichedColumn(
            name=column_name,
            table=table_name,
            db_type=db_type,
        )

        # Signal 1: Name heuristics
        name_type, name_conf = self._classify_by_name(column_name)
        col.name_signal = name_type
        col.name_confidence = name_conf

        # Signal 2: Data patterns
        str_values = [str(v) for v in (sample_values or []) if v is not None]
        data_type, data_conf = _detect_data_pattern(str_values)
        col.data_signal = data_type
        col.data_confidence = data_conf
        col.sample_values = str_values[:5]

        # Signal 3: DB type hint
        db_type_hint = self._classify_by_db_type(db_type)

        # Fusion: combine signals
        col.semantic_type, col.confidence = self._fuse_signals(
            name_type, name_conf,
            data_type, data_conf,
            db_type_hint,
        )

        # Generate alternative names
        col.alternative_names = self._generate_alternatives(
            column_name, col.semantic_type,
        )

        return col

    def enrich_table(
        self,
        table_name: str,
        columns: dict[str, dict[str, Any]],
    ) -> TableEnrichment:
        """
        Enrich all columns in a table.

        Args:
            table_name: Table name.
            columns: Dict of column_name -> {"sample_values": [...], "db_type": "..."}.

        Returns:
            TableEnrichment with all columns classified.
        """
        enrichment = TableEnrichment(table_name=table_name)

        for col_name, col_info in columns.items():
            enriched = self.enrich_column(
                column_name=col_name,
                table_name=table_name,
                sample_values=col_info.get("sample_values", []),
                db_type=col_info.get("db_type", ""),
            )
            enrichment.columns[col_name] = enriched

        # Populate convenience lists
        enrichment.date_columns = enrichment.get_columns_by_type(SemanticColumnType.DATE)
        enrichment.amount_columns = enrichment.get_columns_by_type(SemanticColumnType.AMOUNT)
        enrichment.identifier_columns = enrichment.get_columns_by_type(SemanticColumnType.IDENTIFIER)
        enrichment.name_columns = enrichment.get_columns_by_type(SemanticColumnType.NAME)
        enrichment.status_columns = enrichment.get_columns_by_type(SemanticColumnType.STATUS)
        enrichment.category_columns = enrichment.get_columns_by_type(SemanticColumnType.CATEGORY)

        logger.info(
            "table_enrichment_complete",
            table=table_name,
            columns=len(enrichment.columns),
            dates=len(enrichment.date_columns),
            amounts=len(enrichment.amount_columns),
            identifiers=len(enrichment.identifier_columns),
        )

        return enrichment

    def enrich_from_entity_map(
        self, entity_map: dict,
    ) -> dict[str, TableEnrichment]:
        """
        Enrich all tables from an entity_map (uses probed_values as samples).

        Args:
            entity_map: Standard entity_map dict.

        Returns:
            Dict of table_name -> TableEnrichment.
        """
        results: dict[str, TableEnrichment] = {}
        entities = entity_map.get("entities", {})

        for entity_name, entity in entities.items():
            table = entity.get("table", "")
            if not table:
                continue

            columns: dict[str, dict[str, Any]] = {}

            # Columns from key_columns
            for semantic_key, col_name in entity.get("key_columns", {}).items():
                if col_name not in columns:
                    columns[col_name] = {"sample_values": [], "db_type": ""}

            # Columns from probed_values (with samples)
            for col_name, values in entity.get("probed_values", {}).items():
                samples = []
                if isinstance(values, dict):
                    samples = list(values.keys())
                elif isinstance(values, list):
                    samples = [v.get("value", "") if isinstance(v, dict) else str(v) for v in values]
                columns.setdefault(col_name, {})
                columns[col_name]["sample_values"] = samples

            results[table] = self.enrich_table(table, columns)

        return results

    # ── PRIVATE METHODS ────────────────────────────────────────────────

    def _classify_by_name(
        self, column_name: str,
    ) -> tuple[SemanticColumnType | None, float]:
        """Classify column by name pattern matching."""
        for pattern, sem_type, confidence in _NAME_PATTERNS:
            if pattern.search(column_name):
                return sem_type, confidence
        return None, 0.0

    def _classify_by_db_type(
        self, db_type: str,
    ) -> SemanticColumnType | None:
        """Weak signal from PostgreSQL data type."""
        if not db_type:
            return None
        db_lower = db_type.lower()
        if db_lower in ("date", "timestamp", "timestamptz",
                         "timestamp without time zone",
                         "timestamp with time zone"):
            return SemanticColumnType.DATE
        if db_lower in ("numeric", "decimal", "money",
                         "double precision", "real"):
            return SemanticColumnType.AMOUNT
        if db_lower in ("boolean", "bool"):
            return SemanticColumnType.FLAG
        return None

    def _fuse_signals(
        self,
        name_type: SemanticColumnType | None,
        name_conf: float,
        data_type: SemanticColumnType | None,
        data_conf: float,
        db_type_hint: SemanticColumnType | None,
    ) -> tuple[SemanticColumnType, float]:
        """Fuse name, data, and db_type signals into a final classification."""
        # Both agree → high confidence
        if name_type and data_type and name_type == data_type:
            return name_type, min(1.0, name_conf + data_conf * 0.5)

        # DB type matches one signal → boost that signal
        if db_type_hint:
            if name_type == db_type_hint:
                return name_type, min(1.0, name_conf + 0.1)
            if data_type == db_type_hint:
                return data_type, min(1.0, data_conf + 0.1)

        # Name only → moderate confidence
        if name_type and name_conf >= 0.7:
            return name_type, name_conf

        # Data only → lower confidence
        if data_type and data_conf >= 0.5:
            return data_type, data_conf

        # Name with lower confidence
        if name_type:
            return name_type, name_conf

        # DB type as last resort
        if db_type_hint:
            return db_type_hint, 0.4

        return SemanticColumnType.UNKNOWN, 0.0

    def _generate_alternatives(
        self,
        column_name: str,
        semantic_type: SemanticColumnType,
    ) -> list[str]:
        """
        Generate alternative column names for the same semantic type.

        Used by the zero-row reformulator to try alternative columns.
        """
        _ALTERNATIVES: dict[SemanticColumnType, list[str]] = {
            SemanticColumnType.DATE: [
                "date", "fecha", "created_at", "updated_at",
                "dateinvoiced", "dateacct", "dateordered",
                "invoice_date", "order_date", "payment_date",
                "date_invoice", "date_order",
            ],
            SemanticColumnType.AMOUNT: [
                "amount", "total", "grandtotal", "grand_total",
                "subtotal", "amount_total", "price_total",
                "amount_untaxed", "amount_tax", "net_amount",
                "totallines", "linenetamt",
            ],
            SemanticColumnType.IDENTIFIER: [
                "id", "pk", "code", "num", "number",
                "document_no", "documentno", "value",
            ],
            SemanticColumnType.NAME: [
                "name", "nombre", "description", "title", "label",
            ],
            SemanticColumnType.STATUS: [
                "status", "state", "docstatus", "doc_status",
                "processing_status", "stage",
            ],
        }

        alternatives = _ALTERNATIVES.get(semantic_type, [])
        # Filter out the current column name
        return [a for a in alternatives if a.lower() != column_name.lower()]
