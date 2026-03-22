"""
IndustryDetector — infers client industry and currency from entity_map and schema hints.
Runs once after the first Cartographer call, updates profile.
Uses a fast Haiku call with a tiny prompt.
"""
from __future__ import annotations
from typing import Dict, Any, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from shared.memory.client_profile import ClientProfile

logger = structlog.get_logger()

# ── Heuristic patterns for fast, zero-LLM detection ──────────────────────────
_INDUSTRY_HINTS = {
    "distribución mayorista": [
        "c_invoice", "c_bpartner", "c_order", "m_product", "m_inout",
        "m_warehouse", "m_locator", "shipment"
    ],
    "retail / punto de venta": [
        "pos_order", "pos_session", "point_of_sale", "ticket", "caja"
    ],
    "manufactura": [
        "mrp_production", "bom", "routing", "workcenter", "workorder",
        "mrp_bom", "manufacturing"
    ],
    "servicios profesionales": [
        "timesheet", "project_task", "hr_timesheet", "analytic_account",
        "sale_order_line", "invoice_line"
    ],
    "salud / clínica": [
        "paciente", "patient", "historia_clinica", "medico", "cita",
        "consulta", "farmacia"
    ],
    "finanzas / contabilidad": [
        "account_move", "account_journal", "gl_entry", "gl_account",
        "fin_payment", "account_payment"
    ],
}

_CURRENCY_HINTS = {
    "ARS": ["ar_", "_ar_", "argentina", "peso", "ars"],
    "USD": ["usd", "dollar", "dolares"],
    "EUR": ["eur", "euro"],
    "BRL": ["brl", "real", "brasil"],
    "CLP": ["clp", "chile", "pesos_chilenos"],
    "COP": ["cop", "colombia"],
    "MXN": ["mxn", "mexico"],
    "PEN": ["pen", "soles", "peru"],
}


class IndustryDetector:
    """Infers industry and currency from schema, then optionally refines with LLM."""

    def detect(self, entity_map: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, str]:
        """
        Returns {"industry": str, "currency": str} using heuristics.
        Fast — no LLM calls.
        """
        all_table_names = " ".join(
            (entity.get("table", "") + " " + entity_name).lower()
            for entity_name, entity in entity_map.get("entities", {}).items()
        )
        # Also use config hints
        config_str = " ".join([
            str(config.get("sector", "")),
            str(config.get("country", "")),
            str(config.get("currency", "")),
            str(config.get("erp", "")),
        ]).lower()
        combined = all_table_names + " " + config_str

        # Industry heuristic
        industry = self._match_industry(combined)

        # Currency heuristic
        currency = config.get("currency") or self._match_currency(combined)

        return {"industry": industry, "currency": currency}

    async def detect_with_llm(
        self,
        entity_map: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Enhanced detection using LLM when heuristics give low confidence.
        """
        heuristic = self.detect(entity_map, config)

        # If heuristics gave confident answers, skip LLM
        if heuristic["industry"] != "desconocida":
            return heuristic

        try:
            from shared.llm.monkey_patch import _interceptor
            from shared.llm.base import LLMOptions, ModelType
            import json

            tables = list(entity_map.get("entities", {}).keys())[:15]
            prompt = f"""Analiza estas tablas de base de datos ERP y determina:
1. La industria del cliente (ej: "distribución mayorista", "retail", "manufactura", "servicios", "salud")
2. La moneda funcional probable (ej: ARS, USD, EUR, BRL)

Tablas: {', '.join(tables)}
País configurado: {config.get('country', 'desconocido')}
Sector: {config.get('sector', 'desconocido')}

Responde SOLO con JSON: {{"industry": "...", "currency": "..."}}"""

            options = LLMOptions(model=ModelType.HAIKU, stream=False)
            provider = await _interceptor.get_provider()
            result = await provider.query(prompt, options)
            content = result.content if hasattr(result, "content") else str(result)

            import re as _re
            m = _re.search(r'\{[^}]+\}', content)
            if m:
                data = json.loads(m.group())
                return {
                    "industry": data.get("industry", heuristic["industry"]),
                    "currency": data.get("currency", heuristic["currency"]),
                }
        except Exception as e:
            logger.warning("IndustryDetector LLM call failed", error=str(e))

        return heuristic

    def update_profile(self, profile: "ClientProfile", entity_map: Dict, config: Dict):
        """Update profile.industry_inferred and profile.currency_detected."""
        detected = self.detect(entity_map, config)

        old_industry = profile.industry_inferred
        new_industry = detected["industry"]
        if old_industry != new_industry:
            logger.info(
                "Industry detected",
                client=profile.client_name,
                from_industry=old_industry,
                to_industry=new_industry,
            )
            profile.industry_inferred = new_industry

        if not profile.currency_detected:
            profile.currency_detected = detected["currency"]

    def _match_industry(self, text: str) -> str:
        best_industry = "desconocida"
        best_score = 0
        for industry, keywords in _INDUSTRY_HINTS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best_score = score
                best_industry = industry
        return best_industry

    def _match_currency(self, text: str) -> str:
        for currency, patterns in _CURRENCY_HINTS.items():
            if any(p in text for p in patterns):
                return currency
        return "USD"  # default
