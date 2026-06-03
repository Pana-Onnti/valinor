"""
QueryEvolver — identifies queries that repeatedly return empty results and marks them
for replacement. Also tracks which queries generated the most findings.
"""
from __future__ import annotations
from typing import Dict, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile


class QueryEvolver:

    def analyze_query_results(
        self,
        query_results: Dict[str, Any],
        findings: Dict[str, Any],
        profile: "ClientProfile",
    ) -> Dict[str, Any]:
        """
        Analyze query results after execution.
        - Marks queries that returned 0 rows (useless)
        - Identifies queries whose tables appeared in findings (high-value)
        - Persists empty-query counts across runs in profile.metadata
        Returns a summary dict with 'empty_queries', 'high_value_tables'.
        """
        empty_queries: List[str] = []
        high_value_tables: List[str] = []

        for query_id, result in query_results.get("results", {}).items():
            rows = result.get("rows", [])
            if not rows:
                empty_queries.append(query_id)

        # Persist empty-query counts so repeated empties accumulate across runs
        if not isinstance(profile.metadata.get("empty_query_counts"), dict):
            profile.metadata["empty_query_counts"] = {}
        counts: Dict[str, int] = profile.metadata["empty_query_counts"]
        for qname in empty_queries:
            counts[qname] = counts.get(qname, 0) + 1

        # Tables that appear in finding SQLs are high-value
        finding_sqls: List[str] = []
        for agent_result in findings.values():
            if isinstance(agent_result, dict):
                for f in agent_result.get("findings", []):
                    sql = f.get("sql", "")
                    if sql:
                        finding_sqls.append(sql.lower())

        for entity_name in (profile.focus_tables or []):
            for sql in finding_sqls:
                if entity_name.lower() in sql:
                    high_value_tables.append(entity_name)
                    break

        # Add high-value query hints to profile (max 10 stored)
        for tbl in high_value_tables:
            hint = f"priorizar tabla: {tbl}"
            existing_hints = [
                pq if isinstance(pq, str) else pq.get("hint", "")
                for pq in profile.preferred_queries
            ]
            if hint not in existing_hints:
                if len(profile.preferred_queries) < 10:
                    profile.preferred_queries.append({"hint": hint, "table": tbl})

        return {
            "empty_queries": empty_queries,
            "high_value_tables": high_value_tables,
        }

    def format_context(self, profile: "ClientProfile") -> str:
        """
        Return a human-readable summary of the accumulated query evolution state
        for injection into agent prompts.

        Includes:
        - Queries that have been empty >= 2 consecutive runs (candidates for removal)
        - High-value tables registered in preferred_queries
        """
        lines: List[str] = ["## Query Evolution Context"]

        counts: Dict[str, int] = profile.metadata.get("empty_query_counts", {})
        chronic_empty = sorted(
            [(q, n) for q, n in counts.items() if n >= 2],
            key=lambda x: -x[1],
        )
        if chronic_empty:
            lines.append("\n### Queries con resultados vacíos recurrentes (candidatas a reemplazar):")
            for qname, n in chronic_empty:
                lines.append(f"  - {qname}: vacía en {n} run(s)")
        else:
            lines.append("\nNo hay queries con resultados vacíos recurrentes.")

        high_value = [
            pq["table"] if isinstance(pq, dict) else pq
            for pq in profile.preferred_queries
        ]
        if high_value:
            lines.append("\n### Tablas de alto valor (priorizar en próximas queries):")
            for tbl in high_value:
                lines.append(f"  - {tbl}")

        return "\n".join(lines)
