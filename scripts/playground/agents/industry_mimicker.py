"""
Playground Swarm — Agent 4: Industry Mimicker.

Tier: generator — generates industry-specific datasets with controlled anomalies.
Supports retail, wholesale, services, and manufacturing profiles.
"""

import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

# ── Generic ERP schema (shared across industries) ────────────────────

GENERIC_ERP_SCHEMA = {
    "c_bpartner": """
        CREATE TABLE c_bpartner (
            c_bpartner_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            taxid TEXT,
            is_customer TEXT DEFAULT 'Y',
            is_vendor TEXT DEFAULT 'N',
            is_active TEXT DEFAULT 'Y',
            created TEXT
        )
    """,
    "m_product": """
        CREATE TABLE m_product (
            m_product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            value TEXT,
            producttype TEXT DEFAULT 'I',
            listprice REAL,
            is_active TEXT DEFAULT 'Y',
            parent_product_id INTEGER
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
            FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id)
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
            docstatus TEXT DEFAULT 'CO',
            FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id),
            FOREIGN KEY (c_invoice_id) REFERENCES c_invoice(c_invoice_id)
        )
    """,
}

# ── Industry profiles ────────────────────────────────────────────────

INDUSTRY_PROFILES = {
    "retail": {
        "num_customers": (200, 2000),
        "num_invoices": (100, 5000),
        "amount_range": (5.0, 500.0),
        "num_products": (50, 500),
        "description": "Many small transactions, many customers",
    },
    "wholesale": {
        "num_customers": (10, 50),
        "num_invoices": (50, 500),
        "amount_range": (1000.0, 100000.0),
        "num_products": (20, 100),
        "description": "Fewer large transactions, few big customers",
    },
    "services": {
        "num_customers": (20, 100),
        "num_invoices": (100, 1200),
        "amount_range": (500.0, 10000.0),
        "num_products": (5, 30),
        "description": "Recurring monthly invoices, fixed amounts +/- 10%",
    },
    "manufacturing": {
        "num_customers": (30, 150),
        "num_invoices": (100, 2000),
        "amount_range": (200.0, 50000.0),
        "num_products": (50, 300),
        "description": "BOM-like product relationships, raw + finished goods",
    },
}

# ── Anomaly types ─────────────────────────────────────────────────────

ANOMALY_TYPES = [
    "ghost_vendor",
    "split_invoices",
    "round_amounts",
    "duplicate_payments",
    "future_dates",
    "negative_amounts",
]


