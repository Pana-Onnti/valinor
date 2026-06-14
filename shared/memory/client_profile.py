"""
ClientProfile — persistent per-client state that accumulates across runs.
Stored in PostgreSQL (client_profiles table) or local file fallback.

Decomposed into typed sub-objects (VAL-80) while maintaining full backward
compatibility: to_dict() produces the same flat dict, from_dict() accepts it,
and attribute access like `profile.run_count` still works via properties.
"""
from __future__ import annotations
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class FindingRecord:
    """A finding seen in at least one run."""
    id: str
    title: str
    severity: str          # CRITICAL | HIGH | MEDIUM | LOW | INFO
    agent: str             # analyst | sentinel | hunter
    first_seen: str        # ISO timestamp
    last_seen: str         # ISO timestamp
    runs_open: int = 1     # consecutive runs where it appeared


@dataclass
class KPIDataPoint:
    """One KPI measurement at one point in time."""
    period: str
    label: str
    value: str             # raw string from report
    numeric_value: Optional[float]
    run_date: str          # ISO timestamp


@dataclass
class ClientRefinement:
    """
    Output of the Auto-Refinement Engine.
    Consumed on the NEXT run to guide agents.
    """
    table_weights: Dict[str, float] = field(default_factory=dict)
    query_hints: List[str] = field(default_factory=list)
    focus_areas: List[str] = field(default_factory=list)
    suppress_ids: List[str] = field(default_factory=list)
    context_block: str = ""   # Pre-formatted string injected into agent prompts
    generated_at: str = ""

    def to_prompt_block(self) -> str:
        """Return the pre-formatted context block for injection into agent prompts."""
        if self.context_block:
            return self.context_block
        return ""


@dataclass
class PendingRefinement:
    """A RefinementAgent proposal awaiting human review (VAL-192 N4 write-path).

    A learning is PROPOSED here with full provenance and only becomes active
    (`ClientProfile.refinement`) on EXPLICIT approval — never written direct.
    This cuts the compounding-garbage loop where a wrong learning survives,
    auto-escalates, and gets cited with authority on later runs.
    """
    proposal_id: str
    refinement: Dict                        # ClientRefinement payload (the proposal)
    run_id: str                             # originating run (provenance)
    client_tag: str                         # which client (provenance)
    generated_at: str                       # ISO timestamp (provenance)
    source_findings_ids: List[str] = field(default_factory=list)
    confidence: Optional[float] = None      # run-level, from ProvenanceRegistry
    confidence_label: str = ""              # CONFIRMED | PROVISIONAL | UNVERIFIED | BLOCKED
    status: str = "pending"                 # pending | approved | rejected
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_reason: str = ""


@dataclass
class PendingFindingEscalation:
    """A proposed severity escalation awaiting review (VAL-192 N4, seam A).

    Auto-escalation — a finding bumped a severity level purely for surviving 5+
    runs — is the seam-A write that "gains authority without basis": no new
    evidence, no human confirmation, yet it can climb a hallucinated finding to
    CRITICAL. Under review it is PROPOSED here with provenance and only applied
    to the live record on approval.
    """
    proposal_id: str
    finding_id: str
    from_severity: str
    to_severity: str
    runs_open: int
    run_id: str                             # provenance
    client_tag: str                         # provenance
    generated_at: str                       # provenance
    confidence: Optional[float] = None
    confidence_label: str = ""
    status: str = "pending"                 # pending | approved | rejected
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    review_reason: str = ""


# ── Sub-objects (VAL-80) ──────────────────────────────────────────────────────


@dataclass
class EntityCache:
    """Cartographer entity-map cache."""
    entity_map_cache: Optional[Dict] = None
    entity_map_updated_at: Optional[str] = None   # ISO timestamp


@dataclass
class FindingTracker:
    """Tracking of known, resolved, and false-positive findings."""
    known_findings: Dict[str, Any] = field(default_factory=dict)   # id → FindingRecord dict
    resolved_findings: Dict[str, Any] = field(default_factory=dict)
    false_positives: List[str] = field(default_factory=list)


