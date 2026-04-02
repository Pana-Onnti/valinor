"""
Playground Swarm — Odoo ERP schema template.

Creates SQLite tables that mirror the core Odoo data model for accounting,
partners, products, and sales.
"""

from __future__ import annotations

import sqlite3
from typing import List

_TABLES: List[str] = [
    # ── Partner ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS res_partner (
        id              INTEGER PRIMARY KEY,
        name            TEXT    NOT NULL,
        vat             TEXT,
        email           TEXT,
        phone           TEXT,
        is_company      INTEGER NOT NULL DEFAULT 0 CHECK (is_company IN (0, 1)),
        customer_rank   INTEGER NOT NULL DEFAULT 0,
        supplier_rank   INTEGER NOT NULL DEFAULT 0,
        active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
    )
    """,

    # ── Account ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS account_account (
        id            INTEGER PRIMARY KEY,
        code          TEXT    NOT NULL,
        name          TEXT    NOT NULL,
        account_type  TEXT
    )
    """,

    # ── Account move (invoice / journal entry) ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS account_move (
        id              INTEGER PRIMARY KEY,
        name            TEXT    NOT NULL,
        move_type       TEXT    NOT NULL DEFAULT 'entry'
                        CHECK (move_type IN ('out_invoice', 'in_invoice', 'entry')),
        state           TEXT    NOT NULL DEFAULT 'draft'
                        CHECK (state IN ('posted', 'draft', 'cancel')),
        partner_id      INTEGER REFERENCES res_partner(id),
        invoice_date    TEXT,
        amount_total    REAL    NOT NULL DEFAULT 0,
        amount_untaxed  REAL    NOT NULL DEFAULT 0,
        amount_tax      REAL    NOT NULL DEFAULT 0,
        currency_id     INTEGER,
        company_id      INTEGER
    )
    """,

    # ── Account move line ─────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS account_move_line (
        id          INTEGER PRIMARY KEY,
        move_id     INTEGER NOT NULL REFERENCES account_move(id),
        account_id  INTEGER REFERENCES account_account(id),
        partner_id  INTEGER REFERENCES res_partner(id),
        name        TEXT,
        debit       REAL    NOT NULL DEFAULT 0,
        credit      REAL    NOT NULL DEFAULT 0,
        balance     REAL    NOT NULL DEFAULT 0,
        date        TEXT
    )
    """,

    # ── Product ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS product_product (
        id              INTEGER PRIMARY KEY,
        name            TEXT    NOT NULL,
        default_code    TEXT,
        list_price      REAL    NOT NULL DEFAULT 0,
        standard_price  REAL    NOT NULL DEFAULT 0,
        active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
    )
    """,

    # ── Sale order ────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS sale_order (
        id            INTEGER PRIMARY KEY,
        name          TEXT    NOT NULL,
        partner_id    INTEGER REFERENCES res_partner(id),
        date_order    TEXT,
        amount_total  REAL    NOT NULL DEFAULT 0,
        state         TEXT    NOT NULL DEFAULT 'draft'
                      CHECK (state IN ('sale', 'draft', 'cancel'))
    )
    """,
]

_TABLE_NAMES: List[str] = [
    "res_partner",
    "account_account",
    "account_move",
    "account_move_line",
    "product_product",
    "sale_order",
]


def create_odoo_schema(conn: sqlite3.Connection) -> None:
    """Create all Odoo ERP tables in the given SQLite connection.

    Tables are created with ``IF NOT EXISTS`` so the function is idempotent.
    Foreign-key enforcement is enabled automatically.
    """
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in _TABLES:
        conn.execute(ddl)
    conn.commit()


def get_table_names() -> List[str]:
    """Return the ordered list of table names in the Odoo schema."""
    return list(_TABLE_NAMES)
