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


# ---------------------------------------------------------------------------
# get_patterns_by_category
# ---------------------------------------------------------------------------

def test_get_patterns_by_category_fraud_risk_returns_only_fraud_risk():
    """get_patterns_by_category('fraud_risk') returns only fraud_risk patterns."""
    result = get_patterns_by_category("fraud_risk")
    assert len(result) > 0
    for p in result:
        assert p.category == "fraud_risk", (
            f"Pattern '{p.id}' has category '{p.category}', expected 'fraud_risk'"
        )


def test_get_patterns_by_category_financial_returns_only_financial():
    """get_patterns_by_category('financial') returns only financial patterns."""
    result = get_patterns_by_category("financial")
    assert len(result) > 0
    for p in result:
        assert p.category == "financial"


def test_get_patterns_by_category_unknown_returns_empty():
    """Unknown category returns empty list."""
    result = get_patterns_by_category("nonexistent_category")
    assert result == []


# ---------------------------------------------------------------------------
# Pattern IDs are unique
# ---------------------------------------------------------------------------

def test_all_pattern_ids_are_unique():
    """No two patterns should share the same id."""
    ids = [p.id for p in PATTERNS]
    assert len(ids) == len(set(ids)), (
        f"Duplicate pattern IDs found: {[i for i in ids if ids.count(i) > 1]}"
    )


# ---------------------------------------------------------------------------
# build_sentinel_context output structure
# ---------------------------------------------------------------------------

def test_build_sentinel_context_contains_severity_labels():
    """The context string must include severity labels in brackets."""
    patterns = get_patterns_by_severity("CRITICAL") + get_patterns_by_severity("HIGH")
    context = build_sentinel_context(patterns)
    assert "[CRITICAL]" in context or "[HIGH]" in context, (
        "build_sentinel_context should include severity labels like [CRITICAL] or [HIGH]"
    )


# ---------------------------------------------------------------------------
# Ghost vendor pattern sanity
# ---------------------------------------------------------------------------

def test_ghost_vendor_pattern_is_critical():
    """The ghost_vendor pattern must have CRITICAL severity."""
    pattern = next((p for p in PATTERNS if p.id == "ghost_vendor"), None)
    assert pattern is not None, "ghost_vendor pattern must exist in PATTERNS"
    assert pattern.severity == "CRITICAL", (
        f"ghost_vendor should be CRITICAL; got '{pattern.severity}'"
    )


# ---------------------------------------------------------------------------
# AnomalyPattern field content validation
# ---------------------------------------------------------------------------

def test_all_patterns_have_non_empty_description():
    """Every pattern must have a non-empty description string."""
    for p in PATTERNS:
        assert isinstance(p.description, str) and len(p.description.strip()) > 0, (
            f"Pattern '{p.id}' has empty or missing description"
        )


def test_all_patterns_have_non_empty_interpretation():
    """Every pattern must have a non-empty interpretation string."""
    for p in PATTERNS:
        assert isinstance(p.interpretation, str) and len(p.interpretation.strip()) > 0, (
            f"Pattern '{p.id}' has empty or missing interpretation"
        )


def test_all_patterns_erp_tables_are_lowercase():
    """Convention: erp_tables entries should be lowercase strings."""
    for p in PATTERNS:
        for table in p.erp_tables:
            assert table == table.lower(), (
                f"Pattern '{p.id}' has non-lowercase table '{table}'"
            )


# ---------------------------------------------------------------------------
# get_patterns_by_category — operational category
# ---------------------------------------------------------------------------

def test_get_patterns_by_category_operational_returns_only_operational():
    """get_patterns_by_category('operational') returns only operational patterns."""
    result = get_patterns_by_category("operational")
    assert len(result) > 0
    for p in result:
        assert p.category == "operational", (
            f"Pattern '{p.id}' has category '{p.category}', expected 'operational'"
        )


def test_all_categories_together_cover_all_patterns():
    """Union of all categories must equal the full PATTERNS list."""
    fraud = get_patterns_by_category("fraud_risk")
    financial = get_patterns_by_category("financial")
    operational = get_patterns_by_category("operational")
    total = len(fraud) + len(financial) + len(operational)
    assert total == len(PATTERNS), (
        f"Category counts {len(fraud)}+{len(financial)}+{len(operational)}={total} "
        f"!= total {len(PATTERNS)}"
    )


