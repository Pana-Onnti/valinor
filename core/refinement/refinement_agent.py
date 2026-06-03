"""
RefinementAgent — LLM-powered post-run analyzer.
Runs AFTER a completed run (non-blocking, background task).
Generates ClientRefinement: table_weights, query_hints, focus_areas, suppress_ids.
"""
from __future__ import annotations
import json
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

import structlog

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile, ClientRefinement  # noqa: F401

logger = structlog.get_logger()


class RefinementAgent:
    """
    Post-run analyzer that distills a completed run into improvement instructions
    for the next run. Uses LLM to generate context-aware refinements.
    """

    async def analyze_run(
        self,
        profile: "ClientProfile",
        findings: Dict[str, Any],
        entity_map: Dict[str, Any],
        reports: Dict[str, str],
        period: str,
        run_delta: Optional[Dict] = None,
    ) -> "ClientRefinement":
        """
        Analyze a completed run and produce a ClientRefinement.
        Falls back to heuristic analysis if LLM is unavailable.
        """
        from shared.memory.client_profile import ClientRefinement  # noqa: F811, F401

        try:
            refinement = await self._llm_analyze(profile, findings, reports, period, run_delta)
        except Exception as e:
            logger.warning("RefinementAgent: LLM analysis failed, using heuristics", error=str(e))
            refinement = self._heuristic_analyze(profile, findings, entity_map, run_delta)

        refinement.generated_at = datetime.utcnow().isoformat()
        return refinement

    async def _llm_analyze(
        self,
        profile: "ClientProfile",
        findings: Dict[str, Any],
        reports: Dict[str, str],
        period: str,
        run_delta: Optional[Dict],
    ) -> "ClientRefinement":
        """Use LLM to generate rich refinements."""
        from shared.llm.monkey_patch import _interceptor
        from shared.llm.base import LLMOptions, ModelType
        from shared.memory.client_profile import ClientRefinement

        # Build a compact summary of findings for the LLM
        finding_summary = []
        for agent_name, agent_result in findings.items():
            if isinstance(agent_result, dict):
                for f in agent_result.get("findings", [])[:5]:  # cap at 5 per agent
                    finding_summary.append({
                        "id": f.get("id", ""),
                        "severity": f.get("severity", ""),
                        "title": f.get("title", ""),
                        "agent": agent_name,
                    })

        persistent_findings = [
            {"id": fid, "title": rec.get("title", ""), "runs_open": rec.get("runs_open", 1)}
            for fid, rec in profile.known_findings.items()
            if rec.get("runs_open", 0) >= 2
        ]

        prompt = f"""Eres un analista de BI especializado en sistemas ERP.

CLIENTE: {profile.client_name}
PERÍODO: {period}
RUN #: {profile.run_count + 1}

HALLAZGOS ACTUALES:
{json.dumps(finding_summary, indent=2, ensure_ascii=False)}

HALLAZGOS PERSISTENTES (aparecen en múltiples runs):
{json.dumps(persistent_findings, indent=2, ensure_ascii=False)}

DELTA ESTE RUN:
- Nuevos: {len((run_delta or {}).get('new', []))}
- Resueltos: {len((run_delta or {}).get('resolved', []))}
- Empeorados: {len((run_delta or {}).get('worsened', []))}

TABLAS CON MÁS SEÑAL (histórico):
{json.dumps(profile.focus_tables[:8], ensure_ascii=False)}

Basándote en esta información, genera instrucciones de refinamiento para el PRÓXIMO run.
Responde ÚNICAMENTE con un JSON válido con esta estructura exacta:

{{
  "table_weights": {{"tabla_nombre": 0.9, "otra_tabla": 0.3}},
  "query_hints": ["hint SQL 1", "hint SQL 2"],
  "focus_areas": ["área de negocio 1", "área 2"],
  "suppress_ids": ["FINDING-ID-ya-resuelto"],
  "context_block": "Resumen en 2-3 oraciones del estado actual del cliente para contexto del LLM"
}}

REGLAS:
- table_weights: valores entre 0.1 (baja señal) y 1.0 (alta señal)
- query_hints: máximo 5, específicos y accionables (ej: "filtrar DocStatus='CO'")
- focus_areas: máximo 4, en términos de negocio
- suppress_ids: SOLO findings completamente resueltos (no aparecen en finding_summary)
- context_block: máximo 3 oraciones, en español

SOLO RESPONDE CON EL JSON. SIN MARKDOWN NI EXPLICACIONES."""

        options = LLMOptions(model=ModelType.HAIKU, stream=False)
        provider = await _interceptor.get_provider()
        result = await provider.query(prompt, options)
        content = result.content if hasattr(result, "content") else str(result)

        import re
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            raise ValueError("No JSON in LLM response")

        data = json.loads(json_match.group())
        return ClientRefinement(
            table_weights=data.get("table_weights", {}),
            query_hints=data.get("query_hints", []),
            focus_areas=data.get("focus_areas", []),
            suppress_ids=data.get("suppress_ids", []),
            context_block=data.get("context_block", ""),
        )

    def _heuristic_analyze(
        self,
        profile: "ClientProfile",
        findings: Dict[str, Any],
        entity_map: Dict[str, Any],
        run_delta: Optional[Dict],
    ) -> "ClientRefinement":
        """
        Fallback: generate refinements heuristically without LLM.
        """
        from shared.memory.client_profile import ClientRefinement

        hints = []
        focus_areas = []
        suppress_ids = []

        # Suppress findings that just got resolved
        if run_delta:
            suppress_ids = run_delta.get("resolved", [])[:5]

        # Focus on tables with findings
        if profile.focus_tables:
            focus_areas = profile.focus_tables[:3]

        # Add a basic hint if we know the ERP
        if any("c_invoice" in t for t in (profile.focus_tables or [])):
            hints.append("filtrar DocStatus='CO' para facturas confirmadas")
        if any("c_bpartner" in t for t in (profile.focus_tables or [])):
            hints.append("filtrar iscustomer='Y' AND isactive='Y' para clientes activos")

        return ClientRefinement(
            table_weights=profile.table_weights,
            query_hints=hints,
            focus_areas=focus_areas,
            suppress_ids=suppress_ids,
        )
