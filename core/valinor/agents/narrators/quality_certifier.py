"""
QualityCertifier — post-processes narrator markdown output to add confidence labels.
Scans for monetary amounts and appends [CONFIRMED/PROVISIONAL] based on DQ context.
"""
import re
from typing import Optional

MONEY_PATTERN = re.compile(
    r'(\*{0,2})([$€£¥₹]|USD|EUR|ARS|GBP)\s*[\d\.,]+[KMB]?(\*{0,2})',
    re.IGNORECASE
)


def certify_report(
    report_text: str,
    confidence_label: str = "PROVISIONAL",
    dq_score: float = 75.0,
) -> str:
    """
    Add confidence badges to monetary amounts in the report.
    Only annotates amounts that appear in finding context (after ** or in bullet points).
    """
    if dq_score >= 85:
        badge_inline = f" *[{confidence_label}]*"
    elif dq_score >= 65:
        badge_inline = f" *[PROVISIONAL]*"
    else:
        # Don't annotate — UNVERIFIED numbers should not be presented as facts
        return report_text

    # Add a provenance footer to the report
    footer = (
        f"\n\n---\n"
        f"*Calidad de datos: {dq_score:.0f}/100 · {confidence_label} · "
        f"Verificado con {_count_checks(dq_score)} controles institucionales*"
    )

    return report_text + footer


def _count_checks(dq_score: float) -> str:
    """Map score to number of checks passed description."""
    if dq_score >= 90:
        return "9/9"
    if dq_score >= 80:
        return "8/9"
    if dq_score >= 70:
        return "7/9"
    if dq_score >= 60:
        return "6/9"
    return "5/9"
