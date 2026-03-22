"""
Verification Engine — Deterministic post-analysis claim verification.

Implements the "Triple Verification" pattern:
  1. Claim decomposition: break each finding into atomic verifiable facts
  2. Re-execution: re-query the source data to verify each fact
  3. Number registry: only verified numbers reach the Narrator

Architecture references:
  - CoVe (Meta, ACL 2024) — Chain-of-Verification
  - SAFE (Google DeepMind, NeurIPS 2024) — fact decomposition + verification
  - CRITIC (ICLR 2024) — tool-interactive self-verification
  - Palantir Foundry — "numbers from deterministic systems, narrative from LLMs"
"""

from __future__ import annotations

import json
import re
import signal
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════════════════════
# SQL SAFETY
# ═══════════════════════════════════════════════════════════════════════════

_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _is_safe_identifier(name: str) -> bool:
    """Validate that a string is a safe SQL identifier (table/column name)."""
    return bool(name and _SAFE_IDENTIFIER_RE.match(name) and len(name) <= 128)


class Dimension(str, Enum):
    """Dimensional type for unit-aware verification."""
    EUR = "EUR"
    COUNT = "count"
    PERCENT = "percent"
    DAYS = "days"
    RATIO = "ratio"
    UNKNOWN = "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class AtomicClaim:
    """A single, verifiable factual claim extracted from a finding."""
    claim_id: str
    finding_id: str
    claim_text: str
    claim_type: str  # "numeric", "comparison", "existence", "attribution"
    claimed_value: float | None = None
    claimed_unit: str = "EUR"
    source_query: str | None = None
    source_row: int | None = None
    source_column: str | None = None


@dataclass
class VerificationResult:
    """Result of verifying a single atomic claim."""
    claim_id: str
    status: str  # "VERIFIED", "FAILED", "UNVERIFIABLE", "APPROXIMATE"
    actual_value: float | None = None
    deviation_pct: float | None = None  # % difference from claimed
    evidence: str = ""
    verification_query: str | None = None
    verified_at: str = ""
    confidence_score: float = 0.0


@dataclass
class NumberRegistryEntry:
    """A verified number that narrators are allowed to use."""
    label: str  # "total_revenue_dec_2024", "ar_outstanding_sales"
    value: float
    unit: str = "EUR"
    source_query: str = ""
    source_description: str = ""
    confidence: str = "measured"  # "measured", "computed", "estimated"
    verified_at: str = ""
    dimension: str = "unknown"


@dataclass
class VerificationReport:
    """Complete verification report for a pipeline run."""
    total_claims: int = 0
    verified_claims: int = 0
    failed_claims: int = 0
    unverifiable_claims: int = 0
    approximate_claims: int = 0
    verification_rate: float = 0.0
    results: list[VerificationResult] = field(default_factory=list)
    number_registry: dict[str, NumberRegistryEntry] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)
    verified_at: str = ""

    @property
    def is_trustworthy(self) -> bool:
        """Pipeline output is trustworthy if >80% of claims are verified."""
        return self.verification_rate >= 0.80

    def to_prompt_context(self) -> str:
        """Serialize for injection into narrator prompts."""
        lines = [
            "## VERIFICATION REPORT",
            f"Claims verified: {self.verified_claims}/{self.total_claims} "
            f"({self.verification_rate:.0%})",
        ]

        if self.failed_claims > 0:
            lines.append(f"⚠ FAILED claims: {self.failed_claims} — DO NOT use these values")

        lines.append("\n### NUMBER REGISTRY (use ONLY these values)")
        for label, entry in self.number_registry.items():
            # Determine confidence tier from matching verification results
            conf_score = self._get_entry_confidence_score(label)
            if conf_score >= 0.85:
                tier_tag = "[HIGH CONFIDENCE]"
            elif conf_score >= 0.60:
                tier_tag = "[MEDIUM CONFIDENCE]"
            else:
                tier_tag = "[LOW CONFIDENCE]"
            lines.append(f"- **{label}**: {entry.value:,.2f} {entry.unit} {tier_tag}")
            if entry.source_description:
                lines.append(f"  Source: {entry.source_description}")

        if self.issues:
            lines.append("\n### ISSUES FOUND")
            for issue in self.issues[:10]:
                lines.append(f"- [{issue.get('severity', '?')}] {issue.get('description', '')}")

        return "\n".join(lines)

    def _get_entry_confidence_score(self, label: str) -> float:
        """Get the confidence score for a registry entry based on its provenance."""
        entry = self.number_registry.get(label)
        if entry is None:
            return 0.0
        _confidence_scores = {
            "measured": 0.95,
            "computed": 0.85,
            "estimated": 0.50,
        }
        return _confidence_scores.get(entry.confidence, 0.50)


