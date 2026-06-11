"""
GraphRAG-mínimo — instance-level entity graph + communities + PPR (VAL-192 N3).

The schema-level Knowledge Graph has no community structure at 7 nodes; the
value of GraphRAG for this pipeline is at INSTANCE level: the concrete
customers, segments, categories, metrics and findings that come out of the
post-verification pipeline state. This module builds that graph
DETERMINISTICALLY — zero LLM in graph construction. The LLM only ever
narrates fact sheets produced here; it NEVER calculates.

What lives here:

  * build_entity_graph     — entity resolution across query results (the same
                             customer_id seen in concentration / churn / RFM /
                             dormant queries becomes ONE node with merged
                             attrs — this resolution is the value), plus
                             typed edges (BELONGS_TO, SHARE_OF, AT_RISK,
                             DORMANT, BUYS, MENTIONS, READS, EXPOSED).
                             v2: segment aggregates (total_ltv_eur, share_pct,
                             n_customers), category total_revenue_eur, and
                             metric:exposicion_riesgo synthetic node.
  * detect_communities     — hub detach (never segments/categories) →
                             greedy modularity (CNM) → connectivity refinement
                             → singleton absorption (excl. table nodes).
  * personalized_pagerank  — dense numpy power iteration, seed-biased.
  * select_seeds           — alias map (ES terms) + lexical fallback. No
                             embeddings.
  * multi_agent_mentions   — customers/segments/categories mentioned by ≥2
                             distinct agents.
  * community_fact_sheet / to_evidence_context — deterministic text blocks
                             for downstream narration.

Honesty note: greedy modularity (CNM) + connectivity refinement is
Leiden-equivalent at n<500; leidenalg/igraph rejected as dependency theater.

All numeric coercion goes through `_num`, which understands DB-string
serialization ("364517.30") and Postgres intervals ("147 days, 0:00:00") —
lesson from a real bug where drivers serialized NUMERIC as strings and a
prior instrument silently dropped them.

Domain purity: stdlib + numpy only. No LLM, no DB, no infra imports.

Refs: VAL-192 (N3 v2)
"""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class GraphNode:
    """A typed instance-level node (customer / segment / category / metric /
    finding / table)."""
    id: str
    type: str
    label: str
    attrs: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """A typed weighted edge. `attrs` carries edge-level provenance flags
    (e.g. BUYS granularity="segment": customer→category is ALWAYS a 2-hop
    inference, never asserted directly)."""
    src: str
    dst: str
    type: str
    weight: float = 1.0
    attrs: dict = field(default_factory=dict)


@dataclass
class EntityGraph:
    """Instance-level entity graph: nodes keyed by id + typed edge list."""
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)

    def adjacency(self) -> tuple[np.ndarray, list[str]]:
        """Dense symmetric weighted adjacency W = A + A^T over edge weights,
        plus the ordered node-id list (sorted for determinism)."""
        node_ids = sorted(self.nodes)
        idx = {nid: i for i, nid in enumerate(node_ids)}
        a = np.zeros((len(node_ids), len(node_ids)), dtype=float)
        for e in self.edges:
            if e.src in idx and e.dst in idx and e.src != e.dst:
                a[idx[e.src], idx[e.dst]] += e.weight
        return a + a.T, node_ids

    def degree(self, node_id: str) -> float:
        """Weighted degree (sum of incident edge weights, both directions)."""
        return float(sum(
            e.weight for e in self.edges
            if node_id in (e.src, e.dst) and e.src != e.dst
        ))

    def neighbors(self, node_id: str) -> list[str]:
        """Sorted distinct neighbor ids."""
        out: set[str] = set()
        for e in self.edges:
            if e.src == node_id and e.dst != node_id:
                out.add(e.dst)
            elif e.dst == node_id and e.src != node_id:
                out.add(e.src)
        return sorted(out)


# ═══════════════════════════════════════════════════════════════════════════
# NUMERIC COERCION
# ═══════════════════════════════════════════════════════════════════════════

_INTERVAL_RE = re.compile(r"^([-+]?\d+(?:\.\d+)?)\s*days?\b", re.IGNORECASE)
_NUMERIC_RE = re.compile(r"^[-+]?\d+(?:\.\d+)?$")


def _num(v: Any) -> Optional[float]:
    """Numeric coercion including DB-string serialization.

    Accepts: int/float, "364517.30", "-4389.05", Postgres intervals
    ("147 days, 0:00:00" → 147.0). Rejects (→ None): bools, dates
    ("2025-06-19"), hex UUIDs, anything not purely numeric.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        m = _INTERVAL_RE.match(s)
        if m:
            return float(m.group(1))
        if _NUMERIC_RE.match(s):
            return float(s)
    return None


def _normalize(text: str) -> str:
    """Deterministic name normalization: lowercase, strip accents, strip
    punctuation, collapse whitespace. Used for MENTIONS and seed matching."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


# ═══════════════════════════════════════════════════════════════════════════
# GRAPH CONSTRUCTION (zero LLM)
# ═══════════════════════════════════════════════════════════════════════════

# Query-name substrings that yield customer rows (entity resolution sources).
_CUSTOMER_QUERY_HINTS = ("concentration_top_customers", "churn_risk",
                         "rfm_segmentation", "dormant")

