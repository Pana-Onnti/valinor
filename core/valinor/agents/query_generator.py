"""
Query Generator — KG-guided dynamic SQL construction.

Replaces static template interpolation with programmatic SQL building.
Uses the Knowledge Graph for:
  - Table names from entity_map (not hardcoded)
  - JOIN paths via BFS (not guessed)
  - Required filters from base_filter (not forgotten)
  - Column disambiguation (not ambiguous)

Keeps query_builder.py as fallback for when dynamic generation fails.

Architecture references:
  - QueryWeaver (FalkorDB): KG -> SQL via graph traversal
  - MAC-SQL: Multi-agent decomposition of complex queries
  - TAG (Berkeley): Table-Augmented Generation
"""

from __future__ import annotations

from enum import Enum
from typing import Any

import structlog

from valinor.knowledge_graph import SchemaKnowledgeGraph, JoinPath

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA TOPOLOGY CLASSIFIER — gates query generation by schema complexity
# ═══════════════════════════════════════════════════════════════════════════


class SchemaTopology(str, Enum):
    FULL = "full"         # 3+ entities with invoices, customers, payments
    SLIM = "slim"         # 2 entities (e.g., invoices + customers, no payments)
    MINIMAL = "minimal"   # 1 entity or no clear TRANSACTIONAL


def classify_schema_topology(entity_map: dict) -> SchemaTopology:
    """Classify schema complexity from entity_map."""
    entities = entity_map.get("entities", {})
    if not entities:
        return SchemaTopology.MINIMAL

    has_transactional = False
    has_master = False
    has_payment = False

    for name, entity in entities.items():
        etype = entity.get("type", "")
        key_cols = entity.get("key_columns", {})
        if etype == "TRANSACTIONAL":
            has_transactional = True
        elif etype == "MASTER":
            has_master = True
        # Check for payment-like entity
        if any(k in key_cols for k in ("outstanding_amount", "outstandingamt", "amount_residual")):
            has_payment = True

    if has_transactional and has_master and has_payment:
        return SchemaTopology.FULL
    elif has_transactional and (has_master or len(entities) >= 2):
        return SchemaTopology.SLIM
    else:
        return SchemaTopology.MINIMAL


# ═══════════════════════════════════════════════════════════════════════════
# SQL BUILDER — Fluent API with KG-guided safety
# ═══════════════════════════════════════════════════════════════════════════