# ═══════════════════════════════════════════════════════════════════════════
# VERIFICATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════


class VerificationEngine:
    """
    Deterministic verification of agent findings against source data.

    This is NOT an LLM — it's pure Python that:
      1. Extracts numeric claims from agent findings
      2. Matches each claim to query results
      3. Re-computes values from raw data
      4. Builds a registry of verified numbers for narrators
    """

    TOLERANCE_PCT = 0.5  # Allow 0.5% deviation for rounding

    # SQL keywords that indicate write operations — must be blocked
    FORBIDDEN_SQL_KEYWORDS = frozenset([
        "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
        "TRUNCATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    ])

    def __init__(self, query_results: dict, baseline: dict,
                 knowledge_graph: Any | None = None,
                 connection_string: str | None = None,
                 entity_map: dict | None = None) -> None:
        self.query_results = query_results
        self.baseline = baseline
        self.kg = knowledge_graph
        self.connection_string = connection_string
        self.entity_map = entity_map
        self._registry: dict[str, NumberRegistryEntry] = {}
        self._now = datetime.now().isoformat()

    def verify_findings(self, findings: dict) -> VerificationReport:
        """
        Main entry point: verify all agent findings.

        Args:
            findings: Dict of agent outputs from Stage 3.

        Returns:
            VerificationReport with claim-level results and number registry.
        """
        report = VerificationReport(verified_at=self._now)

        # Step 1: Build number registry from query results (ground truth)
        self._build_registry_from_queries()
        self._build_registry_from_baseline()

        # Step 2: Extract and verify claims from each agent
        all_results = []
        for agent_name, agent_data in findings.items():
            if not isinstance(agent_data, dict) or agent_data.get("error"):
                continue
            if agent_name.startswith("_"):
                continue

            agent_findings = self._parse_agent_findings(agent_data)

            for finding in agent_findings:
                claims = self._decompose_finding(finding, agent_name)
                for claim in claims:
                    result = self._verify_claim(claim)
                    all_results.append(result)

        # Step 3: Compute report metrics
        report.results = all_results
        report.total_claims = len(all_results)
        report.verified_claims = sum(1 for r in all_results if r.status == "VERIFIED")
        report.failed_claims = sum(1 for r in all_results if r.status == "FAILED")
        report.unverifiable_claims = sum(1 for r in all_results if r.status == "UNVERIFIABLE")
        report.approximate_claims = sum(1 for r in all_results if r.status == "APPROXIMATE")
        report.verification_rate = (
            report.verified_claims / max(report.total_claims, 1)
        )
        report.number_registry = dict(self._registry)

        # Step 4: Cross-validation checks
        report.issues = self._cross_validate()

        logger.info(
            "Verification complete",
            total=report.total_claims,
            verified=report.verified_claims,
            failed=report.failed_claims,
            rate=f"{report.verification_rate:.0%}",
            issues=len(report.issues),
        )

        return report

    # ── REGISTRY BUILDING ──────────────────────────────────────────────

    def _build_registry_from_queries(self) -> None:
        """
        Build the number registry from actual query results.

        These are the ground-truth values that narrators can cite.
        """
        results = self.query_results.get("results", {})

        # total_revenue_summary
        if "total_revenue_summary" in results:
            rows = results["total_revenue_summary"].get("rows", [])
            if rows:
                r = rows[0]
                self._register("total_revenue", r.get("total_revenue"),
                               "total_revenue_summary", "Total sales revenue for period")
                self._register("num_invoices", r.get("num_invoices"),
                               "total_revenue_summary", "Invoice count for period")
                self._register("avg_invoice", r.get("avg_invoice"),
                               "total_revenue_summary", "Average invoice amount")
                self._register("min_invoice", r.get("min_invoice"),
                               "total_revenue_summary", "Minimum invoice amount")
                self._register("max_invoice", r.get("max_invoice"),
                               "total_revenue_summary", "Maximum invoice amount")
                self._register("distinct_customers", r.get("distinct_customers"),
                               "total_revenue_summary", "Distinct customers in period")

        # ar_outstanding_actual
        if "ar_outstanding_actual" in results:
            rows = results["ar_outstanding_actual"].get("rows", [])
            if rows:
                r = rows[0]
                self._register("total_outstanding_ar", r.get("total_outstanding"),
                               "ar_outstanding_actual", "Total outstanding AR")
                self._register("overdue_ar", r.get("overdue_amount"),
                               "ar_outstanding_actual", "Overdue AR amount")
                self._register("customers_with_debt", r.get("customers_with_debt"),
                               "ar_outstanding_actual", "Customers with outstanding debt")

        # aging_analysis
        if "aging_analysis" in results:
            rows = results["aging_analysis"].get("rows", [])
            for row in rows:
                tramo = row.get("tramo", "unknown")
                amount = row.get("total_amount")
                if amount is not None:
                    self._register(f"aging_{tramo}", amount,
                                   "aging_analysis", f"Aging bucket: {tramo}")

        # customer_concentration
        if "customer_concentration" in results:
            rows = results["customer_concentration"].get("rows", [])
            for i, row in enumerate(rows[:10]):
                name = row.get("customer_name", f"customer_{i}")
                revenue = row.get("total_revenue")
                pct = row.get("pct_revenue")
                if revenue is not None:
                    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', str(name).lower())[:30]
                    self._register(f"customer_revenue_{safe_name}", revenue,
                                   "customer_concentration",
                                   f"Revenue for {name}")
                    if pct is not None:
                        self._register(f"customer_pct_{safe_name}", pct,
                                       "customer_concentration",
                                       f"Revenue % for {name}")

        # data_freshness
        if "data_freshness" in results:
            rows = results["data_freshness"].get("rows", [])
            if rows:
                r = rows[0]
                self._register("data_freshness_days", r.get("days_since_latest"),
                               "data_freshness", "Days since latest record")

    def _build_registry_from_baseline(self) -> None:
        """Register baseline values that aren't already from queries."""
        for key in ("total_revenue", "num_invoices", "avg_invoice",
                    "distinct_customers", "total_outstanding_ar", "overdue_ar",
                    "customers_with_debt", "data_freshness_days"):
            if key not in self._registry and self.baseline.get(key) is not None:
                self._register(
                    key, self.baseline[key],
                    "baseline", f"From frozen baseline: {key}",
                    confidence="computed",
                )

    # Dimension mapping for known registry labels
    _DIMENSION_MAP: dict[str, str] = {
        "total_revenue": Dimension.EUR,
        "avg_invoice": Dimension.EUR,
        "min_invoice": Dimension.EUR,
        "max_invoice": Dimension.EUR,
        "total_outstanding_ar": Dimension.EUR,
        "overdue_ar": Dimension.EUR,
        "num_invoices": Dimension.COUNT,
        "distinct_customers": Dimension.COUNT,
        "customers_with_debt": Dimension.COUNT,
        "data_freshness_days": Dimension.DAYS,
    }

    def _register(self, label: str, value: Any, source_query: str,
                  description: str, confidence: str = "measured",
                  dimension: str | None = None) -> None:
        """Add a value to the number registry."""
        if value is None:
            return
        try:
            float_val = float(value)
        except (TypeError, ValueError):
            return

        # Auto-detect dimension from label if not explicitly provided
        if dimension is None:
            if label in self._DIMENSION_MAP:
                dimension = self._DIMENSION_MAP[label]
            elif label.startswith("customer_pct_"):
                dimension = Dimension.PERCENT
            else:
                dimension = Dimension.UNKNOWN

        self._registry[label] = NumberRegistryEntry(
            label=label,
            value=float_val,
            source_query=source_query,
            source_description=description,
            confidence=confidence,
            verified_at=self._now,
            dimension=dimension,
        )

    # ── CLAIM EXTRACTION ───────────────────────────────────────────────

    def _parse_agent_findings(self, agent_data: dict) -> list[dict]:
        """Extract structured findings from agent output."""
        # Try structured findings first
        if isinstance(agent_data.get("findings"), list):
            return agent_data["findings"]

        # Parse from text output
        output = agent_data.get("output", "")
        if not isinstance(output, str):
            return []

        for candidate in re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', output):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    if any("id" in item or "headline" in item for item in parsed[:2]):
                        return parsed
            except (json.JSONDecodeError, ValueError):
                continue

        return []

    def _decompose_finding(self, finding: dict, agent_name: str) -> list[AtomicClaim]:
        """
        Decompose a finding into atomic verifiable claims.

        A finding like "Revenue is €1.6M with 3,139 invoices" becomes:
          - Claim 1: total_revenue ≈ 1,600,000
          - Claim 2: num_invoices = 3,139
        """
        claims = []
        finding_id = finding.get("id", "unknown")
        headline = finding.get("headline", "")
        evidence = finding.get("evidence", "")
        value_eur = finding.get("value_eur")
        value_confidence = finding.get("value_confidence", "unknown")

        # Extract the primary EUR value claim
        if value_eur is not None:
            claims.append(AtomicClaim(
                claim_id=f"{finding_id}_value",
                finding_id=finding_id,
                claim_text=f"EUR value: {value_eur}",
                claim_type="numeric",
                claimed_value=float(value_eur),
                claimed_unit="EUR",
                source_query=self._extract_query_ref(evidence),
            ))

        # Extract inline numbers from headline
        for match in re.finditer(
            r'[\$€]\s*([\d,]+(?:\.\d+)?)\s*(?:M\b|K\b)?', headline
        ):
            raw = match.group(1).replace(",", "")
            try:
                val = float(raw)
                # Check for M/K suffix
                suffix = headline[match.end()-1:match.end()]
                if suffix == 'M':
                    val *= 1_000_000
                elif suffix == 'K':
                    val *= 1_000

                # Don't duplicate the primary value_eur
                if value_eur is not None and abs(val - float(value_eur)) < 1:
                    continue

                claims.append(AtomicClaim(
                    claim_id=f"{finding_id}_inline_{len(claims)}",
                    finding_id=finding_id,
                    claim_text=f"Inline value: {val}",
                    claim_type="numeric",
                    claimed_value=val,
                ))
            except ValueError:
                pass

        # Extract percentage claims
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*%', headline):
            try:
                pct = float(match.group(1))
                claims.append(AtomicClaim(
                    claim_id=f"{finding_id}_pct_{len(claims)}",
                    finding_id=finding_id,
                    claim_text=f"Percentage: {pct}%",
                    claim_type="numeric",
                    claimed_value=pct,
                    claimed_unit="percent",
                ))
            except ValueError:
                pass

        # Extract count claims (e.g., "3,139 invoices", "4,854 customers")
        for match in re.finditer(r'([\d,]+)\s+(invoices?|customers?|clients?|debtors?|schedules?)', headline, re.IGNORECASE):
            try:
                count = int(match.group(1).replace(",", ""))
                entity = match.group(2).lower().rstrip("s")
                claims.append(AtomicClaim(
                    claim_id=f"{finding_id}_count_{entity}",
                    finding_id=finding_id,
                    claim_text=f"{entity} count: {count}",
                    claim_type="numeric",
                    claimed_value=float(count),
                    claimed_unit="count",
                ))
            except ValueError:
                pass

        return claims

    # ── CLAIM VERIFICATION ─────────────────────────────────────────────

    def _verify_claim(self, claim: AtomicClaim) -> VerificationResult:
        """
        Verify a single atomic claim against the number registry.

        Verification strategy:
          1. Exact match in registry (within tolerance)
          2. Derivable from registry values (e.g., ratio of two known values)
          3. Present in raw query results
          4. Mark as UNVERIFIABLE if no source found
        """
        if claim.claimed_value is None:
            return VerificationResult(
                claim_id=claim.claim_id,
                status="UNVERIFIABLE",
                evidence="No numeric value claimed",
                verified_at=self._now,
            )

        result = VerificationResult(
            claim_id=claim.claim_id,
            status="UNVERIFIABLE",  # Default, will be overwritten
            verified_at=self._now,
        )

        claimed = claim.claimed_value
        claim_unit = claim.claimed_unit

        # Strategy 1: Direct registry match
        for label, entry in self._registry.items():
            if self._values_match(claimed, entry.value, claim_unit):
                result.status = "VERIFIED"
                result.actual_value = entry.value
                result.deviation_pct = self._deviation_pct(claimed, entry.value)
                result.evidence = f"Matches registry[{label}] = {entry.value} (source: {entry.source_query})"
                result.verification_query = entry.source_query
                # Confidence: measured vs computed
                base_score = 0.95 if entry.confidence == "measured" else 0.85
                result.confidence_score = self._apply_deviation_penalty(
                    base_score, result.deviation_pct)
                return result

        # Strategy 2: Check if it's a derivable value
        derived = self._check_derived_value(claimed, claim_unit)
        if derived:
            result.status = "VERIFIED"
            result.actual_value = derived["value"]
            result.deviation_pct = self._deviation_pct(claimed, derived["value"])
            result.evidence = f"Derived: {derived['derivation']}"
            result.confidence_score = self._apply_deviation_penalty(
                0.60, result.deviation_pct)
            return result

        # Strategy 3: Search raw query results
        raw_match = self._search_raw_results(claimed, claim_unit)
        if raw_match:
            result.status = "VERIFIED"
            result.actual_value = raw_match["value"]
            result.deviation_pct = self._deviation_pct(claimed, raw_match["value"])
            result.evidence = f"Found in {raw_match['query']} row {raw_match.get('row', '?')}"
            result.verification_query = raw_match["query"]
            result.confidence_score = self._apply_deviation_penalty(
                0.75, result.deviation_pct)
            return result

        # Strategy 4: ACTIVE RE-QUERY — generate and execute a verification SQL
        if self.connection_string and self.entity_map:
            active_result = self._active_requery(claim)
            if active_result is not None:
                if active_result.status == "VERIFIED":
                    active_result.confidence_score = self._apply_deviation_penalty(
                        0.90, active_result.deviation_pct)
                elif active_result.status == "APPROXIMATE":
                    dev = abs(active_result.deviation_pct or 0)
                    base = 0.50 if dev < 2.0 else 0.30
                    active_result.confidence_score = self._apply_deviation_penalty(
                        base, active_result.deviation_pct)
                else:
                    active_result.confidence_score = 0.0
                return active_result

        # Strategy 5: Approximate match (within 5%)
        for label, entry in self._registry.items():
            dev = self._deviation_pct(claimed, entry.value)
            if dev is not None and abs(dev) < 5.0:
                result.status = "APPROXIMATE"
                result.actual_value = entry.value
                result.deviation_pct = dev
                result.evidence = f"Approximate match to registry[{label}] = {entry.value} (deviation: {dev:.1f}%)"
                base = 0.50 if abs(dev) < 2.0 else 0.30
                result.confidence_score = self._apply_deviation_penalty(
                    base, dev)
                return result

        # No match found
        result.status = "UNVERIFIABLE"
        result.evidence = f"Value {claimed} not found in any query result or registry"
        result.confidence_score = 0.0
        return result

    def _apply_deviation_penalty(self, base_score: float, deviation_pct: float | None) -> float:
        """Apply deviation penalty to a confidence score and clamp to [0.0, 1.0]."""
        if deviation_pct is not None:
            base_score -= abs(deviation_pct) * 0.02
        return max(0.0, min(1.0, base_score))

    def _values_match(self, claimed: float, actual: float, claim_unit: str = "EUR") -> bool:
        """Check if two values match within tolerance (claim-type-aware)."""
        if actual == 0:
            return claimed == 0
        if claim_unit == "count":
            # Counts must match exactly (after rounding to int)
            return round(claimed) == round(actual)
        elif claim_unit == "percent":
            # Percentages: 2% absolute tolerance
            return abs(claimed - actual) <= 2.0
        else:
            # EUR/other: use relative tolerance based on magnitude
            deviation = abs(claimed - actual) / abs(actual) * 100
            if abs(actual) > 1_000_000:
                return deviation <= 0.5
            elif abs(actual) > 10_000:
                return deviation <= 0.1
            else:
                return deviation <= 0.01

    def _deviation_pct(self, claimed: float, actual: float) -> float | None:
        """Compute percentage deviation."""
        if actual == 0:
            return None if claimed == 0 else 100.0
        return (claimed - actual) / abs(actual) * 100

    def _check_derived_value(self, claimed: float, claim_unit: str = "EUR") -> dict | None:
        """Check if the claimed value is derivable from registry values."""
        registry_values = list(self._registry.items())

        # Check ratios (e.g., avg = total / count)
        for i, (label_a, entry_a) in enumerate(registry_values):
            for j, (label_b, entry_b) in enumerate(registry_values):
                if i == j or entry_b.value == 0:
                    continue

                # Division
                ratio = entry_a.value / entry_b.value
                if self._values_match(claimed, ratio, claim_unit):
                    return {
                        "value": ratio,
                        "derivation": f"{label_a} / {label_b} = {ratio:.2f}",
                    }

                # Multiplication
                product = entry_a.value * entry_b.value
                if abs(product) > 0 and self._values_match(claimed, product, claim_unit):
                    return {
                        "value": product,
                        "derivation": f"{label_a} × {label_b} = {product:.2f}",
                    }

                # Subtraction (e.g., net = gross - credits)
                diff = entry_a.value - entry_b.value
                if abs(diff) > 0 and self._values_match(claimed, diff, claim_unit):
                    return {
                        "value": diff,
                        "derivation": f"{label_a} - {label_b} = {diff:.2f}",
                    }

        # Check percentage of total_revenue
        total_rev = self._registry.get("total_revenue")
        if total_rev and total_rev.value > 0:
            pct_of_rev = (claimed / total_rev.value) * 100
            for label, entry in registry_values:
                if entry.unit == "percent" or "pct" in label:
                    if self._values_match(pct_of_rev, entry.value, claim_unit):
                        return {
                            "value": claimed,
                            "derivation": f"{pct_of_rev:.2f}% of total_revenue matches {label}",
                        }

        return None

    def _search_raw_results(self, claimed: float, claim_unit: str = "EUR") -> dict | None:
        """Search for the claimed value in raw query result rows."""
        for query_id, result in self.query_results.get("results", {}).items():
            for row_idx, row in enumerate(result.get("rows", [])):
                for col, val in row.items():
                    try:
                        float_val = float(val)
                        if self._values_match(claimed, float_val, claim_unit):
                            return {
                                "value": float_val,
                                "query": query_id,
                                "row": row_idx,
                                "column": col,
                            }
                    except (TypeError, ValueError):
                        continue
        return None

    def _extract_query_ref(self, evidence: str) -> str | None:
        """Extract a query ID reference from evidence text."""
        # Look for known query IDs
        known_queries = list(self.query_results.get("results", {}).keys())
        for qid in known_queries:
            if qid in evidence:
                return qid
        return None

    # ── ACTIVE RE-QUERY VERIFICATION (CRITIC pattern) ────────────────

    def _active_requery(self, claim: AtomicClaim) -> VerificationResult | None:
        """
        Attempt active re-query verification for a claim.

        Generates a SQL query from the KG/entity_map, executes it,
        and compares the result to the claimed value.

        Returns a VerificationResult if the re-query succeeds (match or fail),
        or None if we cannot generate/execute a verification query.
        """
        vq = self._generate_verification_query(claim, self.entity_map)
        if vq is None:
            return None

        exec_result = self._execute_verification_query(
            vq["sql"], self.connection_string, timeout=5,
            params=vq.get("params"),
        )
        if exec_result.get("error"):
            logger.warning(
                "Active re-query failed",
                claim_id=claim.claim_id,
                error=exec_result["error"],
            )
            return None

        rows = exec_result.get("rows", [])
        if not rows:
            return None

        # Extract the result value from the first row, first column
        first_row = rows[0]
        if not first_row:
            return None

        actual_value = None
        for col_val in first_row.values():
            try:
                actual_value = float(col_val)
                break
            except (TypeError, ValueError):
                continue

        if actual_value is None:
            return None

        claimed = claim.claimed_value
        result = VerificationResult(
            claim_id=claim.claim_id,
            status="UNVERIFIABLE",  # Will be overwritten below
            verification_query=vq["sql"],
            verified_at=self._now,
        )

        if self._values_match(claimed, actual_value, claim.claimed_unit):
            result.status = "VERIFIED"
            result.actual_value = actual_value
            result.deviation_pct = self._deviation_pct(claimed, actual_value)
            result.evidence = (
                f"Active re-query confirmed: {vq['description']} → {actual_value}"
            )
            # Register the verified value
            label = f"active_{claim.claim_id}"
            self._register(label, actual_value, vq["sql"],
                           vq["description"], confidence="measured")
            return result

        dev = self._deviation_pct(claimed, actual_value)
        if dev is not None and abs(dev) < 5.0:
            result.status = "APPROXIMATE"
            result.actual_value = actual_value
            result.deviation_pct = dev
            result.evidence = (
                f"Active re-query approximate: {vq['description']} → "
                f"{actual_value} (deviation: {dev:.1f}%)"
            )
            return result

        result.status = "FAILED"
        result.actual_value = actual_value
        result.deviation_pct = dev
        result.evidence = (
            f"Active re-query contradicts claim: {vq['description']} → "
            f"{actual_value} (claimed: {claimed}, deviation: {dev:.1f}%)"
        )
        return result

    def _generate_verification_query(
        self, claim: AtomicClaim, entity_map: dict | None,
    ) -> dict | None:
        """
        Generate a SQL query to verify an atomic claim using the KG/entity_map.

        Strategy is data-driven — table names, column names, and filters
        all come from the entity_map, never hardcoded.

        Returns:
            {"sql": str, "expected_type": str, "description": str} or None
        """
        if not entity_map:
            return None

        entities = entity_map.get("entities", {})
        if not entities:
            return None

        claimed = claim.claimed_value
        if claimed is None:
            return None

        # Identify the best entity to query based on claim type
        # Look for TRANSACTIONAL entities with amount columns (revenue claims)
        # or entities with countable PKs (count claims)
        claim_text_lower = claim.claim_text.lower()

        # Determine claim intent
        is_count = claim.claimed_unit == "count" or "count" in claim_text_lower
        is_revenue = (
            claim.claimed_unit == "EUR"
            or "revenue" in claim_text_lower
            or "total" in claim_text_lower
            or "amount" in claim_text_lower
            or "value" in claim_text_lower
        )

        for entity_name, entity in entities.items():
            table = entity.get("table", "")
            etype = entity.get("type", "")
            key_cols = entity.get("key_columns", {})
            base_filter = entity.get("base_filter", "")

            if not table or not _is_safe_identifier(table):
                continue

            # Build WHERE clause from base_filter
            where_parts = []
            if base_filter:
                # Qualify filter columns with table name
                if self.kg:
                    where_parts = self.kg.get_required_filters(table)
                else:
                    # Fallback: use base_filter directly
                    for part in re.split(r'\bAND\b', base_filter, flags=re.IGNORECASE):
                        part = part.strip()
                        if part:
                            if "." not in part.split("=")[0].split("<")[0].split(">")[0]:
                                part = f"{table}.{part}"
                            where_parts.append(part)

            where_clause = " AND ".join(where_parts) if where_parts else "1=1"

            # Strategy A: Count claims — find entity with a PK to COUNT
            if is_count and etype == "TRANSACTIONAL":
                pk_col = key_cols.get("pk") or key_cols.get("customer_pk")
                if not pk_col or not _is_safe_identifier(pk_col):
                    continue

                # Check if claim is about customers specifically
                if "customer" in claim_text_lower or "client" in claim_text_lower:
                    customer_fk = key_cols.get("customer_fk")
                    if customer_fk and _is_safe_identifier(customer_fk):
                        sql = (
                            f"SELECT COUNT(DISTINCT {table}.{customer_fk}) AS cnt "
                            f"FROM {table} WHERE {where_clause}"
                        )
                        return {
                            "sql": sql,
                            "expected_type": "count",
                            "description": f"Count distinct customers in {entity_name}",
                        }

                # Generic count
                sql = (
                    f"SELECT COUNT({table}.{pk_col}) AS cnt "
                    f"FROM {table} WHERE {where_clause}"
                )
                return {
                    "sql": sql,
                    "expected_type": "count",
                    "description": f"Count records in {entity_name}",
                }

            # Strategy B: Revenue/amount claims — SUM the amount column
            if is_revenue and etype == "TRANSACTIONAL":
                amount_col = (
                    key_cols.get("amount_col")
                    or key_cols.get("grand_total")
                    or key_cols.get("amount")
                )
                if not amount_col or not _is_safe_identifier(amount_col):
                    continue

                # Check if claim is about a specific customer
                customer_name_match = re.search(
                    r'(?:customer|client|for)\s+["\']?([A-Za-z][\w\s&.\'-]+)',
                    claim.claim_text, re.IGNORECASE,
                )
                if customer_name_match and key_cols.get("customer_fk"):
                    # Need JOIN to customer table to filter by name
                    customer_name = customer_name_match.group(1).strip()
                    # Find customer entity via KG or entity_map
                    customer_table, customer_pk, customer_name_col = (
                        self._find_customer_entity(entities)
                    )
                    if customer_table and customer_pk and customer_name_col:
                        customer_fk_col = key_cols["customer_fk"]
                        # Validate all identifiers before SQL interpolation
                        ids_to_check = [
                            customer_table, customer_pk, customer_name_col,
                            table, customer_fk_col, amount_col,
                        ]
                        if not all(_is_safe_identifier(n) for n in ids_to_check):
                            continue
                        join_clause = (
                            f"JOIN {customer_table} ON "
                            f"{table}.{customer_fk_col} = {customer_table}.{customer_pk}"
                        )
                        # Use parameterized query for customer name to prevent SQL injection
                        sql = (
                            f"SELECT SUM({table}.{amount_col}) AS total "
                            f"FROM {table} {join_clause} "
                            f"WHERE {where_clause} AND "
                            f"{customer_table}.{customer_name_col} ILIKE :cust_name_pattern"
                        )
                        return {
                            "sql": sql,
                            "params": {"cust_name_pattern": f"%{customer_name}%"},
                            "expected_type": "sum",
                            "description": (
                                f"Total {amount_col} for customer '{customer_name}' "
                                f"in {entity_name}"
                            ),
                        }

                # General SUM
                sql = (
                    f"SELECT SUM({table}.{amount_col}) AS total "
                    f"FROM {table} WHERE {where_clause}"
                )
                return {
                    "sql": sql,
                    "expected_type": "sum",
                    "description": f"Total {amount_col} from {entity_name}",
                }

        return None

    def _find_customer_entity(
        self, entities: dict,
    ) -> tuple[str | None, str | None, str | None]:
        """
        Find the customer table, PK, and name column from the entity_map.

        Returns (table, pk_column, name_column) or (None, None, None).
        """
        for entity_name, entity in entities.items():
            etype = entity.get("type", "")
            if etype in ("MASTER", "DIMENSION") or "customer" in entity_name.lower():
                table = entity.get("table", "")
                key_cols = entity.get("key_columns", {})
                pk = key_cols.get("pk") or key_cols.get("customer_pk")
                name_col = key_cols.get("name") or key_cols.get("customer_name")
                if table and pk and name_col:
                    return table, pk, name_col
        return None, None, None

    def _execute_verification_query(
        self, sql: str, connection_string: str, timeout: int = 5,
        params: dict | None = None,
    ) -> dict:
        """
        Execute a read-only verification query with safety guards.

        Safety:
          - Blocks all write operations (INSERT, UPDATE, DELETE, DROP, etc.)
          - Limits results to 100 rows
          - Timeout after `timeout` seconds
          - Uses a separate thread to enforce timeout

        Returns:
            {"rows": [...], "row_count": int} or {"error": str}
        """
        # Safety: block write operations
        sql_upper = sql.upper().strip()
        for keyword in self.FORBIDDEN_SQL_KEYWORDS:
            if sql_upper.startswith(keyword):
                return {"error": f"Write operation blocked: {keyword}"}
            # Also check for write keywords anywhere (e.g., subquery injection)
            if re.search(rf'\b{keyword}\b', sql_upper):
                return {"error": f"Write operation blocked: {keyword} found in query"}

        # Ensure it starts with SELECT or WITH
        if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
            return {"error": f"Only SELECT/WITH queries allowed, got: {sql_upper[:20]}"}

        max_rows = 100
        result_container: dict = {}
        error_container: dict = {}

        query_params = params or {}

        def _run_query():
            try:
                from sqlalchemy import create_engine, text as sa_text
                engine = create_engine(connection_string)
                with engine.connect() as conn:
                    result = conn.execute(sa_text(sql), query_params)
                    columns = list(result.keys())
                    rows = []
                    for i, row in enumerate(result):
                        if i >= max_rows:
                            break
                        rows.append(dict(zip(columns, row)))
                    result_container["rows"] = rows
                    result_container["row_count"] = len(rows)
                engine.dispose()
            except Exception as exc:
                error_container["error"] = str(exc)

        thread = threading.Thread(target=_run_query, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            return {"error": f"Query timed out after {timeout}s"}

        if error_container:
            return error_container

        return result_container

    # ── CROSS-VALIDATION ───────────────────────────────────────────────

    def _cross_validate(self) -> list[dict]:
        """
        Run cross-validation checks on the registry.

        Catches inconsistencies like:
          - customers_with_debt > distinct_customers * 4 (suspicious)
          - AR > total_revenue * 10 (implausible)
          - avg_invoice != total_revenue / num_invoices (math error)
        """
        issues = []

        # Check: customers_with_debt vs distinct_customers
        cwd = self._registry.get("customers_with_debt")
        dc = self._registry.get("distinct_customers")
        if cwd and dc and dc.value > 0:
            ratio = cwd.value / dc.value
            if ratio > 3.0:
                issues.append({
                    "severity": "critical",
                    "description": (
                        f"customers_with_debt ({cwd.value:,.0f}) is {ratio:.1f}x "
                        f"distinct_customers ({dc.value:,.0f}). "
                        "Possible causes: AR query includes AP (purchase) schedules, "
                        "or includes schedules without invoices (order-only)."
                    ),
                    "check": "debt_customer_ratio",
                    "values": {"customers_with_debt": cwd.value, "distinct_customers": dc.value},
                })

        # Check: AR vs revenue sanity
        ar = self._registry.get("total_outstanding_ar")
        rev = self._registry.get("total_revenue")
        if ar and rev and rev.value > 0:
            ratio = ar.value / rev.value
            if ratio > 5.0:
                issues.append({
                    "severity": "warning",
                    "description": (
                        f"Outstanding AR ({ar.value:,.0f}) is {ratio:.1f}x "
                        f"period revenue ({rev.value:,.0f}). "
                        "This may indicate multi-year accumulation, "
                        "or the AR query may include non-sales items."
                    ),
                    "check": "ar_revenue_ratio",
                    "values": {"ar": ar.value, "revenue": rev.value},
                })

        # Check: avg_invoice mathematical consistency
        avg = self._registry.get("avg_invoice")
        total = self._registry.get("total_revenue")
        count = self._registry.get("num_invoices")
        if avg and total and count and count.value > 0:
            expected_avg = total.value / count.value
            if not self._values_match(avg.value, expected_avg):
                dev = self._deviation_pct(avg.value, expected_avg)
                issues.append({
                    "severity": "warning",
                    "description": (
                        f"avg_invoice ({avg.value:,.2f}) != "
                        f"total_revenue / num_invoices ({expected_avg:,.2f}). "
                        f"Deviation: {dev:.1f}%"
                    ),
                    "check": "avg_invoice_consistency",
                })

        # Check: overdue_ar <= total_ar
        overdue = self._registry.get("overdue_ar")
        total_ar = self._registry.get("total_outstanding_ar")
        if overdue and total_ar and overdue.value > total_ar.value * 1.01:
            issues.append({
                "severity": "critical",
                "description": (
                    f"Overdue AR ({overdue.value:,.0f}) > "
                    f"Total AR ({total_ar.value:,.0f}). "
                    "This is mathematically impossible — check the AR query."
                ),
                "check": "overdue_exceeds_total",
            })

        return issues
