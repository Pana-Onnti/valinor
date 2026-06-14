"""
N3 GraphRAG → production narrator bridge (VAL-192).

Wires the CERTIFIED N3 entity graph into the live pipeline behind
``VALINOR_GRAPHRAG=1``. INERT when the flag is unset (``run.py`` never calls
``build_narrator_graph_context`` and ``run_narrators`` ignores a ``None``
context), so prod behavior is byte-identical with the flag off.

What gets injected: the DETERMINISTIC "Agregados clave" block — the same served
library the certified community arm uses (global exposure, per-segment group-by,
scoring coverage, top-N). Zero LLM, zero DB, numbers verbatim, so it cannot
introduce hallucinations; it only gives narrators global facts that per-query
findings structurally cannot compute.

``graphrag.py`` stays FROZEN (certified v6); this module only composes its
public API. Pure functions, no infrastructure imports (hexagonal).

Refs: VAL-192 (N3 wiring)
"""

from __future__ import annotations

import os
from typing import Optional

_HEADER = (
    "CONTEXTO GLOBAL DEL GRAFO DE ENTIDADES (agregados deterministas cross-query "
    "— ya calculados; copialos VERBATIM, NUNCA recalcules ni infieras):"
)


def graphrag_enabled() -> bool:
    """True iff ``VALINOR_GRAPHRAG=1`` — the single gate for the whole feature."""
    return os.environ.get("VALINOR_GRAPHRAG") == "1"


def _has_aggregates(block: str) -> bool:
    """A ``to_evidence_context`` block always carries section headers; this is
    True only when at least one real aggregate/convergence line is present."""
    for line in block.splitlines():
        s = line.strip()
        if not s or s.startswith("##") or s == "(ninguna)":
            continue
        return True
    return False


def build_narrator_graph_context(
    entity_map: dict,
    query_results: dict,
    baseline: dict,
    findings: dict,
    number_registry: Optional[dict] = None,
    char_budget: int = 6000,
) -> Optional[str]:
    """Deterministic global-aggregate context for Stage-4 narrators, or ``None``.

    Pure + cheap (no LLM, no DB). Returns ``None`` when the state yields no
    meaningful aggregates (e.g. a client with no customer-level queries) so the
    caller treats "no graph value" exactly like "flag off".
    """
    from valinor.graphrag import build_entity_graph, to_evidence_context

    graph = build_entity_graph(
        entity_map, query_results, baseline, findings,
        number_registry=number_registry,
    )
    block = (to_evidence_context(graph, ppr={}, top_k=0, char_budget=char_budget) or "").strip()
    if not block or not _has_aggregates(block):
        return None
    return f"{_HEADER}\n{block}"


def build_narrator_graph_context_safe(
    entity_map: dict,
    query_results: dict,
    baseline: dict,
    findings: dict,
    number_registry: Optional[dict] = None,
    char_budget: int = 6000,
    on_error: Optional[callable] = None,
) -> Optional[str]:
    """Fail-open wrapper around :func:`build_narrator_graph_context`.

    An optional enrichment must NEVER break a pipeline run, so any error degrades
    to ``None`` (no context injected). ``on_error`` is invoked with the exception
    for observability (run.py wires it to a console warning). This is the entry
    point run.py uses.
    """
    try:
        return build_narrator_graph_context(
            entity_map, query_results, baseline, findings,
            number_registry=number_registry, char_budget=char_budget,
        )
    except Exception as exc:  # noqa: BLE001 — optional enrichment, fail open
        if on_error is not None:
            on_error(exc)
        return None


def graph_aggregate_numbers(
    entity_map: dict,
    query_results: dict,
    baseline: dict,
    findings: dict,
    number_registry: Optional[dict] = None,
) -> dict:
    """Every deterministic numeric the graph exposes, in number-registry shape
    (``{label: {"value": float}}``).

    Used by the N3 A/B to extend the grounding ground-truth so a narrator is not
    penalized for citing a CORRECT graph aggregate that the legacy 5-query
    registry never knew about (otherwise the treatment arm looks worse for
    surfacing more true numbers — a measurement artifact, not a regression).
    """
    from valinor.graphrag import build_entity_graph, _num

    graph = build_entity_graph(
        entity_map, query_results, baseline, findings,
        number_registry=number_registry,
    )
    out: dict = {}
    for nid, node in graph.nodes.items():
        for k, v in node.attrs.items():
            val = _num(v)
            if val is None:
                continue
            out[f"{nid}.{k}"] = {"value": float(val)}
    return out
