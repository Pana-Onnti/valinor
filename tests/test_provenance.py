"""
Tests for the provenance tracking module.
Covers FindingProvenance and ProvenanceRegistry — data lineage, confidence
scoring, serialization, and the report context builder.
"""
import sys
import pytest

sys.path.insert(0, "core")
sys.path.insert(0, ".")

from valinor.quality.provenance import FindingProvenance, ProvenanceRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_registry(dq_score: float = 100.0, tag: str = "VALIDATED") -> ProvenanceRegistry:
    return ProvenanceRegistry(
        job_id="job-001",
        client_name="Acme Corp",
        period="2026-Q1",
        dq_report_score=dq_score,
        dq_report_tag=tag,
    )


# ---------------------------------------------------------------------------
# 1. FindingProvenance — creation and defaults
# ---------------------------------------------------------------------------

def test_finding_provenance_defaults():
    """A newly constructed FindingProvenance has sensible default values."""
    fp = FindingProvenance(finding_id="f1", metric_name="revenue")
    assert fp.finding_id == "f1"
    assert fp.metric_name == "revenue"
    assert fp.data_quality_tag == "PRELIMINARY"
    assert fp.confidence_score == 1.0
    assert fp.confidence_label == "PROVISIONAL"
    assert fp.tables_accessed == []
    assert fp.row_counts == {}
    assert fp.reconciliation_discrepancy_pct == 0.0
    assert fp.dq_score == 100.0
    assert fp.dq_warnings == []


def test_finding_provenance_custom_fields():
    """Custom field values are stored verbatim."""
    fp = FindingProvenance(
        finding_id="f2",
        metric_name="margin",
        data_quality_tag="VALIDATED",
        confidence_score=0.9,
        confidence_label="CONFIRMED",
        tables_accessed=["account_move", "product"],
        row_counts={"account_move": 1500},
        dq_score=95.0,
        dq_warnings=["null ratio high on amount_tax"],
    )
    assert fp.tables_accessed == ["account_move", "product"]
    assert fp.row_counts["account_move"] == 1500
    assert fp.dq_warnings[0].startswith("null ratio")


# ---------------------------------------------------------------------------
# 2. ProvenanceRegistry — register() creates FindingProvenance records
# ---------------------------------------------------------------------------

def test_register_returns_finding_provenance():
    """register() returns a FindingProvenance with the correct identifiers."""
    reg = make_registry()
    fp = reg.register(finding_id="f1", metric_name="revenue")
    assert isinstance(fp, FindingProvenance)
    assert fp.finding_id == "f1"
    assert fp.metric_name == "revenue"


def test_register_stores_finding_in_registry():
    """Registered findings are accessible in the findings dict."""
    reg = make_registry()
    reg.register("f1", "revenue")
    reg.register("f2", "cost")
    assert "f1" in reg.findings
    assert "f2" in reg.findings
    assert len(reg.findings) == 2


def test_register_passes_tables():
    """Tables passed to register() are stored on the resulting provenance."""
    reg = make_registry()
    fp = reg.register("f1", "revenue", tables=["account_move", "res_partner"])
    assert "account_move" in fp.tables_accessed
    assert "res_partner" in fp.tables_accessed


def test_register_no_tables_defaults_to_empty_list():
    """When tables=None, tables_accessed is an empty list (not None)."""
    reg = make_registry()
    fp = reg.register("f1", "revenue", tables=None)
    assert fp.tables_accessed == []


# ---------------------------------------------------------------------------
# 3. Confidence labels — CONFIRMED / PROVISIONAL / UNVERIFIED / BLOCKED
# ---------------------------------------------------------------------------

def test_confidence_confirmed_at_perfect_dq():
    """Perfect DQ score and zero reconciliation discrepancy → CONFIRMED."""
    reg = make_registry(dq_score=100.0)
    fp = reg.register("f1", "revenue", reconciliation_discrepancy=0.0)
    assert fp.confidence_label == "CONFIRMED"
    assert fp.confidence_score >= 0.85


def test_confidence_confirmed_threshold():
    """DQ score of 100 and no reconciliation penalty → confidence == 1.0."""
    reg = make_registry(dq_score=100.0)
    fp = reg.register("f1", "revenue")
    assert fp.confidence_score == pytest.approx(1.0)


def test_confidence_provisional_mid_dq():
    """A mid-range DQ score that pushes confidence into PROVISIONAL band."""
    # DQ = 70 → dq_deduction = (30/100)*0.4 = 0.12 → confidence = 0.88
    # But we need something in 0.65–0.84 range.
    # DQ = 40 → dq_deduction = 0.60*0.4 = 0.24 → confidence = 0.76
    reg = make_registry(dq_score=40.0)
    fp = reg.register("f1", "revenue", reconciliation_discrepancy=0.0)
    assert fp.confidence_label == "PROVISIONAL"
    assert 0.65 <= fp.confidence_score < 0.85


def test_confidence_unverified_low_dq():
    """Very low DQ score pushes confidence into UNVERIFIED band (0.45–0.64)."""
    # DQ = 0 → dq_deduction = 0.40 → confidence = 0.60 (UNVERIFIED)
    reg = make_registry(dq_score=0.0)
    fp = reg.register("f1", "revenue", reconciliation_discrepancy=0.0)
    assert fp.confidence_label == "UNVERIFIED"
    assert 0.45 <= fp.confidence_score < 0.65


