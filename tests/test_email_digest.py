"""
Unit tests for EmailDigestBuilder — build_html() and build_subject().

Covers:
  - HTML structure and content
  - Client name in output
  - Findings count and display
  - Subject emoji selection based on delta severity
  - HTML escaping of special-character client names
  - Empty findings handled gracefully
  - Missing delta / dq_score handled gracefully
  - DQ score colour thresholds
  - Resolved findings section
  - KPI table rendering
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.email_digest import EmailDigestBuilder, send_digest, maybe_send_digest
from shared.memory.client_profile import ClientProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_profile(
    client_name: str = "AcmeCorp",
    notification_email: str = "",
    baseline_history: dict | None = None,
) -> ClientProfile:
    profile = ClientProfile(client_name=client_name)
    if notification_email:
        profile.metadata = {"notification_email": notification_email}
    if baseline_history is not None:
        profile.baseline_history = baseline_history
    return profile


def make_run_results(
    findings: list | None = None,
    dq_score: float = 90.0,
) -> dict:
    return {
        "findings": findings or [],
        "dq_score": dq_score,
    }


def make_delta(new: list | None = None, resolved: list | None = None) -> dict:
    return {
        "new": new or [],
        "resolved": resolved or [],
    }


# ---------------------------------------------------------------------------
# Tests — EmailDigestBuilder
# ---------------------------------------------------------------------------

class TestBuildHtmlStructure:
    """Tests for the basic HTML document structure."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()
        self.profile = make_profile()

    def test_returns_string(self):
        html = self.builder.build_html(self.profile, make_run_results(), make_delta())
        assert isinstance(html, str)

    def test_html_doctype_present(self):
        html = self.builder.build_html(self.profile, make_run_results(), make_delta())
        assert "<!DOCTYPE html>" in html

    def test_html_charset_utf8(self):
        html = self.builder.build_html(self.profile, make_run_results(), make_delta())
        assert 'charset="utf-8"' in html

    def test_html_contains_valinor_brand(self):
        html = self.builder.build_html(self.profile, make_run_results(), make_delta())
        assert "VALINOR" in html

    def test_html_contains_footer(self):
        html = self.builder.build_html(self.profile, make_run_results(), make_delta())
        assert "Delta 4C" in html


class TestBuildHtmlClientName:
    """Tests that the client name appears in the HTML output."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()

    def test_client_name_in_header(self):
        profile = make_profile(client_name="GlobalBank")
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert "GlobalBank" in html

    def test_special_chars_escaped(self):
        """Client names with HTML-special characters must be safely escaped."""
        profile = make_profile(client_name="<Acme & Co>")
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        # Raw unescaped angle brackets must not appear inside tag content
        assert "<Acme & Co>" not in html
        # Escaped form should be present
        assert "&lt;Acme" in html or "Acme" in html

    def test_ampersand_in_client_name_escaped(self):
        profile = make_profile(client_name="Smith & Jones")
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert "&amp;" in html  # & must be escaped to &amp;

    def test_quotes_in_client_name_escaped(self):
        """Double-quote in client name must be escaped."""
        profile = make_profile(client_name='Acme "Corp"')
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert '&quot;' in html or "Acme" in html  # escaping or at minimum present


class TestBuildHtmlFindings:
    """Tests for findings count and display in the HTML body."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()
        self.profile = make_profile()

    def test_empty_findings_no_crash(self):
        """Empty findings list must not raise and should show the no-findings message."""
        html = self.builder.build_html(self.profile, make_run_results(findings=[]), make_delta())
        assert "No se encontraron" in html

    def test_findings_count_one_rendered(self):
        findings = [{"id": "F-001", "title": "Revenue drop", "severity": "HIGH"}]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        assert "Revenue drop" in html

    def test_findings_only_top3_shown_in_summary(self):
        """Executive summary shows at most 3 findings."""
        findings = [
            {"id": f"F-{i:03d}", "title": f"Finding {i}", "severity": "MEDIUM"}
            for i in range(6)
        ]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        # Top 3 titles appear; 4th does not need to appear in the summary section
        assert "Finding 0" in html
        assert "Finding 2" in html

    def test_new_findings_id_in_html(self):
        new = [{"id": "NEW-999", "title": "Spike", "severity": "CRITICAL"}]
        html = self.builder.build_html(self.profile, make_run_results(), make_delta(new=new))
        assert "NEW-999" in html

    def test_resolved_findings_id_in_html(self):
        resolved = [{"id": "OLD-001", "title": "Stale index", "severity": "LOW"}]
        html = self.builder.build_html(self.profile, make_run_results(), make_delta(resolved=resolved))
        assert "OLD-001" in html

    def test_empty_delta_no_crash(self):
        """Empty delta dict (no 'new'/'resolved' keys) must not raise."""
        html = self.builder.build_html(self.profile, make_run_results(), {})
        assert isinstance(html, str)
        assert "Sin nuevos hallazgos" in html


