"""
PDF Renderer — convierte HTML D4C a PDF via WeasyPrint.

Fallback: si WeasyPrint no está disponible, retorna None
y el caller decide qué hacer (loggear warning, continuar sin PDF).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def render_pdf(html: str) -> bytes:
    """
    Convierte HTML a PDF bytes usando WeasyPrint.

    Raises:
        ImportError si WeasyPrint no está instalado.
        Exception en caso de error de renderizado.
    """
    try:
        from weasyprint import HTML  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "WeasyPrint no está instalado. "
            "Ejecutar: pip install weasyprint"
        ) from exc

    logger.debug("Renderizando PDF con WeasyPrint...")
    pdf_bytes: bytes = HTML(string=html).write_pdf()
    logger.debug("PDF generado: %d bytes", len(pdf_bytes))
    return pdf_bytes
