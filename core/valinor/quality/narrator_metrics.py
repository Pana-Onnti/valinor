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
    start: int = -1     # span in the source text (for context-sensitive rules)
    end: int = -1


@dataclass
class NumberAudit:
    """Grounding breakdown of the numbers in a narrator output.

    Buckets (VAL-192 N1 Bug-3): `declared` are numbers the narrator explicitly
    marked as estimates ([ESTIMADO]/[INFERIDO]/~…) following the pipeline's own
    honesty protocol — not fabrications, tracked separately. `derived_credited`
    are numbers matched by within-column arithmetic (Δ/%change/share/sum) when
    that crediting is enabled; they count as grounded.
    """
    total: int = 0
    grounded: int = 0
    ungrounded: int = 0
    declared: int = 0
    derived_credited: int = 0
    grounded_values: list[float] = field(default_factory=list)
    ungrounded_values: list[float] = field(default_factory=list)
    declared_values: list[float] = field(default_factory=list)

    @property
    def _verifiable(self) -> int:
        # Declared estimates are out of the verifiable denominator: the metric
        # targets UNdeclared fabrication, honesty lives in the hedging metric.
        return self.grounded + self.ungrounded

    @property
    def grounded_rate(self) -> float:
        return self.grounded / self._verifiable if self._verifiable else 0.0

    @property
    def hallucinated_rate(self) -> float:
        return self.ungrounded / self._verifiable if self._verifiable else 0.0


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
            "numbers_declared": self.numbers.declared,
            "numbers_derived_credited": self.numbers.derived_credited,
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
# The leading lookbehind keeps us out of identifiers ("Q1", "T14:05" in ISO
# stamps, "v0") and number tails; the digit-final num core and the trailing
# letter lookahead keep "### 2. Base" / "€183.906 bajo" from parsing as
# billions (VAL-192 N1 Bug-2).
_NUMBER_RE = re.compile(
    r"(?<![\w.,])"
    r"(?P<cur>€|\$|EUR|USD)?\s*"
    r"(?P<num>\d(?:[\d.,]*\d)?)"
    r"(?:\s*(?P<suffix>MM|millones|mill[oó]n|mil|K|M|B|bn))?(?![A-Za-zÀ-ÿ])"
    r"\s*(?P<pct>%)?",
    re.IGNORECASE,
)

# ── date/time masking (VAL-192 N1 Bug-2) ────────────────────────────────────
# Calendar dates and times are not numeric claims: "Deadline: 10 mayo 2026"
# must not count "10" as a (hallucinated) figure, and "2025-01-02" must not
# leak "01"/"02". Durations ("147 días") stay countable — they are data claims
# (e.g. data_freshness.days_since_latest) and are grounded via Bug-1 parsing.

_MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|"
    "octubre|noviembre|diciembre|ene|feb|mar|abr|jun|jul|ago|sept|sep|oct|nov|dic|"
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december"
)

_DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?Z?)?")
_DATE_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b")
_DATE_DAY_MONTH_RE = re.compile(
    r"\b\d{1,2}\s*(?:de\s+)?(?:" + _MONTHS + r")\b", re.IGNORECASE
)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
# Rank labels ("top-50", "top 10", "#2") are structural references, not data
# claims — same class as "Q1" (found via the golden set on real controller text).
_RANK_LABEL_RE = re.compile(r"\btop[-\s]?\d+\b|#\d+", re.IGNORECASE)


