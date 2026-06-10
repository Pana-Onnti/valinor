"""
Unit tests for the GraphRAG-mínimo instance graph (VAL-192 N3).

Pure / no LLM, no DB, NO client data: every test runs on a synthetic
post-verification pipeline state built in-file (12 customers, 3 segments,
4 categories, metrics, findings), with string-serialized numerics
("12345.67", "147 days, 0:00:00") deliberately mixed with floats — the
regression that motivated `_num` (drivers serialize NUMERIC as strings and a
prior instrument silently dropped them).
"""

from __future__ import annotations

import pytest

from valinor.graphrag import (
    EntityGraph,
    GraphEdge,
    GraphNode,
    _num,
    build_entity_graph,
    community_fact_sheet,
    detect_communities,
    personalized_pagerank,
    select_seeds,
    to_evidence_context,
)

# ═══════════════════════════════════════════════════════════════════════════
# SYNTHETIC FIXTURE — 12 customers / 3 segments / 4 categories / 4 findings
# ═══════════════════════════════════════════════════════════════════════════

_CUSTOMERS = [
    # (id, name, segment, share_pct, ltv_eur, recency_days)
    ("C001", "Acme Corp",       "champions",   "35.00", "127581.06", 12),
    ("C002", "Borealis Foods",  "champions",   20.0,    "72903.46",  20),
    ("C003", "Cobalt Trading",  "champions",   "10.00", 36451.73,    25),
    ("C004", "Delta Mayorista", "champions",   8.0,     "29161.38",  30),
    ("C005", "Estrella Pack",   "at_risk",     7.0,     "25516.21",  147),
    ("C006", "Fenix Logistica", "at_risk",     5.0,     18225.87,    120),
    ("C007", "Gamma Insumos",   "at_risk",     "4.00",  "14580.69",  95),
    ("C008", "Helios Quimica",  "at_risk",     3.0,     10935.52,    200),
    ("C009", "Iris Textil",     "hibernating", 2.0,     "7290.35",   60),
    ("C010", "Jade Comercial",  "hibernating", 1.0,     3645.17,     70),
    ("C011", "Kappa Granos",    "hibernating", None,    None,        80),
    ("C012", "Lumen Servicios", "hibernating", None,    None,        85),
]


def make_state() -> tuple[dict, dict, dict, dict, dict]:
    """Fresh synthetic pipeline state (entity_map, query_results, baseline,
    findings, number_registry). Fresh dicts every call → determinism tests
    rebuild from scratch."""
    entity_map = {
        "entities": {
            "invoices": {"table": "c_invoice"},
            "customers": {"table": "c_bpartner"},
        },
        "relationships": [
            {"from_entity": "invoices", "to_entity": "customers", "via": "c_bpartner_id"},
        ],
    }

    concentration_rows = [
        {"customer_id": cid, "customer_name": name, "ltv_eur": ltv,
         "share_pct": share, "last_purchase": "2025-06-19",
         "risk": "high" if rec > 90 else "low"}
        for cid, name, _seg, share, ltv, rec in _CUSTOMERS
        if share is not None
    ]
    rfm_rows = [
        {"customer_id": cid, "customer_name": name, "segment": seg,
         "recency_days": rec, "frequency": 18,
         "monetary_eur": ltv if ltv is not None else "1893.22",
         "r_score": 3, "f_score": 3, "m_score": 3}
        for cid, name, seg, _share, ltv, rec in _CUSTOMERS
    ]
    churn_rows = [
        {"customer_id": "C005", "customer_name": "Estrella Pack",
         "deal_risk_score": "78.5", "recency_days": "147 days, 0:00:00",
         "ltv_eur": "25516.21", "profile": "cuenta_top"},
        {"customer_id": "C006", "customer_name": "Fenix Logistica",
         "deal_risk_score": 65.0, "recency_days": 120,
         "ltv_eur": 18225.87, "profile": "cuenta_media"},
        {"customer_id": "C007", "customer_name": "Gamma Insumos",
         "deal_risk_score": "52.3", "recency_days": "95 days, 0:00:00",
         "ltv_eur": "14580.69", "profile": "cuenta_media"},
        {"customer_id": "C008", "customer_name": "Helios Quimica",
         "deal_risk_score": 49.0, "recency_days": 200,
         "ltv_eur": 10935.52, "profile": "outlier"},
    ]
    cross_sell_rows = [
        {"segment": "champions",   "category": "Alimentos",  "penetration_pct": "80.00"},
        {"segment": "champions",   "category": "Bebidas",    "penetration_pct": 60.0},
        {"segment": "at_risk",     "category": "Limpieza",   "penetration_pct": "50.00"},
        {"segment": "hibernating", "category": "Ferretería", "penetration_pct": 30.0},
    ]
    query_results = {
        "results": {
            "concentration_top_customers": {"rows": concentration_rows},
            "rfm_segmentation": {"rows": rfm_rows},
            "churn_risk_scoring": {"rows": churn_rows},
            "cross_sell_matrix": {"rows": cross_sell_rows},
        },
        "errors": {},
    }

    baseline = {
        "total_revenue": "364517.30",   # string-serialized NUMERIC (the bug)
        "total_invoices": 3139,
        "period_start": "2025-01-01",   # date → must NOT become a metric
    }
    findings = {
        "sales": {"findings": [
            {"id": "S1", "title": "Acme Corp concentra 35.0% del revenue del periodo",
             "evidence": "share_pct=35.00 en concentration_top_customers"},
            {"id": "S2", "title": "El segmento champions sostiene la facturacion",
             "desc": "4 clientes generan 73% del total"},
        ]},
        "finance": {"findings": [
            {"id": "F3", "headline": "Caida sostenida de ventas en Ferretería"},
            {"id": "F4", "title": "Margen bruto estable durante el periodo"},
        ]},
    }
    number_registry = {
        "total_revenue": {"value": "364517.30"},
        "avg_ticket_eur": {"value": 116.13},
    }
    return entity_map, query_results, baseline, findings, number_registry