@dataclass
class RunStats:
    """Aggregate run statistics."""
    run_count: int = 0
    last_run_date: Optional[str] = None
    last_run_at: Optional[str] = None        # alias kept for VAL-80 spec compat
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    industry_inferred: Optional[str] = None
    currency_detected: Optional[str] = None
    run_history: List[Dict] = field(default_factory=list)  # last 20 runs summary


@dataclass
class DQHistory:
    """Data Quality history."""
    dq_history: List[Dict] = field(default_factory=list)  # last 10 DQ reports per run
    dq_scores: List[float] = field(default_factory=list)  # numeric scores per run
    dq_trend: Optional[str] = None                        # "improving" | "stable" | "declining"


@dataclass
class TableIntelligence:
    """Table focus and weight information."""
    focus_tables: List[str] = field(default_factory=list)
    table_weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class BusinessContext:
    """
    Business context injected during onboarding.
    Gives agents knowledge about the client's business before analyzing their database.
    """
    company_name: str = ""           # "Acme SRL"
    industry: str = ""               # "distribucion_mayorista"
    country: str = ""                # "AR"
    city: str = ""                   # "Córdoba, Argentina"
    erp_type: str = ""               # "gestion_pyme_argentina"
    expected_entities: List[str] = field(default_factory=list)  # ["articulos", "stock", "ventas"]
    notes: str = ""                  # Free text from Loren during onboarding


@dataclass
class AlertConfig:
    """Alert thresholds and triggered alerts."""
    alert_thresholds: List[Dict] = field(default_factory=list)
    triggered_alerts: List[Dict] = field(default_factory=list)  # last 20 triggered


# ── ClientProfile ─────────────────────────────────────────────────────────────


