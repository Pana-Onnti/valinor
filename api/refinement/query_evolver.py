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
        Returns a summary dict with 'empty_queries', 'high_value_tables'.
        """
        empty_queries: List[str] = []
        high_value_tables: List[str] = []

        for result in query_results.get("results", []):
            query_name = result.get("name", "")
            rows = result.get("rows", [])
            if not rows:
                empty_queries.append(query_name)

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
            if hint not in profile.preferred_queries:
                if len(profile.preferred_queries) < 10:
                    profile.preferred_queries.append({"hint": hint, "table": tbl})

        return {
            "empty_queries": empty_queries,
            "high_value_tables": high_value_tables,
        }