@pytest.fixture
def graph() -> EntityGraph:
    return build_entity_graph(*make_state())


def _graph_from_edges(edge_list: list[tuple[str, str, float]]) -> EntityGraph:
    """Hand-built graph for planted community-structure tests."""
    g = EntityGraph()
    for src, dst, weight in edge_list:
        for nid in (src, dst):
            if nid not in g.nodes:
                g.nodes[nid] = GraphNode(id=nid, type=nid.split(":")[0], label=nid)
        g.edges.append(GraphEdge(src=src, dst=dst, type="REL", weight=weight))
    return g


def _clique(prefix: str, size: int, weight: float = 1.0) -> list[tuple[str, str, float]]:
    names = [f"{prefix}:{i}" for i in range(size)]
    return [(names[i], names[j], weight)
            for i in range(size) for j in range(i + 1, size)]


# ═══════════════════════════════════════════════════════════════════════════
# 1. _num COERCION (regression: string-serialized NUMERIC silently dropped)
# ═══════════════════════════════════════════════════════════════════════════


class TestNumCoercion:
    @pytest.mark.parametrize("raw,expected", [
        ("364517.30", 364517.30),
        ("-4389.05", -4389.05),
        ("147 days, 0:00:00", 147.0),
        ("3 days", 3.0),
        (42, 42.0),
        (3.14, 3.14),
        ("  78.5  ", 78.5),
    ])
    def test_coerces(self, raw, expected):
        assert _num(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [
        "2025-06-19",                              # date
        "0A8181B05BBC4A6C8AD2C2DA1A1F4F2E",        # hex UUID
        True, False,                               # bools are not numbers
        "abc", "", None, "12,5", "EUR 100", [], {},
    ])
    def test_rejects(self, raw):
        assert _num(raw) is None


