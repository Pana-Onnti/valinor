"""
Playground Swarm — Agent 3: ERP Forge.

Tier: generator — the core synthetic ERP database generator.
Creates realistic ERP databases with Etendo or Odoo schemas,
using statistical distributions for realistic data patterns.
"""

import math
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

# ── Schema templates ──────────────────────────────────────────────────

ETENDO_SCHEMA = {
    "c_bpartner": """
        CREATE TABLE c_bpartner (
            c_bpartner_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            taxid TEXT,
            is_customer TEXT DEFAULT 'Y',
            is_vendor TEXT DEFAULT 'N',
            is_active TEXT DEFAULT 'Y',
            created TEXT,
            updated TEXT
        )
    """,
    "m_product": """
        CREATE TABLE m_product (
            m_product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            value TEXT,
            upc TEXT,
            producttype TEXT DEFAULT 'I',
            listprice REAL,
            standardprice REAL,
            is_active TEXT DEFAULT 'Y'
        )
    """,
    "c_invoice": """
        CREATE TABLE c_invoice (
            c_invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
            c_bpartner_id INTEGER NOT NULL,
            documentno TEXT NOT NULL,
            dateinvoiced TEXT NOT NULL,
            totallines REAL DEFAULT 0,
            grandtotal REAL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            docstatus TEXT DEFAULT 'CO',
            issotrx TEXT DEFAULT 'Y',
            description TEXT,
            FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id)
        )
    """,
    "c_invoiceline": """
        CREATE TABLE c_invoiceline (
            c_invoiceline_id INTEGER PRIMARY KEY AUTOINCREMENT,
            c_invoice_id INTEGER NOT NULL,
            m_product_id INTEGER,
            line INTEGER,
            qtyinvoiced REAL DEFAULT 1,
            priceactual REAL DEFAULT 0,
            linenetamt REAL DEFAULT 0,
            FOREIGN KEY (c_invoice_id) REFERENCES c_invoice(c_invoice_id),
            FOREIGN KEY (m_product_id) REFERENCES m_product(m_product_id)
        )
    """,
    "c_payment": """
        CREATE TABLE c_payment (
            c_payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            c_bpartner_id INTEGER NOT NULL,
            c_invoice_id INTEGER,
            documentno TEXT,
            datetrx TEXT NOT NULL,
            payamt REAL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            tendertype TEXT DEFAULT 'K',
            docstatus TEXT DEFAULT 'CO',
            FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id),
            FOREIGN KEY (c_invoice_id) REFERENCES c_invoice(c_invoice_id)
        )
    """,
    "c_order": """
        CREATE TABLE c_order (
            c_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            c_bpartner_id INTEGER NOT NULL,
            documentno TEXT NOT NULL,
            dateordered TEXT NOT NULL,
            totallines REAL DEFAULT 0,
            grandtotal REAL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            docstatus TEXT DEFAULT 'CO',
            issotrx TEXT DEFAULT 'Y',
            FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id)
        )
    """,
}

ODOO_SCHEMA = {
    "res_partner": """
        CREATE TABLE res_partner (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            vat TEXT,
            customer_rank INTEGER DEFAULT 1,
            supplier_rank INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            create_date TEXT,
            write_date TEXT
        )
    """,
    "product_template": """
        CREATE TABLE product_template (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            default_code TEXT,
            list_price REAL,
            standard_price REAL,
            type TEXT DEFAULT 'consu',
            active INTEGER DEFAULT 1
        )
    """,
    "account_move": """
        CREATE TABLE account_move (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            amount_untaxed REAL DEFAULT 0,
            amount_total REAL DEFAULT 0,
            currency_id TEXT DEFAULT 'USD',
            state TEXT DEFAULT 'posted',
            move_type TEXT DEFAULT 'out_invoice',
            FOREIGN KEY (partner_id) REFERENCES res_partner(id)
        )
    """,
    "account_move_line": """
        CREATE TABLE account_move_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            move_id INTEGER NOT NULL,
            product_id INTEGER,
            quantity REAL DEFAULT 1,
            price_unit REAL DEFAULT 0,
            price_subtotal REAL DEFAULT 0,
            FOREIGN KEY (move_id) REFERENCES account_move(id),
            FOREIGN KEY (product_id) REFERENCES product_template(id)
        )
    """,
    "account_payment": """
        CREATE TABLE account_payment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            move_id INTEGER,
            name TEXT,
            date TEXT NOT NULL,
            amount REAL DEFAULT 0,
            currency_id TEXT DEFAULT 'USD',
            payment_type TEXT DEFAULT 'inbound',
            state TEXT DEFAULT 'posted',
            FOREIGN KEY (partner_id) REFERENCES res_partner(id),
            FOREIGN KEY (move_id) REFERENCES account_move(id)
        )
    """,
    "sale_order": """
        CREATE TABLE sale_order (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            date_order TEXT NOT NULL,
            amount_untaxed REAL DEFAULT 0,
            amount_total REAL DEFAULT 0,
            currency_id TEXT DEFAULT 'USD',
            state TEXT DEFAULT 'sale',
            FOREIGN KEY (partner_id) REFERENCES res_partner(id)
        )
    """,
}