class SQLBuilder:
    """
    Fluent SQL construction with KG-guided safety.

    The critical innovation: join_to() doesn't take ON conditions — it asks
    the KG for the shortest path and builds the JOIN clause automatically.
    If the path is A->B->C, it generates two JOIN clauses.
    """

    def __init__(self, kg: SchemaKnowledgeGraph) -> None:
        self.kg = kg
        self._selects: list[str] = []
        self._from_table: str | None = None
        self._from_alias: str | None = None
        self._joins: list[str] = []
        self._joined_tables: list[str] = []  # track tables in query for filter/ambiguity
        self._wheres: list[str] = []
        self._group_bys: list[str] = []
        self._having: str | None = None
        self._order_by: str | None = None
        self._limit: int | None = None
        self._table_aliases: dict[str, str] = {}  # table_name -> alias
        self._ctes: list[tuple[str, str]] = []  # (name, sql_string)

    def select(self, expr: str, alias: str = "") -> "SQLBuilder":
        """Add a SELECT expression."""
        if alias:
            self._selects.append(f"{expr} AS {alias}")
        else:
            self._selects.append(expr)
        return self

    def from_table(self, table: str, alias: str = "") -> "SQLBuilder":
        """Set the FROM table."""
        self._from_table = table
        self._from_alias = alias or table
        self._table_aliases[table] = alias or table
        self._joined_tables = [table]
        return self

    def join_to(self, target_table: str, alias: str = "") -> "SQLBuilder":
        """
        Uses KG.find_join_path() to determine correct JOIN.

        If the path requires intermediate tables, generates all necessary
        JOIN clauses automatically.
        """
        if not self._from_table:
            raise ValueError("Must call from_table() before join_to()")

        # Find path from the last joined table (or from_table)
        source = self._joined_tables[-1] if self._joined_tables else self._from_table
        path = self.kg.find_join_path(source, target_table)

        if path is None:
            raise ValueError(
                f"No JOIN path found from {source} to {target_table} in Knowledge Graph"
            )

        # Generate JOIN clauses for each edge in the path
        for edge in path.edges:
            # Determine which side is the "new" table to join
            if edge.to_table not in self._joined_tables:
                join_table = edge.to_table
                on_left = f"{self._table_aliases.get(edge.from_table, edge.from_table)}.{edge.from_column}"
                on_right_table = alias if (join_table == target_table and alias) else join_table
                on_right = f"{on_right_table}.{edge.to_column}"
                table_ref = f"{join_table}" + (f" {alias}" if join_table == target_table and alias else "")
            elif edge.from_table not in self._joined_tables:
                join_table = edge.from_table
                on_left = f"{self._table_aliases.get(edge.to_table, edge.to_table)}.{edge.to_column}"
                on_right_table = alias if (join_table == target_table and alias) else join_table
                on_right = f"{on_right_table}.{edge.from_column}"
                table_ref = f"{join_table}" + (f" {alias}" if join_table == target_table and alias else "")
            else:
                continue  # Both tables already joined

            self._joins.append(f"JOIN {table_ref} ON {on_left} = {on_right}")
            self._joined_tables.append(join_table)
            effective_alias = alias if (join_table == target_table and alias) else join_table
            self._table_aliases[join_table] = effective_alias

        return self

    def where(self, condition: str) -> "SQLBuilder":
        """Add a WHERE condition."""
        self._wheres.append(condition)
        return self

    def where_filters(self, table: str) -> "SQLBuilder":
        """Injects all required filters from KG for this table."""
        filters = self.kg.get_required_filters(table)
        alias = self._table_aliases.get(table, table)
        for f in filters:
            # Re-qualify with the alias used in this query
            qualified = f
            if f.startswith(f"{table}.") and alias != table:
                qualified = f"{alias}.{f[len(table) + 1:]}"
            self._wheres.append(qualified)
        return self

    def where_period(self, date_col: str, period: dict, alias: str = "") -> "SQLBuilder":
        """Add period filtering (start/end date)."""
        prefix = f"{alias}." if alias else ""
        self._wheres.append(f"{prefix}{date_col} >= '{period['start']}'")
        self._wheres.append(f"{prefix}{date_col} <= '{period['end']}'")
        return self

    def group_by(self, *cols: str) -> "SQLBuilder":
        """Add GROUP BY columns."""
        self._group_bys.extend(cols)
        return self

    def having(self, condition: str) -> "SQLBuilder":
        """Add HAVING clause."""
        self._having = condition
        return self

    def order_by(self, col: str, desc: bool = True) -> "SQLBuilder":
        """Set ORDER BY."""
        direction = "DESC" if desc else "ASC"
        self._order_by = f"{col} {direction}"
        return self

    def limit(self, n: int) -> "SQLBuilder":
        """Set LIMIT."""
        self._limit = n
        return self

    def with_cte(self, name: str, sql: str) -> "SQLBuilder":
        """Register a CTE. Rendered before the main SELECT."""
        self._ctes.append((name, sql))
        return self

    def build(self) -> str:
        """Assemble the final SQL string."""
        if not self._selects:
            raise ValueError("No SELECT expressions defined")
        if not self._from_table:
            raise ValueError("No FROM table defined")

        parts = []
        if self._ctes:
            cte_parts = [f"{name} AS (\n{sql}\n)" for name, sql in self._ctes]
            parts.append("WITH " + ",\n".join(cte_parts))
        parts.append("SELECT")
        parts.append("    " + ",\n    ".join(self._selects))

        from_ref = self._from_table
        if self._from_alias and self._from_alias != self._from_table:
            from_ref = f"{self._from_table} {self._from_alias}"
        parts.append(f"FROM {from_ref}")

        for join in self._joins:
            parts.append(join)

        if self._wheres:
            parts.append("WHERE " + "\n  AND ".join(self._wheres))

        if self._group_bys:
            parts.append("GROUP BY " + ", ".join(self._group_bys))

        if self._having:
            parts.append(f"HAVING {self._having}")

        if self._order_by:
            parts.append(f"ORDER BY {self._order_by}")

        if self._limit is not None:
            parts.append(f"LIMIT {self._limit}")

        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# QUERY GENERATOR — KG-guided dynamic SQL construction
# ═══════════════════════════════════════════════════════════════════════════


