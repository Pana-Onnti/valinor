#!/usr/bin/env python3
"""
Seed Demo Database — Deterministic synthetic ERP data for Valinor demo mode.

Generates a reproducible SQLite database with Etendo-schema ERP data:
  - ~50 customers (Pareto-distributed activity)
  - ~5000 invoices with invoice lines
  - ~100 products (log-normal pricing)
  - ~3500 payments (~70% of invoices)
  - ~4000 orders
  - 2 years of data, EUR currency

Uses fixed seed (42) so every run produces identical output.
Output: /tmp/valinor/demo/demo.db

Usage:
    python scripts/seed_demo_db.py [--output PATH] [--force]

Refs: VAL-62
"""

import argparse
import math
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

# ── Fixed seed for reproducibility ────────────────────────────────────────────
SEED = 42
DEFAULT_OUTPUT = Path("/tmp/valinor/demo/demo.db")

# ── Demo parameters ──────────────────────────────────────────────────────────
NUM_CUSTOMERS = 50
NUM_INVOICES = 5000
NUM_PRODUCTS = 100
YEARS_BACK = 2
CURRENCY = "EUR"

# ── Etendo schema DDL ────────────────────────────────────────────────────────

SCHEMA_DDL = {
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
            currency TEXT DEFAULT 'EUR',
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
            currency TEXT DEFAULT 'EUR',
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
            currency TEXT DEFAULT 'EUR',
            docstatus TEXT DEFAULT 'CO',
            issotrx TEXT DEFAULT 'Y',
            FOREIGN KEY (c_bpartner_id) REFERENCES c_bpartner(c_bpartner_id)
        )
    """,
}

# ── Deterministic company / product names (no faker dependency) ───────────────

COMPANY_NAMES = [
    "Meridian Industries", "Nordic Solutions AB", "Cascade Logistics",
    "Vertex Manufacturing", "Solaris Energy GmbH", "Atlas Commerce",
    "Pinnacle Systems", "Horizon Pharma", "Aegis Consulting",
    "Vanguard Materials", "Quantum Electronics", "Stellar Aerospace",
    "Titan Construction", "Olympus Medical", "Zenith Textiles",
    "Aurora Chemicals", "Nexus Distribution", "Sapphire Technologies",
    "Granite Mining Co.", "Coral Maritime",
    "Boreal Timber", "Equinox Retail", "Falcon Freight",
    "Glacier Foods", "Helix Biotech", "Ironclad Security",
    "Jasper Packaging", "Keystone Automotive", "Lumen Optics",
    "Monarch Agriculture", "Nova Telecom", "Oasis Hospitality",
    "Prism Software", "Quartz Instruments", "Ridgeline Engineering",
    "Summit Capital", "Trident Marine", "Unity Healthcare",
    "Volta Renewables", "Westgate Properties",
    "Apex Robotics", "Birch Paper Mills", "Cobalt Metals",
    "Delta Precision", "Eclipse Fashion", "Forge Industrials",
    "Grove Organics", "Harbor Logistics", "Indigo Paints",
    "Jupiter Labs",
]

PRODUCT_NAMES = [
    "Industrial Valve A200", "Precision Bearing XL", "Hydraulic Pump HP-50",
    "Steel Cable 10mm", "Control Panel CP-100", "Circuit Board CB-V3",
    "LED Module 48W", "Thermal Sensor TS-90", "Rubber Gasket Set",
    "Titanium Fastener Kit", "Copper Wire 2.5mm", "Filter Cartridge FC-10",
    "Pneumatic Cylinder PC-75", "Stainless Pipe DN50", "Motor Drive MD-200",
    "Safety Relay SR-24V", "Pressure Gauge PG-100", "Flow Meter FM-40",
    "Heat Exchanger HE-500", "Insulation Panel IP-60",
    "Conveyor Belt 1200mm", "Gearbox GB-300", "Welding Rod 3.2mm",
    "Epoxy Adhesive 5kg", "Carbon Fiber Sheet", "Aluminum Profile AP-40",
    "Polyethylene Tube 25mm", "Silicone Sealant 300ml", "Zinc Coating Spray",
    "Brass Fitting BF-20", "Ceramic Tile CT-30", "Glass Panel GP-800",
    "Transformer TR-1kVA", "Capacitor 100uF", "Resistor Pack 1k",
    "Optical Fiber Cable 12C", "Power Supply PS-500W", "AC Contactor 40A",
    "Thermostat Module TM-10", "Vibration Dampener VD-50",
    "Labeling Machine LM-100", "Packaging Tape 48mm", "Shrink Wrap Roll",
    "Pallet Jack PJ-2500", "Forklift Battery 48V", "Dock Leveler DL-6",
    "Sprinkler Head SH-15", "Emergency Light EL-8W", "Fire Extinguisher 5kg",
    "CCTV Camera 4MP", "Access Card Reader", "Smoke Detector SD-V2",
    "UPS System 3kVA", "Server Rack 42U", "Ethernet Switch 24P",
    "Fiber Patch Panel 24P", "Cable Tray 300mm", "PDU 16A Rack Mount",
    "Air Compressor AC-50", "Dehumidifier DH-20L", "Water Pump WP-100",
    "Generator Set GS-30kW", "Solar Panel 400W", "Inverter 5kW",
    "Battery Bank 200Ah", "Wind Turbine WT-10kW", "Charge Controller CC-60A",
    "Drilling Machine DM-25", "Lathe CNC LC-200", "Milling Machine MM-40",
    "Band Saw BS-300", "Grinding Wheel GW-250", "Plasma Cutter PC-60A",
    "Welding Machine WM-400A", "3D Printer FDM-300", "CNC Router CR-1200",
    "Laser Engraver LE-60W", "Paint Sprayer PS-800", "Sandblaster SB-100",
    "Vacuum Pump VP-40", "Centrifuge CF-500", "Autoclave AC-50L",
    "Spectrophotometer SP-UV", "pH Meter Digital", "Oscilloscope 200MHz",
    "Multimeter True RMS", "Signal Generator SG-1GHz", "Logic Analyzer 16ch",
    "Thermal Camera TC-384", "Hardness Tester HT-200", "Tensile Tester TT-50kN",
    "Caliper Digital 300mm", "Micrometer 25-50mm", "Torque Wrench 200Nm",
    "Hydraulic Press HP-100T", "Chain Hoist 5T", "Winch Electric 3T",
    "Scaffold Set 10m", "Concrete Mixer CM-350", "Rebar Cutter RC-25",
    "Tile Cutter TC-800", "Plaster Pump PP-200",
]

TAX_ID_PREFIXES = [
    "ES", "DE", "FR", "IT", "NL", "BE", "AT", "PT", "IE", "FI",
]


def _generate_tax_id(rng: random.Random, idx: int) -> str:
    prefix = TAX_ID_PREFIXES[idx % len(TAX_ID_PREFIXES)]
    digits = rng.randint(10000000, 99999999)
    return f"{prefix}-{digits}"


def _pareto_weights(rng: random.Random, n: int, alpha: float = 1.16) -> List[float]:
    """Generate Pareto-distributed weights (80/20 rule) using stdlib only."""
    raw = [rng.paretovariate(alpha) for _ in range(n)]
    total = sum(raw)
    return [w / total for w in raw]


def _lognormal_values(rng: random.Random, n: int, mu: float, sigma: float) -> List[float]:
    """Generate log-normal distributed values using stdlib only."""
    return [math.exp(rng.gauss(mu, sigma)) for _ in range(n)]


def seed_demo_db(output_path: Path, force: bool = False) -> Dict[str, int]:
    """
    Generate the demo SQLite database.

    Returns dict of table_name -> row_count.
    """
    if output_path.exists() and not force:
        print(f"Demo DB already exists at {output_path}. Use --force to overwrite.")
        return {}

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing file if forcing
    if output_path.exists():
        output_path.unlink()

    rng = random.Random(SEED)
    now = datetime(2026, 1, 15, 12, 0, 0)  # Fixed reference date
    now_str = now.isoformat()
    date_start = now - timedelta(days=365 * YEARS_BACK)
    date_range_days = (now - date_start).days

    conn = sqlite3.connect(str(output_path))

    # Create schema
    for ddl in SCHEMA_DDL.values():
        conn.execute(ddl)

    # ── Customers ─────────────────────────────────────────────────────────────
    customer_ids: List[int] = []
    for i in range(1, NUM_CUSTOMERS + 1):
        name = COMPANY_NAMES[i - 1] if i <= len(COMPANY_NAMES) else f"Company {i}"
        is_active = "Y" if rng.random() < 0.85 else "N"
        tax_id = _generate_tax_id(rng, i)
        conn.execute(
            "INSERT INTO c_bpartner (c_bpartner_id, name, taxid, is_active, created, updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (i, name, tax_id, is_active, now_str, now_str),
        )
        customer_ids.append(i)

    # ── Products ──────────────────────────────────────────────────────────────
    product_ids: List[int] = []
    product_prices = _lognormal_values(rng, NUM_PRODUCTS, 3.5, 1.0)
    for i in range(1, NUM_PRODUCTS + 1):
        name = PRODUCT_NAMES[i - 1] if i <= len(PRODUCT_NAMES) else f"Product {i}"
        price = round(product_prices[i - 1], 2)
        conn.execute(
            "INSERT INTO m_product (m_product_id, name, value, listprice, standardprice) "
            "VALUES (?, ?, ?, ?, ?)",
            (i, name, f"PROD-{i:05d}", price, round(price * 0.6, 2)),
        )
        product_ids.append(i)

    # ── Pareto customer weights (20/80 rule) ──────────────────────────────────
    weights = _pareto_weights(rng, NUM_CUSTOMERS)

    # ── Invoice amounts: log-normal ───────────────────────────────────────────
    amounts = _lognormal_values(rng, NUM_INVOICES, 6, 1.5)

    # ── Invoices ──────────────────────────────────────────────────────────────
    invoice_data: List[Tuple[int, int, float]] = []
    invoiceline_count = 0

    for i in range(1, NUM_INVOICES + 1):
        # Weighted random choice using cumulative weights
        bp_id = _weighted_choice(rng, customer_ids, weights)
        amount = round(amounts[i - 1], 2)
        inv_date = date_start + timedelta(days=rng.randint(0, date_range_days))

        r = rng.random()
        docstatus = "CO" if r < 0.95 else ("DR" if r < 0.98 else "VO")

        conn.execute(
            "INSERT INTO c_invoice "
            "(c_invoice_id, c_bpartner_id, documentno, dateinvoiced, totallines, grandtotal, currency, docstatus) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (i, bp_id, f"INV-{i:07d}", inv_date.strftime("%Y-%m-%d"), amount, amount, CURRENCY, docstatus),
        )
        invoice_data.append((i, bp_id, amount))

        # Invoice lines (1-5 per invoice)
        num_lines = rng.randint(1, min(5, NUM_PRODUCTS))
        line_products = rng.sample(product_ids, num_lines)
        remaining = amount
        for line_no, prod_id in enumerate(line_products, 1):
            if line_no == num_lines:
                line_amt = round(remaining, 2)
            else:
                line_amt = round(remaining * rng.uniform(0.1, 0.5), 2)
                remaining -= line_amt
            qty = max(1, rng.randint(1, 20))
            price = round(line_amt / qty, 2) if qty > 0 else line_amt
            conn.execute(
                "INSERT INTO c_invoiceline "
                "(c_invoice_id, m_product_id, line, qtyinvoiced, priceactual, linenetamt) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (i, prod_id, line_no * 10, qty, price, line_amt),
            )
            invoiceline_count += 1

    # ── Payments (~70% of invoices) ───────────────────────────────────────────
    payment_count = 0
    for inv_id, bp_id, amount in invoice_data:
        if rng.random() < 0.7:
            pay_date = date_start + timedelta(days=rng.randint(0, date_range_days))
            if rng.random() < 0.1:
                pay_amt = round(amount * rng.uniform(0.3, 0.9), 2)
            else:
                pay_amt = amount
            payment_count += 1
            conn.execute(
                "INSERT INTO c_payment "
                "(c_bpartner_id, c_invoice_id, documentno, datetrx, payamt, currency) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (bp_id, inv_id, f"PAY-{payment_count:07d}", pay_date.strftime("%Y-%m-%d"), pay_amt, CURRENCY),
            )

    # ── Orders (~75% of invoices) ─────────────────────────────────────────────
    num_orders = int(NUM_INVOICES * 0.8)
    order_amounts = _lognormal_values(rng, num_orders, 6, 1.5)
    for i in range(1, num_orders + 1):
        bp_id = _weighted_choice(rng, customer_ids, weights)
        amount = round(order_amounts[i - 1], 2)
        ord_date = date_start + timedelta(days=rng.randint(0, date_range_days))
        r = rng.random()
        docstatus = "CO" if r < 0.95 else ("DR" if r < 0.98 else "VO")
        conn.execute(
            "INSERT INTO c_order "
            "(c_bpartner_id, documentno, dateordered, totallines, grandtotal, currency, docstatus) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bp_id, f"ORD-{i:07d}", ord_date.strftime("%Y-%m-%d"), amount, amount, CURRENCY, docstatus),
        )

    conn.commit()

    # Verify counts
    row_counts: Dict[str, int] = {}
    for table in SCHEMA_DDL:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        row_counts[table] = cursor.fetchone()[0]
    conn.close()

    return row_counts


def _weighted_choice(rng: random.Random, population: List[int], weights: List[float]) -> int:
    """Weighted random choice using cumulative distribution (stdlib only)."""
    r = rng.random()
    cumulative = 0.0
    for item, w in zip(population, weights):
        cumulative += w
        if r <= cumulative:
            return item
    return population[-1]


def main():
    parser = argparse.ArgumentParser(description="Seed Valinor demo database")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output path for the SQLite database (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing database",
    )
    args = parser.parse_args()

    print(f"Seeding demo database at {args.output} ...")
    row_counts = seed_demo_db(args.output, force=args.force)

    if not row_counts:
        sys.exit(0)

    print("Done! Row counts:")
    for table, count in row_counts.items():
        print(f"  {table}: {count:,}")
    total = sum(row_counts.values())
    print(f"  TOTAL: {total:,}")
    print(f"\nConnection string: sqlite:///{args.output}")


if __name__ == "__main__":
    main()
