"""
PromptTuner — generates the adaptive context block injected into agent prompts.
Uses ClientProfile data to make LLM calls client-specific from run #2 onwards.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile


class PromptTuner:
    """
    Generates a context block that is prepended to each agent's system prompt.
    Zero LLM calls — pure string construction from persisted profile data.
    """

    def build_context_block(self, profile: "ClientProfile") -> str:
        """
        Returns a text block like:

        === CONTEXTO DE CLIENTE (Gloria S.A. — Run #4) ===
        - Industria inferida: distribucion mayorista
        - Moneda funcional: ARS
        - Tablas de mayor senal: c_invoice, c_payment, c_bpartner
        - Hallazgos persistentes (3+ runs): CRIT-1 (facturas sin pago >90d)
        - Anomalias resueltas: SENT-2, LOW-4
        - Hints validados: "filtrar DocStatus='CO' para facturas confirmadas"
        ==================================================
        """
        if profile.run_count == 0:
            return ""  # First run — no context yet

        lines = [
            f"═══ CONTEXTO HISTÓRICO: {profile.client_name} — Run #{profile.run_count + 1} ═══",
        ]

        if profile.industry_inferred:
            lines.append(f"- Industria inferida: {profile.industry_inferred}")

        if profile.currency_detected:
            lines.append(f"- Moneda funcional: {profile.currency_detected}")

        if profile.focus_tables:
            lines.append(f"- Tablas de mayor señal: {', '.join(profile.focus_tables[:5])}")

        # Persistent findings (seen 3+ runs)
        persistent = [
            f"{rec['id']} ({rec['title']})"
            for rec in profile.known_findings.values()
            if rec.get("runs_open", 0) >= 3
        ]
        if persistent:
            lines.append(f"- Hallazgos persistentes (3+ runs): {'; '.join(persistent[:5])}")

        # Recently resolved
        resolved_ids = list(profile.resolved_findings.keys())[-5:]
        if resolved_ids:
            lines.append(f"- Anomalías resueltas: {', '.join(resolved_ids)}")

        # Query hints from refinement
        refinement = profile.get_refinement()
        if refinement.query_hints:
            hints_str = "; ".join(f'"{h}"' for h in refinement.query_hints[:3])
            lines.append(f"- Hints validados: {hints_str}")

        if refinement.focus_areas:
            lines.append(f"- Áreas de foco: {', '.join(refinement.focus_areas[:4])}")

        if refinement.suppress_ids:
            lines.append(f"- Hallazgos ya resueltos (no reportar): {', '.join(refinement.suppress_ids)}")

        lines.append("═" * 52)
        return "\n".join(lines)

    def inject_into_memory(self, memory: dict, profile: "ClientProfile") -> dict:
        """
        Injects the context block into the memory dict used by valinor pipeline agents.
        Returns a new memory dict with 'adaptive_context' key added.
        """
        context = self.build_context_block(profile)
        if not context:
            return memory

        enhanced = dict(memory) if memory else {}
        enhanced["adaptive_context"] = context
        enhanced["client_profile_summary"] = {
            "run_count": profile.run_count,
            "known_findings_count": len(profile.known_findings),
            "resolved_findings_count": len(profile.resolved_findings),
            "focus_tables": profile.focus_tables[:5],
            "table_weights": dict(list(profile.table_weights.items())[:10]),
        }
        return enhanced
