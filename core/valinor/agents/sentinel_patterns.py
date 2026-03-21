"""
Financial anomaly patterns for the Sentinel agent.
Based on ACFE (Association of Certified Fraud Examiners) fraud schemes
and quantitative finance anomaly detection methods.
"""
from __future__ import annotations
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class AnomalyPattern:
    id: str
    name: str
    description: str
    sql_template: str          # SQL to detect this pattern (parameterized)
    severity: str              # CRITICAL | HIGH | MEDIUM | LOW
    category: str              # "fraud_risk" | "data_quality" | "operational" | "financial"
    erp_tables: List[str]      # Required tables for this check
    interpretation: str        # How to interpret positive results


# The 15 most important patterns for B2B distributors/ERP systems:

PATTERNS: List[AnomalyPattern] = [
    AnomalyPattern(
        id="ghost_vendor",
        name="Proveedor fantasma (coincidencia dirección-empleado)",
        description="Proveedores con misma dirección que empleados o que comparten número de banco",
        sql_template="""
            SELECT bp.name as partner, bp.vat, COUNT(av.id) as invoices, SUM(av.amount_untaxed) as total
            FROM account_move av
            JOIN res_partner bp ON av.partner_id = bp.id
            WHERE av.move_type = 'in_invoice' AND av.state = 'posted'
            AND av.invoice_date BETWEEN :start AND :end
            AND (bp.vat IS NOT NULL AND bp.vat IN (
                SELECT vat FROM res_partner WHERE customer_rank > 0 AND vat IS NOT NULL
            ))
            GROUP BY bp.name, bp.vat
            HAVING SUM(av.amount_untaxed) > 5000
        """,
        severity="CRITICAL",
        category="fraud_risk",
        erp_tables=["account_move", "res_partner"],
        interpretation="Proveedor con mismo NIF que cliente — posible empresa fantasma o fraude de facturación"
    ),

    AnomalyPattern(
        id="round_amount_concentration",
        name="Concentración de montos redondos sospechosa",
        description="Facturas con montos exactamente redondos (5000, 10000) pueden indicar facturación ficticia",
        sql_template="""
            SELECT
                ROUND(amount_untaxed / 1000) * 1000 as round_amount,
                COUNT(*) as count,
                SUM(amount_untaxed) as total
            FROM account_move
            WHERE move_type = 'in_invoice' AND state = 'posted'
            AND invoice_date BETWEEN :start AND :end
            AND amount_untaxed = ROUND(amount_untaxed / 1000) * 1000
            AND amount_untaxed > 0
            GROUP BY round_amount
            HAVING COUNT(*) > 3
            ORDER BY total DESC
            LIMIT 10
        """,
        severity="MEDIUM",
        category="fraud_risk",
        erp_tables=["account_move"],
        interpretation="Alta concentración de facturas con montos exactamente redondos — verificar contra recibos físicos"
    ),

    AnomalyPattern(
        id="split_invoices_threshold",
        name="Facturas divididas para evadir límite de aprobación",
        description="Multiple invoices from same vendor on same date just below approval threshold",
        sql_template="""
            SELECT
                partner_id,
                bp.name as vendor,
                invoice_date,
                COUNT(*) as invoice_count,
                SUM(amount_untaxed) as total,
                MAX(amount_untaxed) as max_single
            FROM account_move am
            JOIN res_partner bp ON am.partner_id = bp.id
            WHERE am.move_type = 'in_invoice' AND am.state = 'posted'
            AND am.invoice_date BETWEEN :start AND :end
            GROUP BY partner_id, bp.name, invoice_date
            HAVING COUNT(*) >= 3 AND MAX(amount_untaxed) < 5000 AND SUM(amount_untaxed) > 10000
            ORDER BY total DESC
            LIMIT 10
        """,
        severity="HIGH",
        category="fraud_risk",
        erp_tables=["account_move", "res_partner"],
        interpretation="Mismo proveedor, misma fecha, múltiples facturas pequeñas — patrón clásico de evasión de aprobación"
    ),

    AnomalyPattern(
        id="customers_no_activity",
        name="Clientes activos sin actividad en período",
        description="Customers marked active but with zero revenue in the period",
        sql_template="""
            SELECT bp.name, bp.id
            FROM res_partner bp
            WHERE bp.customer_rank > 0 AND bp.active = TRUE
            AND bp.id NOT IN (
                SELECT DISTINCT partner_id FROM account_move
                WHERE move_type = 'out_invoice' AND state = 'posted'
                AND invoice_date BETWEEN :start AND :end
                AND partner_id IS NOT NULL
            )
            LIMIT 20
        """,
        severity="MEDIUM",
        category="operational",
        erp_tables=["res_partner", "account_move"],
        interpretation="Clientes formalmente activos sin compras en el período — posible churn silencioso o datos desactualizados"
    ),

    AnomalyPattern(
        id="credit_note_ratio",
        name="Ratio de notas de crédito anormalmente alto",
        description="High credit note to invoice ratio may indicate returns, errors, or fraud",
        sql_template="""
            SELECT
                COALESCE(SUM(CASE WHEN move_type='out_invoice' THEN amount_untaxed ELSE 0 END), 0) as gross_revenue,
                COALESCE(SUM(CASE WHEN move_type='out_refund' THEN amount_untaxed ELSE 0 END), 0) as total_credits,
                CASE
                    WHEN SUM(CASE WHEN move_type='out_invoice' THEN amount_untaxed ELSE 0 END) > 0
                    THEN ROUND(SUM(CASE WHEN move_type='out_refund' THEN amount_untaxed ELSE 0 END) * 100.0 /
                         SUM(CASE WHEN move_type='out_invoice' THEN amount_untaxed ELSE 0 END), 2)
                    ELSE 0
                END as credit_ratio_pct
            FROM account_move
            WHERE move_type IN ('out_invoice', 'out_refund')
            AND state = 'posted'
            AND invoice_date BETWEEN :start AND :end
        """,
        severity="HIGH",
        category="financial",
        erp_tables=["account_move"],
        interpretation="Credit ratio >10% is elevated; >20% requires explanation (returns policy, corrections, or fraud)"
    ),

    AnomalyPattern(
        id="duplicate_invoices",
        name="Facturas duplicadas por mismo proveedor e importe",
        description="Identical invoice amounts from same vendor within 30-day window — common double-payment scheme",
        sql_template="""
            SELECT
                am1.partner_id,
                bp.name as vendor,
                am1.amount_untaxed,
                am1.invoice_date as date1,
                am2.invoice_date as date2,
                am1.name as ref1,
                am2.name as ref2
            FROM account_move am1
            JOIN account_move am2
                ON am1.partner_id = am2.partner_id
                AND am1.amount_untaxed = am2.amount_untaxed
                AND am1.id < am2.id
                AND ABS(am2.invoice_date - am1.invoice_date) <= 30
            JOIN res_partner bp ON am1.partner_id = bp.id
            WHERE am1.move_type = 'in_invoice' AND am1.state = 'posted'
            AND am2.move_type = 'in_invoice' AND am2.state = 'posted'
            AND am1.invoice_date BETWEEN :start AND :end
            ORDER BY am1.amount_untaxed DESC
            LIMIT 20
        """,
        severity="HIGH",
        category="fraud_risk",
        erp_tables=["account_move", "res_partner"],
        interpretation="Mismo proveedor, mismo monto, fechas cercanas — verificar si corresponde a servicios recurrentes o pago duplicado"
    ),

    AnomalyPattern(
        id="weekend_invoices",
        name="Facturas registradas en fin de semana",
        description="Invoices posted on Saturday/Sunday may indicate backdating or unauthorized access",
        sql_template="""
            SELECT
                EXTRACT(DOW FROM invoice_date) as day_of_week,
                COUNT(*) as count,
                SUM(amount_untaxed) as total
            FROM account_move
            WHERE move_type IN ('in_invoice', 'out_invoice')
            AND state = 'posted'
            AND invoice_date BETWEEN :start AND :end
            AND EXTRACT(DOW FROM invoice_date) IN (0, 6)
            GROUP BY day_of_week
            ORDER BY day_of_week
        """,
        severity="MEDIUM",
        category="fraud_risk",
        erp_tables=["account_move"],
        interpretation="Actividad de facturación en fin de semana — puede indicar backdating, acceso no autorizado, o empresa con operación 7 días"
    ),

    AnomalyPattern(
        id="end_of_period_spike",
        name="Concentración anormal de ingresos al cierre de período",
        description="Revenue recognized disproportionately in the last 3 days of the period",
        sql_template="""
            SELECT
                CASE
                    WHEN invoice_date >= (:end::date - INTERVAL '3 days') THEN 'last_3_days'
                    ELSE 'rest_of_period'
                END as bucket,
                COUNT(*) as invoices,
                SUM(amount_untaxed) as revenue
            FROM account_move
            WHERE move_type = 'out_invoice' AND state = 'posted'
            AND invoice_date BETWEEN :start AND :end
            GROUP BY bucket
            ORDER BY bucket
        """,
        severity="HIGH",
        category="financial",
        erp_tables=["account_move"],
        interpretation="Revenue >20% en últimos 3 días del período — posible channel stuffing o reconocimiento de ingresos agresivo"
    ),

    AnomalyPattern(
        id="inactive_vendor_large_payment",
        name="Pago grande a proveedor sin historial reciente",
        description="Large payment to vendor with no invoices in the prior 12 months",
        sql_template="""
            SELECT
                am.partner_id,
                bp.name as vendor,
                am.amount_untaxed,
                am.invoice_date,
                am.name as ref
            FROM account_move am
            JOIN res_partner bp ON am.partner_id = bp.id
            WHERE am.move_type = 'in_invoice' AND am.state = 'posted'
            AND am.invoice_date BETWEEN :start AND :end
            AND am.amount_untaxed > 10000
            AND am.partner_id NOT IN (
                SELECT DISTINCT partner_id FROM account_move
                WHERE move_type = 'in_invoice' AND state = 'posted'
                AND invoice_date < :start
                AND invoice_date >= (:start::date - INTERVAL '12 months')
            )
            ORDER BY am.amount_untaxed DESC
            LIMIT 10
        """,
        severity="HIGH",
        category="fraud_risk",
        erp_tables=["account_move", "res_partner"],
        interpretation="Proveedor sin actividad previa recibiendo pagos grandes — requiere validación de contrato y autorización"
    ),

    AnomalyPattern(
        id="margin_compression_by_product",
        name="Compresión de margen atípica por línea de producto",
        description="Product lines with gross margin significantly below company average — pricing errors or theft",
        sql_template="""
            SELECT
                pt.name as product,
                SUM(sol.price_subtotal) as revenue,
                SUM(sol.product_uom_qty * pp.standard_price) as cost_estimate,
                CASE
                    WHEN SUM(sol.price_subtotal) > 0
                    THEN ROUND((1 - SUM(sol.product_uom_qty * pp.standard_price) /
                         SUM(sol.price_subtotal)) * 100, 2)
                    ELSE NULL
                END as margin_pct
            FROM sale_order_line sol
            JOIN sale_order so ON sol.order_id = so.id
            JOIN product_product pp ON sol.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE so.state IN ('sale', 'done')
            AND so.date_order BETWEEN :start AND :end
            GROUP BY pt.name
            HAVING SUM(sol.price_subtotal) > 1000
            ORDER BY margin_pct ASC
            LIMIT 15
        """,
        severity="MEDIUM",
        category="financial",
        erp_tables=["sale_order_line", "sale_order", "product_product", "product_template"],
        interpretation="Productos con margen <10% o negativo — revisar precio de costo, descuentos no autorizados, o errores de configuración"
    ),

    AnomalyPattern(
        id="overdue_receivables_concentration",
        name="Concentración de cartera vencida en pocos clientes",
        description="Top-3 customers by overdue AR represent disproportionate concentration risk",
        sql_template="""
            SELECT
                bp.name as customer,
                SUM(am.amount_residual) as overdue_amount,
                MAX(CURRENT_DATE - am.invoice_date_due) as max_days_overdue
            FROM account_move am
            JOIN res_partner bp ON am.partner_id = bp.id
            WHERE am.move_type = 'out_invoice'
            AND am.state = 'posted'
            AND am.payment_state IN ('not_paid', 'partial')
            AND am.invoice_date_due < CURRENT_DATE
            GROUP BY bp.name
            ORDER BY overdue_amount DESC
            LIMIT 10
        """,
        severity="HIGH",
        category="financial",
        erp_tables=["account_move", "res_partner"],
        interpretation="Top 3 clientes concentran cartera vencida — evaluar riesgo de crédito y necesidad de provisión"
    ),

    AnomalyPattern(
        id="journal_entry_without_invoice",
        name="Asientos manuales sin soporte de factura",
        description="Manual journal entries directly to revenue or expense accounts without linked invoice",
        sql_template="""
            SELECT
                aj.name as journal,
                aml.account_id,
                aa.name as account_name,
                COUNT(aml.id) as entries,
                SUM(ABS(aml.balance)) as total_amount
            FROM account_move_line aml
            JOIN account_move am ON aml.move_id = am.id
            JOIN account_journal aj ON am.journal_id = aj.id
            JOIN account_account aa ON aml.account_id = aa.id
            WHERE am.move_type = 'entry'
            AND am.state = 'posted'
            AND am.invoice_date BETWEEN :start AND :end
            AND aa.account_type IN ('income', 'expense')
            AND am.id NOT IN (
                SELECT id FROM account_move WHERE move_type IN ('out_invoice','in_invoice','out_refund','in_refund')
            )
            GROUP BY aj.name, aml.account_id, aa.name
            HAVING SUM(ABS(aml.balance)) > 1000
            ORDER BY total_amount DESC
            LIMIT 15
        """,
        severity="HIGH",
        category="fraud_risk",
        erp_tables=["account_move_line", "account_move", "account_journal", "account_account"],
        interpretation="Asientos manuales a cuentas de resultado sin factura de respaldo — riesgo de manipulación contable"
    ),

    AnomalyPattern(
        id="purchase_without_receipt",
        name="Facturas de compra sin recepción de mercancía",
        description="Vendor invoices with no matching warehouse receipt (3-way match failure)",
        sql_template="""
            SELECT
                am.name as invoice_ref,
                bp.name as vendor,
                am.amount_untaxed,
                am.invoice_date
            FROM account_move am
            JOIN res_partner bp ON am.partner_id = bp.id
            WHERE am.move_type = 'in_invoice'
            AND am.state = 'posted'
            AND am.invoice_date BETWEEN :start AND :end
            AND am.amount_untaxed > 500
            AND NOT EXISTS (
                SELECT 1 FROM purchase_order_line pol
                JOIN purchase_order po ON pol.order_id = po.id
                WHERE po.partner_id = am.partner_id
                AND po.date_order BETWEEN (:start::date - INTERVAL '60 days') AND :end
                AND po.state IN ('purchase', 'done')
            )
            ORDER BY am.amount_untaxed DESC
            LIMIT 15
        """,
        severity="MEDIUM",
        category="fraud_risk",
        erp_tables=["account_move", "res_partner", "purchase_order_line", "purchase_order"],
        interpretation="Factura sin orden de compra asociada — posible pago ficticio o bypassing del proceso de aprobación"
    ),

    AnomalyPattern(
        id="excessive_discounts",
        name="Descuentos excesivos por vendedor",
        description="Sales reps granting discounts significantly above company average",
        sql_template="""
            SELECT
                ru.name as salesperson,
                COUNT(so.id) as orders,
                AVG(sol.discount) as avg_discount_pct,
                SUM(sol.price_subtotal) as revenue,
                SUM(sol.price_unit * sol.product_uom_qty * sol.discount / 100) as discount_given
            FROM sale_order so
            JOIN sale_order_line sol ON sol.order_id = so.id
            JOIN res_users ru ON so.user_id = ru.id
            WHERE so.state IN ('sale', 'done')
            AND so.date_order BETWEEN :start AND :end
            AND sol.discount > 0
            GROUP BY ru.name
            HAVING AVG(sol.discount) > 15 OR SUM(sol.price_unit * sol.product_uom_qty * sol.discount / 100) > 5000
            ORDER BY avg_discount_pct DESC
            LIMIT 10
        """,
        severity="MEDIUM",
        category="financial",
        erp_tables=["sale_order", "sale_order_line", "res_users"],
        interpretation="Vendedores con descuento promedio >15% — posible abuso de autorización o colusión con clientes"
    ),

    AnomalyPattern(
        id="benford_first_digit_invoices",
        name="Ley de Benford — anomalía en primer dígito de facturas",
        description="Distribution of invoice first digits deviates from expected Benford's Law distribution",
        sql_template="""
            SELECT
                CAST(LEFT(CAST(CAST(amount_untaxed AS INTEGER) AS VARCHAR), 1) AS INTEGER) as first_digit,
                COUNT(*) as observed_count,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as observed_pct
            FROM account_move
            WHERE move_type IN ('in_invoice', 'out_invoice')
            AND state = 'posted'
            AND invoice_date BETWEEN :start AND :end
            AND amount_untaxed >= 10
            GROUP BY first_digit
            ORDER BY first_digit
        """,
        severity="HIGH",
        category="fraud_risk",
        erp_tables=["account_move"],
        interpretation="Desviación significativa de la Ley de Benford indica posible manipulación sistemática de montos de facturas"
    ),
]


def get_patterns_for_tables(available_tables: List[str]) -> List[AnomalyPattern]:
    """Return only patterns where all required tables are available."""
    available = set(t.lower() for t in available_tables)
    return [p for p in PATTERNS if all(t.lower() in available for t in p.erp_tables)]


def get_patterns_by_category(category: str) -> List[AnomalyPattern]:
    """Return patterns filtered by category."""
    return [p for p in PATTERNS if p.category == category]


def get_patterns_by_severity(severity: str) -> List[AnomalyPattern]:
    """Return patterns filtered by severity level."""
    return [p for p in PATTERNS if p.severity == severity]


def build_sentinel_context(patterns: List[AnomalyPattern]) -> str:
    """Build context block to inject into Sentinel agent prompt."""
    lines = ["PATRONES DE FRAUDE Y ANOMALÍA FINANCIERA A INVESTIGAR:"]
    for p in patterns:
        lines.append(f"  [{p.severity}] {p.name}: {p.description}")
    lines.append("\nINSTRUCCIÓN: Para cada hallazgo, indica si coincide con alguno de estos patrones.")
    return "\n".join(lines)
