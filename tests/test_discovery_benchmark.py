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
    compare_hint_delta_to_baseline,
    compare_to_baseline,
    hint_pack_deltas,
    load_baseline,
    load_golden_hint_pack,
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
        # 3 variants x 3 modes (fk_only, ensemble, ensemble_hinted) — VAL-175
        assert len(baseline["results"]) == 9
        modes = {r["mode"] for r in baseline["results"]}
        assert modes == {"fk_only", "ensemble", "ensemble_hinted"}
        # hint_pack_name must be set iff the row is the hinted (moat) run.
        for r in baseline["results"]:
            expected = "argentina_gestion" if r["mode"] == "ensemble_hinted" else ""
            assert r.get("hint_pack_name", "") == expected, r["mode"]

    def test_no_fk_recall_regression(self, baseline, current_results):
        # Fail-fast if the moat rows vanished: otherwise this gate silently checks
        # fewer rows without complaint (VAL-175).
        assert any(r.mode == "ensemble_hinted" for r in current_results), \
            "no ensemble_hinted rows produced — run_all_variants regressed"
        failures = []
        for r in current_results:
            ok, msg = compare_to_baseline(r, baseline, recall_tolerance=0.05)
            if not ok:
                failures.append(msg)
        assert not failures, "FK recall regressions detected:\n" + "\n".join(failures)


@pytest.mark.discovery_benchmark
class TestHintPackAblation:
    """Moat metric (VAL-175): the curated ERP hint pack must measurably lift recall
    where commodity structural inference fails, and the gate must cover that delta."""

    def test_real_hint_pack_loads(self):
        """DoD #1: country/erp_type map to the real argentina_gestion.yaml."""
        hp = load_golden_hint_pack()
        assert hp, "hint pack must not be empty (naming mismatch regressed)"
        assert "table_patterns" in hp
        assert "naming_conventions" in hp

    def test_wrong_naming_returns_empty_hint_pack(self):
        """Documents the original VAL-175 bug: the business_context labels
        ('AR', 'gestion_pyme_argentina') do NOT resolve any YAML and degrade to {}."""
        from valinor.discovery.erp_hints import load_hint_pack
        assert load_hint_pack("AR", "gestion_pyme_argentina") == {}

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_hint_pack_never_reduces_recall(self, variant):
        """The hint pack adds deterministic candidates — it can only help, never hurt."""
        golden = load_golden_dataset(variant)
        conn = build_golden_sqlite(variant)
        try:
            plain = EnsembleBenchmark(golden, conn).run()
            hinted = EnsembleBenchmark(
                golden, conn,
                hint_pack=load_golden_hint_pack(),
                hint_pack_name="argentina_gestion",
            ).run()
        finally:
            conn.close()
        assert plain.mode == "ensemble"
        assert hinted.mode == "ensemble_hinted"
        assert hinted.hint_pack_name == "argentina_gestion"
        assert hinted.fk_recall >= plain.fk_recall - 1e-9

    def test_no_fks_variant_shows_positive_moat_delta(self):
        """The moat datapoint: with NO FK constraints (the real SYSCOP/BDPYME case),
        the hint pack recovers the CompDet -> CompCab header/detail link that
        structural inference misses."""
        golden = load_golden_dataset("gloria_no_fks")
        conn = build_golden_sqlite("gloria_no_fks")
        try:
            plain = EnsembleBenchmark(golden, conn).run()
            hinted = EnsembleBenchmark(
                golden, conn,
                hint_pack=load_golden_hint_pack(),
                hint_pack_name="argentina_gestion",
            ).run()
        finally:
            conn.close()
        assert hinted.fk_recall > plain.fk_recall  # the moat lift
        # Verify the SPECIFIC relation the hint pack recovered, not just "some" gain.
        link = "compdet.nrocomp -> compcab.nrocomp"
        assert link in hinted.true_positives
        assert link not in plain.true_positives

    def test_moat_delta_gate_passes_against_baseline(self):
        """DoD #3: the regression gate covers the hint-pack delta, and current==baseline."""
        if not BASELINE_PATH.exists():
            pytest.skip(f"No baseline at {BASELINE_PATH}")
        baseline = load_baseline(BASELINE_PATH)
        results = run_all_variants(mode="ensemble")
        ok, messages = compare_hint_delta_to_baseline(results, baseline, delta_tolerance=0.05)
        assert ok, "moat delta regressed:\n" + "\n".join(messages)

    def test_moat_delta_gate_flags_erosion(self):
        """A baseline claiming a larger hint-pack lift than current must fail the gate."""
        results = run_all_variants(mode="ensemble")
        # Fake a baseline where the hint pack used to recover ALL relations for no_fks.
        fake_baseline = {
            "version": 1,
            "results": [
                {"variant": "gloria_no_fks", "mode": "ensemble", "fk_recall": 0.0},
                {"variant": "gloria_no_fks", "mode": "ensemble_hinted", "fk_recall": 1.0},
            ],
        }
        ok, messages = compare_hint_delta_to_baseline(results, fake_baseline, delta_tolerance=0.05)
        assert not ok
        assert any("recall eroded" in m for m in messages)

    def test_moat_gate_fails_closed_when_no_hinted_rows(self):
        """Critical: if the hint pack failed to load there are no ensemble_hinted rows,
        and the gate must FAIL (not pass on an empty intersection)."""
        results = run_all_variants(mode="ensemble")
        baseline = {"results": [r.to_dict() for r in results]}
        commodity_only = [r for r in results if r.mode != "ensemble_hinted"]
        ok, messages = compare_hint_delta_to_baseline(commodity_only, baseline)
        assert not ok
        assert any("no ensemble_hinted runs" in m for m in messages)

    def test_moat_gate_flags_vanished_variant(self):
        """If a variant the baseline gated stops producing an ensemble_hinted run,
        the gate must fail (measurement vanished), not silently skip it."""
        results = run_all_variants(mode="ensemble")
        baseline = {"results": [r.to_dict() for r in results]}
        # Drop gloria_no_fks' hinted row from the CURRENT results only.
        partial = [
            r for r in results
            if not (r.variant == "gloria_no_fks" and r.mode == "ensemble_hinted")
        ]
        ok, messages = compare_hint_delta_to_baseline(partial, baseline)
        assert not ok
        assert any("gloria_no_fks" in m and "vanished" in m for m in messages)

    def test_ensemble_benchmark_requires_hint_pack_name(self):
        """A non-empty hint_pack must be paired with a label, so mode and
        hint_pack_name can never disagree."""
        golden = load_golden_dataset("gloria_full")
        conn = build_golden_sqlite("gloria_full")
        try:
            with pytest.raises(ValueError):
                EnsembleBenchmark(golden, conn, hint_pack=load_golden_hint_pack())
        finally:
            conn.close()


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
