"""
Narrator grounding metrics — deterministic, LLM-free measurement of how well a
narrator's prose is anchored to verified numbers.

This is the measurement instrument for the Number Registry A/B experiment
(VAL-163): given a narrator's text output plus the ground-truth numbers for that
run (the verification Number Registry ∪ findings ∪ query_results), it scores:

  * grounded_rate   — % of numbers in the text that match a ground-truth value
  * hallucinated    — numbers that appear nowhere in the ground truth
  * hedging         — frequency of hedging/qualifier language (ES + EN)

Everything here is pure: no Claude calls, no DB. The expensive part of the A/B
(actually producing control vs treatment narrator text) runs the real narrators;
this module only scores the text they produce, so it is fully unit-testable with
hand-built fixtures.

Tolerance mirrors VerificationEngine._values_match (core/valinor/verification.py):
counts match exactly, percentages within ±2 absolute points, monetary/other within
a magnitude-scaled relative band. Kept local on purpose — this is offline analysis
tooling, decoupled from the production verifier.

Refs: VAL-163
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class ExtractedNumber:
    """A numeric mention found in narrator text."""
    raw: str            # the matched span, e.g. "€1.2M", "45%", "3,139"
    value: float        # normalized magnitude
    is_percent: bool    # the mention carried a % sign
    is_currency: bool   # the mention carried a currency marker (€, $, EUR, USD)


@dataclass
class NumberAudit:
    """Grounding breakdown of the numbers in a narrator output."""
    total: int = 0
    grounded: int = 0
    ungrounded: int = 0
    grounded_values: list[float] = field(default_factory=list)
    ungrounded_values: list[float] = field(default_factory=list)

    @property
    def grounded_rate(self) -> float:
        return self.grounded / self.total if self.total else 0.0

    @property
    def hallucinated_rate(self) -> float:
        return self.ungrounded / self.total if self.total else 0.0


@dataclass
class HedgingAudit:
    """Hedging-language breakdown."""
    count: int = 0
    matches: list[str] = field(default_factory=list)
    word_count: int = 0

    @property
    def per_100_words(self) -> float:
        return (self.count / self.word_count * 100) if self.word_count else 0.0


@dataclass
class NarratorMetrics:
    """Full grounding metrics for one narrator output."""
    numbers: NumberAudit
    hedging: HedgingAudit
    word_count: int

    def to_dict(self) -> dict:
        return {
            "word_count": self.word_count,
            "numbers_total": self.numbers.total,
            "numbers_grounded": self.numbers.grounded,
            "numbers_ungrounded": self.numbers.ungrounded,
            "grounded_rate": round(self.numbers.grounded_rate, 4),
            "hallucinated_rate": round(self.numbers.hallucinated_rate, 4),
            "hedging_count": self.hedging.count,
            "hedging_per_100_words": round(self.hedging.per_100_words, 4),
        }


# ═══════════════════════════════════════════════════════════════════════════
# NUMBER EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

# One token: optional currency marker, digits with , / . grouping, optional
# decimal, optional magnitude suffix (K/M/MM/B/bn/mil/millón…), optional %.
# Suffix alternatives are ordered longest-first so "mil" is not eaten by "M".
_NUMBER_RE = re.compile(
    r"(?P<cur>€|\$|EUR|USD)?\s*"
    r"(?P<num>\d[\d.,]*)"
    r"\s*(?P<suffix>MM|millones|mill[oó]n|mil|K|M|B|bn)?"
    r"\s*(?P<pct>%)?",
    re.IGNORECASE,
)

_SUFFIX_MULT = {
    "k": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "mil": 1_000,
    "millon": 1_000_000,
    "millón": 1_000_000,
    "millones": 1_000_000,
}


def _parse_numeric(core: str) -> Optional[float]:
    """Parse the digit core of a number, resolving , / . as grouping vs decimal.

    Heuristic (covers Anglo "1,234,567.89" and European "1.234.567,89"):
      * both separators present → the rightmost is the decimal point.
      * one separator: if the last group is exactly 3 digits it's a thousands
        group (dropped); otherwise it's a decimal point. This parses "3,139" and
        "1.234" as 3139/1234 but "12.5", "519,77" and "1.2" as decimals.
      * no separator → plain int/float.
    """
    core = core.strip()
    if not re.search(r"\d", core):
        return None
    has_comma = "," in core
    has_dot = "." in core
    try:
        if has_comma and has_dot:
            dec = "," if core.rfind(",") > core.rfind(".") else "."
            grp = "." if dec == "," else ","
            return float(core.replace(grp, "").replace(dec, "."))
        if has_comma or has_dot:
            sep = "," if has_comma else "."
            last = core.rsplit(sep, 1)[1]
            if len(last) == 3:
                return float(core.replace(sep, ""))     # thousands grouping
            return float(core.replace(sep, "."))         # decimal
        return float(core)
    except ValueError:
        return None


def _is_year_like(num: "ExtractedNumber") -> bool:
    """A bare 4-digit integer in 1990-2100 — almost always a calendar year, not a
    financial figure. Excluded so dates don't inflate the hallucination count."""
    return (
        not num.is_currency
        and not num.is_percent
        and float(num.value).is_integer()
        and 1990 <= num.value <= 2100
    )


