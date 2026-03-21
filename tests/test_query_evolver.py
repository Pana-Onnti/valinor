"""
Tests for QueryEvolver — api/refinement/query_evolver.py

Covers:
  - Empty-query detection and persistence across runs
  - High-value table identification from finding SQLs
  - Context dict shape (required keys)
  - Repeated empty queries increment the stored counter
  - Non-empty results are never flagged as empty
  - format_context() returns a string summary
  - Profile preferred_queries updated when high-value tables found
  - Edge cases: empty entity map, None / missing results
"""
import sys
import pytest

sys.path.insert(0, "api")
sys.path.insert(0, "shared")
sys.path.insert(0, ".")

from refinement.query_evolver import QueryEvolver
from memory.client_profile import ClientProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(name: str = "TestCorp", focus_tables=None) -> ClientProfile:
    p = ClientProfile.new(name)
    if focus_tables:
        p.focus_tables = focus_tables
    return p


def _make_qr(*entries):
    """
    Build a query_results dict.
    Each entry is a (name, rows) tuple where rows is a list (possibly empty).
    """
    return {
        "results": [
            {"name": name, "rows": rows}
            for name, rows in entries
        ]
    }


def _make_findings(table_sql_pairs):
    """
    Build a findings dict with finding SQLs that reference specific tables.
    table_sql_pairs: list of (table_name, sql_snippet) tuples.
    """
    findings_list = [
        {"id": f"F{i:03d}", "severity": "HIGH", "sql": sql}
        for i, (_, sql) in enumerate(table_sql_pairs, start=1)
    ]
    return {"analyst": {"findings": findings_list}}


# ---------------------------------------------------------------------------
# TestQueryEvolver
# ---------------------------------------------------------------------------

