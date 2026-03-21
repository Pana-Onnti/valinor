"""
ClientProfile — persistent per-client state that accumulates across runs.
Stored in PostgreSQL (client_profiles table) or local file fallback.
"""
from __future__ import annotations
import json
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
class ClientProfile:
    """
    Full persistent profile for one client.
    Loaded before each run, saved after.
    """
    client_name: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # ── Cartographer cache ────────────────────────────────────────────────────
    entity_map_cache: Optional[Dict] = None
    entity_map_updated_at: Optional[str] = None   # ISO timestamp

    # ── Finding tracking ──────────────────────────────────────────────────────
    known_findings: Dict[str, Any] = field(default_factory=dict)   # id → FindingRecord dict
    resolved_findings: Dict[str, Any] = field(default_factory=dict)

    # ── Table intelligence ────────────────────────────────────────────────────
    focus_tables: List[str] = field(default_factory=list)
    table_weights: Dict[str, float] = field(default_factory=dict)

    # ── KPI history ───────────────────────────────────────────────────────────
    baseline_history: Dict[str, List[Any]] = field(default_factory=dict)

    # ── Query intelligence ────────────────────────────────────────────────────
    preferred_queries: List[Dict] = field(default_factory=list)
    false_positives: List[str] = field(default_factory=list)

    # ── Refinement (from last RefinementAgent run) ────────────────────────────
    refinement: Optional[Dict] = None   # ClientRefinement as dict

    # ── Run stats ─────────────────────────────────────────────────────────────
    run_count: int = 0
    last_run_date: Optional[str] = None
    industry_inferred: Optional[str] = None
    currency_detected: Optional[str] = None

    # ── History ───────────────────────────────────────────────────────────────
    run_history: List[Dict] = field(default_factory=list)  # last 20 runs summary

    # ── Alert thresholds ──────────────────────────────────────────────────────
    alert_thresholds: List[Dict] = field(default_factory=list)
    # Each threshold: {"label": str, "metric": str, "operator": ">"|"<"|">="|"<=", "value": float, "currency": bool, "triggered": bool, "last_triggered": str}
    triggered_alerts: List[Dict] = field(default_factory=list)  # last 20 triggered

    # ── Segmentation history ──────────────────────────────────────────────────
    segmentation_history: List[Dict] = field(default_factory=list)  # last 12 periods

    # ── Data Quality history ──────────────────────────────────────────────────
    dq_history: List[Dict] = field(default_factory=list)  # last 10 DQ reports per run

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
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "ClientProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def new(cls, client_name: str) -> "ClientProfile":
        return cls(client_name=client_name)