def extract_numbers(text: str) -> list[ExtractedNumber]:
    """Extract numeric mentions (currency, percent, counts) from narrator text.

    Bare year-like integers (1990-2100) are skipped — they are dates, not claims.
    """
    out: list[ExtractedNumber] = []
    for m in _NUMBER_RE.finditer(text or ""):
        core = m.group("num")
        base = _parse_numeric(core)
        if base is None:
            continue
        suffix = (m.group("suffix") or "").lower()
        value = base * _SUFFIX_MULT.get(suffix, 1)
        num = ExtractedNumber(
            raw=m.group(0).strip(),
            value=value,
            is_percent=m.group("pct") == "%",
            is_currency=m.group("cur") is not None,
        )
        if suffix == "" and _is_year_like(num):
            continue
        out.append(num)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# GROUND TRUTH + MATCHING
# ═══════════════════════════════════════════════════════════════════════════


def _iter_numeric(obj: Any):
    """Yield every numeric (non-bool) leaf value in a nested dict/list."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_numeric(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_numeric(v)


def collect_ground_truth(
    verification_report: Any = None,
    findings: Optional[dict] = None,
    query_results: Optional[dict] = None,
) -> list[float]:
    """Collect the allowed/true numbers for a run: registry ∪ findings ∪ query_results.

    A narrator number is "grounded" iff it matches one of these within tolerance
    (VAL-163 metrics #1/#2). Accepts the live VerificationReport object or a plain
    dict-shaped registry, so it works with both real runs and test fixtures.
    """
    truth: list[float] = []

    if verification_report is not None:
        registry = getattr(verification_report, "number_registry", None)
        if registry is None and isinstance(verification_report, dict):
            registry = verification_report.get("number_registry")
        if isinstance(registry, dict):
            for entry in registry.values():
                val = getattr(entry, "value", None)
                if val is None and isinstance(entry, dict):
                    val = entry.get("value")
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    truth.append(float(val))

    if query_results:
        truth.extend(_iter_numeric(query_results.get("results", query_results)))

    if findings:
        truth.extend(_iter_numeric(findings))

    # Drop near-zero noise; keep magnitudes that are meaningful to cite.
    return [t for t in truth if abs(t) >= 1.0]


def _within_tolerance(value: float, target: float, is_percent: bool) -> bool:
    """Dimension-aware match — mirrors VerificationEngine._values_match."""
    if target == 0:
        return value == 0
    if is_percent:
        return abs(value - target) <= 2.0
    # Exact integer match (counts) — both look like whole numbers, modest size.
    if abs(target) < 100_000 and abs(value - round(value)) < 1e-9 and round(value) == round(target):
        return True
    deviation = abs(value - target) / abs(target) * 100
    if abs(target) > 1_000_000:
        return deviation <= 0.5
    if abs(target) > 10_000:
        return deviation <= 0.1
    return deviation <= 1.0


def is_grounded(num: ExtractedNumber, ground_truth: list[float]) -> bool:
    """True if the extracted number matches any ground-truth value within tolerance."""
    return any(_within_tolerance(num.value, g, num.is_percent) for g in ground_truth)


def audit_numbers(text: str, ground_truth: list[float]) -> NumberAudit:
    """Classify every number in `text` as grounded vs ungrounded (hallucinated)."""
    audit = NumberAudit()
    for num in extract_numbers(text):
        audit.total += 1
        if is_grounded(num, ground_truth):
            audit.grounded += 1
            audit.grounded_values.append(num.value)
        else:
            audit.ungrounded += 1
            audit.ungrounded_values.append(num.value)
    return audit


# ═══════════════════════════════════════════════════════════════════════════
# HEDGING LANGUAGE
# ═══════════════════════════════════════════════════════════════════════════

# Qualifier/retraction phrases that signal an unverified number. Spanish first
# (narrators output Spanish) + English. Comparative metric — a constant bias
# cancels between control and treatment; what matters is the relative delta.
_HEDGING_PHRASES = [
    # Spanish
    "aproximadamente", "aproximado", "alrededor de", "cerca de", "en torno a",
    "más o menos", "mas o menos", "se estima", "estimado", "estimada", "estimamos",
    "podría", "podria", "podrían", "podrian", "puede indicar", "puede ser",
    "posiblemente", "probablemente", "tal vez", "quizás", "quizas", "parecería",
    "pareceria", "al parecer", "en general",
    # English
    "approximately", "approximate", "roughly", "around", "may indicate", "may be",
    "might", "could be", "estimated", "appears to", "seems", "possibly", "probably",
    "based on available data", "based on the available data",
]

_HEDGING_RES = [
    (p, re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE))
    for p in _HEDGING_PHRASES
]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def audit_hedging(text: str) -> HedgingAudit:
    """Count hedging-phrase occurrences in narrator text."""
    audit = HedgingAudit(word_count=_word_count(text))
    for phrase, rx in _HEDGING_RES:
        for _ in rx.finditer(text or ""):
            audit.count += 1
            audit.matches.append(phrase)
    return audit


# ═══════════════════════════════════════════════════════════════════════════
# TOP-LEVEL SCORER
# ═══════════════════════════════════════════════════════════════════════════


def score_narrator_output(
    text: str,
    verification_report: Any = None,
    findings: Optional[dict] = None,
    query_results: Optional[dict] = None,
) -> NarratorMetrics:
    """Score one narrator output against its run's ground-truth numbers (VAL-163)."""
    ground_truth = collect_ground_truth(verification_report, findings, query_results)
    return NarratorMetrics(
        numbers=audit_numbers(text, ground_truth),
        hedging=audit_hedging(text),
        word_count=_word_count(text),
    )
