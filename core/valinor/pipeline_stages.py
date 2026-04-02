"""
Pipeline Stages — Query execution, calibration gate, baseline computation, and deltas.

Extracted from pipeline.py for better modularity.

Contains:
  - execute_queries      Stage 2.5: run SQL against DB
  - gate_calibration     Stage 1.5: verify base_filter before analysis runs
  - compute_baseline     post-2.5: build provenance-tagged shared context
  - compute_degradation_level   pipeline degradation assessment
  - compute_mom_delta    post-2.5b: month-over-month delta computation
"""

import re
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import create_engine, text

_pipeline_logger = structlog.get_logger()

# ── SQL Safety ─────────────────────────────────────────────────────
_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _is_safe_identifier(name: str) -> bool:
    """Validate that a string is a safe SQL identifier (table/column name)."""
    return bool(name and _SAFE_IDENTIFIER_RE.match(name) and len(name) <= 128)


# ═══════════════════════════════════════════════════════════════
# STAGE 2.5 — EXECUTE QUERIES
# ═══════════════════════════════════════════════════════════════

async def execute_queries(query_pack: dict, client_config: dict, query_timeout_ms: int = 30000) -> dict:
    """
    Execute all queries from the query pack against the client database.

    Uses a single connection with REPEATABLE READ isolation so that all queries
    see the same database snapshot (prevents phantom reads across queries).
    Falls back to the default isolation level if REPEATABLE READ is not supported
    (e.g. some MySQL configs, SQLite).

    Returns:
        Dict with 'results' (successful), 'errors' (failed), and 'snapshot_timestamp'.
    """
    connection_string = client_config["connection_string"]
    engine = create_engine(connection_string)
    results: dict[str, Any] = {
        "results": {},
        "errors": {},
        "snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Apply search_path from config overrides (e.g. playground tests)
    db_schema = client_config.get("db_schema")

    def _run_queries(conn: Any) -> None:
        # Set schema search path if configured
        if db_schema:
            try:
                conn.execute(text(f"SET search_path TO {db_schema}, public"))
            except Exception:
                pass  # Non-PostgreSQL databases ignore this

        for query_item in query_pack.get("queries", []):
            query_id = query_item["id"]
            sql = query_item["sql"]
            try:
                # Try to set per-query timeout (PostgreSQL only, harmless on others)
                try:
                    conn.execute(text(f"SET LOCAL statement_timeout = '{query_timeout_ms}'"))
                except Exception:
                    pass  # Non-PostgreSQL databases ignore this

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
                error_type = "timeout" if "cancel" in str(e).lower() or "timeout" in str(e).lower() else "error"
                results["errors"][query_id] = {
                    "error": str(e),
                    "error_type": error_type,
                    "sql": sql[:200],
                    "domain": query_item.get("domain", "unknown"),
                }

    try:
        # Attempt REPEATABLE READ isolation — all queries share one snapshot
        try:
            with engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as conn:
                _run_queries(conn)
        except Exception as iso_err:
            # REPEATABLE READ not supported — fall back but flag degradation
            _pipeline_logger.warning(
                "REPEATABLE READ not supported, falling back to default isolation. "
                "Queries may see inconsistent snapshots.",
                error=str(iso_err),
            )
            results["_isolation_degraded"] = True
            results["_isolation_warning"] = (
                "REPEATABLE READ isolation unavailable. Queries ran without "
                "snapshot consistency — values may reflect mid-transaction state."
            )
            with engine.connect() as conn:
                _run_queries(conn)
    finally:
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

        if not table or not _is_safe_identifier(table):
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
        if amount_col and _is_safe_identifier(amount_col) and entity.get("type") == "TRANSACTIONAL":
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

    # ── FK orphan check — entity_map-driven, not hardcoded ───────────
    # Check FK relationships declared in entity_map
    for entity_name, entity in entities.items():
        fk_refs = entity.get("key_columns", {})
        entity_table = entity.get("table", "")
        if not entity_table or not _is_safe_identifier(entity_table):
            continue
        for col_key, col_name in fk_refs.items():
            if not col_key.endswith("_fk") or not col_name:
                continue
            if not _is_safe_identifier(col_name):
                continue
            # Find the referenced entity's table
            ref_entity_type = col_key.replace("_fk", "")
            for ref_name, ref_entity in entities.items():
                if ref_entity_type in ref_name.lower() or ref_entity.get("type") == "MASTER":
                    ref_table = ref_entity.get("table", "")
                    ref_pk = ref_entity.get("key_columns", {}).get("pk")
                    if ref_table and ref_pk and _is_safe_identifier(ref_table) and _is_safe_identifier(ref_pk):
                        try:
                            with engine.connect() as conn:
                                orphan_sql = (
                                    f"SELECT COUNT(*) FROM {entity_table} src "
                                    f"LEFT JOIN {ref_table} ref ON src.{col_name} = ref.{ref_pk} "
                                    f"WHERE ref.{ref_pk} IS NULL AND src.{col_name} IS NOT NULL"
                                )
                                orphan_count = conn.execute(text(orphan_sql)).scalar() or 0
                                if orphan_count > 0:
                                    checks.append({
                                        "entity": f"{entity_name}_fk_{col_key}",
                                        "status": "warning",
                                        "detail": f"{orphan_count} orphaned rows in {entity_table}.{col_name} → {ref_table}.{ref_pk}",
                                    })
                        except Exception as e:
                            _pipeline_logger.warning(
                                "FK orphan check failed",
                                entity=entity_name, fk=col_name, error=str(e),
                            )
                        break  # Only check first matching ref entity

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


def compute_baseline(query_results: dict) -> dict:
    """
    Compute a shared revenue baseline from executed query results.

    Every metric carries _provenance: source_query, row_count, executed_at.
    Agents that receive provenance can verify. Agents with bare numbers cannot.

    Structure:
        baseline["total_revenue"]           -> flat value (backward compat)
        baseline["_provenance"]["total_revenue"] -> {source_query, row_count, executed_at}

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
            f"\u26a0\ufe0f Data is {freshness} days old. All figures reflect the last available "
            "snapshot. Verify with source system before acting."
        )

    # ── Degradation level ──
    baseline["_degradation_level"] = compute_degradation_level(query_results)

    # ── Error / timeout summary ──
    errors = query_results.get("errors", {})
    if errors:
        timeout_count = sum(1 for e in errors.values() if isinstance(e, dict) and e.get("error_type") == "timeout")
        baseline["_query_errors"] = len(errors)
        baseline["_query_timeouts"] = timeout_count

    # ── NULL-rate metadata: degrade confidence for NULL-heavy columns ──
    null_analysis = results.get("null_analysis", {}).get("rows", [])
    if null_analysis:
        for row in null_analysis:
            col_name = row.get("column_name", "")
            null_rate = row.get("null_rate")
            if null_rate is None:
                continue
            try:
                null_rate_f = float(null_rate)
            except (TypeError, ValueError):
                continue

            # Find which baseline metrics depend on this column
            # and degrade their provenance
            for metric_key, prov in baseline["_provenance"].items():
                if isinstance(prov, dict) and prov.get("confidence") == "measured":
                    # Degrade based on NULL rate
                    if null_rate_f > 0.50:
                        prov["confidence"] = "degraded"
                        prov["null_rate"] = null_rate_f
                    elif null_rate_f > 0.20:
                        prov["confidence"] = "partial"
                        prov["null_rate"] = null_rate_f

    return baseline


# ═══════════════════════════════════════════════════════════════
# PIPELINE DEGRADATION LEVEL
# ═══════════════════════════════════════════════════════════════


def compute_degradation_level(query_results: dict) -> str:
    """
    Compute pipeline degradation level based on query execution results.

    Returns:
        "full": All critical queries succeeded
        "degraded": Revenue data OK but some non-critical queries failed
        "minimal": Only metadata queries succeeded
        "failed": No queries succeeded
    """
    results = query_results.get("results", {})
    errors = query_results.get("errors", {})

    if not results:
        return "failed"

    # Critical queries — pipeline cannot produce useful output without these
    critical_queries = {"total_revenue_summary"}
    # Important but not critical
    important_queries = {"ar_outstanding_actual", "customer_concentration", "aging_analysis"}

    has_critical = bool(critical_queries & set(results.keys()))
    has_important = bool(important_queries & set(results.keys()))

    error_count = len(errors)
    timeout_count = sum(1 for e in errors.values() if isinstance(e, dict) and e.get("error_type") == "timeout")

    if not has_critical:
        # Check if at least data_freshness or some metadata query succeeded
        if results:
            return "minimal"
        return "failed"

    if has_critical and has_important and error_count == 0:
        return "full"

    return "degraded"


# ═══════════════════════════════════════════════════════════════
# STAGE POST-2.5B — MoM DELTA COMPUTATION
# ═══════════════════════════════════════════════════════════════


def compute_mom_delta(
    current_baseline: dict,
    previous_baseline: dict | None = None,
) -> dict:
    """
    Compare current analysis baseline with previous period to detect trends.

    Returns a dict with:
      - deltas: per-metric change (absolute and percentage)
      - alerts: significant changes that warrant attention
      - trend_summary: human-readable summary for narrator injection

    This converts a static snapshot into a monitoring service.
    """
    if not previous_baseline or not previous_baseline.get("data_available"):
        return {
            "has_previous": False,
            "deltas": {},
            "alerts": [],
            "trend_summary": "No previous period data available for comparison.",
        }

    TRACKED_METRICS = {
        "total_revenue": {"label": "Revenue", "unit": "EUR", "alert_pct": 10},
        "num_invoices": {"label": "Invoice count", "unit": "count", "alert_pct": 15},
        "avg_invoice": {"label": "Avg invoice", "unit": "EUR", "alert_pct": 15},
        "distinct_customers": {"label": "Active customers", "unit": "count", "alert_pct": 10},
        "total_outstanding_ar": {"label": "Outstanding AR", "unit": "EUR", "alert_pct": 15},
        "overdue_ar": {"label": "Overdue AR", "unit": "EUR", "alert_pct": 20},
        "customers_with_debt": {"label": "Customers with debt", "unit": "count", "alert_pct": 15},
        "data_freshness_days": {"label": "Data freshness", "unit": "days", "alert_pct": 50},
    }

    deltas: dict[str, dict] = {}
    alerts: list[dict] = []

    for metric, meta in TRACKED_METRICS.items():
        curr_val = current_baseline.get(metric)
        prev_val = previous_baseline.get(metric)

        if curr_val is None or prev_val is None:
            continue

        try:
            curr_f = float(curr_val)
            prev_f = float(prev_val)
        except (TypeError, ValueError):
            continue

        abs_delta = curr_f - prev_f
        pct_delta = ((abs_delta / abs(prev_f)) * 100) if prev_f != 0 else None

        delta_entry = {
            "current": curr_f,
            "previous": prev_f,
            "absolute_change": abs_delta,
            "pct_change": round(pct_delta, 2) if pct_delta is not None else None,
            "direction": "up" if abs_delta > 0 else ("down" if abs_delta < 0 else "flat"),
        }
        deltas[metric] = delta_entry

        if pct_delta is not None and abs(pct_delta) >= meta["alert_pct"]:
            direction_word = "increased" if abs_delta > 0 else "decreased"
            severity = "critical" if abs(pct_delta) >= meta["alert_pct"] * 2 else "warning"
            alerts.append({
                "metric": metric,
                "label": meta["label"],
                "severity": severity,
                "message": (
                    f"{meta['label']} {direction_word} by {abs(pct_delta):.1f}% "
                    f"({prev_f:,.0f} \u2192 {curr_f:,.0f} {meta['unit']})"
                ),
                "pct_change": pct_delta,
            })

    # Build human-readable trend summary
    if not deltas:
        summary = "No comparable metrics between periods."
    else:
        alerts.sort(key=lambda a: abs(a.get("pct_change", 0)), reverse=True)
        summary_parts = []
        if alerts:
            summary_parts.append(f"**{len(alerts)} significant change(s) detected:**")
            for alert in alerts[:5]:
                icon = "\u2191" if alert["pct_change"] > 0 else "\u2193"
                summary_parts.append(f"  - {icon} {alert['message']}")
        else:
            summary_parts.append("All metrics within normal variation vs previous period.")
        stable_count = len(deltas) - len(alerts)
        if stable_count > 0:
            summary_parts.append(f"  {stable_count} metric(s) stable.")
        summary = "\n".join(summary_parts)

    return {
        "has_previous": True,
        "deltas": deltas,
        "alerts": alerts,
        "trend_summary": summary,
    }
