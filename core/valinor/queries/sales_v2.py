"""
Parametrized SQL templates for Sales Report v2.

Each builder takes a resolved entity_map (Cartographer output) and returns
a dialect-aware SQL string. The DataPrefetcher runs these and packs the
results into the context passed to the sales narrator.

5 queries:
  1. rfm_segmentation       — R, F, M scored 1-5 → 11 segments
  2. concentration_hhi      — HHI + CR1/CR5/CR10
  3. concentration_top      — Top N customers with share, LTV, last purchase
  4. cross_sell_matrix      — RFM segment × category penetration
  5. churn_risk_scoring     — dormant customers scored for priority call list

Refs: VAL-141
"""

from __future__ import annotations

from typing import Any

from core.valinor.sql_safety import is_safe_identifier


# ═══════════════════════════════════════════════════════════════════════════
# Entity map resolution helpers
# ═══════════════════════════════════════════════════════════════════════════


def _resolve(entity_map: dict, entity: str) -> dict:
    """Pull an entity's config from the Cartographer output."""
    return entity_map.get("entities", {}).get(entity, {})


def _table(entity_map: dict, entity: str, fallback: str) -> str:
    # entity_map is LLM-derived (Cartographer output) and gets f-string-interpolated
    # straight into raw SQL below. Validate the identifier and fall back to the
    # hardcoded safe literal on a hallucinated/injected name (VAL-170).
    name = _resolve(entity_map, entity).get("table", fallback)
    return name if is_safe_identifier(name) else fallback


def _col(entity_map: dict, entity: str, semantic: str, fallback: str) -> str:
    cols = _resolve(entity_map, entity).get("key_columns", {})
    name = cols.get(semantic, fallback)
    return name if is_safe_identifier(name) else fallback  # VAL-170: untrusted identifier


def _base_filter(entity_map: dict, entity: str) -> str:
    """
    Return the entity's base_filter ready to be appended to an existing WHERE clause.

    Cartographer emits `base_filter` as a bare predicate (e.g. "issotrx='Y' AND
    docstatus='CO'"), so we prepend ` AND ` when non-empty. Callers inject the
    result right after a WHERE condition — no connector needed on their side.
    Accepts legacy filters that already include a leading "AND ".
    """
    f = _resolve(entity_map, entity).get("base_filter", "").strip()
    if not f:
        return ""
    return f" {f}" if f.upper().startswith("AND ") else f" AND {f}"


# ═══════════════════════════════════════════════════════════════════════════
# Query 1 — RFM Segmentation
# ═══════════════════════════════════════════════════════════════════════════


def rfm_segmentation_sql(entity_map: dict, months: int = 12) -> str:
    """
    RFM scored 1-5 on each axis, then bucketed into 11 standard segments.

    Returns one row per customer with: customer_id, r_score, f_score, m_score,
    segment, recency_days, frequency, monetary_eur.
    """
    invoices = _table(entity_map, "invoices", "invoices")
    customers = _table(entity_map, "customers", "customers")

    inv_date = _col(entity_map, "invoices", "invoice_date", "invoice_date")
    inv_customer = _col(entity_map, "invoices", "customer_fk", "customer_id")
    inv_total = _col(entity_map, "invoices", "amount_col", "total_amount")
    inv_id = _col(entity_map, "invoices", "pk", "id")
    cust_id = _col(entity_map, "customers", "pk", "id")
    cust_name = _col(entity_map, "customers", "customer_name", "name")

    inv_filter = _base_filter(entity_map, "invoices")
    where_inv = f"WHERE {inv_date} > CURRENT_DATE - INTERVAL '{months} months' {inv_filter}"

    return f"""
WITH rfm_raw AS (
    SELECT
        c.{cust_id} AS customer_id,
        c.{cust_name} AS customer_name,
        CURRENT_DATE - MAX(i.{inv_date})::date AS recency_days,
        COUNT(DISTINCT i.{inv_id}) AS frequency,
        COALESCE(SUM(i.{inv_total}), 0) AS monetary_eur
    FROM {customers} c
    LEFT JOIN {invoices} i
      ON i.{inv_customer} = c.{cust_id}
     AND i.{inv_date} > CURRENT_DATE - INTERVAL '{months} months'
    GROUP BY c.{cust_id}, c.{cust_name}
    HAVING COUNT(DISTINCT i.{inv_id}) > 0
),
rfm_scored AS (
    SELECT
        customer_id, customer_name, recency_days, frequency, monetary_eur,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency ASC)    AS f_score,
        NTILE(5) OVER (ORDER BY monetary_eur ASC) AS m_score
    FROM rfm_raw
)
SELECT
    customer_id, customer_name, recency_days, frequency, monetary_eur,
    r_score, f_score, m_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'champions'
        WHEN r_score >= 3 AND f_score >= 4 AND m_score >= 4 THEN 'loyal'
        WHEN r_score >= 4 AND f_score >= 2 AND m_score >= 2 THEN 'potential_loyalists'
        WHEN r_score = 5 AND f_score = 1                    THEN 'new_customers'
        WHEN r_score >= 4 AND f_score <= 2 AND m_score <= 2 THEN 'promising'
        WHEN r_score = 3 AND f_score = 3                    THEN 'need_attention'
        WHEN r_score <= 3 AND f_score >= 2 AND m_score <= 3 THEN 'about_to_sleep'
        WHEN r_score <= 2 AND f_score >= 3 AND m_score >= 3 THEN 'at_risk'
        WHEN r_score <= 2 AND f_score >= 4 AND m_score >= 5 THEN 'cannot_lose'
        WHEN r_score <= 2 AND f_score <= 2 AND m_score <= 2 THEN 'hibernating'
        ELSE 'lost'
    END AS segment
FROM rfm_scored
ORDER BY monetary_eur DESC
""".strip()


