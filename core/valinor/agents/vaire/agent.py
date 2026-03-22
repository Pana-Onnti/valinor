"""
Vairë Agent — Frontend rendering agent para KO Reports.

Responsabilidades:
  1. Seleccionar template según tipo de output
  2. Mapear findings/metrics del Narrador a la estructura de renderizado
  3. Enforcement de loss framing en hero numbers
  4. Generación de PDF via WeasyPrint
  5. Branding automático D4C
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .pdf_renderer import render_pdf
from .templates import render_ko_report_html

logger = logging.getLogger(__name__)


# ── Modelos de entrada/salida ─────────────────────────────────────────────────

@dataclass
class VaireInput:
    """Output del Narrador + metadata necesaria para renderizado."""
    company_name: str
    run_date: str                        # ISO format
    executive_report: str                # Markdown crudo del Narrador
    data_quality_score: float = 1.0      # 0–1
    findings: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    charts_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class VaireOutput:
    """Todo lo que Vairë produce."""
    html: str                           # HTML completo del KO Report v2
    pdf_bytes: bytes | None             # PDF listo para adjuntar a email
    whatsapp_summary: str              # Texto plano para WhatsApp


# ── Agente ────────────────────────────────────────────────────────────────────

class VaireAgent:
    """
    Agente de renderizado frontend.

    Uso:
        agent = VaireAgent()
        output = agent.render(vaire_input)
        # output.html → mandar al browser
        # output.pdf_bytes → adjuntar al email
        # output.whatsapp_summary → enviar por WhatsApp
    """

    def render(self, data: VaireInput) -> VaireOutput:
        """Punto de entrada principal. Produce HTML, PDF y summary."""
        logger.info("Vairë: renderizando reporte para %s", data.company_name)

        # 1. Parsear findings del markdown ejecutivo
        findings = self._parse_findings(data)

        # 2. Enforcement de loss framing
        findings = self._enforce_loss_framing(findings)

        # 3. Generar HTML
        html = render_ko_report_html(
            company_name=data.company_name,
            run_date=data.run_date,
            dq_score=data.data_quality_score,
            findings=findings,
            metrics=data.metrics,
        )

        # 4. PDF
        pdf_bytes: bytes | None = None
        try:
            pdf_bytes = render_pdf(html)
        except Exception as exc:
            logger.warning("Vairë: PDF generation failed — %s", exc)

        # 5. WhatsApp summary
        summary = self._build_whatsapp_summary(data.company_name, findings)

        logger.info("Vairë: reporte listo — %d findings, PDF=%s", len(findings), pdf_bytes is not None)
        return VaireOutput(html=html, pdf_bytes=pdf_bytes, whatsapp_summary=summary)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_findings(self, data: VaireInput) -> list[dict[str, Any]]:
        """
        Prioriza findings explícitos; si no hay, extrae del markdown.
        Asegura que todos tengan severity, title, y body.
        """
        if data.findings:
            return data.findings

        # Extracción simple desde markdown ejecutivo
        findings: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        buf: list[str] = []

        import re
        header_re = re.compile(
            r'^#{1,3}\s*(🔴|🟠|🟡|🟢|CRITICAL|HIGH|MEDIUM|LOW)[^—–\-]*[—–\-]+?\s*(.+)',
            re.IGNORECASE,
        )
        sev_map = {
            '🔴': 'CRITICAL', 'CRITICAL': 'CRITICAL',
            '🟠': 'HIGH',     'HIGH':     'HIGH',
            '🟡': 'MEDIUM',   'MEDIUM':   'MEDIUM',
            '🟢': 'LOW',      'LOW':      'LOW',
        }

        def flush():
            if current:
                current['body'] = '\n'.join(buf).strip()
                findings.append(current)
                buf.clear()

        for line in data.executive_report.splitlines():
            m = header_re.match(line)
            if m:
                flush()
                sev_raw = m.group(1).strip()
                severity = sev_map.get(sev_raw.upper(), 'INFO')
                title = m.group(2).strip()
                # Limpiar ID del título si existe
                id_match = re.match(r'^([\w\-]+-\d+)\s*[—–\-]?\s*(.*)', title)
                current = {
                    'id': id_match.group(1) if id_match else f'F{len(findings)+1}',
                    'severity': severity,
                    'title': (id_match.group(2) if id_match else title).strip(),
                    'body': '',
                }
            elif current:
                buf.append(line)

        flush()
        return findings

    def _enforce_loss_framing(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Verifica que hero numbers usen framing negativo (Kahneman loss aversion).
        Convierte gain framing -> loss framing in both ES and EN.
        """
        replacements = [
            # Spanish
            (r'podr[ií]as? ganar',        'est[a/as] perdiendo'),
            (r'potencial de (.+?) en ingresos', r'perdida de \1'),
            (r'oportunidad de',           'costo de no actuar:'),
            (r'podr[ií]as? ahorrar',      'esta perdiendo'),
            (r'ahorro potencial de',      'perdida actual de'),
            # English
            (r'you could save',           'you are losing'),
            (r'You could save',           'You are losing'),
            (r'potential savings? of',     'current loss of'),
            (r'opportunity to gain',       'cost of inaction:'),
            (r'you could gain',           'you are losing'),
            (r'You could gain',           'You are losing'),
            (r'potential revenue of',      'revenue loss of'),
        ]
        import re

        # Fix the placeholder in Spanish replacements
        es_replacements = [
            (r'podr[ií]as ganar',         'estas perdiendo'),
            (r'Podr[ií]as ganar',         'Estas perdiendo'),
            (r'podria ganar',             'esta perdiendo'),
            (r'Podria ganar',             'Esta perdiendo'),
            (r'potencial de (.+?) en ingresos', r'perdida de \1'),
            (r'oportunidad de',           'costo de no actuar:'),
            (r'podr[ií]as ahorrar',       'estas perdiendo'),
            (r'podria ahorrar',           'esta perdiendo'),
            (r'ahorro potencial de',      'perdida actual de'),
            # English
            (r'you could save',           'you are losing'),
            (r'You could save',           'You are losing'),
            (r'potential savings? of',     'current loss of'),
            (r'opportunity to gain',       'cost of inaction:'),
            (r'you could gain',           'you are losing'),
            (r'You could gain',           'You are losing'),
            (r'potential revenue of',      'revenue loss of'),
        ]

        for f in findings:
            for field_name in ('title', 'body', 'situation', 'complication', 'resolution'):
                text = f.get(field_name, '')
                if not text:
                    continue
                for pattern, replacement in es_replacements:
                    text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
                f[field_name] = text
        return findings

    def _build_whatsapp_summary(
        self,
        company_name: str,
        findings: list[dict[str, Any]],
    ) -> str:
        """Texto plano conciso para enviar por WhatsApp."""
        critical = [f for f in findings if f.get('severity') == 'CRITICAL']
        high     = [f for f in findings if f.get('severity') == 'HIGH']

        lines = [
            f"*Valinor · {company_name}* — {date.today().strftime('%d/%m/%Y')}",
            "",
        ]

        if critical:
            lines.append(f"🔴 *{len(critical)} crítico(s):*")
            for f in critical[:3]:
                lines.append(f"  • {f.get('title', '')}")

        if high:
            lines.append(f"🟠 *{len(high)} alto(s):*")
            for f in high[:2]:
                lines.append(f"  • {f.get('title', '')}")

        total = len(findings)
        lines += [
            "",
            f"Total hallazgos: {total}",
            "Generado por Valinor · Delta 4C",
        ]
        return '\n'.join(lines)
