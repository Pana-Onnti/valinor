"""
Golden Dataset — Ground truth for Discovery Engine benchmarking.

Provides synthetic but realistic schemas simulating Argentine ERP databases
(legacy gestión-PyME systems). Three variants test different discovery challenges:

1. gloria_full: Explicit FK constraints (like Etendo/Gloria)
2. gloria_no_fks: Same schema WITHOUT FK constraints (like a no-FK legacy ERP)
3. gloria_obfuscated: Cryptic table/column names (legacy systems)

Each variant is buildable as a real SQLite database so the discovery
engine can run against it.

Refs: VAL-129
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import sqlite3


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


class TableClassification(str, Enum):
    MASTER = "MASTER"
    TRANSACTIONAL = "TRANSACTIONAL"
    CONFIG = "CONFIG"
    BRIDGE = "BRIDGE"


class RelationType(str, Enum):
    EXPLICIT_FK = "explicit_fk"
    IMPLICIT_FK = "implicit_fk"
    COMPOSITE_KEY = "composite_key"


@dataclass
class GoldenTable:
    name: str
    classification: TableClassification
    business_entity: str  # "productos", "clientes", "ventas", etc.


@dataclass
class GoldenRelation:
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relation_type: RelationType


@dataclass
class GoldenDataset:
    """Ground truth for Discovery Engine benchmarking."""
    name: str
    description: str
    tables: list[GoldenTable] = field(default_factory=list)
    relations: list[GoldenRelation] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# TABLE DEFINITIONS — Argentine PyME ERP schema
# ═══════════════════════════════════════════════════════════════════════════

_FULL_TABLES = [
    GoldenTable("Articulos", TableClassification.MASTER, "productos"),
    GoldenTable("Clientes", TableClassification.MASTER, "clientes"),
    GoldenTable("Proveedores", TableClassification.MASTER, "proveedores"),
    GoldenTable("Vendedores", TableClassification.MASTER, "vendedores"),
    GoldenTable("Rubros", TableClassification.CONFIG, "rubros"),
    GoldenTable("CondPago", TableClassification.CONFIG, "condiciones_pago"),
    GoldenTable("CompCab", TableClassification.TRANSACTIONAL, "comprobantes_cabecera"),
    GoldenTable("CompDet", TableClassification.TRANSACTIONAL, "comprobantes_detalle"),
    GoldenTable("Stock", TableClassification.BRIDGE, "stock"),
    GoldenTable("MovStock", TableClassification.TRANSACTIONAL, "movimientos_stock"),
]

_OBFUSCATED_MAP = {
    "Articulos": "Art",
    "Clientes": "Cli",
    "Proveedores": "Prov",
    "Vendedores": "Vend",
    "Rubros": "Rub",
    "CondPago": "CP",
    "CompCab": "CC",
    "CompDet": "CD",
    "Stock": "Stk",
    "MovStock": "MS",
}

# Ground truth FK relations
_EXPLICIT_RELATIONS = [
    GoldenRelation("CompCab", "CodCli", "Clientes", "CodCli", RelationType.EXPLICIT_FK),
    GoldenRelation("CompCab", "CodVend", "Vendedores", "CodVend", RelationType.EXPLICIT_FK),
    GoldenRelation("CompDet", "NroComp", "CompCab", "NroComp", RelationType.EXPLICIT_FK),
    GoldenRelation("CompDet", "CodArt", "Articulos", "CodArt", RelationType.EXPLICIT_FK),
    GoldenRelation("Stock", "CodArt", "Articulos", "CodArt", RelationType.EXPLICIT_FK),
    GoldenRelation("MovStock", "CodArt", "Articulos", "CodArt", RelationType.EXPLICIT_FK),
    GoldenRelation("Articulos", "CodRub", "Rubros", "CodRub", RelationType.EXPLICIT_FK),
]

# This one is always implicit — no FK even in the full variant
_IMPLICIT_RELATIONS = [
    GoldenRelation("CompCab", "CodCondPago", "CondPago", "CodCondPago", RelationType.IMPLICIT_FK),
]

_ALL_RELATIONS = _EXPLICIT_RELATIONS + _IMPLICIT_RELATIONS


# ═══════════════════════════════════════════════════════════════════════════
# DDL — SQLite CREATE TABLE statements
# ═══════════════════════════════════════════════════════════════════════════

def _ddl_tables(with_fks: bool, obfuscate: bool) -> list[str]:
    """Generate CREATE TABLE DDL statements."""

    def _t(name: str) -> str:
        return _OBFUSCATED_MAP.get(name, name) if obfuscate else name

    fk = ""  # placeholder for FK clauses

    stmts = []

    # Rubros (CONFIG)
    stmts.append(f"""
        CREATE TABLE {_t('Rubros')} (
            CodRub INTEGER PRIMARY KEY,
            Descripcion TEXT NOT NULL
        )
    """)

    # CondPago (CONFIG)
    stmts.append(f"""
        CREATE TABLE {_t('CondPago')} (
            CodCondPago INTEGER PRIMARY KEY,
            Descripcion TEXT NOT NULL,
            Dias INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Articulos (MASTER)
    fk_rub = f", FOREIGN KEY (CodRub) REFERENCES {_t('Rubros')}(CodRub)" if with_fks else ""
    stmts.append(f"""
        CREATE TABLE {_t('Articulos')} (
            CodArt INTEGER PRIMARY KEY,
            Descripcion TEXT NOT NULL,
            CodRub INTEGER,
            PrecioVenta REAL NOT NULL DEFAULT 0,
            PrecioCosto REAL NOT NULL DEFAULT 0
            {fk_rub}
        )
    """)

    # Clientes (MASTER)
    stmts.append(f"""
        CREATE TABLE {_t('Clientes')} (
            CodCli INTEGER PRIMARY KEY,
            RazonSocial TEXT NOT NULL,
            CUIT TEXT,
            CondIVA TEXT DEFAULT 'RI',
            Direccion TEXT
        )
    """)

    # Proveedores (MASTER)
    stmts.append(f"""
        CREATE TABLE {_t('Proveedores')} (
            CodProv INTEGER PRIMARY KEY,
            RazonSocial TEXT NOT NULL,
            CUIT TEXT
        )
    """)

    # Vendedores (MASTER)
    stmts.append(f"""
        CREATE TABLE {_t('Vendedores')} (
            CodVend INTEGER PRIMARY KEY,
            Nombre TEXT NOT NULL
        )
    """)

    # CompCab (TRANSACTIONAL)
    fk_cc = ""
    if with_fks:
        fk_cc = (
            f", FOREIGN KEY (CodCli) REFERENCES {_t('Clientes')}(CodCli)"
            f", FOREIGN KEY (CodVend) REFERENCES {_t('Vendedores')}(CodVend)"
        )
    # NOTE: CodCondPago FK is NEVER declared, even in full variant (implicit)
    stmts.append(f"""
        CREATE TABLE {_t('CompCab')} (
            NroComp INTEGER PRIMARY KEY,
            TipoComp TEXT NOT NULL DEFAULT 'FA',
            FechaComp TEXT NOT NULL,
            CodCli INTEGER NOT NULL,
            CodVend INTEGER,
            CodCondPago INTEGER,
            Total REAL NOT NULL DEFAULT 0
            {fk_cc}
        )
    """)

    # CompDet (TRANSACTIONAL)
    fk_cd = ""
    if with_fks:
        fk_cd = (
            f", FOREIGN KEY (NroComp) REFERENCES {_t('CompCab')}(NroComp)"
            f", FOREIGN KEY (CodArt) REFERENCES {_t('Articulos')}(CodArt)"
        )
    stmts.append(f"""
        CREATE TABLE {_t('CompDet')} (
            NroComp INTEGER NOT NULL,
            NroItem INTEGER NOT NULL,
            CodArt INTEGER NOT NULL,
            Cantidad REAL NOT NULL DEFAULT 1,
            PrecioUnit REAL NOT NULL DEFAULT 0,
            Subtotal REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (NroComp, NroItem)
            {fk_cd}
        )
    """)

    # Stock (BRIDGE)
    fk_stk = f", FOREIGN KEY (CodArt) REFERENCES {_t('Articulos')}(CodArt)" if with_fks else ""
    stmts.append(f"""
        CREATE TABLE {_t('Stock')} (
            CodArt INTEGER PRIMARY KEY,
            StockActual REAL NOT NULL DEFAULT 0,
            StockMinimo REAL NOT NULL DEFAULT 0,
            UltMov TEXT
            {fk_stk}
        )
    """)

    # MovStock (TRANSACTIONAL)
    fk_ms = f", FOREIGN KEY (CodArt) REFERENCES {_t('Articulos')}(CodArt)" if with_fks else ""
    stmts.append(f"""
        CREATE TABLE {_t('MovStock')} (
            NroMov INTEGER PRIMARY KEY,
            CodArt INTEGER NOT NULL,
            Cantidad REAL NOT NULL DEFAULT 0,
            TipoMov TEXT NOT NULL DEFAULT 'E',
            FechaMov TEXT NOT NULL
            {fk_ms}
        )
    """)

    return stmts


# ═══════════════════════════════════════════════════════════════════════════
# SAMPLE DATA — realistic Argentine ERP records
# ═══════════════════════════════════════════════════════════════════════════

def _insert_sample_data(conn: sqlite3.Connection, obfuscate: bool) -> None:
    """Insert realistic sample data into the golden dataset."""

    def _t(name: str) -> str:
        return _OBFUSCATED_MAP.get(name, name) if obfuscate else name

    cur = conn.cursor()

    # Rubros (5 categories)
    rubros = [(1, "Alimentos"), (2, "Bebidas"), (3, "Limpieza"), (4, "Perfumeria"), (5, "Varios")]
    cur.executemany(f"INSERT INTO {_t('Rubros')} VALUES (?, ?)", rubros)

    # CondPago (3 options)
    condpago = [(1, "Contado", 0), (2, "30 dias", 30), (3, "60 dias", 60)]
    cur.executemany(f"INSERT INTO {_t('CondPago')} VALUES (?, ?, ?)", condpago)

    # Articulos (20 products)
    articulos = [
        (i, f"Articulo {i:03d}", (i % 5) + 1, round(100 + i * 15.5, 2), round(60 + i * 9.3, 2))
        for i in range(1, 21)
    ]
    cur.executemany(f"INSERT INTO {_t('Articulos')} VALUES (?, ?, ?, ?, ?)", articulos)

    # Clientes (10 customers)
    clientes = [
        (i, f"Cliente SA {i}", f"30-{70000000 + i}-{i % 10}", "RI", f"Calle {i} 1234")
        for i in range(1, 11)
    ]
    cur.executemany(f"INSERT INTO {_t('Clientes')} VALUES (?, ?, ?, ?, ?)", clientes)

    # Proveedores (5 suppliers)
    proveedores = [
        (i, f"Proveedor SRL {i}", f"30-{80000000 + i}-{i % 10}")
        for i in range(1, 6)
    ]
    cur.executemany(f"INSERT INTO {_t('Proveedores')} VALUES (?, ?, ?)", proveedores)

    # Vendedores (4 salespeople)
    vendedores = [(1, "Juan Perez"), (2, "Maria Garcia"), (3, "Carlos Lopez"), (4, "Ana Martinez")]
    cur.executemany(f"INSERT INTO {_t('Vendedores')} VALUES (?, ?)", vendedores)

    # CompCab (200 invoices)
    import random
    random.seed(42)  # Reproducible
    compcab = []
    for i in range(1, 201):
        tipo = random.choice(["FA", "FA", "FA", "NC", "ND"])
        mes = (i % 12) + 1
        dia = (i % 28) + 1
        fecha = f"2025-{mes:02d}-{dia:02d}"
        cli = random.randint(1, 10)
        vend = random.randint(1, 4)
        condpago_id = random.randint(1, 3)
        total = round(random.uniform(500, 50000), 2)
        compcab.append((i, tipo, fecha, cli, vend, condpago_id, total))
    cur.executemany(
        f"INSERT INTO {_t('CompCab')} VALUES (?, ?, ?, ?, ?, ?, ?)", compcab
    )

    # CompDet (500 detail lines)
    compdet = []
    item_counter: dict[int, int] = {}
    for _ in range(500):
        nro_comp = random.randint(1, 200)
        item_counter[nro_comp] = item_counter.get(nro_comp, 0) + 1
        nro_item = item_counter[nro_comp]
        cod_art = random.randint(1, 20)
        cantidad = random.randint(1, 50)
        precio_unit = round(random.uniform(10, 500), 2)
        subtotal = round(cantidad * precio_unit, 2)
        compdet.append((nro_comp, nro_item, cod_art, cantidad, precio_unit, subtotal))
    cur.executemany(
        f"INSERT INTO {_t('CompDet')} VALUES (?, ?, ?, ?, ?, ?)", compdet
    )

    # Stock (20 entries — one per article)
    stock = [
        (i, round(random.uniform(0, 500), 2), round(random.uniform(10, 50), 2),
         f"2025-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}")
        for i in range(1, 21)
    ]
    cur.executemany(f"INSERT INTO {_t('Stock')} VALUES (?, ?, ?, ?)", stock)

    # MovStock (150 movements)
    movstock = []
    for i in range(1, 151):
        cod_art = random.randint(1, 20)
        cantidad = round(random.uniform(1, 100), 2)
        tipo = random.choice(["E", "E", "S", "S", "A"])
        mes = (i % 12) + 1
        dia = (i % 28) + 1
        fecha = f"2025-{mes:02d}-{dia:02d}"
        movstock.append((i, cod_art, cantidad, tipo, fecha))
    cur.executemany(
        f"INSERT INTO {_t('MovStock')} VALUES (?, ?, ?, ?, ?)", movstock
    )

    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════


def get_golden_tables(obfuscate: bool = False) -> list[GoldenTable]:
    """Get table definitions, optionally with obfuscated names."""
    if not obfuscate:
        return list(_FULL_TABLES)
    return [
        GoldenTable(
            name=_OBFUSCATED_MAP.get(t.name, t.name),
            classification=t.classification,
            business_entity=t.business_entity,
        )
        for t in _FULL_TABLES
    ]


def get_golden_relations(
    obfuscate: bool = False,
    include_explicit: bool = True,
) -> list[GoldenRelation]:
    """Get ground truth relations.

    Args:
        obfuscate: Use short/cryptic table names.
        include_explicit: If True, include explicit FK relations.
            If False, only return implicit ones (for no_fks variant).
    """
    if include_explicit:
        rels = list(_ALL_RELATIONS)
    else:
        # In no_fks variant, ALL relations become implicit
        rels = [
            GoldenRelation(
                r.source_table, r.source_column,
                r.target_table, r.target_column,
                RelationType.IMPLICIT_FK,
            )
            for r in _ALL_RELATIONS
        ]

    if obfuscate:
        rels = [
            GoldenRelation(
                _OBFUSCATED_MAP.get(r.source_table, r.source_table),
                r.source_column,
                _OBFUSCATED_MAP.get(r.target_table, r.target_table),
                r.target_column,
                r.relation_type,
            )
            for r in rels
        ]

    return rels


def load_golden_dataset(variant: str = "gloria_full") -> GoldenDataset:
    """Load a golden dataset variant.

    Args:
        variant: One of "gloria_full", "gloria_no_fks", "gloria_obfuscated".

    Returns:
        GoldenDataset with tables and ground-truth relations.
    """
    if variant.startswith("retail"):  # second ERP family (VAL-145), lazy import
        from .golden_dataset_retail import load_retail_dataset
        return load_retail_dataset(variant)
    if variant == "gloria_full":
        return GoldenDataset(
            name="gloria_full",
            description="Argentine PyME ERP with explicit FK constraints",
            tables=get_golden_tables(obfuscate=False),
            relations=get_golden_relations(obfuscate=False, include_explicit=True),
        )
    elif variant == "gloria_no_fks":
        return GoldenDataset(
            name="gloria_no_fks",
            description="Same schema WITHOUT FK constraints (simulates a no-FK legacy ERP)",
            tables=get_golden_tables(obfuscate=False),
            relations=get_golden_relations(obfuscate=False, include_explicit=False),
        )
    elif variant == "gloria_obfuscated":
        return GoldenDataset(
            name="gloria_obfuscated",
            description="Short/cryptic table names simulating legacy systems",
            tables=get_golden_tables(obfuscate=True),
            relations=get_golden_relations(obfuscate=True, include_explicit=False),
        )
    else:
        raise ValueError(f"Unknown variant: {variant}. Use gloria_full, gloria_no_fks, or gloria_obfuscated")


def build_golden_sqlite(variant: str = "gloria_full") -> sqlite3.Connection:
    """Create an in-memory SQLite database with the golden dataset.

    Args:
        variant: One of "gloria_full", "gloria_no_fks", "gloria_obfuscated".

    Returns:
        sqlite3.Connection with tables pre-created and sample data inserted.
    """
    if variant.startswith("retail"):  # second ERP family (VAL-145), lazy import
        from .golden_dataset_retail import build_retail_sqlite
        return build_retail_sqlite(variant)

    with_fks = variant == "gloria_full"
    obfuscate = variant == "gloria_obfuscated"

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")

    ddl_stmts = _ddl_tables(with_fks=with_fks, obfuscate=obfuscate)
    for stmt in ddl_stmts:
        conn.execute(stmt)

    _insert_sample_data(conn, obfuscate=obfuscate)

    return conn