# ═══════════════════════════════════════════════════════════════════════════
# 2. GRAPH CONSTRUCTION — counts, entity resolution, BUYS granularity
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildEntityGraph:
    def test_node_counts_by_type(self, graph):
        by_type = {}
        for node in graph.nodes.values():
            by_type[node.type] = by_type.get(node.type, 0) + 1
        assert by_type == {
            "customer": 12,
            "segment": 3,
            "category": 4,
            # total_revenue + total_invoices (baseline) + avg_ticket_eur
            # (registry) + churn_risk + dormancy (hubs); period_start is a
            # date and must NOT appear.
            "metric": 5,
            "finding": 4,
            "table": 2,
        }
        assert len(graph.nodes) == 30
        assert "metric:period_start" not in graph.nodes

    def test_edge_counts_by_type(self, graph):
        by_type = {}
        for e in graph.edges:
            by_type[e.type] = by_type.get(e.type, 0) + 1
        assert by_type == {
            "BELONGS_TO": 12,   # every customer → its RFM segment
            "SHARE_OF": 10,     # C001..C010 carry share_pct
            "AT_RISK": 4,       # C005..C008 carry deal_risk_score
            "DORMANT": 4,       # C005..C008 recency_days > 90
            "BUYS": 4,          # cross_sell rows
            "MENTIONS": 3,      # S1→Acme Corp, S2→champions, F3→Ferretería
            "READS": 1,         # invoices → customers
        }

    def test_entity_resolution_merges_attrs_across_queries(self, graph):
        # C005 appears in concentration (share), churn (risk score, interval
        # recency) AND rfm (segment) — ONE node, merged attrs, floats.
        node = graph.nodes["customer:C005"]
        assert node.label == "Estrella Pack"
        assert node.attrs["share_pct"] == pytest.approx(7.0)
        assert node.attrs["deal_risk_score"] == pytest.approx(78.5)   # from "78.5"
        assert node.attrs["ltv_eur"] == pytest.approx(25516.21)      # from string
        assert node.attrs["recency_days"] == pytest.approx(147.0)
        # Non-numeric attrs survive as raw values.
        assert node.attrs["last_purchase"] == "2025-06-19"

    def test_buys_edges_record_segment_granularity(self, graph):
        buys = [e for e in graph.edges if e.type == "BUYS"]
        assert buys and all(e.attrs.get("granularity") == "segment" for e in buys)
        champ = next(e for e in buys
                     if e.src == "segment:champions" and e.dst == "category:Alimentos")
        assert champ.weight == pytest.approx(0.80)   # penetration "80.00" / 100

    def test_share_of_weights_from_string_pct(self, graph):
        acme = next(e for e in graph.edges
                    if e.type == "SHARE_OF" and e.src == "customer:C001")
        assert acme.dst == "metric:total_revenue"
        assert acme.weight == pytest.approx(0.35)    # "35.00" / 100

    def test_accepts_unwrapped_query_results(self):
        entity_map, qr, baseline, findings, registry = make_state()
        plain = qr["results"]                         # no {"results": ...} wrapper
        g = build_entity_graph(entity_map, plain, baseline, findings, registry)
        assert len(g.nodes) == 30

    def test_mentions_resolved_by_normalized_label(self, graph):
        mentions = {(e.src, e.dst) for e in graph.edges if e.type == "MENTIONS"}
        assert mentions == {
            ("finding:S1", "customer:C001"),          # "Acme Corp" in title
            ("finding:S2", "segment:champions"),
            ("finding:F3", "category:Ferretería"),    # accent-insensitive
        }


# ═══════════════════════════════════════════════════════════════════════════
# 3. HUB TRAP REGRESSION — detach vs no detach
# ═══════════════════════════════════════════════════════════════════════════


class TestHubDetach:
    def test_detach_yields_multiple_communities(self, graph):
        comms = detect_communities(graph)
        # metric:total_revenue touches 10 of 12 customers → hub → -1.
        assert comms["metric:total_revenue"] == -1
        assert len({c for c in comms.values() if c >= 0}) >= 3
        # Segments end up in different communities (not glued by the hub).
        assert comms["segment:champions"] != comms["segment:at_risk"]

    def test_no_detach_collapses_hub_dominated_graph(self):
        # Planted: two 4-cliques whose ONLY bridge is a heavy hub touching
        # all 8 nodes (the metric:total_revenue shape).
        edges = _clique("a", 4) + _clique("b", 4)
        for grp in ("a", "b"):
            for i in range(4):
                edges.append(("hub:rev", f"{grp}:{i}", 10.0))
        g = _graph_from_edges(edges)

        detached = detect_communities(g, hub_degree_frac=0.5)
        n_detached = len({c for c in detached.values() if c >= 0})
        assert detached["hub:rev"] == -1
        assert n_detached == 2                         # the two cliques

        glued = detect_communities(g, hub_degree_frac=1.0)   # no detach
        n_glued = len({c for c in glued.values() if c >= 0})
        assert n_glued < n_detached
        assert n_glued == 1                            # hub glues everything