# Fields that, merged across queries, indicate days since last purchase.
_RECENCY_FIELDS = ("recency_days", "days_since_purchase", "days_since_last_purchase")

_DORMANCY_THRESHOLD_DAYS = 90
_FINDING_TEXT_TRUNC = 160


def _short(value: Any, limit: int = _FINDING_TEXT_TRUNC) -> str:
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _rows_of(qdata: Any) -> list[dict]:
    if isinstance(qdata, dict):
        rows = qdata.get("rows", [])
    elif isinstance(qdata, list):
        rows = qdata
    else:
        rows = []
    return [r for r in rows if isinstance(r, dict)]


def _ensure_metric(graph: EntityGraph, label: str, value: Optional[float] = None) -> str:
    nid = f"metric:{label}"
    if nid not in graph.nodes:
        attrs = {"value": value} if value is not None else {}
        graph.nodes[nid] = GraphNode(id=nid, type="metric", label=label, attrs=attrs)
    elif value is not None and "value" not in graph.nodes[nid].attrs:
        graph.nodes[nid].attrs["value"] = value
    return nid


def _registry_value(entry: Any) -> Optional[float]:
    """Number-registry entries arrive as dicts, dataclass-likes or raw scalars."""
    if isinstance(entry, dict):
        return _num(entry.get("value"))
    if hasattr(entry, "value"):
        return _num(entry.value)
    return _num(entry)


