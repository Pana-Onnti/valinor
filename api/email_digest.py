"""
Email Digest Generator for Valinor SaaS.
Generates HTML email summaries of analysis results.
Can send via SMTP or just return HTML for preview.
"""
from __future__ import annotations
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional, List
from datetime import datetime

import structlog

logger = structlog.get_logger()


def _dq_color(score: int) -> str:
    """Return hex color string for a DQ score."""
    if score >= 85:
        return "#16a34a"
    elif score >= 65:
        return "#d97706"
    elif score >= 45:
        return "#ea580c"
    else:
        return "#dc2626"


def build_digest_html(
    client_name: str,
    period: str,
    run_delta: Dict,
    findings_summary: Dict,
    top_findings: List[Dict],
    kpi_history: Optional[Dict] = None,
    triggered_alerts: Optional[List[Dict]] = None,
    data_quality: Optional[Dict] = None,
) -> str:
    """Build a complete HTML email digest."""

    critical = findings_summary.get("critical", 0)
    high = findings_summary.get("high", 0)
    new_count = len(run_delta.get("new", []))
    resolved_count = len(run_delta.get("resolved", []))

    # Determine headline
    if critical > 0:
        headline_color = "#DC2626"
        headline = f"⚠️ {critical} hallazgo{'s' if critical > 1 else ''} crítico{'s' if critical > 1 else ''} requieren atención"
    elif high > 0:
        headline_color = "#EA580C"
        headline = f"🔶 {high} hallazgo{'s' if high > 1 else ''} de alta prioridad detectado{'s' if high > 1 else ''}"
    elif resolved_count > 0:
        headline_color = "#059669"
        headline = f"✅ {resolved_count} issue{'s' if resolved_count > 1 else ''} resuelto{'s' if resolved_count > 1 else ''} — sistema mejorando"
    else:
        headline_color = "#7C3AED"
        headline = "📊 Análisis completado — sin cambios críticos"

    # Build top findings HTML
    findings_html = ""
    for f in top_findings[:5]:
        sev = f.get("severity", "INFO").upper()
        colors_map = {
            "CRITICAL": ("#FEF2F2", "#DC2626", "🔴"),
            "HIGH":     ("#FFF7ED", "#EA580C", "🟠"),
            "MEDIUM":   ("#FFFBEB", "#D97706", "🟡"),
            "LOW":      ("#EFF6FF", "#2563EB", "🔵"),
        }
        bg, fg, icon = colors_map.get(sev, ("#F9FAFB", "#6B7280", "⚪"))
        is_new = f.get("id", "") in run_delta.get("new", [])
        new_badge = '<span style="background:#7C3AED;color:white;font-size:10px;padding:2px 6px;border-radius:10px;margin-left:6px;">NUEVO</span>' if is_new else ""

        findings_html += f"""
        <tr>
          <td style="padding:12px;background:{bg};border-left:3px solid {fg};border-radius:0 6px 6px 0;">
            <div style="font-size:13px;font-weight:600;color:#111827;">
              {icon} {f.get('title', f.get('id', ''))} {new_badge}
            </div>
            <div style="font-size:11px;color:#6B7280;margin-top:4px;">
              {f.get('id','')} · {sev}
            </div>
          </td>
        </tr>
        <tr><td style="padding:3px 0;"></td></tr>"""

    # KPI snapshot
    kpi_html = ""
    if kpi_history:
        kpi_html = '<tr><td style="padding:12px 0 6px;"><div style="font-size:12px;font-weight:700;color:#374151;letter-spacing:0.08em;text-transform:uppercase;">KPIs</div></td></tr>'
        for label, points in list(kpi_history.items())[:4]:
            if not points:
                continue
            latest = points[-1]
            prev = points[-2] if len(points) > 1 else None
            trend = ""
            if prev and latest.get("numeric_value") and prev.get("numeric_value"):
                diff = latest["numeric_value"] - prev["numeric_value"]
                trend_color = "#059669" if diff >= 0 else "#DC2626"
                trend_arrow = "▲" if diff >= 0 else "▼"
                trend = f' <span style="color:{trend_color}">{trend_arrow} {abs(diff):.1f}</span>'

            kpi_html += f"""
            <tr>
              <td style="padding:6px 12px;background:#F9FAFB;border-radius:6px;margin-bottom:4px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <span style="font-size:11px;color:#6B7280;">{label}</span>
                  <span style="font-size:13px;font-weight:700;color:#111827;">{latest.get('value', '—')}{trend}</span>
                </div>
              </td>
            </tr>
            <tr><td style="padding:2px 0;"></td></tr>"""

    # Pre-compute stats row to avoid backslash-in-f-string (Python < 3.12)
    _td_sep = '<td width="8"></td>'
    _stats_items = [
        ("Críticos", critical, "#DC2626"),
        ("Altos", high, "#EA580C"),
        ("Nuevos", new_count, "#7C3AED"),
        ("Resueltos", resolved_count, "#059669"),
    ]
    stats_row_html = _td_sep.join(
        f'<td align="center" style="background:#F9FAFB;border-radius:8px;padding:12px;">'
        f'<div style="font-size:22px;font-weight:800;color:{c};">{v}</div>'
        f'<div style="font-size:10px;color:#9CA3AF;margin-top:2px;">{l}</div></td>'
        for l, v, c in _stats_items
    )

    # Pre-compute DQ row
    dq_row_html = ""
    if data_quality:
        dq_score = data_quality.get("score", 0)
        dq_label = data_quality.get("confidence_label") or data_quality.get("label", "")
        dq_tag = data_quality.get("tag", "")
        dq_color_val = _dq_color(int(dq_score) if isinstance(dq_score, (int, float)) else 0)
        dq_display = f"{dq_score}/100 {dq_label}" if dq_label else f"{dq_score}/100"
        if dq_tag:
            dq_display = f"{dq_display} · {dq_tag}"
        dq_row_html = (
            '<tr>'
            '<td style="padding:4px 12px;font-size:11px;color:#6B7280;">Calidad datos</td>'
            f'<td style="padding:4px 12px;font-size:11px;font-weight:bold;color:{dq_color_val};">'
            f'{dq_display}</td>'
            '</tr>'
        )

    # Pre-compute DQ section
    if dq_row_html:
        dq_row_section = (
            '<tr><td style="padding:0 32px 8px;">'
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="background:#F5F3FF;border-radius:6px;border:1px solid #DDD6FE;">'
            + dq_row_html +
            '</table></td></tr>'
        )
    else:
        dq_row_section = ''

    # Pre-compute findings section
    if findings_html:
        findings_section = (
            '<tr><td style="padding:0 32px;">'
            '<div style="font-size:11px;font-weight:700;color:#374151;letter-spacing:0.08em;'
            'text-transform:uppercase;margin-bottom:8px;">HALLAZGOS PRIORITARIOS</div>'
            '<table width="100%" cellpadding="0" cellspacing="0">'
            + findings_html +
            '</table></td></tr>'
        )
    else:
        findings_section = ''

    # Pre-compute KPIs section
    kpis_section = (
        f'<tr><td style="padding:8px 32px 0;"><table width="100%">{kpi_html}</table></td></tr>'
        if kpi_html else ''
    )

    # Pre-compute alerts section
    alerts_section = build_alerts_section(triggered_alerts) if triggered_alerts else ''

    # Pre-compute date string
    today_str = datetime.utcnow().strftime('%d/%m/%Y')

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Valinor — {client_name} — {period}</title>
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#F3F4F6;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F3F4F6;padding:32px 16px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:white;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

        <!-- Header -->
        <tr>
          <td style="background:#08090F;padding:24px 32px;">
            <table width="100%"><tr>
              <td>
                <div style="color:#7C3AED;font-size:11px;font-weight:700;letter-spacing:0.15em;text-transform:uppercase;margin-bottom:4px;">VALINOR · Delta4C</div>
                <div style="color:white;font-size:20px;font-weight:800;">{client_name}</div>
                <div style="color:rgba(255,255,255,0.5);font-size:12px;margin-top:2px;">{period} · {today_str}</div>
              </td>
              <td align="right" style="vertical-align:top;">
                <div style="background:rgba(124,58,237,0.2);border:1px solid rgba(124,58,237,0.4);color:#A78BFA;font-size:10px;font-weight:700;padding:4px 10px;border-radius:20px;letter-spacing:0.1em;">ANÁLISIS COMPLETADO</div>
              </td>
            </tr></table>
          </td>
        </tr>

        <!-- Headline -->
        <tr>
          <td style="padding:24px 32px 0;">
            <div style="font-size:16px;font-weight:700;color:{headline_color};">{headline}</div>
          </td>
        </tr>

        <!-- Stats row -->
        <tr>
          <td style="padding:16px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                {stats_row_html}
              </tr>
            </table>
          </td>
        </tr>

        <!-- DQ row -->
        {dq_row_section}

        <!-- Triggered alerts -->
        {alerts_section}

        <!-- Findings -->
        {findings_section}

        <!-- KPIs -->
        {kpis_section}

        <!-- CTA -->
        <tr>
          <td style="padding:24px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0"><tr>
              <td>
                <a href="http://localhost:3000" style="display:inline-block;background:#7C3AED;color:white;font-size:13px;font-weight:700;padding:12px 24px;border-radius:8px;text-decoration:none;">Ver reporte completo →</a>
              </td>
            </tr></table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#F9FAFB;border-top:1px solid #E5E7EB;padding:16px 32px;">
            <div style="font-size:10px;color:#9CA3AF;text-align:center;">
              Valinor SaaS · Delta4C · Análisis de solo lectura — sin almacenamiento de datos del cliente<br>
              Análisis verificado con 8 controles de calidad — Aislamiento REPEATABLE READ<br>
              Para desuscribirse, contacte a su administrador.
            </div>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    return html


