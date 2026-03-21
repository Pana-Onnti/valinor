"""
Tests for shared/pdf_generator.py

Covers:
  - generate_pdf_report output format and content
  - Helper functions: _escape_pdf_string, _wrap_lines
  - Edge cases: missing fields, Unicode, long text, None values
"""

import sys
import re

sys.path.insert(0, ".")

# Evict any stub injected by test_api_endpoints so we import the real module
sys.modules.pop("shared.pdf_generator", None)

import pytest
from shared.pdf_generator import generate_pdf_report, _escape_pdf_string, _wrap_lines


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RESULTS = {
    "job_id": "job-abc-123",
    "client_name": "Acme Corp",
    "period": "Q1-2026",
    "status": "completed",
    "execution_time_seconds": 47.3,
    "timestamp": "2026-03-21T10:00:00",
    "findings": {
        "analyst": {
            "findings": [
                {"severity": "CRITICAL", "description": "Revenue discrepancy > 5%"},
                {"severity": "HIGH", "description": "AR aging > 90 days spike"},
            ]
        },
        "sentinel": {
            "findings": [
                {"severity": "MEDIUM", "description": "Unusual access pattern"},
            ]
        },
    },
    "reports": {
        "executive": (
            "Valinor ha completado el analisis de Acme Corp para Q1-2026.\n\n"
            "Se detectaron 3 hallazgos criticos que requieren atencion inmediata."
        )
    },
}


# ---------------------------------------------------------------------------
# Test 1: generate_pdf_report returns bytes
# ---------------------------------------------------------------------------

def test_generate_pdf_report_returns_bytes():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert isinstance(result, bytes)


# ---------------------------------------------------------------------------
# Test 2: Output starts with %PDF magic bytes
# ---------------------------------------------------------------------------

def test_pdf_starts_with_magic_bytes():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert result.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# Test 3: Output length > 1000 bytes
# ---------------------------------------------------------------------------

def test_pdf_length_above_minimum():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert len(result) > 1000


# ---------------------------------------------------------------------------
# Test 4: PDF contains %%EOF marker
# ---------------------------------------------------------------------------

def test_pdf_contains_eof_marker():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert b"%%EOF" in result


# ---------------------------------------------------------------------------
# Test 5: job_id appears in the PDF content stream
# ---------------------------------------------------------------------------

def test_job_id_in_pdf():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert b"job-abc-123" in result


# ---------------------------------------------------------------------------
# Test 6: client_name appears in the PDF content stream
# ---------------------------------------------------------------------------

def test_client_name_in_pdf():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert b"Acme Corp" in result


# ---------------------------------------------------------------------------
# Test 7: period appears in the PDF content stream
# ---------------------------------------------------------------------------

def test_period_in_pdf():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert b"Q1-2026" in result


# ---------------------------------------------------------------------------
# Test 8: total findings count is correct (2 + 1 = 3)
# ---------------------------------------------------------------------------

def test_total_findings_count():
    result = generate_pdf_report(SAMPLE_RESULTS)
    # The header line reads "Total Findings: 3"
    assert b"Total Findings: 3" in result


# ---------------------------------------------------------------------------
# Test 9: executive text is included in the output
# ---------------------------------------------------------------------------

def test_executive_text_included():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert b"Valinor ha completado" in result


# ---------------------------------------------------------------------------
# Test 10: Missing fields fall back gracefully (empty dict input)
# ---------------------------------------------------------------------------

def test_empty_dict_fallback():
    result = generate_pdf_report({})
    assert isinstance(result, bytes)
    assert result.startswith(b"%PDF-")
    assert b"N/A" in result
    assert b"%%EOF" in result


# ---------------------------------------------------------------------------
# Test 11: Euro symbol € is handled (no UnicodeEncodeError)
# ---------------------------------------------------------------------------

def test_euro_symbol_no_encode_error():
    results = dict(SAMPLE_RESULTS)
    results["reports"] = {"executive": "Revenue is 1000\u20ac this quarter."}
    # Should not raise
    pdf = generate_pdf_report(results)
    assert isinstance(pdf, bytes)
    # € should be replaced by "EUR" in the stream
    assert b"EUR" in pdf


# ---------------------------------------------------------------------------
# Test 12: Non-latin-1 chars are replaced not lost (£, ¥, curly quotes)
# ---------------------------------------------------------------------------

