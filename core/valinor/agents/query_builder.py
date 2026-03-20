"""
Query Builder — Stage 2: Deterministic SQL Generation.

NOT an agent — pure Python. Takes entity_map and generates
parameterized SQL queries from templates. Zero LLM cost.

Key design:
- Each template uses {entity_filter} placeholders (e.g., {invoices_filter})
- If entity.base_filter is set, it is injected as "AND <filter>"
- Default is empty string — safe for DBs without multi-tenant filters
- Value queries are added to give agents actual EUR numbers, not guesses
"""

import json
from typing import Any


# ═══════════════════════════════════════════════════════════════
# QUERY TEMPLATES
# Each template uses {X_filter} placeholders injected by build_queries.
# Default: empty string (no extra filter). Set via entity.base_filter.
# ═══════════════════════════════════════════════════════════════

QUERY_TEMPLATES = {
    # ─── VALUE QUERIES (run first — give agents actual EUR numbers) ───

    "total_revenue_summary": {
        "domain": "financial",
        "requires": ["invoices"],
        "description": "Total revenue for the period — single source of truth for all EUR estimates",
        "template": """
            SELECT
                COUNT(*) as num_invoices,
                SUM({amount_col}) as total_revenue,
                AVG({amount_col}) as avg_invoice,
                MIN({amount_col}) as min_invoice,
                MAX({amount_col}) as max_invoice,
                MIN({invoice_date}) as date_from,
                MAX({invoice_date}) as date_to,
                COUNT(DISTINCT {customer_fk}) as distinct_customers
            FROM {invoice_table}
            WHERE {invoice_date} >= '{start_date}'
            AND {invoice_date} <= '{end_date}'
            {invoices_filter}
        """,
    },

    "ar_outstanding_actual": {
        "domain": "credit",
        "requires": ["payments"],
        "description": "Actual sum of outstanding AR — real number not estimate",
        "template": """
            SELECT
                COUNT(*) as total_schedules,
                COUNT(CASE WHEN {outstanding_amount} > 0 THEN 1 END) as unpaid_count,
                SUM({outstanding_amount}) as total_outstanding,
                AVG({outstanding_amount}) as avg_outstanding,
                COUNT(CASE WHEN {due_date} < CURRENT_DATE AND {outstanding_amount} > 0 THEN 1 END) as overdue_count,
                SUM(CASE WHEN {due_date} < CURRENT_DATE AND {outstanding_amount} > 0 THEN {outstanding_amount} ELSE 0 END) as overdue_amount,
                COUNT(DISTINCT {customer_id}) as customers_with_debt
            FROM {payment_table}
            WHERE {outstanding_amount} > 0
            {payments_filter}
        """,
    },

    "dormant_customer_list": {
        "domain": "sales",
        "requires": ["invoices", "customers"],
        "description": "Real customer names and IDs for dormant accounts — no guessing needed",
        "template": """
            SELECT
                cust.{customer_pk} as customer_id,
                cust.{customer_name} as customer_name,
                MAX(inv.{invoice_date}) as last_purchase,
                CURRENT_DATE - MAX(inv.{invoice_date}) as days_inactive,
                COUNT(inv.{invoice_pk}) as total_invoices,
                SUM(inv.{amount_col}) as lifetime_revenue,
                AVG(inv.{amount_col}) as avg_invoice_value
            FROM {customer_table} cust
            JOIN {invoice_table} inv ON cust.{customer_pk} = inv.{customer_fk}
            WHERE 1=1
            {invoices_filter}
            {customers_filter}
            GROUP BY cust.{customer_pk}, cust.{customer_name}
            HAVING MAX(inv.{invoice_date}) < CURRENT_DATE - INTERVAL '90 days'
            ORDER BY lifetime_revenue DESC
            LIMIT 30
        """,
    },

    "never_invoiced_customers": {
        "domain": "sales",
        "requires": ["invoices", "customers"],
        "description": "Customers registered but never purchased — actual IDs and names",
        "template": """
            SELECT
                cust.{customer_pk} as customer_id,
                cust.{customer_name} as customer_name
            FROM {customer_table} cust
            WHERE cust.{customer_pk} NOT IN (
                SELECT DISTINCT {customer_fk}
                FROM {invoice_table}
                WHERE {customer_fk} IS NOT NULL
                {invoices_filter}
            )
            {customers_filter}
            ORDER BY cust.{customer_name}
        """,
    },

    "orders_without_invoices": {
        "domain": "financial",
        "requires": ["orders", "invoices"],
        "description": "Count and value of orders with no matching invoice",
        "template": """
            SELECT
                COUNT(ord.{order_pk}) as unbilled_orders,
                SUM(ord.{order_amount}) as potential_unbilled_value,
                AVG(ord.{order_amount}) as avg_order_value,
                MIN(ord.{order_date}) as oldest_unbilled,
                MAX(ord.{order_date}) as newest_unbilled
            FROM {order_table} ord
            WHERE ord.{order_pk} NOT IN (
                SELECT DISTINCT {order_fk}
                FROM {invoice_table}
                WHERE {order_fk} IS NOT NULL
                {invoices_filter}
            )
            AND ord.{order_date} >= '{start_date}'
            AND ord.{order_date} <= '{end_date}'
            {orders_filter}
        """,
    },

    # ─── FINANCIAL DOMAIN ───

    "revenue_by_period": {
        "domain": "financial",
        "requires": ["invoices"],
        "description": "Monthly revenue evolution",
        "template": """
            SELECT
                DATE_TRUNC('month', {invoice_date}) as period,
                COUNT(*) as num_invoices,
                SUM({amount_col}) as revenue,
                COUNT(DISTINCT {customer_fk}) as active_customers
            FROM {invoice_table}
            WHERE {invoice_date} >= '{start_date}'
            AND {invoice_date} <= '{end_date}'
            {invoices_filter}
            GROUP BY 1
            ORDER BY 1
        """,
    },

    "customer_concentration": {
        "domain": "financial",
        "requires": ["invoices", "customers"],
        "description": "Revenue concentration by customer (Pareto)",
        "template": """
            SELECT
                cust.{customer_pk} as customer_id,
                cust.{customer_name} as customer_name,
                COUNT(*) as num_invoices,
                SUM(inv.{amount_col}) as total_revenue,
                SUM(inv.{amount_col}) * 100.0 / NULLIF(
                    (SELECT SUM({amount_col}) FROM {invoice_table}
                     WHERE {invoice_date} >= '{start_date}'
                     AND {invoice_date} <= '{end_date}'
                     {invoices_filter}), 0
                ) as pct_revenue
            FROM {invoice_table} inv
            JOIN {customer_table} cust ON inv.{customer_fk} = cust.{customer_pk}
            WHERE inv.{invoice_date} >= '{start_date}'
            AND inv.{invoice_date} <= '{end_date}'
            {invoices_filter}
            {customers_filter}
            GROUP BY 1, 2
            ORDER BY total_revenue DESC
        """,
    },

    "revenue_yoy": {
        "domain": "financial",
        "requires": ["invoices"],
        "description": "Year-over-year revenue comparison",
        "template": """
            SELECT
                EXTRACT(YEAR FROM {invoice_date}) as year,
                EXTRACT(MONTH FROM {invoice_date}) as month,
                COUNT(*) as num_invoices,
                SUM({amount_col}) as revenue
            FROM {invoice_table}
            WHERE {invoice_date} >= '{start_date}'::date - INTERVAL '1 year'
            AND {invoice_date} <= '{end_date}'
            {invoices_filter}
            GROUP BY 1, 2
            ORDER BY 1, 2
        """,
    },

    # ─── CREDIT DOMAIN ───

    "aging_analysis": {
        "domain": "credit",
        "requires": ["payments"],
        "description": "Aging buckets for unpaid invoices",
        "template": """
            SELECT
                CASE
                    WHEN CURRENT_DATE - {due_date} <= 0 THEN 'not_due'
                    WHEN CURRENT_DATE - {due_date} <= 30 THEN '0-30d'
                    WHEN CURRENT_DATE - {due_date} <= 60 THEN '31-60d'
                    WHEN CURRENT_DATE - {due_date} <= 90 THEN '61-90d'
                    WHEN CURRENT_DATE - {due_date} <= 180 THEN '91-180d'
                    WHEN CURRENT_DATE - {due_date} <= 365 THEN '181-365d'
                    ELSE '>365d'
                END as tramo,
                COUNT(*) as num_payments,
                COUNT(DISTINCT {customer_id}) as num_customers,
                SUM({outstanding_amount}) as total_amount
            FROM {payment_table}
            WHERE {outstanding_amount} > 0
            {payments_filter}
            GROUP BY 1
            ORDER BY 2
        """,
    },

    "top_debtors": {
        "domain": "credit",
        "requires": ["payments", "customers"],
        "description": "Largest outstanding debts by customer",
        "template": """
            SELECT
                cust.{customer_pk} as customer_id,
                cust.{customer_name} as customer_name,
                SUM({outstanding_amount}) as total_outstanding,
                COUNT(*) as num_unpaid,
                MIN({due_date}) as oldest_due_date,
                CURRENT_DATE - MIN({due_date}) as max_days_overdue
            FROM {payment_table} pay
            JOIN {customer_table} cust ON pay.{customer_id} = cust.{customer_pk}
            WHERE pay.{outstanding_amount} > 0
            {payments_filter}
            {customers_filter}
            GROUP BY 1, 2
            ORDER BY total_outstanding DESC
            LIMIT 20
        """,
    },

    # ─── SALES DOMAIN ───

    "customer_retention": {
        "domain": "sales",
        "requires": ["invoices", "customers"],
        "description": "Customer retention / churn analysis",
        "template": """
            WITH period_current AS (
                SELECT DISTINCT {customer_fk} as customer_id
                FROM {invoice_table}
                WHERE {invoice_date} >= '{start_date}'
                AND {invoice_date} <= '{end_date}'
                {invoices_filter}
            ),
            period_previous AS (
                SELECT DISTINCT {customer_fk} as customer_id
                FROM {invoice_table}
                WHERE {invoice_date} >= '{start_date}'::date - INTERVAL '1 year'
                AND {invoice_date} < '{start_date}'
                {invoices_filter}
            )
            SELECT
                (SELECT COUNT(*) FROM period_previous) as prev_customers,
                (SELECT COUNT(*) FROM period_current) as curr_customers,
                (SELECT COUNT(*) FROM period_current
                 WHERE customer_id IN (SELECT customer_id FROM period_previous)) as retained,
                (SELECT COUNT(*) FROM period_previous
                 WHERE customer_id NOT IN (SELECT customer_id FROM period_current)) as churned,
                (SELECT COUNT(*) FROM period_current
                 WHERE customer_id NOT IN (SELECT customer_id FROM period_previous)) as new_customers
        """,
    },

    # ─── DATA QUALITY DOMAIN ───

    "null_analysis": {
        "domain": "data_quality",
        "requires": ["invoices"],
        "description": "Null rate analysis for key invoice fields",
        "template": """
            SELECT
                COUNT(*) as total_rows,
                SUM(CASE WHEN {invoice_date} IS NULL THEN 1 ELSE 0 END) as null_dates,
                SUM(CASE WHEN {amount_col} IS NULL THEN 1 ELSE 0 END) as null_amounts,
                SUM(CASE WHEN {customer_fk} IS NULL THEN 1 ELSE 0 END) as null_customers,
                ROUND(SUM(CASE WHEN {invoice_date} IS NULL THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) as pct_null_dates,
                ROUND(SUM(CASE WHEN {amount_col} IS NULL THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*), 0), 2) as pct_null_amounts
            FROM {invoice_table}
            {invoices_filter_where}
        """,
    },

    "duplicate_detection": {
        "domain": "data_quality",
        "requires": ["invoices"],
        "description": "Detect potential duplicate invoices",
        "template": """
            SELECT
                {invoice_date},
                {customer_fk},
                {amount_col},
                COUNT(*) as occurrences
            FROM {invoice_table}
            WHERE {invoice_date} >= '{start_date}'
            AND {invoice_date} <= '{end_date}'
            {invoices_filter}
            GROUP BY 1, 2, 3
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC
            LIMIT 50
        """,
    },

    "data_freshness": {
        "domain": "data_quality",
        "requires": ["invoices"],
        "description": "Check data freshness — when was the latest record?",
        "template": """
            SELECT
                MIN({invoice_date}) as earliest_record,
                MAX({invoice_date}) as latest_record,
                CURRENT_DATE - MAX({invoice_date}) as days_since_latest,
                COUNT(*) as total_records,
                COUNT(DISTINCT {customer_fk}) as distinct_customers
            FROM {invoice_table}
            {invoices_filter_where}
        """,
    },

    # ─── SEASONALITY DOMAIN ───

    "monthly_seasonality": {
        "domain": "financial",
        "requires": ["invoices"],
        "description": "Monthly revenue pattern to detect seasonality",
        "template": """
            SELECT
                EXTRACT(MONTH FROM {invoice_date}) as month,
                COUNT(*) as num_years_data,
                AVG(monthly_revenue) as avg_monthly_revenue,
                MIN(monthly_revenue) as min_monthly_revenue,
                MAX(monthly_revenue) as max_monthly_revenue
            FROM (
                SELECT
                    DATE_TRUNC('month', {invoice_date}) as month_date,
                    EXTRACT(MONTH FROM {invoice_date}) as month_num,
                    SUM({amount_col}) as monthly_revenue
                FROM {invoice_table}
                WHERE {invoice_date} >= '{start_date}'::date - INTERVAL '2 years'
                AND {invoice_date} <= '{end_date}'
                {invoices_filter}
                GROUP BY 1, 2
            ) monthly
            GROUP BY EXTRACT(MONTH FROM month_date)
            ORDER BY 1
        """,
    },
}