# ═══════════════════════════════════════════════════════════════════════════
# Query 2 — HHI + Concentration Ratios
# ═══════════════════════════════════════════════════════════════════════════


def concentration_hhi_sql(entity_map: dict, months: int = 12) -> str:
    """
    Herfindahl-Hirschman Index (0-10000) over customer revenue share.
    Returns a single row: hhi, cr1, cr5, cr10, total_customers, total_revenue.
    """
    invoices = _table(entity_map, "invoices", "invoices")
    inv_date = _col(entity_map, "invoices", "invoice_date", "invoice_date")
    inv_customer = _col(entity_map, "invoices", "customer_fk", "customer_id")
    inv_total = _col(entity_map, "invoices", "amount_col", "total_amount")
    inv_filter = _base_filter(entity_map, "invoices")

    return f"""
WITH customer_revenue AS (
    SELECT
        {inv_customer} AS customer_id,
        SUM({inv_total}) AS revenue_eur
    FROM {invoices}
    WHERE {inv_date} > CURRENT_DATE - INTERVAL '{months} months'
    {inv_filter}
    GROUP BY {inv_customer}
    HAVING SUM({inv_total}) > 0
),
total AS (
    SELECT SUM(revenue_eur) AS total_rev, COUNT(*) AS total_customers
    FROM customer_revenue
),
ranked AS (
    SELECT
        cr.customer_id,
        cr.revenue_eur,
        cr.revenue_eur / NULLIF(t.total_rev, 0) AS share,
        ROW_NUMBER() OVER (ORDER BY cr.revenue_eur DESC) AS rn,
        t.total_rev,
        t.total_customers
    FROM customer_revenue cr CROSS JOIN total t
)
SELECT
    ROUND(SUM((share * 100) * (share * 100))::numeric, 2) AS hhi,
    ROUND((100 * SUM(CASE WHEN rn <= 1  THEN revenue_eur ELSE 0 END) / NULLIF(MAX(total_rev), 0))::numeric, 2) AS cr1_pct,
    ROUND((100 * SUM(CASE WHEN rn <= 5  THEN revenue_eur ELSE 0 END) / NULLIF(MAX(total_rev), 0))::numeric, 2) AS cr5_pct,
    ROUND((100 * SUM(CASE WHEN rn <= 10 THEN revenue_eur ELSE 0 END) / NULLIF(MAX(total_rev), 0))::numeric, 2) AS cr10_pct,
    MAX(total_customers) AS total_customers,
    MAX(total_rev) AS total_revenue
FROM ranked
""".strip()


# ═══════════════════════════════════════════════════════════════════════════
# Query 3 — Top-N customers (detailed table for concentration display)
# ═══════════════════════════════════════════════════════════════════════════