class QueryGenerator:
    """
    Generates analysis queries dynamically using the Knowledge Graph.

    Instead of static templates with {placeholder} substitution, builds SQL
    programmatically. Entity detection is by TYPE (TRANSACTIONAL, MASTER),
    not by NAME (invoices, customers). Column detection is by SEMANTIC ROLE
    (amount_col, date_col) from key_columns, not by name.
    """

    def __init__(
        self,
        kg: SchemaKnowledgeGraph,
        entity_map: dict,
        period: dict,
    ) -> None:
        self.kg = kg
        self.entity_map = entity_map
        self.period = period
        self._entities = entity_map.get("entities", {})

    # ── PUBLIC API ──────────────────────────────────────────────────────

    def generate_all(self) -> dict:
        """Generate all analysis queries. Returns same format as build_queries()."""
        topology = classify_schema_topology(self.entity_map)
        logger.info("schema_topology_classified", topology=topology.value)

        queries = []
        skipped = []

        # Base generators available in all topologies
        base_generators = [
            ("revenue_summary", "financial", self.generate_revenue_summary),
            ("revenue_trend", "financial", self.generate_revenue_trend),
            ("yoy_comparison", "financial", self.generate_yoy_comparison),
        ]

        # Slim adds customer-related queries
        slim_generators = [
            ("customer_concentration", "financial", self.generate_customer_concentration),
            ("dormant_customers", "sales", self.generate_dormant_customers),
        ]

        # Full adds AR/payment queries
        full_generators = [
            ("ar_outstanding", "credit", self.generate_ar_outstanding),
            ("aging_analysis", "credit", self.generate_aging_analysis),
            ("top_debtors", "credit", self.generate_top_debtors),
        ]

        if topology == SchemaTopology.FULL:
            generators = base_generators + slim_generators + full_generators
        elif topology == SchemaTopology.SLIM:
            generators = base_generators + slim_generators
        else:
            generators = base_generators

        for query_id, domain, gen_fn in generators:
            try:
                result = gen_fn()
                if result:
                    queries.append({
                        "id": query_id,
                        "domain": domain,
                        "description": result["description"],
                        "sql": result["sql"],
                        "source": "kg_generator",
                    })
                else:
                    skipped.append({
                        "id": query_id,
                        "domain": domain,
                        "reason": "Required entities not found in entity_map",
                    })
            except Exception as e:
                logger.warning(
                    "Query generation failed",
                    query_id=query_id,
                    error=str(e),
                )
                skipped.append({
                    "id": query_id,
                    "domain": domain,
                    "reason": f"Generation error: {e}",
                })

        query_pack = {"queries": queries, "skipped": skipped, "_topology": topology.value}
        return query_pack

    # ── QUERY GENERATORS ────────────────────────────────────────────────

    def generate_revenue_summary(self) -> dict | None:
        """Revenue summary for the primary transactional entity."""
        revenue = self._find_revenue_entity()
        if not revenue:
            return None

        table = revenue["table"]
        kc = revenue.get("key_columns", {})
        amount_col = self._find_key_column(kc, "amount_col", "grand_total", "amount")
        date_col = self._find_key_column(kc, "invoice_date", "date_col", "date")
        customer_fk = self._find_key_column(kc, "customer_fk", "partner_fk")

        if not amount_col or not date_col:
            return None

        builder = SQLBuilder(self.kg)
        builder.from_table(table)
        builder.select(f"COUNT(*)", "num_records")
        builder.select(f"SUM({amount_col})", "total_revenue")
        builder.select(f"AVG({amount_col})", "avg_amount")
        builder.select(f"MIN({amount_col})", "min_amount")
        builder.select(f"MAX({amount_col})", "max_amount")
        builder.select(f"MIN({date_col})", "date_from")
        builder.select(f"MAX({date_col})", "date_to")

        if customer_fk:
            builder.select(f"COUNT(DISTINCT {customer_fk})", "distinct_customers")

        builder.where_period(date_col, self.period)
        builder.where_filters(table)

        return {
            "description": f"Revenue summary from {revenue['name']}",
            "sql": builder.build(),
        }

    def generate_ar_outstanding(self) -> dict | None:
        """Outstanding AR — auto-detects payment entity and JOINs through invoice."""
        payment = self._find_payment_entity()
        revenue = self._find_revenue_entity()
        if not payment or not revenue:
            return None

        pay_table = payment["table"]
        inv_table = revenue["table"]
        pay_kc = payment.get("key_columns", {})
        inv_kc = revenue.get("key_columns", {})

        outstanding_col = self._find_key_column(
            pay_kc, "outstanding_amount", "outstandingamt", "amount_residual"
        )
        due_date_col = self._find_key_column(pay_kc, "due_date", "duedate", "date_maturity")
        customer_fk = self._find_key_column(inv_kc, "customer_fk", "partner_fk")

        if not outstanding_col:
            return None

        builder = SQLBuilder(self.kg)
        builder.from_table(pay_table, "pay")
        builder.join_to(inv_table, "inv")
        builder.select("COUNT(*)", "total_schedules")
        builder.select(
            f"COUNT(CASE WHEN pay.{outstanding_col} > 0 THEN 1 END)",
            "unpaid_count",
        )
        builder.select(f"SUM(pay.{outstanding_col})", "total_outstanding")
        builder.select(f"AVG(pay.{outstanding_col})", "avg_outstanding")

        if due_date_col:
            builder.select(
                f"COUNT(CASE WHEN pay.{due_date_col}::date < CURRENT_DATE "
                f"AND pay.{outstanding_col} > 0 THEN 1 END)",
                "overdue_count",
            )
            builder.select(
                f"SUM(CASE WHEN pay.{due_date_col}::date < CURRENT_DATE "
                f"AND pay.{outstanding_col} > 0 THEN pay.{outstanding_col} ELSE 0 END)",
                "overdue_amount",
            )

        if customer_fk:
            builder.select(f"COUNT(DISTINCT inv.{customer_fk})", "customers_with_debt")

        builder.where(f"pay.{outstanding_col} > 0")
        builder.where_filters(pay_table)
        builder.where_filters(inv_table)

        return {
            "description": f"Outstanding AR from {payment['name']} via {revenue['name']}",
            "sql": builder.build(),
        }

    def generate_aging_analysis(self) -> dict | None:
        """Aging buckets for outstanding amounts."""
        payment = self._find_payment_entity()
        revenue = self._find_revenue_entity()
        if not payment or not revenue:
            return None

        pay_table = payment["table"]
        inv_table = revenue["table"]
        pay_kc = payment.get("key_columns", {})
        inv_kc = revenue.get("key_columns", {})

        outstanding_col = self._find_key_column(
            pay_kc, "outstanding_amount", "outstandingamt", "amount_residual"
        )
        due_date_col = self._find_key_column(pay_kc, "due_date", "duedate", "date_maturity")
        customer_fk = self._find_key_column(inv_kc, "customer_fk", "partner_fk")

        if not outstanding_col or not due_date_col:
            return None

        aging_expr = (
            f"CASE\n"
            f"    WHEN pay.{due_date_col}::date >= CURRENT_DATE THEN 'not_due'\n"
            f"    WHEN CURRENT_DATE - pay.{due_date_col}::date <= 30 THEN '0-30d'\n"
            f"    WHEN CURRENT_DATE - pay.{due_date_col}::date <= 60 THEN '31-60d'\n"
            f"    WHEN CURRENT_DATE - pay.{due_date_col}::date <= 90 THEN '61-90d'\n"
            f"    WHEN CURRENT_DATE - pay.{due_date_col}::date <= 180 THEN '91-180d'\n"
            f"    WHEN CURRENT_DATE - pay.{due_date_col}::date <= 365 THEN '181-365d'\n"
            f"    ELSE '>365d'\n"
            f"END"
        )

        builder = SQLBuilder(self.kg)
        builder.from_table(pay_table, "pay")
        builder.join_to(inv_table, "inv")
        builder.select(aging_expr, "tramo")
        builder.select("COUNT(*)", "num_payments")
        if customer_fk:
            builder.select(f"COUNT(DISTINCT inv.{customer_fk})", "num_customers")
        builder.select(f"SUM(pay.{outstanding_col})", "total_amount")
        builder.where(f"pay.{outstanding_col} > 0")
        builder.where_filters(pay_table)
        builder.where_filters(inv_table)
        builder.group_by("1")
        builder.order_by("total_amount")

        return {
            "description": f"Aging analysis from {payment['name']}",
            "sql": builder.build(),
        }

    def generate_customer_concentration(self) -> dict | None:
        """Revenue by customer (Pareto)."""
        revenue = self._find_revenue_entity()
        customer = self._find_customer_entity()
        if not revenue or not customer:
            return None

        inv_table = revenue["table"]
        cust_table = customer["table"]
        inv_kc = revenue.get("key_columns", {})
        cust_kc = customer.get("key_columns", {})

        amount_col = self._find_key_column(inv_kc, "amount_col", "grand_total", "amount")
        date_col = self._find_key_column(inv_kc, "invoice_date", "date_col", "date")
        customer_fk = self._find_key_column(inv_kc, "customer_fk", "partner_fk")
        cust_pk = self._find_key_column(cust_kc, "pk", "customer_pk")
        cust_name = self._find_key_column(cust_kc, "customer_name", "name")

        if not amount_col or not date_col or not cust_pk:
            return None

        # Build subquery for total revenue (for percentage calculation)
        sub = SQLBuilder(self.kg)
        sub.from_table(inv_table, "sub")
        sub.select(f"SUM(sub.{amount_col})")
        sub.where_period(date_col, self.period, alias="sub")
        # Apply revenue entity filters to subquery
        inv_filters = self.kg.get_required_filters(inv_table)
        for f in inv_filters:
            # Re-qualify for subquery alias
            if f.startswith(f"{inv_table}."):
                f = f"sub.{f[len(inv_table) + 1:]}"
            sub.where(f)

        total_subquery = f"({sub.build()})"

        builder = SQLBuilder(self.kg)
        builder.from_table(inv_table, "inv")
        builder.join_to(cust_table, "cust")
        builder.select(f"cust.{cust_pk}", "customer_id")
        if cust_name:
            builder.select(f"cust.{cust_name}", "customer_name")
        builder.select("COUNT(*)", "num_invoices")
        builder.select(f"SUM(inv.{amount_col})", "total_revenue")
        builder.select(
            f"SUM(inv.{amount_col}) * 100.0 / NULLIF({total_subquery}, 0)",
            "pct_revenue",
        )
        builder.where_period(date_col, self.period, alias="inv")
        builder.where_filters(inv_table)
        builder.where_filters(cust_table)
        builder.group_by(f"cust.{cust_pk}")
        if cust_name:
            builder.group_by(f"cust.{cust_name}")
        builder.order_by("total_revenue")

        return {
            "description": f"Customer concentration from {revenue['name']}",
            "sql": builder.build(),
        }

    def generate_top_debtors(self) -> dict | None:
        """Top debtors with correct JOIN path."""
        payment = self._find_payment_entity()
        revenue = self._find_revenue_entity()
        customer = self._find_customer_entity()
        if not payment or not revenue or not customer:
            return None

        pay_table = payment["table"]
        inv_table = revenue["table"]
        cust_table = customer["table"]
        pay_kc = payment.get("key_columns", {})
        inv_kc = revenue.get("key_columns", {})
        cust_kc = customer.get("key_columns", {})

        outstanding_col = self._find_key_column(
            pay_kc, "outstanding_amount", "outstandingamt", "amount_residual"
        )
        due_date_col = self._find_key_column(pay_kc, "due_date", "duedate", "date_maturity")
        cust_pk = self._find_key_column(cust_kc, "pk", "customer_pk")
        cust_name = self._find_key_column(cust_kc, "customer_name", "name")

        if not outstanding_col or not cust_pk:
            return None

        builder = SQLBuilder(self.kg)
        builder.from_table(pay_table, "pay")
        builder.join_to(inv_table, "inv")
        builder.join_to(cust_table, "cust")
        builder.select(f"cust.{cust_pk}", "customer_id")
        if cust_name:
            builder.select(f"cust.{cust_name}", "customer_name")
        builder.select(f"SUM(pay.{outstanding_col})", "total_outstanding")
        builder.select("COUNT(*)", "num_unpaid")
        if due_date_col:
            builder.select(f"MIN(pay.{due_date_col})::date", "oldest_due_date")
            builder.select(
                f"CURRENT_DATE - MIN(pay.{due_date_col})::date",
                "max_days_overdue",
            )
        builder.where(f"pay.{outstanding_col} > 0")
        builder.where_filters(pay_table)
        builder.where_filters(inv_table)
        builder.where_filters(cust_table)
        builder.group_by(f"cust.{cust_pk}")
        if cust_name:
            builder.group_by(f"cust.{cust_name}")
        builder.order_by("total_outstanding")
        builder.limit(20)

        return {
            "description": f"Top debtors from {payment['name']}",
            "sql": builder.build(),
        }

    def generate_dormant_customers(self) -> dict | None:
        """Customers who stopped purchasing."""
        revenue = self._find_revenue_entity()
        customer = self._find_customer_entity()
        if not revenue or not customer:
            return None

        inv_table = revenue["table"]
        cust_table = customer["table"]
        inv_kc = revenue.get("key_columns", {})
        cust_kc = customer.get("key_columns", {})

        amount_col = self._find_key_column(inv_kc, "amount_col", "grand_total", "amount")
        date_col = self._find_key_column(inv_kc, "invoice_date", "date_col", "date")
        cust_pk = self._find_key_column(cust_kc, "pk", "customer_pk")
        cust_name = self._find_key_column(cust_kc, "customer_name", "name")
        inv_pk = self._find_key_column(inv_kc, "pk", "invoice_pk")

        if not date_col or not cust_pk:
            return None

        builder = SQLBuilder(self.kg)
        builder.from_table(cust_table, "cust")
        builder.join_to(inv_table, "inv")
        builder.select(f"cust.{cust_pk}", "customer_id")
        if cust_name:
            builder.select(f"cust.{cust_name}", "customer_name")
        builder.select(f"MAX(inv.{date_col})", "last_purchase")
        builder.select(f"CURRENT_DATE - MAX(inv.{date_col})::date", "days_inactive")
        if inv_pk:
            builder.select(f"COUNT(inv.{inv_pk})", "total_invoices")
        if amount_col:
            builder.select(f"SUM(inv.{amount_col})", "lifetime_revenue")
            builder.select(f"AVG(inv.{amount_col})", "avg_invoice_value")
        builder.where_filters(inv_table)
        builder.where_filters(cust_table)
        builder.group_by(f"cust.{cust_pk}")
        if cust_name:
            builder.group_by(f"cust.{cust_name}")
        builder.having(f"MAX(inv.{date_col}) < CURRENT_DATE - INTERVAL '90 days'")
        builder.order_by("lifetime_revenue" if amount_col else "last_purchase")
        builder.limit(30)

        return {
            "description": f"Dormant customers from {customer['name']}",
            "sql": builder.build(),
        }

    def generate_revenue_trend(self) -> dict | None:
        """Monthly revenue with MoM growth rate and 3-month moving average."""
        revenue = self._find_revenue_entity()
        if not revenue:
            return None

        table = revenue["table"]
        kc = revenue.get("key_columns", {})
        amount_col = self._find_key_column(kc, "amount_col", "grand_total", "amount")
        date_col = self._find_key_column(kc, "invoice_date", "date_col", "date")
        base_filter = revenue.get("base_filter", "")

        if not amount_col or not date_col:
            return None

        where = f"WHERE {base_filter}" if base_filter else ""
        if where and self.period:
            where += f" AND {date_col} >= '{self.period.get('start', '')}'"
            where += f" AND {date_col} <= '{self.period.get('end', '')}'"
        elif self.period:
            where = (
                f"WHERE {date_col} >= '{self.period.get('start', '')}'"
                f" AND {date_col} <= '{self.period.get('end', '')}'"
            )

        sql = f"""WITH monthly_agg AS (
    SELECT
        DATE_TRUNC('month', {date_col}) AS month,
        SUM({amount_col}) AS revenue,
        COUNT(*) AS invoice_count
    FROM {table}
    {where}
    GROUP BY DATE_TRUNC('month', {date_col})
    ORDER BY month
)
SELECT
    month,
    revenue,
    invoice_count,
    LAG(revenue) OVER (ORDER BY month) AS prev_month_revenue,
    CASE
        WHEN LAG(revenue) OVER (ORDER BY month) > 0
        THEN ROUND(((revenue - LAG(revenue) OVER (ORDER BY month)) * 100.0
              / LAG(revenue) OVER (ORDER BY month))::numeric, 2)
        ELSE NULL
    END AS mom_growth_pct,
    ROUND(AVG(revenue) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)::numeric, 2) AS moving_avg_3m
FROM monthly_agg
ORDER BY month"""

        return {
            "id": "revenue_trend",
            "sql": sql,
            "description": "Monthly revenue with MoM growth rate and 3-month moving average",
            "domain": "financial",
        }

    def generate_yoy_comparison(self) -> dict | None:
        """Year-over-year comparison with actual growth rates."""
        revenue = self._find_revenue_entity()
        if not revenue:
            return None

        table = revenue["table"]
        kc = revenue.get("key_columns", {})
        amount_col = self._find_key_column(kc, "amount_col", "grand_total", "amount")
        date_col = self._find_key_column(kc, "invoice_date", "date_col", "date")
        base_filter = revenue.get("base_filter", "")

        if not amount_col or not date_col:
            return None

        where = f"WHERE {base_filter}" if base_filter else "WHERE 1=1"

        sql = f"""WITH yearly AS (
    SELECT
        EXTRACT(YEAR FROM {date_col}) AS year,
        EXTRACT(MONTH FROM {date_col}) AS month,
        SUM({amount_col}) AS revenue
    FROM {table}
    {where}
    GROUP BY EXTRACT(YEAR FROM {date_col}), EXTRACT(MONTH FROM {date_col})
)
SELECT
    y1.year,
    y1.month,
    y1.revenue AS current_revenue,
    y2.revenue AS prior_year_revenue,
    CASE
        WHEN y2.revenue > 0
        THEN ROUND(((y1.revenue - y2.revenue) * 100.0 / y2.revenue)::numeric, 2)
        ELSE NULL
    END AS yoy_growth_pct
FROM yearly y1
LEFT JOIN yearly y2
    ON y1.month = y2.month AND y1.year = y2.year + 1
ORDER BY y1.year, y1.month"""

        return {
            "id": "yoy_comparison",
            "sql": sql,
            "description": "Year-over-year monthly comparison with growth rates",
            "domain": "financial",
        }

    # ── ENTITY DETECTION (by TYPE, not NAME) ────────────────────────────

    def _find_entity_by_type(
        self, entity_type: str, hints: list[str] | None = None
    ) -> dict | None:
        """Find an entity of the given type. Use hints for disambiguation."""
        candidates = [
            (name, e)
            for name, e in self._entities.items()
            if e.get("type") == entity_type
        ]
        if not candidates:
            return None

        if hints:
            for hint in hints:
                for name, e in candidates:
                    if hint in name.lower():
                        return {"name": name, **e}

        return {"name": candidates[0][0], **candidates[0][1]}

    def _find_revenue_entity(self) -> dict | None:
        """Find the primary revenue entity (TRANSACTIONAL with amount column)."""
        candidates = [
            (name, e)
            for name, e in self._entities.items()
            if e.get("type") == "TRANSACTIONAL"
        ]
        if not candidates:
            return None

        # Prefer entities that have an amount-like key_column
        amount_keys = ("amount_col", "grand_total", "amount", "amount_total")
        for name, e in candidates:
            kc = e.get("key_columns", {})
            if any(k in kc for k in amount_keys):
                # Also prefer those with a date column (invoices over payments)
                date_keys = ("invoice_date", "date_col", "date")
                if any(k in kc for k in date_keys):
                    return {"name": name, **e}

        # Fall back to any TRANSACTIONAL with amount
        for name, e in candidates:
            kc = e.get("key_columns", {})
            if any(k in kc for k in amount_keys):
                return {"name": name, **e}

        return None

    def _find_customer_entity(self) -> dict | None:
        """Find the customer entity (MASTER referenced by revenue entity)."""
        # First try: MASTER entity
        master = self._find_entity_by_type(
            "MASTER", hints=["customer", "partner", "client", "bpartner"]
        )
        if master:
            return master

        # Fall back to any MASTER
        return self._find_entity_by_type("MASTER")

    def _find_payment_entity(self) -> dict | None:
        """Find payment schedule/payment entity (has outstanding_amount or similar)."""
        outstanding_keys = (
            "outstanding_amount", "outstandingamt", "amount_residual",
            "amount_due", "balance",
        )
        for name, e in self._entities.items():
            kc = e.get("key_columns", {})
            if any(k in kc for k in outstanding_keys):
                return {"name": name, **e}

        # Fall back to TRANSACTIONAL with payment/schedule hints
        return self._find_entity_by_type(
            "TRANSACTIONAL",
            hints=["payment", "schedule", "receivable", "payable"],
        )

    # ── COLUMN DETECTION (by SEMANTIC ROLE) ─────────────────────────────

    # ── ZERO-ROW REFORMULATION (VAL-43) ───────────────────────────────

    def reformulate_zero_row_query(
        self,
        original_query: dict,
        max_retries: int = 3,
        semantic_enrichment: dict | None = None,
    ) -> list[dict]:
        """
        Generate reformulated queries when the original returned 0 rows.

        Strategies (tried in order):
          1. Relax date filters (widen range by 6 months)
          2. Remove one WHERE filter at a time
          3. Try alternative column names from semantic enrichment

        Args:
            original_query: Dict with 'sql', 'id', 'description' keys.
            max_retries: Maximum number of reformulations to return.
            semantic_enrichment: Optional dict of column -> alternative names.

        Returns:
            List of reformulated query dicts, each with 'sql', 'id',
            'description', 'reformulation_strategy'.
        """
        sql = original_query.get("sql", "")
        query_id = original_query.get("id", "unknown")
        reformulations: list[dict] = []

        # Strategy 1: Relax date filters
        relaxed = self._relax_date_filters(sql)
        if relaxed and relaxed != sql:
            reformulations.append({
                "id": f"{query_id}_relaxed_dates",
                "sql": relaxed,
                "description": f"{original_query.get('description', '')} (relaxed date range)",
                "reformulation_strategy": "relax_date_filters",
                "attempt": len(reformulations) + 1,
            })

        # Strategy 2: Remove filters one at a time
        stripped_variants = self._remove_filters_one_by_one(sql)
        for i, variant_sql in enumerate(stripped_variants):
            if len(reformulations) >= max_retries:
                break
            reformulations.append({
                "id": f"{query_id}_no_filter_{i}",
                "sql": variant_sql,
                "description": f"{original_query.get('description', '')} (filter #{i+1} removed)",
                "reformulation_strategy": f"remove_filter_{i}",
                "attempt": len(reformulations) + 1,
            })

        # Strategy 3: Try alternative column names
        if semantic_enrichment and len(reformulations) < max_retries:
            alt_variants = self._try_alternative_columns(sql, semantic_enrichment)
            for variant_sql in alt_variants:
                if len(reformulations) >= max_retries:
                    break
                reformulations.append({
                    "id": f"{query_id}_alt_cols",
                    "sql": variant_sql,
                    "description": f"{original_query.get('description', '')} (alternative columns)",
                    "reformulation_strategy": "alternative_columns",
                    "attempt": len(reformulations) + 1,
                })

        logger.info(
            "zero_row_reformulations_generated",
            query_id=query_id,
            num_reformulations=len(reformulations),
        )

        return reformulations[:max_retries]

    @staticmethod
    def _relax_date_filters(sql: str) -> str:
        """Widen date range by 6 months on each side."""
        import re as _re

        # Match patterns like: column >= '2024-01-01'
        def _widen_start(match: _re.Match) -> str:
            col = match.group(1)
            date_str = match.group(2)
            # Try to shift date back 6 months
            try:
                from datetime import datetime, timedelta
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                new_dt = dt - timedelta(days=180)
                return f"{col} >= '{new_dt.strftime('%Y-%m-%d')}'"
            except (ValueError, ImportError):
                return match.group(0)

        def _widen_end(match: _re.Match) -> str:
            col = match.group(1)
            date_str = match.group(2)
            try:
                from datetime import datetime, timedelta
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                new_dt = dt + timedelta(days=180)
                return f"{col} <= '{new_dt.strftime('%Y-%m-%d')}'"
            except (ValueError, ImportError):
                return match.group(0)

        result = _re.sub(
            r"(\w+)\s*>=\s*'(\d{4}-\d{2}-\d{2})'",
            _widen_start,
            sql,
        )
        result = _re.sub(
            r"(\w+)\s*<=\s*'(\d{4}-\d{2}-\d{2})'",
            _widen_end,
            result,
        )
        return result

    @staticmethod
    def _remove_filters_one_by_one(sql: str) -> list[str]:
        """
        Remove one AND condition at a time from the WHERE clause.
        Returns a list of SQL variants, each missing one filter.
        """
        import re as _re

        # Split WHERE clause into AND conditions
        where_match = _re.search(r'WHERE\s+(.*?)(?:GROUP BY|ORDER BY|HAVING|LIMIT|$)',
                                  sql, _re.IGNORECASE | _re.DOTALL)
        if not where_match:
            return []

        where_body = where_match.group(1).strip()
        # Split on AND (but not inside parentheses)
        conditions = _re.split(r'\bAND\b', where_body, flags=_re.IGNORECASE)
        conditions = [c.strip() for c in conditions if c.strip()]

        if len(conditions) <= 1:
            return []

        variants = []
        for i in range(len(conditions)):
            # Skip removing date conditions (they're relaxed in strategy 1)
            if ">=" in conditions[i] or "<=" in conditions[i]:
                continue
            remaining = [c for j, c in enumerate(conditions) if j != i]
            new_where = " AND ".join(remaining)
            new_sql = sql[:where_match.start(1)] + new_where + sql[where_match.end(1):]
            variants.append(new_sql)

        return variants

    @staticmethod
    def _try_alternative_columns(
        sql: str,
        semantic_enrichment: dict[str, list[str]],
    ) -> list[str]:
        """
        Replace columns in SQL with alternatives from semantic enrichment.

        Args:
            sql: Original SQL string.
            semantic_enrichment: Dict of column_name -> [alternative_names].

        Returns:
            List of SQL variants with alternative column names.
        """
        import re as _re

        variants = []
        for col_name, alternatives in semantic_enrichment.items():
            if col_name.lower() not in sql.lower():
                continue
            for alt in alternatives[:2]:  # Try at most 2 alternatives per column
                new_sql = _re.sub(
                    rf'\b{_re.escape(col_name)}\b',
                    alt,
                    sql,
                    flags=_re.IGNORECASE,
                )
                if new_sql != sql:
                    variants.append(new_sql)
                    break  # One alternative per column is enough

        return variants

    # ── COLUMN DETECTION (by SEMANTIC ROLE) ─────────────────────────────

    @staticmethod
    def _find_key_column(key_columns: dict, *semantic_keys: str) -> str | None:
        """
        Find a column by trying multiple semantic key names.

        Tries each key in order, returning the first match from key_columns.
        This makes the generator schema-agnostic: Openbravo uses 'amount_col',
        Odoo might use 'amount', SAP might use 'amount_total'.

        Fallback: if no exact key matches, search by substring in key names
        (e.g., 'amount' matches 'amount_col').
        """
        # Try exact key match first
        for key in semantic_keys:
            if key in key_columns:
                return key_columns[key]
        # Fallback: search by value substring in key names
        for candidate in semantic_keys:
            normalized = candidate.replace("_col", "")
            for key, val in key_columns.items():
                if normalized in key.lower():
                    return val
        return None
