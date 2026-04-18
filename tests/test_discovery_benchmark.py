"""
Discovery Engine benchmark — precision/recall/F1 + entity accuracy + consensus.

Runs FK-only and 4-agent ensemble discovery against 3 golden variants
(gloria_full, gloria_no_fks, gloria_obfuscated) and compares against a
saved baseline to catch regressions.

Opt-in: requires `--mark discovery_benchmark` (not in default run).

Refs: VAL-129
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from valinor.discovery.benchmark import (
    BenchmarkResult,
    DiscoveryBenchmark,
    EnsembleBenchmark,
    compare_to_baseline,
    load_baseline,
    run_all_variants,
    save_baseline,
)
from valinor.discovery.golden_dataset import (
    build_golden_sqlite,
    load_golden_dataset,
)

BASELINE_PATH = Path(__file__).parent / "data" / "discovery_baseline.json"
VARIANTS = ["gloria_full", "gloria_no_fks", "gloria_obfuscated"]


@pytest.mark.discovery_benchmark
class TestGoldenDataset:
    """Ground-truth dataset loads and builds correctly."""

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_load_variant(self, variant):
        golden = load_golden_dataset(variant)
        assert golden.name == variant
        assert len(golden.tables) == 10
        assert len(golden.relations) == 8

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_build_sqlite(self, variant):
        conn = build_golden_sqlite(variant)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}
            assert len(tables) == 10
        finally:
            conn.close()

    def test_no_fks_variant_has_zero_fk_constraints(self):
        conn = build_golden_sqlite("gloria_no_fks")
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for (tname,) in cur.fetchall():
                cur.execute(f"PRAGMA foreign_key_list([{tname}])")
                assert cur.fetchall() == [], f"{tname} must have no FKs"
        finally:
            conn.close()


@pytest.mark.discovery_benchmark
class TestFKDiscoveryBenchmark:
    """FK-only benchmark (statistical inclusion + name similarity)."""

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_runs_without_error(self, variant):
        golden = load_golden_dataset(variant)
        conn = build_golden_sqlite(variant)
        try:
            result = DiscoveryBenchmark(golden, conn).run()
            assert isinstance(result, BenchmarkResult)
            assert result.mode == "fk_only"
            assert result.variant == variant
            assert 0.0 <= result.fk_precision <= 1.0
            assert 0.0 <= result.fk_recall <= 1.0
        finally:
            conn.close()

    def test_full_variant_recalls_all_explicit_fks(self):
        """With explicit FKs and inclusion ratio 100%, recall must stay high."""
        golden = load_golden_dataset("gloria_full")
        conn = build_golden_sqlite("gloria_full")
        try:
            result = DiscoveryBenchmark(golden, conn).run()
            assert result.fk_recall >= 0.9


        finally:
            conn.close()


@pytest.mark.discovery_benchmark
class TestEnsembleBenchmark:
    """4-agent ensemble benchmark (structural + semantic + domain + process)."""

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_runs_without_error(self, variant):
        golden = load_golden_dataset(variant)
        conn = build_golden_sqlite(variant)
        try:
            result = EnsembleBenchmark(golden, conn).run()
            assert isinstance(result, BenchmarkResult)
            assert result.mode == "ensemble"
            assert result.variant == variant
            assert sum(result.consensus_counts.values()) >= 0
            assert 0.0 <= result.entity_accuracy <= 1.0
        finally:
            conn.close()

    def test_full_variant_structural_agent_finds_explicit_fks(self):
        """With explicit FKs, structural agent alone should produce high precision."""
        golden = load_golden_dataset("gloria_full")
        conn = build_golden_sqlite("gloria_full")
        try:
            result = EnsembleBenchmark(golden, conn).run()
            assert result.fk_precision >= 0.9
            # At least 7 of 8 explicit FKs (CondPago is never explicit, that's the implicit one)
            assert len(result.true_positives) >= 7
        finally:
            conn.close()


@pytest.mark.discovery_benchmark
class TestBaselineRegression:
    """Current benchmark must not regress more than 5% vs saved baseline."""

    @pytest.fixture(scope="class")
    def baseline(self):
        if not BASELINE_PATH.exists():
            pytest.skip(f"No baseline at {BASELINE_PATH}")
        return load_baseline(BASELINE_PATH)

    @pytest.fixture(scope="class")
    def current_results(self):
        return run_all_variants(mode="both")

    def test_baseline_file_is_valid(self, baseline):
        assert baseline["version"] == 1
        assert "results" in baseline
        assert len(baseline["results"]) == 6  # 3 variants x 2 modes

    def test_no_fk_recall_regression(self, baseline, current_results):
        failures = []
        for r in current_results:
            ok, msg = compare_to_baseline(r, baseline, recall_tolerance=0.05)
            if not ok:
                failures.append(msg)
        assert not failures, "FK recall regressions detected:\n" + "\n".join(failures)


@pytest.mark.discovery_benchmark
class TestBaselinePersistence:
    """save/load roundtrip."""

    def test_save_and_load_roundtrip(self, tmp_path):
        golden = load_golden_dataset("gloria_full")
        conn = build_golden_sqlite("gloria_full")
        try:
            result = DiscoveryBenchmark(golden, conn).run()
        finally:
            conn.close()

        path = tmp_path / "baseline.json"
        save_baseline([result], path)
        loaded = load_baseline(path)

        assert loaded["version"] == 1
        assert len(loaded["results"]) == 1
        assert loaded["results"][0]["variant"] == "gloria_full"
        assert loaded["results"][0]["fk_recall"] == round(result.fk_recall, 4)

    def test_compare_flags_regression(self, tmp_path):
        """compare_to_baseline returns False when recall drops beyond tolerance."""
        golden = load_golden_dataset("gloria_full")
        conn = build_golden_sqlite("gloria_full")
        try:
            current = EnsembleBenchmark(golden, conn).run()
        finally:
            conn.close()

        # Fake baseline with recall always higher than current + tolerance
        fake_baseline = {
            "version": 1,
            "results": [
                {
                    "variant": current.variant,
                    "mode": current.mode,
                    "fk_recall": current.fk_recall + 0.20,
                }
            ],
        }
        ok, msg = compare_to_baseline(current, fake_baseline, recall_tolerance=0.05)
        assert not ok
        assert "regressed" in msg
