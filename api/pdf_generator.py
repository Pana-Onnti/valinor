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


class BrandedPDFGenerator:
    """Generates a branded PDF from a Valinor executive report (markdown)."""

    def generate(
        self,
        report_markdown: str,
        client_name: str,
        period: str,
        run_delta: Optional[dict] = None,
        findings_summary: Optional[dict] = None,
    ) -> bytes:
        """Returns PDF as bytes."""
        buffer = io.BytesIO()

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

        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E5E7EB')))
        story.append(Spacer(1, 0.4*cm))

        # ── Report body (markdown → reportlab) ───────────────────────────────
        story.extend(self._parse_markdown(report_markdown, styles))

        # ── Footer note ───────────────────────────────────────────────────────
        story.append(Spacer(1, 0.8*cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E5E7EB')))
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            f"Generado por Valinor SaaS · Delta4C · {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC · "
            "Análisis de solo lectura — sin almacenamiento de datos del cliente.",
            styles['footer']
        ))

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

    def _parse_markdown(self, text: str, styles) -> list:
        """Convert markdown text to ReportLab flowables."""
        flowables = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i].rstrip()

            if line.startswith('### '):
                flowables.append(Paragraph(self._md_inline(line[4:]), styles['h3']))
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
