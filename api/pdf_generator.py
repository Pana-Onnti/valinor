"""
PDF Report Generator for Valinor SaaS.
Converts markdown executive reports to branded PDFs using ReportLab.
"""
from __future__ import annotations
import io
import re
from datetime import datetime
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, KeepTogether
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas

# ── Brand colors ──────────────────────────────────────────────────────────────
BRAND_DARK   = colors.HexColor('#08090F')
BRAND_VIOLET = colors.HexColor('#7C3AED')
BRAND_RED    = colors.HexColor('#DC2626')
BRAND_ORANGE = colors.HexColor('#EA580C')
BRAND_AMBER  = colors.HexColor('#D97706')
BRAND_GRAY   = colors.HexColor('#6B7280')
BRAND_LIGHT  = colors.HexColor('#F9FAFB')
WHITE        = colors.white

# ── DQ confidence colors ──────────────────────────────────────────────────────
DQ_GREEN  = colors.HexColor('#16a34a')
DQ_AMBER  = colors.HexColor('#d97706')
DQ_ORANGE = colors.HexColor('#ea580c')
DQ_RED    = colors.HexColor('#dc2626')

DQ_BG     = colors.HexColor('#EDE9FE')   # light violet/lavender background


def _dq_label_color(score: int):
    """Return (label_str, color) for a DQ score."""
    if score >= 85:
        return "CONFIRMED", DQ_GREEN
    elif score >= 65:
        return "PROVISIONAL", DQ_AMBER
    elif score >= 45:
        return "UNVERIFIED", DQ_ORANGE
    else:
        return "BLOCKED", DQ_RED


