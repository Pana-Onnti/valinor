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
                             DORMANT, BUYS, MENTIONS, READS).
  * detect_communities     — hub detach → greedy modularity (CNM) →
                             connectivity refinement.
  * personalized_pagerank  — dense numpy power iteration, seed-biased.
  * select_seeds           — lexical seed selection from a question. No
                             embeddings.
  * community_fact_sheet / to_evidence_context — deterministic text blocks
                             for downstream narration.

Honesty note: greedy modularity (CNM) + connectivity refinement is
Leiden-equivalent at n<500; leidenalg/igraph rejected as dependency theater.

All numeric coercion goes through `_num`, which understands DB-string
serialization ("364517.30") and Postgres intervals ("147 days, 0:00:00") —
lesson from a real bug where drivers serialized NUMERIC as strings and a
prior instrument silently dropped them.

Domain purity: stdlib + numpy only. No LLM, no DB, no infra imports.

Refs: VAL-192 (N3)
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
    for qname in sorted(n for n in results if "cross_sell" in n.lower()):
        for row in _rows_of(results[qname]):
            cat = row.get("category")
            seg = row.get("segment") or row.get("rfm_segment")
            if not cat:
                continue
            cat_id = f"category:{cat}"
            if cat_id not in graph.nodes:
                graph.nodes[cat_id] = GraphNode(id=cat_id, type="category", label=str(cat))
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

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# COMMUNITY DETECTION — hub detach → CNM → connectivity refinement
# ═══════════════════════════════════════════════════════════════════════════


def detect_communities(
    graph: EntityGraph,
    hub_degree_frac: float = 0.25,
    seed: int = 42,
) -> dict[str, int]:
    """Communities via hub-detach + greedy modularity (CNM) + connectivity
    refinement. Fully deterministic — `seed` kept for API stability only.

    1. Detach hubs: nodes touching more than hub_degree_frac * n_nodes
       neighbors (e.g. metric:total_revenue touches every customer) are
       excluded from clustering and re-attached at the end with community
       id -1 (shared facts, not cluster members).
    2. CNM: singletons; repeatedly merge the community pair with max ΔQ > 0.
       Q = (1/2m) Σ [w_ij − k_i k_j / 2m] δ(c_i, c_j).
       Deterministic tie-break: lexicographically smallest sorted key pair.
    3. Refinement: split any community whose induced subgraph is internally
       disconnected into its connected components.
    """
    w_full, ids = graph.adjacency()
    n = len(ids)
    if n == 0:
        return {}

    neighbor_counts = (w_full > 0).sum(axis=1)
    hubs = {ids[i] for i in range(n) if neighbor_counts[i] > hub_degree_frac * n}
    keep = [i for i in range(n) if ids[i] not in hubs]
    kept_ids = [ids[i] for i in keep]
    w = w_full[np.ix_(keep, keep)]
    nk = len(kept_ids)

    # ── CNM greedy modularity ───────────────────────────────────────────────
    # Communities keyed by their lexicographically smallest member id.
    members: dict[str, set[int]] = {kept_ids[i]: {i} for i in range(nk)}
    m = float(w.sum()) / 2.0
    if m > 0:
        deg = w.sum(axis=1)
        a_sum: dict[str, float] = {kept_ids[i]: float(deg[i]) for i in range(nk)}
        # Symmetric inter-community weights (only pairs with w > 0 can have ΔQ > 0).
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
            ka, kb = best_pair  # ka < kb: kb merges into ka
            members[ka] |= members.pop(kb)
            a_sum[ka] += a_sum.pop(kb)
            for kc, wt in inter.pop(kb).items():
                if kc == ka:
                    continue
                inter[kc].pop(kb, None)
                inter[ka][kc] = inter[ka].get(kc, 0.0) + wt
                inter[kc][ka] = inter[kc].get(ka, 0.0) + wt
            inter[ka].pop(kb, None)

    # ── connectivity refinement: split internally disconnected communities ──
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


def select_seeds(question: str, graph: EntityGraph) -> dict[str, float]:
    """Lexical seed selection: a node seeds iff its normalized label appears
    as a substring in the normalized question (or, for multiword labels, the
    whole question appears inside the label). No embeddings, no fuzziness.
    Returns {} when nothing matches — caller falls back to community medoids.
    """
    norm_q = _normalize(question)
    seeds: dict[str, float] = {}
    for nid in sorted(graph.nodes):
        norm_label = _normalize(graph.nodes[nid].label)
        if len(norm_label) < 3:
            continue
        if norm_label in norm_q or (
            len(norm_label.split()) > 1 and norm_q and norm_q in norm_label
        ):
            seeds[nid] = 1.0
    return seeds


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
    bought, findings touching the community."""
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

    return "\n".join(lines)


def to_evidence_context(
    graph: EntityGraph,
    ppr: dict[str, float],
    top_k: int = 30,
    char_budget: int = 6000,
) -> str:
    """Top-k nodes by PPR score with attrs + the edges among them, truncated
    to char_budget. Deterministic ordering: (-score, node_id)."""
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

    out: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + (1 if out else 0)
        if used + cost > char_budget:
            break
        out.append(line)
        used += cost
    return "\n".join(out)
