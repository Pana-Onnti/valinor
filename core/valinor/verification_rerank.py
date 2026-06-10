"""
Two-stage grounding — stage 1.5 (generic registry enrichment) + stage 2
(LLM rerank of dubious claims) for the VerificationEngine (VAL-192 N2).

The universal pattern: retrieve barato → rerank caro. Stage 1 (VerificationEngine)
is cheap and structural and runs over ALL claims; this module adds:

  * enrich_registry — deterministic: the engine's `_build_registry_from_queries`
    only knows 5 legacy query names, so the VAL-141 queries (concentration,
    RFM, churn, HHI…) never reach the Number Registry that narrators are told
    to cite from. This walks every query result generically and registers
    single-row scalars, rank-1 values and column sums. Pure, no LLM.

  * rerank_unverifiable — the expensive pass, ONLY over claims stage 1 left
    UNVERIFIABLE: one batched LLM call proposes, per claim, an arithmetic
    derivation over named query columns ("sum of ltv_eur over the 10 rows of
    concentration_top_customers"); the proposal is then CONFIRMED
    DETERMINISTICALLY — the code recomputes the value and only a numeric match
    upgrades the claim to VERIFIED. The LLM proposes, the code disposes: a
    hallucinated proposal cannot corrupt the report. Proposed contradictions
    are recorded as disputed issues, never auto-retracted.

NOT wired into run.py: eval-first, wire-later (same pattern as VAL-161/163).
Measured offline via scripts/run_capture_ab_live.py --enriched (treatment2)
and scripts/eval.py ab.

Refs: VAL-192 (N2), VAL-163, VAL-161
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from valinor.verification import (
    NumberRegistryEntry,
    VerificationReport,
)


# ═══════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _to_float(raw: Any) -> Optional[float]:
    """Numeric leaf coercion incl. DB string serialization ('364517.30')."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip()
        m = re.match(r"(\d+)\s*days?\b", s, re.IGNORECASE)   # '147 days, 0:00:00'
        if m:
            return float(m.group(1))
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s):
            return float(s)
    return None


def _values_match(claimed: float, actual: float, unit: str = "EUR") -> bool:
    """Tolerance mirror of VerificationEngine._values_match (kept local on
    purpose — same convention as quality/narrator_metrics). Magnitudes only:
    extracted claims are unsigned ('nota de crédito de €4.389,05' vs the
    stored min_invoice=-4389.05 is the same fact)."""
    claimed, actual = abs(claimed), abs(actual)
    if actual == 0:
        return claimed == 0
    if unit in ("percent", "%"):
        return abs(claimed - actual) <= 2.0
    if actual < 100_000 and float(claimed).is_integer() and round(claimed) == round(actual):
        return True
    deviation = abs(claimed - actual) / actual * 100
    if actual > 1_000_000:
        return deviation <= 0.5
    return deviation <= 1.0   # agents round aggregates (€914,861 → "€914K")


def _iter_queries(query_results: dict):
    """Yield (query_name, rows[list[dict]]) for every executed query."""
    results = (query_results or {}).get("results", query_results or {})
    if not isinstance(results, dict):
        return
    for qname, qdata in results.items():
        rows = qdata.get("rows", qdata) if isinstance(qdata, dict) else qdata
        if isinstance(rows, dict):
            rows = [rows]
        if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
            yield qname, rows


_DIM_BY_COL = (
    (re.compile(r"(_|^)(eur|amount|revenue|total|ltv|importe)", re.I), "EUR"),
    (re.compile(r"(_|^)pct$|_pct(_|$)|percent|share", re.I), "percent"),
    (re.compile(r"days|dias|d[ií]as", re.I), "days"),
    (re.compile(r"(_|^)(num|count|n_)|_count$|invoices$|customers$", re.I), "count"),
)


def _infer_dimension(column: str) -> str:
    for rx, dim in _DIM_BY_COL:
        if rx.search(column):
            return dim
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 1.5 — GENERIC REGISTRY ENRICHMENT (deterministic)
# ═══════════════════════════════════════════════════════════════════════════


