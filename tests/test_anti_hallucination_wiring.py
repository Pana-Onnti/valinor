"""
Regression test for VAL-161 — anti-hallucination wiring.

Confirms that the production pipeline (CLI core/valinor/run.py + SaaS
core/adapters/valinor_adapter.py) actually constructs the
SchemaKnowledgeGraph and VerificationEngine and feeds the
VerificationReport (with Number Registry) to the narrators.

If any of these assertions break, the Gloria bug is back in scope:
analyst hallucinations like "$13.5M AR / 4854 debtors" would flow
unverified into the executive report.

Refs: VAL-161
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest

from valinor.knowledge_graph import SchemaKnowledgeGraph, build_knowledge_graph
from valinor.verification import VerificationEngine


REPO_ROOT = Path(__file__).parent.parent
CLI_RUN_PATH = REPO_ROOT / "core" / "valinor" / "run.py"
SAAS_ADAPTER_PATH = REPO_ROOT / "core" / "adapters" / "valinor_adapter.py"


# ══════════════════════════════════════════════════════════════════════════
# Fixtures — Gloria post-fix ground truth + the canonical hallucination
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def gloria_post_fix_query_results():
    """Gloria query results with the *correct* values (post-fix ground truth)."""
    return {
        "results": {
            "total_revenue_summary": {
                "rows": [{
                    "num_invoices": 3139,
                    "total_revenue": 1631559.62,
                    "avg_invoice": 519.77,
                    "min_invoice": -35511.52,
                    "max_invoice": 123376.73,
                    "distinct_customers": 1223,
                    "date_from": "2024-12-01",
                    "date_to": "2024-12-31",
                }],
                "row_count": 1,
            },
            "ar_outstanding_actual": {
                "rows": [{
                    "total_outstanding": 3267365.43,
                    "overdue_amount": 3267365.43,
                    "customers_with_debt": 616,
                }],
                "row_count": 1,
            },
        },
        "errors": {},
    }


@pytest.fixture
def gloria_baseline_post_fix():
    return {
        "data_available": True,
        "total_revenue": 1631559.62,
        "num_invoices": 3139,
        "total_outstanding_ar": 3267365.43,
        "customers_with_debt": 616,
        "distinct_customers": 1223,
    }


@pytest.fixture
def gloria_hallucinated_findings():
    """The exact Gloria bug: agent claims $13.5M AR + 4854 debtors."""
    return {
        "analyst": {
            "agent": "analyst",
            "output": "AR analysis complete",
            "findings": [
                {
                    "id": "FIN-AR-HALLUCINATION",
                    "headline": "$13.5M AR, 100% Overdue",
                    "value_eur": 13509300.79,
                    "value_confidence": "measured",
                    "evidence": "ar_outstanding_actual query, 4854 customers affected",
                    "domain": "finance",
                    "severity": "critical",
                },
            ],
        },
    }


# ══════════════════════════════════════════════════════════════════════════
# Static wiring assertions — read the source so we don't depend on heavy
# imports (the SaaS adapter eagerly applies the SDK monkey-patch).
# ══════════════════════════════════════════════════════════════════════════

def test_cli_run_wires_kg_and_verification():
    """core/valinor/run.py must build the KG and run the VerificationEngine."""
    src = CLI_RUN_PATH.read_text(encoding="utf-8")
    assert "from valinor.knowledge_graph import build_knowledge_graph" in src, \
        "CLI run.py must import build_knowledge_graph"
    assert "from valinor.verification import VerificationEngine" in src, \
        "CLI run.py must import VerificationEngine"
    assert "build_knowledge_graph(entity_map)" in src, \
        "CLI run.py must call build_knowledge_graph(entity_map) after Cartographer"
    # VerificationEngine is instantiated with (query_results, baseline, kg) positionally;
    # N5 (VAL-192) added optional connection_string/entity_map kwargs and wrapped the call
    # across lines, so assert the invariant (constructor + positional args) not the one-liner.
    assert "VerificationEngine(" in src and "query_results, baseline, kg" in src, \
        "CLI run.py must instantiate VerificationEngine(query_results, baseline, kg, ...)"
    assert "verifier.verify_findings(findings)" in src, \
        "CLI run.py must call verify_findings(findings)"
    assert "verification_report=verification_report" in src, \
        "CLI run.py must pass verification_report=... to run_narrators"
    assert "kg=kg" in src, \
        "CLI run.py must pass kg=kg to run_analysis_agents"


def test_saas_adapter_wires_kg_and_verification():
    """core/adapters/valinor_adapter.py must do the same wiring as CLI."""
    src = SAAS_ADAPTER_PATH.read_text(encoding="utf-8")
    assert "from valinor.knowledge_graph import build_knowledge_graph" in src, \
        "SaaS adapter must import build_knowledge_graph"
    assert "from valinor.verification import VerificationEngine" in src, \
        "SaaS adapter must import VerificationEngine"
    assert "build_knowledge_graph(entity_map)" in src, \
        "SaaS adapter must call build_knowledge_graph(entity_map) after Cartographer"
    # See note in test_cli_run_wires_kg_and_verification: N5 wrapped the call + added kwargs.
    assert "VerificationEngine(" in src and "query_results, baseline, kg" in src, \
        "SaaS adapter must instantiate VerificationEngine(query_results, baseline, kg, ...)"
    assert "verifier.verify_findings(findings)" in src, \
        "SaaS adapter must call verify_findings(findings)"
    assert "verification_report=verification_report" in src, \
        "SaaS adapter must pass verification_report=... to narrate_executive"
    assert "kg=kg" in src, \
        "SaaS adapter must pass kg=kg to run_analysis_agents"


# ══════════════════════════════════════════════════════════════════════════
# Functional regression — wire the modules in the same order the pipeline
# does and assert the Gloria hallucination is caught.
# ══════════════════════════════════════════════════════════════════════════

def test_kg_constructible_from_minimal_gloria_entity_map():
    """build_knowledge_graph must produce a non-empty graph from a Gloria-like map."""
    entity_map = {
        "entities": {
            "invoices": {
                "table": "c_invoice", "type": "INVOICE",
                "key_columns": {"id": "c_invoice_id", "amount": "grandtotal"},
            },
            "customers": {
                "table": "c_bpartner", "type": "CUSTOMER",
                "key_columns": {"id": "c_bpartner_id"},
            },
        },
        "relationships": [
            {"from": "invoices", "to": "customers",
             "via": "c_bpartner_id", "cardinality": "N:1"},
        ],
    }
    kg = build_knowledge_graph(entity_map)
    assert isinstance(kg, SchemaKnowledgeGraph)
    assert len(kg.tables) == 2
    assert len(kg.edges) == 1
    assert kg.to_prompt_context()  # non-empty


def test_gloria_hallucination_caught_by_wired_pipeline(
    gloria_post_fix_query_results,
    gloria_baseline_post_fix,
    gloria_hallucinated_findings,
):
    """
    Wire the modules exactly as the pipeline does (KG + VerificationEngine
    over query_results + baseline) and feed the canonical Gloria
    hallucination. The report must:

      1. Flag the $13.5M AR claim as not VERIFIED.
      2. Anchor the Number Registry on the real $3.27M AR / 616 debtors.
      3. Surface a NUMBER REGISTRY block in to_prompt_context() so
         narrators see the verified values.
    """
    kg = SchemaKnowledgeGraph()
    verifier = VerificationEngine(
        gloria_post_fix_query_results,
        gloria_baseline_post_fix,
        kg,
    )
    report = verifier.verify_findings(gloria_hallucinated_findings)

    # 1. The $13.5M monetary claim must not be VERIFIED.
    #    (Note: a "100% overdue" sub-claim may legitimately VERIFY — real
    #    Gloria has 100% overdue ratio. We only assert on the dollar amount
    #    and the bogus customer count.)
    value_results = [
        r for r in report.results
        if r.claim_id == "FIN-AR-HALLUCINATION_value"
    ]
    assert value_results, "VerificationEngine produced no _value claim for the AR finding"
    assert value_results[0].status != "VERIFIED", (
        "Gloria hallucination ($13.5M AR _value claim) was verified — "
        f"the wiring is broken. Status: {value_results[0].status}"
    )

    # Any customer-count sub-claim extracted from the finding must not verify
    # at the bogus 4854 (real is 616). Only assert when such a claim was
    # decomposed — the engine doesn't always extract counts from free text.
    count_results = [
        r for r in report.results
        if r.claim_id and "count" in r.claim_id
        and r.claim_id.startswith("FIN-AR-HALLUCINATION")
    ]
    for r in count_results:
        assert r.status != "VERIFIED", (
            f"Bogus customer count claim verified (real is 616): {r.claim_id} → {r.status}"
        )

    # 2. Number Registry anchors narrators to the real AR.
    assert "total_outstanding_ar" in report.number_registry
    assert report.number_registry["total_outstanding_ar"].value == 3267365.43
    assert "customers_with_debt" in report.number_registry
    assert report.number_registry["customers_with_debt"].value == 616

    # 3. Narrators see the registry through to_prompt_context().
    ctx = report.to_prompt_context()
    assert "NUMBER REGISTRY" in ctx
    # Real AR value must appear (formatted with thousands separators).
    assert "3,267,365.43" in ctx, (
        "Number Registry context must surface the verified $3.27M AR — "
        "narrators won't have ground truth otherwise."
    )
