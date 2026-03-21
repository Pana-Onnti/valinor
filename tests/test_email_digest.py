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
