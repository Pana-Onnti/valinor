"""
EmailDigest — builds and sends executive summary email digests after each analysis run.

Responsibilities:
  - Build an HTML email body from run results, delta, and client profile
  - Build a subject line that signals urgency via emoji
  - Send via SMTP using environment variables
  - Provide a convenience wrapper that reads notification preferences from the profile

Environment variables consumed by send_digest():
  SMTP_HOST       — SMTP server hostname (required)
  SMTP_PORT       — SMTP server port (default: 587)
  SMTP_USER       — SMTP login username (required)
  SMTP_PASSWORD   — SMTP login password (required)
  SMTP_FROM       — Sender address (required)
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Any, Dict, List, Optional

from shared.memory.client_profile import ClientProfile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity badge colours (inline CSS)
# ---------------------------------------------------------------------------

_SEVERITY_COLORS: Dict[str, str] = {
    "CRITICAL": "#c0392b",
    "HIGH":     "#e67e22",
    "MEDIUM":   "#f39c12",
    "LOW":      "#27ae60",
    "INFO":     "#2980b9",
}

_DQ_GREEN  = "#27ae60"
_DQ_YELLOW = "#f39c12"
_DQ_RED    = "#c0392b"


def _dq_color(score: float) -> str:
    if score >= 85:
        return _DQ_GREEN
    if score >= 65:
        return _DQ_YELLOW
    return _DQ_RED


def _dq_class(score: float) -> str:
    if score >= 85:
        return "green"
    if score >= 65:
        return "yellow"
    return "red"


def _severity_badge(severity: str) -> str:
    color = _SEVERITY_COLORS.get(severity.upper(), "#7f8c8d")
    label = escape(severity.upper())
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:3px;font-size:11px;font-weight:bold;">{label}</span>'
    )


# ---------------------------------------------------------------------------
# EmailDigestBuilder
# ---------------------------------------------------------------------------

class EmailDigestBuilder:
    """Builds HTML email bodies and subject lines for analysis digests."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_html(
        self,
        profile: ClientProfile,
        run_results: Dict[str, Any],
        delta: Dict[str, Any],
    ) -> str:
        """
        Build a complete HTML email body.

        Args:
            profile:     ClientProfile for the client being reported on.
            run_results: Dict with at least a "findings" key (list of finding dicts).
                         Each finding should have: id, title, severity.
                         Optionally: "dq_score" (float 0-100).
            delta:       Dict with "new" and "resolved" lists of finding dicts.

        Returns:
            Full HTML string ready to embed in a MIME message.
        """
        client_name = escape(profile.client_name)
        findings: List[Dict] = run_results.get("findings") or []
        new_findings: List[Dict] = delta.get("new") or []
        resolved_findings: List[Dict] = delta.get("resolved") or []
        dq_score: float = float(run_results.get("dq_score", 0))

        top3 = findings[:3]
        dq_color = _dq_color(dq_score)
        dq_cls = _dq_class(dq_score)

        sections: List[str] = []

        # ── Header ────────────────────────────────────────────────────
        sections.append(
            f"""
            <div style="background:#1a1a2e;padding:24px 32px;border-radius:8px 8px 0 0;">
              <div style="font-size:22px;font-weight:bold;color:#e0e0e0;letter-spacing:1px;">
                &#9670; VALINOR
              </div>
              <div style="font-size:16px;color:#a0a0c0;margin-top:4px;">
                Análisis completado &mdash; {client_name}
              </div>
            </div>
            """
        )

        # ── Executive Summary ─────────────────────────────────────────
        sections.append('<div style="padding:24px 32px;">')
        sections.append(
            '<h2 style="margin:0 0 12px;font-size:16px;color:#333;">Resumen Ejecutivo</h2>'
        )
        if top3:
            sections.append('<ul style="margin:0;padding-left:20px;">')
            for f in top3:
                title = escape(str(f.get("title", f.get("id", "—"))))
                sev = f.get("severity", "INFO")
                sections.append(
                    f'<li style="margin-bottom:6px;">{_severity_badge(sev)} {title}</li>'
                )
            sections.append("</ul>")
        else:
            sections.append(
                '<p style="color:#666;margin:0;">No se encontraron hallazgos en este análisis.</p>'
            )

        # ── New Findings ──────────────────────────────────────────────
        sections.append(
            '<h2 style="margin:20px 0 12px;font-size:16px;color:#333;">Nuevos Hallazgos</h2>'
        )
        if new_findings:
            sections.append('<ul style="margin:0;padding-left:20px;">')
            for f in new_findings:
                fid = escape(str(f.get("id", "—")))
                title = escape(str(f.get("title", fid)))
                sev = f.get("severity", "INFO")
                sections.append(
                    f'<li style="margin-bottom:6px;">'
                    f'<code style="font-size:11px;color:#888;">{fid}</code> '
                    f'{_severity_badge(sev)} {title}</li>'
                )
            sections.append("</ul>")
        else:
            sections.append(
                '<p style="color:#666;margin:0;">Sin nuevos hallazgos.</p>'
            )

        # ── Resolved Findings ─────────────────────────────────────────
        sections.append(
            '<h2 style="margin:20px 0 12px;font-size:16px;color:#333;">Hallazgos Resueltos</h2>'
        )
        if resolved_findings:
            sections.append('<ul style="margin:0;padding-left:20px;">')
            for f in resolved_findings:
                fid = escape(str(f.get("id", "—")))
                title = escape(str(f.get("title", fid)))
                sections.append(
                    f'<li style="margin-bottom:6px;color:#27ae60;">'
                    f'&#10003; <code style="font-size:11px;color:#888;">{fid}</code> {title}</li>'
                )
            sections.append("</ul>")
        else:
            sections.append(
                '<p style="color:#666;margin:0;">Ningún hallazgo resuelto en este ciclo.</p>'
            )

        # ── KPI Table ─────────────────────────────────────────────────
        kpi_html = self._build_kpi_table(profile)
        if kpi_html:
            sections.append(
                '<h2 style="margin:20px 0 12px;font-size:16px;color:#333;">KPIs Principales</h2>'
            )
            sections.append(kpi_html)

        # ── DQ Score Badge ────────────────────────────────────────────
        sections.append(
            '<h2 style="margin:20px 0 12px;font-size:16px;color:#333;">Data Quality Score</h2>'
        )
        sections.append(
            f'<span class="dq-score {dq_cls}" '
            f'style="display:inline-block;background:{dq_color};color:#fff;'
            f'padding:8px 20px;border-radius:20px;font-size:18px;font-weight:bold;">'
            f'{dq_score:.1f} / 100</span>'
        )

        sections.append("</div>")  # close padding div

        # ── Footer ────────────────────────────────────────────────────
        sections.append(
            '<div style="background:#f5f5f5;padding:16px 32px;border-radius:0 0 8px 8px;'
            'border-top:1px solid #e0e0e0;font-size:12px;color:#999;text-align:center;">'
            "Powered by Valinor &middot; Delta 4C"
            "</div>"
        )

        body = "\n".join(sections)
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
            f'<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;'
            f'background:#ffffff;border:1px solid #e0e0e0;border-radius:8px;">'
            f"{body}"
            "</body></html>"
        )

    def build_subject(
        self,
        client_name: str,
        delta: Dict[str, Any],
        dq_score: float,
    ) -> str:
        """
        Build an email subject line with urgency emoji.

        Rules:
          - Count CRITICAL and HIGH new findings in delta["new"].
          - If any CRITICAL/HIGH findings  → red circle prefix + count description.
          - Otherwise                      → green checkmark prefix.

        Args:
            client_name: Name of the client shown in the subject.
            delta:       Dict with "new" list of finding dicts (each has "severity").
            dq_score:    Data quality score (0-100), appended when below 65.

        Returns:
            Subject line string.
        """
        new_findings: List[Dict] = delta.get("new") or []
        critical_count = sum(
            1 for f in new_findings
            if f.get("severity", "").upper() in ("CRITICAL", "HIGH")
        )

        safe_name = client_name.strip()

        if critical_count > 0:
            noun = "hallazgo crítico" if critical_count == 1 else "nuevos hallazgos críticos"
            return f"\U0001f534 Valinor: {critical_count} {noun} \u2014 {safe_name}"

        # No critical/high findings
        return f"\u2705 Valinor: Análisis completado \u2014 {safe_name}"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_kpi_table(self, profile: ClientProfile) -> str:
        """Return an HTML table with the last 3 data points for the top 3 KPIs."""
        baseline: Dict[str, List[Any]] = profile.baseline_history or {}
        if not baseline:
            return ""

        top_kpis = list(baseline.keys())[:3]

        rows: List[str] = []
        for kpi_key in top_kpis:
            history: List[Any] = baseline[kpi_key] or []
            last3 = history[-3:]  # most recent last
            kpi_label = escape(str(kpi_key))
            for point in last3:
                if isinstance(point, dict):
                    period = escape(str(point.get("period", "—")))
                    value  = escape(str(point.get("value", point.get("numeric_value", "—"))))
                else:
                    period = "—"
                    value  = escape(str(point))
                rows.append(
                    f"<tr>"
                    f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">{kpi_label}</td>'
                    f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;color:#666;">{period}</td>'
                    f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;font-weight:bold;">{value}</td>'
                    f"</tr>"
                )

        if not rows:
            return ""

        header = (
            "<tr style='background:#f8f8f8;'>"
            "<th style='padding:8px 10px;text-align:left;font-size:12px;color:#666;'>KPI</th>"
            "<th style='padding:8px 10px;text-align:left;font-size:12px;color:#666;'>Período</th>"
            "<th style='padding:8px 10px;text-align:left;font-size:12px;color:#666;'>Valor</th>"
            "</tr>"
        )
        return (
            '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
            f"{header}{''.join(rows)}"
            "</table>"
        )