def enrich_registry(
    report: VerificationReport,
    query_results: dict,
    max_entries: int = 80,
) -> int:
    """Register single-row scalars, rank-1 values and column sums from every
    query result the legacy builder skipped. Returns entries added."""
    added = 0
    for qname, rows in _iter_queries(query_results):
        numeric_cols: dict[str, list[float]] = {}
        for row in rows:
            for col, raw in row.items():
                val = _to_float(raw)
                if val is not None:
                    numeric_cols.setdefault(col, []).append(val)

        for col, vals in numeric_cols.items():
            dim = _infer_dimension(col)
            candidates: list[tuple[str, float, str, str]] = []
            if len(rows) == 1:
                candidates.append((f"{qname}.{col}", vals[0], "measured",
                                   f"{qname}: {col}"))
            else:
                candidates.append((f"{qname}.{col}_top1", vals[0], "measured",
                                   f"{qname}: {col} of rank-1 row"))
                if dim in ("EUR", "count") and 2 <= len(vals) <= 60:
                    candidates.append((f"{qname}.{col}_sum", sum(vals), "computed",
                                       f"{qname}: sum of {col} over {len(vals)} rows"))
            for label, value, confidence, desc in candidates:
                if label in report.number_registry:
                    continue
                if len(report.number_registry) >= max_entries:
                    return added
                report.number_registry[label] = NumberRegistryEntry(
                    label=label, value=round(value, 2), source_query=qname,
                    source_description=desc, confidence=confidence,
                    verified_at=report.verified_at, dimension=dim,
                )
                added += 1
    return added


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 2 — LLM RERANK (propose) + DETERMINISTIC CONFIRMATION (dispose)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class RerankOutcome:
    report: VerificationReport
    upgraded: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)   # proposed but not confirmed
    disputed: list[dict] = field(default_factory=list)   # LLM says data contradicts


def _data_digest(query_results: dict, max_rows: int = 15) -> str:
    """Compact, token-bounded digest of the available data for the prompt."""
    lines = []
    for qname, rows in _iter_queries(query_results):
        cols = sorted({c for r in rows for c in r})
        lines.append(f"## {qname} ({len(rows)} rows) cols: {', '.join(cols)}")
        for i, row in enumerate(rows[:max_rows]):
            compact = {c: row.get(c) for c in cols if not str(row.get(c, ""))[:1].isalpha() or len(str(row.get(c, ""))) < 28}
            lines.append(f"  r{i}: {json.dumps(compact, default=str, ensure_ascii=False)}")
        if len(rows) > max_rows:
            lines.append(f"  … {len(rows) - max_rows} more rows omitted")
    return "\n".join(lines)


_PROPOSAL_PROMPT = """You are a deterministic verifier's assistant. Stage-1 structural
verification left these claims UNVERIFIABLE. For each, propose the arithmetic derivation
over the query data below that the claim's MEANING points to (e.g. a claim about "top 10
customers revenue" → sum of the value column over rows 0-9 of the concentration query).

DO NOT do the arithmetic yourself — code recomputes every proposal and only a numeric
match upgrades the claim, so a plausible-but-wrong proposal costs nothing. PREFER
proposing over answering "none" whenever the claim semantically references data you can
see. Answer "none" only when the claim references data that simply is not present.

Allowed derivation kinds:
- "direct":     {{"query": q, "column": c, "row": i}}
- "sum":        {{"query": q, "column": c, "rows": [i,...] | "all"}}
- "difference": {{"a": <direct-ref>, "b": <direct-ref>}}   (computes |a-b|)
- "share_pct":  {{"part": <direct-ref>, "total_query": q, "total_column": c}}  (part/sum*100)
- "contradicted": the data DISPROVES the claim (point to the contradicting ref)
- "none": no derivation exists in this data

Return ONLY a JSON array, one object per claim:
[{{"claim_id": "...", "kind": "...", ...refs..., "note": "<10 words"}}]

CLAIMS:
{claims}

DATA:
{digest}
"""


def _resolve_ref(ref: dict, query_results: dict) -> Optional[float]:
    by_name = dict(_iter_queries(query_results))
    rows = by_name.get(ref.get("query"))
    if rows is None:
        return None
    try:
        return _to_float(rows[int(ref.get("row", 0))].get(ref.get("column")))
    except (IndexError, ValueError, TypeError):
        return None


def _compute_proposal(p: dict, query_results: dict) -> Optional[float]:
    """Recompute the proposed derivation. None = unresolvable."""
    kind = p.get("kind")
    by_name = dict(_iter_queries(query_results))
    if kind == "direct":
        return _resolve_ref(p, query_results)
    if kind == "sum":
        rows = by_name.get(p.get("query"))
        if rows is None:
            return None
        idxs = range(len(rows)) if p.get("rows") in ("all", None) else p["rows"]
        try:
            vals = [_to_float(rows[int(i)].get(p.get("column"))) for i in idxs]
        except (IndexError, ValueError, TypeError):
            return None
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None
    if kind == "difference":
        a = _resolve_ref(p.get("a", {}), query_results)
        b = _resolve_ref(p.get("b", {}), query_results)
        return abs(a - b) if a is not None and b is not None else None
    if kind == "share_pct":
        part = _resolve_ref(p.get("part", {}), query_results)
        rows = by_name.get(p.get("total_query"))
        if part is None or rows is None:
            return None
        vals = [_to_float(r.get(p.get("total_column"))) for r in rows]
        vals = [v for v in vals if v is not None]
        total = sum(vals)
        return part / total * 100 if total else None
    return None