def concentration_top_customers_sql(entity_map: dict, months: int = 12, limit: int = 10) -> str:
    invoices = _table(entity_map, "invoices", "invoices")
    customers = _table(entity_map, "customers", "customers")
    inv_date = _col(entity_map, "invoices", "invoice_date", "invoice_date")
    inv_customer = _col(entity_map, "invoices", "customer_fk", "customer_id")
    inv_total = _col(entity_map, "invoices", "amount_col", "total_amount")
    cust_id = _col(entity_map, "customers", "pk", "id")
    cust_name = _col(entity_map, "customers", "customer_name", "name")
    inv_filter = _base_filter(entity_map, "invoices")

    # Aggregate on invoices alone (avoids "isactive ambiguous" when base_filter
    # uses bare column names that also exist on customers); join customers last
    # for human-readable names only.
    return f"""
WITH customer_revenue AS (
    SELECT
        {inv_customer} AS customer_id,
        SUM({inv_total}) AS ltv_eur,
        MAX({inv_date}::date) AS last_purchase
    FROM {invoices}
    WHERE {inv_date} > CURRENT_DATE - INTERVAL '{months} months'
    {inv_filter}
    GROUP BY {inv_customer}
    HAVING SUM({inv_total}) > 0
),
with_names AS (
    SELECT
        cr.customer_id,
        cr.ltv_eur,
        cr.last_purchase,
        c.{cust_name} AS customer_name
    FROM customer_revenue cr
    LEFT JOIN {customers} c ON c.{cust_id} = cr.customer_id
),
total AS (SELECT SUM(ltv_eur) AS total_rev FROM customer_revenue)
SELECT
    customer_id,
    customer_name,
    ROUND(ltv_eur::numeric, 2) AS ltv_eur,
    ROUND((100 * ltv_eur / NULLIF(t.total_rev, 0))::numeric, 2) AS share_pct,
    last_purchase::text AS last_purchase,
    CASE
        WHEN CURRENT_DATE - last_purchase > 90 THEN 'high'
        WHEN CURRENT_DATE - last_purchase > 45 THEN 'medium'
        ELSE 'low'
    END AS risk
FROM with_names, total t
ORDER BY ltv_eur DESC
LIMIT {limit}
""".strip()


# ═══════════════════════════════════════════════════════════════════════════
# Query 4 — Magic Matrix (cross-sell: segment × category penetration)
# ═══════════════════════════════════════════════════════════════════════════


