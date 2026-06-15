"""
Agent-claims grounding instrument (VAL-192 N5).

Measures the UNCITED-CLAIMS RATE over the atomic claims the swarm agents make:
every claim should trace to a citation (the query / registry entry that resolved
it) or be a declared inference. This is the claim-level counterpart to the N1
narrator-grounding instrument (which measures NUMBERS in narrator text).

Operational buckets over a ``VerificationReport``'s per-claim ``results``:

  - declared     — the agent marked the claim as NOT measured: via the typed
                   ``value_confidence`` of its finding (``estimated``/``inferred``,
                   higher fidelity) OR the ``[ESTIMADO]/[INFERIDO]/~`` text marker
                   N1 uses. Out of the denominator — this is the "or marked as
                   inference" half of the N5 rule.
  - cited        — status VERIFIED/APPROXIMATE with a non-null
                   ``verification_query`` (resolved lineage to a query/registry).
  - failed       — status FAILED (had lineage but the value was contradicted).
  - unresolvable — status UNVERIFIABLE but a query WAS attempted (a data-coverage
                   gap, not an authoring failure).
  - uncited      — status UNVERIFIABLE and NO query attempted — the authoring
                   failure N5 ultimately enforces against.

  ``uncited_rate = uncited / (total - declared)``  (mirrors N1's verifiable denom)

Pure + post-hoc: reads an existing ``VerificationReport``, runs no agent or DB.
Numeric-claim granularity (matches ``_decompose_finding``); prose assertions are
a documented blind-spot, exactly as N1 declared for action-plan prose.

Refs: VAL-192 (N5)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Reuse N1's declared-estimate protocol markers verbatim (single source of truth).
from valinor.quality.narrator_metrics import _DECLARED_AFTER_RE

_CITED_STATUSES = ("VERIFIED", "APPROXIMATE")
# The agent's own typed "not measured" markers (schemas.agent_outputs.ValueConfidence).
_INFERENCE_CONFIDENCE = ("estimated", "inferred")


def _value_confidence_by_finding(findings) -> dict:
    """Map finding_id → value_confidence from the swarm findings dict."""
    out: dict = {}
    if not isinstance(findings, dict):
        return out
    for agent, data in findings.items():
        if str(agent).startswith("_") or not isinstance(data, dict):
            continue
        for f in data.get("findings", []) or []:
            if isinstance(f, dict) and f.get("id") and f.get("value_confidence") is not None:
                out[str(f["id"])] = str(f["value_confidence"]).lower()
    return out


def _get(obj: Any, key: str, default=None):
    """Field access that works for both dataclasses and plain dicts (the report
    is dataclasses in-memory, dicts once serialized to disk)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _claim_is_declared(text: str) -> bool:
    """True if the claim text marks itself an estimate/inference (~ or [ESTIMADO])."""
    if not text:
        return False
    if "~" in text:
        return True
    return bool(_DECLARED_AFTER_RE.search(text))


@dataclass
class AgentClaimsAudit:
    """Citation coverage over the atomic claims of one verification run."""
    total_claims: int = 0
    cited: int = 0
    failed: int = 0
    unresolvable: int = 0
    uncited: int = 0
    declared_inference: int = 0

    @property
    def verifiable(self) -> int:
        """Denominator: claims that should carry a citation (declared excluded)."""
        return max(0, self.total_claims - self.declared_inference)

    @property
    def uncited_rate(self) -> float:
        return self.uncited / self.verifiable if self.verifiable else 0.0

    @property
    def cited_rate(self) -> float:
        return self.cited / self.verifiable if self.verifiable else 0.0

    def to_dict(self) -> dict:
        return {
            "total_claims": self.total_claims,
            "cited": self.cited,
            "failed": self.failed,
            "unresolvable": self.unresolvable,
            "uncited": self.uncited,
            "declared_inference": self.declared_inference,
            "verifiable": self.verifiable,
            "uncited_rate": round(self.uncited_rate, 4),
            "cited_rate": round(self.cited_rate, 4),
        }


def score_agent_claims(results, claims=None, findings=None) -> AgentClaimsAudit:
    """Compute the uncited-claims audit from a VerificationReport's per-claim results.

    results:  list of VerificationResult (objects or dicts) — needs ``status``,
              ``verification_query`` and ``claim_id``.
    claims:   optional list of AtomicClaim (objects or dicts) — needs ``claim_id``,
              ``claim_text`` and ``finding_id`` — used to detect declared inferences
              and to join claims to their finding's ``value_confidence``.
    findings: optional swarm findings dict ({agent: {findings: [{id,
              value_confidence}]}}) — a claim whose finding is ``estimated``/
              ``inferred`` is a declared inference (the higher-fidelity marker).
    """
    text_by_id: dict = {}
    fid_by_id: dict = {}
    for c in (claims or []):
        cid = _get(c, "claim_id")
        if cid is not None:
            text_by_id[cid] = _get(c, "claim_text", "") or ""
            fid_by_id[cid] = _get(c, "finding_id")
    vc_by_fid = _value_confidence_by_finding(findings)

    audit = AgentClaimsAudit()
    for r in results or []:
        audit.total_claims += 1
        status = (_get(r, "status", "") or "").upper()
        vquery = _get(r, "verification_query")
        cid = _get(r, "claim_id")

        # Declared inference: the agent flagged it as not-measured, via the typed
        # value_confidence of its finding OR the [ESTIMADO]/~ text marker.
        vc = vc_by_fid.get(fid_by_id.get(cid))
        if vc in _INFERENCE_CONFIDENCE or _claim_is_declared(text_by_id.get(cid, "")):
            audit.declared_inference += 1
            continue

        if status in _CITED_STATUSES and vquery is not None:
            audit.cited += 1
        elif status == "FAILED":
            audit.failed += 1
        elif status == "UNVERIFIABLE" and vquery is not None:
            audit.unresolvable += 1
        else:
            # UNVERIFIABLE without a query, or the degenerate case of a
            # VERIFIED/APPROXIMATE claim with no recorded citation: both mean
            # "no resolvable lineage" under the strict definition.
            audit.uncited += 1
    return audit