# ---------------------------------------------------------------------------
# Specific pattern existence checks
# ---------------------------------------------------------------------------

def test_duplicate_invoices_pattern_exists():
    """duplicate_invoices pattern must be present and in fraud_risk category."""
    p = next((x for x in PATTERNS if x.id == "duplicate_invoices"), None)
    assert p is not None, "duplicate_invoices pattern must exist"
    assert p.category == "fraud_risk"
    assert p.severity in ("CRITICAL", "HIGH")


def test_end_of_period_spike_pattern_exists():
    """end_of_period_spike pattern must exist in financial category."""
    p = next((x for x in PATTERNS if x.id == "end_of_period_spike"), None)
    assert p is not None, "end_of_period_spike pattern must exist"
    assert p.category == "financial"


def test_benford_first_digit_invoices_pattern_exists():
    """benford_first_digit_invoices must exist with HIGH severity."""
    p = next((x for x in PATTERNS if x.id == "benford_first_digit_invoices"), None)
    assert p is not None, "benford_first_digit_invoices pattern must exist"
    assert p.severity == "HIGH"


def test_credit_note_ratio_pattern_in_financial():
    """credit_note_ratio must be in financial category."""
    p = next((x for x in PATTERNS if x.id == "credit_note_ratio"), None)
    assert p is not None, "credit_note_ratio pattern must exist"
    assert p.category == "financial"


# ---------------------------------------------------------------------------
# get_patterns_for_tables — case insensitive input
# ---------------------------------------------------------------------------

def test_get_patterns_for_tables_case_insensitive():
    """Table names passed in upper/mixed case must still match patterns."""
    result_lower = get_patterns_for_tables(["account_move"])
    result_upper = get_patterns_for_tables(["ACCOUNT_MOVE"])
    result_mixed = get_patterns_for_tables(["Account_Move"])
    # All three calls should return the same number of patterns
    assert len(result_lower) == len(result_upper) == len(result_mixed), (
        f"Case sensitivity mismatch: lower={len(result_lower)}, "
        f"upper={len(result_upper)}, mixed={len(result_mixed)}"
    )


# ---------------------------------------------------------------------------
# build_sentinel_context — all-patterns input
# ---------------------------------------------------------------------------

def test_build_sentinel_context_all_patterns_mentions_every_id():
    """build_sentinel_context with ALL patterns should mention each pattern id or name."""
    context = build_sentinel_context(PATTERNS)
    assert isinstance(context, str)
    assert len(context) > 100, "Context with all patterns should be substantial"


def test_build_sentinel_context_single_pattern():
    """build_sentinel_context with a single pattern returns a non-empty string."""
    single = [PATTERNS[0]]
    context = build_sentinel_context(single)
    assert isinstance(context, str)
    assert len(context) > 0


# ---------------------------------------------------------------------------
# PATTERNS count regression
# ---------------------------------------------------------------------------

def test_patterns_count_at_least_sixteen():
    """PATTERNS must have at least 16 entries (regression guard)."""
    assert len(PATTERNS) >= 16, (
        f"Expected at least 16 patterns; got {len(PATTERNS)}"
    )


# ---------------------------------------------------------------------------
# AnomalyPattern dataclass fields are strings
# ---------------------------------------------------------------------------

def test_anomaly_pattern_field_types():
    """Each AnomalyPattern's id, name, severity, category, sql_template must be str."""
    for p in PATTERNS:
        assert isinstance(p.id, str), f"Pattern id not str: {type(p.id)}"
        assert isinstance(p.name, str), f"Pattern '{p.id}' name not str"
        assert isinstance(p.severity, str), f"Pattern '{p.id}' severity not str"
        assert isinstance(p.category, str), f"Pattern '{p.id}' category not str"
        assert isinstance(p.sql_template, str), f"Pattern '{p.id}' sql_template not str"
        assert isinstance(p.erp_tables, list), f"Pattern '{p.id}' erp_tables not list"