def cross_sell_matrix_sql(entity_map: dict, months: int = 12) -> str:
    """
    Matrix: for each RFM segment × product category, % of customers in that
    segment who bought at least once from that category.

    Joins `m_product_category` by `m_product_category_id` (via `product_categories`
    entity in entity_map) to emit human-readable category names. Falls back to
    the category_id string when the categories entity is missing.
    """
    invoices = _table(entity_map, "invoices", "invoices")
    invoice_lines = _table(entity_map, "invoice_lines", "invoice_lines")
    products = _table(entity_map, "products", "products")
    product_categories = _table(entity_map, "product_categories", "m_product_category")

    inv_date = _col(entity_map, "invoices", "invoice_date", "invoice_date")
    inv_customer = _col(entity_map, "invoices", "customer_fk", "customer_id")
    inv_id = _col(entity_map, "invoices", "pk", "id")
    line_inv = _col(entity_map, "invoice_lines", "invoice_id", "invoice_id")
    line_product = _col(entity_map, "invoice_lines", "product_id", "product_id")
    line_amount = _col(entity_map, "invoice_lines", "line_amount", "line_amount")
    prod_id = _col(entity_map, "products", "product_id", "id")
    prod_category = _col(entity_map, "products", "category", "category")
    pc_id = _col(entity_map, "product_categories", "category_id", "m_product_category_id")
    pc_name = _col(entity_map, "product_categories", "category_name", "name")

    inv_filter = _base_filter(entity_map, "invoices")

    # Pre-filter invoices in a CTE so JOINs to invoice_lines/products/categories
    # never re-apply base_filter (which uses bare column names that collide with
    # `isactive` on every Openbravo table).
    return f"""
WITH invoices_filtered AS (
    SELECT
        {inv_id}       AS invoice_id,
        {inv_customer} AS customer_id,
        {inv_date}     AS invoice_date
    FROM {invoices}
    WHERE {inv_date} > CURRENT_DATE - INTERVAL '{months} months'
    {inv_filter}
),
rfm_raw AS (
    SELECT
        inv.customer_id,
        CURRENT_DATE - MAX(inv.invoice_date)::date AS recency_days,
        COUNT(DISTINCT inv.invoice_id) AS frequency,
        COALESCE(SUM((SELECT SUM(l.{line_amount}) FROM {invoice_lines} l WHERE l.{line_inv} = inv.invoice_id)), 0) AS monetary_eur
    FROM invoices_filtered inv
    GROUP BY inv.customer_id
    HAVING COUNT(DISTINCT inv.invoice_id) > 0
),
rfm_scored AS (
    SELECT
        customer_id,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,
        NTILE(5) OVER (ORDER BY frequency ASC)    AS f_score,
        NTILE(5) OVER (ORDER BY monetary_eur ASC) AS m_score
    FROM rfm_raw
),
rfm_seg AS (
    SELECT
        customer_id,
        CASE
            WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'champions'
            WHEN r_score >= 3 AND f_score >= 4 AND m_score >= 4 THEN 'loyal'
            WHEN r_score >= 4 AND f_score >= 2 AND m_score >= 2 THEN 'potential_loyalists'
            WHEN r_score <= 2 AND f_score >= 3 AND m_score >= 3 THEN 'at_risk'
            WHEN r_score <= 2 AND f_score >= 4 AND m_score >= 5 THEN 'cannot_lose'
            WHEN r_score <= 2 AND f_score <= 2 AND m_score <= 2 THEN 'hibernating'
            ELSE 'other'
        END AS segment
    FROM rfm_scored
),
customer_categories AS (
    SELECT
        inv.customer_id,
        COALESCE(pc.{pc_name}, p.{prod_category}::text) AS category,
        SUM(l.{line_amount}) AS segment_spent_eur
    FROM invoices_filtered inv
    JOIN {invoice_lines} l ON l.{line_inv} = inv.invoice_id
    JOIN {products} p ON p.{prod_id} = l.{line_product}
    LEFT JOIN {product_categories} pc ON pc.{pc_id} = p.{prod_category}
    WHERE p.{prod_category} IS NOT NULL
    GROUP BY inv.customer_id, pc.{pc_name}, p.{prod_category}
)
SELECT
    s.segment,
    cc.category,
    COUNT(DISTINCT cc.customer_id) AS customers_buying,
    (SELECT COUNT(*) FROM rfm_seg s2 WHERE s2.segment = s.segment) AS segment_size,
    ROUND(SUM(cc.segment_spent_eur)::numeric, 2) AS category_revenue_eur,
    ROUND((100.0 * COUNT(DISTINCT cc.customer_id) /
           NULLIF((SELECT COUNT(*) FROM rfm_seg s2 WHERE s2.segment = s.segment), 0))::numeric, 2)
        AS penetration_pct
FROM rfm_seg s
JOIN customer_categories cc USING (customer_id)
GROUP BY s.segment, cc.category
ORDER BY s.segment, penetration_pct DESC
""".strip()


# ═══════════════════════════════════════════════════════════════════════════
# Query 5 — Churn/Deal Risk Scoring for dormants
# ═══════════════════════════════════════════════════════════════════════════