@dataclass
class ClientProfile:
    """
    Full persistent profile for one client.
    Loaded before each run, saved after.

    Fields are organized into typed sub-objects but remain accessible as
    flat attributes for backward compatibility (via __getattr__/__setattr__).
    """
    client_name: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # ── Sub-objects ────────────────────────────────────────────────────────────
    _entity_cache: EntityCache = field(default_factory=EntityCache)
    _finding_tracker: FindingTracker = field(default_factory=FindingTracker)
    _run_stats: RunStats = field(default_factory=RunStats)
    _dq_history: DQHistory = field(default_factory=DQHistory)
    _table_intelligence: TableIntelligence = field(default_factory=TableIntelligence)
    _alert_config: AlertConfig = field(default_factory=AlertConfig)

    # ── KPI history ────────────────────────────────────────────────────────────
    baseline_history: Dict[str, List[Any]] = field(default_factory=dict)

    # ── Query intelligence ─────────────────────────────────────────────────────
    preferred_queries: List[Dict] = field(default_factory=list)

    # ── Refinement (from last RefinementAgent run) ─────────────────────────────
    refinement: Optional[Dict] = None   # ClientRefinement as dict (ACTIVE, approved)

    # ── Pending proposals awaiting human review (VAL-192 N4) ───────────────────
    pending_refinements: List[Dict] = field(default_factory=list)   # seam B (refinement)
    pending_escalations: List[Dict] = field(default_factory=list)   # seam A (severity)

    # ── Segmentation history ───────────────────────────────────────────────────
    segmentation_history: List[Dict] = field(default_factory=list)  # last 12 periods

    # ── Webhooks ───────────────────────────────────────────────────────────────
    webhooks: List[Dict] = field(default_factory=list)  # registered webhook URLs

    # ── Vertical schedule config (VAL-130 L2) ─────────────────────────────────
    # list of dicts matching worker.scheduler.VerticalSchedule.to_dict():
    #   {"vertical": "inventory", "cron": "0 6 * * 1-5", "mode": "run",
    #    "enabled": True, "channels": ["email", "whatsapp"],
    #    "recipients": ["ops@example.com", "+5491100000000"]}
    schedule_config: List[Dict] = field(default_factory=list)

    # ── Business context (onboarding) ────────────────────────────────────────
    business_context: Optional[BusinessContext] = None

    # ── Arbitrary metadata ─────────────────────────────────────────────────────
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── Delegated field registry ───────────────────────────────────────────────
    # Maps flat field names → (sub-object attr name, field name within sub-object)
    _DELEGATED_FIELDS: dict = field(init=False, repr=False, default=None)

    # Maps sub-object attr → (sub-object class, set of field names)
    _SUB_MAPPINGS: dict = field(init=False, repr=False, default=None)

    def __post_init__(self):
        object.__setattr__(self, '_DELEGATED_FIELDS', {
            # EntityCache
            'entity_map_cache': '_entity_cache',
            'entity_map_updated_at': '_entity_cache',
            # FindingTracker
            'known_findings': '_finding_tracker',
            'resolved_findings': '_finding_tracker',
            'false_positives': '_finding_tracker',
            # RunStats
            'run_count': '_run_stats',
            'last_run_date': '_run_stats',
            'last_run_at': '_run_stats',
            'total_tokens_used': '_run_stats',
            'total_cost_usd': '_run_stats',
            'industry_inferred': '_run_stats',
            'currency_detected': '_run_stats',
            'run_history': '_run_stats',
            # DQHistory
            'dq_history': '_dq_history',
            'dq_scores': '_dq_history',
            'dq_trend': '_dq_history',
            # TableIntelligence
            'focus_tables': '_table_intelligence',
            'table_weights': '_table_intelligence',
            # AlertConfig
            'alert_thresholds': '_alert_config',
            'triggered_alerts': '_alert_config',
        })
        object.__setattr__(self, '_SUB_MAPPINGS', {
            '_entity_cache': (EntityCache, {'entity_map_cache', 'entity_map_updated_at'}),
            '_finding_tracker': (FindingTracker, {'known_findings', 'resolved_findings', 'false_positives'}),
            '_run_stats': (RunStats, {'run_count', 'last_run_date', 'last_run_at', 'total_tokens_used', 'total_cost_usd', 'industry_inferred', 'currency_detected', 'run_history'}),
            '_dq_history': (DQHistory, {'dq_history', 'dq_scores', 'dq_trend'}),
            '_table_intelligence': (TableIntelligence, {'focus_tables', 'table_weights'}),
            '_alert_config': (AlertConfig, {'alert_thresholds', 'triggered_alerts'}),
        })
        # N4: guarantee the pending-review queues are never None (a corrupt or
        # legacy dict could carry an explicit null that would override the
        # default_factory and crash every write-path method).
        if self.pending_refinements is None:
            object.__setattr__(self, 'pending_refinements', [])
        if self.pending_escalations is None:
            object.__setattr__(self, 'pending_escalations', [])

    def __getattr__(self, name: str):
        # __post_init__ hasn't run yet or _DELEGATED_FIELDS not set
        delegated = object.__getattribute__(self, '__dict__').get('_DELEGATED_FIELDS')
        if delegated and name in delegated:
            sub_obj = object.__getattribute__(self, delegated[name])
            return getattr(sub_obj, name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value):
        delegated = object.__getattribute__(self, '__dict__').get('_DELEGATED_FIELDS')
        if delegated and name in delegated:
            sub_obj = object.__getattribute__(self, delegated[name])
            setattr(sub_obj, name, value)
            return
        object.__setattr__(self, name, value)

    def get_refinement(self) -> ClientRefinement:
        if self.refinement:
            return ClientRefinement(**self.refinement)
        return ClientRefinement()

    # ── N4 write-path: pending refinement proposals (VAL-192) ──────────────────

    def add_pending_refinement(self, pending: Dict) -> None:
        """Stage a proposal. Does NOT activate it (refinement stays untouched)."""
        self.pending_refinements.append(pending)

    def get_pending_refinements(self, status: Optional[str] = "pending") -> List[Dict]:
        """Pending proposals filtered by status (None → all)."""
        if status is None:
            return list(self.pending_refinements)
        return [p for p in self.pending_refinements if p.get("status") == status]

    def approve_pending_refinement(self, proposal_id: str,
                                   reviewed_by: str = "operator") -> Optional[Dict]:
        """Approve a pending proposal → ACTIVATE it as the refinement (replaces
        the prior active refinement; the agent proposes a COMPLETE
        ClientRefinement each run — same supersede semantics as the legacy
        auto-write). Returns the updated record, or None if not found/not pending."""
        for p in self.pending_refinements:
            if p.get("proposal_id") == proposal_id and p.get("status") == "pending":
                p["status"] = "approved"
                p["reviewed_at"] = datetime.utcnow().isoformat()
                p["reviewed_by"] = reviewed_by
                self.refinement = dict(p.get("refinement") or {})
                return p
        return None

    def reject_pending_refinement(self, proposal_id: str, reason: str = "",
                                  reviewed_by: str = "operator") -> Optional[Dict]:
        """Reject a pending proposal (archived, never merged). Returns the record
        or None if not found / not pending."""
        for p in self.pending_refinements:
            if p.get("proposal_id") == proposal_id and p.get("status") == "pending":
                p["status"] = "rejected"
                p["reviewed_at"] = datetime.utcnow().isoformat()
                p["reviewed_by"] = reviewed_by
                p["review_reason"] = reason
                return p
        return None

    # ── N4 seam A: pending finding-severity escalations (VAL-192) ──────────────

    def add_pending_escalation(self, pending: Dict) -> None:
        """Stage a proposed escalation. Does NOT change the finding's severity."""
        self.pending_escalations.append(pending)

    def get_pending_escalations(self, status: Optional[str] = "pending") -> List[Dict]:
        if status is None:
            return list(self.pending_escalations)
        return [p for p in self.pending_escalations if p.get("status") == status]

    def approve_pending_escalation(self, proposal_id: str,
                                   reviewed_by: str = "operator") -> Optional[Dict]:
        """Approve an escalation → APPLY the severity bump to the live finding
        record (if still tracked). Returns the record, or None if not found /
        not pending."""
        for p in self.pending_escalations:
            if p.get("proposal_id") == proposal_id and p.get("status") == "pending":
                p["status"] = "approved"
                p["reviewed_at"] = datetime.utcnow().isoformat()
                p["reviewed_by"] = reviewed_by
                rec = self.known_findings.get(p.get("finding_id"))
                if rec is not None:
                    rec["severity"] = p.get("to_severity")
                    rec["auto_escalated"] = True
                return p
        return None

    def reject_pending_escalation(self, proposal_id: str, reason: str = "",
                                  reviewed_by: str = "operator") -> Optional[Dict]:
        for p in self.pending_escalations:
            if p.get("proposal_id") == proposal_id and p.get("status") == "pending":
                p["status"] = "rejected"
                p["reviewed_at"] = datetime.utcnow().isoformat()
                p["reviewed_by"] = reviewed_by
                p["review_reason"] = reason
                return p
        return None

    def is_entity_map_fresh(self, max_age_hours: int = 72) -> bool:
        """True if entity_map_cache exists and is less than max_age_hours old."""
        if not self.entity_map_cache or not self.entity_map_updated_at:
            return False
        try:
            updated = datetime.fromisoformat(self.entity_map_updated_at)
            age_hours = (datetime.utcnow() - updated).total_seconds() / 3600
            return age_hours < max_age_hours
        except Exception:
            return False

    def to_dict(self) -> Dict:
        """Serialize to a flat dict — backward compatible with the pre-VAL-80 format."""
        d: Dict[str, Any] = {
            'client_name': self.client_name,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
        }
        # Flatten all sub-objects
        for sub_attr in ('_entity_cache', '_finding_tracker', '_run_stats',
                         '_dq_history', '_table_intelligence', '_alert_config'):
            sub_obj = object.__getattribute__(self, sub_attr)
            d.update(asdict(sub_obj))
        # Direct fields
        d['baseline_history'] = self.baseline_history
        d['preferred_queries'] = self.preferred_queries
        d['refinement'] = self.refinement
        d['pending_refinements'] = self.pending_refinements
        d['pending_escalations'] = self.pending_escalations
        d['segmentation_history'] = self.segmentation_history
        d['webhooks'] = self.webhooks
        d['schedule_config'] = self.schedule_config
        d['business_context'] = asdict(self.business_context) if self.business_context else None
        d['metadata'] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "ClientProfile":
        """Deserialize from a flat dict OR a nested dict (from dataclasses.asdict).

        Accepts both the old pre-VAL-80 flat format and the new nested format
        where sub-objects appear as dicts under their attribute names.
        """
        # Identity / top-level fields
        top_level_fields = {
            'client_name', 'created_at', 'updated_at',
            'baseline_history', 'preferred_queries', 'refinement',
            'pending_refinements', 'pending_escalations',
            'segmentation_history', 'webhooks', 'schedule_config', 'metadata',
            'business_context',
        }

        # Sub-object field mappings
        sub_mappings = {
            '_entity_cache': (EntityCache, {'entity_map_cache', 'entity_map_updated_at'}),
            '_finding_tracker': (FindingTracker, {'known_findings', 'resolved_findings', 'false_positives'}),
            '_run_stats': (RunStats, {'run_count', 'last_run_date', 'last_run_at', 'total_tokens_used', 'total_cost_usd', 'industry_inferred', 'currency_detected', 'run_history'}),
            '_dq_history': (DQHistory, {'dq_history', 'dq_scores', 'dq_trend'}),
            '_table_intelligence': (TableIntelligence, {'focus_tables', 'table_weights'}),
            '_alert_config': (AlertConfig, {'alert_thresholds', 'triggered_alerts'}),
        }

        kwargs = {}

        # Extract top-level fields. Skip explicit None so the field's
        # default_factory wins — a corrupt/legacy dict carrying e.g.
        # "pending_refinements": null must not leave a collection field None.
        for k in top_level_fields:
            if k in d and d[k] is not None:
                kwargs[k] = d[k]

        # Build sub-objects: prefer nested format, fall back to flat keys
        for sub_attr, (sub_cls, field_names) in sub_mappings.items():
            if sub_attr in d and isinstance(d[sub_attr], dict):
                # Nested format (from dataclasses.asdict)
                kwargs[sub_attr] = sub_cls(**d[sub_attr])
            else:
                # Flat format (old pre-VAL-80 or to_dict output)
                sub_kwargs = {k: d[k] for k in field_names if k in d}
                kwargs[sub_attr] = sub_cls(**sub_kwargs)

        # Deserialize business_context dict into BusinessContext object
        bc = kwargs.get('business_context')
        if bc is not None and isinstance(bc, dict):
            kwargs['business_context'] = BusinessContext(**bc)

        return cls(**kwargs)

    @classmethod
    def new(cls, client_name: str) -> "ClientProfile":
        return cls(client_name=client_name)


