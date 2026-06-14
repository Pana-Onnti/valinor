#!/usr/bin/env python3
"""
Reference-answer builder for the N3 global-questions eval (VAL-192 N3).

Computes, via PURE deterministic joins over a captured pipeline state
(state.json), the reference values that resolve the {REF:...} placeholders in
evals/golden/global_questions.yaml. No LLM, no DB, no graph — the references
are the ground truth the graph arms get judged against, so they must come
from an independent, simpler computation.

Computability rule (the gate this script enforces): a question only enters
the eval if its reference is computable from the state by joins. If any
non-replaced question can't be computed, this script FAILS LOUDLY listing
them — reformulate or replace before freezing the set.

Usage:
    python scripts/build_global_references.py \
        --state evals/fixtures/state_demo.json \
        --out evals/fixtures/references_demo.json
    # Real captures: --state docs/experiments/val-163/state.json \
    #                --out docs/experiments/val-192-n3/references.json  (gitignored)

Refs: VAL-192
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import yaml


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        m = re.match(r"(\d+)\s*days?\b", s, re.IGNORECASE)
        if m:
            return float(m.group(1))
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s):
            return float(s)
    return None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _rows(state: dict, *name_substrings: str) -> list[dict]:
    qr = state["query_results"]
    results = qr.get("results", qr)
    for qname, qdata in results.items():
        if all(sub in qname for sub in name_substrings):
            rows = qdata.get("rows", qdata) if isinstance(qdata, dict) else qdata
            if isinstance(rows, list):
                return rows
    return []


def _field(row: dict, *candidates: str):
    for c in candidates:
        if c in row:
            return row[c]
    return None


# ── customer master: the entity resolution the per-query pipeline never does ─


def build_customers(state: dict) -> dict[str, dict]:
    """{customer_id: {name, ltv, segment, risk, days_since}} — union of queries."""
    cust: dict[str, dict] = {}

    def slot(cid):
        return cust.setdefault(str(cid), {"name": None, "ltv": None, "segment": None,
                                          "risk": None, "days_since": None})

    for row in _rows(state, "rfm"):
        cid = _field(row, "customer_id", "bpartner_id")
        if cid is None:
            continue
        c = slot(cid)
        c["name"] = c["name"] or _field(row, "customer_name", "name")
        c["segment"] = _field(row, "segment", "rfm_segment", "segmento")
        c["ltv"] = c["ltv"] if c["ltv"] is not None else _num(_field(row, "monetary_eur", "ltv_eur"))
        # v2: RFM carries recency_days — "dormancia >90 días" lives here too
        # (found via the graph arm disagreeing with the reference: KONG DE,
        # champion with recency>90, was exposed in-graph but missed here).
        days = _num(_field(row, "recency_days"))
        if days is not None:
            c["days_since"] = max(days, c["days_since"] or 0)

    for row in _rows(state, "concentration", "customers"):
        cid = _field(row, "customer_id", "bpartner_id")
        if cid is None:
            continue
        c = slot(cid)
        c["name"] = c["name"] or _field(row, "customer_name", "name")
        ltv = _num(_field(row, "ltv_eur", "total_revenue", "revenue_eur"))
        if ltv is not None:
            c["ltv"] = ltv

    for row in _rows(state, "churn"):
        cid = _field(row, "customer_id", "bpartner_id")
        if cid is None:
            continue
        c = slot(cid)
        c["risk"] = _num(_field(row, "deal_risk_score", "risk_score"))
        days = _num(_field(row, "recency_days", "days_since_purchase", "days_since_last_purchase"))
        if days is not None:
            c["days_since"] = max(days, c["days_since"] or 0)
        if c["ltv"] is None:
            c["ltv"] = _num(_field(row, "ltv_eur"))

    for row in _rows(state, "dormant"):
        cid = _field(row, "customer_id", "bpartner_id")
        if cid is None:
            continue
        c = slot(cid)
        days = _num(_field(row, "days_since_purchase", "days_dormant", "days_since_last_purchase"))
        if days is not None:
            c["days_since"] = max(days, c["days_since"] or 0)

    return cust


def total_revenue(state: dict) -> float | None:
    t = _num(state.get("baseline", {}).get("total_revenue"))
    if t:
        return t
    rows = _rows(state, "total_revenue_summary")
    return _num(_field(rows[0], "total_revenue")) if rows else None


def findings_mentions(state: dict, labels: dict[str, str]) -> dict[str, set]:
    """{label_key: set(agents that mention it)} via normalized containment."""
    out: dict[str, set] = {k: set() for k in labels}
    for agent, data in (state.get("findings") or {}).items():
        if agent.startswith("_") or not isinstance(data, dict):
            continue
        blob = _norm(json.dumps(data, ensure_ascii=False))
        for key, label in labels.items():
            if label and _norm(label) in blob:
                out[key].add(agent)
    return out


# ── per-question reference computations ──────────────────────────────────────


def compute_references(state: dict) -> tuple[dict, list[str]]:
    refs: dict = {}
    not_computable: list[str] = []
    cust = build_customers(state)
    total = total_revenue(state)

    with_ltv = {cid: c for cid, c in cust.items() if c["ltv"]}

    # q1 — exposed = risk OR days_since>90, deduplicated
    exposed = {cid: c for cid, c in with_ltv.items()
               if (c["risk"] or 0) > 0 or (c["days_since"] or 0) > 90}
    if exposed and total:
        eur = sum(c["ltv"] for c in exposed.values())
        risky = sum(c["ltv"] for c in with_ltv.values() if (c["risk"] or 0) > 0)
        dormant = sum(c["ltv"] for c in with_ltv.values() if (c["days_since"] or 0) > 90)
        top5 = sorted(exposed.values(), key=lambda c: -c["ltv"])[:5]
        refs["q1"] = {
            "exposed_eur": round(eur, 2),
            "exposed_share_pct": round(eur / total * 100, 2),
            "exposed_customers": sorted(c["name"] or cid for cid, c in exposed.items()),
            # v2 (train iteration): a 250-word answer cannot name 20 customers —
            # the gradable fact is the top-5 by LTV. Full list kept for audit.
            "exposed_customers_top5": sorted(filter(None, (c["name"] for c in top5))),
            "naive_double_count_eur": round(risky + dormant, 2),  # the trap
        }
    else:
        not_computable.append("q1")

    # q2 — top segment by ltv + categories it does NOT buy
    seg_ltv: dict[str, float] = {}
    for c in with_ltv.values():
        if c["segment"]:
            seg_ltv[c["segment"]] = seg_ltv.get(c["segment"], 0) + c["ltv"]
    xsell = _rows(state, "cross_sell")
    if seg_ltv and xsell:
        top_seg = max(seg_ltv, key=seg_ltv.get)
        all_cats = {_field(r, "category", "categoria") for r in xsell} - {None}
        bought = {_field(r, "category", "categoria") for r in xsell
                  if _field(r, "segment", "segmento") == top_seg}
        missing = all_cats - bought
        # v2: 20 categorías no caben en 250 palabras — el fact evaluable es el
        # top-5 de las faltantes por revenue total de categoría (los gaps que valen).
        cat_rev: dict[str, float] = {}
        for r in xsell:
            cat = _field(r, "category", "categoria")
            rev = _num(_field(r, "category_revenue_eur", "revenue_eur", "revenue"))
            if cat and rev:
                cat_rev[cat] = cat_rev.get(cat, 0) + rev
        top5_missing = sorted(missing, key=lambda c: (-cat_rev.get(c, 0.0), c))[:5]
        refs["q2"] = {
            "top_segment": [top_seg],
            "top_segment_eur": round(seg_ltv[top_seg], 2),
            "missing_categories": sorted(missing),
            "missing_categories_top5": sorted(top5_missing),
        }
    else:
        not_computable.append("q2")

    # q3 — top-3 by risk: blast radius
    risky = sorted((c for c in with_ltv.values() if c["risk"]),
                   key=lambda c: -c["risk"])[:3]
    if len(risky) == 3 and total:
        eur = sum(c["ltv"] for c in risky)
        refs["q3"] = {
            "blast_eur": round(eur, 2),
            "blast_share_pct": round(eur / total * 100, 2),
            "segments_hit": sorted({c["segment"] for c in risky if c["segment"]}),
        }
    else:
        not_computable.append("q3")

    # q4 — share attribution by segment
    if seg_ltv and total:
        top_seg = max(seg_ltv, key=seg_ltv.get)
        top1 = max(with_ltv.values(), key=lambda c: c["ltv"])
        refs["q4"] = {
            "top_segment": [top_seg],
            "top_segment_share_pct": round(seg_ltv[top_seg] / total * 100, 2),
            "top1_customer_segment": [top1["segment"]] if top1["segment"] else [],
        }
    else:
        not_computable.append("q4")

    # q5 — customers mentioned by ≥2 agents
    labels = {cid: c["name"] for cid, c in cust.items() if c["name"]}
    mentions = findings_mentions(state, labels)
    convergent = {cid: agents for cid, agents in mentions.items() if len(agents) >= 2}
    if any(len(a) >= 1 for a in mentions.values()):
        refs["q5"] = {
            "convergent_customers": sorted(labels[cid] for cid in convergent),
            "agents_involved": sorted(set().union(*convergent.values()) if convergent else []),
        }
    else:
        not_computable.append("q5")

    # q7 — minimal Pareto-80 subset + fragility
    if with_ltv and total:
        ranked = sorted(with_ltv.values(), key=lambda c: -c["ltv"])
        acc, n = 0.0, 0
        for c in ranked:
            acc += c["ltv"]
            n += 1
            if acc >= 0.80 * total:
                break
        members = ranked[:n]
        fragile = [c for c in members
                   if (c["risk"] or 0) > 0 or (c["days_since"] or 0) > 90]
        fragile_names = sorted(filter(None, (c["name"] for c in fragile)))
        top5 = sorted(fragile, key=lambda c: -c["ltv"])[:5]
        refs["q7"] = {
            "pareto_n": n,
            "fragile_members": fragile_names,
            # v3 re-spec (q7 ya es train): 10 labels eran inevaluables — top-5.
            "fragile_members_top5": sorted(filter(None, (c["name"] for c in top5))),
        }
    else:
        not_computable.append("q7")

    # ── v3 test split (re-freeze): q9 / q10 / q13 ───────────────────────────

    # q9 — segmento con mayor LTV en riesgo (join churn × rfm + group-by)
    risk_by_seg: dict[str, list] = {}
    for c in with_ltv.values():
        if (c["risk"] or 0) > 0 and c["segment"]:
            risk_by_seg.setdefault(c["segment"], []).append(c)
    if risk_by_seg:
        top_seg = max(risk_by_seg, key=lambda s: sum(c["ltv"] for c in risk_by_seg[s]))
        refs["q9"] = {
            "risk_top_segment": [top_seg],
            "risk_top_segment_ltv_eur": round(sum(c["ltv"] for c in risk_by_seg[top_seg]), 2),
            "risk_top_segment_n": len(risk_by_seg[top_seg]),
        }
    else:
        not_computable.append("q9")

    # q10 — top-10 por LTV ∩ riesgo de churn (doble exposición)
    if with_ltv and total:
        top10 = sorted(with_ltv.values(), key=lambda c: -c["ltv"])[:10]
        double = [c for c in top10 if (c["risk"] or 0) > 0]
        all_risky = [c for c in with_ltv.values() if (c["risk"] or 0) > 0]
        refs["q10"] = {
            "double_exposed": sorted(filter(None, (c["name"] for c in double))),
            "double_exposed_share_pct": round(sum(c["ltv"] for c in double) / total * 100, 2),
            "double_exposed_n": len(double),
            # Trampa: share de TODOS los riesgosos (no la intersección con top-10).
            "all_risky_share_pct": round(sum(c["ltv"] for c in all_risky) / total * 100, 2),
        }
    else:
        not_computable.append("q10")

    # q13 — cobertura del scoring: clientes con LTV pero sin deal_risk_score
    if with_ltv:
        unscored = [c for c in with_ltv.values() if c["risk"] is None]
        top3 = sorted(unscored, key=lambda c: -c["ltv"])[:3]
        refs["q13"] = {
            "unscored_n": len(unscored),
            "unscored_ltv_eur": round(sum(c["ltv"] for c in unscored), 2),
            "unscored_top3": sorted(filter(None, (c["name"] for c in top3))),
        }
    else:
        not_computable.append("q13")

    # ── v4 test split (re-freeze #2): q14 / q15 / q16 ───────────────────────

    # q14 — segmento con más LTV dormido (>90 días sin comprar)
    dormant_by_seg: dict[str, list] = {}
    for c in with_ltv.values():
        if (c["days_since"] or 0) > 90 and c["segment"]:
            dormant_by_seg.setdefault(c["segment"], []).append(c)
    if dormant_by_seg:
        top_seg = max(dormant_by_seg,
                      key=lambda s: sum(c["ltv"] for c in dormant_by_seg[s]))
        refs["q14"] = {
            "dormant_top_segment": [top_seg],
            "dormant_top_segment_ltv_eur": round(
                sum(c["ltv"] for c in dormant_by_seg[top_seg]), 2),
            "dormant_top_segment_n": len(dormant_by_seg[top_seg]),
        }
    else:
        not_computable.append("q14")

    # q15 — top-10 por LTV ∩ sin score (membresía × ausencia)
    if with_ltv:
        top10 = sorted(with_ltv.values(), key=lambda c: -c["ltv"])[:10]
        t10_unscored = [c for c in top10 if c["risk"] is None]
        refs["q15"] = {
            "top10_unscored_n": len(t10_unscored),
            "top10_unscored": sorted(filter(None, (c["name"] for c in t10_unscored))),
            "top10_unscored_ltv_eur": round(sum(c["ltv"] for c in t10_unscored), 2),
        }
    else:
        not_computable.append("q15")

    # q16 — concentración del riesgo: top-3 por score dentro del LTV en riesgo
    risky_all = [c for c in with_ltv.values() if (c["risk"] or 0) > 0]
    if len(risky_all) >= 3:
        top3_score = sorted(risky_all, key=lambda c: (-c["risk"], -c["ltv"]))[:3]
        risky_total = sum(c["ltv"] for c in risky_all)
        refs["q16"] = {
            "top3_by_score": sorted(filter(None, (c["name"] for c in top3_score))),
            "top3_score_ltv_share_pct": round(
                sum(c["ltv"] for c in top3_score) / risky_total * 100, 2)
            if risky_total else None,
            "risky_total_ltv_eur": round(risky_total, 2),
        }
    else:
        not_computable.append("q16")

    # ── v5 test split (re-freeze #3): q17 / q18 / q20 ───────────────────────

    # q17 — peso de los convergentes: clientes mencionados por ≥2 agentes × LTV
    conv_cust = [cust[cid] for cid in convergent if cust[cid]["ltv"]]
    if convergent and total and conv_cust:
        conv_ltv = sum(c["ltv"] for c in conv_cust)
        refs["q17"] = {
            "convergent_customers": sorted(filter(None, (c["name"] for c in conv_cust))),
            "convergent_ltv_eur": round(conv_ltv, 2),
            "convergent_share_pct": round(conv_ltv / total * 100, 2),
        }
    else:
        not_computable.append("q17")

    # q18 — mayor LTV promedio por segmento (avg = suma/count del group-by)
    seg_groups: dict[str, list] = {}
    for c in with_ltv.values():
        if c["segment"]:
            seg_groups.setdefault(c["segment"], []).append(c)
    if seg_groups:
        top_seg = max(seg_groups,
                      key=lambda s: sum(c["ltv"] for c in seg_groups[s]) / len(seg_groups[s]))
        grp = seg_groups[top_seg]
        refs["q18"] = {
            "avg_top_segment": [top_seg],
            "avg_top_segment_avg_ltv_eur": round(sum(c["ltv"] for c in grp) / len(grp), 2),
            "avg_top_segment_n": len(grp),
        }
    else:
        not_computable.append("q18")

    # ── v6 test split (re-freeze #4, certificación): q22 / q24 / q25 ────────

    # q22 — segmento con más LTV sin score (group-by × complemento del scoring)
    unscored_by_seg: dict[str, list] = {}
    for c in with_ltv.values():
        if c["risk"] is None and c["segment"]:
            unscored_by_seg.setdefault(c["segment"], []).append(c)
    if unscored_by_seg:
        top_seg = max(unscored_by_seg,
                      key=lambda s: sum(c["ltv"] for c in unscored_by_seg[s]))
        refs["q22"] = {
            "unscored_top_segment": [top_seg],
            "unscored_top_segment_ltv_eur": round(
                sum(c["ltv"] for c in unscored_by_seg[top_seg]), 2),
            "unscored_top_segment_n": len(unscored_by_seg[top_seg]),
        }
    else:
        not_computable.append("q22")

    # q24 — intersección top-5 por LTV ∩ top-5 por deal_risk_score
    if with_ltv:
        top5_ltv = {id(c) for c in sorted(with_ltv.values(), key=lambda c: -c["ltv"])[:5]}
        scored = [c for c in with_ltv.values() if c["risk"] is not None]
        top5_score = {id(c) for c in sorted(scored, key=lambda c: (-c["risk"], -c["ltv"]))[:5]}
        both = [c for c in with_ltv.values() if id(c) in top5_ltv and id(c) in top5_score]
        refs["q24"] = {
            "double_top": sorted(filter(None, (c["name"] for c in both))),
            "double_top_n": len(both),
        }
    else:
        not_computable.append("q24")

    # q25 — cliente más expuesto (máximo de la unión churn∪dormancia) + total
    if exposed:
        top_exp = max(exposed.values(), key=lambda c: c["ltv"])
        refs["q25"] = {
            "top_exposed_customer": [top_exp["name"]] if top_exp["name"] else [],
            "top_exposed_ltv_eur": round(top_exp["ltv"], 2),
            "total_exposed_ltv_eur": round(sum(c["ltv"] for c in exposed.values()), 2),
        }
    else:
        not_computable.append("q25")

    # q20 — categoría líder por revenue + segmentos compradores
    if xsell:
        cat_rev2: dict[str, float] = {}
        cat_buyers: dict[str, set] = {}
        for r in xsell:
            cat = _field(r, "category", "categoria")
            seg = _field(r, "segment", "segmento")
            rev = _num(_field(r, "category_revenue_eur", "revenue_eur", "revenue"))
            if cat is None:
                continue
            if rev:
                cat_rev2[cat] = cat_rev2.get(cat, 0) + rev
            if seg:
                cat_buyers.setdefault(cat, set()).add(seg)
        if cat_rev2:
            top_cat = max(cat_rev2, key=cat_rev2.get)
            refs["q20"] = {
                "top_category": [top_cat],
                "top_category_revenue_eur": round(cat_rev2[top_cat], 2),
                "buying_segments": sorted(cat_buyers.get(top_cat, set())),
            }
        else:
            not_computable.append("q20")
    else:
        not_computable.append("q20")

    # q8 — segments with share >10% and zero finding mentions
    if seg_ltv and total:
        seg_mentions = findings_mentions(state, {s: s for s in seg_ltv})
        # a segment is covered if the segment name OR any member customer is mentioned
        member_mentions = mentions  # from q5
        covered = {s for s, a in seg_mentions.items() if a}
        for cid, agents in member_mentions.items():
            if agents and cust[cid]["segment"]:
                covered.add(cust[cid]["segment"])
        blind = {s: ltv for s, ltv in seg_ltv.items()
                 if s not in covered and ltv / total * 100 > 10}
        refs["q8"] = {
            "blind_segments": sorted(blind),
            "blind_share_pct": round(sum(blind.values()) / total * 100, 2),
        }
    else:
        not_computable.append("q8")

    return refs, not_computable


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 N3 reference builder")
    ap.add_argument("--state", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--questions", default="evals/golden/global_questions.yaml")
    ap.add_argument("--allow-partial", action="store_true",
                    help="don't fail on uncomputable questions (exploration only)")
    args = ap.parse_args(argv)

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    questions = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    active = [q["id"] for q in questions if q.get("status") != "replaced"]

    refs, not_computable = compute_references(state)
    missing = [q for q in active if q.split("-")[0] not in refs]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(refs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(refs)} questions resolved)", file=sys.stderr)

    if missing and not args.allow_partial:
        print(f"\nCOMPUTABILITY RULE VIOLATED — not computable from this state: "
              f"{missing + not_computable}\nReformulate or mark status: replaced "
              f"before freezing the set.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
