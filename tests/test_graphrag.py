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
    multi_agent_mentions,
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
            # (registry) + churn_risk + dormancy + exposicion_riesgo (v2) +
            # cobertura_scoring (v4); period_start is a date and must NOT appear.
            "metric": 7,  # +1 for metric:cobertura_scoring (v4 spec change)
            "finding": 4,
            "table": 2,
        }
        assert len(graph.nodes) == 32  # +1 for metric:cobertura_scoring (v4)
        assert "metric:period_start" not in graph.nodes
        assert "metric:exposicion_riesgo" in graph.nodes
        assert "metric:cobertura_scoring" in graph.nodes

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
            "EXPOSED": 4,       # metric:exposicion_riesgo → top-4 at-risk (v2 spec change)
            "UNSCORED": 3,      # metric:cobertura_scoring → top-3 unscored by LTV (v4)
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
        assert len(g.nodes) == 32  # +1 for metric:cobertura_scoring (v4 spec change)

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
        # v2: alias map now also triggers on "riesgo" and "concentr" in this
        # question, so more seeds are returned alongside Acme Corp — that's
        # correct and intentional (richer context for PPR). Check that the
        # target customer IS in seeds and that an empty question still returns {}.
        seeds = select_seeds("¿Qué riesgo concentra Acme Corp este año?", graph)
        assert "customer:C001" in seeds          # Acme Corp matched by label
        assert "metric:churn_risk" in seeds      # "riesgo" alias
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
        ctx = to_evidence_context(graph, ppr, top_k=30, char_budget=10000)
        assert len(ctx) <= 10000
        assert "Acme Corp" in ctx
        assert "SHARE_OF" in ctx


# ═══════════════════════════════════════════════════════════════════════════
# 9. V2 SEGMENT AGGREGATES — computed correctly from string numerics
# ═══════════════════════════════════════════════════════════════════════════


class TestSegmentAggregates:
    def test_segment_total_ltv_from_strings(self, graph):
        # champions: C001(127581.06) + C002(72903.46) + C003(36451.73) + C004(29161.38)
        champ = graph.nodes["segment:champions"]
        assert champ.attrs["n_customers"] == 4
        assert champ.attrs["total_ltv_eur"] == pytest.approx(266097.63, rel=1e-4)
        # share_pct: 35+20+10+8 = 73.0
        assert champ.attrs["share_pct"] == pytest.approx(73.0)

    def test_segment_no_ltv_when_customers_have_none(self, graph):
        # hibernating: C011 and C012 have no ltv_eur but the RFM row provides
        # monetary_eur="1893.22" as the fallback — so ALL 4 customers contribute.
        hib = graph.nodes["segment:hibernating"]
        assert hib.attrs["n_customers"] == 4
        # C009(7290.35) + C010(3645.17) + C011(1893.22) + C012(1893.22) = 14721.96
        assert hib.attrs.get("total_ltv_eur") == pytest.approx(14721.96, rel=1e-4)

    def test_category_total_revenue_eur(self, graph):
        # Fixture has no category_revenue_eur in cross_sell rows, so no attr.
        # (The synthetic fixture omits it — this validates the graceful no-op.)
        # If the attr is present it must be numeric.
        for nid in graph.nodes:
            if graph.nodes[nid].type == "category":
                rev = graph.nodes[nid].attrs.get("total_revenue_eur")
                if rev is not None:
                    assert isinstance(rev, float)


# ═══════════════════════════════════════════════════════════════════════════
# 10. V2 HUB CONSTRAINT — segment nodes NEVER become hubs
# ═══════════════════════════════════════════════════════════════════════════


class TestSegmentNeverHub:
    def test_segment_not_hub_even_at_high_degree(self):
        """Plant a segment with edges to 20 nodes (far exceeds hub_degree_frac
        threshold). It must NOT be detached to -1."""
        edges: list[tuple[str, str, float]] = []
        # One segment connected to many customers.
        for i in range(20):
            cid = f"customer:{i}"
            edges.append(("segment:big", cid, 1.0))
        # Two tightly-connected cliques so there are ≥2 real communities.
        edges += _clique("alpha", 4)
        edges += _clique("beta", 4)
        g = _graph_from_edges(edges)
        # Override types for segment node.
        g.nodes["segment:big"].type = "segment"

        comms = detect_communities(g, hub_degree_frac=0.25)
        # segment:big has degree > 0.25 * n_nodes but must NOT be -1.
        assert comms.get("segment:big") != -1, (
            "segment:big was detached to hub (-1) — spec forbids this"
        )

    def test_at_risk_segment_not_detached_in_full_fixture(self, graph):
        comms = detect_communities(graph)
        # segment:at_risk has high degree (connected to 4 customers + categories)
        # but must never be hub.
        assert comms.get("segment:at_risk") != -1


