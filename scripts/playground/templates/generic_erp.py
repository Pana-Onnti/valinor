"""
Playground Swarm — Generic ERP schema template.

A simplified, ERP-agnostic schema for invoices, customers, payments,
products, and orders.  Useful for quick synthetic-data generation when
a full Etendo or Odoo model is not required.
"""

from __future__ import annotations

import sqlite3
from typing import List

_TABLES: List[str] = [
    # ── Customers ─────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS customers (
        id          INTEGER PRIMARY KEY,
        name        TEXT    NOT NULL,
        email       TEXT,
        country     TEXT,
        segment     TEXT,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
    )
    """,

    # ── Products ──────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS products (
        id          INTEGER PRIMARY KEY,
        name        TEXT    NOT NULL,
        category    TEXT,
        unit_price  REAL    NOT NULL DEFAULT 0,
        cost_price  REAL    NOT NULL DEFAULT 0,
        stock_qty   INTEGER NOT NULL DEFAULT 0
    )
    """,

    # ── Invoices ──────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS invoices (
        id              INTEGER PRIMARY KEY,
        invoice_number  TEXT    NOT NULL,
        customer_id     INTEGER NOT NULL REFERENCES customers(id),
        invoice_date    TEXT    NOT NULL,
        due_date        TEXT,
        total_amount    REAL    NOT NULL DEFAULT 0,
        tax_amount      REAL    NOT NULL DEFAULT 0,
        status          TEXT    NOT NULL DEFAULT 'draft',
        currency        TEXT    NOT NULL DEFAULT 'EUR'
    )
    """,

    # ── Payments ──────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS payments (
        id            INTEGER PRIMARY KEY,
        invoice_id    INTEGER NOT NULL REFERENCES invoices(id),
        payment_date  TEXT    NOT NULL,
        amount        REAL    NOT NULL DEFAULT 0,
        method        TEXT
    )
    """,

    # ── Orders ────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS orders (
        id            INTEGER PRIMARY KEY,
        customer_id   INTEGER NOT NULL REFERENCES customers(id),
        order_date    TEXT    NOT NULL,
        total_amount  REAL    NOT NULL DEFAULT 0,
        status        TEXT    NOT NULL DEFAULT 'draft'
    )
    """,
]

_TABLE_NAMES: List[str] = [
    "customers",
    "products",
    "invoices",
    "payments",
    "orders",
]


def create_generic_schema(conn: sqlite3.Connection) -> None:
    """Create all generic ERP tables in the given SQLite connection.

    Tables are created with ``IF NOT EXISTS`` so the function is idempotent.
    Foreign-key enforcement is enabled automatically.
    """
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in _TABLES:
        conn.execute(ddl)
    conn.commit()


def get_table_names() -> List[str]:
    """Return the ordered list of table names in the generic schema."""
    return list(_TABLE_NAMES)