def churn_risk_scoring_sql(
    entity_map: dict,
    months: int = 12,
    dormant_threshold_days: int = 60,
    limit: int = 50,
) -> str:
    """
    Deterministic deal-risk score for dormant customers.

    Score = f(recency_days, historical_ltv, frequency_drop):
      * 0-100 where higher = more urgent priority call.
      * Weights are tuned heuristically; v1 uses a deterministic formula,
        v2 can swap for a trained model.

    Dormant = last purchase > dormant_threshold_days ago.
    """
    invoices = _table(entity_map, "invoices", "invoices")
    customers = _table(entity_map, "customers", "customers")
    inv_date = _col(entity_map, "invoices", "invoice_date", "invoice_date")
    inv_customer = _col(entity_map, "invoices", "customer_fk", "customer_id")
    inv_total = _col(entity_map, "invoices", "amount_col", "total_amount")
    inv_id = _col(entity_map, "invoices", "pk", "id")
    cust_id = _col(entity_map, "customers", "pk", "id")
    cust_name = _col(entity_map, "customers", "customer_name", "name")
    inv_filter = _base_filter(entity_map, "invoices")

    # Aggregate on invoices alone first (avoids "isactive ambiguous" when
    # base_filter uses bare column names that also exist on customers);
    # join customers last for human-readable names only.
    return f"""
WITH history_raw AS (
    SELECT
        {inv_customer} AS customer_id,
        COUNT(DISTINCT {inv_id}) AS frequency,
        SUM({inv_total}) AS ltv_eur,
        MAX({inv_date}::date) AS last_purchase,
        MIN({inv_date}::date) AS first_purchase,
        CURRENT_DATE - MAX({inv_date}::date) AS recency_days,
        AVG({inv_total}) AS avg_order_eur,
        STDDEV_POP({inv_total}) AS stddev_order_eur
    FROM {invoices}
    WHERE {inv_date} > CURRENT_DATE - INTERVAL '{months} months'
    {inv_filter}
    GROUP BY {inv_customer}
    HAVING SUM({inv_total}) > 0
),
history AS (
    SELECT
        h.customer_id,
        c.{cust_name} AS customer_name,
        h.frequency,
        h.ltv_eur,
        h.last_purchase,
        h.first_purchase,
        h.recency_days,
        h.avg_order_eur,
        h.stddev_order_eur
    FROM history_raw h
    LEFT JOIN {customers} c ON c.{cust_id} = h.customer_id
),
dormant AS (
    SELECT * FROM history WHERE recency_days > {dormant_threshold_days}
),
ltv_percentiles AS (
    -- 'cuenta_top' = the top-5 LTV customers in the dormant pool. An
    -- absolute cap (not a percentile) so the badge stays rare and
    -- legible regardless of dormant population size. Percentiles
    -- (p95, p99) all turned out too permissive — when all top-12 risk
    -- scores are also the top-12 LTVs, the badge collapses into "all
    -- TOP" and stops differentiating.
    SELECT MIN(ltv_eur) AS p_top_ltv
    FROM (
        SELECT ltv_eur FROM dormant ORDER BY ltv_eur DESC LIMIT 5
    ) top5
),
scored AS (
    SELECT
        customer_id,
        customer_name,
        ltv_eur,
        frequency,
        last_purchase::text AS last_purchase,
        first_purchase::text AS first_purchase,
        recency_days,
        avg_order_eur,
        stddev_order_eur,
        -- Score components (each 0-100, weighted):
        --   recency_factor: older = higher urgency (capped at 180d)
        --   value_factor:   higher LTV = higher priority
        --   frequency_factor: frequent in past = more recoverable
        LEAST(100, (recency_days::numeric / 180.0) * 100) * 0.3
      + LEAST(100, (ltv_eur / NULLIF((SELECT MAX(ltv_eur) FROM dormant), 0)) * 100) * 0.5
      + LEAST(100, (frequency::numeric / NULLIF((SELECT MAX(frequency) FROM dormant), 0)) * 100) * 0.2
        AS deal_risk_score,
        -- Recovery potential: avg_order × win_rate × confidence_factor × cadence_factor.
        -- confidence_factor penalizes small samples: freq<=3 gets 0.1, freq<=10 gets 0.4,
        -- freq<=30 gets 0.7, freq>30 gets 1.0. Outliers (KONG con 1 pedido) no distorsionan.
        -- cadence_factor: for high-frequency clients, what you recover isn't "one order"
        -- but "resume the monthly cadence". monthly_freq ≈ frequency / months_active
        -- (clamped so low-freq clients get at least 1× single-order recovery).
        avg_order_eur * 0.30
          * CASE
              WHEN frequency <= 3  THEN 0.10
              WHEN frequency <= 10 THEN 0.40
              WHEN frequency <= 30 THEN 0.70
              ELSE 1.00
            END
          * GREATEST(
              1.0,
              (frequency::numeric / NULLIF(
                  GREATEST(1, EXTRACT(MONTH FROM AGE(last_purchase::timestamp, first_purchase::timestamp))::int + 1),
                  0
              )) * 0.5
            )
        AS recovery_potential_eur,
        -- Profile: cuenta_top (LTV p95+) > account_grande (>100 pedidos) >
        --          outlier (1-3) > cuenta_media (resto).
        -- Top-LTV precedence because a 32-order client responsable for 14%
        -- del revenue NO es "cuenta media" — es la cuenta crítica del reporte.
        CASE
            WHEN ltv_eur >= (SELECT p_top_ltv FROM ltv_percentiles) THEN 'cuenta_top'
            WHEN frequency > 100 THEN 'account_grande'
            WHEN frequency <= 3  THEN 'outlier'
            ELSE 'cuenta_media'
        END AS profile
    FROM dormant
)
SELECT
    customer_id,
    customer_name,
    ROUND(deal_risk_score::numeric, 1) AS deal_risk_score,
    last_purchase,
    first_purchase,
    ROUND(ltv_eur::numeric, 2) AS ltv_eur,
    ROUND(recovery_potential_eur::numeric, 2) AS recovery_potential_eur,
    ROUND(avg_order_eur::numeric, 2) AS avg_order_eur,
    recency_days,
    frequency,
    profile
FROM scored
ORDER BY deal_risk_score DESC
LIMIT {limit}
""".strip()


