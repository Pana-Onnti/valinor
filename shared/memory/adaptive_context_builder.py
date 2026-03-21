"""
adaptive_context_builder — builds a rich adaptive context string for injection
into agent memory.  Consumed by ValinorAdapter before agents run.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile


def build_adaptive_context(profile: "ClientProfile") -> str:
    """
    Produce a human-readable adaptive context block summarising what Valinor
    knows about this client across past runs.

    The returned string is designed to be stored in ``memory["adaptive_context"]``
    and injected verbatim into agent prompts.
    """
    # ── Header ────────────────────────────────────────────────────────────────
    lines: list[str] = ["CONTEXTO ADAPTATIVO DEL CLIENTE"]

    lines.append(f"Cliente: {profile.client_name}")

    industry = profile.industry_inferred or "Desconocida"
    lines.append(f"Industria: {industry} (detectada automáticamente)")

    currency = profile.currency_detected or "No detectada"
    lines.append(f"Moneda: {currency}")

    last_run = profile.last_run_date or "N/A"
    lines.append(
        f"Análisis realizados: {profile.run_count} (último: {last_run})"
    )

    # Top-5 focus tables
    top_tables = profile.focus_tables[:5]
    if top_tables:
        lines.append(f"Tablas de foco: {', '.join(top_tables)}")
    else:
        lines.append("Tablas de foco: No definidas aún")

    # Persistent findings (open for >= 3 consecutive runs)
    persistent_count = sum(
        1
        for rec in profile.known_findings.values()
        if isinstance(rec, dict) and rec.get("runs_open", 0) >= 3
    )
    lines.append(f"Hallazgos persistentes: {persistent_count}")

    # Active alert thresholds
    threshold_count = len(profile.alert_thresholds) if profile.alert_thresholds else 0
    lines.append(f"Umbrales activos: {threshold_count}")

    # ── Historical baseline ────────────────────────────────────────────────────
    lines.append("")
    lines.append("LÍNEA BASE HISTÓRICA:")

    if profile.baseline_history:
        # Pick the top-3 KPI series; for each show the most recent data point
        kpi_keys = list(profile.baseline_history.keys())[:3]
        for kpi_key in kpi_keys:
            series = profile.baseline_history[kpi_key]
            if not series:
                continue
            # The series is a list of KPIDataPoint dicts; last entry is most recent
            last_point = series[-1] if isinstance(series[-1], dict) else {}
            label = last_point.get("label") or kpi_key
            value = last_point.get("value", "N/A")
            period = last_point.get("period", "")
            period_suffix = f" ({period})" if period else ""
            lines.append(f"  - {label}: {value}{period_suffix}")
    else:
        lines.append("  (sin historial aún)")

    # ── Active refinement ─────────────────────────────────────────────────────
    lines.append("")
    lines.append("REFINAMIENTO ACTIVO:")

    refinement = profile.get_refinement()

    preferred_depth = getattr(refinement, "preferred_analysis_depth", None)
    if preferred_depth:
        lines.append(f"  Profundidad preferida: {preferred_depth}")

    focus_areas = getattr(refinement, "focus_areas", None)
    if focus_areas:
        areas_str = ", ".join(focus_areas[:5])
        lines.append(f"  Áreas de foco: {areas_str}")

    if not preferred_depth and not focus_areas:
        lines.append("  (sin refinamiento previo)")

    return "\n".join(lines)
