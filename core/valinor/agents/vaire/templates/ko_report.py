"""
KO Report HTML template — Vairë.

Genera HTML completo del KO Report v2 con tokens D4C.
Usa string templates (sin dependencia de Jinja2) para portabilidad.
"""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Any


# ── D4C Design Tokens ─────────────────────────────────────────────────────────

BG_PRIMARY  = '#0A0A0F'
BG_CARD     = '#111116'
BG_ELEVATED = '#1A1A22'
BG_HOVER    = '#222230'

TEXT_PRIMARY   = '#F0F0F5'
TEXT_SECONDARY = '#8A8A9A'
TEXT_TERTIARY  = '#5A5A6A'

ACCENT_TEAL   = '#2A9D8F'
ACCENT_RED    = '#E63946'
ACCENT_YELLOW = '#E9C46A'
ACCENT_ORANGE = '#F4845F'
ACCENT_BLUE   = '#85B7EB'

FONT_DISPLAY = "'Inter', 'DM Sans', system-ui, sans-serif"
FONT_MONO    = "'JetBrains Mono', 'Fira Code', monospace"

SEV_COLOR = {
    'CRITICAL': ACCENT_RED,
    'HIGH':     ACCENT_ORANGE,
    'MEDIUM':   ACCENT_YELLOW,
    'LOW':      ACCENT_BLUE,
    'INFO':     ACCENT_BLUE,
}

SEV_LABEL = {
    'CRITICAL': 'Crítico',
    'HIGH':     'Alto',
    'MEDIUM':   'Medio',
    'LOW':      'Bajo',
    'INFO':     'Info',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _badge(severity: str) -> str:
    color = SEV_COLOR.get(severity, ACCENT_BLUE)
    label = SEV_LABEL.get(severity, severity)
    return (
        f'<span style="font-family:{FONT_MONO};font-size:10px;font-weight:600;'
        f'letter-spacing:0.05em;text-transform:uppercase;color:{color};'
        f'background:{color}20;border:1px solid {color}40;'
        f'border-radius:8px;padding:2px 8px;">{escape(label)}</span>'
    )


def _finding_card(f: dict[str, Any]) -> str:
    severity = f.get('severity', 'INFO')
    color = SEV_COLOR.get(severity, ACCENT_BLUE)
    fid = escape(str(f.get('id', '')))
    title = escape(str(f.get('title', '')))
    body = escape(str(f.get('body', '')))

    return f"""
    <div style="background:{BG_CARD};border:1px solid {BG_HOVER};
                border-left:3px solid {color};border-radius:12px;
                padding:16px 20px;margin-bottom:10px;">
      <div style="display:flex;align-items:flex-start;gap:10px;">
        {_badge(severity)}
        <div>
          <div style="font-family:{FONT_MONO};font-size:10px;
                      color:{TEXT_TERTIARY};margin-bottom:4px;">{fid}</div>
          <div style="font-family:{FONT_DISPLAY};font-size:14px;font-weight:600;
                      color:{TEXT_PRIMARY};line-height:1.4;">{title}</div>
        </div>
      </div>
      {f'<p style="font-family:{FONT_DISPLAY};font-size:13px;color:{TEXT_SECONDARY};margin:12px 0 0 0;line-height:1.6;">{body}</p>' if body else ''}
    </div>
    """


def _section_header(num: str, title: str, description: str = '') -> str:
    desc_html = (
        f'<p style="font-family:{FONT_DISPLAY};font-size:13px;'
        f'color:{TEXT_SECONDARY};margin:4px 0 0 0;">{escape(description)}</p>'
        if description else ''
    )
    return f"""
    <div style="margin-bottom:24px;">
      <div style="display:flex;align-items:baseline;gap:16px;">
        <span style="font-family:{FONT_MONO};font-size:32px;font-weight:700;
                     color:{ACCENT_TEAL}50;line-height:1;">{num}</span>
        <h2 style="font-family:{FONT_DISPLAY};font-size:18px;font-weight:700;
                   color:{TEXT_PRIMARY};margin:0;">{escape(title)}</h2>
      </div>
      {desc_html}
    </div>
    """


# ── Main renderer ─────────────────────────────────────────────────────────────

def render_ko_report_html(
    company_name: str,
    run_date: str,
    dq_score: float,
    findings: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
) -> str:
    """Genera HTML completo del KO Report v2 con tokens D4C."""

    today = date.today().strftime('%d de %B de %Y')

    critical = [f for f in findings if f.get('severity') == 'CRITICAL']
    high     = [f for f in findings if f.get('severity') == 'HIGH']
    other    = [f for f in findings if f.get('severity') not in ('CRITICAL', 'HIGH')]

    # Ordenar: CRITICAL → HIGH → resto
    ordered = critical + high + other

    # DQ badge
    dq_pct = round(dq_score * 100)
    dq_color = ACCENT_TEAL if dq_score >= 0.8 else ACCENT_YELLOW if dq_score >= 0.6 else ACCENT_RED

    # Severity summary
    sev_html = ''
    if critical:
        sev_html += f'<span style="font-family:{FONT_MONO};font-size:10px;color:{ACCENT_RED};">{len(critical)} crítico(s)</span> '
    if high:
        sev_html += f'<span style="font-family:{FONT_MONO};font-size:10px;color:{ACCENT_ORANGE};">{len(high)} alto(s)</span>'

    # Headline loss framing
    headline = ''
    if critical:
        headline = f"""
        <div style="background:{ACCENT_RED}10;border:1px solid {ACCENT_RED}40;border-left:3px solid {ACCENT_RED};
                    border-radius:12px;padding:16px 20px;margin-bottom:24px;">
          <div style="font-family:{FONT_DISPLAY};font-size:20px;font-weight:700;
                      color:{TEXT_PRIMARY};line-height:1.3;">
            {escape(company_name)} tiene {len(critical)} problema{'s' if len(critical) > 1 else ''} crítico{'s' if len(critical) > 1 else ''} que requieren acción inmediata.
          </div>
        </div>
        """

    # Findings HTML
    findings_html = ''.join(_finding_card(f) for f in ordered)
    if not findings_html:
        findings_html = f'<p style="font-family:{FONT_DISPLAY};font-size:13px;color:{TEXT_TERTIARY};">Sin hallazgos registrados.</p>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Valinor KO Report — {escape(company_name)}</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: {BG_PRIMARY};
      color: {TEXT_PRIMARY};
      font-family: {FONT_DISPLAY};
      min-height: 100vh;
    }}
    @media print {{
      .no-print {{ display: none !important; }}
    }}
  </style>
