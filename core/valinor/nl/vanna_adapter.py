"""
Vanna AI NL→SQL Adapter (VAL-32).

Wraps the Vanna NL→SQL library with:
- Anthropic as the LLM backend (using the ANTHROPIC_API_KEY env var)
- An in-memory vector store (no external dependency required)
- Integration with CartographerOutput: the schema discovered by the
  Cartographer is used to train Vanna so it can generate accurate SQL
  for this specific client's database.

This layer is ADDITIVE — it does not modify or replace the QueryBuilder.
Use it for ad-hoc / conversational questions.

Usage:
    adapter = VannaAdapter()
    adapter.train_from_entity_map(entity_map_dict)
    result = adapter.ask("What are my top 5 customers by revenue?")
    # result = {"sql": "SELECT ...", "explanation": "...", "error": None}
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

# Ensure project root on sys.path
_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── In-memory vector store (no external dependency) ──────────────────────────

class _InMemoryVectorStore:
    """
    Minimal in-memory vector store for Vanna.

    Stores DDL strings and documentation as plain text.
    Similarity is not implemented (returns all docs) — suitable for small schemas.
    For production with large schemas, swap for ChromaDB or pgvector.
    """

    def __init__(self):
        self._ddl: List[str] = []
        self._docs: List[str] = []
        self._sql: List[str] = []

    def add_ddl(self, ddl: str, **kwargs) -> str:
        self._ddl.append(ddl)
        return f"ddl-{len(self._ddl)}"

    def add_documentation(self, doc: str, **kwargs) -> str:
        self._docs.append(doc)
        return f"doc-{len(self._docs)}"

    def add_question_sql(self, question: str, sql: str, **kwargs) -> str:
        self._sql.append(f"Q: {question}\nSQL: {sql}")
        return f"sql-{len(self._sql)}"

    def get_related_ddl(self, question: str, **kwargs) -> List[str]:
        return self._ddl  # Return all — small schema

    def get_related_documentation(self, question: str, **kwargs) -> List[str]:
        return self._docs

    def get_similar_question_sql(self, question: str, **kwargs) -> List[Dict[str, str]]:
        items = []
        for entry in self._sql:
            lines = entry.split("\n")
            if len(lines) >= 2:
                items.append({
                    "question": lines[0].replace("Q: ", ""),
                    "sql": lines[1].replace("SQL: ", ""),
                })
        return items

    def get_training_data(self, **kwargs):
        import pandas as pd
        rows = []
        for d in self._ddl:
            rows.append({"type": "ddl", "content": d})
        for d in self._docs:
            rows.append({"type": "documentation", "content": d})
        for d in self._sql:
            rows.append({"type": "sql", "content": d})
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["type", "content"])

    def remove_training_data(self, id: str, **kwargs) -> bool:
        return True


# ── Vanna adapter class ───────────────────────────────────────────────────────

class VannaAdapter:
    """
    NL→SQL adapter backed by Vanna AI + Anthropic + in-memory store.

    Lifecycle:
    1. Instantiate: VannaAdapter()
    2. Train from schema: adapter.train_from_entity_map(entity_map)
    3. Ask: adapter.ask("question") → {"sql": ..., "explanation": ..., "error": None}
    4. (Optional) Execute: adapter.ask_and_run("question", connection_string)
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: Optional[str] = None,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._vn = None
        self._trained = False
        self._init()

    def _init(self) -> None:
        """Initialize Vanna with Anthropic + in-memory store."""
        try:
            from vanna.legacy.base import VannaBase
            from vanna.legacy.anthropic.anthropic_chat import Anthropic_Chat

            store = _InMemoryVectorStore()

            class _VannaInstance(Anthropic_Chat, VannaBase):
                """Combined Anthropic + in-memory Vanna instance."""

                def __init__(self, config):
                    Anthropic_Chat.__init__(self, config=config)
                    VannaBase.__init__(self, config=config)

                # Delegate vector store methods to the in-memory store
                def add_ddl(self, ddl: str, **kwargs) -> str:
                    return store.add_ddl(ddl, **kwargs)

                def add_documentation(self, doc: str, **kwargs) -> str:
                    return store.add_documentation(doc, **kwargs)

                def add_question_sql(self, question: str, sql: str, **kwargs) -> str:
                    return store.add_question_sql(question, sql, **kwargs)

                def get_related_ddl(self, question: str, **kwargs):
                    return store.get_related_ddl(question, **kwargs)

                def get_related_documentation(self, question: str, **kwargs):
                    return store.get_related_documentation(question, **kwargs)

                def get_similar_question_sql(self, question: str, **kwargs):
                    return store.get_similar_question_sql(question, **kwargs)

                def get_training_data(self, **kwargs):
                    return store.get_training_data(**kwargs)

                def remove_training_data(self, id: str, **kwargs) -> bool:
                    return store.remove_training_data(id, **kwargs)

            self._vn = _VannaInstance(
                config={
                    "api_key": self.api_key,
                    "model": self.model,
                }
            )
            logger.info("vanna_adapter: initialized", model=self.model)

        except Exception as exc:
            logger.warning("vanna_adapter: init failed", error=str(exc))
            self._vn = None

    @property
    def is_ready(self) -> bool:
        return self._vn is not None

    def train_from_entity_map(self, entity_map: Dict[str, Any]) -> int:
        """
        Train Vanna with the schema discovered by the Cartographer.

        Each entity in the entity_map generates:
        - A synthetic DDL statement
        - A documentation string describing the entity

        Args:
            entity_map: Legacy dict format or CartographerOutput.to_entity_map_dict()

        Returns:
            Number of training entries added.
        """
        if not self.is_ready:
            logger.warning("vanna_adapter: not ready, skipping training")
            return 0

        entities = entity_map.get("entities", {})
        client = entity_map.get("client", "unknown")
        count = 0

        # Add global documentation
        self._vn.add_documentation(
            f"Database schema for client: {client}. "
            f"This database contains {len(entities)} main entities."
        )
        count += 1

        for entity_name, cfg in entities.items():
            table = cfg.get("table", entity_name)
            key_cols = cfg.get("key_columns", {})
            row_count = cfg.get("row_count", 0)
            base_filter = cfg.get("base_filter", "").strip()
            entity_type = cfg.get("entity_type", "UNKNOWN")

            # Synthetic DDL
            cols_ddl = []
            for semantic_name, actual_col in key_cols.items():
                cols_ddl.append(f"    {actual_col} -- {semantic_name}")

            ddl = textwrap.dedent(f"""
                -- Entity: {entity_name} ({entity_type}) — {row_count:,} rows
                CREATE TABLE {table} (
                {chr(10).join(cols_ddl) if cols_ddl else '    -- (columns unknown)'}
                );
            """).strip()

            self._vn.add_ddl(ddl)
            count += 1

            # Documentation
            doc_parts = [
                f"Table '{table}' represents '{entity_name}' ({entity_type}).",
                f"It has approximately {row_count:,} rows.",
            ]
            if base_filter:
                doc_parts.append(f"Standard filter: {base_filter}")
            if key_cols:
                cols_list = ", ".join(f"{v} ({k})" for k, v in list(key_cols.items())[:6])
                doc_parts.append(f"Key columns: {cols_list}.")

            self._vn.add_documentation(" ".join(doc_parts))
            count += 1

        self._trained = True
        logger.info("vanna_adapter: training complete", entries=count, client=client)
        return count

    def ask(self, question: str) -> Dict[str, Any]:
        """
        Convert a natural language question to SQL.

        Args:
            question: Natural language question about the data.

        Returns:
            {
                "sql": "SELECT ...",
                "explanation": "...",
                "error": None | "..."
            }
        """
        if not self.is_ready:
            return {
                "sql": None,
                "explanation": None,
                "error": "Vanna adapter not initialized. Check ANTHROPIC_API_KEY.",
            }

        try:
            sql = self._vn.generate_sql(question=question)
            return {
                "sql": sql,
                "explanation": f"Generated SQL for: {question}",
                "error": None,
            }
        except Exception as exc:
            logger.error("vanna_adapter.ask failed", question=question, error=str(exc))
            return {
                "sql": None,
                "explanation": None,
                "error": str(exc),
            }

    def ask_and_run(
        self,
        question: str,
        connection_string: str,
        max_rows: int = 100,
    ) -> Dict[str, Any]:
        """
        Convert NL question to SQL and execute it.

        Args:
            question: Natural language question.
            connection_string: SQLAlchemy connection string.
            max_rows: Maximum rows to return.

        Returns:
            {
                "sql": "...",
                "result": [{...}, ...],
                "explanation": "...",
                "error": None | "..."
            }
        """
        result = self.ask(question)
        if result["error"] or not result["sql"]:
            result["result"] = []
            return result

        try:
            from sqlalchemy import create_engine, text as sa_text

            engine = create_engine(connection_string)
            with engine.connect() as conn:
                rows = conn.execute(sa_text(result["sql"]))
                cols = list(rows.keys())
                data = [dict(zip(cols, row)) for row in rows.fetchmany(max_rows)]
            engine.dispose()

            result["result"] = data
            logger.info(
                "vanna_adapter.ask_and_run",
                question=question,
                rows_returned=len(data),
            )
            return result

        except Exception as exc:
            logger.error("vanna_adapter.ask_and_run failed", error=str(exc))
            result["error"] = str(exc)
            result["result"] = []
            return result