# ═══════════════════════════════════════════════════════════════════════════
# 4. CONNECTIVITY REFINEMENT — cliques bridged only through a hub
# ═══════════════════════════════════════════════════════════════════════════


class TestRefinement:
    def test_hub_bridged_cliques_split(self):
        edges = _clique("x", 3) + _clique("y", 3)
        for grp in ("x", "y"):
            for i in range(3):
                edges.append(("hub:z", f"{grp}:{i}", 1.0))
        g = _graph_from_edges(edges)

        comms = detect_communities(g, hub_degree_frac=0.5)
        assert comms["hub:z"] == -1
        assert comms["x:0"] == comms["x:1"] == comms["x:2"]
        assert comms["y:0"] == comms["y:1"] == comms["y:2"]
        assert comms["x:0"] != comms["y:0"]


# ═══════════════════════════════════════════════════════════════════════════
# 5. PERSONALIZED PAGERANK
# ═══════════════════════════════════════════════════════════════════════════


class TestPersonalizedPagerank:
    def test_distribution_and_locality(self, graph):
        ppr = personalized_pagerank(graph, {"customer:C001": 1.0})
        assert sum(ppr.values()) == pytest.approx(1.0, abs=1e-6)
        assert all(v >= 0 for v in ppr.values())
        # Seed dominates; seed-adjacent beats distant provenance nodes.
        assert ppr["customer:C001"] == max(ppr.values())
        assert ppr["segment:champions"] > ppr["table:invoices"]

    def test_empty_seeds_uniform_teleport(self, graph):
        ppr = personalized_pagerank(graph, {})
        assert sum(ppr.values()) == pytest.approx(1.0, abs=1e-6)
        assert len(ppr) == len(graph.nodes)

    def test_select_seeds_lexical(self, graph):
        seeds = select_seeds("¿Qué riesgo concentra Acme Corp este año?", graph)
        assert seeds == {"customer:C001": 1.0}
        assert select_seeds("zzz nothing matches zzz", graph) == {}


# ═══════════════════════════════════════════════════════════════════════════
# 6. DETERMINISM
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    def test_two_runs_identical(self):
        g1 = build_entity_graph(*make_state())
        g2 = build_entity_graph(*make_state())
        assert sorted(g1.nodes) == sorted(g2.nodes)
        assert [(e.src, e.dst, e.type, e.weight) for e in g1.edges] == \
               [(e.src, e.dst, e.type, e.weight) for e in g2.edges]
        assert detect_communities(g1) == detect_communities(g2)
        assert personalized_pagerank(g1, {"customer:C001": 1.0}) == \
               personalized_pagerank(g2, {"customer:C001": 1.0})


# ═══════════════════════════════════════════════════════════════════════════
# 7. COMMUNITY FACT SHEET (string-numeric inputs!)
# ═══════════════════════════════════════════════════════════════════════════


class TestFactSheet:
    def test_top_share_and_share_sum(self, graph):
        comms = detect_communities(graph)
        sheet = community_fact_sheet(graph, comms, comms["customer:C001"])
        # Top member by SHARE_OF weight — share_pct arrived as string "35.00".
        assert "Acme Corp: 35.0%" in sheet
        # Champions shares: 35 + 20 + 10 + 8 = 73.0 (mix of strings + floats).
        assert "Sum of revenue shares: 73.0%" in sheet
        # The segment's categories and the findings touching it appear.
        assert "Alimentos" in sheet and "Bebidas" in sheet
        assert "champions" in sheet


# ═══════════════════════════════════════════════════════════════════════════
# 8. EVIDENCE CONTEXT — char budget
# ═══════════════════════════════════════════════════════════════════════════


class TestEvidenceContext:
    def test_respects_char_budget(self, graph):
        ppr = personalized_pagerank(graph, {"customer:C001": 1.0})
        small = to_evidence_context(graph, ppr, top_k=30, char_budget=500)
        assert 0 < len(small) <= 500

    def test_top_nodes_present_under_generous_budget(self, graph):
        ppr = personalized_pagerank(graph, {"customer:C001": 1.0})
        ctx = to_evidence_context(graph, ppr, top_k=30, char_budget=6000)
        assert len(ctx) <= 6000
        assert "Acme Corp" in ctx
        assert "SHARE_OF" in ctx