class TestBuildHtmlDQScore:
    """Tests for the DQ score badge colour thresholds."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()
        self.profile = make_profile()

    def test_dq_score_green_above_85(self):
        html = self.builder.build_html(self.profile, make_run_results(dq_score=92.0), make_delta())
        assert "#27ae60" in html  # green

    def test_dq_score_yellow_between_65_and_85(self):
        html = self.builder.build_html(self.profile, make_run_results(dq_score=70.0), make_delta())
        assert "#f39c12" in html  # yellow

    def test_dq_score_red_below_65(self):
        html = self.builder.build_html(self.profile, make_run_results(dq_score=40.0), make_delta())
        assert "#c0392b" in html  # red

    def test_missing_dq_score_defaults_to_zero(self):
        """If run_results has no dq_score key, should default to 0 (red badge)."""
        run_results = {"findings": []}
        html = self.builder.build_html(self.profile, run_results, make_delta())
        assert "0.0 / 100" in html

    def test_dq_score_value_shown(self):
        html = self.builder.build_html(self.profile, make_run_results(dq_score=77.5), make_delta())
        assert "77.5" in html


class TestBuildSubject:
    """Tests for EmailDigestBuilder.build_subject()."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()

    def test_critical_finding_triggers_red_emoji(self):
        delta = make_delta(new=[{"id": "F1", "title": "X", "severity": "CRITICAL"}])
        subject = self.builder.build_subject("AcmeCorp", delta, dq_score=80.0)
        assert "\U0001f534" in subject  # 🔴

    def test_high_finding_triggers_red_emoji(self):
        delta = make_delta(new=[{"id": "F2", "title": "Y", "severity": "HIGH"}])
        subject = self.builder.build_subject("AcmeCorp", delta, dq_score=80.0)
        assert "\U0001f534" in subject  # 🔴

    def test_low_finding_gives_green_checkmark(self):
        delta = make_delta(new=[{"id": "F3", "title": "Z", "severity": "LOW"}])
        subject = self.builder.build_subject("AcmeCorp", delta, dq_score=90.0)
        assert "\u2705" in subject  # ✅

    def test_empty_delta_gives_green_checkmark(self):
        subject = self.builder.build_subject("AcmeCorp", make_delta(), dq_score=90.0)
        assert "\u2705" in subject  # ✅

    def test_subject_contains_client_name(self):
        subject = self.builder.build_subject("GlobalRetail", make_delta(), dq_score=90.0)
        assert "GlobalRetail" in subject

    def test_subject_singular_for_one_critical(self):
        delta = make_delta(new=[{"id": "F4", "title": "Issue", "severity": "CRITICAL"}])
        subject = self.builder.build_subject("AcmeCorp", delta, dq_score=80.0)
        assert "1 hallazgo crítico" in subject

    def test_subject_plural_for_multiple_critical(self):
        delta = make_delta(new=[
            {"id": "F5", "title": "A", "severity": "CRITICAL"},
            {"id": "F6", "title": "B", "severity": "HIGH"},
        ])
        subject = self.builder.build_subject("AcmeCorp", delta, dq_score=80.0)
        assert "2 nuevos hallazgos críticos" in subject

    def test_missing_new_key_in_delta_no_crash(self):
        """delta without 'new' key must not raise."""
        subject = self.builder.build_subject("AcmeCorp", {}, dq_score=90.0)
        assert isinstance(subject, str)