def build_entity_graph(
    entity_map: dict,
    query_results: dict,
    baseline: dict,
    findings: dict,
    number_registry: Optional[dict] = None,
) -> EntityGraph:
    """Build the instance-level entity graph from post-verification state.

    Entity resolution: the same customer_id appearing in multiple queries
    (concentration / churn / RFM / dormant) becomes ONE node with attrs merged
    across queries — THIS is where the value is. All numerics pass `_num`.

    v2 additions:
    - Segment nodes: total_ltv_eur, share_pct, n_customers aggregates.
    - Category nodes: total_revenue_eur from cross_sell rows.
    - metric:exposicion_riesgo synthetic node for at-risk / dormant customers.
    """
    graph = EntityGraph()
    qr = query_results if isinstance(query_results, dict) else {}
    results = qr.get("results", qr)
    if not isinstance(results, dict):
        results = {}

    # ── customer / segment / category nodes from query rows ───────────────
    dormant_query_customers: set[str] = set()
    customer_query_names = sorted(
        name for name in results
        if any(h in name.lower() for h in _CUSTOMER_QUERY_HINTS)
    )
    for qname in customer_query_names:
        is_dormant_query = "dormant" in qname.lower()
        for row in _rows_of(results[qname]):
            cust_id = row.get("customer_id")
            if cust_id is None:
                continue
            nid = f"customer:{cust_id}"
            node = graph.nodes.get(nid)
            if node is None:
                node = GraphNode(id=nid, type="customer", label=str(cust_id)[:12])
                graph.nodes[nid] = node
            name = row.get("customer_name")
            if name:
                node.label = str(name)
            for k, v in row.items():
                if k in ("customer_id", "customer_name"):
                    continue
                n = _num(v)
                node.attrs[k] = n if n is not None else v
            if is_dormant_query:
                dormant_query_customers.add(nid)
            # segment nodes + membership (from RFM rows)
            seg = row.get("segment") or row.get("rfm_segment")
            if seg and "rfm" in qname.lower():
                seg_id = f"segment:{seg}"
                if seg_id not in graph.nodes:
                    graph.nodes[seg_id] = GraphNode(id=seg_id, type="segment", label=str(seg))
                graph.edges.append(GraphEdge(src=nid, dst=seg_id, type="BELONGS_TO"))

    # ── category nodes + BUYS edges from cross_sell_matrix ─────────────────
    # Also collect category_revenue_eur per category for v2 aggregate.
    _cat_revenue_acc: dict[str, float] = {}
    for qname in sorted(n for n in results if "cross_sell" in n.lower()):
        for row in _rows_of(results[qname]):
            cat = row.get("category")
            seg = row.get("segment") or row.get("rfm_segment")
            if not cat:
                continue
            cat_id = f"category:{cat}"
            if cat_id not in graph.nodes:
                graph.nodes[cat_id] = GraphNode(id=cat_id, type="category", label=str(cat))
            # Accumulate category revenue across all segment rows.
            rev_val = _num(row.get("category_revenue_eur") or row.get("revenue"))
            if rev_val is not None:
                _cat_revenue_acc[cat_id] = _cat_revenue_acc.get(cat_id, 0.0) + rev_val
            if not seg:
                continue
            seg_id = f"segment:{seg}"
            if seg_id not in graph.nodes:
                graph.nodes[seg_id] = GraphNode(id=seg_id, type="segment", label=str(seg))
            pen = _num(row.get("penetration_pct"))
            graph.edges.append(GraphEdge(
                src=seg_id, dst=cat_id, type="BUYS",
                weight=(pen / 100.0) if pen is not None else 1.0,
                # customer→category is ALWAYS a 2-hop inference — record it.
                attrs={"granularity": "segment"},
            ))

    # Apply category total_revenue_eur attrs.
    for cat_id, total_rev in _cat_revenue_acc.items():
        if cat_id in graph.nodes:
            graph.nodes[cat_id].attrs["total_revenue_eur"] = round(total_rev, 2)

    # ── metric nodes from baseline + number_registry ───────────────────────
    if isinstance(baseline, dict):
        for key in sorted(baseline):
            val = _num(baseline[key])
            if val is not None:
                _ensure_metric(graph, key, val)
    for label in sorted(number_registry or {}):
        val = _registry_value((number_registry or {})[label])
        if val is not None:
            _ensure_metric(graph, label, val)

    # ── finding nodes ───────────────────────────────────────────────────────
    finding_texts: dict[str, str] = {}  # finding node id → concatenated text
    if isinstance(findings, dict):
        for agent in sorted(findings):
            agent_data = findings[agent]
            items = (agent_data.get("findings", []) if isinstance(agent_data, dict)
                     else agent_data if isinstance(agent_data, list) else [])
            for item in items:
                if not isinstance(item, dict) or "id" not in item:
                    continue
                fid = f"finding:{item['id']}"
                title = (item.get("title") or item.get("headline")
                         or item.get("desc") or item.get("description") or "")
                graph.nodes[fid] = GraphNode(
                    id=fid, type="finding", label=_short(title) or str(item["id"]),
                    attrs={"agent": agent, "title": _short(title)},
                )
                finding_texts[fid] = " ".join(
                    str(v) for v in item.values() if isinstance(v, str)
                )

    # ── table nodes (provenance layer) ──────────────────────────────────────
    entities = entity_map.get("entities", {}) if isinstance(entity_map, dict) else {}
    for ename in sorted(entities):
        edata = entities[ename]
        tname = edata.get("table", ename) if isinstance(edata, dict) else ename
        tid = f"table:{ename}"
        graph.nodes[tid] = GraphNode(id=tid, type="table", label=str(tname))

    # ── SHARE_OF / AT_RISK / DORMANT edges from merged customer attrs ───────
    total_rev_node = graph.nodes.get("metric:total_revenue")
    total_rev = _num(total_rev_node.attrs.get("value")) if total_rev_node else None
    for nid in sorted(graph.nodes):
        node = graph.nodes[nid]
        if node.type != "customer":
            continue
        share = _num(node.attrs.get("share_pct"))
        ltv = _num(node.attrs.get("ltv_eur"))
        if share is not None:
            mid = _ensure_metric(graph, "total_revenue", total_rev)
            graph.edges.append(GraphEdge(src=nid, dst=mid, type="SHARE_OF",
                                         weight=share / 100.0))
        elif ltv is not None and total_rev:
            mid = _ensure_metric(graph, "total_revenue", total_rev)
            graph.edges.append(GraphEdge(src=nid, dst=mid, type="SHARE_OF",
                                         weight=ltv / total_rev))
        risk = _num(node.attrs.get("deal_risk_score"))
        if risk is not None:
            mid = _ensure_metric(graph, "churn_risk")
            graph.edges.append(GraphEdge(src=nid, dst=mid, type="AT_RISK",
                                         weight=risk / 100.0))
        recency = next(
            (r for r in (_num(node.attrs.get(f)) for f in _RECENCY_FIELDS)
             if r is not None),
            None,
        )
        if (recency is not None and recency > _DORMANCY_THRESHOLD_DAYS) \
                or nid in dormant_query_customers:
            mid = _ensure_metric(graph, "dormancy")
            graph.edges.append(GraphEdge(src=nid, dst=mid, type="DORMANT"))

    # ── MENTIONS: finding → customer/segment/category by normalized label ──
    mention_targets = sorted(
        nid for nid, n in graph.nodes.items()
        if n.type in ("customer", "segment", "category")
    )
    for fid in sorted(finding_texts):
        norm_text = _normalize(finding_texts[fid])
        for tid in mention_targets:
            norm_label = _normalize(graph.nodes[tid].label)
            if len(norm_label) >= 3 and norm_label in norm_text:
                graph.edges.append(GraphEdge(src=fid, dst=tid, type="MENTIONS"))

    # ── READS: table provenance from entity_map relationships (best effort) ─
    rels = entity_map.get("relationships", []) if isinstance(entity_map, dict) else []
    for rel in rels if isinstance(rels, list) else []:
        if not isinstance(rel, dict):
            continue
        src_e = rel.get("from_entity") or rel.get("from_table") or rel.get("source")
        dst_e = rel.get("to_entity") or rel.get("to_table") or rel.get("target")
        src_id, dst_id = f"table:{src_e}", f"table:{dst_e}"
        if src_id in graph.nodes and dst_id in graph.nodes and src_id != dst_id:
            graph.edges.append(GraphEdge(src=src_id, dst=dst_id, type="READS"))

    # ══════════════════════════════════════════════════════════════════════
    # v2 — post-pass deterministic aggregates
    # ══════════════════════════════════════════════════════════════════════

    # ── A1. Segment aggregates: total_ltv_eur, share_pct, n_customers ──────
    # Walk BELONGS_TO edges (customer → segment) and sum their ltv + share.
    _seg_ltv: dict[str, float] = {}
    _seg_share: dict[str, float] = {}
    _seg_ncust: dict[str, int] = {}
    for e in graph.edges:
        if e.type != "BELONGS_TO":
            continue
        seg_id = e.dst
        cust_node = graph.nodes.get(e.src)
        if cust_node is None:
            continue
        ltv = _num(cust_node.attrs.get("ltv_eur") or cust_node.attrs.get("monetary_eur"))
        share = _num(cust_node.attrs.get("share_pct"))
        _seg_ncust[seg_id] = _seg_ncust.get(seg_id, 0) + 1
        if ltv is not None:
            _seg_ltv[seg_id] = _seg_ltv.get(seg_id, 0.0) + ltv
        if share is not None:
            _seg_share[seg_id] = _seg_share.get(seg_id, 0.0) + share

    for seg_id in sorted(_seg_ncust):
        seg_node = graph.nodes.get(seg_id)
        if seg_node is None:
            continue
        seg_node.attrs["n_customers"] = _seg_ncust[seg_id]
        if seg_id in _seg_ltv:
            seg_node.attrs["total_ltv_eur"] = round(_seg_ltv[seg_id], 2)
        # share_pct MUST be consistent with total_ltv_eur (same numerator,
        # denominator = total revenue). Summing member share_pct attrs is
        # wrong when only top-N concentration rows carry them (measured live:
        # champions 32.34% partial-sum vs 45.3% real — internally inconsistent
        # with its own total_ltv_eur). Partial-sum kept only as last resort.
        if seg_id in _seg_ltv and total_rev:
            seg_node.attrs["share_pct"] = round(_seg_ltv[seg_id] / total_rev * 100.0, 2)
        elif seg_id in _seg_share:
            seg_node.attrs["share_pct"] = round(_seg_share[seg_id], 2)

    # Per-segment cross-sell gap (deterministic complement): categories the
    # segment does NOT buy, ranked by category revenue — the model cannot
    # reliably compute a 20-element complement from prose (measured: q2).
    all_cats = {nid for nid, n in graph.nodes.items() if n.type == "category"}
    if all_cats:
        cat_rev = {nid: _num(graph.nodes[nid].attrs.get("total_revenue_eur")) or 0.0
                   for nid in all_cats}
        bought_by_seg: dict[str, set[str]] = {}
        for e in graph.edges:
            if e.type == "BUYS":
                bought_by_seg.setdefault(e.src, set()).add(e.dst)
        for seg_id in sorted(_seg_ncust):
            seg_node = graph.nodes.get(seg_id)
            if seg_node is None:
                continue
            missing = all_cats - bought_by_seg.get(seg_id, set())
            top5 = sorted(missing, key=lambda c: (-cat_rev[c], c))[:5]
            seg_node.attrs["missing_categories_top5"] = [
                graph.nodes[c].label for c in top5]

    # ── A3. metric:exposicion_riesgo — at-risk OR dormant customers ─────────
    # Collect unique customer ids from AT_RISK + DORMANT edges.
    exposed_customers: set[str] = set()
    for e in graph.edges:
        if e.type in ("AT_RISK", "DORMANT") and e.src.startswith("customer:"):
            exposed_customers.add(e.src)

    if exposed_customers:
        exp_ltv_total = 0.0
        exp_ltv_per_cust: list[tuple[float, str]] = []  # (ltv, nid)
        for cid in sorted(exposed_customers):
            cnode = graph.nodes.get(cid)
            if cnode is None:
                continue
            ltv = _num(cnode.attrs.get("ltv_eur") or cnode.attrs.get("monetary_eur"))
            lbl = cnode.label
            if ltv is not None:
                exp_ltv_per_cust.append((ltv, cid))
                exp_ltv_total += ltv

        exp_share = round(exp_ltv_total / total_rev * 100.0, 2) if total_rev else None
        # Top-5 by ltv desc, deterministic tie-break by node id.
        top5_sorted = sorted(exp_ltv_per_cust, key=lambda x: (-x[0], x[1]))[:5]
        top5_labels = [graph.nodes[cid].label for _, cid in top5_sorted]

        exp_nid = _ensure_metric(graph, "exposicion_riesgo")
        exp_node = graph.nodes[exp_nid]
        exp_node.attrs["ltv_eur"] = round(exp_ltv_total, 2)
        exp_node.attrs["n_customers"] = len(exposed_customers)
        exp_node.attrs["top5"] = top5_labels
        if exp_share is not None:
            exp_node.attrs["share_pct"] = exp_share

        # EXPOSED edges only toward top-5 customers (edge-light by design).
        for ltv_val, cid in top5_sorted:
            w = ltv_val / exp_ltv_total if exp_ltv_total > 0 else 1.0 / len(top5_sorted)
            graph.edges.append(GraphEdge(src=exp_nid, dst=cid, type="EXPOSED", weight=w))

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# COMMUNITY DETECTION — hub detach → CNM → connectivity refinement → absorb
# ═══════════════════════════════════════════════════════════════════════════