def _get_entity_filter(entity: dict, prefix: str = "AND") -> str:
    """
    Extract the base_filter from an entity definition.

    Returns: SQL fragment with prefix (e.g., "AND issotrx = 'Y'")
    or empty string if no filter defined.
    """
    base_filter = entity.get("base_filter", "").strip()
    if not base_filter:
        return ""
    # Avoid double-prefixing
    if base_filter.upper().startswith("AND "):
        return base_filter
    return f"{prefix} {base_filter}"


def _find_relationship_column(entity_map: dict, from_entity: str, to_entity: str) -> str | None:
    """Find the column linking from_entity to to_entity via relationships."""
    for rel in entity_map.get("relationships", []):
        if rel.get("from") == from_entity and rel.get("to") == to_entity:
            return rel.get("via")
        if rel.get("from") == to_entity and rel.get("to") == from_entity:
            return rel.get("via")
    return None


def build_queries(entity_map: dict, period: dict) -> dict:
    """
    Takes entity_map + period config.
    Returns executable query_pack with SQL ready to run.

    Args:
        entity_map: Dict with 'entities' key mapping entity names to their config.
        period: Dict with 'start', 'end', 'label' keys.

    Returns:
        Dict with 'queries' (list of ready queries) and 'skipped' (list of skipped templates).
    """
    query_pack: dict[str, list] = {"queries": [], "skipped": []}
    entities = entity_map.get("entities", {})

    for query_id, template_config in QUERY_TEMPLATES.items():
        required = template_config["requires"]

        # Check if we have all required entities
        if not all(req in entities for req in required):
            missing = [r for r in required if r not in entities]
            query_pack["skipped"].append({
                "id": query_id,
                "domain": template_config["domain"],
                "reason": f"Missing entities: {missing}",
            })
            continue

        # Build params from entity map key_columns
        params: dict[str, Any] = {}

        for entity_name in required:
            entity = entities[entity_name]
            # Add all key_columns for this entity
            for col_key, col_val in entity.get("key_columns", {}).items():
                params[col_key] = col_val
            # Add table name variants (singular and plural)
            singular = entity_name.rstrip("s")
            params[f"{singular}_table"] = entity.get("table", "")
            params[f"{entity_name}_table"] = entity.get("table", "")

        # Add period params
        params["start_date"] = period["start"]
        params["end_date"] = period["end"]

        # ── Inject entity filters from base_filter ──
        # Default all filter slots to empty string (safe no-op)
        for entity_name in ["invoices", "customers", "payments", "products",
                             "orders", "invoice_lines"]:
            filter_key = f"{entity_name}_filter"
            params[filter_key] = ""
            # "WHERE-style" variant for queries that have no existing WHERE clause
            params[f"{entity_name}_filter_where"] = ""

        # Populate from entity base_filter if defined
        for entity_name in required:
            entity = entities[entity_name]
            frag = _get_entity_filter(entity)
            if frag:
                params[f"{entity_name}_filter"] = frag
                params[f"{entity_name}_filter_where"] = f"WHERE {frag.lstrip('AND ').lstrip('and ')}"

        # ── Special: inject relationship FK for orders_without_invoices ──
        if query_id == "orders_without_invoices":
            order_fk = _find_relationship_column(entity_map, "invoices", "orders")
            if not order_fk:
                # Try common column names as fallback
                order_fk = entities.get("invoices", {}).get("key_columns", {}).get(
                    "order_fk", entities.get("orders", {}).get("key_columns", {}).get("order_pk")
                )
            if not order_fk:
                query_pack["skipped"].append({
                    "id": query_id,
                    "domain": template_config["domain"],
                    "reason": "Cannot determine order FK in invoice table (no relationship defined)",
                })
                continue
            params["order_fk"] = order_fk

        # ── Special: payment outstanding column ──
        if query_id in ("ar_outstanding_actual", "aging_analysis", "top_debtors"):
            payment_entity = entities.get("payments", {})
            if not params.get("outstanding_amount"):
                # Try common column names
                outstanding = payment_entity.get("key_columns", {}).get(
                    "outstanding_amount",
                    payment_entity.get("key_columns", {}).get("outstandingamt", "outstandingamt")
                )
                params["outstanding_amount"] = outstanding
            if not params.get("due_date"):
                params["due_date"] = payment_entity.get("key_columns", {}).get(
                    "due_date",
                    payment_entity.get("key_columns", {}).get("duedate", "duedate")
                )
            if not params.get("customer_id"):
                params["customer_id"] = payment_entity.get("key_columns", {}).get(
                    "customer_id",
                    payment_entity.get("key_columns", {}).get("customer_fk", "c_bpartner_id")
                )

        # ── Special: invoice_pk for dormant_customer_list ──
        if query_id in ("dormant_customer_list",):
            invoice_entity = entities.get("invoices", {})
            if not params.get("invoice_pk"):
                params["invoice_pk"] = invoice_entity.get("key_columns", {}).get(
                    "invoice_pk",
                    invoice_entity.get("key_columns", {}).get("invoice_id", "c_invoice_id")
                )

        # Try to format the SQL template
        try:
            sql = template_config["template"].format(**params)
            query_pack["queries"].append({
                "id": query_id,
                "domain": template_config["domain"],
                "description": template_config["description"],
                "sql": sql.strip(),
                "params": {k: v for k, v in params.items() if not k.endswith("_filter")},
            })
        except KeyError as e:
            query_pack["skipped"].append({
                "id": query_id,
                "domain": template_config["domain"],
                "reason": f"Missing parameter: {e} — check entity key_columns in entity_map",
            })

    return query_pack
