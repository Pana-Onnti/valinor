"""
KO Report HTML template — Vaire.

Genera HTML completo del KO Report v3 con tokens D4C.
Usa string templates (sin dependencia de Jinja2) para portabilidad.

Design principles:
  - Minto Pyramid: Situation -> Complication -> Resolution per finding
  - Loss framing (Kahneman): "you are losing $X/month" not "you could save $X"
  - Hero numbers: large, prominent key metrics at the top
  - Tufte: high data-ink ratio, no chartjunk, clear typography
"""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Any


# -- D4C Design Tokens ---------------------------------------------------------

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
    'CRITICAL': 'Critico',
    'HIGH':     'Alto',
    'MEDIUM':   'Medio',
    'LOW':      'Bajo',
    'INFO':     'Info',
}


# -- Helpers -------------------------------------------------------------------

def _badge(severity: str) -> str:
    color = SEV_COLOR.get(severity, ACCENT_BLUE)
    label = SEV_LABEL.get(severity, severity)
    return (
        f'<span style="font-family:{FONT_MONO};font-size:10px;font-weight:600;'
        f'letter-spacing:0.05em;text-transform:uppercase;color:{color};'
        f'background:{color}20;border:1px solid {color}40;'
        f'border-radius:8px;padding:2px 8px;">{escape(label)}</span>'
    )


def _hero_number(value: str, label: str, color: str = ACCENT_TEAL) -> str:
    """Large, prominent metric -- Tufte: let the number speak."""
    return f"""
    <div style="text-align:center;padding:0 12px;">
      <div style="font-family:{FONT_MONO};font-size:36px;font-weight:700;
                  color:{color};line-height:1.1;letter-spacing:-0.02em;">
        {escape(str(value))}
      </div>
      <div style="font-family:{FONT_DISPLAY};font-size:11px;font-weight:500;
                  color:{TEXT_SECONDARY};margin-top:4px;letter-spacing:0.03em;
                  text-transform:uppercase;">
        {escape(label)}
      </div>
    </div>
    """