def test_non_latin1_chars_replaced():
    text = "Price: \u00a3100 or \u00a51200 or \u2018quoted\u2019"
    escaped = _escape_pdf_string(text)
    # Original symbols should NOT appear (they're replaced)
    assert "\u00a3" not in escaped
    assert "\u00a5" not in escaped
    assert "\u2018" not in escaped
    assert "\u2019" not in escaped
    # Replacements should be present
    assert "GBP" in escaped
    assert "JPY" in escaped
    # Result should be encodable as latin-1
    escaped.encode("latin-1")


# ---------------------------------------------------------------------------
# Test 13: Long executive text is truncated to 2000 chars
# ---------------------------------------------------------------------------

def test_long_executive_text_truncated():
    long_text = "A" * 5000
    results = {"reports": {"executive": long_text}}
    pdf = generate_pdf_report(results)
    assert isinstance(pdf, bytes)
    # The truncation to 2000 means we won't have 5000 A's; check PDF is generated
    # and doesn't contain more than ~2000 A's in a run
    content = pdf.decode("latin-1", errors="replace")
    # Find the longest run of 'A' characters
    runs = re.findall(r"A+", content)
    longest_run = max(len(r) for r in runs) if runs else 0
    assert longest_run <= 2000


# ---------------------------------------------------------------------------
# Test 14: generate_pdf_report with None execution_time shows N/A
# ---------------------------------------------------------------------------

def test_none_execution_time_shows_na():
    results = dict(SAMPLE_RESULTS)
    results["execution_time_seconds"] = None
    pdf = generate_pdf_report(results)
    assert b"N/A" in pdf


# ---------------------------------------------------------------------------
# Test 15: generate_pdf_report with nested findings counts correctly
# ---------------------------------------------------------------------------

def test_nested_findings_count():
    results = {
        "findings": {
            "agent_a": {"findings": [{"id": 1}, {"id": 2}, {"id": 3}]},
            "agent_b": {"findings": [{"id": 4}]},
            "agent_c": {},  # no 'findings' key — should count 0
        }
    }
    pdf = generate_pdf_report(results)
    assert b"Total Findings: 4" in pdf


# ---------------------------------------------------------------------------
# Test 16: _escape_pdf_string escapes parentheses: ( → \(
# ---------------------------------------------------------------------------

def test_escape_pdf_string_parentheses():
    result = _escape_pdf_string("hello (world)")
    assert r"\(" in result
    assert r"\)" in result
    assert "(" not in result.replace(r"\(", "")
    assert ")" not in result.replace(r"\)", "")


# ---------------------------------------------------------------------------
# Test 17: _escape_pdf_string escapes backslash: \ → \\
# ---------------------------------------------------------------------------

def test_escape_pdf_string_backslash():
    result = _escape_pdf_string("path\\to\\file")
    assert "\\\\" in result


# ---------------------------------------------------------------------------
# Test 18: _wrap_lines returns correct number of lines for short text
# ---------------------------------------------------------------------------

def test_wrap_lines_correct_count():
    text = "Line one\nLine two\nLine three"
    lines = _wrap_lines(text, max_chars=90)
    # Each non-empty paragraph becomes one line (all < 90 chars)
    assert len(lines) == 3
    assert lines[0] == "Line one"
    assert lines[1] == "Line two"
    assert lines[2] == "Line three"


# ---------------------------------------------------------------------------
# Test 19: _wrap_lines handles empty paragraph
# ---------------------------------------------------------------------------

def test_wrap_lines_empty_paragraph():
    text = "First paragraph\n\nSecond paragraph"
    lines = _wrap_lines(text, max_chars=90)
    # Should produce: ["First paragraph", "", "Second paragraph"]
    assert "" in lines
    assert "First paragraph" in lines
    assert "Second paragraph" in lines


# ---------------------------------------------------------------------------
# Test 20: PDF is valid enough to contain a parseable cross-reference table
# ---------------------------------------------------------------------------

def test_pdf_has_valid_xref_table():
    pdf = generate_pdf_report(SAMPLE_RESULTS)
    content = pdf.decode("latin-1", errors="replace")

    # Must have xref keyword
    assert "xref" in content

    # Must have startxref keyword followed by a number
    match = re.search(r"startxref\s+(\d+)", content)
    assert match is not None, "startxref not found in PDF"

    xref_offset = int(match.group(1))
    # The xref offset must be within the bounds of the PDF
    assert 0 < xref_offset < len(pdf)

    # Verify the xref table is actually at that offset
    xref_region = pdf[xref_offset:xref_offset + 4]
    assert xref_region == b"xref", (
        f"Expected 'xref' at offset {xref_offset}, got {xref_region!r}"
    )


