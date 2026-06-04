"""
Synthetic schema generator for the Discovery Engine scalability sweep (VAL-145 §7).

Generates star-ish schemas of an arbitrary table count N (dimension + fact tables
with ground-truth FKs) so discovery latency and FK precision/recall can be profiled
as a function of N (50 / 200 / 500 …).

Design choices that keep the sweep HONEST:
  * Dimension tables get DISJOINT PK value ranges, so an inclusion dependency holds
    only for the true target — FK precision is decoupled from incidental name
    similarity (no spurious matches from synthetic regularity).
  * Distinct random table tokens → realistic, low cross-name similarity.
  * Small, constant row counts → the latency curve isolates table-count scaling
    (the O(N²) structural matching), not data volume.

Refs: VAL-145 (relates VAL-129, VAL-175)
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

_DIM_ROWS = 10        # distinct PK values per dimension
_FACT_ROWS = 20       # rows per fact table
_PK_STRIDE = 1000     # disjoint PK base spacing — EVERY table gets its own range


def _unique_tokens(n: int, rng: random.Random) -> list[str]:
    """n distinct lowercase 5-letter tokens (low mutual name similarity)."""
    seen: set[str] = set()
    out: list[str] = []
    while len(out) < n:
        tok = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(5))
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def generate_synthetic_schema(n_tables: int, seed: int = 13):
    """Return (tables, relations, meta) for an N-table star-ish schema.

    ~33% dimension (master) tables, the rest fact (transactional) tables; each fact
    references 1-3 dimensions via a name-matched FK column. EVERY table gets a
    DISJOINT PK value range (base = global index × stride) so an inclusion
    dependency can only hold for the true target — no spurious matches between any
    two PK columns. meta[table] = {pk, pk_base, is_dim, ent}.
    """
    if n_tables < 4:
        raise ValueError("n_tables must be >= 4")
    rng = random.Random(seed)

    n_dims = max(2, n_tables // 3)
    tokens = _unique_tokens(n_tables, rng)

    tables: list[GoldenTable] = []
    meta: dict[str, dict] = {}
    for idx, tok in enumerate(tokens):
        is_dim = idx < n_dims
        name = f"{tok}_{'dim' if is_dim else 'fact'}"
        cls = TableClassification.MASTER if is_dim else TableClassification.TRANSACTIONAL
        tables.append(GoldenTable(name, cls, tok))
        meta[name] = {"pk": f"{tok}_id", "pk_base": idx * _PK_STRIDE,
                      "is_dim": is_dim, "ent": tok}

    dim_names = [n for n, m in meta.items() if m["is_dim"]]
    relations: list[GoldenRelation] = []
    for name, m in meta.items():
        if m["is_dim"]:
            continue
        for ref in rng.sample(dim_names, rng.randint(1, min(3, n_dims))):
            rm = meta[ref]
            relations.append(GoldenRelation(
                name, rm["pk"], ref, rm["pk"], RelationType.IMPLICIT_FK,
            ))

    return tables, relations, meta


def build_synthetic_dataset(n_tables: int, with_fks: bool = False, seed: int = 13):
    """Build (GoldenDataset, sqlite connection) for an N-table synthetic schema."""
    tables, relations, meta = generate_synthetic_schema(n_tables, seed)
    rng = random.Random(seed + 1)

    fact_fks: dict[str, list[tuple[str, str]]] = {}  # fact -> [(fk_col, ref_table)]
    for r in relations:
        fact_fks.setdefault(r.source_table, []).append((r.source_column, r.target_table))

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()

    # DDL
    for t in tables:
        m = meta[t.name]
        ent = m["ent"]
        if m["is_dim"]:
            cur.execute(
                f"CREATE TABLE {t.name} ({m['pk']} INTEGER PRIMARY KEY, "
                f"{ent}_name TEXT, {ent}_code TEXT)"
            )
        else:
            fkcols = fact_fks.get(t.name, [])
            cols = [f"{m['pk']} INTEGER PRIMARY KEY"]
            cols += [f"{c} INTEGER" for c, _ in fkcols]
            cols += [f"{ent}_amount REAL", f"{ent}_qty REAL"]
            fk_clause = ""
            if with_fks:
                fk_clause = "".join(
                    f", FOREIGN KEY ({c}) REFERENCES {ref}({meta[ref]['pk']})"
                    for c, ref in fkcols
                )
            cur.execute(f"CREATE TABLE {t.name} ({', '.join(cols)}{fk_clause})")

    # Data — dims first (disjoint PK ranges), then facts referencing them.
    for name, m in meta.items():
        if not m["is_dim"]:
            continue
        base, ent = m["pk_base"], m["ent"]
        # name/code are token-prefixed so they're distinct ACROSS dims too — a real
        # dim's natural key never collides with another dim's (no cross-inclusion FP).
        cur.executemany(
            f"INSERT INTO {name} VALUES (?, ?, ?)",
            [(base + k, f"{ent}-{k}", f"{ent}{k:03d}") for k in range(1, _DIM_ROWS + 1)],
        )

    for name, m in meta.items():
        if m["is_dim"]:
            continue
        base = m["pk_base"]
        fkcols = fact_fks.get(name, [])
        rows = []
        for j in range(1, _FACT_ROWS + 1):
            vals = [base + j]  # fact PK — its own disjoint range
            for _c, ref in fkcols:
                vals.append(meta[ref]["pk_base"] + rng.randint(1, _DIM_ROWS))
            vals += [round(rng.uniform(1, 1000), 2), round(rng.uniform(1, 50), 2)]
            rows.append(tuple(vals))
        placeholders = ", ".join("?" for _ in rows[0])
        cur.executemany(f"INSERT INTO {name} VALUES ({placeholders})", rows)

    conn.commit()

    dataset = GoldenDataset(
        name=f"synthetic_{n_tables}",
        description=f"Synthetic {n_tables}-table star schema (scalability sweep)",
        tables=tables,
        relations=relations,
    )
    return dataset, conn
