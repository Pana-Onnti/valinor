"""
Inventory vertical — lightweight stock-and-sales digest.

One agent (Haiku), 5 queries, produces a prioritized purchase recommendation
digest formatted for short-form delivery (WhatsApp, SMS, email body).

Budget target: <$0.01/run, <30s per run.

Refs: VAL-130 (L1.a)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from valinor.verticals.config import AgentSpec, VerticalConfig
from valinor.verticals.registry import register_agent

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Inventory Agent
# ─────────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """Sos el agente de inventario. Recibes datos de stock y ventas de los ultimos dias.

Tu trabajo:
1. Identificar articulos que estan por debajo del stock minimo.
2. Calcular cuantas unidades de cada articulo comprar basado en:
   - Ventas promedio de los ultimos 7 dias
   - Stock actual
   - Stock minimo configurado (o inferido si no existe)
   - Lead time de reposicion (default: 3 dias si no se conoce)
3. Priorizar: urgencia (stock=0 > stock<minimo > stock bajando rapido).
4. Formato: lista priorizada con articulo, stock actual, recomendacion, razon.

Se directo y operativo. El destinatario es el encargado de compras que lee esto a las 6AM.

Responde en JSON estricto:
{
  "urgent": [{"sku": "...", "name": "...", "stock": 0, "recommend": 15, "reason": "..."}],
  "low_stock": [...],
  "top_selling": [{"sku": "...", "name": "...", "units": 45}],
  "summary": "texto de 1-2 lineas"
}
"""


async def run_inventory_analyzer(context: dict[str, Any]) -> dict[str, Any]:
    """
    Inventory analyzer — 1 Haiku call.

    Args:
        context: dict with keys:
            - "query_results": dict with stock_actual, ventas_ayer, bajo_minimo, etc.
            - "client_name": str
            - "llm_client": optional async callable for LLM (for testing)

    Returns:
        {"agent": "inventory_analyzer", "output": <parsed digest>, "raw": <str>}
    """
    query_results = context.get("query_results", {})
    client_name = context.get("client_name", "unknown")
    llm_client = context.get("llm_client")

    user_prompt = (
        f"Cliente: {client_name}\n"
        f"Datos de inventario y ventas:\n"
        f"{json.dumps(query_results, ensure_ascii=False, default=str)}\n\n"
        f"Analiza y responde en JSON estricto segun el formato del system prompt."
    )

    if llm_client is None:
        # Default: use anthropic SDK via shared.llm module (lazily, so tests can inject)
        try:
            from shared.llm.client import get_default_llm
            llm_client = get_default_llm(model="haiku")
        except ImportError:
            logger.warning("inventory_analyzer: no llm_client + shared.llm unavailable; returning stub")
            return {
                "agent": "inventory_analyzer",
                "output": {"urgent": [], "low_stock": [], "top_selling": [], "summary": "stub"},
                "raw": "",
                "error": "no_llm_client",
            }

    raw = await llm_client.complete(system=SYSTEM_PROMPT, prompt=user_prompt)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("inventory_analyzer: bad JSON response: %s", exc)
        parsed = {"urgent": [], "low_stock": [], "top_selling": [], "summary": "parse_error"}

    return {"agent": "inventory_analyzer", "output": parsed, "raw": raw}


# Register the agent so vertical configs can reference it by name
INVENTORY_ANALYZER = register_agent(AgentSpec(
    name="inventory_analyzer",
    runner=run_inventory_analyzer,
    model="haiku",
    required_inputs=("query_results", "client_name"),
))


# ─────────────────────────────────────────────────────────────────────
# Inventory Vertical Config
# ─────────────────────────────────────────────────────────────────────


INVENTORY_VERTICAL = VerticalConfig(
    name="inventory",
    description="Daily stock + sales digest for buyers. 1 Haiku agent, 5 pre-computed queries.",
    agents=[INVENTORY_ANALYZER],
    queries=[
        "stock_actual",        # SELECT articulo, stock_actual, stock_minimo FROM ...
        "ventas_ayer",         # SELECT articulo, SUM(cantidad) FROM ventas WHERE fecha = ayer
        "delta_stock",         # stock_actual - ventas_ayer projected
        "bajo_minimo",         # WHERE stock_actual < stock_minimo
        "top_vendidos_semana", # TOP 10 ultimos 7 dias
    ],
    output_format="digest",
    estimated_cost_usd=0.005,
    estimated_duration_seconds=15.0,
)
