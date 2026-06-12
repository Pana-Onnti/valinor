"""
Two-layer judge for the N3 global-questions eval (VAL-192 N3).

Layer 0 — deterministic, runs FIRST: required_facts presence (numeric facts via
the N1-fixed number extractor with per-fact tolerance; label facts via
normalized containment) + must_not_include traps. A FLAT arm failing layer 0
is structural-failure evidence independent of any judge's opinion.

Layer 1 — LLM-as-judge (Haiku via the monkey-patchable agent SDK, injectable
for tests): scores each required_fact 0 (absent) / 1 (present, wrong number) /
2 (present, correct ±tolerance) and counts forbidden hits (−2 each). The judge
receives the REFERENCE values (computed by scripts/build_global_references.py
— pure joins, independent of the graph under test) plus granularity notes,
and must penalize over-granular claims as groundedness failures.

Gate (the N3 milestone): community arm ≥80% of required-fact points on ≥5
questions where flat scores <50% on those same questions, with zero forbidden
hits in the community arm. Run via `scripts/eval.py graphrag`.

Refs: VAL-192
"""

from __future__ import annotations

import json
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from valinor.quality.narrator_metrics import extract_numbers


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def resolve_placeholder(expected: Any, qid_short: str, references: dict) -> Any:
    """'{REF:q1.exposed_eur}' → references['q1']['exposed_eur'] (verbatim otherwise)."""
    if isinstance(expected, str):
        m = re.fullmatch(r"\{REF:(\w+)\.(\w+)\}", expected.strip())
        if m:
            return references.get(m.group(1), {}).get(m.group(2))
    return expected


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 0 — deterministic
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Layer0Result:
    facts_total: int = 0
    facts_present: float = 0.0       # numeric: 0/1 each; labels: fraction present
    forbidden_hits: int = 0
    details: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.facts_present / self.facts_total if self.facts_total else 0.0


def _numeric_present(answer: str, expected: float, tolerance_pct: float) -> bool:
    for num in extract_numbers(answer):
        target = abs(float(expected))
        if target == 0:
            if num.value == 0:
                return True
            continue
        if abs(abs(num.value) - target) / target * 100 <= max(tolerance_pct, 0.01):
            return True
    return False


def judge_layer0(answer: str, question: dict, references: dict) -> Layer0Result:
    """Deterministic presence check of required facts + forbidden traps."""
    res = Layer0Result()
    qid_short = question["id"].split("-")[0]

    for fact in question.get("required_facts", []):
        expected = resolve_placeholder(fact.get("expected"), qid_short, references)
        if expected is None:
            continue
        res.facts_total += 1
        if fact.get("kind") == "labels":
            labels = expected if isinstance(expected, list) else [expected]
            if not labels:
                res.facts_present += 1.0   # empty reference: vacuously present
                continue
            blob = _norm(answer)
            got = sum(1 for lab in labels if _norm(lab) and _norm(lab) in blob)
            res.facts_present += got / len(labels)
            if got < len(labels):
                res.details.append(f"labels {fact['fact']}: {got}/{len(labels)}")
        else:
            ok = _numeric_present(answer, float(expected), float(fact.get("tolerance_pct", 1.0)))
            res.facts_present += 1.0 if ok else 0.0
            if not ok:
                res.details.append(f"missing numeric {fact['fact']} ≈ {expected}")

    # A numeric trap is a SUBSTITUTION trap: it only counts when some required
    # numeric fact is missing (the answer used the wrong number INSTEAD of the
    # right one). Mere co-occurrence next to the correct facts is legitimate
    # context ("del total en riesgo X%, los doblemente expuestos son Y%").
    numeric_facts_all_present = all(
        _numeric_present(answer, float(resolve_placeholder(f.get("expected"), qid_short, references)),
                         float(f.get("tolerance_pct", 1.0)))
        for f in question.get("required_facts", [])
        if f.get("kind") != "labels"
        and resolve_placeholder(f.get("expected"), qid_short, references) is not None
    )
    for trap in question.get("must_not_include", []):
        t = resolve_placeholder(trap, qid_short, references)
        if t is None:
            continue
        if isinstance(t, (int, float)):
            if _numeric_present(answer, float(t), 0.5) and not numeric_facts_all_present:
                res.forbidden_hits += 1
                res.details.append(f"forbidden number present (substitution): {t}")
        elif isinstance(t, str) and _norm(t) and _norm(t) in _norm(answer):
            res.forbidden_hits += 1
            res.details.append(f"forbidden text present: {t}")
    return res


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 1 — LLM-as-judge (injectable)
# ═══════════════════════════════════════════════════════════════════════════


