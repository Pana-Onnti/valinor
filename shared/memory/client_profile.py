"""
ClientProfile — persistent per-client state that accumulates across runs.
Stored in PostgreSQL (client_profiles table) or local file fallback.

Decomposed into typed sub-objects (VAL-80) while maintaining full backward
compatibility: to_dict() produces the same flat dict, from_dict() accepts it,
and attribute access like `profile.run_count` still works via properties.
"""
from __future__ import annotations
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
    refinement: Optional[Dict] = None   # ClientRefinement as dict

    # ── Segmentation history ───────────────────────────────────────────────────
    segmentation_history: List[Dict] = field(default_factory=list)  # last 12 periods

    # ── Webhooks ───────────────────────────────────────────────────────────────
    webhooks: List[Dict] = field(default_factory=list)  # registered webhook URLs

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
        d['segmentation_history'] = self.segmentation_history
        d['webhooks'] = self.webhooks
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
            'segmentation_history', 'webhooks', 'metadata',
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

        # Extract top-level fields
        for k in top_level_fields:
            if k in d:
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