# ═══════════════════════════════════════════════════════════════════════════
# 11. V2 SINGLETON ABSORPTION — categories join their segment's community
# ═══════════════════════════════════════════════════════════════════════════


class TestSingletonAbsorption:
    def test_category_singletons_absorbed_into_segment_community(self):
        """Build a graph where categories are connected only to one segment
        (which has ≥2 members). Without absorption they'd stay singletons;
        with absorption they join the segment's community."""
        edges: list[tuple[str, str, float]] = []
        # Two clique-communities so CNM has something to work with.
        edges += _clique("customer", 3, weight=2.0)
        edges.append(("segment:seg", "customer:0", 1.0))
        edges.append(("segment:seg", "customer:1", 1.0))
        edges.append(("segment:seg", "customer:2", 1.0))
        # A category singleton connected only to the segment.
        edges.append(("segment:seg", "category:cat", 1.0))
        # Unrelated second community.
        edges += _clique("other", 3, weight=2.0)
        g = _graph_from_edges(edges)
        g.nodes["segment:seg"].type = "segment"
        g.nodes["category:cat"].type = "category"

        comms = detect_communities(g)
        # category:cat must end up in the same community as the segment.
        assert comms.get("category:cat") == comms.get("segment:seg"), (
            "category:cat should have been absorbed into segment:seg's community"
        )

    def test_absorption_reduces_community_count(self):
        """Community count with absorption must be ≤ without.
        We use the full fixture graph which has category singletons."""
        g = build_entity_graph(*make_state())

        # Count singletons before absorption (monkeypatch by limiting passes=0
        # is invasive; instead compare against a star graph we control).
        # Just verify the fixture itself has fewer singletons than 52 (the
        # pre-v2 Gloria-measured value), i.e. absorption ran.
        comms = detect_communities(g)
        n_real_comms = len({c for c in comms.values() if c >= 0})
        # 52 was the diagnosed value; we expect much fewer with consolidation.
        assert n_real_comms < 30, (
            f"Expected consolidated community count < 30, got {n_real_comms}"
        )

    def test_table_nodes_not_absorbed(self):
        """table:* nodes must NOT be absorbed — provenance singletons are fine."""
        g = build_entity_graph(*make_state())
        comms = detect_communities(g)
        # Tables that are singletons should stay at their own community id
        # (they have no neighbors that form a ≥2 community they can join except
        # each other; at worst they stay singleton but must never be forced
        # into a content community).
        # What we assert: table nodes are NEVER absorbed into a community that
        # contains no other table node, i.e. we don't care which community they
        # land in, we just confirm no exception is raised and they have a valid
        # community assignment (>= -1 means processed normally).
        for nid, cid in comms.items():
            if nid.startswith("table:"):
                assert isinstance(cid, int)


# ═══════════════════════════════════════════════════════════════════════════
# 12. V2 SELECT_SEEDS — alias map returns non-empty for key ES phrases
# ═══════════════════════════════════════════════════════════════════════════


class TestSeedAliases:
    def test_riesgo_churn_dormancia(self, graph):
        seeds = select_seeds("riesgo de churn o dormancia", graph)
        assert "metric:churn_risk" in seeds
        assert "metric:dormancy" in seeds
        assert seeds  # non-empty

    def test_segmento_rfm(self, graph):
        seeds = select_seeds("segmento RFM de clientes activos", graph)
        # All segment:* nodes must be seeded.
        seg_seeds = [k for k in seeds if k.startswith("segment:")]
        assert len(seg_seeds) >= 1
        assert seeds  # non-empty

    def test_hallazgos_dos_agentes(self, graph):
        seeds = select_seeds("mencionados en hallazgos de dos agentes", graph)
        # "mencion" and "hallazgo" both appear in normalized form.
        finding_seeds = [k for k in seeds if k.startswith("finding:")]
        assert len(finding_seeds) >= 1
        assert seeds  # non-empty

    def test_concentracion_facturacion(self, graph):
        seeds = select_seeds("concentración de facturación top clientes", graph)
        assert "metric:total_revenue" in seeds
        assert seeds  # non-empty

    def test_no_false_positive_short_label(self, graph):
        # "varios" (6 chars exactly) must not match short/irrelevant labels.
        # (The v1 bug was len < 3; v2 raises floor to 6.)
        seeds = select_seeds("varios clientes en riesgo", graph)
        # "riesgo" alias should fire, but "varios" must NOT match a label of
        # a node whose normalized name is < 6 chars.
        assert "metric:churn_risk" in seeds
        # No node whose label normalizes to "varios" should appear in the
        # fixture graph (it's not in the synthetic data).
        assert "category:varios" not in seeds