def _date_spans(text: str) -> list[tuple[int, int]]:
    """Spans of calendar dates / times / rank labels — numbers inside are skipped."""
    spans: list[tuple[int, int]] = []
    for rx in (_DATE_ISO_RE, _DATE_DAY_MONTH_RE, _TIME_RE, _RANK_LABEL_RE):
        spans.extend(m.span() for m in rx.finditer(text))
    for m in _DATE_SLASH_RE.finditer(text):
        d, mo = int(m.group(1)), int(m.group(2))
        # Plausible as dd/mm or mm/dd → date. "36/70 claims" stays countable.
        if (d <= 31 and mo <= 12) or (d <= 12 and mo <= 31):
            spans.append(m.span())
    return spans

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

    Bare year-like integers (1990-2100) and numbers inside calendar dates/times
    ("10 mayo 2026", "2025-01-02", "14:05:56") are skipped — dates, not claims.
    """
    out: list[ExtractedNumber] = []
    masked = _date_spans(text or "")
    for m in _NUMBER_RE.finditer(text or ""):
        if any(m.start("num") < end and m.end("num") > start for start, end in masked):
            continue
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
            start=m.start(),
            end=m.end(),
        )
        if suffix == "" and _is_year_like(num):
            continue
        out.append(num)
    return out


# ── declared estimates (VAL-192 N1 Bug-3) ───────────────────────────────────
# The pipeline's own honesty protocol tags non-measured figures: "[ESTIMADO]",
# "[INFERIDO]", "*(estimado)*", "~" prefix. A narrator following that protocol
# is not fabricating — these go to the `declared` bucket, not `hallucinated`.
# Hedging words ("aproximadamente") are NOT markers: they stay in the hedging
# metric, so the canonical €13.5M case still counts as hallucinated.

_DECLARED_AFTER_RE = re.compile(
    r"\[(?:ESTIMADO|INFERIDO|PROYECTADO)|\(\s*(?:estimad[oa]|inferid[oa]|proyectad[oa])",
    re.IGNORECASE,
)


def _is_declared_estimate(text: str, num: ExtractedNumber) -> bool:
    """True if the mention is explicitly marked as an estimate."""
    if num.start < 0:
        return False
    if "~" in text[max(0, num.start - 3):num.start + 1]:
        return True
    return bool(_DECLARED_AFTER_RE.search(text[num.end:num.end + 45]))


# ═══════════════════════════════════════════════════════════════════════════
# GROUND TRUTH + MATCHING
# ═══════════════════════════════════════════════════════════════════════════


# DB drivers serialize NUMERIC columns as strings ("364517.30") and intervals
# as "147 days, 0:00:00" — both are real, grounded values (VAL-192 N1 Bug-1).
# Dates/datetimes/UUIDs contain non-numeric chars and stay out: they are not
# numeric claims (their text-side mentions are masked by _date_spans).
_INTERVAL_STR_RE = re.compile(r"(\d+)\s*days?\b", re.IGNORECASE)
_NUMERIC_STR_RE = re.compile(r"[-+]?\d[\d.,]*")


def _parse_string_numeric(s: str) -> Optional[float]:
    """Parse a DB value serialized as string; None if it isn't purely numeric."""
    s = s.strip()
    m = _INTERVAL_STR_RE.match(s)          # "147 days, 0:00:00" → 147.0
    if m:
        return float(m.group(1))
    if _NUMERIC_STR_RE.fullmatch(s):       # "364517.30", "-4389.05", "80.7"
        base = _parse_numeric(s.lstrip("+-"))
        if base is None:
            return None
        return -base if s.startswith("-") else base
    return None