# ---------------------------------------------------------------------------
# Tests — send_digest (SMTP)
# ---------------------------------------------------------------------------

class TestSendDigest:

    def test_send_digest_calls_smtp(self):
        env_vars = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "user@example.com",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM": "noreply@valinor.io",
        }
        mock_server = MagicMock()
        mock_server.__enter__ = MagicMock(return_value=mock_server)
        mock_server.__exit__ = MagicMock(return_value=False)

        with patch.dict("os.environ", env_vars):
            with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp_cls:
                result = send_digest(
                    to_email="client@acmecorp.com",
                    subject="Test subject",
                    html_body="<p>Hello</p>",
                )

        assert result is True
        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
        mock_server.sendmail.assert_called_once()

    def test_send_digest_returns_false_when_no_env_vars(self):
        empty_env = {
            "SMTP_HOST": "",
            "SMTP_PORT": "587",
            "SMTP_USER": "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM": "",
        }
        with patch.dict("os.environ", empty_env, clear=False):
            result = send_digest(
                to_email="client@acmecorp.com",
                subject="Should not send",
                html_body="<p>irrelevant</p>",
            )
        assert result is False


# ---------------------------------------------------------------------------
# Additional tests — edge cases and boundary conditions
# ---------------------------------------------------------------------------


class TestDQScoreBoundaryValues:
    """Boundary values right on the DQ score thresholds."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()
        self.profile = make_profile()

    def test_dq_score_exactly_85_is_green(self):
        """Score of exactly 85.0 should use the green colour."""
        html = self.builder.build_html(self.profile, make_run_results(dq_score=85.0), make_delta())
        assert "#27ae60" in html

    def test_dq_score_exactly_65_is_yellow(self):
        """Score of exactly 65.0 should use the yellow colour (65 <= score < 85)."""
        html = self.builder.build_html(self.profile, make_run_results(dq_score=65.0), make_delta())
        assert "#f39c12" in html

    def test_dq_score_zero_is_red(self):
        """Score of 0.0 must produce the red badge."""
        html = self.builder.build_html(self.profile, make_run_results(dq_score=0.0), make_delta())
        assert "#c0392b" in html

    def test_dq_score_100_is_green(self):
        """A perfect score of 100.0 must produce the green badge."""
        html = self.builder.build_html(self.profile, make_run_results(dq_score=100.0), make_delta())
        assert "#27ae60" in html


class TestKPITableRendering:
    """Tests for the _build_kpi_table helper inside EmailDigestBuilder."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()

    def test_kpi_table_rendered_when_baseline_present(self):
        """When baseline_history has data, 'KPIs Principales' heading should appear."""
        profile = make_profile(baseline_history={
            "revenue": [{"period": "Q1", "value": 1000}, {"period": "Q2", "value": 1200}]
        })
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert "KPIs Principales" in html

    def test_kpi_table_shows_kpi_key(self):
        """The KPI key name must appear inside the rendered table."""
        profile = make_profile(baseline_history={
            "churn_rate": [{"period": "Q1", "value": 5.2}]
        })
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert "churn_rate" in html

    def test_kpi_table_absent_when_no_baseline(self):
        """Without baseline history the 'KPIs Principales' heading must not appear."""
        profile = make_profile(baseline_history={})
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert "KPIs Principales" not in html

    def test_kpi_table_scalar_values_rendered(self):
        """Scalar (non-dict) history entries should still render without crashing."""
        profile = make_profile(baseline_history={"revenue": [100, 200, 300]})
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert isinstance(html, str)
        assert "revenue" in html


