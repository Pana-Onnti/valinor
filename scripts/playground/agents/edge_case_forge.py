"""
Playground Swarm — Agent 5: Edge Case Forge.

Tier: generator — creates extreme/adversarial datasets to test system resilience.
Generates one SQLite DB per edge case, covering empty tables, nulls, type coercion
traps, encoding issues, and boundary values.
"""

import random
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

# ── Generic ERP schema (minimal) ─────────────────────────────────────

GENERIC_SCHEMA = {
    "c_bpartner": """
        CREATE TABLE c_bpartner (
            c_bpartner_id INTEGER PRIMARY KEY,
            name TEXT,
            taxid TEXT,
            is_customer TEXT,
            is_active TEXT
        )
    """,
    "c_invoice": """
        CREATE TABLE c_invoice (
            c_invoice_id INTEGER PRIMARY KEY,
            c_bpartner_id INTEGER,
            documentno TEXT,
            dateinvoiced TEXT,
            grandtotal REAL,
            docstatus TEXT
        )
    """,
    "c_payment": """
        CREATE TABLE c_payment (
            c_payment_id INTEGER PRIMARY KEY,
            c_bpartner_id INTEGER,
            c_invoice_id INTEGER,
            datetrx TEXT,
            payamt REAL,
            docstatus TEXT
        )
    """,
    "m_product": """
        CREATE TABLE m_product (
            m_product_id INTEGER PRIMARY KEY,
            name TEXT,
            value TEXT,
            listprice REAL,
            is_active TEXT
        )
    """,
}

# ── Edge case definitions ────────────────────────────────────────────

EDGE_CASES = [
    "empty_tables",
    "single_row",
    "all_nulls",
    "mixed_types",
    "huge_amounts",
    "negative_everything",
    "duplicate_pks",
    "unicode_hell",
    "date_extremes",
    "single_customer",
]


