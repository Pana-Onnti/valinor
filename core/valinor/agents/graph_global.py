"""
Global-question answerer — the LLM half of N3 GraphRAG (VAL-192 N3).

The only module of N3 that talks to the model. Three entry points, all with
`query_fn` injectable so the orchestration is unit-testable offline:

  * summarize_communities — one call per community, narrating the DETERMINISTIC
    fact sheet (the LLM narrates, it never calculates; numbers verbatim).
  * answer_global_question — the COMMUNITY arm: community summaries + PPR
    top-k evidence + number registry → answer with the facts available.
  * answer_flat — the control arms: same token budget, no graph. Two modes:
    include_raw_rows=True (strongest control: findings + baseline + registry +
    raw query rows up to budget) and False (FLAT-narrator: what narrators see
    today — findings + baseline + registry only; reported, not gated).

Equal budgets across arms prevent a strawman control. Mirrors the narrator
pattern (claude_agent_sdk via monkey-patchable provider, Spanish output).

Refs: VAL-192
"""

from __future__ import annotations

import json
import os
from typing import Awaitable, Callable, Optional

from valinor.graphrag import (
    EntityGraph,
    community_fact_sheet,
    personalized_pagerank,
    select_seeds,
    to_evidence_context,
)

QueryFn = Callable[[str], Awaitable[str]]

CONTEXT_BUDGET_CHARS = 12_000   # same for every arm — anti-strawman


async def _default_query(prompt: str) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, query  # type: ignore

    options = ClaudeAgentOptions(
        model=os.getenv("VALINOR_NARRATOR_MODEL", "haiku"),
        system_prompt="Sos un analista financiero senior. Respondés en español, "
                      "conciso, con números exactos de las fuentes provistas.",
        max_turns=1,
    )
    chunks: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        for block in getattr(msg, "content", []):
            chunks.append(getattr(block, "text", ""))
    return "".join(chunks)


async def summarize_communities(
    graph: EntityGraph,
    communities: dict[str, int],
    client_config: dict,
    query_fn: Optional[QueryFn] = None,
) -> dict[int, str]:
    """One Spanish narrative per community from its deterministic fact sheet."""
    query_fn = query_fn or _default_query
    out: dict[int, str] = {}
    sizes: dict[int, int] = {}
    for c in communities.values():
        if c >= 0:
            sizes[c] = sizes.get(c, 0) + 1
    # Singleton communities (disconnected findings/metrics) carry no community
    # structure worth narrating — their content rides in the PPR evidence.
    for cid in sorted(c for c, n in sizes.items() if n >= 2):
        sheet = community_fact_sheet(graph, communities, cid)
        prompt = (
            f"CLIENTE: {client_config.get('display_name', '?')} "
            f"({client_config.get('sector', '?')})\n\n"
            f"FICHA DETERMINISTA DE LA COMUNIDAD {cid} (números ya calculados — "
            f"copialos VERBATIM, no recalcules nada):\n{sheet}\n\n"
            "Narrá en ≤120 palabras qué es esta comunidad de entidades y por qué "
            "importa para el negocio. Solo números de la ficha."
        )
        out[cid] = await query_fn(prompt)
    return out


async def answer_global_question(
    question: str,
    graph: EntityGraph,
    communities: dict[str, int],
    summaries: dict[int, str],
    number_registry: Optional[dict],
    client_config: dict,
    top_k: int = 30,
    query_fn: Optional[QueryFn] = None,
) -> str:
    """COMMUNITY arm: summaries + PPR-ranked evidence within the shared budget."""
    query_fn = query_fn or _default_query
    seeds = select_seeds(question, graph)
    ppr = personalized_pagerank(graph, seeds)
    evidence = to_evidence_context(graph, ppr, top_k=top_k,
                                   char_budget=CONTEXT_BUDGET_CHARS // 2)
    summaries_txt = "\n\n".join(
        f"### Comunidad {cid}\n{txt}" for cid, txt in sorted(summaries.items())
    )[: CONTEXT_BUDGET_CHARS // 3]
    registry_txt = json.dumps(number_registry or {}, ensure_ascii=False, default=str)[:1500]

    prompt = (
        f"CLIENTE: {client_config.get('display_name', '?')}\n\n"
        f"RESÚMENES POR COMUNIDAD DEL GRAFO DE ENTIDADES:\n{summaries_txt}\n\n"
        f"EVIDENCIA (nodos top-{top_k} por relevancia PPR a la pregunta, con "
        f"atributos y aristas):\n{evidence}\n\n"
        f"NUMBER REGISTRY:\n{registry_txt}\n\n"
        f"PREGUNTA GLOBAL:\n{question}\n\n"
        # Guardrails v2 (iteración train): los forbidden hits del primer run
        # vinieron de inferencias sobre-granulares y aritmética inventada.
        "REGLAS DURAS:\n"
        "1. Solo números que estén TEXTUALES en la evidencia/resúmenes/registry, "
        "o sumas explícitas de valores presentes (decí 'suma de X valores').\n"
        "2. Si un dato no está en la evidencia, escribí literalmente 'no "
        "derivable de los datos disponibles' — NUNCA lo infieras ni redondees "
        "desde memoria.\n"
        "3. Granularidad: cross-sell es segmento×categoría — PROHIBIDO atribuir "
        "categorías a clientes individuales.\n"
        "4. Nombrá como máximo 5 entidades por lista, las de mayor valor.\n"
        "≤250 palabras."
    )
    return await query_fn(prompt)


async def answer_flat(
    question: str,
    state: dict,
    client_config: dict,
    include_raw_rows: bool = True,
    query_fn: Optional[QueryFn] = None,
) -> str:
    """Control arms: same budget, no graph. include_raw_rows=False = narrator view."""
    query_fn = query_fn or _default_query
    parts = [
        f"BASELINE:\n{json.dumps(state.get('baseline', {}), ensure_ascii=False, default=str)[:1500]}",
        f"FINDINGS DE AGENTES:\n{json.dumps(state.get('findings', {}), ensure_ascii=False, default=str)[:4000]}",
    ]
    if include_raw_rows:
        qr = state.get("query_results", {})
        qr = qr.get("results", qr)
        parts.append(f"QUERY RESULTS (filas crudas):\n"
                     f"{json.dumps(qr, ensure_ascii=False, default=str)[:CONTEXT_BUDGET_CHARS // 2]}")
    context = "\n\n".join(parts)[:CONTEXT_BUDGET_CHARS]

    prompt = (
        f"CLIENTE: {client_config.get('display_name', '?')}\n\n"
        f"{context}\n\n"
        f"PREGUNTA GLOBAL:\n{question}\n\n"
        "Respondé con números exactos de las fuentes. Si no podés calcular algo "
        "con lo provisto, decilo. ≤250 palabras."
    )
    return await query_fn(prompt)
