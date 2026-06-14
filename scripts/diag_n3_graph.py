"""
Structural diagnostic of the entity graph N3 (VAL-192) over the val-163 capture.
"""
import json
import sys
import collections

sys.path.insert(0, 'core')

from valinor.graphrag import build_entity_graph, detect_communities, select_seeds, _normalize

# ── Load state ────────────────────────────────────────────────────────────────
with open('docs/experiments/val-163/state.json') as f:
    state = json.load(f)

g = build_entity_graph(
    state['entity_map'],
    state['query_results'],
    state['baseline'],
    state['findings'],
)

comm = detect_communities(g)

# ── 1. Community size distribution ────────────────────────────────────────────
size_count: dict[str, int] = collections.Counter(comm.values())
# sizes: -1 = hubs, 0+ = communities
comm_to_members: dict[int, list[str]] = collections.defaultdict(list)
for nid, cid in comm.items():
    comm_to_members[cid].append(nid)

non_hub_comm_sizes = [len(v) for k, v in comm_to_members.items() if k != -1]
size_distribution = {"1": 0, "2": 0, "3+": 0}
for s in non_hub_comm_sizes:
    if s == 1:
        size_distribution["1"] += 1
    elif s == 2:
        size_distribution["2"] += 1
    else:
        size_distribution["3+"] += 1

print(f"Total nodes: {len(g.nodes)}")
print(f"Total edges: {len(g.edges)}")
print(f"Total communities (excl. hub -1): {len(non_hub_comm_sizes)}")
print(f"Community size distribution: {size_distribution}")

# ── Singleton composition ──────────────────────────────────────────────────────
singleton_ids = [members[0] for cid, members in comm_to_members.items()
                 if cid != -1 and len(members) == 1]
singleton_type_count: dict[str, int] = collections.Counter(
    g.nodes[nid].type for nid in singleton_ids if nid in g.nodes
)
print(f"\nSingleton nodes ({len(singleton_ids)} total) type breakdown: {dict(singleton_type_count)}")

# ── 2. Hub edges for singleton customers ──────────────────────────────────────
hubs_set = set(comm_to_members.get(-1, []))
print(f"\nHubs (community -1): {sorted(hubs_set)}")

singleton_customers = [nid for nid in singleton_ids
                       if g.nodes.get(nid, None) and g.nodes[nid].type == 'customer']
print(f"\nSingleton customers: {len(singleton_customers)}")

customers_only_hub_edges = 0
customer_edge_detail = []
for nid in singleton_customers:
    neighbors = g.neighbors(nid)
    hub_neighbors = [nb for nb in neighbors if nb in hubs_set]
    non_hub_neighbors = [nb for nb in neighbors if nb not in hubs_set]
    if len(non_hub_neighbors) == 0 and len(hub_neighbors) > 0:
        customers_only_hub_edges += 1
    customer_edge_detail.append({
        "id": nid,
        "label": g.nodes[nid].label,
        "hub_neighbors": hub_neighbors,
        "non_hub_neighbors": non_hub_neighbors,
        "edge_types": sorted(set(
            e.type for e in g.edges
            if e.src == nid or e.dst == nid
        )),
    })

print(f"Singleton customers with ONLY hub edges: {customers_only_hub_edges}")
for d in customer_edge_detail[:5]:
    print(f"  {d['label']}: hub_nbrs={d['hub_neighbors']}, non_hub={d['non_hub_neighbors']}, types={d['edge_types']}")

# ── 3. Hubs and their degree ──────────────────────────────────────────────────
hubs_with_degree = []
for hid in sorted(hubs_set):
    deg = sum(1 for e in g.edges if e.src == hid or e.dst == hid)
    hubs_with_degree.append({"id": hid, "degree": deg})
    print(f"  Hub: {hid}  degree={deg}")

# ── 4. select_seeds for 4 TRAIN questions ────────────────────────────────────
questions = {
    "q1": "¿Qué porcentaje de la facturación total está en clientes que además presentan riesgo de churn o dormancia (>90 días sin comprar)? ¿Cuáles son?",
    "q2": "¿Qué segmento RFM concentra más facturación y qué categorías de producto NO ha penetrado todavía? Cuantificá la oportunidad.",
    "q4": "¿La concentración de facturación la explica un solo segmento RFM o cruza varios? ¿Qué segmento aporta más share y cuánto?",
    "q5": "¿Qué clientes aparecen mencionados en hallazgos de DOS o más agentes distintos, y qué dice cada uno?",
}

seeds_per_question = {}
all_labels = sorted(set(_normalize(g.nodes[nid].label) for nid in g.nodes))