class BrandedPDFGenerator:
    """Generates a branded PDF from a Valinor executive report (markdown)."""

    def generate(
        self,
        report_markdown: str,
        client_name: str,
        period: str,
        run_delta: Optional[dict] = None,
        findings_summary: Optional[dict] = None,
        results: Optional[dict] = None,
    ) -> bytes:
        """Returns PDF as bytes."""
        buffer = io.BytesIO()
        results = results or {}

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2.2*cm,
            leftMargin=2.2*cm,
            topMargin=2.5*cm,
            bottomMargin=2.5*cm,
            title=f"Valinor — {client_name} — {period}",
            author="Valinor SaaS · Delta4C",
        )

        styles = self._build_styles()
        story = []

        # ── Cover header ──────────────────────────────────────────────────────
        story.append(self._cover_header(styles, client_name, period, run_delta))
        story.append(Spacer(1, 0.5*cm))

        # ── Summary stats bar ─────────────────────────────────────────────────
        if findings_summary:
            story.append(self._stats_bar(styles, findings_summary))
            story.append(Spacer(1, 0.4*cm))

        # ── Data Quality section ──────────────────────────────────────────────
        dq = results.get("data_quality")
        if dq:
            story.append(self._data_quality_section(styles, dq))
            story.append(Spacer(1, 0.35*cm))

            # ── Waterfall audit table ─────────────────────────────────────────
            snapshot_ts = (
                results.get("stages", {})
                .get("query_execution", {})
                .get("snapshot_timestamp")
            )
            if snapshot_ts:
                story.append(self._audit_table(styles, dq, snapshot_ts))
                story.append(Spacer(1, 0.35*cm))

        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E5E7EB')))
        story.append(Spacer(1, 0.4*cm))

        # ── Report body (markdown → reportlab) ───────────────────────────────
        dq_score = dq.get("score", 100) if dq else 100
        story.extend(self._parse_markdown(report_markdown, styles, dq_score=dq_score))

        # ── Footer note ───────────────────────────────────────────────────────
        story.append(Spacer(1, 0.8*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E5E7EB')))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            f"Generado por Valinor SaaS · Delta4C · {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC · "
            "Análisis de solo lectura — sin almacenamiento de datos del cliente.",
            styles['footer']
        ))

        # ── Triggered alerts section ──────────────────────────────────────────
        triggered_alerts = results.get("triggered_alerts", [])
        if triggered_alerts:
            story.append(Spacer(1, 0.4*cm))
            story.append(self._triggered_alerts_section(styles, triggered_alerts))

        # ── Provenance footer (last page) ─────────────────────────────────────
        if dq:
            story.append(Spacer(1, 0.4*cm))
            story.append(self._build_provenance_footer_table(results))

        doc.build(story, onFirstPage=self._page_header, onLaterPages=self._page_header)
        return buffer.getvalue()

    def _build_styles(self):
        styles = getSampleStyleSheet()

        custom = {
            'h1': ParagraphStyle('h1', fontName='Helvetica-Bold', fontSize=18,
                                  textColor=BRAND_DARK, spaceBefore=12, spaceAfter=6),
            'h2': ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=13,
                                  textColor=BRAND_VIOLET, spaceBefore=10, spaceAfter=4,
                                  borderPad=0, borderColor=BRAND_VIOLET),
            'h3': ParagraphStyle('h3', fontName='Helvetica-Bold', fontSize=11,
                                  textColor=BRAND_DARK, spaceBefore=8, spaceAfter=3),
            'body': ParagraphStyle('body', fontName='Helvetica', fontSize=9.5,
                                    textColor=colors.HexColor('#374151'),
                                    leading=15, spaceAfter=4),
            'bullet': ParagraphStyle('bullet', fontName='Helvetica', fontSize=9.5,
                                      textColor=colors.HexColor('#374151'),
                                      leading=14, leftIndent=14, spaceAfter=2,
                                      bulletIndent=4),
            'critical': ParagraphStyle('critical', fontName='Helvetica-Bold', fontSize=9.5,
                                        textColor=BRAND_RED, leading=14, spaceAfter=3),
            'high': ParagraphStyle('high', fontName='Helvetica-Bold', fontSize=9.5,
                                    textColor=BRAND_ORANGE, leading=14, spaceAfter=3),
            'kpi_label': ParagraphStyle('kpi_label', fontName='Helvetica', fontSize=8,
                                         textColor=BRAND_GRAY),
            'kpi_value': ParagraphStyle('kpi_value', fontName='Helvetica-Bold', fontSize=14,
                                         textColor=BRAND_DARK),
            'cover_title': ParagraphStyle('cover_title', fontName='Helvetica-Bold', fontSize=22,
                                           textColor=BRAND_DARK, spaceAfter=4),
            'cover_sub': ParagraphStyle('cover_sub', fontName='Helvetica', fontSize=11,
                                         textColor=BRAND_GRAY),
            'footer': ParagraphStyle('footer', fontName='Helvetica', fontSize=7.5,
                                      textColor=BRAND_GRAY, alignment=TA_CENTER),
        }
        return custom

    def _cover_header(self, styles, client_name, period, run_delta):
        data = [
            [Paragraph(f'<b>{client_name}</b>', styles['cover_title']),
             Paragraph('VALINOR', ParagraphStyle('brand', fontName='Helvetica-Bold',
                        fontSize=11, textColor=BRAND_VIOLET, alignment=TA_RIGHT))],
            [Paragraph(f'Análisis de Inteligencia de Negocio · {period}', styles['cover_sub']),
             Paragraph(datetime.utcnow().strftime('%d/%m/%Y'), ParagraphStyle('date',
                        fontName='Helvetica', fontSize=9, textColor=BRAND_GRAY, alignment=TA_RIGHT))],
        ]
        t = Table(data, colWidths=['75%', '25%'])
        t.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        return t

    def _stats_bar(self, styles, summary: dict):
        items = []
        for label, value, color in [
            ('Críticos', summary.get('critical', 0), BRAND_RED),
            ('Altos', summary.get('high', 0), BRAND_ORANGE),
            ('Medios', summary.get('medium', 0), BRAND_AMBER),
            ('Nuevos', summary.get('new', 0), BRAND_VIOLET),
            ('Resueltos', summary.get('resolved', 0), colors.HexColor('#059669')),
        ]:
            items.append([
                Paragraph(str(value), ParagraphStyle('sv', fontName='Helvetica-Bold',
                           fontSize=16, textColor=color, alignment=TA_CENTER)),
                Paragraph(label, ParagraphStyle('sl', fontName='Helvetica', fontSize=8,
                           textColor=BRAND_GRAY, alignment=TA_CENTER)),
            ])

        row1 = [items[i][0] for i in range(5)]
        row2 = [items[i][1] for i in range(5)]
        t = Table([row1, row2], colWidths=['20%']*5)
        t.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F9FAFB')),
            ('ROUNDEDCORNERS', [6,6,6,6]),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#E5E7EB')),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        return t

    # ── Data Quality section ──────────────────────────────────────────────────

    def _dq_score_bar(self, score: int, bar_width_pt: float = 340) -> Drawing:
        """
        Return a ReportLab Drawing that renders a coloured progress bar for
        the DQ score, e.g.  ████████░░  84/100
        """
        _, bar_color = _dq_label_color(score)
        bar_h = 10
        drawing = Drawing(bar_width_pt, bar_h + 4)

        # Background track
        drawing.add(Rect(
            0, 2, bar_width_pt * 0.72, bar_h,
            fillColor=colors.HexColor('#E5E7EB'),
            strokeColor=None,
            rx=3, ry=3,
        ))
        # Filled portion
        fill_w = max(4, bar_width_pt * 0.72 * score / 100)
        drawing.add(Rect(
            0, 2, fill_w, bar_h,
            fillColor=bar_color,
            strokeColor=None,
            rx=3, ry=3,
        ))
        # Score label to the right of the bar
        drawing.add(String(
            bar_width_pt * 0.72 + 8, 3,
            f'{score}/100',
            fontName='Helvetica-Bold',
            fontSize=9,
            fillColor=colors.HexColor('#1F2937'),
        ))
        return drawing

    def _dq_checks_table(self, checks: list) -> Table:
        """
        Build a compact table showing each DQ check: name, status, score impact.
        Expected check dict keys: name (str), passed (bool), impact (int, optional).
        """
        header_style = ParagraphStyle('dqch', fontName='Helvetica-Bold', fontSize=7.5,
                                       textColor=WHITE)
        cell_style = ParagraphStyle('dqcc', fontName='Helvetica', fontSize=7.5,
                                     textColor=BRAND_DARK)
        ok_style = ParagraphStyle('dqco', fontName='Helvetica-Bold', fontSize=7.5,
                                   textColor=DQ_GREEN)
        fail_style = ParagraphStyle('dqcf', fontName='Helvetica-Bold', fontSize=7.5,
                                     textColor=DQ_RED)

        data = [
            [Paragraph('<b>Verificación</b>', header_style),
             Paragraph('<b>Estado</b>', header_style),
             Paragraph('<b>Impacto</b>', header_style)],
        ]
        for chk in checks:
            name = chk.get("name", chk.get("check", "—"))
            passed = chk.get("passed", chk.get("status") in ("ok", "pass", "passed", True))
            impact = chk.get("impact", chk.get("score_impact"))
            status_para = Paragraph('✓ PASS' if passed else '✗ FAIL',
                                    ok_style if passed else fail_style)
            impact_text = f'−{abs(impact)}' if (impact is not None and not passed) else ('0' if impact is not None else '—')
            data.append([
                Paragraph(str(name), cell_style),
                status_para,
                Paragraph(impact_text, cell_style),
            ])

        t = Table(data, colWidths=['58%', '22%', '20%'])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4C1D95')),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F3FF')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#F5F3FF'), colors.HexColor('#EDE9FE')]),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#C4B5FD')),
            ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#DDD6FE')),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        return t

    def _data_quality_section(self, styles, dq: dict):
        """Build the CALIDAD DE DATOS box to show after the stats bar."""
        score = dq.get("score", 0)
        label, lcolor = _dq_label_color(score)
        tag = dq.get("tag", "FINAL")
        analysis_ts = dq.get("analysis_timestamp", datetime.utcnow().strftime('%Y-%m-%d %H:%M') + " UTC")
        reconciliation = dq.get("reconciliation", "")
        discrepancy = dq.get("discrepancy_pct")
        warnings = dq.get("warnings", [])
        checks = dq.get("checks", [])

        # Title row
        title_para = Paragraph(
            '<b>CALIDAD DE DATOS</b>',
            ParagraphStyle('dq_title', fontName='Helvetica-Bold', fontSize=9,
                           textColor=BRAND_DARK)
        )

        # Score + label + tag in one line
        lcolor_hex = lcolor.hexval() if hasattr(lcolor, 'hexval') else '#16a34a'
        score_para = Paragraph(
            f'Puntuación: <b>{score}/100</b>  ·  '
            f'<font color="{lcolor_hex}"><b>{label}</b></font>  ·  {tag}',
            ParagraphStyle('dq_score', fontName='Helvetica', fontSize=9,
                           textColor=BRAND_DARK)
        )

        # Analysis timestamp
        ts_para = Paragraph(
            f'Análisis: {analysis_ts}',
            ParagraphStyle('dq_ts', fontName='Helvetica', fontSize=8,
                           textColor=BRAND_GRAY)
        )

        # Reconciliation line
        rec_text = reconciliation if reconciliation else "—"
        disc_text = f" · discrepancia {discrepancy}%" if discrepancy is not None else ""
        rec_para = Paragraph(
            f'Reconciliación: {rec_text}{disc_text}',
            ParagraphStyle('dq_rec', fontName='Helvetica', fontSize=8,
                           textColor=BRAND_DARK)
        )

        rows = [[title_para], [score_para], [self._dq_score_bar(score)], [ts_para], [rec_para]]

        # ── DQ checks table ───────────────────────────────────────────────────
        if checks:
            checks_label = Paragraph(
                '<b>Verificaciones de calidad</b>',
                ParagraphStyle('dq_chk_lbl', fontName='Helvetica-Bold', fontSize=8,
                               textColor=BRAND_DARK, spaceBefore=4)
            )
            rows.append([checks_label])
            rows.append([self._dq_checks_table(checks)])

        # ── Warnings list ─────────────────────────────────────────────────────
        if warnings:
            warn_header = Paragraph(
                f'<font color="#d97706"><b>Advertencias ({len(warnings)})</b></font>',
                ParagraphStyle('dq_wh', fontName='Helvetica-Bold', fontSize=8,
                               textColor=DQ_AMBER, spaceBefore=4)
            )
            rows.append([warn_header])
            for w in warnings:
                # Each warning may be a string or a dict with a 'message' key
                msg = w if isinstance(w, str) else w.get("message", w.get("msg", str(w)))
                severity = (w.get("severity", "").lower() if isinstance(w, dict) else "")
                marker_color = "#ea580c" if severity == "high" else "#d97706"
                rows.append([Paragraph(
                    f'<font color="{marker_color}">▲</font> {self._md_inline(str(msg))}',
                    ParagraphStyle('dq_wi', fontName='Helvetica', fontSize=8,
                                   textColor=BRAND_DARK, leftIndent=8, spaceAfter=1)
                )])

        t = Table(rows, colWidths=['100%'])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), DQ_BG),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#C4B5FD')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [DQ_BG]),
        ]))
        return t

    def _audit_table(self, styles, dq: dict, snapshot_ts: str):
        """Build the AUDITORIA DE EJECUCION waterfall table."""
        score = dq.get("score", 0)
        label, _ = _dq_label_color(score)
        queries_count = dq.get("queries_executed", "—")
        warnings_count = len(dq.get("warnings", []))
        warn_sym = "⚠" if warnings_count > 0 else "✓"

        header_style = ParagraphStyle('ath', fontName='Helvetica-Bold', fontSize=8,
                                       textColor=WHITE)
        cell_style = ParagraphStyle('atc', fontName='Helvetica', fontSize=8,
                                     textColor=BRAND_DARK)
        ok_style = ParagraphStyle('atk', fontName='Helvetica-Bold', fontSize=8,
                                   textColor=DQ_GREEN)

        data = [
            [Paragraph('<b>Etapa</b>', header_style),
             Paragraph('<b>Estado</b>', header_style),
             Paragraph('<b>Detalles</b>', header_style)],
            [Paragraph('Snapshot BD', cell_style),
             Paragraph('✓', ok_style),
             Paragraph(str(snapshot_ts), cell_style)],
            [Paragraph('Consultas ejecutadas', cell_style),
             Paragraph('✓', ok_style),
             Paragraph(f'{queries_count} consultas', cell_style)],
            [Paragraph('Calidad verificada', cell_style),
             Paragraph(warn_sym, ok_style),
             Paragraph(f'{score}/100 · {label}', cell_style)],
            [Paragraph('Advertencias', cell_style),
             Paragraph(str(warnings_count), ok_style),
             Paragraph('', cell_style)],
        ]

        t = Table(data, colWidths=['40%', '15%', '45%'])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_DARK),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F3FF')),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#C4B5FD')),
            ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#DDD6FE')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))
        return t

    def _build_provenance_footer_table(self, results: dict) -> Table:
        """Build the TRAZABILIDAD DE DATOS provenance footer for the last page."""
        dq = results.get("data_quality", {}) or {}
        score = dq.get("score", "—")
        label, _ = _dq_label_color(int(score) if isinstance(score, (int, float)) else 0)
        tag = dq.get("tag", "FINAL")
        analysis_ts = dq.get("analysis_timestamp", datetime.utcnow().strftime('%Y-%m-%d %H:%M') + " UTC")
        reconciliation = dq.get("reconciliation", "—")
        discrepancy = dq.get("discrepancy_pct", "—")
        snapshot_ts = (
            results.get("stages", {})
            .get("query_execution", {})
            .get("snapshot_timestamp", "—")
        )

        cell_style = ParagraphStyle('pf_cell', fontName='Helvetica', fontSize=7.5,
                                     textColor=BRAND_DARK)
        title_style = ParagraphStyle('pf_title', fontName='Helvetica-Bold', fontSize=8,
                                      textColor=BRAND_DARK)

        data = [
            [Paragraph('TRAZABILIDAD DE DATOS', title_style)],
            [Paragraph(
                f'Puntuación DQ: <b>{score}/100 ({tag})</b>  |  Análisis: {analysis_ts}',
                cell_style
            )],
            [Paragraph(
                f'Reconciliación: {reconciliation}  |  Discrepancia: {discrepancy}%',
                cell_style
            )],
            [Paragraph(
                f'Snapshot BD: {snapshot_ts} (aislamiento REPEATABLE READ)',
                cell_style
            )],
        ]

        t = Table(data, colWidths=['100%'])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F3F4F6')),
            ('BOX', (0, 0), (-1, -1), 1, BRAND_GRAY),
            ('LINEABOVE', (0, 0), (-1, 0), 1.5, BRAND_GRAY),
            ('LINEBELOW', (0, -1), (-1, -1), 1.5, BRAND_GRAY),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        return t

    def _triggered_alerts_section(self, styles, alerts: list) -> Table:
        """
        Build the ALERTAS DISPARADAS block from a list of alert dicts.
        Expected keys: threshold_label (str), computed_value (float),
                       threshold_value (float), severity (str: CRITICAL|HIGH|…)
        """
        title_style = ParagraphStyle('alrt_title', fontName='Helvetica-Bold', fontSize=9,
                                      textColor=BRAND_DARK)
        rows = [[Paragraph('<b>ALERTAS DISPARADAS</b>', title_style)]]

        for alert in alerts:
            label = alert.get("threshold_label", alert.get("label", "—"))
            computed = alert.get("computed_value", alert.get("value"))
            threshold = alert.get("threshold_value", alert.get("threshold"))
            severity = str(alert.get("severity", "HIGH")).upper()

            if severity == "CRITICAL":
                text_color = BRAND_RED
                marker = "⚠"
            else:
                text_color = BRAND_ORANGE
                marker = "⚠"

            computed_str = f"{computed:.1f}" if isinstance(computed, (int, float)) else str(computed)
            threshold_str = f"{threshold}" if threshold is not None else "—"

            rows.append([Paragraph(
                f'<font color="{"#DC2626" if severity == "CRITICAL" else "#EA580C"}">'
                f'<b>{marker} {label}:</b> {computed_str} '
                f'(umbral: {threshold_str})</font>',
                ParagraphStyle('alrt_row', fontName='Helvetica', fontSize=8.5,
                               textColor=text_color, spaceAfter=2, leftIndent=6)
            )])

        t = Table(rows, colWidths=['100%'])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FEF2F2')),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FFF7ED')),
            ('BOX', (0, 0), (-1, -1), 1, BRAND_RED),
            ('LINEBELOW', (0, 0), (-1, 0), 0.5, BRAND_RED),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        return t

    def _parse_markdown(self, text: str, styles, dq_score: int = 100) -> list:
        """Convert markdown text to ReportLab flowables."""
        flowables = []
        lines = text.split('\n')
        i = 0

        # Derive confidence badge text and color from DQ score
        conf_label, conf_color = _dq_label_color(dq_score)
        conf_hex = conf_color.hexval() if hasattr(conf_color, 'hexval') else '#16a34a'

        while i < len(lines):
            line = lines[i].rstrip()

            if line.startswith('### '):
                flowables.append(Paragraph(self._md_inline(line[4:]), styles['h3']))
                # Confidence badge after h3 findings headings
                badge = (
                    f'<font color="{conf_hex}" size="7"><b> [{conf_label}]</b></font>'
                )
                flowables.append(Paragraph(badge, styles['body']))
            elif line.startswith('## '):
                flowables.append(Spacer(1, 0.3*cm))
                flowables.append(Paragraph(self._md_inline(line[3:]), styles['h2']))
            elif line.startswith('# '):
                flowables.append(Paragraph(self._md_inline(line[2:]), styles['h1']))
            elif line.startswith('- ') or line.startswith('* '):
                content = line[2:]
                # Detect severity
                sev = ''
                if 'CRITICAL' in content.upper() or '🔴' in content:
                    sev = 'critical'
                elif 'HIGH' in content.upper() or '🟠' in content:
                    sev = 'high'

                style = styles.get(sev, styles['bullet']) if sev else styles['bullet']
                flowables.append(Paragraph(f'• {self._md_inline(content)}', style))
            elif line.startswith('**') and line.endswith('**') and len(line) > 4:
                flowables.append(Paragraph(f'<b>{self._md_inline(line[2:-2])}</b>', styles['body']))
            elif line.startswith('---') or line.startswith('==='):
                flowables.append(HRFlowable(width="100%", thickness=0.5,
                                            color=colors.HexColor('#E5E7EB')))
                flowables.append(Spacer(1, 0.15*cm))
            elif line.strip():
                flowables.append(Paragraph(self._md_inline(line), styles['body']))
            else:
                flowables.append(Spacer(1, 0.12*cm))

            i += 1

        return flowables

    def _md_inline(self, text: str) -> str:
        """Convert inline markdown to ReportLab XML."""
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', text)
        # Escape any remaining & < > that aren't already tags
        text = re.sub(r'&(?!amp;|lt;|gt;|nbsp;)', '&amp;', text)
        return text

    def _page_header(self, c: canvas.Canvas, doc):
        """Draw page header/footer on every page."""
        c.saveState()
        # Top line
        c.setStrokeColor(BRAND_VIOLET)
        c.setLineWidth(2)
        c.line(2.2*cm, A4[1] - 1.2*cm, A4[0] - 2.2*cm, A4[1] - 1.2*cm)
        # Page number
        c.setFont('Helvetica', 8)
        c.setFillColor(BRAND_GRAY)
        c.drawRightString(A4[0] - 2.2*cm, 1.5*cm, f'Pág. {doc.page}')
        c.drawString(2.2*cm, 1.5*cm, 'Valinor SaaS · Confidencial')
        c.restoreState()