# Node types that are NEVER treated as hubs — they are natural anchors.
_HUB_EXEMPT_TYPES = frozenset({"segment", "category"})

# Node types excluded from singleton absorption (provenance, fine alone).
_ABSORPTION_EXEMPT_TYPES = frozenset({"table"})


def detect_communities(
    graph: EntityGraph,
    hub_degree_frac: float = 0.25,
    seed: int = 42,
) -> dict[str, int]:
    """Communities via hub-detach + greedy modularity (CNM) + connectivity
    refinement + singleton absorption. Fully deterministic.

    1. Detach hubs: nodes touching more than hub_degree_frac * n_nodes
       neighbors, BUT only for types NOT in _HUB_EXEMPT_TYPES (segment and
       category are never detached — they are natural community anchors).
       Detached nodes get community id -1.
    2. CNM: singletons; repeatedly merge the community pair with max ΔQ > 0.
       Q = (1/2m) Σ [w_ij − k_i k_j / 2m] δ(c_i, c_j).
       Deterministic tie-break: lexicographically smallest sorted key pair.
    3. Refinement: split any community whose induced subgraph is internally
       disconnected into its connected components.
    4. Singleton absorption (max 3 passes until fixpoint): any singleton
       joins the community of its highest-weight neighbor (must have size ≥2).
       If the only neighbor is hub (-1), use next-best. table:* nodes are
       EXCLUDED from absorption (provenance, fine alone). Deterministic
       tie-break: lexicographic node id.
    """
    w_full, ids = graph.adjacency()
    n = len(ids)
    if n == 0:
        return {}

    neighbor_counts = (w_full > 0).sum(axis=1)
    # B1: segment and category nodes are NEVER hubs — they anchor communities.
    hubs = {
        ids[i] for i in range(n)
        if neighbor_counts[i] > hub_degree_frac * n
        and graph.nodes.get(ids[i]) is not None
        and graph.nodes[ids[i]].type not in _HUB_EXEMPT_TYPES
    }
    keep = [i for i in range(n) if ids[i] not in hubs]
    kept_ids = [ids[i] for i in keep]
    w = w_full[np.ix_(keep, keep)]
    nk = len(kept_ids)

    # ── CNM greedy modularity ───────────────────────────────────────────────
    members: dict[str, set[int]] = {kept_ids[i]: {i} for i in range(nk)}
    m = float(w.sum()) / 2.0
    if m > 0:
        deg = w.sum(axis=1)
        a_sum: dict[str, float] = {kept_ids[i]: float(deg[i]) for i in range(nk)}
        inter: dict[str, dict[str, float]] = {k: {} for k in members}
        for i in range(nk):
            for j in range(i + 1, nk):
                if w[i, j] > 0:
                    ki, kj = kept_ids[i], kept_ids[j]
                    inter[ki][kj] = inter[ki].get(kj, 0.0) + float(w[i, j])
                    inter[kj][ki] = inter[kj].get(ki, 0.0) + float(w[i, j])

        while True:
            best_dq, best_pair = 0.0, None
            for ka in sorted(inter):
                for kb in sorted(inter[ka]):
                    if kb <= ka:
                        continue
                    dq = inter[ka][kb] / m - (a_sum[ka] * a_sum[kb]) / (2.0 * m * m)
                    if dq > best_dq + 1e-12 or (
                        best_pair is not None
                        and abs(dq - best_dq) <= 1e-12
                        and (ka, kb) < best_pair
                    ):
                        best_dq, best_pair = dq, (ka, kb)
            if best_pair is None or best_dq <= 1e-12:
                break
            ka, kb = best_pair
            members[ka] |= members.pop(kb)
            a_sum[ka] += a_sum.pop(kb)
            for kc, wt in inter.pop(kb).items():
                if kc == ka:
                    continue
                inter[kc].pop(kb, None)
                inter[ka][kc] = inter[ka].get(kc, 0.0) + wt
                inter[kc][ka] = inter[kc].get(ka, 0.0) + wt
            inter[ka].pop(kb, None)

    # ── connectivity refinement ─────────────────────────────────────────────
    refined: list[set[int]] = []
    for key in sorted(members):
        comm = members[key]
        unseen = set(comm)
        while unseen:
            start = min(unseen)
            component, queue = {start}, deque([start])
            unseen.discard(start)
            while queue:
                cur = queue.popleft()
                for other in list(unseen):
                    if w[cur, other] > 0:
                        unseen.discard(other)
                        component.add(other)
                        queue.append(other)
            refined.append(component)

    # ── assign deterministic integer ids; hubs → -1 ─────────────────────────
    refined.sort(key=lambda comp: kept_ids[min(comp)])
    out: dict[str, int] = {hid: -1 for hid in hubs}
    for cid, comp in enumerate(refined):
        for i in comp:
            out[kept_ids[i]] = cid

    # ── B2. Singleton absorption (max 3 passes until fixpoint) ──────────────
    # Build a fast lookup: community → set of node ids.
    # Compute neighbor weights from the FULL adjacency (including hub edges).
    idx_full = {nid: i for i, nid in enumerate(ids)}
    comm_members: dict[int, set[str]] = {}
    for nid, cid in out.items():
        comm_members.setdefault(cid, set()).add(nid)

    def _comm_size(c: int) -> int:
        return len(comm_members.get(c, set()))

    for _pass in range(3):
        changed = False
        # Process singletons in deterministic order.
        singletons = sorted(
            nid for nid, cid in out.items()
            if cid >= 0
            and _comm_size(cid) == 1
            and graph.nodes.get(nid) is not None
            and graph.nodes[nid].type not in _ABSORPTION_EXEMPT_TYPES
        )
        for nid in singletons:
            if _comm_size(out[nid]) != 1:
                # Already absorbed in this pass.
                continue
            ni = idx_full.get(nid)
            if ni is None:
                continue
            # Collect neighbors with their edge weight, exclude hubs (-1) first.
            # Best = highest weight neighbor whose community size >= 2.
            # Tie-break: lexicographic node id.
            neighbor_weights: list[tuple[float, str]] = []
            for j, other_id in enumerate(ids):
                if other_id == nid:
                    continue
                wt = float(w_full[ni, j])
                if wt > 0:
                    neighbor_weights.append((wt, other_id))

            if not neighbor_weights:
                continue

            # Sort: descending weight, then ascending node id for tie-break.
            neighbor_weights.sort(key=lambda x: (-x[0], x[1]))

            best_target_comm = None
            for wt, nbr_id in neighbor_weights:
                nbr_comm = out.get(nbr_id)
                if nbr_comm is None or nbr_comm == -1:
                    continue
                if _comm_size(nbr_comm) >= 2:
                    best_target_comm = nbr_comm
                    break

            if best_target_comm is None:
                continue

            # Move nid from its current community to best_target_comm.
            old_comm = out[nid]
            comm_members[old_comm].discard(nid)
            if not comm_members[old_comm]:
                del comm_members[old_comm]
            out[nid] = best_target_comm
            comm_members.setdefault(best_target_comm, set()).add(nid)
            changed = True

        if not changed:
            break

    return out


