"""
N3 GraphRAG production wiring (VAL-192).

Covers the four seams that make the feature safe to ship behind
VALINOR_GRAPHRAG=1, all offline (no LLM, no DB):

  1. graphrag_context — the deterministic context builder (real demo state vs
     empty state vs the env gate).
  2. run_narrators — threads graph_context to every narrator, and is INERT
     (no _graph_context kwarg) when graph_context is None.
  3. the narrator prompt — actually carries the injected block, and omits it by
     default (default-off proof).
  4. graphrag_narrator_ab — control(off)/treatment(on) capture + union ground
     truth, with all collaborators injected.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from valinor.graphrag_context import (
    build_narrator_graph_context,
    graph_aggregate_numbers,
    graphrag_enabled,
    _has_aggregates,
)

_ROOT = Path(__file__).resolve().parent.parent
_DEMO_STATE = json.loads((_ROOT / "evals" / "fixtures" / "state_demo.json").read_text(encoding="utf-8"))


# ── 1. graphrag_context (pure) ────────────────────────────────────────────────

def test_graphrag_enabled_reflects_env(monkeypatch):
    monkeypatch.delenv("VALINOR_GRAPHRAG", raising=False)
    assert graphrag_enabled() is False
    monkeypatch.setenv("VALINOR_GRAPHRAG", "1")
    assert graphrag_enabled() is True
    monkeypatch.setenv("VALINOR_GRAPHRAG", "0")
    assert graphrag_enabled() is False


def test_build_context_on_real_demo_state():
    block = build_narrator_graph_context(
        _DEMO_STATE["entity_map"], _DEMO_STATE["query_results"],
        _DEMO_STATE["baseline"], _DEMO_STATE["findings"],
    )
    assert block is not None
    assert "CONTEXTO GLOBAL DEL GRAFO" in block
    assert "Agregados clave" in block


def test_build_context_empty_state_returns_none():
    assert build_narrator_graph_context({}, {"results": {}}, {}, {}) is None


def test_has_aggregates_distinguishes_header_only():
    header_only = "## Agregados clave (deterministas)\n## Convergencia multi-agente (global)\n  (ninguna)"
    assert _has_aggregates(header_only) is False
    with_content = header_only + "\n  EN RIESGO (global): €10,00 LTV, 1 clientes"
    assert _has_aggregates(with_content) is True


def test_aggregate_numbers_nonempty_on_demo():
    nums = graph_aggregate_numbers(
        _DEMO_STATE["entity_map"], _DEMO_STATE["query_results"],
        _DEMO_STATE["baseline"], _DEMO_STATE["findings"],
    )
    assert len(nums) > 0
    assert all("value" in v and isinstance(v["value"], float) for v in nums.values())


# ── 2. run_narrators threading (offline, narrators monkeypatched) ─────────────

def _patch_fake_narrators(monkeypatch, seen: dict):
    import valinor.agents.narrators.ceo as m_ceo
    import valinor.agents.narrators.controller as m_ctrl
    import valinor.agents.narrators.sales as m_sales
    import valinor.agents.narrators.executive as m_exec

    def _mk(name):
        async def fake(findings, entity_map, memory, client_config, baseline, **kw):
            # Sentinel default so the inert test can prove the key is ABSENT
            # (not merely present-with-None — which a unconditional-set bug would be).
            seen[name] = kw.get("_graph_context", "__ABSENT__")
            return f"# {name}"
        return fake

    monkeypatch.setattr(m_ceo, "narrate_ceo", _mk("ceo"))
    monkeypatch.setattr(m_ctrl, "narrate_controller", _mk("controller"))
    monkeypatch.setattr(m_sales, "narrate_sales", _mk("sales"))
    monkeypatch.setattr(m_exec, "narrate_executive", _mk("executive"))


def test_run_narrators_threads_graph_context(monkeypatch):
    from valinor.pipeline_narrator import run_narrators
    seen: dict = {}
    _patch_fake_narrators(monkeypatch, seen)
    asyncio.run(run_narrators(
        {}, {"entities": {}}, None, {"name": "X"}, {}, {"results": {}},
        graph_context="BLK",
    ))
    assert set(seen) == {"ceo", "controller", "sales", "executive"}
    assert set(seen.values()) == {"BLK"}


def test_run_narrators_inert_without_graph_context(monkeypatch):
    from valinor.pipeline_narrator import run_narrators
    seen: dict = {}
    _patch_fake_narrators(monkeypatch, seen)
    asyncio.run(run_narrators(
        {}, {"entities": {}}, None, {"name": "X"}, {}, {"results": {}},
    ))
    # graph_context defaults to None → narrators never receive the kwarg AT ALL
    # (proven via the sentinel; a present-with-None kwarg would read as None).
    assert set(seen.values()) == {"__ABSENT__"}


# ── 3. narrator prompt injection (real narrate_ceo, fake LLM) ─────────────────

def _patch_fake_query(monkeypatch, module, rec: dict):
    async def fake_query(prompt, options=None):
        rec["prompt"] = prompt

        class _Block:
            text = "ok"

        class _Msg:
            content = [_Block()]

        yield _Msg()

    monkeypatch.setattr(module, "query", fake_query)


_NARRATORS = [
    ("ceo", "narrate_ceo"),
    ("controller", "narrate_controller"),
    ("sales", "narrate_sales"),
    ("executive", "narrate_executive"),
]


@pytest.mark.parametrize("mod_name, fn_name", _NARRATORS)
def test_narrator_prompt_includes_graph_context(monkeypatch, mod_name, fn_name):
    import importlib
    mod = importlib.import_module(f"valinor.agents.narrators.{mod_name}")
    rec: dict = {}
    _patch_fake_query(monkeypatch, mod, rec)
    asyncio.run(getattr(mod, fn_name)(
        {}, {"entities": {}}, None, {"name": "X"}, {"rev": 1},
        query_results={}, _graph_context="MARKER_XYZ",
    ))
    assert "MARKER_XYZ" in rec["prompt"]


@pytest.mark.parametrize("mod_name, fn_name", _NARRATORS)
def test_narrator_prompt_omits_graph_context_by_default(monkeypatch, mod_name, fn_name):
    import importlib
    mod = importlib.import_module(f"valinor.agents.narrators.{mod_name}")
    rec: dict = {}
    _patch_fake_query(monkeypatch, mod, rec)
    asyncio.run(getattr(mod, fn_name)(
        {}, {"entities": {}}, None, {"name": "X"}, {"rev": 1},
        query_results={},
    ))
    assert "CONTEXTO GLOBAL DEL GRAFO" not in rec["prompt"]


def test_safe_wrapper_fails_open_on_exception(monkeypatch):
    """A graph bug must degrade to None, never break a run (the non-negotiable
    contract run.py relies on). on_error fires for observability."""
    import valinor.graphrag_context as gc

    def _boom(*a, **k):
        raise RuntimeError("graph blew up")

    monkeypatch.setattr(gc, "build_narrator_graph_context", _boom)
    errs: list = []
    out = gc.build_narrator_graph_context_safe(
        {}, {"results": {}}, {}, {}, on_error=errs.append,
    )
    assert out is None
    assert len(errs) == 1 and isinstance(errs[0], RuntimeError)


def test_safe_wrapper_passes_through_on_success():
    """When the builder succeeds, the wrapper returns its value verbatim."""
    from valinor.graphrag_context import build_narrator_graph_context_safe
    out = build_narrator_graph_context_safe(
        _DEMO_STATE["entity_map"], _DEMO_STATE["query_results"],
        _DEMO_STATE["baseline"], _DEMO_STATE["findings"],
    )
    assert out is not None and "CONTEXTO GLOBAL DEL GRAFO" in out


# ── 4. graphrag_narrator_ab harness (offline, collaborators injected) ─────────

_AB_SPEC = importlib.util.spec_from_file_location(
    "graphrag_narrator_ab", _ROOT / "scripts" / "graphrag_narrator_ab.py",
)
_AB_MOD = importlib.util.module_from_spec(_AB_SPEC)
_AB_SPEC.loader.exec_module(_AB_MOD)
capture_graphrag_ab = _AB_MOD.capture_graphrag_ab


@dataclass
class _Entry:
    value: float
    unit: str = "EUR"
    dimension: str = "currency"
    source_query: str = "q_rev"


class _FakeVR:
    def __init__(self):
        self.number_registry = {"total_revenue": _Entry(123456.0)}


def _state():
    return {
        "entity_map": {"tables": {}},
        "query_results": {"results": {}},
        "baseline": {"data_available": True, "total_revenue": 123456.0},
        "findings": {"executive": {"summary": "rev 123456"}},
        "memory": None,
        "client_config": {"name": "Golden PyME"},
    }


def _run_ab(only=None, ctx="GRAPH_BLOCK"):
    calls = []

    async def fake_run_narrators(**kwargs):
        calls.append(kwargs.get("graph_context"))
        tag = "on" if kwargs.get("graph_context") else "off"
        return {"briefing_ceo": f"# ceo {tag}", "reporte_ejecutivo": f"# exec {tag}"}

    control, treatment, dataset = asyncio.run(capture_graphrag_ab(
        _state(), only=only,
        run_narrators_fn=fake_run_narrators,
        build_vr_fn=lambda s: _FakeVR(),
        build_ctx_fn=lambda *a, **k: ctx,
        aggregate_numbers_fn=lambda *a, **k: {"segment:champions.total_ltv_eur": {"value": 10.0}},
    ))
    return control, treatment, dataset, calls


def test_ab_control_off_treatment_on():
    control, treatment, _, calls = _run_ab()
    assert calls[0] is None          # control = graph off
    assert calls[1] == "GRAPH_BLOCK"  # treatment = graph on
    assert "off" in control["briefing_ceo"]
    assert "on" in treatment["briefing_ceo"]


def test_ab_dataset_unions_registry_and_graph_numbers():
    _, _, dataset, _ = _run_ab()
    reg = dataset["number_registry"]
    assert reg["total_revenue"]["value"] == 123456.0          # legacy registry
    assert reg["segment:champions.total_ltv_eur"]["value"] == 10.0  # graph aggregate
    # Exactly the union: 1 registry entry + 1 graph entry, no drops, no phantoms.
    assert len(reg) == 2
    assert dataset["graph_context_injected"] is True


def test_ab_reports_empty_context_as_no_treatment():
    _, _, dataset, calls = _run_ab(ctx=None)
    assert dataset["graph_context_injected"] is False
    assert calls[1] is None  # treatment got None too → equals control


def test_ab_only_filter_subsets_both_branches():
    control, treatment, _, _ = _run_ab(only={"briefing_ceo"})
    assert set(control) == {"briefing_ceo"}
    assert set(treatment) == {"briefing_ceo"}
