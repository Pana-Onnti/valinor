"""
Golden Dataset — second ERP family (Retail POS) for cross-pilot generalization.

A structurally analogous but LEXICALLY DISTINCT ERP from the Argentine gestión
family in golden_dataset.py: English naming with an `Id`-suffix convention and
Header/Lines documents (vs `Cod*`/`Nro*` prefixes and `Cab`/`Det` in the gestión
family). Same entity mix (master / config / transactional / bridge) and the same
8 relations (7 explicit + 1 implicit) so the two families are directly comparable.

Purpose (VAL-145 §7 cross-pilot generalization, enabled by VAL-175 ablation):
  * structural inference is convention-agnostic → should generalize across families.
  * the gestión hint pack (argentina_gestion.yaml) must NOT fire here (specificity).
  * a retail hint pack (retail_pos.yaml) SHOULD fire here (per-family curation).

Refs: VAL-145 (relates VAL-175, VAL-129)
"""

from __future__ import annotations

import random
import sqlite3

from .golden_dataset import (
    GoldenDataset,
    GoldenRelation,
    GoldenTable,
    RelationType,
    TableClassification,
)


# ═══════════════════════════════════════════════════════════════════════════
# TABLE DEFINITIONS — Retail POS schema (English, Id-suffix convention)
# ═══════════════════════════════════════════════════════════════════════════

_RETAIL_TABLES = [
    GoldenTable("Products", TableClassification.MASTER, "products"),
    GoldenTable("Customers", TableClassification.MASTER, "customers"),
    GoldenTable("Suppliers", TableClassification.MASTER, "suppliers"),
    GoldenTable("Employees", TableClassification.MASTER, "employees"),
    GoldenTable("Categories", TableClassification.CONFIG, "categories"),
    GoldenTable("PayMethods", TableClassification.CONFIG, "payment_methods"),
    GoldenTable("SaleHeader", TableClassification.TRANSACTIONAL, "sales_header"),
    GoldenTable("SaleLines", TableClassification.TRANSACTIONAL, "sales_lines"),
    GoldenTable("Inventory", TableClassification.BRIDGE, "inventory"),
    GoldenTable("StockMoves", TableClassification.TRANSACTIONAL, "stock_moves"),
]

# Ground-truth FK relations (mirror the gestión family: 7 explicit + 1 implicit).
_EXPLICIT_RELATIONS = [
    GoldenRelation("SaleHeader", "CustomerId", "Customers", "CustomerId", RelationType.EXPLICIT_FK),
    GoldenRelation("SaleHeader", "EmployeeId", "Employees", "EmployeeId", RelationType.EXPLICIT_FK),
    GoldenRelation("SaleLines", "SaleId", "SaleHeader", "SaleId", RelationType.EXPLICIT_FK),
    GoldenRelation("SaleLines", "ProductId", "Products", "ProductId", RelationType.EXPLICIT_FK),
    GoldenRelation("Inventory", "ProductId", "Products", "ProductId", RelationType.EXPLICIT_FK),
    GoldenRelation("StockMoves", "ProductId", "Products", "ProductId", RelationType.EXPLICIT_FK),
    GoldenRelation("Products", "CategoryId", "Categories", "CategoryId", RelationType.EXPLICIT_FK),
]

# Never declared even in the full variant (the hard implicit case).
_IMPLICIT_RELATIONS = [
    GoldenRelation("SaleHeader", "MethodId", "PayMethods", "MethodId", RelationType.IMPLICIT_FK),
]

_ALL_RELATIONS = _EXPLICIT_RELATIONS + _IMPLICIT_RELATIONS


# ═══════════════════════════════════════════════════════════════════════════
# DDL
# ═══════════════════════════════════════════════════════════════════════════