# ---------------------------------------------------------------------------
# SMTP delivery
# ---------------------------------------------------------------------------

def send_digest(to_email: str, subject: str, html_body: str) -> bool:
    """
    Send an HTML email via SMTP.

    Reads connection settings from environment variables:
      SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM

    Args:
        to_email:  Recipient address.
        subject:   Email subject.
        html_body: HTML content for the email body.

    Returns:
        True if the message was accepted by the server, False on any failure.
        Never raises — all exceptions are caught and logged.
    """
    smtp_host     = os.environ.get("SMTP_HOST", "").strip()
    smtp_port_str = os.environ.get("SMTP_PORT", "587").strip()
    smtp_user     = os.environ.get("SMTP_USER", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
    smtp_from     = os.environ.get("SMTP_FROM", "").strip()

    missing = [
        name for name, val in [
            ("SMTP_HOST", smtp_host),
            ("SMTP_USER", smtp_user),
            ("SMTP_PASSWORD", smtp_password),
            ("SMTP_FROM", smtp_from),
        ]
        if not val
    ]
    if missing:
        logger.warning(
            "send_digest: missing SMTP env vars %s — email not sent", missing
        )
        return False

    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        logger.warning("send_digest: invalid SMTP_PORT '%s', defaulting to 587", smtp_port_str)
        smtp_port = 587

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_from
    msg["To"]      = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_from, [to_email], msg.as_string())
        logger.info("send_digest: email sent to %s", to_email)
        return True
    except Exception as exc:
        logger.error("send_digest: failed to send email to %s — %s", to_email, exc)
        return False


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

def maybe_send_digest(
    profile: ClientProfile,
    run_results: Dict[str, Any],
    delta: Dict[str, Any],
) -> bool:
    """
    Send a digest email if the profile has a notification_email configured.

    Reads ``profile.metadata["notification_email"]``.  If the key is absent or
    empty, the function skips sending and returns False.

    Args:
        profile:     ClientProfile to read notification settings from.
        run_results: Passed through to EmailDigestBuilder.build_html().
        delta:       Passed through to EmailDigestBuilder.build_html() and build_subject().

    Returns:
        True if the email was successfully sent, False if skipped or failed.
    """
    to_email: Optional[str] = (profile.metadata or {}).get("notification_email", "")
    if not to_email:
        logger.debug(
            "maybe_send_digest: no notification_email set for client '%s', skipping",
            profile.client_name,
        )
        return False

    dq_score: float = float(run_results.get("dq_score", 0))
    builder = EmailDigestBuilder()
    html_body = builder.build_html(profile, run_results, delta)
    subject   = builder.build_subject(profile.client_name, delta, dq_score)

    return send_digest(to_email, subject, html_body)