async def _default_llm_json(prompt: str) -> list[dict]:
    """One batched call through the (monkey-patchable) agent SDK."""
    import os
    from claude_agent_sdk import ClaudeAgentOptions, query  # type: ignore

    options = ClaudeAgentOptions(
        model=os.getenv("VALINOR_RERANK_MODEL", "haiku"),
        system_prompt="You answer with a single JSON array. No prose.",
        max_turns=1,
    )
    chunks: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        for block in getattr(msg, "content", []):
            chunks.append(getattr(block, "text", ""))
    text = "".join(chunks)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    return json.loads(m.group(0)) if m else []


async def rerank_unverifiable(
    report: VerificationReport,
    query_results: dict,
    claims_by_id: Optional[dict] = None,
    llm_json_fn: Optional[Callable[[str], Awaitable[list[dict]]]] = None,
    max_claims: int = 40,
) -> RerankOutcome:
    """Stage 2 over the UNVERIFIABLE remainder. Mutates `report` in place
    (claim statuses + counters + issues) and returns the outcome breakdown.

    claims_by_id ({claim_id: AtomicClaim}) provides claim text/units for the
    prompt; without it the registry of results still works (text omitted).
    llm_json_fn is injectable for offline tests.
    """
    llm_json_fn = llm_json_fn or _default_llm_json
    outcome = RerankOutcome(report=report)

    dubious = [r for r in report.results if r.status == "UNVERIFIABLE"]
    targets = []
    for r in dubious[:max_claims]:
        claim = (claims_by_id or {}).get(r.claim_id)
        value = getattr(claim, "claimed_value", None)
        if value is None or value == 0:
            continue   # negative/existence claims: out of stage-2 scope
        targets.append({
            "claim_id": r.claim_id,
            "claimed_value": value,
            "unit": getattr(claim, "claimed_unit", "EUR"),
            "text": getattr(claim, "claim_text", "")[:120],
        })
    if not targets:
        return outcome

    prompt = _PROPOSAL_PROMPT.format(
        claims=json.dumps(targets, ensure_ascii=False, indent=1),
        digest=_data_digest(query_results),
    )
    proposals = await llm_json_fn(prompt)
    by_claim = {p.get("claim_id"): p for p in proposals if isinstance(p, dict)}
    claimed_by_id = {t["claim_id"]: t for t in targets}

    for r in report.results:
        p = by_claim.get(r.claim_id)
        t = claimed_by_id.get(r.claim_id)
        if not p or not t or r.status != "UNVERIFIABLE":
            continue
        if p.get("kind") in (None, "none"):
            continue
        if p.get("kind") == "contradicted":
            actual = _compute_proposal({**p, "kind": "direct"}, query_results)
            entry = {"claim_id": r.claim_id, "claimed": t["claimed_value"],
                     "pointed_value": actual, "note": p.get("note", "")}
            outcome.disputed.append(entry)
            report.issues.append({
                "severity": "warning",
                "description": f"stage-2 dispute: claim {r.claim_id} "
                               f"({t['claimed_value']}) vs data {actual} — review",
            })
            continue
        actual = _compute_proposal(p, query_results)
        if actual is not None and _values_match(t["claimed_value"], actual, t["unit"]):
            r.status = "VERIFIED"
            r.actual_value = round(actual, 2)
            r.deviation_pct = (
                abs(t["claimed_value"] - actual) / abs(actual) * 100 if actual else 0.0
            )
            r.evidence = (f"stage-2 rerank: {p.get('kind')} over "
                          f"{p.get('query') or p.get('a', {}).get('query', '?')} "
                          f"(LLM-proposed, deterministically confirmed)")
            r.confidence_score = 0.70
            outcome.upgraded.append({"claim_id": r.claim_id, "kind": p.get("kind"),
                                     "claimed": t["claimed_value"], "actual": actual})
        else:
            outcome.rejected.append({"claim_id": r.claim_id, "kind": p.get("kind"),
                                     "claimed": t["claimed_value"], "computed": actual})

    # Refresh counters — never touch claims stage 1 already settled.
    report.verified_claims = sum(1 for r in report.results if r.status == "VERIFIED")
    report.unverifiable_claims = sum(1 for r in report.results if r.status == "UNVERIFIABLE")
    if report.total_claims:
        report.verification_rate = report.verified_claims / report.total_claims
    return outcome