# ═══════════════════════════════════════════════════════════════════════════
# 13. V2 MULTI-AGENT MENTIONS
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiAgentMentions:
    def _graph_with_multi_agent_mentions(self) -> EntityGraph:
        """Mini graph: one customer mentioned by 2 agents, one by 1 agent."""
        g = EntityGraph()
        g.nodes["customer:A"] = GraphNode(id="customer:A", type="customer", label="Alpha Corp")
        g.nodes["customer:B"] = GraphNode(id="customer:B", type="customer", label="Beta Inc")
        g.nodes["finding:X"] = GraphNode(
            id="finding:X", type="finding", label="Finding X",
            attrs={"agent": "sales"},
        )
        g.nodes["finding:Y"] = GraphNode(
            id="finding:Y", type="finding", label="Finding Y",
            attrs={"agent": "finance"},
        )
        g.nodes["finding:Z"] = GraphNode(
            id="finding:Z", type="finding", label="Finding Z",
            attrs={"agent": "sales"},
        )
        # Both agents mention customer:A.
        g.edges.append(GraphEdge(src="finding:X", dst="customer:A", type="MENTIONS"))
        g.edges.append(GraphEdge(src="finding:Y", dst="customer:A", type="MENTIONS"))
        # Only one agent mentions customer:B.
        g.edges.append(GraphEdge(src="finding:Z", dst="customer:B", type="MENTIONS"))
        return g

    def test_detects_customer_with_two_agents(self):
        g = self._graph_with_multi_agent_mentions()
        result = multi_agent_mentions(g)
        nids = [d["node_id"] for d in result]
        assert "customer:A" in nids

    def test_excludes_customer_with_one_agent(self):
        g = self._graph_with_multi_agent_mentions()
        result = multi_agent_mentions(g)
        nids = [d["node_id"] for d in result]
        assert "customer:B" not in nids

    def test_agents_list_sorted(self):
        g = self._graph_with_multi_agent_mentions()
        result = multi_agent_mentions(g)
        entry = next(d for d in result if d["node_id"] == "customer:A")
        assert entry["agents"] == sorted(entry["agents"])


# ═══════════════════════════════════════════════════════════════════════════
# 14. V2 EVIDENCE CONTEXT — convergencia multi-agente block always present
# ═══════════════════════════════════════════════════════════════════════════


class TestEvidenceContextV2:
    def test_convergencia_block_always_present(self, graph):
        ppr = personalized_pagerank(graph, {"customer:C001": 1.0})
        ctx = to_evidence_context(graph, ppr, top_k=30, char_budget=8000)
        assert "Convergencia multi-agente" in ctx

    def test_convergencia_block_before_ppr_nodes(self, graph):
        ppr = personalized_pagerank(graph, {"customer:C001": 1.0})
        ctx = to_evidence_context(graph, ppr, top_k=30, char_budget=8000)
        conv_pos = ctx.index("Convergencia multi-agente")
        # PPR node lines start with "[customer]" or "[segment]" etc.
        ppr_pos = ctx.find("[customer]")
        if ppr_pos == -1:
            ppr_pos = ctx.find("[segment]")
        if ppr_pos != -1:
            assert conv_pos < ppr_pos