# ── Backward-compatible __init__ wrapper ──────────────────────────────────────
# Allows callers to pass flat field names (e.g., alert_thresholds=...) directly
# to the ClientProfile constructor, routing them into the correct sub-objects.

_FLAT_TO_SUB = {
    'entity_map_cache': ('_entity_cache', EntityCache),
    'entity_map_updated_at': ('_entity_cache', EntityCache),
    'known_findings': ('_finding_tracker', FindingTracker),
    'resolved_findings': ('_finding_tracker', FindingTracker),
    'false_positives': ('_finding_tracker', FindingTracker),
    'run_count': ('_run_stats', RunStats),
    'last_run_date': ('_run_stats', RunStats),
    'last_run_at': ('_run_stats', RunStats),
    'total_tokens_used': ('_run_stats', RunStats),
    'total_cost_usd': ('_run_stats', RunStats),
    'industry_inferred': ('_run_stats', RunStats),
    'currency_detected': ('_run_stats', RunStats),
    'run_history': ('_run_stats', RunStats),
    'dq_history': ('_dq_history', DQHistory),
    'dq_scores': ('_dq_history', DQHistory),
    'dq_trend': ('_dq_history', DQHistory),
    'focus_tables': ('_table_intelligence', TableIntelligence),
    'table_weights': ('_table_intelligence', TableIntelligence),
    'alert_thresholds': ('_alert_config', AlertConfig),
    'triggered_alerts': ('_alert_config', AlertConfig),
}