class ERPForgeAgent(PlaygroundAgent):
    """Core generator: creates realistic ERP databases with Etendo/Odoo schemas."""

    def __init__(self) -> None:
        self.name = "erp_forge"
        self.tier = "generator"
        super().__init__()

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        datasets: List[DatasetRecord] = []
        errors: List[str] = []

        # Always generate Etendo
        try:
            ds = self._generate_erp(ctx, "etendo")
            datasets.append(ds)
            await ctx.generated_datasets.put(ds)
        except Exception as exc:
            msg = f"Etendo generation failed: {exc}"
            self.logger.error(msg)
            errors.append(msg)

        # 50% chance to also generate Odoo
        if random.random() < 0.5:
            try:
                ds = self._generate_erp(ctx, "odoo")
                datasets.append(ds)
                await ctx.generated_datasets.put(ds)
            except Exception as exc:
                msg = f"Odoo generation failed: {exc}"
                self.logger.error(msg)
                errors.append(msg)

        self._datasets_produced += len(datasets)
        return AgentResult(
            agent_name=self.name,
            success=len(datasets) > 0,
            datasets=datasets,
            errors=errors if errors else None,
            stats={"datasets_produced": len(datasets)},
        )

    def _generate_erp(self, ctx: PlaygroundContext, schema_type: str) -> DatasetRecord:
        try:
            import numpy as np
            from faker import Faker
        except ImportError as exc:
            raise RuntimeError(f"Missing dependency: {exc}. Install with: pip install numpy faker") from exc

        fake = Faker()
        run_id = uuid.uuid4().hex[:8]
        now = datetime.utcnow()

        # ── Randomized parameters ─────────────────────────────────────
        num_customers = random.randint(10, 200)
        num_invoices = random.randint(500, 50000)
        num_products = random.randint(20, 500)
        years_back = random.randint(1, 5)
        currency = random.choice(["USD", "EUR", "ARS", "GBP", "BRL"])

        date_start = now - timedelta(days=365 * years_back)

        db_name = f"erp_{schema_type}_{run_id}.db"
        db_path = ctx.datasets_dir / "synthetic" / db_name
        db_path.parent.mkdir(parents=True, exist_ok=True)

        schema = ETENDO_SCHEMA if schema_type == "etendo" else ODOO_SCHEMA
        conn = sqlite3.connect(str(db_path))

        # Create tables
        for ddl in schema.values():
            conn.execute(ddl)

        row_counts: Dict[str, int] = {}

        if schema_type == "etendo":
            row_counts = self._populate_etendo(conn, fake, np, num_customers, num_invoices, num_products, currency, date_start, now)
        else:
            row_counts = self._populate_odoo(conn, fake, np, num_customers, num_invoices, num_products, currency, date_start, now)

        conn.commit()
        conn.close()

        self.logger.info(
            "%s ERP (%s): %d customers, %d invoices, %d products — %s",
            schema_type, run_id, num_customers, num_invoices, num_products, currency,
        )

        return DatasetRecord(
            name=db_name.replace(".db", ""),
            path=str(db_path),
            source_agent=self.name,
            tier=self.tier,
            created_at=now.isoformat(),
            row_counts=row_counts,
            tags=["synthetic", "erp", schema_type, currency],
            metadata={
                "schema_type": schema_type,
                "num_customers": num_customers,
                "num_invoices": num_invoices,
                "num_products": num_products,
                "years_back": years_back,
                "currency": currency,
            },
        )

    def _populate_etendo(
        self,
        conn: sqlite3.Connection,
        fake: Any,
        np: Any,
        num_customers: int,
        num_invoices: int,
        num_products: int,
        currency: str,
        date_start: datetime,
        date_end: datetime,
    ) -> Dict[str, int]:
        now_str = datetime.utcnow().isoformat()
        date_range_days = (date_end - date_start).days or 1

        # ── Customers ─────────────────────────────────────────────────
        customer_ids: List[int] = []
        for i in range(1, num_customers + 1):
            is_active = "Y" if random.random() < 0.8 else "N"
            conn.execute(
                "INSERT INTO c_bpartner (c_bpartner_id, name, taxid, is_active, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (i, fake.company(), fake.bothify("??-########"), is_active, now_str, now_str),
            )
            customer_ids.append(i)

        # ── Products ──────────────────────────────────────────────────
        product_ids: List[int] = []
        product_prices = np.exp(np.random.normal(3.5, 1.0, num_products))
        for i in range(1, num_products + 1):
            price = round(float(product_prices[i - 1]), 2)
            conn.execute(
                "INSERT INTO m_product (m_product_id, name, value, listprice, standardprice) "
                "VALUES (?, ?, ?, ?, ?)",
                (i, fake.catch_phrase(), f"PROD-{i:05d}", price, round(price * 0.6, 2)),
            )
            product_ids.append(i)

        # ── Pareto customer weights (20/80 rule) ─────────────────────
        alpha = 1.16  # Pareto shape for ~80/20
        weights = np.random.pareto(alpha, num_customers) + 1
        weights = weights / weights.sum()

        # ── Invoice amounts: log-normal ──────────────────────────────
        amounts = np.exp(np.random.normal(6, 1.5, num_invoices))

        # ── Invoices ──────────────────────────────────────────────────
        invoice_data: List[Tuple[int, int, float]] = []  # (invoice_id, bp_id, amount)
        for i in range(1, num_invoices + 1):
            bp_id = int(np.random.choice(customer_ids, p=weights))
            amount = round(float(amounts[i - 1]), 2)
            inv_date = date_start + timedelta(days=random.randint(0, date_range_days))

            # docstatus: 95% CO, 3% DR, 2% VO
            r = random.random()
            docstatus = "CO" if r < 0.95 else ("DR" if r < 0.98 else "VO")

            conn.execute(
                "INSERT INTO c_invoice "
                "(c_invoice_id, c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, currency, docstatus) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (i, bp_id, f"INV-{i:07d}", inv_date.strftime("%Y-%m-%d"), amount, amount, currency, docstatus),
            )
            invoice_data.append((i, bp_id, amount))

            # Invoice lines (1-5 per invoice)
            num_lines = random.randint(1, min(5, num_products))
            line_products = random.sample(product_ids, num_lines)
            remaining = amount
            for line_no, prod_id in enumerate(line_products, 1):
                if line_no == num_lines:
                    line_amt = round(remaining, 2)
                else:
                    line_amt = round(remaining * random.uniform(0.1, 0.5), 2)
                    remaining -= line_amt
                qty = max(1, random.randint(1, 20))
                price = round(line_amt / qty, 2) if qty > 0 else line_amt
                conn.execute(
                    "INSERT INTO c_invoiceline "
                    "(c_invoice_id, m_product_id, line, qtyinvoiced, priceactual, linenetamt) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (i, prod_id, line_no * 10, qty, price, line_amt),
                )

        # ── Payments (~70% of invoices) ──────────────────────────────
        payment_count = 0
        for inv_id, bp_id, amount in invoice_data:
            if random.random() < 0.7:
                pay_date = date_start + timedelta(days=random.randint(0, date_range_days))
                # Some partial payments
                if random.random() < 0.1:
                    pay_amt = round(amount * random.uniform(0.3, 0.9), 2)
                else:
                    pay_amt = amount
                payment_count += 1
                conn.execute(
                    "INSERT INTO c_payment "
                    "(c_bpartner_id, c_invoice_id, documentno, datetrx, payamt, currency) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (bp_id, inv_id, f"PAY-{payment_count:07d}", pay_date.strftime("%Y-%m-%d"), pay_amt, currency),
                )

        # ── Orders (slightly fewer than invoices) ────────────────────
        num_orders = int(num_invoices * random.uniform(0.6, 0.9))
        for i in range(1, num_orders + 1):
            bp_id = int(np.random.choice(customer_ids, p=weights))
            amount = round(float(np.exp(np.random.normal(6, 1.5))), 2)
            ord_date = date_start + timedelta(days=random.randint(0, date_range_days))
            r = random.random()
            docstatus = "CO" if r < 0.95 else ("DR" if r < 0.98 else "VO")
            conn.execute(
                "INSERT INTO c_order "
                "(c_bpartner_id, documentno, dateordered, totallines, grandtotal, currency, docstatus) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (bp_id, f"ORD-{i:07d}", ord_date.strftime("%Y-%m-%d"), amount, amount, currency, docstatus),
            )

        return {
            "c_bpartner": num_customers,
            "m_product": num_products,
            "c_invoice": num_invoices,
            "c_invoiceline": num_invoices,  # approximate
            "c_payment": payment_count,
            "c_order": num_orders,
        }

    def _populate_odoo(
        self,
        conn: sqlite3.Connection,
        fake: Any,
        np: Any,
        num_customers: int,
        num_invoices: int,
        num_products: int,
        currency: str,
        date_start: datetime,
        date_end: datetime,
    ) -> Dict[str, int]:
        now_str = datetime.utcnow().isoformat()
        date_range_days = (date_end - date_start).days or 1

        # ── Partners ──────────────────────────────────────────────────
        partner_ids: List[int] = []
        for i in range(1, num_customers + 1):
            active = 1 if random.random() < 0.8 else 0
            conn.execute(
                "INSERT INTO res_partner (id, name, vat, active, create_date, write_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (i, fake.company(), fake.bothify("??########"), active, now_str, now_str),
            )
            partner_ids.append(i)

        # ── Products ──────────────────────────────────────────────────
        product_ids: List[int] = []
        product_prices = np.exp(np.random.normal(3.5, 1.0, num_products))
        for i in range(1, num_products + 1):
            price = round(float(product_prices[i - 1]), 2)
            conn.execute(
                "INSERT INTO product_template (id, name, default_code, list_price, standard_price) "
                "VALUES (?, ?, ?, ?, ?)",
                (i, fake.catch_phrase(), f"PROD-{i:05d}", price, round(price * 0.6, 2)),
            )
            product_ids.append(i)

        # Pareto weights
        alpha = 1.16
        weights = np.random.pareto(alpha, num_customers) + 1
        weights = weights / weights.sum()

        amounts = np.exp(np.random.normal(6, 1.5, num_invoices))

        # ── Account moves (invoices) ─────────────────────────────────
        move_data: List[Tuple[int, int, float]] = []
        for i in range(1, num_invoices + 1):
            partner_id = int(np.random.choice(partner_ids, p=weights))
            amount = round(float(amounts[i - 1]), 2)
            inv_date = date_start + timedelta(days=random.randint(0, date_range_days))

            r = random.random()
            state = "posted" if r < 0.95 else ("draft" if r < 0.98 else "cancel")

            conn.execute(
                "INSERT INTO account_move "
                "(id, partner_id, name, invoice_date, amount_untaxed, amount_total, currency_id, state) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (i, partner_id, f"INV/{i:07d}", inv_date.strftime("%Y-%m-%d"), amount, amount, currency, state),
            )
            move_data.append((i, partner_id, amount))

            # Move lines
            num_lines = random.randint(1, min(5, num_products))
            line_products = random.sample(product_ids, num_lines)
            remaining = amount
            for line_no, prod_id in enumerate(line_products, 1):
                if line_no == num_lines:
                    line_amt = round(remaining, 2)
                else:
                    line_amt = round(remaining * random.uniform(0.1, 0.5), 2)
                    remaining -= line_amt
                qty = max(1, random.randint(1, 20))
                price = round(line_amt / qty, 2) if qty > 0 else line_amt
                conn.execute(
                    "INSERT INTO account_move_line "
                    "(move_id, product_id, quantity, price_unit, price_subtotal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (i, prod_id, qty, price, line_amt),
                )

        # ── Payments ──────────────────────────────────────────────────
        payment_count = 0
        for move_id, partner_id, amount in move_data:
            if random.random() < 0.7:
                pay_date = date_start + timedelta(days=random.randint(0, date_range_days))
                if random.random() < 0.1:
                    pay_amt = round(amount * random.uniform(0.3, 0.9), 2)
                else:
                    pay_amt = amount
                payment_count += 1
                conn.execute(
                    "INSERT INTO account_payment "
                    "(partner_id, move_id, name, date, amount, currency_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (partner_id, move_id, f"PAY/{payment_count:07d}", pay_date.strftime("%Y-%m-%d"), pay_amt, currency),
                )

        # ── Sale orders ───────────────────────────────────────────────
        num_orders = int(num_invoices * random.uniform(0.6, 0.9))
        for i in range(1, num_orders + 1):
            partner_id = int(np.random.choice(partner_ids, p=weights))
            amount = round(float(np.exp(np.random.normal(6, 1.5))), 2)
            ord_date = date_start + timedelta(days=random.randint(0, date_range_days))
            r = random.random()
            state = "sale" if r < 0.95 else ("draft" if r < 0.98 else "cancel")
            conn.execute(
                "INSERT INTO sale_order "
                "(partner_id, name, date_order, amount_untaxed, amount_total, currency_id, state) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (partner_id, f"SO/{i:07d}", ord_date.strftime("%Y-%m-%d"), amount, amount, currency, state),
            )

        return {
            "res_partner": num_customers,
            "product_template": num_products,
            "account_move": num_invoices,
            "account_move_line": num_invoices,  # approximate
            "account_payment": payment_count,
            "sale_order": num_orders,
        }