_JUDGE_PROMPT = """Sos un juez determinista de groundedness para análisis financiero.
Pregunta evaluada:
{question}

REFERENCIA (calculada por joins deterministas — es la verdad):
{reference}

{granularity}

RESPUESTA A EVALUAR:
{answer}

Por cada required_fact puntuá: 0 = ausente, 1 = presente pero número/lista incorrecta,
2 = presente y correcto (dentro de la tolerancia).
IMPORTANTE: las listas de la referencia son CONJUNTOS sin orden (vienen ordenadas
alfabéticamente por convención) — NO penalices el orden en que la respuesta las
presenta; solo importa la pertenencia.

FORBIDDEN: un forbidden es SOLO una frase citable de la respuesta que (a) atribuye
una categoría de producto a un CLIENTE individual (los datos son segmento×categoría),
o (b) CONTRADICE un valor de la referencia (mismo concepto, número incompatible).
NO son forbidden: mencionar clientes por nombre, citar números del contexto que la
referencia no cubre (la referencia es mínima, no exhaustiva), decir "no derivable
de los datos disponibles", ni los números correctos. Por cada forbidden citá la
frase textual.

Respondé SOLO un objeto JSON:
{{"facts": [{{"fact": "...", "score": 0|1|2}}], "forbidden_quotes": ["<frase textual>", ...], "rationale": "<máx 30 palabras>"}}

REQUIRED FACTS:
{facts}
"""


async def _default_judge_llm(prompt: str) -> dict:
    import os
    from claude_agent_sdk import ClaudeAgentOptions, query  # type: ignore

    options = ClaudeAgentOptions(
        model=os.getenv("VALINOR_JUDGE_MODEL", "haiku"),
        system_prompt="You answer with a single JSON object. No prose.",
        max_turns=1,
    )
    chunks: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        for block in getattr(msg, "content", []):
            chunks.append(getattr(block, "text", ""))
    m = re.search(r"\{.*\}", "".join(chunks), re.DOTALL)
    return json.loads(m.group(0)) if m else {"facts": [], "forbidden_hits": 0}


async def judge_layer1(
    answer: str,
    question: dict,
    references: dict,
    judge_llm_fn: Optional[Callable[[str], Awaitable[dict]]] = None,
    reps: int = 1,
) -> dict:
    """LLM judge, median over `reps`. Returns {points, max_points, forbidden_hits, raw}."""
    judge_llm_fn = judge_llm_fn or _default_judge_llm
    qid_short = question["id"].split("-")[0]
    facts = [
        {**f, "expected": resolve_placeholder(f.get("expected"), qid_short, references)}
        for f in question.get("required_facts", [])
    ]
    facts = [f for f in facts if f.get("expected") is not None]
    if not facts:
        return {"points": 0, "max_points": 0, "forbidden_hits": 0, "raw": []}

    prompt = _JUDGE_PROMPT.format(
        question=question["question"].strip(),
        reference=json.dumps(references.get(qid_short, {}), ensure_ascii=False, indent=1),
        granularity=("NOTA DE GRANULARIDAD: " + question["granularity_notes"].strip())
        if question.get("granularity_notes") else "",
        answer=answer[:8000],
        facts=json.dumps([{"fact": f["fact"], "expected": f["expected"]} for f in facts],
                         ensure_ascii=False, indent=1),
    )

    rep_points: list[float] = []
    rep_forbidden: list[int] = []
    raw = []
    for _ in range(max(1, reps)):
        verdict = await judge_llm_fn(prompt)
        raw.append(verdict)
        pts = sum(min(2, max(0, int(f.get("score", 0)))) for f in verdict.get("facts", []))
        rep_points.append(pts)
        # Auditable forbidden: count = quotable claims; legacy int kept for
        # injected test judges that don't emit quotes.
        quotes = verdict.get("forbidden_quotes")
        rep_forbidden.append(
            len(quotes) if isinstance(quotes, list) else int(verdict.get("forbidden_hits", 0)))
    return {
        "points": statistics.median(rep_points),
        "max_points": 2 * len(facts),
        "forbidden_hits": int(statistics.median(rep_forbidden)),
        "raw": raw,
    }


# ═══════════════════════════════════════════════════════════════════════════
# GATE — the N3 milestone
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_gate(per_question: dict[str, dict], min_wins: int = 5) -> dict:
    """per_question: {qid: {"flat": frac, "community": frac, "community_forbidden": int}}
    (frac = points/max_points). Win = flat < 0.5 ≤ ... community ≥ 0.8, no forbidden."""
    wins, flat_fails = [], []
    for qid, s in per_question.items():
        if s["flat"] < 0.5:
            flat_fails.append(qid)
            if s["community"] >= 0.8 and s.get("community_forbidden", 0) == 0:
                wins.append(qid)
    return {
        "flat_fails": sorted(flat_fails),
        "wins": sorted(wins),
        "gate_passed": len(wins) >= min_wins,
        "min_wins": min_wins,
    }