class IndustryMimickerAgent(PlaygroundAgent):
    """Generates industry-specific datasets with controlled anomaly injection."""

    def __init__(self) -> None:
        self.name = "industry_mimicker"
        self.tier = "generator"
        super().__init__()

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        try:
            import numpy as np
            from faker import Faker
        except ImportError as exc:
            return AgentResult(
                agent_name=self.name,
                success=False,
                errors=[f"Missing dependency: {exc}. Install: pip install numpy faker"],
            )

        industry = random.choice(list(INDUSTRY_PROFILES.keys()))
        profile = INDUSTRY_PROFILES[industry]
        fake = Faker()
        run_id = uuid.uuid4().hex[:8]
        now = datetime.utcnow()

        db_name = f"industry_{industry}_{run_id}.db"
        db_path = ctx.datasets_dir / "synthetic" / db_name
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))

        # Create tables
        for ddl in GENERIC_ERP_SCHEMA.values():
            conn.execute(ddl)

        # ── Generate base data ────────────────────────────────────────
        num_customers = random.randint(*profile["num_customers"])
        num_invoices = random.randint(*profile["num_invoices"])
        num_products = random.randint(*profile["num_products"])
        amt_lo, amt_hi = profile["amount_range"]
        date_start = now - timedelta(days=365 * random.randint(1, 3))
        date_range_days = (now - date_start).days or 1

        # Customers
        customer_ids: List[int] = []
        for i in range(1, num_customers + 1):
            conn.execute(
                "INSERT INTO c_bpartner (c_bpartner_id, name, taxid, is_customer, created) "
                "VALUES (?, ?, ?, 'Y', ?)",
                (i, fake.company(), fake.bothify("??-########"), now.isoformat()),
            )
            customer_ids.append(i)

        # Products
        product_ids: List[int] = []
        for i in range(1, num_products + 1):
            price = round(random.uniform(amt_lo * 0.1, amt_hi * 0.3), 2)
            parent_id = None
            if industry == "manufacturing" and i > num_products // 2:
                # Finished goods reference raw materials (BOM-like)
                parent_id = random.randint(1, num_products // 2)
            conn.execute(
                "INSERT INTO m_product (m_product_id, name, value, listprice, producttype, parent_product_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    i,
                    fake.catch_phrase(),
                    f"PROD-{i:05d}",
                    price,
                    "R" if (industry == "manufacturing" and i <= num_products // 2) else "I",
                    parent_id,
                ),
            )
            product_ids.append(i)

        # Invoices
        invoice_data: List[Tuple[int, int, float, str]] = []  # (inv_id, bp_id, amount, date)

        if industry == "services":
            # Recurring: same customers, monthly, fixed amount +/- 10%
            inv_id = 0
            for cust_id in customer_ids:
                base_amount = round(random.uniform(amt_lo, amt_hi), 2)
                months = (now - date_start).days // 30
                for m in range(months):
                    inv_id += 1
                    if inv_id > num_invoices:
                        break
                    amount = round(base_amount * random.uniform(0.9, 1.1), 2)
                    inv_date = (date_start + timedelta(days=30 * m)).strftime("%Y-%m-%d")
                    conn.execute(
                        "INSERT INTO c_invoice "
                        "(c_invoice_id, c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, docstatus) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'CO')",
                        (inv_id, cust_id, f"INV-{inv_id:07d}", inv_date, amount, amount),
                    )
                    invoice_data.append((inv_id, cust_id, amount, inv_date))
                if inv_id >= num_invoices:
                    break
        else:
            # Standard: random amounts within range
            amounts = np.random.uniform(amt_lo, amt_hi, num_invoices)
            # Pareto customer distribution
            weights = np.random.pareto(1.16, num_customers) + 1
            weights = weights / weights.sum()

            for i in range(1, num_invoices + 1):
                bp_id = int(np.random.choice(customer_ids, p=weights))
                amount = round(float(amounts[i - 1]), 2)
                inv_date = (date_start + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO c_invoice "
                    "(c_invoice_id, c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, docstatus) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'CO')",
                    (i, bp_id, f"INV-{i:07d}", inv_date, amount, amount),
                )
                invoice_data.append((i, bp_id, amount, inv_date))

        # Payments (~70%)
        payment_count = 0
        for inv_id, bp_id, amount, _ in invoice_data:
            if random.random() < 0.7:
                payment_count += 1
                pay_date = (date_start + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO c_payment "
                    "(c_bpartner_id, c_invoice_id, documentno, datetrx, payamt) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (bp_id, inv_id, f"PAY-{payment_count:07d}", pay_date, amount),
                )

        # ── Anomaly injection ─────────────────────────────────────────
        num_anomalies = random.randint(2, 5)
        selected_anomalies = random.sample(ANOMALY_TYPES, min(num_anomalies, len(ANOMALY_TYPES)))
        injected_anomalies: List[str] = []

        for anomaly in selected_anomalies:
            try:
                self._inject_anomaly(conn, anomaly, customer_ids, invoice_data, fake, now, date_range_days, date_start)
                injected_anomalies.append(anomaly)
            except Exception as exc:
                self.logger.warning("Failed to inject anomaly %s: %s", anomaly, exc)

        conn.commit()
        conn.close()

        actual_invoices = len(invoice_data)
        row_counts = {
            "c_bpartner": num_customers,
            "m_product": num_products,
            "c_invoice": actual_invoices,
            "c_payment": payment_count,
        }

        self.logger.info(
            "%s industry (%s): %d invoices, anomalies: %s",
            industry, run_id, actual_invoices, injected_anomalies,
        )

        self._datasets_produced += 1
        ds = DatasetRecord(
            name=db_name.replace(".db", ""),
            path=str(db_path),
            source_agent=self.name,
            tier=self.tier,
            created_at=now.isoformat(),
            row_counts=row_counts,
            tags=["synthetic", "erp", "industry", industry] + injected_anomalies,
            metadata={
                "industry": industry,
                "anomalies_injected": injected_anomalies,
                "num_anomalies": len(injected_anomalies),
            },
        )
        await ctx.generated_datasets.put(ds)

        return AgentResult(
            agent_name=self.name,
            success=True,
            datasets=[ds],
            stats={
                "industry": industry,
                "anomalies": injected_anomalies,
                "invoices": actual_invoices,
            },
        )

    def _inject_anomaly(
        self,
        conn: sqlite3.Connection,
        anomaly: str,
        customer_ids: List[int],
        invoice_data: List[Tuple[int, int, float, str]],
        fake: Any,
        now: datetime,
        date_range_days: int,
        date_start: datetime,
    ) -> None:
        max_inv_id = max(d[0] for d in invoice_data) if invoice_data else 0

        if anomaly == "ghost_vendor":
            # Vendor with same taxid as a customer
            cursor = conn.execute(
                "SELECT taxid FROM c_bpartner WHERE is_customer = 'Y' LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                conn.execute(
                    "INSERT INTO c_bpartner (name, taxid, is_customer, is_vendor, created) "
                    "VALUES (?, ?, 'N', 'Y', ?)",
                    (fake.company() + " Holdings", row[0], now.isoformat()),
                )

        elif anomaly == "split_invoices":
            # 3+ invoices same customer/date just under $10K
            bp_id = random.choice(customer_ids)
            split_date = (date_start + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d")
            for j in range(random.randint(3, 6)):
                amount = round(random.uniform(9500, 9999), 2)
                conn.execute(
                    "INSERT INTO c_invoice "
                    "(c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, docstatus) "
                    "VALUES (?, ?, ?, ?, ?, 'CO')",
                    (bp_id, f"SPLIT-{max_inv_id + j + 1:07d}", split_date, amount, amount),
                )

        elif anomaly == "round_amounts":
            # Cluster of invoices at exact round numbers
            bp_id = random.choice(customer_ids)
            for round_amt in [1000.0, 5000.0, 10000.0]:
                for _ in range(random.randint(2, 4)):
                    inv_date = (date_start + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d")
                    conn.execute(
                        "INSERT INTO c_invoice "
                        "(c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, docstatus) "
                        "VALUES (?, ?, ?, ?, ?, 'CO')",
                        (bp_id, f"RND-{uuid.uuid4().hex[:6]}", inv_date, round_amt, round_amt),
                    )

        elif anomaly == "duplicate_payments":
            # Same amount/date/customer paid twice
            if invoice_data:
                inv_id, bp_id, amount, inv_date = random.choice(invoice_data)
                for _ in range(2):
                    conn.execute(
                        "INSERT INTO c_payment "
                        "(c_bpartner_id, c_invoice_id, documentno, datetrx, payamt) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (bp_id, inv_id, f"DUPPAY-{uuid.uuid4().hex[:6]}", inv_date, amount),
                    )

        elif anomaly == "future_dates":
            # Invoice dated in 2099
            bp_id = random.choice(customer_ids)
            conn.execute(
                "INSERT INTO c_invoice "
                "(c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, docstatus) "
                "VALUES (?, ?, '2099-12-31', 1500.00, 1500.00, 'CO')",
                (bp_id, f"FUT-{uuid.uuid4().hex[:6]}"),
            )

        elif anomaly == "negative_amounts":
            # Negative invoice amounts
            bp_id = random.choice(customer_ids)
            for _ in range(random.randint(2, 5)):
                amount = -round(random.uniform(100, 5000), 2)
                inv_date = (date_start + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d")
                conn.execute(
                    "INSERT INTO c_invoice "
                    "(c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, docstatus) "
                    "VALUES (?, ?, ?, ?, ?, 'CO')",
                    (bp_id, f"NEG-{uuid.uuid4().hex[:6]}", inv_date, amount, amount),
                )