def _minto_finding_card(f: dict[str, Any]) -> str:
    """
    Finding card with Minto Pyramid structure:
      Situation -> Complication -> Resolution
    Falls back to flat body if Minto fields are absent (backward compat).
    """
    severity = f.get('severity', 'INFO')
    color = SEV_COLOR.get(severity, ACCENT_BLUE)
    fid = escape(str(f.get('id', '')))
    title = escape(str(f.get('title', '')))

    # Minto fields (optional -- backward compatible)
    situation = escape(str(f.get('situation', '')))
    complication = escape(str(f.get('complication', '')))
    resolution = escape(str(f.get('resolution', '')))
    body = escape(str(f.get('body', '')))

    # Build Minto structure if fields are present, otherwise fall back to body
    has_minto = any([situation, complication, resolution])

    if has_minto:
        minto_html = ''
        label_style = (
            f'font-family:{FONT_MONO};font-size:9px;font-weight:600;'
            f'letter-spacing:0.08em;text-transform:uppercase;'
            f'color:{TEXT_TERTIARY};margin-bottom:2px;'
        )
        text_style = (
            f'font-family:{FONT_DISPLAY};font-size:13px;'
            f'color:{TEXT_SECONDARY};line-height:1.5;margin:0;'
        )

        if situation:
            minto_html += f"""
            <div style="margin-bottom:8px;">
              <div style="{label_style}">Situacion</div>
              <p style="{text_style}">{situation}</p>
            </div>
            """
        if complication:
            minto_html += f"""
            <div style="margin-bottom:8px;">
              <div style="{label_style}color:{color};">Complicacion</div>
              <p style="{text_style}">{complication}</p>
            </div>
            """
        if resolution:
            minto_html += f"""
            <div>
              <div style="{label_style}color:{ACCENT_TEAL};">Resolucion</div>
              <p style="{text_style}">{resolution}</p>
            </div>
            """

        detail_html = f'<div style="margin-top:12px;padding-top:10px;border-top:1px solid {BG_HOVER};">{minto_html}</div>'
    elif body:
        detail_html = (
            f'<p style="font-family:{FONT_DISPLAY};font-size:13px;color:{TEXT_SECONDARY};'
            f'margin:12px 0 0 0;line-height:1.6;">{body}</p>'
        )
    else:
        detail_html = ''

    # Loss-framed impact line (if present)
    impact = f.get('impact', '')
    impact_html = ''
    if impact:
        impact_html = (
            f'<div style="margin-top:10px;padding:8px 12px;'
            f'background:{ACCENT_RED}10;border-left:2px solid {ACCENT_RED};'
            f'border-radius:0 6px 6px 0;">'
            f'<span style="font-family:{FONT_MONO};font-size:12px;font-weight:600;'
            f'color:{ACCENT_RED};">{escape(str(impact))}</span>'
            f'</div>'
        )

    return f"""
    <div style="background:{BG_CARD};border:1px solid {BG_HOVER};
                border-left:3px solid {color};border-radius:12px;
                padding:16px 20px;margin-bottom:10px;">
      <div style="display:flex;align-items:flex-start;gap:10px;">
        {_badge(severity)}
        <div style="flex:1;">
          <div style="font-family:{FONT_MONO};font-size:10px;
                      color:{TEXT_TERTIARY};margin-bottom:4px;">{fid}</div>
          <div style="font-family:{FONT_DISPLAY};font-size:14px;font-weight:600;
                      color:{TEXT_PRIMARY};line-height:1.4;">{title}</div>
        </div>
      </div>
      {impact_html}
      {detail_html}
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


def _sparkline_bar(value: float, max_value: float = 1.0, color: str = ACCENT_TEAL) -> str:
    """Tufte-style inline sparkline bar -- minimal, no chrome."""
    pct = min(100, max(0, (value / max_value) * 100)) if max_value > 0 else 0
    return (
        f'<div style="width:100%;height:4px;background:{BG_HOVER};border-radius:2px;overflow:hidden;">'
        f'<div style="width:{pct:.0f}%;height:100%;background:{color};border-radius:2px;"></div>'
        f'</div>'
    )


# -- Main renderer -------------------------------------------------------------

def render_ko_report_html(
    company_name: str,
    run_date: str,
    dq_score: float,
    findings: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
) -> str:
    """Genera HTML completo del KO Report v3 con Minto + loss framing + Tufte."""

    today = date.today().strftime('%d de %B de %Y')
    metrics = metrics or {}

    critical = [f for f in findings if f.get('severity') == 'CRITICAL']
    high     = [f for f in findings if f.get('severity') == 'HIGH']
    other    = [f for f in findings if f.get('severity') not in ('CRITICAL', 'HIGH')]

    # Ordenar: CRITICAL -> HIGH -> resto
    ordered = critical + high + other

    # DQ badge
    dq_pct = round(dq_score * 100)
    dq_color = ACCENT_TEAL if dq_score >= 0.8 else ACCENT_YELLOW if dq_score >= 0.6 else ACCENT_RED

    # Severity summary
    sev_html = ''
    if critical:
        sev_html += f'<span style="font-family:{FONT_MONO};font-size:10px;color:{ACCENT_RED};">{len(critical)} critico(s)</span> '
    if high:
        sev_html += f'<span style="font-family:{FONT_MONO};font-size:10px;color:{ACCENT_ORANGE};">{len(high)} alto(s)</span>'

    # ── Hero numbers section (Tufte: let the data speak) ─────────────────────
    hero_items = []

    # Total findings
    hero_items.append(_hero_number(
        str(len(findings)),
        'Hallazgos',
        ACCENT_RED if critical else ACCENT_YELLOW if high else ACCENT_TEAL,
    ))

    # Critical count
    if critical:
        hero_items.append(_hero_number(
            str(len(critical)),
            'Criticos',
            ACCENT_RED,
        ))

    # DQ score
    hero_items.append(_hero_number(
        f'{dq_pct}%',
        'Calidad de datos',
        dq_color,
    ))

    # Custom metrics from pipeline (loss-framed numbers)
    monthly_loss = metrics.get('monthly_loss') or metrics.get('perdida_mensual')
    if monthly_loss:
        hero_items.append(_hero_number(
            f'${monthly_loss:,.0f}' if isinstance(monthly_loss, (int, float)) else str(monthly_loss),
            'Perdida mensual estimada',
            ACCENT_RED,
        ))

    annual_risk = metrics.get('annual_risk') or metrics.get('riesgo_anual')
    if annual_risk:
        hero_items.append(_hero_number(
            f'${annual_risk:,.0f}' if isinstance(annual_risk, (int, float)) else str(annual_risk),
            'Riesgo anual',
            ACCENT_ORANGE,
        ))

    hero_html = ''.join(hero_items) if hero_items else ''
    hero_section = f"""
    <div style="display:flex;justify-content:center;gap:32px;flex-wrap:wrap;
                padding:24px 0;margin-bottom:32px;
                border-bottom:1px solid {BG_ELEVATED};">
      {hero_html}
    </div>
    """ if hero_html else ''

    # Pre-compute strings that contain special chars (can't use \u in f-strings)
    middot = '\u00b7'
    exec_subtitle = f'{company_name} {middot} {run_date}'
    footer_left = f'Generado por Valinor {middot} Delta 4C {middot} {today}'

    # ── Loss-framed headline ─────────────────────────────────────────────────
    headline = ''
    if critical:
        loss_text = ''
        if monthly_loss:
            formatted = f'${monthly_loss:,.0f}' if isinstance(monthly_loss, (int, float)) else str(monthly_loss)
            loss_text = f' Esta perdiendo aproximadamente {formatted}/mes.'

        headline = f"""
        <div style="background:{ACCENT_RED}08;border:1px solid {ACCENT_RED}30;
                    border-left:3px solid {ACCENT_RED};
                    border-radius:0 12px 12px 0;padding:16px 20px;margin-bottom:24px;">
          <div style="font-family:{FONT_DISPLAY};font-size:18px;font-weight:700;
                      color:{TEXT_PRIMARY};line-height:1.4;">
            {escape(company_name)} tiene {len(critical)} problema{'s' if len(critical) > 1 else ''} critico{'s' if len(critical) > 1 else ''} que requieren accion inmediata.{loss_text}
          </div>
        </div>
        """
    elif high:
        headline = f"""
        <div style="background:{ACCENT_ORANGE}08;border:1px solid {ACCENT_ORANGE}30;
                    border-left:3px solid {ACCENT_ORANGE};
                    border-radius:0 12px 12px 0;padding:16px 20px;margin-bottom:24px;">
          <div style="font-family:{FONT_DISPLAY};font-size:18px;font-weight:700;
                      color:{TEXT_PRIMARY};line-height:1.4;">
            {escape(company_name)} tiene {len(high)} hallazgo{'s' if len(high) > 1 else ''} de alta prioridad que merecen atencion.
          </div>
        </div>
        """

    # ── Severity distribution (Tufte sparkline bars, no chart chrome) ────────
    total = len(findings) or 1
    sev_dist_html = ''
    sev_counts = [
        ('CRITICAL', len(critical), ACCENT_RED),
        ('HIGH', len(high), ACCENT_ORANGE),
        ('MEDIUM', len([f for f in findings if f.get('severity') == 'MEDIUM']), ACCENT_YELLOW),
        ('LOW', len([f for f in findings if f.get('severity') == 'LOW']), ACCENT_BLUE),
    ]
    if findings:
        rows = ''
        for sev_name, count, color in sev_counts:
            if count > 0:
                rows += f"""
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
                  <span style="font-family:{FONT_MONO};font-size:10px;color:{color};
                              width:60px;text-transform:uppercase;letter-spacing:0.05em;">
                    {SEV_LABEL.get(sev_name, sev_name)}
                  </span>
                  <div style="flex:1;">{_sparkline_bar(count, total, color)}</div>
                  <span style="font-family:{FONT_MONO};font-size:11px;color:{TEXT_SECONDARY};
                              width:24px;text-align:right;">{count}</span>
                </div>
                """
        if rows:
            sev_dist_html = f"""
            <div style="margin-bottom:32px;padding:16px;background:{BG_CARD};
                        border:1px solid {BG_HOVER};border-radius:12px;">
              <div style="font-family:{FONT_MONO};font-size:10px;color:{TEXT_TERTIARY};
                          text-transform:uppercase;letter-spacing:0.08em;margin-bottom:12px;">
                Distribucion por severidad
              </div>
              {rows}
            </div>
            """

    # ── Findings HTML ────────────────────────────────────────────────────────
    findings_html = ''.join(_minto_finding_card(f) for f in ordered)
    if not findings_html:
        findings_html = f'<p style="font-family:{FONT_DISPLAY};font-size:13px;color:{TEXT_TERTIARY};">Sin hallazgos registrados.</p>'

    # ── DQ score bar (Tufte: small-multiple inline) ──────────────────────────
    dq_bar_html = f"""
    <div style="display:flex;align-items:center;gap:8px;">
      <span style="font-family:{FONT_MONO};font-size:11px;color:{TEXT_TERTIARY};">DQ</span>
      <div style="width:80px;">{_sparkline_bar(dq_score, 1.0, dq_color)}</div>
      <span style="font-family:{FONT_MONO};font-size:13px;font-weight:700;color:{dq_color};">{dq_pct}%</span>
    </div>
    """

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
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    /* Tufte: generous line-height for readability */
    p {{ line-height: 1.6; }}
    @media print {{
      body {{ background: #fff; color: #111; }}
      .no-print {{ display: none !important; }}
    }}
  </style>
</head>
<body>
  <!-- Nav Header — minimal, Tufte-style -->
  <header style="background:{BG_CARD};border-bottom:1px solid {BG_HOVER};
                 padding:14px 32px;display:flex;align-items:center;
                 justify-content:space-between;position:sticky;top:0;z-index:100;">
    <div style="display:flex;align-items:center;gap:16px;">
      <span style="font-family:{FONT_MONO};font-size:14px;font-weight:700;
                   color:{ACCENT_TEAL};letter-spacing:-0.02em;">VALINOR</span>
      <div style="width:1px;height:16px;background:{BG_HOVER};"></div>
      <span style="font-family:{FONT_DISPLAY};font-size:13px;color:{TEXT_SECONDARY};">Intelligence Report</span>
    </div>
    <div style="display:flex;align-items:center;gap:24px;">
      {dq_bar_html}
      {sev_html}
    </div>
  </header>

  <!-- Body -->
  <main style="max-width:960px;margin:0 auto;padding:48px 32px;">

    <!-- Hero Numbers -->
    {hero_section}

    <!-- 01 Executive Summary (Minto: answer first) -->
    <section style="margin-bottom:48px;">
      {_section_header('01', 'Resumen Ejecutivo', exec_subtitle)}
      {headline}
    </section>

    <!-- Severity Distribution (Tufte sparklines) -->
    {sev_dist_html}

    <!-- 02 Hallazgos (Minto: supporting arguments) -->
    <section style="margin-bottom:48px;">
      {_section_header('02', 'Hallazgos', f'{len(findings)} hallazgos ordenados por severidad')}
      {findings_html}
    </section>

    <!-- Footer — minimal, Tufte -->
    <footer style="border-top:1px solid {BG_ELEVATED};padding-top:24px;
                   display:flex;justify-content:space-between;align-items:center;">
      <span style="font-family:{FONT_MONO};font-size:11px;color:{TEXT_TERTIARY};">
        {footer_left}
      </span>
      <span style="font-family:{FONT_MONO};font-size:11px;color:{TEXT_TERTIARY};">
        {escape(run_date)}
      </span>
    </footer>
  </main>
</body>
</html>"""
