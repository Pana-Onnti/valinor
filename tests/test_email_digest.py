"""
Unit tests for EmailDigestBuilder and send_digest / maybe_send_digest.

All SMTP interactions are mocked via unittest.mock — no real network calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
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
        profile.metadata["notification_email"] = notification_email
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
# TestEmailDigestBuilder
# ---------------------------------------------------------------------------

class TestEmailDigestBuilder:
    """Tests for EmailDigestBuilder.build_html() and build_subject()."""

    def setup_method(self):
        self.builder = EmailDigestBuilder()

    # 1. HTML contains client name
    def test_build_html_contains_client_name(self):
        profile = make_profile(client_name="AcmeCorp")
        html = self.builder.build_html(profile, make_run_results(), make_delta())
        assert "AcmeCorp" in html

    # 2. HTML mentions new finding IDs
    def test_build_html_contains_new_findings(self):
        new_findings = [
            {"id": "FIND-001", "title": "Revenue drop", "severity": "HIGH"},
            {"id": "FIND-002", "title": "Null spike", "severity": "MEDIUM"},
        ]
        delta = make_delta(new=new_findings)
        profile = make_profile()
        html = self.builder.build_html(profile, make_run_results(), delta)
        assert "FIND-001" in html
        assert "FIND-002" in html

    # 3. DQ score >= 85 uses green colour (#27ae60)
    def test_build_html_dq_score_green_when_high(self):
        run_results = make_run_results(dq_score=92.0)
        html = self.builder.build_html(make_profile(), run_results, make_delta())
        # The DQ badge must reference the green hex colour or CSS class
        assert "#27ae60" in html or "green" in html

    # 4. Subject has red circle emoji when critical findings exist
    def test_build_subject_critical_emoji(self):
        delta = make_delta(new=[
            {"id": "FIND-001", "title": "Critical issue", "severity": "CRITICAL"},
        ])
        subject = self.builder.build_subject("AcmeCorp", delta, dq_score=80.0)
        assert "\U0001f534" in subject  # 🔴

    # 5. Subject has green checkmark emoji when no critical findings
    def test_build_subject_ok_emoji(self):
        delta = make_delta(new=[
            {"id": "FIND-003", "title": "Minor warning", "severity": "LOW"},
        ])
        subject = self.builder.build_subject("AcmeCorp", delta, dq_score=90.0)
        assert "\u2705" in subject  # ✅

        # Also check when delta is completely empty
        subject_empty = self.builder.build_subject("AcmeCorp", make_delta(), dq_score=90.0)
        assert "\u2705" in subject_empty


# ---------------------------------------------------------------------------
# TestSendDigest
# ---------------------------------------------------------------------------

class TestSendDigest:
    """Tests for send_digest() SMTP delivery function."""

    # 1. Mock smtplib.SMTP and verify sendmail is called
    def test_send_digest_calls_smtp(self):
        env_vars = {
            "SMTP_HOST":     "smtp.example.com",
            "SMTP_PORT":     "587",
            "SMTP_USER":     "user@example.com",
            "SMTP_PASSWORD": "secret",
            "SMTP_FROM":     "noreply@valinor.io",
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
        # SMTP was instantiated with correct host/port
        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
        # sendmail was called with the right recipient
        mock_server.sendmail.assert_called_once()
        call_args = mock_server.sendmail.call_args
        assert "client@acmecorp.com" in call_args[0][1]

    # 2. Missing env vars → returns False gracefully (no exception)
    def test_send_digest_returns_false_when_no_env_vars(self):
        # Override all SMTP vars to empty strings so they appear unset.
        # send_digest treats empty strings as missing and returns False without raising.
        empty_env = {
            "SMTP_HOST":     "",
            "SMTP_PORT":     "587",
            "SMTP_USER":     "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM":     "",
        }
        with patch.dict("os.environ", empty_env, clear=False):
            result = send_digest(
                to_email="client@acmecorp.com",
                subject="Should not send",
                html_body="<p>irrelevant</p>",
            )

        assert result is False