def _iter_numeric(obj: Any):
    """Yield every numeric (non-bool) leaf value in a nested dict/list.

    String leaves that are purely numeric (or Postgres intervals) count too —
    see _parse_string_numeric (VAL-192 N1 Bug-1).
    """
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, str):
        val = _parse_string_numeric(obj)
        if val is not None:
            yield val
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_numeric(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_numeric(v)


def _iter_numeric_with_prose(obj: Any):
    """Like _iter_numeric, but also extracts numbers MENTIONED inside prose
    strings ("doble conteo de €20,520–€51,300"). Used for findings only: the
    narrator's job is faithfulness to its inputs, and agent finding text is
    input — repeating a figure stated there is not fabrication (N1 Bug-3)."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, str):
        val = _parse_string_numeric(obj)
        if val is not None:
            yield val
        else:
            for num in extract_numbers(obj):
                yield num.value
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_numeric_with_prose(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_numeric_with_prose(v)


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
        truth.extend(_iter_numeric_with_prose(findings))

    # Drop near-zero noise; keep magnitudes that are meaningful to cite.
    # abs(): the text extractor is unsigned ("pérdida de €4.389" cites the
    # magnitude of min_invoice=-4389.05), so matching is on magnitudes.
    return [abs(t) for t in truth if abs(t) >= 1.0]


def collect_derived_candidates(
    query_results: Optional[dict] = None,
    baseline: Optional[dict] = None,
) -> list[float]:
    """Within-column derived values: |Δ|, %change, share-of-total and sums over
    each query column (plus the baseline as one group).

    Restricted to column-mates ON PURPOSE: corpus-wide pairwise crediting was
    measured on the 2026-05-08 Gloria narrators and credits arbitrary planning
    numbers ("Top 200", "Siguientes 500") — it would blind the metric. Standard
    analyst arithmetic over a series (MoM gap, share of total) is the defensible
    boundary. OFF by default; eval.py measures both configs (N1 Bug-3).
    """
    cols: dict[str, list[float]] = {}
    qr = (query_results or {})
    qr = qr.get("results", qr)
    if isinstance(qr, dict):
        for qname, qdata in qr.items():
            rows = qdata.get("rows", qdata) if isinstance(qdata, dict) else qdata
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for col, raw in row.items():
                    if isinstance(raw, bool):
                        continue
                    val = (
                        float(raw) if isinstance(raw, (int, float))
                        else _parse_string_numeric(raw) if isinstance(raw, str)
                        else None
                    )
                    if val is not None:
                        cols.setdefault(f"{qname}.{col}", []).append(val)
    if baseline:
        cols["baseline"] = list(_iter_numeric(baseline))

    out: set[float] = set()
    for vals in cols.values():
        vals = [v for v in vals if abs(v) >= 1.0][:60]
        if len(vals) < 2:
            continue
        total = sum(vals)
        out.add(abs(total))
        for i, a in enumerate(vals):
            if total:
                out.add(round(abs(a) / abs(total) * 100, 4))
            for b in vals[i + 1:]:
                out.add(abs(a - b))
                if b:
                    out.add(round(abs(a - b) / abs(b) * 100, 4))
                if a:
                    out.add(round(abs(a - b) / abs(a) * 100, 4))
    return sorted(v for v in out if v >= 1.0)


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


def audit_numbers(
    text: str,
    ground_truth: list[float],
    derived_truth: Optional[list[float]] = None,
) -> NumberAudit:
    """Classify every number in `text`: grounded / declared / derived / ungrounded.

    Precedence: grounded beats everything (a tagged-but-correct number is still
    grounded); then declared-estimate markers; then (if enabled) within-column
    derived credit, which counts toward grounded; the rest is hallucinated.
    """
    audit = NumberAudit()
    for num in extract_numbers(text):
        audit.total += 1
        if is_grounded(num, ground_truth):
            audit.grounded += 1
            audit.grounded_values.append(num.value)
        elif _is_declared_estimate(text, num):
            audit.declared += 1
            audit.declared_values.append(num.value)
        elif derived_truth and is_grounded(num, derived_truth):
            audit.derived_credited += 1
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
    credit_derived: bool = False,
) -> NarratorMetrics:
    """Score one narrator output against its run's ground-truth numbers (VAL-163).

    credit_derived=True additionally credits within-column arithmetic (Δ/%change/
    share/sum) — an eval.py config dimension, off by default (N1 Bug-3).
    """
    ground_truth = collect_ground_truth(verification_report, findings, query_results)
    derived = collect_derived_candidates(query_results) if credit_derived else None
    return NarratorMetrics(
        numbers=audit_numbers(text, ground_truth, derived_truth=derived),
        hedging=audit_hedging(text),
        word_count=_word_count(text),
    )