# ═══════════════════════════════════════════════════════════════════════════
# PERSONALIZED PAGERANK
# ═══════════════════════════════════════════════════════════════════════════


def personalized_pagerank(
    graph: EntityGraph,
    seeds: dict[str, float],
    alpha: float = 0.85,
    tol: float = 1e-10,
    max_iter: int = 100,
) -> dict[str, float]:
    """Dense power iteration on the column-stochastic transition matrix from
    the symmetrized W. Dangling columns redistribute to the teleport vector.

    p_{t+1} = (1 − α) e_s + α T p_t, with e_s = normalized seeds.
    Empty (or unmatched) seeds fall back to the uniform teleport vector —
    i.e. plain PageRank.
    """
    w, ids = graph.adjacency()
    n = len(ids)
    if n == 0:
        return {}

    col_sums = w.sum(axis=0)
    dangling = col_sums <= 0
    safe = np.where(dangling, 1.0, col_sums)
    t_mat = w / safe  # column-stochastic where not dangling

    idx = {nid: i for i, nid in enumerate(ids)}
    e_s = np.zeros(n)
    for nid, wt in (seeds or {}).items():
        if nid in idx and wt > 0:
            e_s[idx[nid]] = wt
    if e_s.sum() <= 0:
        e_s = np.full(n, 1.0 / n)  # uniform teleport fallback
    else:
        e_s = e_s / e_s.sum()

    p = e_s.copy()
    for _ in range(max_iter):
        dangling_mass = float(p[dangling].sum())
        p_next = (1.0 - alpha) * e_s + alpha * (t_mat @ p + dangling_mass * e_s)
        if float(np.abs(p_next - p).sum()) < tol:
            p = p_next
            break
        p = p_next
    return {ids[i]: float(p[i]) for i in range(n)}


