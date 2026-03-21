"""
Lightweight PDF generator using only Python stdlib (no reportlab/weasyprint).

Generates a minimal but valid PDF from raw PDF syntax — header, catalog,
pages tree, content stream, and cross-reference table.

Usage:
    from shared.pdf_generator import generate_pdf_report
    pdf_bytes = generate_pdf_report(results)
"""

import io
import textwrap
from datetime import datetime


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _escape_pdf_string(text: str) -> str:
    """Escape for PDF string literals; replace non-latin-1 chars with ASCII approximations."""
    # Replace common non-latin-1 symbols with ASCII alternatives
    replacements = {
        "\u20ac": "EUR",  # €
        "\u00a3": "GBP",  # £
        "\u00a5": "JPY",  # ¥
        "\u2019": "'", "\u2018": "'",  # curly quotes
        "\u201c": '"', "\u201d": '"',
        "\u2013": "-", "\u2014": "--",  # en/em dash
        "\u2026": "...",  # ellipsis
    }
    for ch, repl in replacements.items():
        text = text.replace(ch, repl)
    # Drop remaining non-latin-1 chars
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(text: str, max_chars: int = 90) -> list[str]:
    """Wrap a block of text to fit within max_chars per line."""
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=max_chars) or [""]
        lines.extend(wrapped)
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_pdf_report(results: dict) -> bytes:
    """
    Generate a minimal but valid PDF report from Valinor analysis results.

    Parameters
    ----------
    results:
        The results dict returned by a completed Valinor analysis job.
        Expected keys (all optional, fall back gracefully):
        - job_id, client_name, period, status, execution_time_seconds,
          timestamp, findings, reports.executive

    Returns
    -------
    bytes
        Raw PDF file contents.
    """
    # ── Gather fields ──────────────────────────────────────────────────────
    job_id = str(results.get("job_id", "N/A"))
    client_name = str(results.get("client_name", "N/A"))
    period = str(results.get("period", "N/A"))
    job_status = str(results.get("status", "completed"))
    execution_time = results.get("execution_time_seconds")
    exec_time_str = f"{execution_time:.1f}s" if execution_time is not None else "N/A"
    timestamp = str(results.get("timestamp", datetime.utcnow().isoformat()))

    # Findings count
    findings = results.get("findings", {})
    total_findings = sum(
        len(v.get("findings", [])) if isinstance(v, dict) else 0
        for v in findings.values()
    )

    # Executive report text (first 2000 chars)
    executive_text = results.get("reports", {}).get("executive", "")
    executive_text = executive_text[:2000] if executive_text else "(No executive report available)"

    # ── Build content lines ────────────────────────────────────────────────
    header_lines = [
        "VALINOR SAAS - Executive Analysis Report",
        "=" * 50,
        "",
        f"Job ID        : {job_id}",
        f"Client        : {client_name}",
        f"Period        : {period}",
        f"Status        : {job_status}",
        f"Exec. Time    : {exec_time_str}",
        f"Generated At  : {timestamp}",
        f"Total Findings: {total_findings}",
        "",
        "-" * 50,
        "EXECUTIVE SUMMARY",
        "-" * 50,
        "",
    ]

    executive_wrapped = _wrap_lines(executive_text, max_chars=90)
    all_text_lines = header_lines + executive_wrapped

    # ── PDF construction ───────────────────────────────────────────────────
    buf = io.BytesIO()

    # Collect byte offsets for each object
    offsets: list[int] = []

    def write(data: bytes) -> int:
        """Write bytes to buffer, return offset before write."""
        pos = buf.tell()
        buf.write(data)
        return pos

    # PDF header
    write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

    # ── Object 1: Catalog ──────────────────────────────────────────────────
    offsets.append(buf.tell())
    write(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")

    # ── Object 2: Pages (root) ─────────────────────────────────────────────
    offsets.append(buf.tell())
    write(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")

    # ── Object 4: Font (Courier) ───────────────────────────────────────────
    # Build font object before page so we can reference it
    offsets.append(buf.tell())
    write(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj\n")

    # ── Object 5: Content stream ───────────────────────────────────────────
    # Build PDF content stream commands
    stream_parts: list[str] = [
        "BT",
        "/F1 10 Tf",
        "1 0 0 1 50 780 Tm",  # start near top-left (origin is bottom-left)
    ]

    # Each line: move down 14pt, write text
    for i, line in enumerate(all_text_lines):
        # Move text position: first line is already set, subsequent move -14 pt
        if i == 0:
            stream_parts.append(f"0 0 Td")
        else:
            stream_parts.append("0 -14 Td")
        escaped = _escape_pdf_string(line)
        stream_parts.append(f"({escaped}) Tj")

    stream_parts.append("ET")

    stream_bytes = "\n".join(stream_parts).encode("latin-1")
    stream_length = len(stream_bytes)

    offsets.append(buf.tell())
    buf.write(f"5 0 obj\n<< /Length {stream_length} >>\nstream\n".encode())
    buf.write(stream_bytes)
    buf.write(b"\nendstream\nendobj\n")

    # ── Object 3: Page ────────────────────────────────────────────────────
    offsets.append(buf.tell())
    write(
        b"3 0 obj\n"
        b"<< /Type /Page\n"
        b"   /Parent 2 0 R\n"
        b"   /MediaBox [0 0 612 792]\n"
        b"   /Contents 5 0 R\n"
        b"   /Resources << /Font << /F1 4 0 R >> >>\n"
        b">>\n"
        b"endobj\n"
    )

    # ── Cross-reference table ─────────────────────────────────────────────
    # Objects: 1 (catalog), 2 (pages), 4 (font), 5 (content), 3 (page)
    # We need them in order 1..5 for the xref
    # Rebuild in canonical order 1-5:
    #   offset index: 1→offsets[0], 2→offsets[1], 4→offsets[2], 5→offsets[3], 3→offsets[4]
    obj_offsets = {
        1: offsets[0],
        2: offsets[1],
        4: offsets[2],
        5: offsets[3],
        3: offsets[4],
    }

    xref_pos = buf.tell()
    buf.write(b"xref\n")
    buf.write(b"0 6\n")
    buf.write(b"0000000000 65535 f \n")  # object 0 (free)
    for obj_num in range(1, 6):
        offset = obj_offsets[obj_num]
        buf.write(f"{offset:010d} 00000 n \n".encode())

    buf.write(
        f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )

    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sample_results = {
        "job_id": "sample-job-001",
        "client_name": "Acme Corp",
        "period": "Q1-2026",
        "status": "completed",
        "execution_time_seconds": 47.3,
        "timestamp": datetime.utcnow().isoformat(),
        "findings": {
            "analyst": {
                "findings": [
                    {"severity": "CRITICAL", "description": "Revenue discrepancy > 5%"},
                    {"severity": "HIGH", "description": "AR aging > 90 days spike"},
                ]
            }
        },
        "reports": {
            "executive": (
                "Valinor ha completado el analisis de Acme Corp para Q1-2026.\n\n"
                "Se detectaron 2 hallazgos, incluyendo 1 CRITICO relacionado con una "
                "discrepancia de revenue superior al 5% en comparacion con el periodo anterior.\n\n"
                "Se recomienda revision inmediata del proceso de conciliacion de ventas y "
                "verificar los datos de facturacion del mes de marzo."
            )
        },
    }

    output_path = "/tmp/test_valinor.pdf"
    pdf_bytes = generate_pdf_report(sample_results)
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"PDF generated: {output_path} ({len(pdf_bytes)} bytes)")