_original_init = ClientProfile.__init__


def _compat_init(self, *args, **kwargs):
    # Collect flat kwargs that belong to sub-objects
    sub_kwargs: Dict[str, Dict[str, Any]] = {}
    flat_keys = [k for k in kwargs if k in _FLAT_TO_SUB]
    for k in flat_keys:
        sub_attr, _ = _FLAT_TO_SUB[k]
        sub_kwargs.setdefault(sub_attr, {})[k] = kwargs.pop(k)

    # Build sub-objects from collected flat kwargs, merging with any
    # explicitly passed sub-object kwargs
    for sub_attr, fields in sub_kwargs.items():
        if sub_attr not in kwargs:
            _, sub_cls = _FLAT_TO_SUB[next(iter(fields))]
            kwargs[sub_attr] = sub_cls(**fields)
        else:
            # Sub-object already passed; update its fields
            existing = kwargs[sub_attr]
            for fname, fval in fields.items():
                setattr(existing, fname, fval)

    _original_init(self, *args, **kwargs)


ClientProfile.__init__ = _compat_init


# ── N4 write-path helpers (VAL-192) ───────────────────────────────────────────

# Provenance fields every staged/merged learning must carry (CI linter enforces).
PROVENANCE_REQUIRED = ("run_id", "client_tag", "generated_at")


