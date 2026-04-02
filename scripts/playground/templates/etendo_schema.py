"""
Playground Swarm — Etendo ERP schema template.

Creates SQLite tables that mirror the core Etendo ERP data model used in
invoicing, payments, partners, products, and orders.
"""

from __future__ import annotations

import sqlite3
from typing import List

_TABLES: List[str] = [
    # ── Business partner ──────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS c_bpartner (
        c_bpartner_id  TEXT    PRIMARY KEY,
        name           TEXT    NOT NULL,
        value          TEXT    NOT NULL,
        taxid          TEXT,
        iscustomer     TEXT    NOT NULL DEFAULT 'N' CHECK (iscustomer IN ('Y', 'N')),
        isvendor       TEXT    NOT NULL DEFAULT 'N' CHECK (isvendor  IN ('Y', 'N')),
        isactive       TEXT    NOT NULL DEFAULT 'Y' CHECK (isactive  IN ('Y', 'N')),
        ad_org_id      TEXT,
        created        TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Invoice ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS c_invoice (
        c_invoice_id   TEXT    PRIMARY KEY,
        documentno     TEXT    NOT NULL,
        c_bpartner_id  TEXT    NOT NULL REFERENCES c_bpartner(c_bpartner_id),
        dateinvoiced   TEXT    NOT NULL,
        grandtotal     REAL    NOT NULL DEFAULT 0,
        totallines     REAL    NOT NULL DEFAULT 0,
        issotrx        TEXT    NOT NULL DEFAULT 'Y' CHECK (issotrx  IN ('Y', 'N')),
        docstatus      TEXT    NOT NULL DEFAULT 'DR' CHECK (docstatus IN ('CO', 'DR', 'VO')),
        isactive       TEXT    NOT NULL DEFAULT 'Y' CHECK (isactive  IN ('Y', 'N')),
        ad_org_id      TEXT,
        c_currency_id  TEXT,
        created        TEXT    NOT NULL DEFAULT (datetime('now')),
        updated        TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Payment schedule ──────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS fin_payment_schedule (
        fin_payment_schedule_id  TEXT  PRIMARY KEY,
        c_invoice_id             TEXT  REFERENCES c_invoice(c_invoice_id),
        c_bpartner_id            TEXT  REFERENCES c_bpartner(c_bpartner_id),
        amount                   REAL  NOT NULL DEFAULT 0,
        outstandingamt           REAL  NOT NULL DEFAULT 0,
        duedate                  TEXT  NOT NULL,
        paidamt                  REAL  NOT NULL DEFAULT 0,
        isactive                 TEXT  NOT NULL DEFAULT 'Y' CHECK (isactive IN ('Y', 'N'))
    )
    """,

    # ── Product ───────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS m_product (
        m_product_id  TEXT    PRIMARY KEY,
        name          TEXT    NOT NULL,
        value         TEXT    NOT NULL,
        producttype   TEXT,
        isactive      TEXT    NOT NULL DEFAULT 'Y' CHECK (isactive IN ('Y', 'N')),
        created       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Sales / Purchase order ────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS c_order (
        c_order_id     TEXT    PRIMARY KEY,
        documentno     TEXT    NOT NULL,
        c_bpartner_id  TEXT    NOT NULL REFERENCES c_bpartner(c_bpartner_id),
        dateordered    TEXT    NOT NULL,
        grandtotal     REAL    NOT NULL DEFAULT 0,
        issotrx        TEXT    NOT NULL DEFAULT 'Y' CHECK (issotrx   IN ('Y', 'N')),
        docstatus      TEXT    NOT NULL DEFAULT 'DR' CHECK (docstatus IN ('CO', 'DR', 'VO')),
        isactive       TEXT    NOT NULL DEFAULT 'Y' CHECK (isactive   IN ('Y', 'N'))
    )
    """,

    # ── User ──────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS ad_user (
        ad_user_id  TEXT    PRIMARY KEY,
        name        TEXT    NOT NULL,
        email       TEXT,
        isactive    TEXT    NOT NULL DEFAULT 'Y' CHECK (isactive IN ('Y', 'N'))
    )
    """,
]

_TABLE_NAMES: List[str] = [
    "c_bpartner",
    "c_invoice",
    "fin_payment_schedule",
    "m_product",
    "c_order",
    "ad_user",
]


def create_etendo_schema(conn: sqlite3.Connection) -> None:
    """Create all Etendo ERP tables in the given SQLite connection.

    Tables are created with ``IF NOT EXISTS`` so the function is idempotent.
    Foreign-key enforcement is enabled automatically.
    """
    conn.execute("PRAGMA foreign_keys = ON")
    for ddl in _TABLES:
        conn.execute(ddl)
    conn.commit()


def get_table_names() -> List[str]:
    """Return the ordered list of table names in the Etendo schema."""
    return list(_TABLE_NAMES)