def _ddl_tables(with_fks: bool) -> list[str]:
    stmts = []

    stmts.append("""
        CREATE TABLE Categories (
            CategoryId INTEGER PRIMARY KEY,
            Name TEXT NOT NULL
        )
    """)

    stmts.append("""
        CREATE TABLE PayMethods (
            MethodId INTEGER PRIMARY KEY,
            Name TEXT NOT NULL,
            TermDays INTEGER NOT NULL DEFAULT 0
        )
    """)

    fk = ", FOREIGN KEY (CategoryId) REFERENCES Categories(CategoryId)" if with_fks else ""
    stmts.append(f"""
        CREATE TABLE Products (
            ProductId INTEGER PRIMARY KEY,
            Name TEXT NOT NULL,
            CategoryId INTEGER,
            RetailPrice REAL NOT NULL DEFAULT 0,
            UnitCost REAL NOT NULL DEFAULT 0
            {fk}
        )
    """)

    stmts.append("""
        CREATE TABLE Customers (
            CustomerId INTEGER PRIMARY KEY,
            FullName TEXT NOT NULL,
            TaxNo TEXT,
            Segment TEXT DEFAULT 'retail',
            Address TEXT
        )
    """)

    stmts.append("""
        CREATE TABLE Suppliers (
            SupplierId INTEGER PRIMARY KEY,
            Name TEXT NOT NULL,
            TaxNo TEXT
        )
    """)

    stmts.append("""
        CREATE TABLE Employees (
            EmployeeId INTEGER PRIMARY KEY,
            FullName TEXT NOT NULL
        )
    """)

    fk = ""
    if with_fks:
        fk = (
            ", FOREIGN KEY (CustomerId) REFERENCES Customers(CustomerId)"
            ", FOREIGN KEY (EmployeeId) REFERENCES Employees(EmployeeId)"
        )
    # NOTE: MethodId FK is NEVER declared (implicit), even in the full variant.
    stmts.append(f"""
        CREATE TABLE SaleHeader (
            SaleId INTEGER PRIMARY KEY,
            DocType TEXT NOT NULL DEFAULT 'TICKET',
            SaleDate TEXT NOT NULL,
            CustomerId INTEGER NOT NULL,
            EmployeeId INTEGER,
            MethodId INTEGER,
            GrandTotal REAL NOT NULL DEFAULT 0
            {fk}
        )
    """)

    fk = ""
    if with_fks:
        fk = (
            ", FOREIGN KEY (SaleId) REFERENCES SaleHeader(SaleId)"
            ", FOREIGN KEY (ProductId) REFERENCES Products(ProductId)"
        )
    stmts.append(f"""
        CREATE TABLE SaleLines (
            SaleId INTEGER NOT NULL,
            LineNo INTEGER NOT NULL,
            ProductId INTEGER NOT NULL,
            Qty REAL NOT NULL DEFAULT 1,
            UnitPrice REAL NOT NULL DEFAULT 0,
            LineTotal REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (SaleId, LineNo)
            {fk}
        )
    """)

    fk = ", FOREIGN KEY (ProductId) REFERENCES Products(ProductId)" if with_fks else ""
    stmts.append(f"""
        CREATE TABLE Inventory (
            ProductId INTEGER PRIMARY KEY,
            OnHand REAL NOT NULL DEFAULT 0,
            ReorderLevel REAL NOT NULL DEFAULT 0,
            LastMoveDate TEXT
            {fk}
        )
    """)

    fk = ", FOREIGN KEY (ProductId) REFERENCES Products(ProductId)" if with_fks else ""
    stmts.append(f"""
        CREATE TABLE StockMoves (
            MoveId INTEGER PRIMARY KEY,
            ProductId INTEGER NOT NULL,
            Qty REAL NOT NULL DEFAULT 0,
            MoveType TEXT NOT NULL DEFAULT 'IN',
            MoveDate TEXT NOT NULL
            {fk}
        )
    """)

    return stmts


# ═══════════════════════════════════════════════════════════════════════════
# SAMPLE DATA
# ═══════════════════════════════════════════════════════════════════════════