</head>
<body>
  <!-- Nav Header -->
  <header style="background:{BG_CARD};border-bottom:1px solid {BG_HOVER};
                 padding:14px 32px;display:flex;align-items:center;
                 justify-content:space-between;position:sticky;top:0;z-index:100;">
    <div style="display:flex;align-items:center;gap:16px;">
      <span style="font-family:{FONT_MONO};font-size:14px;font-weight:700;
                   color:{ACCENT_TEAL};letter-spacing:-0.02em;">◈ VALINOR</span>
      <div style="width:1px;height:16px;background:{BG_HOVER};"></div>
      <span style="font-family:{FONT_DISPLAY};font-size:13px;color:{TEXT_SECONDARY};">Intelligence Report</span>
    </div>
    <div style="display:flex;align-items:center;gap:24px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="font-family:{FONT_MONO};font-size:11px;color:{TEXT_TERTIARY};">DQ</span>
        <span style="font-family:{FONT_MONO};font-size:13px;font-weight:700;color:{dq_color};">{dq_pct}%</span>
      </div>
      {sev_html}
    </div>
  </header>

  <!-- Body -->
  <main style="max-width:960px;margin:0 auto;padding:48px 32px;">

    <!-- 01 Executive Summary -->
    <section style="margin-bottom:48px;">
      {_section_header('01', 'Resumen Ejecutivo', f'{company_name} · {run_date}')}
      {headline}
    </section>

    <!-- 02 Hallazgos -->
    <section style="margin-bottom:48px;">
      {_section_header('02', 'Hallazgos', f'{len(findings)} hallazgos ordenados por severidad')}
      {findings_html}
    </section>

    <!-- Footer -->
    <footer style="border-top:1px solid {BG_ELEVATED};padding-top:24px;
                   display:flex;justify-content:space-between;align-items:center;">
      <span style="font-family:{FONT_MONO};font-size:11px;color:{TEXT_TERTIARY};">
        Generado por Valinor · Delta 4C · {today}
      </span>
      <span style="font-family:{FONT_MONO};font-size:11px;color:{TEXT_TERTIARY};">
        {escape(run_date)}
      </span>
    </footer>
  </main>
</body>
</html>"""