# ═══════════════════════════════════════════════════════════════════════════
# Public entry point — build all 5 queries from an entity_map
# ═══════════════════════════════════════════════════════════════════════════


SALES_V2_QUERY_KEYS = (
    "rfm_segmentation",
    "concentration_hhi",
    "concentration_top_customers",
    "cross_sell_matrix",
    "churn_risk_scoring",
)


def build_sales_v2_queries(entity_map: dict, months: int = 12) -> dict[str, str]:
    """
    Build the 5 sales v2 queries ready to execute.

    Callers with incomplete entity_maps (e.g. no invoice_lines/products) will
    get SQL that references fallback table names — let the executor error,
    then the DataPrefetcher records the failure and the narrator adapts.
    """
    months = int(months)  # VAL-170: enforce numeric type before f-string interpolation
    return {
        "rfm_segmentation": rfm_segmentation_sql(entity_map, months=months),
        "concentration_hhi": concentration_hhi_sql(entity_map, months=months),
        "concentration_top_customers": concentration_top_customers_sql(entity_map, months=months),
        "cross_sell_matrix": cross_sell_matrix_sql(entity_map, months=months),
        "churn_risk_scoring": churn_risk_scoring_sql(entity_map, months=months),
    }


def hhi_level(hhi: float) -> str:
    """Classify HHI per DOJ/antitrust thresholds (applied to customer concentration)."""
    if hhi < 1500:
        return "diversified"
    if hhi < 2500:
        return "moderate"
    return "high_risk"


# ═══════════════════════════════════════════════════════════════════════════
# Query-pack integration — append sales_v2 queries to an existing pack
# ═══════════════════════════════════════════════════════════════════════════


def append_to_query_pack(query_pack: dict, entity_map: dict, months: int = 12) -> dict:
    """
    Append the 5 sales_v2 queries to an existing query_pack (mutates and returns).

    The pipeline's `execute_queries` consumes `query_pack["queries"]`, where each
    entry is `{"id", "sql", "domain", "description", "params"}`. The keys we use
    here line up with what the sales narrator v2 expects in
    `query_results["results"]`.

    No-op when the entity_map lacks invoices/customers — skipping is silent so
    callers that build queries for non-sales schemas (e.g. tests with empty
    entity_maps) don't acquire synthetic SQL.
    """
    entities = entity_map.get("entities", {}) or {}
    if not ({"invoices", "customers"} <= set(entities.keys())):
        # Silent skip — we don't pollute query_pack.skipped (which is reserved
        # for the main template engine's tracked skips).
        return query_pack

    queries = build_sales_v2_queries(entity_map, months=months)
    descriptions = {
        "rfm_segmentation":
            "RFM segmentation (Recency/Frequency/Monetary) → 11 standard B2B segments",
        "concentration_hhi":
            "Herfindahl-Hirschman Index + CR1/CR5/CR10 concentration ratios",
        "concentration_top_customers":
            "Top-10 customers with LTV, share, last purchase, risk class",
        "cross_sell_matrix":
            "RFM segment × product category penetration (Magic Matrix)",
        "churn_risk_scoring":
            "Deal Risk Score for dormant customers (deterministic formula)",
    }
    pack_queries = query_pack.setdefault("queries", [])
    for qid, sql in queries.items():
        pack_queries.append({
            "id": qid,
            "sql": sql,
            "domain": "sales",
            "description": descriptions.get(qid, ""),
            "params": {"months": months},
        })
    return query_pack