def _insert_sample_data(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    rng = random.Random(7)  # reproducible, distinct seed from the gestión family

    cur.executemany("INSERT INTO Categories VALUES (?, ?)",
                    [(i, f"Category {i}") for i in range(1, 7)])
    cur.executemany("INSERT INTO PayMethods VALUES (?, ?, ?)",
                    [(1, "Cash", 0), (2, "Card", 0), (3, "Account 30d", 30)])
    cur.executemany("INSERT INTO Products VALUES (?, ?, ?, ?, ?)",
                    [(i, f"Product {i:03d}", (i % 6) + 1, round(50 + i * 7.5, 2),
                      round(30 + i * 4.1, 2)) for i in range(1, 26)])
    cur.executemany("INSERT INTO Customers VALUES (?, ?, ?, ?, ?)",
                    [(i, f"Customer {i}", f"TAX{90000 + i}", "retail", f"St {i}")
                     for i in range(1, 16)])
    cur.executemany("INSERT INTO Suppliers VALUES (?, ?, ?)",
                    [(i, f"Supplier {i}", f"TAX{70000 + i}") for i in range(1, 6)])
    cur.executemany("INSERT INTO Employees VALUES (?, ?)",
                    [(i, f"Employee {i}") for i in range(1, 7)])

    headers = []
    for i in range(1, 121):
        headers.append((
            i, rng.choice(["TICKET", "TICKET", "INVOICE"]),
            f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}",
            rng.randint(1, 15), rng.randint(1, 6), rng.randint(1, 3),
            round(rng.uniform(20, 5000), 2),
        ))
    cur.executemany("INSERT INTO SaleHeader VALUES (?, ?, ?, ?, ?, ?, ?)", headers)

    lines, counter = [], {}
    for _ in range(300):
        sale = rng.randint(1, 120)
        counter[sale] = counter.get(sale, 0) + 1
        qty = rng.randint(1, 20)
        price = round(rng.uniform(10, 400), 2)
        lines.append((sale, counter[sale], rng.randint(1, 25), qty, price,
                      round(qty * price, 2)))
    cur.executemany("INSERT INTO SaleLines VALUES (?, ?, ?, ?, ?, ?)", lines)

    cur.executemany("INSERT INTO Inventory VALUES (?, ?, ?, ?)",
                    [(i, round(rng.uniform(0, 300), 2), round(rng.uniform(5, 40), 2),
                      f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}")
                     for i in range(1, 26)])
    cur.executemany("INSERT INTO StockMoves VALUES (?, ?, ?, ?, ?)",
                    [(i, rng.randint(1, 25), round(rng.uniform(1, 80), 2),
                      rng.choice(["IN", "IN", "OUT"]),
                      f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}")
                     for i in range(1, 101)])
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

_VARIANTS = ("retail_full", "retail_no_fks")


def load_retail_dataset(variant: str = "retail_full") -> GoldenDataset:
    """Load a retail-family golden dataset variant.

    Variants: "retail_full" (explicit FKs), "retail_no_fks" (no FK constraints).
    """
    if variant not in _VARIANTS:
        raise ValueError(f"Unknown retail variant: {variant}. Use one of {_VARIANTS}")

    include_explicit = variant == "retail_full"
    if include_explicit:
        relations = list(_ALL_RELATIONS)
        desc = "Retail POS ERP (English, Id-suffix) with explicit FK constraints"
    else:
        relations = [
            GoldenRelation(r.source_table, r.source_column, r.target_table,
                           r.target_column, RelationType.IMPLICIT_FK)
            for r in _ALL_RELATIONS
        ]
        desc = "Retail POS ERP without FK constraints (cross-family no-FK case)"

    return GoldenDataset(
        name=variant,
        description=desc,
        tables=list(_RETAIL_TABLES),
        relations=relations,
    )


def build_retail_sqlite(variant: str = "retail_full") -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the retail golden dataset."""
    if variant not in _VARIANTS:
        raise ValueError(f"Unknown retail variant: {variant}. Use one of {_VARIANTS}")

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    for stmt in _ddl_tables(with_fks=variant == "retail_full"):
        conn.execute(stmt)
    _insert_sample_data(conn)
    return conn