# ---------------------------------------------------------------------------
# Test 21: Status field appears in PDF output
# ---------------------------------------------------------------------------

def test_status_field_in_pdf():
    result = generate_pdf_report(SAMPLE_RESULTS)
    assert b"completed" in result


# ---------------------------------------------------------------------------
# Test 22: execution_time_seconds is formatted with one decimal place
# ---------------------------------------------------------------------------

def test_execution_time_formatted():
    results = dict(SAMPLE_RESULTS)
    results["execution_time_seconds"] = 12.5
    pdf = generate_pdf_report(results)
    assert b"12.5s" in pdf


# ---------------------------------------------------------------------------
# Test 23: Zero findings count shows "Total Findings: 0"
# ---------------------------------------------------------------------------

def test_zero_findings_count():
    results = {"findings": {}}
    pdf = generate_pdf_report(results)
    assert b"Total Findings: 0" in pdf


# ---------------------------------------------------------------------------
# Test 24: findings dict with non-dict values counts only dict entries
# ---------------------------------------------------------------------------

def test_findings_non_dict_values_ignored():
    results = {
        "findings": {
            "agent_a": {"findings": [{"id": 1}, {"id": 2}]},
            "agent_b": "this is not a dict",
            "agent_c": 42,
        }
    }
    pdf = generate_pdf_report(results)
    assert b"Total Findings: 2" in pdf


# ---------------------------------------------------------------------------
# Test 25: PDF contains "EXECUTIVE SUMMARY" section header
# ---------------------------------------------------------------------------

def test_executive_summary_section_header():
    pdf = generate_pdf_report(SAMPLE_RESULTS)
    assert b"EXECUTIVE SUMMARY" in pdf


# ---------------------------------------------------------------------------
# Test 26: PDF contains "VALINOR SAAS" branding
# ---------------------------------------------------------------------------

def test_pdf_contains_valinor_branding():
    pdf = generate_pdf_report(SAMPLE_RESULTS)
    assert b"VALINOR SAAS" in pdf


# ---------------------------------------------------------------------------
# Test 27: Curly quotes are replaced by straight quotes
# ---------------------------------------------------------------------------

def test_curly_quotes_replaced():
    text = "\u201cHello\u201d and \u2018world\u2019"
    escaped = _escape_pdf_string(text)
    assert "\u201c" not in escaped
    assert "\u201d" not in escaped
    assert "\u2018" not in escaped
    assert "\u2019" not in escaped
    # Should be encodable as latin-1
    escaped.encode("latin-1")


# ---------------------------------------------------------------------------
# Test 28: En-dash and em-dash are replaced with ASCII hyphens
# ---------------------------------------------------------------------------

def test_dashes_replaced():
    text = "period\u2013to\u2014end"
    escaped = _escape_pdf_string(text)
    assert "\u2013" not in escaped
    assert "\u2014" not in escaped
    assert "-" in escaped


# ---------------------------------------------------------------------------
# Test 29: Ellipsis character is replaced with "..."
# ---------------------------------------------------------------------------

def test_ellipsis_replaced():
    text = "loading\u2026"
    escaped = _escape_pdf_string(text)
    assert "\u2026" not in escaped
    assert "..." in escaped


# ---------------------------------------------------------------------------
# Test 30: _wrap_lines with long single word exceeding max_chars
# ---------------------------------------------------------------------------

def test_wrap_lines_very_long_word():
    long_word = "A" * 200
    lines = _wrap_lines(long_word, max_chars=90)
    # textwrap.wrap will break the word across lines; all chunks <= 90 chars (or one chunk)
    assert len(lines) >= 1
    for line in lines:
        assert len(line) <= 200  # at minimum, no line explodes beyond original


# ---------------------------------------------------------------------------
# Test 31: _wrap_lines returns empty string for blank-only input
# ---------------------------------------------------------------------------

def test_wrap_lines_blank_input():
    lines = _wrap_lines("", max_chars=90)
    # Empty string has no splitlines() → returns empty list
    assert lines == []


# ---------------------------------------------------------------------------
# Test 32: generate_pdf_report with missing "reports" key still generates PDF
# ---------------------------------------------------------------------------

def test_missing_reports_key_fallback():
    results = {
        "job_id": "job-no-report",
        "client_name": "Ghost Corp",
        "period": "Q2-2026",
    }
    pdf = generate_pdf_report(results)
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-")
    assert b"No executive report available" in pdf