def memory_review_enabled() -> bool:
    """True unless ``VALINOR_MEMORY_REVIEW=0`` — the N4 propose→review→merge path
    is now the DEFAULT (flipped 2026-06-14 after the end-to-end flow was proven
    live): learnings stage for human review instead of auto-applying. Set
    ``VALINOR_MEMORY_REVIEW=0`` to restore the legacy auto-write."""
    return os.environ.get("VALINOR_MEMORY_REVIEW", "1") != "0"


def extract_finding_ids(findings: Dict) -> List[str]:
    """Collect finding ids from a swarm-output dict (best-effort, type-guarded).
    These are the source learnings a refinement proposal derives from."""
    ids: List[str] = []
    if not isinstance(findings, dict):
        return ids
    for agent_name, agent_data in findings.items():
        if agent_name.startswith("_") or not isinstance(agent_data, dict):
            continue
        for f in agent_data.get("findings", []) or []:
            if isinstance(f, dict) and f.get("id"):
                ids.append(str(f["id"]))
    return ids


def build_pending_refinement(
    refinement: Dict,
    run_id: str,
    client_tag: str,
    source_findings_ids: Optional[List[str]] = None,
    confidence: Optional[float] = None,
    confidence_label: str = "",
    proposal_id: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Dict:
    """Build a ``PendingRefinement`` (as dict) with provenance, ready to stage.

    proposal_id / generated_at are injectable for deterministic tests; they
    default to a uuid and utcnow respectively.
    """
    return asdict(PendingRefinement(
        proposal_id=proposal_id or f"pr_{uuid.uuid4().hex[:12]}",
        refinement=dict(refinement or {}),
        run_id=run_id,
        client_tag=client_tag,
        generated_at=generated_at or datetime.utcnow().isoformat(),
        source_findings_ids=list(source_findings_ids or []),
        confidence=confidence,
        confidence_label=confidence_label,
    ))


def build_pending_escalation(
    finding_id: str,
    from_severity: str,
    to_severity: str,
    runs_open: int,
    run_id: str,
    client_tag: str,
    confidence: Optional[float] = None,
    confidence_label: str = "",
    proposal_id: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Dict:
    """Build a ``PendingFindingEscalation`` (as dict) with provenance, ready to
    stage. proposal_id / generated_at are injectable for deterministic tests."""
    return asdict(PendingFindingEscalation(
        proposal_id=proposal_id or f"pe_{uuid.uuid4().hex[:12]}",
        finding_id=finding_id,
        from_severity=from_severity,
        to_severity=to_severity,
        runs_open=runs_open,
        run_id=run_id,
        client_tag=client_tag,
        generated_at=generated_at or datetime.utcnow().isoformat(),
        confidence=confidence,
        confidence_label=confidence_label,
    ))


def has_provenance(record: Dict) -> bool:
    """True iff a pending/merged refinement record carries the required
    provenance (used by the CI provenance linter). Requires the source/date/
    client-tag trio present and a non-None confidence."""
    if not isinstance(record, dict):
        return False
    if any(not record.get(k) for k in PROVENANCE_REQUIRED):
        return False
    return record.get("confidence") is not None
