"""
Tests for the second ERP family (Retail POS) golden dataset + cross-family
generalization (VAL-145).

Build tests are pure/fast (default suite). The cross-family ablation test runs the
deterministic ensemble across both families and is gated under @discovery_benchmark.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from valinor.discovery.erp_hints import load_hint_pack
from valinor.discovery.golden_dataset import build_golden_sqlite, load_golden_dataset
from valinor.discovery.golden_dataset_retail import (
    build_retail_sqlite,
    load_retail_dataset,
)

RETAIL_VARIANTS = ["retail_full", "retail_no_fks"]


# ── dataset build (pure, default suite) ────────────────────────────────────

class TestRetailGoldenDataset:
    @pytest.mark.parametrize("variant", RETAIL_VARIANTS)
    def test_load_variant(self, variant):
        g = load_retail_dataset(variant)
        assert g.name == variant
        assert len(g.tables) == 10
        assert len(g.relations) == 8  # 7 explicit + 1 implicit, mirrors gestión

    @pytest.mark.parametrize("variant", RETAIL_VARIANTS)
    def test_build_sqlite_has_10_tables(self, variant):
        conn = build_retail_sqlite(variant)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            assert len({r[0] for r in cur.fetchall()}) == 10
        finally:
            conn.close()

    def test_no_fks_variant_has_zero_constraints(self):
        conn = build_retail_sqlite("retail_no_fks")
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for (t,) in cur.fetchall():
                cur.execute(f"PRAGMA foreign_key_list([{t}])")
                assert cur.fetchall() == [], f"{t} must have no FK constraints"
        finally:
            conn.close()

    def test_full_variant_has_constraints(self):
        conn = build_retail_sqlite("retail_full")
        try:
            cur = conn.cursor()
            total = 0
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for (t,) in cur.fetchall():
                cur.execute(f"PRAGMA foreign_key_list([{t}])")
                total += len(cur.fetchall())
            assert total >= 6  # the explicit FKs are declared
        finally:
            conn.close()

    def test_unified_dispatch_via_golden_dataset(self):
        # load_golden_dataset / build_golden_sqlite delegate retail_* variants.
        assert load_golden_dataset("retail_no_fks").name == "retail_no_fks"
        conn = build_golden_sqlite("retail_full")
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
            assert cur.fetchone()[0] == 10
        finally:
            conn.close()

    def test_retail_hint_pack_loads(self):
        hp = load_hint_pack("retail", "pos")
        assert hp
        assert "table_patterns" in hp and "naming_conventions" in hp


# ── cross-family generalization (runs ensemble, gated) ─────────────────────

@pytest.mark.discovery_benchmark
class TestCrossFamilyGeneralization:
    """The §7 cross-pilot result: own hint pack helps, the other family's does not."""

    @staticmethod
    def _matrix():
        spec = importlib.util.spec_from_file_location(
            "discovery_cross_family_eval",
            Path(__file__).resolve().parent.parent / "scripts"
            / "discovery_cross_family_eval.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.build_cross_family_matrix()

    def test_own_hint_helps_each_family(self):
        m = self._matrix()
        assert m["ablation_no_fks"]["retail"]["own_delta"] > 0
        assert m["ablation_no_fks"]["gestion"]["own_delta"] > 0

    def test_cross_hint_does_not_leak(self):
        # the Argentine pack must NOT fire on retail, and vice versa.
        m = self._matrix()
        assert m["ablation_no_fks"]["retail"]["cross_delta_max"] == 0.0
        assert m["ablation_no_fks"]["gestion"]["cross_delta_max"] == 0.0

    def test_structural_generalizes_and_verdicts_hold(self):
        m = self._matrix()
        assert all(v >= 0.8 for v in m["structural_full_recall"].values())
        assert m["verdicts"] == {
            "per_family_curation_works": True,
            "hint_packs_are_specific": True,
            "structural_inference_generalizes": True,
        }
