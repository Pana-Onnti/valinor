"""
Orchestration tests for the N3 answerer (VAL-192 N3). Offline: query_fn is
injected, no LLM. The contract under test: prompts carry the deterministic
fact sheets / evidence / budget, and arms get the right context shape.
"""

from __future__ import annotations

import json

from valinor.agents.graph_global import (
    CONTEXT_BUDGET_CHARS,
    answer_flat,
    answer_global_question,
    summarize_communities,
)
from valinor.graphrag import build_entity_graph, detect_communities

STATE = json.loads(open("evals/fixtures/state_demo.json", encoding="utf-8").read())


def _graph():
    return build_entity_graph(
        STATE["entity_map"], STATE["query_results"], STATE["baseline"], STATE["findings"]
    )


class TestSummaries:
    async def test_one_call_per_community_with_fact_sheet(self):
        graph = _graph()
        comm = detect_communities(graph)
        prompts = []

        async def fake(prompt):
            prompts.append(prompt)
            return "resumen"

        out = await summarize_communities(graph, comm, STATE["client_config"], query_fn=fake)
        # one call per community with ≥2 members — singletons ride in the evidence
        sizes: dict[int, int] = {}
        for c in comm.values():
            if c >= 0:
                sizes[c] = sizes.get(c, 0) + 1
        n_multi = sum(1 for n in sizes.values() if n >= 2)
        assert len(out) == n_multi == len(prompts)
        assert 0 < n_multi < len(sizes) or n_multi == len(sizes)
        # prompts narrate the deterministic sheet (verbatim-numbers instruction)
        assert all("VERBATIM" in p for p in prompts)


class TestAnswerArms:
    async def test_community_arm_carries_evidence_and_summaries(self):
        graph = _graph()
        comm = detect_communities(graph)
        captured = {}

        async def fake(prompt):
            captured["prompt"] = prompt
            return "respuesta"

        ans = await answer_global_question(
            "¿Qué segmento concentra más facturación?", graph, comm,
            {0: "resumen comunidad"}, None, STATE["client_config"], query_fn=fake)
        assert ans == "respuesta"
        assert "Comunidad 0" in captured["prompt"]
        assert "PPR" in captured["prompt"]

    async def test_flat_arms_differ_by_raw_rows(self):
        prompts = {}

        async def fake_raw(prompt):
            prompts["raw"] = prompt
            return "x"

        async def fake_narr(prompt):
            prompts["narr"] = prompt
            return "x"

        await answer_flat("¿pregunta?", STATE, STATE["client_config"],
                          include_raw_rows=True, query_fn=fake_raw)
        await answer_flat("¿pregunta?", STATE, STATE["client_config"],
                          include_raw_rows=False, query_fn=fake_narr)
        assert "QUERY RESULTS" in prompts["raw"]
        assert "QUERY RESULTS" not in prompts["narr"]
        # equal-budget rule: neither arm exceeds the shared budget + question/preamble
        assert len(prompts["raw"]) < CONTEXT_BUDGET_CHARS + 1500