# ══════════════════════════════════════════════════════════════════════════
# SEED ALIAS MAP (ES terms → graph node ids)
# ══════════════════════════════════════════════════════════════════════════

# Each entry: (substring_to_match_in_normalized_question, node_id_or_prefix)
# Entries are processed in order; all that match are union-added to seeds.
# Prefix entries (ending in ":*") expand to all matching node ids in graph.
_ALIAS_MAP: list[tuple[str, str]] = [
    # Spanish → specific metrics / all-nodes of a type.
    ("churn",         "metric:churn_risk"),
    ("dormanc",       "metric:dormancy"),
    ("dormi",         "metric:dormancy"),
    ("sin comprar",   "metric:dormancy"),
    ("riesgo",        "metric:churn_risk"),
    ("riesgo",        "metric:exposicion_riesgo"),
    ("segmento",      "segment:*"),
    ("rfm",           "segment:*"),
    ("categor",       "category:*"),
    ("facturacion",   "metric:total_revenue"),
    ("revenue",       "metric:total_revenue"),
    ("ingres",        "metric:total_revenue"),
    ("hallazgo",      "finding:*"),
    ("agente",        "finding:*"),
    ("mencion",       "finding:*"),
    ("concentr",      "metric:total_revenue"),
]


def _alias_seeds(norm_q: str, graph: EntityGraph) -> dict[str, float]:
    """Resolve alias map entries whose substring appears in norm_q.
    Returns dict nid → 1.0 (uniform weight, same as lexical branch).
    """
    found: dict[str, float] = {}
    for term, target in _ALIAS_MAP:
        if term not in norm_q:
            continue
        if target.endswith(":*"):
            prefix = target[:-1]  # e.g. "segment:"
            for nid in graph.nodes:
                if nid.startswith(prefix):
                    found[nid] = 1.0
        else:
            if target in graph.nodes:
                found[target] = 1.0

    # "concentr" special case: also add top-3 customers by SHARE_OF weight.
    if "concentr" in norm_q:
        share_edges = sorted(
            (e for e in graph.edges if e.type == "SHARE_OF"),
            key=lambda e: (-e.weight, e.src),
        )
        for e in share_edges[:3]:
            found[e.src] = 1.0

    return found