class EdgeCaseForgeAgent(PlaygroundAgent):
    """Generates extreme/adversarial datasets — one DB per edge case."""

    def __init__(self) -> None:
        self.name = "edge_case_forge"
        self.tier = "generator"
        super().__init__()

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        datasets: List[DatasetRecord] = []
        errors: List[str] = []

        for case_name in EDGE_CASES:
            try:
                ds = self._generate_case(ctx, case_name)
                datasets.append(ds)
                await ctx.generated_datasets.put(ds)
            except Exception as exc:
                msg = f"Edge case '{case_name}' failed: {exc}"
                self.logger.error(msg)
                errors.append(msg)

        self._datasets_produced += len(datasets)
        return AgentResult(
            agent_name=self.name,
            success=len(datasets) > 0,
            datasets=datasets,
            errors=errors if errors else None,
            stats={
                "cases_attempted": len(EDGE_CASES),
                "cases_succeeded": len(datasets),
            },
        )

    def _generate_case(self, ctx: PlaygroundContext, case_name: str) -> DatasetRecord:
        db_path = ctx.datasets_dir / "edge_cases" / f"edge_{case_name}.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing to start fresh
        if db_path.exists():
            db_path.unlink()

        conn = sqlite3.connect(str(db_path))
        now = datetime.utcnow().isoformat()

        # Create schema
        for ddl in GENERIC_SCHEMA.values():
            conn.execute(ddl)

        handler = getattr(self, f"_case_{case_name}", None)
        if handler is None:
            raise ValueError(f"Unknown edge case: {case_name}")

        row_counts = handler(conn)

        conn.commit()
        conn.close()

        self.logger.info("Edge case '%s': %s", case_name, row_counts)
        return DatasetRecord(
            name=f"edge_{case_name}",
            path=str(db_path),
            source_agent=self.name,
            tier=self.tier,
            created_at=now,
            row_counts=row_counts,
            tags=["edge_case", case_name],
            metadata={"edge_case": case_name},
        )

    # ── Case handlers ────────────────────────────────────────────────

    def _case_empty_tables(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """Schema exists but 0 rows in all tables."""
        return {t: 0 for t in GENERIC_SCHEMA}

    def _case_single_row(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """Exactly 1 row per table."""
        conn.execute(
            "INSERT INTO c_bpartner VALUES (1, 'Solo Customer', 'TX-0001', 'Y', 'Y')"
        )
        conn.execute(
            "INSERT INTO c_invoice VALUES (1, 1, 'INV-0001', '2024-06-15', 1234.56, 'CO')"
        )
        conn.execute(
            "INSERT INTO c_payment VALUES (1, 1, 1, '2024-06-20', 1234.56, 'CO')"
        )
        conn.execute(
            "INSERT INTO m_product VALUES (1, 'Only Product', 'PROD-001', 99.99, 'Y')"
        )
        return {t: 1 for t in GENERIC_SCHEMA}

    def _case_all_nulls(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """1000 rows but all non-PK columns are NULL."""
        n = 1000
        for i in range(1, n + 1):
            conn.execute(
                "INSERT INTO c_bpartner (c_bpartner_id) VALUES (?)", (i,)
            )
            conn.execute(
                "INSERT INTO c_invoice (c_invoice_id) VALUES (?)", (i,)
            )
            conn.execute(
                "INSERT INTO c_payment (c_payment_id) VALUES (?)", (i,)
            )
            conn.execute(
                "INSERT INTO m_product (m_product_id) VALUES (?)", (i,)
            )
        return {t: n for t in GENERIC_SCHEMA}

    def _case_mixed_types(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """String values 'N/A', 'null', '#REF!' in numeric columns."""
        # SQLite is type-flexible, so we can insert strings into REAL columns
        bad_values = ["N/A", "null", "#REF!", "NaN", "INF", "-", ""]
        n = 100
        for i in range(1, n + 1):
            conn.execute(
                "INSERT INTO c_bpartner VALUES (?, ?, ?, ?, ?)",
                (i, f"Customer {i}", random.choice(bad_values), "Y", "Y"),
            )
            # Insert string into grandtotal (REAL column) — SQLite allows this
            conn.execute(
                "INSERT INTO c_invoice VALUES (?, ?, ?, ?, ?, ?)",
                (i, i, f"INV-{i}", "2024-01-15", random.choice(bad_values), "CO"),
            )
            conn.execute(
                "INSERT INTO c_payment VALUES (?, ?, ?, ?, ?, ?)",
                (i, i, i, "2024-01-20", random.choice(bad_values), "CO"),
            )
            conn.execute(
                "INSERT INTO m_product VALUES (?, ?, ?, ?, ?)",
                (i, f"Product {i}", f"P-{i}", random.choice(bad_values), "Y"),
            )
        return {t: n for t in GENERIC_SCHEMA}

    def _case_huge_amounts(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """Invoice amounts of 999_999_999_999.99."""
        huge = 999_999_999_999.99
        n = 50
        conn.execute(
            "INSERT INTO c_bpartner VALUES (1, 'Big Spender Inc', 'TX-BIG', 'Y', 'Y')"
        )
        conn.execute(
            "INSERT INTO m_product VALUES (1, 'Expensive Item', 'EXP-001', ?, 'Y')",
            (huge,),
        )
        for i in range(1, n + 1):
            conn.execute(
                "INSERT INTO c_invoice VALUES (?, 1, ?, '2024-06-15', ?, 'CO')",
                (i, f"INV-HUGE-{i}", huge),
            )
            conn.execute(
                "INSERT INTO c_payment VALUES (?, 1, ?, '2024-06-20', ?, 'CO')",
                (i, i, huge),
            )
        return {"c_bpartner": 1, "c_invoice": n, "c_payment": n, "m_product": 1}

    def _case_negative_everything(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """All amounts negative."""
        n = 100
        conn.execute(
            "INSERT INTO c_bpartner VALUES (1, 'Negative Corp', 'TX-NEG', 'Y', 'Y')"
        )
        for i in range(1, n + 1):
            amt = -round(random.uniform(1, 100000), 2)
            conn.execute(
                "INSERT INTO c_invoice VALUES (?, 1, ?, '2024-03-15', ?, 'CO')",
                (i, f"INV-NEG-{i}", amt),
            )
            conn.execute(
                "INSERT INTO c_payment VALUES (?, 1, ?, '2024-03-20', ?, 'CO')",
                (i, i, amt),
            )
        conn.execute(
            "INSERT INTO m_product VALUES (1, 'Negative Product', 'NEG-001', -99.99, 'Y')"
        )
        return {"c_bpartner": 1, "c_invoice": n, "c_payment": n, "m_product": 1}

    def _case_duplicate_pks(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """Intentionally duplicate primary keys. Uses a table without PK constraint."""
        # Drop and recreate without PRIMARY KEY constraint for this edge case
        conn.execute("DROP TABLE c_invoice")
        conn.execute(
            """
            CREATE TABLE c_invoice (
                c_invoice_id INTEGER,
                c_bpartner_id INTEGER,
                documentno TEXT,
                dateinvoiced TEXT,
                grandtotal REAL,
                docstatus TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO c_bpartner VALUES (1, 'DupKey Customer', 'TX-DUP', 'Y', 'Y')"
        )
        conn.execute(
            "INSERT INTO m_product VALUES (1, 'DupKey Product', 'DUP-001', 50.0, 'Y')"
        )

        n = 50
        for i in range(1, n + 1):
            # Insert each ID twice
            for _ in range(2):
                conn.execute(
                    "INSERT INTO c_invoice VALUES (?, 1, ?, '2024-05-15', ?, 'CO')",
                    (i, f"INV-DUP-{i}", round(random.uniform(100, 5000), 2)),
                )
        conn.execute(
            "INSERT INTO c_payment VALUES (1, 1, 1, '2024-05-20', 500.0, 'CO')"
        )
        return {"c_bpartner": 1, "c_invoice": n * 2, "c_payment": 1, "m_product": 1}

    def _case_unicode_hell(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """Customer names with emojis, RTL text, zero-width chars."""
        unicode_names = [
            "\U0001f4b0 Money Corp \U0001f4b0",
            "\u0634\u0631\u0643\u0629 \u0627\u0644\u0639\u0631\u0628\u064a\u0629",  # Arabic company name
            "\u200b\u200bZero\u200bWidth\u200b",  # zero-width spaces
            "Caf\u00e9 & Fr\u00e8res S.A.",
            "\u2068Hidden\u2069 \u202eLTR\u202c Override",
            "NULL\x00BYTE",  # null byte in string
            "\U0001f1fa\U0001f1f8 American Co \U0001f1fa\U0001f1f8",  # flag emojis
            "\u4e2d\u6587\u516c\u53f8",  # Chinese company name
            "Tab\there\nnewline",
            "Robert'); DROP TABLE c_bpartner;--",  # SQL injection attempt
            "\U0001f602\U0001f602\U0001f602 LOL Corp",
            "\u0e1a\u0e23\u0e34\u0e29\u0e31\u0e17\u0e44\u0e17\u0e22",  # Thai
        ]
        n = len(unicode_names)
        for i, name in enumerate(unicode_names, 1):
            # Replace actual null bytes — SQLite can't store them
            safe_name = name.replace("\x00", "\\x00")
            conn.execute(
                "INSERT INTO c_bpartner VALUES (?, ?, ?, 'Y', 'Y')",
                (i, safe_name, f"TX-UNI-{i}"),
            )
            conn.execute(
                "INSERT INTO c_invoice VALUES (?, ?, ?, '2024-07-15', ?, 'CO')",
                (i, i, f"INV-UNI-{i}", round(random.uniform(100, 5000), 2)),
            )
        conn.execute(
            "INSERT INTO m_product VALUES (1, '\U0001f4e6 Magic Box', 'UNI-001', 42.0, 'Y')"
        )
        conn.execute(
            "INSERT INTO c_payment VALUES (1, 1, 1, '2024-07-20', 500.0, 'CO')"
        )
        return {"c_bpartner": n, "c_invoice": n, "c_payment": 1, "m_product": 1}

    def _case_date_extremes(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """Dates from year 1900 and 2099."""
        extreme_dates = [
            "1900-01-01",
            "1900-12-31",
            "1969-12-31",
            "1970-01-01",
            "1999-12-31",
            "2000-01-01",
            "2000-02-29",
            "2038-01-19",  # Unix Y2038
            "2099-01-01",
            "2099-12-31",
            "0001-01-01",
            "9999-12-31",
        ]
        conn.execute(
            "INSERT INTO c_bpartner VALUES (1, 'Time Traveler Inc', 'TX-TIME', 'Y', 'Y')"
        )
        conn.execute(
            "INSERT INTO m_product VALUES (1, 'Timeless Product', 'TIME-001', 100.0, 'Y')"
        )
        n = len(extreme_dates)
        for i, dt in enumerate(extreme_dates, 1):
            conn.execute(
                "INSERT INTO c_invoice VALUES (?, 1, ?, ?, 1000.00, 'CO')",
                (i, f"INV-DATE-{i}", dt),
            )
            conn.execute(
                "INSERT INTO c_payment VALUES (?, 1, ?, ?, 1000.00, 'CO')",
                (i, i, dt),
            )
        return {"c_bpartner": 1, "c_invoice": n, "c_payment": n, "m_product": 1}

    def _case_single_customer(self, conn: sqlite3.Connection) -> Dict[str, int]:
        """All invoices belong to 1 customer."""
        conn.execute(
            "INSERT INTO c_bpartner VALUES (1, 'Monopoly Customer', 'TX-MONO', 'Y', 'Y')"
        )
        conn.execute(
            "INSERT INTO m_product VALUES (1, 'Standard Product', 'STD-001', 75.0, 'Y')"
        )
        n = 500
        for i in range(1, n + 1):
            amt = round(random.uniform(10, 10000), 2)
            conn.execute(
                "INSERT INTO c_invoice VALUES (?, 1, ?, '2024-06-15', ?, 'CO')",
                (i, f"INV-MONO-{i}", amt),
            )
        payment_count = 0
        for i in range(1, n + 1):
            if random.random() < 0.7:
                payment_count += 1
                conn.execute(
                    "INSERT INTO c_payment VALUES (?, 1, ?, '2024-06-20', ?, 'CO')",
                    (payment_count, i, round(random.uniform(10, 10000), 2)),
                )
        return {"c_bpartner": 1, "c_invoice": n, "c_payment": payment_count, "m_product": 1}