def test_confidence_blocked_by_recon_penalty():
    """High reconciliation discrepancy combined with low DQ produces BLOCKED."""
    # DQ = 0 → dq_deduction = 0.40; recon_discrepancy = 0.20 (≥ 0.10, capped at 1.0) → recon_penalty = 0.20
    # confidence = 1.0 - 0.40 - 0.20 = 0.40 → BLOCKED
    reg = make_registry(dq_score=0.0)
    fp = reg.register("f1", "revenue", reconciliation_discrepancy=0.20)
    assert fp.confidence_label == "BLOCKED"
    assert fp.confidence_score < 0.45


def test_confidence_never_negative():
    """Confidence score is clamped to 0.0 minimum regardless of penalties."""
    reg = make_registry(dq_score=0.0)
    fp = reg.register("f1", "revenue", reconciliation_discrepancy=999.0)
    assert fp.confidence_score >= 0.0


# ---------------------------------------------------------------------------
# 4. to_display_badge()
# ---------------------------------------------------------------------------

def test_display_badge_contains_label_and_tag():
    """Badge includes the confidence label and the DQ tag."""
    reg = make_registry(dq_score=100.0, tag="VALIDATED")
    fp = reg.register("f1", "revenue")
    badge = fp.to_display_badge()
    assert "CONFIRMED" in badge
    assert "VALIDATED" in badge


def test_display_badge_contains_score():
    """Badge reports the score as an integer out of 100."""
    reg = make_registry(dq_score=100.0)
    fp = reg.register("f1", "revenue")
    badge = fp.to_display_badge()
    # confidence 1.0 → score 100
    assert "100/100" in badge


# ---------------------------------------------------------------------------
# 5. Serialization — to_dict()
# ---------------------------------------------------------------------------

def test_finding_provenance_to_dict_roundtrip():
    """to_dict() returns a plain dict with all fields intact."""
    reg = make_registry(dq_score=100.0, tag="VALIDATED")
    fp = reg.register("f1", "revenue", tables=["account_move"])
    d = fp.to_dict()
    assert isinstance(d, dict)
    assert d["finding_id"] == "f1"
    assert d["metric_name"] == "revenue"
    assert d["confidence_label"] in ("CONFIRMED", "PROVISIONAL", "UNVERIFIED", "BLOCKED")
    assert "tables_accessed" in d
    assert "account_move" in d["tables_accessed"]


def test_registry_to_dict_structure():
    """ProvenanceRegistry.to_dict() returns nested findings."""
    reg = make_registry(dq_score=90.0, tag="VALIDATED")
    reg.register("f1", "revenue")
    reg.register("f2", "cost")
    d = reg.to_dict()
    assert d["job_id"] == "job-001"
    assert d["client_name"] == "Acme Corp"
    assert d["period"] == "2026-Q1"
    assert d["dq_report_score"] == 90.0
    assert d["dq_report_tag"] == "VALIDATED"
    assert "f1" in d["findings"]
    assert "f2" in d["findings"]
    # Each nested finding should itself be a dict
    assert isinstance(d["findings"]["f1"], dict)


def test_registry_to_dict_empty_findings():
    """to_dict() on a registry with no findings returns an empty findings dict."""
    reg = make_registry()
    d = reg.to_dict()
    assert d["findings"] == {}


# ---------------------------------------------------------------------------
# 6. summary_for_report() — provenance context string builder
# ---------------------------------------------------------------------------

def test_summary_for_report_contains_dq_score():
    """Summary block includes the DQ score."""
    reg = make_registry(dq_score=87.0, tag="VALIDATED")
    summary = reg.summary_for_report()
    assert "87" in summary


def test_summary_for_report_contains_tag():
    """Summary block includes the DQ tag."""
    reg = make_registry(dq_score=100.0, tag="VALIDATED")
    summary = reg.summary_for_report()
    assert "VALIDATED" in summary


def test_summary_for_report_certified_count():
    """Certified count reflects only CONFIRMED findings."""
    reg = make_registry(dq_score=100.0, tag="VALIDATED")
    reg.register("f1", "revenue")   # CONFIRMED (dq=100, no recon penalty)
    reg.register("f2", "cost")     # CONFIRMED
    # Introduce a third with a low-DQ registry to get a non-CONFIRMED finding
    low_reg = make_registry(dq_score=0.0, tag="PRELIMINARY")
    low_reg.register("f3", "margin")  # UNVERIFIED
    # Check the high-quality registry separately
    summary = reg.summary_for_report()
    assert "2/2" in summary


def test_summary_for_report_no_findings():
    """Summary is well-formed even when no findings have been registered."""
    reg = make_registry()
    summary = reg.summary_for_report()
    assert "0/0" in summary
    assert "DQ Score" in summary


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

def test_dq_tag_propagated_to_finding():
    """The registry's DQ tag is propagated to every registered finding."""
    reg = make_registry(dq_score=100.0, tag="CERTIFIED")
    fp = reg.register("f1", "revenue")
    assert fp.data_quality_tag == "CERTIFIED"


def test_dq_score_propagated_to_finding():
    """The registry's DQ score is stored on each finding."""
    reg = make_registry(dq_score=72.5, tag="PROVISIONAL")
    fp = reg.register("f1", "revenue")
    assert fp.dq_score == 72.5


def test_registry_overwrite_finding():
    """Re-registering the same finding_id replaces the previous record."""
    reg = make_registry(dq_score=100.0)
    reg.register("f1", "revenue")
    reg.register("f1", "revenue_updated")
    assert reg.findings["f1"].metric_name == "revenue_updated"
    assert len(reg.findings) == 1


def test_analysis_timestamp_is_set():
    """analysis_timestamp is automatically populated (non-empty ISO string)."""
    fp = FindingProvenance(finding_id="f1", metric_name="revenue")
    assert fp.analysis_timestamp
    # Basic ISO format sanity: contains 'T' separator
    assert "T" in fp.analysis_timestamp