def select_seeds(question: str, graph: EntityGraph) -> dict[str, float]:
    """Seed selection: alias map (ES/EN keywords) UNION lexical match on
    normalized labels (min length 6 to kill false positives like "varios").

    Returns {} only when NOTHING matches — caller falls back to community
    medoids.
    """
    norm_q = _normalize(question)

    # 1. Alias map — fast substring lookup.
    seeds = _alias_seeds(norm_q, graph)

    # 2. Lexical fallback — label must be at least 6 chars (was 3 in v1).
    for nid in sorted(graph.nodes):
        norm_label = _normalize(graph.nodes[nid].label)
        if len(norm_label) < 6:
            continue
        if norm_label in norm_q or (
            len(norm_label.split()) > 1 and norm_q and norm_q in norm_label
        ):
            seeds[nid] = 1.0

    return seeds


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-AGENT CONVERGENCE HELPER
# ═══════════════════════════════════════════════════════════════════════════


def multi_agent_mentions(graph: EntityGraph) -> list[dict]:
    """Return entities (customer / segment / category) mentioned by ≥2 distinct
    agents (via MENTIONS edges from finding nodes whose attrs["agent"] differ).

    Result: sorted list of dicts {label, node_id, agents: sorted list} for any
    entity node that has MENTIONS edges from findings attributed to ≥2 distinct
    agents. Deterministic: sorted by descending agent count, then node_id.
    """
    # Collect: entity_nid → set of agent names
    entity_agents: dict[str, set[str]] = {}
    for e in graph.edges:
        if e.type != "MENTIONS":
            continue
        finding_node = graph.nodes.get(e.src)
        entity_node = graph.nodes.get(e.dst)
        if finding_node is None or entity_node is None:
            continue
        if entity_node.type not in ("customer", "segment", "category"):
            continue
        agent = finding_node.attrs.get("agent")
        if not agent:
            continue
        entity_agents.setdefault(e.dst, set()).add(str(agent))

    result = []
    for nid, agents in sorted(entity_agents.items()):
        if len(agents) >= 2:
            node = graph.nodes[nid]
            result.append({
                "label": node.label,
                "node_id": nid,
                "agents": sorted(agents),
            })

    # Sort: descending agent count, then node_id for determinism.
    result.sort(key=lambda d: (-len(d["agents"]), d["node_id"]))
    return result


# ═══════════════════════════════════════════════════════════════════════════
# DETERMINISTIC TEXT BLOCKS — the LLM narrates these, it NEVER calculates
# ═══════════════════════════════════════════════════════════════════════════


def community_fact_sheet(
    graph: EntityGraph,
    communities: dict[str, int],
    cid: int,
) -> str:
    """Deterministic fact sheet for one community: member counts by type, top
    members by SHARE_OF weight, share sum, AT_RISK/DORMANT flags, categories
    bought, findings touching the community, and multi-agent convergence."""
    member_ids = sorted(nid for nid, c in communities.items()
                        if c == cid and nid in graph.nodes)
    member_set = set(member_ids)
    lines = [f"COMMUNITY {cid} — {len(member_ids)} members"]

    counts: dict[str, int] = {}
    for nid in member_ids:
        counts[graph.nodes[nid].type] = counts.get(graph.nodes[nid].type, 0) + 1
    lines.append("Members by type: " + ", ".join(
        f"{t}={c}" for t, c in sorted(counts.items())))

    shares = sorted(
        ((e.weight, graph.nodes[e.src].label) for e in graph.edges
         if e.type == "SHARE_OF" and e.src in member_set),
        key=lambda x: (-x[0], x[1]),
    )
    if shares:
        lines.append("Top members by revenue share:")
        for weight, label in shares[:5]:
            lines.append(f"  - {label}: {weight * 100:.1f}%")
        lines.append(f"Sum of revenue shares: {sum(s[0] for s in shares) * 100:.1f}%")

    at_risk = sorted(graph.nodes[e.src].label for e in graph.edges
                     if e.type == "AT_RISK" and e.src in member_set)
    if at_risk:
        lines.append("AT_RISK: " + ", ".join(at_risk))
    dormant = sorted(graph.nodes[e.src].label for e in graph.edges
                     if e.type == "DORMANT" and e.src in member_set)
    if dormant:
        lines.append("DORMANT: " + ", ".join(dormant))

    bought = sorted({graph.nodes[e.dst].label for e in graph.edges
                     if e.type == "BUYS" and e.src in member_set
                     and e.dst in graph.nodes})
    if bought:
        lines.append("Categories bought (segment-level): " + ", ".join(bought))

    touching = sorted({graph.nodes[e.src].label for e in graph.edges
                       if e.type == "MENTIONS" and e.dst in member_set
                       and e.src in graph.nodes})
    if touching:
        lines.append("Findings touching this community:")
        for label in touching:
            lines.append(f"  - {label}")

    # Multi-agent convergence within this community.
    conv = [
        d for d in multi_agent_mentions(graph)
        if d["node_id"] in member_set
    ]
    if conv:
        lines.append("Convergencia multi-agente:")
        for d in conv:
            lines.append(f"  - {d['label']} ← {', '.join(d['agents'])}")

    # Segment / metric attrs (aggregates).
    for nid in member_ids:
        node = graph.nodes[nid]
        if node.type in ("segment", "metric") and node.attrs:
            attr_str = ", ".join(
                f"{k}={node.attrs[k]}" for k in sorted(node.attrs)
                if k not in ("title",)
            )
            if attr_str:
                lines.append(f"  [{node.type}] {node.label}: {attr_str}")

    return "\n".join(lines)