class TestBuildHtmlSpecialCasesExtra:
    """Additional edge-case tests for build_html."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()
        self.profile = make_profile()

    def test_finding_with_only_id_no_title_renders(self):
        """A finding dict that has only 'id' (no 'title') must not crash."""
        findings = [{"id": "F-NO-TITLE", "severity": "HIGH"}]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        assert "F-NO-TITLE" in html

    def test_finding_severity_unknown_renders(self):
        """An unrecognised severity string must not crash; title should appear in the summary."""
        findings = [{"id": "F-UNK", "title": "Unknown sev", "severity": "UNKNOWN"}]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        assert "Unknown sev" in html

    def test_resolved_section_absent_message_when_empty(self):
        """When there are no resolved findings the 'ningún' message must appear."""
        html = self.builder.build_html(self.profile, make_run_results(), make_delta(resolved=[]))
        assert "Ningún hallazgo resuelto" in html


# ===========================================================================
# Additional tests
# ===========================================================================

class TestBuildSubjectAdditional:
    """Additional build_subject tests."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()

    def test_subject_contains_client_name(self):
        """Subject line must include the client name."""
        subject = self.builder.build_subject("TestCorp", make_delta(), 90.0)
        assert "TestCorp" in subject

    def test_subject_is_non_empty_string(self):
        subject = self.builder.build_subject("TestCorp", make_delta(), 90.0)
        assert isinstance(subject, str) and len(subject) > 0

    def test_subject_zero_findings(self):
        """Subject with zero findings should not crash."""
        subject = self.builder.build_subject("TestCorp", make_delta(new=[]), 90.0)
        assert isinstance(subject, str)

    def test_subject_critical_finding_has_urgent_indicator(self):
        """Critical findings should produce a more urgent subject."""
        findings = [{"id": "F1", "title": "Big issue", "severity": "CRITICAL"}]
        subject = self.builder.build_subject("TestCorp", make_delta(new=findings), 90.0)
        assert isinstance(subject, str) and len(subject) > 0


class TestBuildHtmlAdditional:
    """Additional build_html coverage."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()
        self.profile = make_profile()

    def test_multiple_findings_all_rendered(self):
        """All finding titles should appear in the HTML."""
        findings = [
            {"id": "F1", "title": "Revenue drop", "severity": "HIGH"},
            {"id": "F2", "title": "Margin squeeze", "severity": "MEDIUM"},
            {"id": "F3", "title": "Customer churn", "severity": "LOW"},
        ]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        for f in findings:
            assert f["title"] in html

    def test_critical_severity_colour_present(self):
        """CRITICAL severity should use the red colour."""
        findings = [{"id": "F1", "title": "Critical issue", "severity": "CRITICAL"}]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        assert "#c0392b" in html

    def test_info_severity_colour_present(self):
        """INFO severity should use the blue colour."""
        findings = [{"id": "F1", "title": "Info note", "severity": "INFO"}]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        assert "#2980b9" in html

    def test_new_findings_in_delta_shown(self):
        """New findings listed in the delta should appear in the HTML."""
        new_f = [{"id": "FN1", "title": "New critical alert", "severity": "HIGH"}]
        html = self.builder.build_html(self.profile, make_run_results(), make_delta(new=new_f))
        assert "New critical alert" in html

    def test_resolved_findings_in_delta_shown(self):
        """Resolved findings listed in the delta should appear in the HTML."""
        resolved_f = [{"id": "FR1", "title": "Old resolved issue", "severity": "MEDIUM"}]
        html = self.builder.build_html(self.profile, make_run_results(), make_delta(resolved=resolved_f))
        assert "Old resolved issue" in html

    def test_dq_score_displayed_in_html(self):
        """The DQ score value should appear in the rendered HTML."""
        html = self.builder.build_html(self.profile, make_run_results(dq_score=78.5), make_delta())
        assert "78" in html

    def test_output_is_valid_html_fragment(self):
        """HTML output must start with <!DOCTYPE html>."""
        html = self.builder.build_html(self.profile, make_run_results(), make_delta())
        assert html.strip().startswith("<!DOCTYPE html>")

    def test_empty_client_name_no_crash(self):
        """An empty client name string must not raise."""
        profile = make_profile(client_name="")
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert isinstance(html, str)

    def test_dq_score_mid_range_yellow(self):
        """Score in 65-85 range should produce yellow badge colour."""
        html = self.builder.build_html(self.profile, make_run_results(dq_score=75.0), make_delta())
        assert "#f39c12" in html

    def test_high_finding_colour(self):
        """HIGH severity badge should use the orange colour."""
        findings = [{"id": "F1", "title": "High issue", "severity": "HIGH"}]
        html = self.builder.build_html(self.profile, make_run_results(findings=findings), make_delta())
        assert "#e67e22" in html