class TestQueryEvolver:

    # ------------------------------------------------------------------
    # 1. Empty-query detection
    # ------------------------------------------------------------------

    def test_empty_results_tracked(self):
        """Queries returning 0 rows appear in the 'empty_queries' return key."""
        evolver = QueryEvolver()
        profile = _make_profile()
        qr = _make_qr(("overdue_invoices", []), ("active_customers", [{"id": 1}]))

        result = evolver.analyze_query_results(qr, {}, profile)

        assert "overdue_invoices" in result["empty_queries"]
        assert "active_customers" not in result["empty_queries"]

    def test_non_empty_results_not_in_empty_list(self):
        """A query with at least one row must NOT appear in empty_queries."""
        evolver = QueryEvolver()
        profile = _make_profile()
        qr = _make_qr(
            ("revenue_by_month", [{"month": "2025-01", "total": 50000}]),
            ("top_customers", [{"name": "Acme"}, {"name": "Beta"}]),
        )

        result = evolver.analyze_query_results(qr, {}, profile)

        assert result["empty_queries"] == []

    # ------------------------------------------------------------------
    # 2. High-value table identification
    # ------------------------------------------------------------------

    def test_high_value_table_identified(self):
        """
        A focus_table that appears inside a finding SQL is classified as high-value.
        """
        evolver = QueryEvolver()
        profile = _make_profile(focus_tables=["account_move", "sale_order"])
        findings = _make_findings([
            ("account_move", "SELECT * FROM account_move WHERE state='posted'"),
        ])

        result = evolver.analyze_query_results(_make_qr(), findings, profile)

        assert "account_move" in result["high_value_tables"]

    def test_table_not_in_findings_sql_is_not_high_value(self):
        """A focus_table not referenced in any finding SQL must not be high-value."""
        evolver = QueryEvolver()
        profile = _make_profile(focus_tables=["account_move", "res_partner"])
        findings = _make_findings([
            ("account_move", "SELECT * FROM account_move"),
        ])

        result = evolver.analyze_query_results(_make_qr(), findings, profile)

        assert "res_partner" not in result["high_value_tables"]

    # ------------------------------------------------------------------
    # 3. Return dict shape
    # ------------------------------------------------------------------

    def test_context_dict_has_required_keys(self):
        """The returned dict must always contain 'empty_queries' and 'high_value_tables'."""
        evolver = QueryEvolver()
        profile = _make_profile()

        result = evolver.analyze_query_results({}, {}, profile)

        assert "empty_queries" in result
        assert "high_value_tables" in result

    def test_context_dict_values_are_lists(self):
        """Both 'empty_queries' and 'high_value_tables' must be list instances."""
        evolver = QueryEvolver()
        profile = _make_profile()

        result = evolver.analyze_query_results(_make_qr(), {}, profile)

        assert isinstance(result["empty_queries"], list)
        assert isinstance(result["high_value_tables"], list)

    # ------------------------------------------------------------------
    # 4. Repeated empty query increments count across runs
    # ------------------------------------------------------------------

    def test_repeated_empty_query_increments_count(self):
        """
        Calling analyze_query_results twice with the same empty query must
        increment the stored counter in profile.metadata['empty_query_counts'].
        """
        evolver = QueryEvolver()
        profile = _make_profile()
        qr = _make_qr(("slow_query", []))

        evolver.analyze_query_results(qr, {}, profile)
        evolver.analyze_query_results(qr, {}, profile)

        counts = profile.metadata.get("empty_query_counts", {})
        assert counts.get("slow_query", 0) == 2

    def test_three_runs_accumulate_correctly(self):
        """Three consecutive empty results must yield a count of 3."""
        evolver = QueryEvolver()
        profile = _make_profile()
        qr = _make_qr(("zero_result_query", []))

        for _ in range(3):
            evolver.analyze_query_results(qr, {}, profile)

        counts = profile.metadata.get("empty_query_counts", {})
        assert counts["zero_result_query"] == 3

    def test_non_empty_query_count_not_stored(self):
        """A query that returns rows must NOT appear in empty_query_counts."""
        evolver = QueryEvolver()
        profile = _make_profile()
        qr = _make_qr(("healthy_query", [{"id": 1}]))

        evolver.analyze_query_results(qr, {}, profile)

        counts = profile.metadata.get("empty_query_counts", {})
        assert "healthy_query" not in counts

    # ------------------------------------------------------------------
    # 5. format_context() output
    # ------------------------------------------------------------------

    def test_format_context_is_string(self):
        """format_context() must return a str instance."""
        evolver = QueryEvolver()
        profile = _make_profile()

        ctx = evolver.format_context(profile)

        assert isinstance(ctx, str)

    def test_format_context_non_empty(self):
        """format_context() must return a non-empty string."""
        evolver = QueryEvolver()
        profile = _make_profile()

        ctx = evolver.format_context(profile)

        assert len(ctx) > 0

    def test_format_context_mentions_chronic_empty_queries(self):
        """
        After a query has been empty >= 2 runs, format_context() must mention it.
        """
        evolver = QueryEvolver()
        profile = _make_profile()
        qr = _make_qr(("dead_query", []))

        evolver.analyze_query_results(qr, {}, profile)
        evolver.analyze_query_results(qr, {}, profile)

        ctx = evolver.format_context(profile)

        assert "dead_query" in ctx

    def test_format_context_mentions_high_value_table(self):
        """
        After a high-value table is added to preferred_queries,
        format_context() must include it.
        """
        evolver = QueryEvolver()
        profile = _make_profile(focus_tables=["account_move"])
        findings = _make_findings([
            ("account_move", "SELECT id FROM account_move"),
        ])

        evolver.analyze_query_results(_make_qr(), findings, profile)

        ctx = evolver.format_context(profile)

        assert "account_move" in ctx

    # ------------------------------------------------------------------
    # 6. Profile preferred_queries update
    # ------------------------------------------------------------------

    def test_update_profile_modifies_preferred_queries(self):
        """
        When a high-value table is detected, the profile's preferred_queries
        list must grow and contain a hint for that table.
        """
        evolver = QueryEvolver()
        profile = _make_profile(focus_tables=["sale_order"])
        assert len(profile.preferred_queries) == 0

        findings = _make_findings([("sale_order", "SELECT * FROM sale_order")])
        evolver.analyze_query_results(_make_qr(), findings, profile)

        assert len(profile.preferred_queries) == 1
        hint_entry = profile.preferred_queries[0]
        assert isinstance(hint_entry, dict)
        assert hint_entry.get("table") == "sale_order"

    def test_preferred_queries_capped_at_10(self):
        """preferred_queries must never exceed 10 entries."""
        evolver = QueryEvolver()
        tables = [f"table_{i}" for i in range(15)]
        profile = _make_profile(focus_tables=tables)

        for tbl in tables:
            findings = _make_findings([(tbl, f"SELECT * FROM {tbl}")])
            evolver.analyze_query_results(_make_qr(), findings, profile)

        assert len(profile.preferred_queries) <= 10

    def test_no_duplicate_hints_added(self):
        """
        Running analyze_query_results twice for the same high-value table must
        not add duplicate entries to preferred_queries.
        """
        evolver = QueryEvolver()
        profile = _make_profile(focus_tables=["account_move"])
        findings = _make_findings([("account_move", "SELECT * FROM account_move")])

        evolver.analyze_query_results(_make_qr(), findings, profile)
        evolver.analyze_query_results(_make_qr(), findings, profile)

        tables_stored = [
            pq["table"] if isinstance(pq, dict) else pq
            for pq in profile.preferred_queries
        ]
        assert tables_stored.count("account_move") == 1

    # ------------------------------------------------------------------
    # 7. Edge cases
    # ------------------------------------------------------------------

    def test_empty_entity_map_no_crash(self):
        """
        A profile with no focus_tables must not raise and must return
        an empty high_value_tables list.
        """
        evolver = QueryEvolver()
        profile = _make_profile(focus_tables=[])
        findings = _make_findings([("account_move", "SELECT * FROM account_move")])

        result = evolver.analyze_query_results(_make_qr(), findings, profile)

        assert result["high_value_tables"] == []

    def test_none_or_missing_results_key(self):
        """
        query_results without a 'results' key must not crash and must return
        empty lists.
        """
        evolver = QueryEvolver()
        profile = _make_profile()

        result = evolver.analyze_query_results({}, {}, profile)

        assert result["empty_queries"] == []
        assert result["high_value_tables"] == []

    def test_results_entry_without_rows_key(self):
        """
        A result dict that has no 'rows' key must be treated as empty (0 rows).
        """
        evolver = QueryEvolver()
        profile = _make_profile()
        qr = {"results": [{"name": "missing_rows_query"}]}  # no 'rows' key

        result = evolver.analyze_query_results(qr, {}, profile)

        assert "missing_rows_query" in result["empty_queries"]

    def test_empty_findings_dict_no_crash(self):
        """
        An empty findings dict must not crash and must produce no high_value_tables.
        """
        evolver = QueryEvolver()
        profile = _make_profile(focus_tables=["account_move"])

        result = evolver.analyze_query_results(_make_qr(), {}, profile)

        assert result["high_value_tables"] == []