def to_evidence_context(
    graph: EntityGraph,
    ppr: dict[str, float],
    top_k: int = 30,
    char_budget: int = 6000,
) -> str:
    """Top-k nodes by PPR score with attrs + the edges among them, truncated
    to char_budget. Deterministic ordering: (-score, node_id).

    v2: prepends a global "Convergencia multi-agente" block (always present,
    cheap to produce, small). For segment/metric nodes in top-k, their
    aggregated attrs are printed in full.
    """
    # ── Global key-aggregates block (always prepended) ────────────────────
    # v2.1: the exposure/segment aggregates existed as node attrs but answers
    # kept using partial segment numbers — surface them unmissably up top.
    agg_lines: list[str] = ["## Agregados clave (deterministas — usar ESTOS números)"]
    exp = graph.nodes.get("metric:exposicion_riesgo")
    if exp is not None and exp.attrs:
        a = exp.attrs
        agg_lines.append(
            f"  EXPOSICIÓN COMPUESTA churn∪dormancia>90d (unión DEDUPLICADA): "
            f"€{a.get('ltv_eur'):,.2f} = {a.get('share_pct')}% de la facturación "
            f"total, {a.get('n_customers')} clientes. Top-5 por LTV: "
            f"{', '.join(a.get('top5', []))}")
    tot = graph.nodes.get("metric:total_revenue")
    if tot is not None and tot.attrs.get("value") is not None:
        agg_lines.append(f"  FACTURACIÓN TOTAL: €{_num(tot.attrs['value']):,.2f}")
    for nid in sorted(graph.nodes):
        node = graph.nodes[nid]
        if node.type == "segment" and node.attrs.get("total_ltv_eur") is not None:
            line = (
                f"  SEGMENTO {node.label}: €{node.attrs['total_ltv_eur']:,.2f} "
                f"= {node.attrs.get('share_pct')}% del total "
                f"({node.attrs.get('n_customers')} clientes)")
            missing = node.attrs.get("missing_categories_top5")
            if missing:
                line += f" | categorías SIN penetrar (top revenue): {', '.join(missing)}"
            agg_lines.append(line)
    agg_block = "\n".join(agg_lines)

    # ── Global multi-agent block (always prepended) ──────────────────────
    conv = multi_agent_mentions(graph)
    conv_lines: list[str] = ["## Convergencia multi-agente (global)"]
    if conv:
        for d in conv:
            conv_lines.append(f"  {d['label']} ← {', '.join(d['agents'])}")
    else:
        conv_lines.append("  (ninguna)")
    conv_block = agg_block + "\n\n" + "\n".join(conv_lines)

    # ── PPR top-k ─────────────────────────────────────────────────────────
    ranked = sorted(
        (nid for nid in ppr if nid in graph.nodes),
        key=lambda nid: (-ppr[nid], nid),
    )[:top_k]
    selected = set(ranked)

    lines: list[str] = []
    for nid in ranked:
        node = graph.nodes[nid]
        attrs = ", ".join(f"{k}={node.attrs[k]}" for k in sorted(node.attrs))
        line = f"[{node.type}] {node.label} (ppr={ppr[nid]:.4f})"
        if attrs:
            line += f" | {attrs}"
        lines.append(line)
    for e in graph.edges:
        if e.src in selected and e.dst in selected:
            lines.append(f"{graph.nodes[e.src].label} -{e.type}({e.weight:.2f})-> "
                         f"{graph.nodes[e.dst].label}")

    # Assemble: conv_block first, then PPR lines, respecting char_budget.
    # The aggregates+convergence header is prioritized but never exempt from
    # the budget (tiny budgets in tests/tools must still be honored).
    if len(conv_block) > char_budget:
        conv_block = conv_block[: max(0, char_budget - 1)]
    out: list[str] = [conv_block]
    used = len(conv_block) + 1  # +1 for separator newline
    for line in lines:
        cost = len(line) + (1 if out else 0)
        if used + cost > char_budget:
            break
        out.append(line)
        used += cost
    return "\n".join(out)