print("\n=== select_seeds results ===")
for qk, qtext in questions.items():
    seeds = select_seeds(qtext, g)
    seeds_per_question[qk] = sorted(seeds.keys())
    print(f"\n{qk}: {seeds_per_question[qk]}")
    if not seeds:
        norm_q = _normalize(qtext)
        # Look for partial matches to explain failure
        candidates = []
        for nid in g.nodes:
            norm_label = _normalize(g.nodes[nid].label)
            if len(norm_label) >= 3:
                words = norm_label.split()
                for w in words:
                    if len(w) >= 4 and w in norm_q:
                        candidates.append((nid, g.nodes[nid].type, norm_label, w))
                        break
        print(f"  Partial word matches: {candidates[:10]}")

# ── Seed failure reason analysis ──────────────────────────────────────────────
print("\n=== Normalized question tokens vs node labels ===")
for qk, qtext in questions.items():
    norm_q = _normalize(qtext)
    print(f"\n{qk} normalized: '{norm_q[:120]}'")

print("\n=== All node labels (normalized) ===")
type_labels = collections.defaultdict(list)
for nid, node in g.nodes.items():
    type_labels[node.type].append(_normalize(node.label))
for t, labels in sorted(type_labels.items()):
    print(f"  type={t}: {sorted(labels)[:10]}")

# ── 5. MENTIONS edges ─────────────────────────────────────────────────────────
mentions_edges = [e for e in g.edges if e.type == "MENTIONS"]
print(f"\nTotal MENTIONS edges: {len(mentions_edges)}")

# Finding → target
mentions_by_finding = collections.defaultdict(list)
for e in mentions_edges:
    mentions_by_finding[e.src].append(e.dst)

print(f"Findings with MENTIONS: {len(mentions_by_finding)}")
for fid, targets in sorted(mentions_by_finding.items())[:5]:
    agent = g.nodes[fid].attrs.get('agent', '?')
    print(f"  {fid} (agent={agent}): {targets}")

# q5 convergent customers
convergent_customers = ["EL CORTE INGLES S.A.", "GUAW", "ISKAY PET S.LU."]
print("\n=== q5 convergent customers ===")
q5_conv_detail = []
for cname in convergent_customers:
    norm_name = _normalize(cname)
    # Search by normalized label
    matching_nodes = [nid for nid, node in g.nodes.items()
                      if _normalize(node.label) == norm_name or
                      node.label.upper() == cname.upper()]
    node_exists = len(matching_nodes) > 0
    agents_mentioning = []
    if node_exists:
        for nid in matching_nodes:
            # Find findings that mention this node
            mentioning_findings = [e.src for e in mentions_edges if e.dst == nid]
            for fid in mentioning_findings:
                agent = g.nodes[fid].attrs.get('agent', '?')
                if agent not in agents_mentioning:
                    agents_mentioning.append(agent)
    print(f"  '{cname}': node_exists={node_exists}, matching={matching_nodes}, agents={agents_mentioning}")
    q5_conv_detail.append({
        "name": cname,
        "node_exists": node_exists,
        "matching_nodes": matching_nodes,
        "agents_mentioning": agents_mentioning,
    })

# ── Also check by partial substring for q5 customers ─────────────────────────
print("\n=== Substring search for q5 customers in node labels ===")
for cname in convergent_customers:
    norm = _normalize(cname)
    parts = norm.split()
    hits = []
    for nid, node in g.nodes.items():
        node_norm = _normalize(node.label)
        for part in parts:
            if len(part) >= 4 and part in node_norm:
                hits.append((nid, node.label, node.type))
                break
    print(f"  '{cname}' parts={parts}: hits={hits}")

# ── Summary report ─────────────────────────────────────────────────────────────
print("\n\n=== FINAL JSON REPORT ===")
result = {
    "community_sizes": size_distribution,
    "singleton_composition": dict(singleton_type_count),
    "customers_only_hub_edges": customers_only_hub_edges,
    "hubs": hubs_with_degree,
    "seeds_per_question": seeds_per_question,
    "seeds_failure_reason": (
        "select_seeds requires exact normalized substring match: "
        "norm_label IN norm_question. "
        "Metric/segment node labels use machine codes (e.g. 'metric:churn_risk', 'segment:champions') "
        "that do NOT appear verbatim in the Spanish question text after normalization. "
        "E.g. q1 asks 'churn' → matches 'churn' but node label is 'churn_risk' → normalized 'churn risk' → "
        "not a substring of the question. "
        "Customer labels (full names like 'EL CORTE INGLES S.A.') are too long/specific to appear in generic questions. "
        "q2 'segmento rfm' would need label='rfm' but segment node labels are 'champions','at_risk',etc."
    ),
    "mentions": {
        "total": len(mentions_edges),
        "q5_convergent_in_graph": q5_conv_detail,
    },
    "top_insights": [],
}
print(json.dumps(result, indent=2, ensure_ascii=False))
