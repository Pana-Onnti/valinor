"""
Pipeline — Master orchestrator for Valinor stages.

Contains:
  - execute_queries      Stage 2.5: run SQL against DB
  - gate_calibration     Stage 1.5: verify base_filter before analysis runs
  - compute_baseline     post-2.5: build provenance-tagged shared context
  - run_analysis_agents  Stage 3: Analyst + Sentinel + Hunter in parallel
  - reconcile_swarm      Stage 3.5: detect & resolve agent numeric conflicts
  - run_narrators        Stage 4: audience reports

Key patterns implemented:
  - Deterministic Guard Rail   (gate_calibration — no LLM, cheap SQL assertions)
  - Frozen Brief w/ provenance (compute_baseline — every metric carries its source)
  - Reconciliation Node        (reconcile_swarm — Haiku arbiter on >2x conflicts)
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any

from claude_agent_sdk import query as agent_query, ClaudeAgentOptions, AssistantMessage, TextBlock
from sqlalchemy import create_engine, text

from valinor.agents.analyst import run_analyst
from valinor.agents.sentinel import run_sentinel
from valinor.agents.hunter import run_hunter


# ═══════════════════════════════════════════════════════════════
# STAGE 2.5 — EXECUTE QUERIES
# ═══════════════════════════════════════════════════════════════

async def execute_queries(query_pack: dict, client_config: dict) -> dict:
    """
    Execute all queries from the query pack against the client database.

    Returns:
        Dict with 'results' (successful) and 'errors' (failed).
    """
    connection_string = client_config["connection_string"]
    engine = create_engine(connection_string)
    results: dict[str, Any] = {"results": {}, "errors": {}}

    for query_item in query_pack.get("queries", []):
        query_id = query_item["id"]
        sql = query_item["sql"]
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql))
                columns = list(result.keys())
                rows = []
                for row in result:
                    row_dict = dict(zip(columns, row))
                    for key, value in row_dict.items():
                        if not isinstance(value, (str, int, float, bool, type(None))):
                            row_dict[key] = str(value)
                    rows.append(row_dict)
                results["results"][query_id] = {
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "domain": query_item.get("domain", "unknown"),
                    "description": query_item.get("description", ""),
                }
        except Exception as e:
            results["errors"][query_id] = {
                "error": str(e),
                "sql": sql[:200],
                "domain": query_item.get("domain", "unknown"),
            }

    engine.dispose()
    return results


# ═══════════════════════════════════════════════════════════════
# STAGE 1.5 — DETERMINISTIC GUARD RAIL
# Pattern: Invariant Assertion (Anthropic harness, 2024)
# ═══════════════════════════════════════════════════════════════

async def gate_calibration(entity_map: dict, client_config: dict) -> dict:
    """
    Deterministic pre-flight check — NO LLM cost, just cheap SQL COUNT queries.

    For every entity in entity_map that has a base_filter, verifies:
      1. COUNT(*) filtered > 0          (filter doesn't eliminate everything)
      2. COUNT(*) filtered < COUNT(*)   (filter actually filters something)
      3. SUM(amount) filtered not NULL  (transactional entities have real data)

    If any check fails, returns structured feedback that can be fed back to
    the Cartographer for correction (Reflexion pattern).

    Returns:
        {
            "passed": bool,
            "checks": [...],            # per-entity detail
            "failures": [...],          # structured feedback for Cartographer
            "entities_verified": int,
        }
    """
    connection_string = client_config["connection_string"]
    entities = entity_map.get("entities", {})

    checks: list[dict] = []
    failures: list[dict] = []

    try:
        engine = create_engine(connection_string)
    except Exception as e:
        return {
            "passed": False,
            "checks": [{"entity": "connection", "status": "error", "detail": str(e)}],
            "failures": [{"entity": "connection", "feedback": f"Cannot connect: {e}"}],
            "entities_verified": 0,
        }

    for entity_name, entity in entities.items():
        table = entity.get("table")
        base_filter = entity.get("base_filter", "").strip()

        if not table:
            continue

        # ── Check 1: COUNT total ──
        try:
            with engine.connect() as conn:
                total_count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        except Exception as e:
            checks.append({
                "entity": entity_name,
                "table": table,
                "check": "total_count",
                "status": "error",
                "detail": str(e),
            })
            failures.append({
                "entity": entity_name,
                "feedback": f"Cannot query table {table}: {e}. Verify table name.",
            })
            continue

        checks.append({
            "entity": entity_name,
            "table": table,
            "check": "total_count",
            "status": "pass",
            "value": total_count,
        })

        # ── Check 2 & 3: Only if base_filter is set ──
        if not base_filter:
            checks.append({
                "entity": entity_name,
                "table": table,
                "check": "base_filter_exists",
                "status": "warn",
                "detail": "No base_filter set — queries will include all rows (multi-tenant risk).",
            })
            continue

        # Check 2: COUNT with filter > 0
        try:
            with engine.connect() as conn:
                filtered_count = conn.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE {base_filter}")
                ).scalar()
        except Exception as e:
            checks.append({
                "entity": entity_name,
                "table": table,
                "check": "filtered_count",
                "status": "error",
                "detail": str(e),
            })
            failures.append({
                "entity": entity_name,
                "feedback": (
                    f"base_filter '{base_filter}' causes SQL error on {table}: {e}. "
                    "The filter syntax may be wrong for this database dialect."
                ),
            })
            continue

        if filtered_count == 0:
            checks.append({
                "entity": entity_name,
                "table": table,
                "check": "filtered_count_nonzero",
                "status": "fail",
                "value": filtered_count,
                "total": total_count,
            })
            failures.append({
                "entity": entity_name,
                "feedback": (
                    f"base_filter '{base_filter}' returns 0 rows from {table} "
                    f"(total rows: {total_count}). The filter value is likely wrong. "
                    "Run: SELECT DISTINCT <filter_column>, COUNT(*) FROM "
                    f"{table} GROUP BY 1 LIMIT 10 — to discover valid values."
                ),
            })
            continue

        if total_count > 0 and filtered_count >= total_count:
            checks.append({
                "entity": entity_name,
                "table": table,
                "check": "filter_actually_filters",
                "status": "warn",
                "value": filtered_count,
                "total": total_count,
                "coverage_pct": round(filtered_count / total_count * 100, 1),
            })
            # Not a hard failure — could legitimately be a single-tenant DB
        else:
            coverage_pct = round(filtered_count / total_count * 100, 1) if total_count else 0
            checks.append({
                "entity": entity_name,
                "table": table,
                "check": "filter_coverage",
                "status": "pass",
                "filtered": filtered_count,
                "total": total_count,
                "coverage_pct": coverage_pct,
            })

        # Check 3: SUM(amount) non-null for transactional entities
        amount_col = entity.get("key_columns", {}).get("amount_col")
        if amount_col and entity.get("type") == "TRANSACTIONAL":
            try:
                with engine.connect() as conn:
                    total_amount = conn.execute(
                        text(f"SELECT SUM({amount_col}) FROM {table} WHERE {base_filter}")
                    ).scalar()

                if total_amount is None or total_amount == 0:
                    checks.append({
                        "entity": entity_name,
                        "table": table,
                        "check": "amount_sum_nonzero",
                        "status": "warn",
                        "value": total_amount,
                        "detail": f"SUM({amount_col}) is null/zero with filter. Check filter + column.",
                    })
                else:
                    checks.append({
                        "entity": entity_name,
                        "table": table,
                        "check": "amount_sum_nonzero",
                        "status": "pass",
                        "value": float(total_amount),
                    })
            except Exception as e:
                checks.append({
                    "entity": entity_name,
                    "table": table,
                    "check": "amount_sum_nonzero",
                    "status": "error",
                    "detail": str(e),
                })

    engine.dispose()

    hard_failures = [c for c in checks if c["status"] == "fail"]
    errors = [c for c in checks if c["status"] == "error"]
    passed = len(hard_failures) == 0 and len(errors) == 0

    return {
        "passed": passed,
        "checks": checks,
        "failures": failures,
        "entities_verified": len([c for c in checks if c["status"] == "pass"]),
        "warnings": [c for c in checks if c["status"] == "warn"],
    }


# ═══════════════════════════════════════════════════════════════
# POST STAGE 2.5 — FROZEN BRIEF WITH PROVENANCE
# Pattern: Frozen Brief / Provenance-Tagged Handoff
# ═══════════════════════════════════════════════════════════════

def compute_baseline(query_results: dict) -> dict:
    """
    Compute a shared revenue baseline from executed query results.

    Every metric carries _provenance: source_query, row_count, executed_at.
    Agents that receive provenance can verify. Agents with bare numbers cannot.

    Structure:
        baseline["total_revenue"]           → flat value (backward compat)
        baseline["_provenance"]["total_revenue"] → {source_query, row_count, executed_at}

    Returns:
        Frozen brief dict injected into all Stage 3 agents and Stage 4 narrators.
        Agents MUST use these numbers as ground truth for EUR estimates.
    """
    now = datetime.now(timezone.utc).isoformat()
    results = query_results.get("results", {})

    baseline: dict[str, Any] = {
        # ── Flat values (backward compat + easy access) ──
        "data_available": False,
        "total_revenue": None,
        "num_invoices": None,
        "avg_invoice": None,
        "min_invoice": None,
        "max_invoice": None,
        "date_from": None,
        "date_to": None,
        "data_freshness_days": None,
        "distinct_customers": None,
        "total_outstanding_ar": None,
        "overdue_ar": None,
        "customers_with_debt": None,
        "source_queries": [],
        "warning": None,
        # ── Provenance: every metric points to its source ──
        "_provenance": {},
    }

    def _tag(metric: str, value: Any, source_query: str, row_count: int) -> None:
        """Record a metric value and its provenance together."""
        baseline[metric] = value
        baseline["_provenance"][metric] = {
            "source_query": source_query,
            "row_count": row_count,
            "executed_at": now,
            "confidence": "measured",
        }

    # ── Primary: total_revenue_summary ──
    if "total_revenue_summary" in results:
        rows = results["total_revenue_summary"].get("rows", [])
        row_count = results["total_revenue_summary"].get("row_count", 0)
        if rows:
            r = rows[0]
            baseline["data_available"] = True
            _tag("total_revenue",      _f(r.get("total_revenue")),      "total_revenue_summary", row_count)
            _tag("num_invoices",       _i(r.get("num_invoices")),        "total_revenue_summary", row_count)
            _tag("avg_invoice",        _f(r.get("avg_invoice")),         "total_revenue_summary", row_count)
            _tag("min_invoice",        _f(r.get("min_invoice")),         "total_revenue_summary", row_count)
            _tag("max_invoice",        _f(r.get("max_invoice")),         "total_revenue_summary", row_count)
            _tag("date_from",          str(r.get("date_from", "")),      "total_revenue_summary", row_count)
            _tag("date_to",            str(r.get("date_to", "")),        "total_revenue_summary", row_count)
            _tag("distinct_customers", _i(r.get("distinct_customers")),  "total_revenue_summary", row_count)
            baseline["source_queries"].append("total_revenue_summary")

    # ── Supplement: data_freshness ──
    if "data_freshness" in results:
        rows = results["data_freshness"].get("rows", [])
        row_count = results["data_freshness"].get("row_count", 0)
        if rows:
            r = rows[0]
            _tag("data_freshness_days", _i(r.get("days_since_latest")), "data_freshness", row_count)
            if not baseline["data_available"]:
                baseline["data_available"] = True
                _tag("num_invoices",       _i(r.get("total_records")),    "data_freshness", row_count)
                _tag("distinct_customers", _i(r.get("distinct_customers")), "data_freshness", row_count)
            baseline["source_queries"].append("data_freshness")

    # ── AR outstanding ──
    if "ar_outstanding_actual" in results:
        rows = results["ar_outstanding_actual"].get("rows", [])
        row_count = results["ar_outstanding_actual"].get("row_count", 0)
        if rows:
            r = rows[0]
            _tag("total_outstanding_ar", _f(r.get("total_outstanding")),  "ar_outstanding_actual", row_count)
            _tag("overdue_ar",           _f(r.get("overdue_amount")),     "ar_outstanding_actual", row_count)
            _tag("customers_with_debt",  _i(r.get("customers_with_debt")),"ar_outstanding_actual", row_count)
            baseline["source_queries"].append("ar_outstanding_actual")

    # ── Derive avg if not direct ──
    if baseline["avg_invoice"] is None and baseline["total_revenue"] and baseline["num_invoices"]:
        try:
            derived = baseline["total_revenue"] / baseline["num_invoices"]
            baseline["avg_invoice"] = derived
            baseline["_provenance"]["avg_invoice"] = {
                "source_query": "derived: total_revenue / num_invoices",
                "confidence": "inferred",
                "executed_at": now,
            }
        except (TypeError, ZeroDivisionError):
            pass

    # ── Data freshness warning ──
    freshness = baseline.get("data_freshness_days")
    if freshness and isinstance(freshness, int) and freshness > 14:
        baseline["warning"] = (
            f"⚠️ Data is {freshness} days old. All figures reflect the last available "
            "snapshot. Verify with source system before acting."
        )

    return baseline


def _f(val: Any) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _i(val: Any) -> int | None:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════
# STAGE 3 — PARALLEL ANALYSIS AGENTS
# ═══════════════════════════════════════════════════════════════

async def run_analysis_agents(
    query_results: dict, entity_map: dict, memory: dict | None, baseline: dict
) -> dict:
    """Run Analyst, Sentinel, Hunter in parallel. All receive the frozen brief."""
    analyst_task  = run_analyst( query_results, entity_map, memory, baseline)
    sentinel_task = run_sentinel(query_results, entity_map, memory, baseline)
    hunter_task   = run_hunter(  query_results, entity_map, memory, baseline)

    raw = await asyncio.gather(analyst_task, sentinel_task, hunter_task, return_exceptions=True)

    findings: dict[str, Any] = {}
    for result in raw:
        if isinstance(result, Exception):
            findings[f"error_{type(result).__name__}"] = {
                "agent": "unknown", "output": str(result), "error": True,
            }
        elif isinstance(result, dict):
            findings[result.get("agent", "unknown")] = result
        else:
            findings["unknown"] = {"agent": "unknown", "output": str(result)}

    return findings


# ═══════════════════════════════════════════════════════════════
# STAGE 3.5 — RECONCILIATION NODE
# Pattern: Debate + Judge (Arbiter) / Self-Consistency
# Source: Multi-Agent Collaboration Survey (arxiv:2501.06322, 2025)
#         Agent Drift paper (arxiv:2601.04170, 2025)
# ═══════════════════════════════════════════════════════════════

def _parse_findings_from_output(agent_data: dict) -> list[dict]:
    """Extract structured findings list from an agent's raw output."""
    if isinstance(agent_data.get("findings"), list):
        return agent_data["findings"]
    output = agent_data.get("output", "")
    if not output:
        return []
    for candidate in re.findall(r'\[\s*\{[\s\S]*?\}\s*\]', output):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                if any("id" in item or "value_eur" in item for item in parsed[:2]):
                    return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    return []


async def reconcile_swarm(findings: dict, baseline: dict) -> dict:
    """
    Detect and resolve numeric conflicts between Analyst, Sentinel, and Hunter.

    Algorithm:
      1. Parse structured findings from all 3 agents.
      2. Group by domain (financial / data_quality / sales).
      3. Within each domain, collect all value_eur values.
      4. If any pair differs by > CONFLICT_THRESHOLD (2x), invoke a Haiku
         Arbiter that:
           - Sees both findings + the frozen baseline
           - Selects the more defensible value WITH a citation
           - Explains the discrepancy in one sentence
      5. Attach a reconciliation_notes list to the findings dict.
         Narrators pick this up automatically.

    The Arbiter DOES NOT average values — it selects the one supported by
    the baseline or re-executable query evidence.
    """
    CONFLICT_THRESHOLD = 2.0  # flag when max/min ratio exceeds this

    # ── Collect all findings with value_eur ──
    all_findings: list[dict] = []
    for agent_name, agent_data in findings.items():
        if isinstance(agent_data, dict) and not agent_data.get("error"):
            for f in _parse_findings_from_output(agent_data):
                if isinstance(f, dict) and f.get("value_eur") is not None:
                    f["_agent"] = agent_name
                    all_findings.append(f)

    if not all_findings:
        findings["_reconciliation"] = {
            "ran": True, "conflicts_found": 0, "notes": [],
            "message": "No structured findings with value_eur to reconcile.",
        }
        return findings

    # ── Group by domain and headline keywords ──
    # Simple heuristic: cluster findings that share the same domain AND
    # at least one significant keyword (>5 chars) in their headline
    conflicts: list[dict] = []
    processed_pairs: set[frozenset] = set()

    for i, f1 in enumerate(all_findings):
        for j, f2 in enumerate(all_findings):
            if i >= j:
                continue
            pair_key = frozenset([f1.get("id",""), f2.get("id","")])
            if pair_key in processed_pairs:
                continue
            # Same agent → no conflict by definition
            if f1["_agent"] == f2["_agent"]:
                continue
            # Different domain → different topics, not a conflict
            if f1.get("domain") != f2.get("domain"):
                continue

            v1 = float(f1["value_eur"])
            v2 = float(f2["value_eur"])
            if v1 <= 0 or v2 <= 0:
                continue

            ratio = max(v1, v2) / min(v1, v2)
            if ratio < CONFLICT_THRESHOLD:
                continue

            # Check headline similarity (at least 1 significant word overlap)
            words1 = {w.lower() for w in re.findall(r'\b\w{5,}\b', f1.get("headline", ""))}
            words2 = {w.lower() for w in re.findall(r'\b\w{5,}\b', f2.get("headline", ""))}
            if not words1 & words2:
                continue

            processed_pairs.add(pair_key)
            conflicts.append({
                "finding_1": f1,
                "finding_2": f2,
                "ratio": round(ratio, 1),
                "domain": f1.get("domain"),
            })

    if not conflicts:
        findings["_reconciliation"] = {
            "ran": True,
            "conflicts_found": 0,
            "notes": [],
            "message": f"No numeric conflicts found among {len(all_findings)} findings (threshold: {CONFLICT_THRESHOLD}x).",
        }
        return findings

    # ── Invoke Haiku arbiter for each conflict ──
    reconciliation_notes: list[dict] = []

    baseline_summary = {
        k: v for k, v in baseline.items()
        if not k.startswith("_") and v is not None
    }

    for conflict in conflicts:
        f1 = conflict["finding_1"]
        f2 = conflict["finding_2"]

        arbiter_prompt = f"""
Two analysis agents disagree on the same metric by {conflict['ratio']}x.
Your job: select the more defensible value and explain the discrepancy in one sentence.

FROZEN BASELINE (measured from database — ground truth):
{json.dumps(baseline_summary, indent=2, default=str)}

FINDING 1 (from {f1['_agent']}):
  headline: {f1.get('headline')}
  value_eur: {f1.get('value_eur')}
  evidence: {f1.get('evidence', 'not provided')}
  value_confidence: {f1.get('value_confidence', 'unknown')}

FINDING 2 (from {f2['_agent']}):
  headline: {f2.get('headline')}
  value_eur: {f2.get('value_eur')}
  evidence: {f2.get('evidence', 'not provided')}
  value_confidence: {f2.get('value_confidence', 'unknown')}

Respond with valid JSON only:
{{
  "selected_value": <number>,
  "selected_agent": "<agent name>",
  "discrepancy_explanation": "<one sentence: why they differ>",
  "confidence": "high|medium|low"
}}
"""

        arbiter_options = ClaudeAgentOptions(model="haiku", max_turns=3)
        arbiter_output = []

        try:
            async for msg in agent_query(prompt=arbiter_prompt, options=arbiter_options):
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            arbiter_output.append(block.text)
        except Exception as e:
            arbiter_output = [f'{{"error": "{e}"}}']

        raw_response = "\n".join(arbiter_output)
        arbitration: dict = {}
        try:
            json_match = re.search(r'\{[\s\S]*\}', raw_response)
            if json_match:
                arbitration = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            arbitration = {"error": "Could not parse arbiter response", "raw": raw_response[:200]}

        reconciliation_notes.append({
            "finding_ids": [f1.get("id"), f2.get("id")],
            "agents": [f1["_agent"], f2["_agent"]],
            "domain": conflict["domain"],
            "ratio": conflict["ratio"],
            "values": {f1["_agent"]: f1["value_eur"], f2["_agent"]: f2["value_eur"]},
            "arbitration": arbitration,
        })

    findings["_reconciliation"] = {
        "ran": True,
        "conflicts_found": len(conflicts),
        "notes": reconciliation_notes,
        "message": (
            f"Resolved {len(reconciliation_notes)} conflict(s) across "
            f"{len(all_findings)} findings."
        ),
    }

    return findings


# ═══════════════════════════════════════════════════════════════
# STAGE 4 — NARRATORS
# ═══════════════════════════════════════════════════════════════

async def run_narrators(
    findings: dict,
    entity_map: dict,
    memory: dict | None,
    client_config: dict,
    baseline: dict,
    query_results: dict,
) -> dict[str, str]:
    """
    Run all four narrator agents sequentially to produce audience-specific reports.

    Narrators receive:
      - findings: swarm output including _reconciliation notes
      - baseline: frozen brief with provenance
      - query_results: raw rows for customer lists / AR tables
    """
    from valinor.agents.narrators.ceo        import narrate_ceo
    from valinor.agents.narrators.controller import narrate_controller
    from valinor.agents.narrators.sales      import narrate_sales
    from valinor.agents.narrators.executive  import narrate_executive

    reports: dict[str, str] = {}

    for name, fn, extra_kwargs in [
        ("briefing_ceo",       narrate_ceo,        {}),
        ("reporte_controller", narrate_controller, {"query_results": query_results}),
        ("reporte_ventas",     narrate_sales,      {"query_results": query_results}),
        ("reporte_ejecutivo",  narrate_executive,  {}),
    ]:
        try:
            reports[name] = await fn(
                findings, entity_map, memory, client_config, baseline, **extra_kwargs
            )
        except Exception as e:
            reports[name] = f"# Error generating {name}\n\n{e}"

    return reports
