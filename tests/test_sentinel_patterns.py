"""
Unit tests for the sentinel_patterns module.
No mocking — pure in-memory data.
"""
import pytest
from core.valinor.agents.sentinel_patterns import (
    PATTERNS,
    AnomalyPattern,
    get_patterns_for_tables,
    get_patterns_by_severity,
    get_patterns_by_category,
    build_sentinel_context,
)


# ---------------------------------------------------------------------------
# get_patterns_for_tables
# ---------------------------------------------------------------------------

def test_get_patterns_for_tables_account_move_res_partner():
    """Patterns requiring only account_move and/or res_partner should be returned."""
    result = get_patterns_for_tables(["account_move", "res_partner"])
    assert len(result) > 0
    # Every returned pattern must only need tables from the supplied set
    available = {"account_move", "res_partner"}
    for pattern in result:
        for table in pattern.erp_tables:
            assert table.lower() in available, (
                f"Pattern '{pattern.id}' requires table '{table}' which was not supplied"
            )


def test_get_patterns_for_tables_empty_input_returns_empty():
    """No available tables — no patterns can be used."""
    result = get_patterns_for_tables([])
    assert result == []


def test_get_patterns_for_tables_subset_excludes_multi_table_patterns():
    """Patterns that need tables not in the supplied list must be excluded."""
    # supply only account_move — patterns needing res_partner must NOT appear
    result = get_patterns_for_tables(["account_move"])
    for pattern in result:
        for table in pattern.erp_tables:
            assert table.lower() == "account_move", (
                f"Pattern '{pattern.id}' requires '{table}' but only account_move was supplied"
            )


def test_get_patterns_for_tables_all_tables_returns_all_patterns():
    """Supplying every table referenced in PATTERNS returns all patterns."""
    all_tables = set()
    for p in PATTERNS:
        all_tables.update(t.lower() for t in p.erp_tables)
    result = get_patterns_for_tables(list(all_tables))
    assert len(result) == len(PATTERNS)


# ---------------------------------------------------------------------------
# get_patterns_by_severity
# ---------------------------------------------------------------------------

def test_get_patterns_by_severity_critical_returns_only_critical():
    """get_patterns_by_severity('CRITICAL') must return only CRITICAL patterns."""
    result = get_patterns_by_severity("CRITICAL")
    assert len(result) > 0
    for pattern in result:
        assert pattern.severity == "CRITICAL", (
            f"Pattern '{pattern.id}' has severity '{pattern.severity}', expected CRITICAL"
        )


def test_get_patterns_by_severity_high_returns_only_high():
    result = get_patterns_by_severity("HIGH")
    assert len(result) > 0
    for pattern in result:
        assert pattern.severity == "HIGH"


def test_get_patterns_by_severity_unknown_returns_empty():
    result = get_patterns_by_severity("NONEXISTENT_SEVERITY")
    assert result == []


# ---------------------------------------------------------------------------
# build_sentinel_context
# ---------------------------------------------------------------------------

def test_build_sentinel_context_returns_non_empty_string():
    """build_sentinel_context with any patterns must return a non-empty string."""
    patterns = get_patterns_by_severity("HIGH")
    assert len(patterns) > 0
    context = build_sentinel_context(patterns)
    assert isinstance(context, str)
    assert len(context) > 0


def test_build_sentinel_context_contains_pattern_names():
    """The returned context string must include each pattern's name."""
    patterns = get_patterns_for_tables(["account_move", "res_partner"])
    context = build_sentinel_context(patterns)
    for pattern in patterns:
        assert pattern.name in context, (
            f"Pattern name '{pattern.name}' not found in build_sentinel_context output"
        )


def test_build_sentinel_context_empty_list_returns_header_only():
    """build_sentinel_context with an empty list still returns a non-empty header string."""
    context = build_sentinel_context([])
    assert isinstance(context, str)
    assert len(context) > 0


# ---------------------------------------------------------------------------
# benford_deviation pattern exists in PATTERNS
# ---------------------------------------------------------------------------

def test_benford_deviation_pattern_exists():
    """The benford_deviation pattern must be present in PATTERNS."""
    ids = [p.id for p in PATTERNS]
    assert "benford_deviation" in ids


def test_benford_deviation_pattern_structure():
    """benford_deviation must be a well-formed AnomalyPattern."""
    pattern = next(p for p in PATTERNS if p.id == "benford_deviation")
    assert isinstance(pattern, AnomalyPattern)
    assert pattern.name  # non-empty name
    assert pattern.severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    assert len(pattern.erp_tables) > 0
    assert len(pattern.sql_template.strip()) > 0


# ---------------------------------------------------------------------------
# PATTERNS list sanity checks
# ---------------------------------------------------------------------------

def test_patterns_list_is_non_empty():
    assert len(PATTERNS) > 0


def test_all_patterns_have_required_fields():
    """Every pattern must have id, name, severity, erp_tables, and sql_template."""
    for p in PATTERNS:
        assert p.id, f"Pattern missing id: {p}"
        assert p.name, f"Pattern '{p.id}' missing name"
        assert p.severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"), (
            f"Pattern '{p.id}' has unknown severity '{p.severity}'"
        )
        assert isinstance(p.erp_tables, list) and len(p.erp_tables) > 0, (
            f"Pattern '{p.id}' has empty erp_tables"
        )
        assert p.sql_template.strip(), f"Pattern '{p.id}' has empty sql_template"