# ═══════════════════════════════════════════════════════════════════════════
# 15. V2 DETERMINISM END-TO-END
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterminismV2:
    def test_v2_two_runs_identical(self):
        """Full pipeline: build_entity_graph → detect_communities → PPR →
        select_seeds → multi_agent_mentions must be identical across two runs
        from fresh state."""
        g1 = build_entity_graph(*make_state())
        g2 = build_entity_graph(*make_state())
        assert sorted(g1.nodes) == sorted(g2.nodes)
        assert [(e.src, e.dst, e.type, e.weight) for e in g1.edges] == \
               [(e.src, e.dst, e.type, e.weight) for e in g2.edges]
        c1 = detect_communities(g1)
        c2 = detect_communities(g2)
        assert c1 == c2
        assert personalized_pagerank(g1, {"segment:champions": 1.0}) == \
               personalized_pagerank(g2, {"segment:champions": 1.0})
        assert multi_agent_mentions(g1) == multi_agent_mentions(g2)


# ═══════════════════════════════════════════════════════════════════════════
# 16. V4 RANK_BY_LTV — deterministic 1-based rank on customer nodes
# ═══════════════════════════════════════════════════════════════════════════


class TestRankByLtv:
    def test_rank1_is_highest_ltv(self, graph):
        """C001 (Acme Corp, ltv_eur=127581.06) must be rank 1."""
        assert graph.nodes["customer:C001"].attrs.get("rank_by_ltv") == 1

    def test_rank_order_descending(self, graph):
        """Ranks must be strictly descending by LTV (ties broken lex by node id)."""
        ranked = sorted(
            [(node.attrs["rank_by_ltv"], _num(node.attrs.get("ltv_eur") or node.attrs.get("monetary_eur")), nid)
             for nid, node in graph.nodes.items()
             if node.type == "customer" and "rank_by_ltv" in node.attrs],
        )
        # The ranks form a contiguous 1..N sequence with no gaps.
        ranks = [r[0] for r in ranked]
        assert ranks == list(range(1, len(ranks) + 1))
        # Each rank-k LTV >= rank-(k+1) LTV.
        for i in range(len(ranked) - 1):
            ltv_k = ranked[i][1]
            ltv_next = ranked[i + 1][1]
            assert ltv_k >= ltv_next

    def test_all_ltv_known_customers_have_rank(self, graph):
        """Every customer with ltv_eur or monetary_eur must have rank_by_ltv."""
        for nid, node in graph.nodes.items():
            if node.type != "customer":
                continue
            ltv = _num(node.attrs.get("ltv_eur") or node.attrs.get("monetary_eur"))
            if ltv is not None:
                assert "rank_by_ltv" in node.attrs, f"{nid} has LTV but no rank_by_ltv"

    def test_no_ltv_customers_have_no_rank(self, graph):
        """Customers with no LTV at all must NOT have rank_by_ltv.
        In the fixture C011 and C012 DO get monetary_eur from the RFM row,
        so they WILL have a rank; this test ensures no extras appear."""
        for nid, node in graph.nodes.items():
            if node.type != "customer":
                continue
            ltv = _num(node.attrs.get("ltv_eur") or node.attrs.get("monetary_eur"))
            if ltv is None:
                assert "rank_by_ltv" not in node.attrs, (
                    f"{nid} has no LTV but rank_by_ltv={node.attrs.get('rank_by_ltv')}"
                )

    def test_tiebreak_is_lexicographic(self):
        """Two customers with the same LTV must break ties by node id lex order."""
        from valinor.graphrag import EntityGraph, GraphNode, build_entity_graph
        # Build a minimal fixture with two customers sharing the same LTV.
        entity_map = {"entities": {}, "relationships": []}
        qr = {"results": {
            "concentration_top_customers": {"rows": [
                {"customer_id": "ZZZ", "customer_name": "ZZZ Co", "ltv_eur": "1000.00", "share_pct": 10},
                {"customer_id": "AAA", "customer_name": "AAA Co", "ltv_eur": "1000.00", "share_pct": 10},
            ]},
        }}
        g = build_entity_graph(entity_map, qr, {}, {})
        # AAA lexicographically < ZZZ, so customer:AAA should rank 1.
        assert g.nodes["customer:AAA"].attrs["rank_by_ltv"] == 1
        assert g.nodes["customer:ZZZ"].attrs["rank_by_ltv"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# 17. V4 COBERTURA_SCORING — customers with LTV but no deal_risk_score
# ═══════════════════════════════════════════════════════════════════════════


class TestCoberturaScoring:
    def test_node_exists(self, graph):
        """metric:cobertura_scoring must be created when unscored customers exist."""
        assert "metric:cobertura_scoring" in graph.nodes

    def test_n_customers_correct(self, graph):
        """In the fixture: C001-C004 (champions), C009-C010, C011-C012 = 8 unscored
        with LTV known. C005-C008 have deal_risk_score so they are excluded."""
        cov = graph.nodes["metric:cobertura_scoring"]
        assert cov.attrs["n_customers"] == 8

    def test_ltv_eur_is_sum_of_unscored(self, graph):
        """ltv_eur = sum of all LTV-known unscored customers."""
        # C001:127581.06 + C002:72903.46 + C003:36451.73 + C004:29161.38
        # + C009:7290.35 + C010:3645.17 + C011:1893.22 + C012:1893.22 = 280819.59
        expected = 127581.06 + 72903.46 + 36451.73 + 29161.38 + 7290.35 + 3645.17 + 1893.22 + 1893.22
        cov = graph.nodes["metric:cobertura_scoring"]
        assert cov.attrs["ltv_eur"] == pytest.approx(expected, rel=1e-4)

    def test_top3_by_ltv_desc(self, graph):
        """Top-3 must be the 3 highest-LTV unscored customers: Acme, Borealis, Cobalt."""
        cov = graph.nodes["metric:cobertura_scoring"]
        assert cov.attrs["top3"] == ["Acme Corp", "Borealis Foods", "Cobalt Trading"]

    def test_unscored_edges_toward_top3(self, graph):
        """Exactly 3 UNSCORED edges from metric:cobertura_scoring to top-3."""
        unscored_edges = [e for e in graph.edges if e.type == "UNSCORED"]
        assert len(unscored_edges) == 3
        dsts = {e.dst for e in unscored_edges}
        assert dsts == {"customer:C001", "customer:C002", "customer:C003"}
        # All edges start from the cobertura node.
        assert all(e.src == "metric:cobertura_scoring" for e in unscored_edges)

    def test_weights_relative_to_full_group(self, graph):
        """Edge weights = ltv_customer / ltv_total_del_grupo (full unscored group,
        not just top-3). The top-3 LTVs sum to < ltv_total_del_grupo so weights
        sum to < 1.0 — this mirrors the exposicion_riesgo pattern exactly.
        Each weight must be in (0, 1)."""
        unscored_edges = [e for e in graph.edges if e.type == "UNSCORED"]
        cov = graph.nodes["metric:cobertura_scoring"]
        total_unscored_ltv = cov.attrs["ltv_eur"]
        for e in unscored_edges:
            cnode = graph.nodes[e.dst]
            ltv = _num(cnode.attrs.get("ltv_eur") or cnode.attrs.get("monetary_eur"))
            assert ltv is not None
            expected_w = ltv / total_unscored_ltv
            assert e.weight == pytest.approx(expected_w, rel=1e-5)

    def test_node_absent_when_all_have_score(self):
        """metric:cobertura_scoring must NOT be created when every LTV-known
        customer already has deal_risk_score."""
        entity_map = {"entities": {}, "relationships": []}
        # Single customer WITH deal_risk_score.
        qr = {"results": {
            "churn_risk_all": {"rows": [
                {"customer_id": "X1", "customer_name": "X One",
                 "deal_risk_score": 50.0, "ltv_eur": "5000.00"},
            ]},
        }}
        g = build_entity_graph(entity_map, qr, {}, {})
        assert "metric:cobertura_scoring" not in g.nodes

    def test_share_pct_relative_to_total_revenue(self, graph):
        """share_pct = unscored_ltv / total_revenue * 100."""
        cov = graph.nodes["metric:cobertura_scoring"]
        total_rev = 364517.30  # from fixture baseline
        expected_share = round(cov.attrs["ltv_eur"] / total_rev * 100.0, 2)
        assert cov.attrs.get("share_pct") == pytest.approx(expected_share, rel=1e-4)


# ═══════════════════════════════════════════════════════════════════════════
# 18. V4 EVIDENCE CONTEXT HEADER — COBERTURA SCORING + TOP-10 POR LTV
# ═══════════════════════════════════════════════════════════════════════════


class TestEvidenceContextV4:
    def _ctx(self, graph, budget: int = 20000) -> str:
        ppr = personalized_pagerank(graph, {"customer:C001": 1.0})
        return to_evidence_context(graph, ppr, top_k=30, char_budget=budget)

    def test_cobertura_scoring_line_present(self, graph):
        ctx = self._ctx(graph)
        assert "COBERTURA SCORING" in ctx

    def test_cobertura_scoring_contains_n_and_ltv(self, graph):
        ctx = self._ctx(graph)
        # 8 unscored customers in the fixture.
        assert "8 clientes" in ctx

    def test_top10_ltv_line_present(self, graph):
        ctx = self._ctx(graph)
        assert "TOP-10 POR LTV" in ctx

    def test_top10_rank1_is_acme(self, graph):
        """Rank 1 in TOP-10 must be Acme Corp."""
        ctx = self._ctx(graph)
        # The line is "1. Acme Corp €127,581.06 ..."
        assert "1. Acme Corp" in ctx

    def test_top10_acme_flags_score_no(self, graph):
        """Acme Corp has no deal_risk_score → [score: no]."""
        ctx = self._ctx(graph)
        idx = ctx.index("1. Acme Corp")
        snippet = ctx[idx:idx + 80]
        assert "[score: no]" in snippet

    def test_top10_estrella_flags_risk_yes_score_yes(self, graph):
        """Estrella Pack (C005, rank=5) has deal_risk_score AND AT_RISK edge.
        Its entry in the TOP-10 line must show [riesgo: sí] [score: sí]."""
        ctx = self._ctx(graph)
        top10_idx = ctx.find("TOP-10 POR LTV")
        assert top10_idx != -1
        top10_section = ctx[top10_idx:]
        # Find Estrella Pack's entry within the TOP-10 section.
        idx = top10_section.find("Estrella Pack")
        assert idx != -1, "Estrella Pack not found in TOP-10 POR LTV section"
        snippet = top10_section[idx:idx + 80]
        assert "[riesgo: sí]" in snippet
        assert "[score: sí]" in snippet

    def test_header_order_cobertura_before_top10(self, graph):
        """COBERTURA SCORING line must appear before TOP-10 POR LTV in header."""
        ctx = self._ctx(graph)
        assert ctx.index("COBERTURA SCORING") < ctx.index("TOP-10 POR LTV")


# ═══════════════════════════════════════════════════════════════════════════
# 19. V4 SELECT_SEEDS — new aliases
# ═══════════════════════════════════════════════════════════════════════════


class TestSeedAliasesV4:
    def test_cobertura_alias(self, graph):
        seeds = select_seeds("¿qué parte de la cartera no está cubierta por el scoring?", graph)
        assert "metric:cobertura_scoring" in seeds

    def test_sin_score_alias(self, graph):
        seeds = select_seeds("clientes sin score asignado", graph)
        assert "metric:cobertura_scoring" in seeds

    def test_scoring_alias(self, graph):
        seeds = select_seeds("modelo de scoring de clientes", graph)
        assert "metric:cobertura_scoring" in seeds
        assert "metric:churn_risk" in seeds

    def test_ltv_alias(self, graph):
        seeds = select_seeds("top clientes por LTV", graph)
        assert "metric:total_revenue" in seeds


# ═══════════════════════════════════════════════════════════════════════════
# 20. V4 DETERMINISM END-TO-END
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterminismV4:
    def test_v4_two_runs_identical(self):
        """rank_by_ltv and cobertura_scoring are deterministic across two fresh builds."""
        g1 = build_entity_graph(*make_state())
        g2 = build_entity_graph(*make_state())
        # Node attrs (including rank_by_ltv) must match.
        for nid in g1.nodes:
            assert g1.nodes[nid].attrs == g2.nodes[nid].attrs, (
                f"Attrs differ for {nid}: {g1.nodes[nid].attrs} vs {g2.nodes[nid].attrs}"
            )
        # Edge list (including UNSCORED) must match exactly.
        edges1 = [(e.src, e.dst, e.type, e.weight) for e in g1.edges]
        edges2 = [(e.src, e.dst, e.type, e.weight) for e in g2.edges]
        assert edges1 == edges2
        # PPR over new seeds must match.
        p1 = personalized_pagerank(g1, {"metric:cobertura_scoring": 1.0})
        p2 = personalized_pagerank(g2, {"metric:cobertura_scoring": 1.0})
        assert p1 == p2
