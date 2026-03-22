#!/usr/bin/env python3
"""
End-to-end test: build queries from Gloria entity_map, execute against DB,
verify results match cross-referenced ground truth.

Usage: python3 scripts/test_gloria_queries.py
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from sqlalchemy import create_engine, text
from valinor.agents.query_builder import build_queries
from valinor.knowledge_graph import build_knowledge_graph
from valinor.verification import VerificationEngine

# Import compute_baseline without importing the full pipeline (avoids claude_agent_sdk)
import importlib.util
_pipeline_spec = importlib.util.spec_from_file_location(
    "_pipeline_partial", str(Path(__file__).parent.parent / "core" / "valinor" / "pipeline.py"),
    submodule_search_locations=[],
)
# We can't import pipeline.py directly because it imports claude_agent_sdk.
# Instead, re-implement compute_baseline locally (it's pure Python, no SDK dependency).
from datetime import datetime, timezone
from typing import Any

def _f(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None

def _i(val):
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None

def compute_baseline(query_results: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    results = query_results.get("results", {})
    baseline = {
        "data_available": False, "total_revenue": None, "num_invoices": None,
        "avg_invoice": None, "min_invoice": None, "max_invoice": None,
        "date_from": None, "date_to": None, "data_freshness_days": None,
        "distinct_customers": None, "total_outstanding_ar": None,
        "overdue_ar": None, "customers_with_debt": None,
        "source_queries": [], "warning": None, "_provenance": {},
    }
    def _tag(metric, value, source_query, row_count):
        baseline[metric] = value
        baseline["_provenance"][metric] = {"source_query": source_query, "row_count": row_count, "executed_at": now, "confidence": "measured"}

    if "total_revenue_summary" in results:
        rows = results["total_revenue_summary"].get("rows", [])
        rc = results["total_revenue_summary"].get("row_count", 0)
        if rows:
            r = rows[0]
            baseline["data_available"] = True
            _tag("total_revenue", _f(r.get("total_revenue")), "total_revenue_summary", rc)
            _tag("num_invoices", _i(r.get("num_invoices")), "total_revenue_summary", rc)
            _tag("avg_invoice", _f(r.get("avg_invoice")), "total_revenue_summary", rc)
            _tag("min_invoice", _f(r.get("min_invoice")), "total_revenue_summary", rc)
            _tag("max_invoice", _f(r.get("max_invoice")), "total_revenue_summary", rc)
            _tag("distinct_customers", _i(r.get("distinct_customers")), "total_revenue_summary", rc)
            baseline["source_queries"].append("total_revenue_summary")
    if "ar_outstanding_actual" in results:
        rows = results["ar_outstanding_actual"].get("rows", [])
        rc = results["ar_outstanding_actual"].get("row_count", 0)
        if rows:
            r = rows[0]
            _tag("total_outstanding_ar", _f(r.get("total_outstanding")), "ar_outstanding_actual", rc)
            _tag("overdue_ar", _f(r.get("overdue_amount")), "ar_outstanding_actual", rc)
            _tag("customers_with_debt", _i(r.get("customers_with_debt")), "ar_outstanding_actual", rc)
            baseline["source_queries"].append("ar_outstanding_actual")
    return baseline

GLORIA_CONN = "postgresql://tad:tad@localhost:5432/gloria"

# Gloria entity map (simplified — matching real schema)
GLORIA_ENTITY_MAP = {
    "entities": {
        "invoices": {
            "table": "c_invoice",
            "type": "TRANSACTIONAL",
            "row_count": 4117,
            "confidence": 0.99,
            "key_columns": {
                "pk": "c_invoice_id",
                "invoice_pk": "c_invoice_id",
                "invoice_date": "dateinvoiced",
                "amount_col": "grandtotal",
                "customer_fk": "c_bpartner_id",
            },
            "base_filter": "issotrx='Y' AND docstatus='CO' AND isactive='Y'",
            "probed_values": {
                "issotrx": {"Y": 2366, "N": 1751},
                "docstatus": {"CO": 4108, "DR": 9},
                "isactive": {"Y": 4117},
            },
        },
        "customers": {
            "table": "c_bpartner",
            "type": "MASTER",
            "row_count": 88,
            "confidence": 0.98,
            "key_columns": {
                "pk": "c_bpartner_id",
                "customer_pk": "c_bpartner_id",
                "customer_name": "name",
            },
            "base_filter": "iscustomer='Y' AND isactive='Y'",
            "probed_values": {
                "isactive": {"Y": 81, "N": 7},
                "iscustomer": {"Y": 49, "N": 39},
            },
        },
        "payments": {
            "table": "fin_payment_schedule",
            "type": "TRANSACTIONAL",
            "row_count": 8019,
            "confidence": 0.97,
            "key_columns": {
                "pk": "fin_payment_schedule_id",
                "outstanding_amount": "outstandingamt",
                "due_date": "duedate",
                "customer_id": "c_bpartner_id",
            },
            "base_filter": "isactive='Y'",
            "probed_values": {
                "isactive": {"Y": 8019},
            },
        },
    },
    "relationships": [
        {"from": "invoices", "to": "customers", "via": "c_bpartner_id", "cardinality": "N:1"},
        {"from": "payments", "to": "invoices", "via": "c_invoice_id", "cardinality": "N:1"},
    ],
}

PERIOD = {"start": "2024-12-01", "end": "2024-12-31", "label": "2024-12"}

# Ground truth (verified via direct SQL against Gloria DB)
GROUND_TRUTH = {
    "total_revenue": 1631559.62,
    "num_invoices": 3139,
    "avg_invoice": 519.77,
    "distinct_customers": 1223,
    "ar_total_outstanding": 3267365.43,  # AR only (issotrx='Y'), excludes AP + order-only
    "ar_customers_with_debt": 509,       # With correct issotrx + IS NOT NULL + docstatus filters
    "top_debtor_name": "ISKAY PET S.LU.",
    "top_debtor_amount": 865514.74,
}


def main():
    print("=" * 70)
    print("  GLORIA E2E TEST — Query Builder + Knowledge Graph + Verification")
    print("=" * 70)

    # Step 1: Build Knowledge Graph
    print("\n▸ Building Knowledge Graph...")
    kg = build_knowledge_graph(GLORIA_ENTITY_MAP)
    print(f"  ✓ {len(kg.tables)} tables, {len(kg.edges)} edges, "
          f"{len(kg.concepts)} concepts")

    # Verify JOIN path reasoning
    path = kg.find_join_path("fin_payment_schedule", "c_bpartner")
    if path:
        print(f"  ✓ JOIN path fps→customer: {' → '.join(path.tables)} ({path.hop_count} hops)")
    else:
        print("  ✗ No JOIN path found fps→customer")

    # Step 2: Build queries
    print("\n▸ Building queries...")
    query_pack = build_queries(GLORIA_ENTITY_MAP, PERIOD)
    print(f"  ✓ {len(query_pack['queries'])} queries, {len(query_pack['skipped'])} skipped")
    for q in query_pack["queries"]:
        print(f"    • {q['id']} ({q['domain']})")
    for s in query_pack["skipped"]:
        print(f"    ○ SKIP {s['id']}: {s['reason']}")

    # Step 3: Execute against Gloria DB
    print("\n▸ Executing queries against Gloria DB...")
    engine = create_engine(GLORIA_CONN)
    results = {"results": {}, "errors": {}}

    for q in query_pack["queries"]:
        try:
            with engine.connect() as conn:
                result = conn.execute(text(q["sql"]))
                columns = list(result.keys())
                rows = []
                for row in result:
                    row_dict = dict(zip(columns, row))
                    for key, value in row_dict.items():
                        if not isinstance(value, (str, int, float, bool, type(None))):
                            row_dict[key] = str(value)
                    rows.append(row_dict)
                results["results"][q["id"]] = {
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                }
                status = "✓" if rows else "○ (empty)"
                print(f"    {status} {q['id']}: {len(rows)} rows")
        except Exception as e:
            err_msg = str(e)[:120]
            results["errors"][q["id"]] = {"error": err_msg, "sql": q["sql"][:200]}
            print(f"    ✗ {q['id']}: {err_msg}")

    engine.dispose()

    # Step 4: Compute baseline
    print("\n▸ Computing baseline...")
    baseline = compute_baseline(results)
    print(f"  Revenue:    {baseline.get('total_revenue', 'N/A'):>15,.2f}" if baseline.get('total_revenue') else "  Revenue:    N/A")
    print(f"  Invoices:   {baseline.get('num_invoices', 'N/A'):>15,}" if baseline.get('num_invoices') else "  Invoices:   N/A")
    print(f"  Customers:  {baseline.get('distinct_customers', 'N/A'):>15,}" if baseline.get('distinct_customers') else "  Customers:  N/A")
    print(f"  AR Total:   {baseline.get('total_outstanding_ar', 'N/A'):>15,.2f}" if baseline.get('total_outstanding_ar') else "  AR Total:   N/A")
    print(f"  Debtors:    {baseline.get('customers_with_debt', 'N/A'):>15,}" if baseline.get('customers_with_debt') else "  Debtors:    N/A")

    # Step 5: Verification
    print("\n▸ Running Verification Engine...")
    verifier = VerificationEngine(results, baseline, kg)

    # Simulate agent findings with both correct and hallucinated values
    test_findings = {
        "analyst_correct": {
            "findings": [
                {"id": "FIN-001", "headline": "Revenue $1,631,559.62 from 3,139 invoices",
                 "value_eur": 1631559.62, "value_confidence": "measured",
                 "evidence": "total_revenue_summary"},
            ],
        },
        "analyst_hallucinated": {
            "findings": [
                {"id": "FIN-BAD1", "headline": "$13.5M AR — structural collections failure",
                 "value_eur": 13509300.79, "value_confidence": "measured",
                 "evidence": "ar_outstanding_actual"},
                {"id": "FIN-BAD2", "headline": "4,854 customers owe money",
                 "value_eur": None, "value_confidence": "measured",
                 "evidence": "ar_outstanding_actual"},
            ],
        },
    }

    report = verifier.verify_findings(test_findings)
    print(f"\n  Verification Report:")
    print(f"    Total claims:       {report.total_claims}")
    print(f"    Verified:           {report.verified_claims}")
    print(f"    Failed/Unverified:  {report.failed_claims + report.unverifiable_claims}")
    print(f"    Approximate:        {report.approximate_claims}")
    print(f"    Rate:               {report.verification_rate:.0%}")

    if report.issues:
        print(f"\n  Cross-validation issues ({len(report.issues)}):")
        for issue in report.issues:
            print(f"    [{issue['severity']}] {issue['description'][:100]}")

    # Step 6: Compare with ground truth
    print("\n" + "=" * 70)
    print("  GROUND TRUTH COMPARISON")
    print("=" * 70)

    checks_passed = 0
    checks_total = 0

    def check(name, actual, expected, tolerance_pct=0.5):
        nonlocal checks_passed, checks_total
        checks_total += 1
        if actual is None:
            print(f"  ✗ {name}: MISSING (expected {expected})")
            return
        try:
            actual_f = float(actual)
            expected_f = float(expected)
            if expected_f == 0:
                match = actual_f == 0
            else:
                dev = abs(actual_f - expected_f) / abs(expected_f) * 100
                match = dev <= tolerance_pct
            if match:
                checks_passed += 1
                print(f"  ✓ {name}: {actual_f:>15,.2f} (expected {expected_f:,.2f})")
            else:
                dev = (actual_f - expected_f) / abs(expected_f) * 100
                print(f"  ✗ {name}: {actual_f:>15,.2f} (expected {expected_f:,.2f}, "
                      f"deviation {dev:+.1f}%)")
        except (TypeError, ValueError) as e:
            print(f"  ✗ {name}: conversion error: {e}")

    check("Total Revenue", baseline.get("total_revenue"), GROUND_TRUTH["total_revenue"])
    check("Invoice Count", baseline.get("num_invoices"), GROUND_TRUTH["num_invoices"])
    check("Avg Invoice", baseline.get("avg_invoice"), GROUND_TRUTH["avg_invoice"])
    check("Distinct Customers", baseline.get("distinct_customers"), GROUND_TRUTH["distinct_customers"])
    check("AR Outstanding", baseline.get("total_outstanding_ar"), GROUND_TRUTH["ar_total_outstanding"], tolerance_pct=1.0)
    check("Customers with Debt", baseline.get("customers_with_debt"), GROUND_TRUTH["ar_customers_with_debt"], tolerance_pct=1.0)

    # Check top debtors
    top_debtors = results["results"].get("top_debtors", {}).get("rows", [])
    if top_debtors:
        top = top_debtors[0]
        check("Top Debtor Amount", top.get("total_outstanding"), GROUND_TRUTH["top_debtor_amount"], tolerance_pct=1.0)
        top_name = top.get("customer_name", "")
        if GROUND_TRUTH["top_debtor_name"] in str(top_name):
            checks_passed += 1
            checks_total += 1
            print(f"  ✓ Top Debtor Name: {top_name}")
        else:
            checks_total += 1
            print(f"  ✗ Top Debtor Name: {top_name} (expected {GROUND_TRUTH['top_debtor_name']})")
    else:
        checks_total += 2
        print(f"  ✗ Top Debtors: query not available")

    print(f"\n{'=' * 70}")
    print(f"  RESULT: {checks_passed}/{checks_total} ground truth checks passed")
    if checks_passed == checks_total:
        print("  STATUS: ALL CORRECT — Zero hallucination potential")
    elif checks_passed >= checks_total - 2:
        print("  STATUS: MOSTLY CORRECT — Minor deviations")
    else:
        print("  STATUS: NEEDS INVESTIGATION — Significant deviations")
    print(f"{'=' * 70}")

    # Print number registry for reference
    print(f"\n  Number Registry ({len(report.number_registry)} entries):")
    for label, entry in sorted(report.number_registry.items()):
        print(f"    {label:30s} = {entry.value:>15,.2f} [{entry.confidence}] ({entry.source_query})")

    return checks_passed == checks_total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
