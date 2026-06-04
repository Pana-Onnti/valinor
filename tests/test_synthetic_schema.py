"""
Tests for the synthetic schema generator + discovery scalability sweep (VAL-145).

Generator tests are pure/fast (default suite). The sweep sanity runs structural
discovery at small N and is gated under @discovery_benchmark.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from valinor.discovery.synthetic_schema import (
    build_synthetic_dataset,
    generate_synthetic_schema,
)


# ── generator (pure, default suite) ────────────────────────────────────────

class TestSyntheticSchema:
    @pytest.mark.parametrize("n", [50, 200])
    def test_table_count(self, n):
        tables, relations, meta = generate_synthetic_schema(n)
        assert len(tables) == n
        # every relation goes fact → dim (source is a fact, target is a dim).
        dim_names = {name for name, m in meta.items() if m["is_dim"]}
        for r in relations:
            assert r.target_table in dim_names
            assert r.source_table not in dim_names
        assert len(relations) >= 1

    def test_reproducible(self):
        a = generate_synthetic_schema(40, seed=5)[0]
        b = generate_synthetic_schema(40, seed=5)[0]
        assert [t.name for t in a] == [t.name for t in b]

    def test_no_fks_build_has_zero_constraints(self):
        _, conn = build_synthetic_dataset(20, with_fks=False)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            assert len(tables) == 20
            for t in tables:
                cur.execute(f"PRAGMA foreign_key_list([{t}])")
                assert cur.fetchall() == []
        finally:
            conn.close()

    def test_with_fks_build_has_constraints(self):
        dataset, conn = build_synthetic_dataset(20, with_fks=True)
        try:
            cur = conn.cursor()
            total = 0
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for (t,) in cur.fetchall():
                cur.execute(f"PRAGMA foreign_key_list([{t}])")
                total += len(cur.fetchall())
            assert total == len(dataset.relations)  # one declared FK per ground-truth
        finally:
            conn.close()

    def test_too_small_rejected(self):
        with pytest.raises(ValueError):
            generate_synthetic_schema(3)


# ── scalability sweep (runs discovery, gated) ──────────────────────────────

@pytest.mark.discovery_benchmark
class TestScalabilitySweep:
    @staticmethod
    def _sweep(sizes):
        spec = importlib.util.spec_from_file_location(
            "discovery_scalability_eval",
            Path(__file__).resolve().parent.parent / "scripts"
            / "discovery_scalability_eval.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.run_scalability_sweep(sizes)

    def test_sweep_shape_and_accuracy(self):
        rows = self._sweep([8, 16])
        assert [r["n_tables"] for r in rows] == [8, 16]
        for r in rows:
            assert set(r) >= {"golden_fks", "predicted", "fk_recall",
                              "fk_precision", "latency_seconds"}
            # disjoint PK ranges → the true FKs are found at high recall/precision.
            assert r["fk_recall"] >= 0.9
            assert r["fk_precision"] >= 0.9
            assert r["latency_seconds"] >= 0.0