def build_alerts_section(alerts: List[Dict]) -> str:
    """Build the '⚠️ Alertas Disparadas' section as a colored severity table."""
    if not alerts:
        return ""

    _severity_styles = {
        "CRITICAL": ("#FEF2F2", "#DC2626"),
        "HIGH":     ("#FFF7ED", "#EA580C"),
        "MEDIUM":   ("#FFFBEB", "#D97706"),
    }
    _default_style = ("#F9FAFB", "#6B7280")

    header = (
        '<tr style="background:#F3F4F6;">'
        '<th style="padding:6px 10px;font-size:10px;color:#6B7280;font-weight:700;text-align:left;text-transform:uppercase;">Alerta</th>'
        '<th style="padding:6px 10px;font-size:10px;color:#6B7280;font-weight:700;text-align:left;text-transform:uppercase;">Métrica</th>'
        '<th style="padding:6px 10px;font-size:10px;color:#6B7280;font-weight:700;text-align:right;text-transform:uppercase;">Valor</th>'
        '<th style="padding:6px 10px;font-size:10px;color:#6B7280;font-weight:700;text-align:right;text-transform:uppercase;">Umbral</th>'
        '</tr>'
    )

    rows = ""
    for a in alerts:
        sev = a.get("severity", a.get("level", "HIGH")).upper()
        bg, fg = _severity_styles.get(sev, _default_style)
        name = a.get("name", a.get("threshold_label", "Alerta"))
        metric = a.get("metric", a.get("metric_name", "—"))
        value = a.get("computed_value", a.get("current_value", "—"))
        threshold = a.get("threshold", a.get("threshold_value", "—"))
        operator = a.get("operator", ">")
        rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:8px 10px;font-size:12px;font-weight:600;color:{fg};border-left:3px solid {fg};">{name}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#374151;">{metric}</td>'
            f'<td style="padding:8px 10px;font-size:12px;font-weight:700;color:{fg};text-align:right;">{value}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#6B7280;text-align:right;">{operator} {threshold}</td>'
            '</tr>'
        )

    table = (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;border:1px solid #FECACA;border-radius:8px;overflow:hidden;">'
        + header + rows +
        '</table>'
    )

    return (
        '<tr><td style="padding:0 32px 16px;">'
        '<div style="font-size:11px;font-weight:700;color:#DC2626;letter-spacing:0.08em;'
        'text-transform:uppercase;margin-bottom:8px;">⚠️ ALERTAS DISPARADAS</div>'
        + table +
        '</td></tr>'
    )


async def send_digest(
    to_email: str,
    subject: str,
    html_content: str,
) -> bool:
    """Send email via SMTP. Returns True if sent successfully."""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("SMTP_FROM", "valinor@delta4c.com")

    if not smtp_host:
        logger.warning("SMTP not configured — email not sent")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to_email
        msg.attach(MIMEText(html_content, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, to_email, msg.as_string())

        logger.info("Email digest sent", to=to_email)
        return True
    except Exception as e:
        logger.error("Failed to send email digest", error=str(e))
        return False
