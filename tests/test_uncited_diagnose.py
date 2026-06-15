"""
N5 uncited-claims diagnostic primitives (VAL-192).

Unit-covers the deterministic categorization helpers the diagnosis relies on
(_near tolerance + column aggregate extraction). The full diagnose() is
validated by running on a captured state (scripts/uncited_claims_diagnose.py).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "uncited_claims_diagnose", _ROOT / "scripts" / "uncited_claims_diagnose.py")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def test_near_relative_tolerance():
    assert _MOD._near(100.0, [100.4], tol=0.005)        # 0.4% < 0.5%
    assert not _MOD._near(100.0, [101.0], tol=0.005)    # 1% > 0.5%
    assert _MOD._near(0.0, [0.0])                        # exact zero
    assert not _MOD._near(1000.0, [500.0, 2000.0])


def test_column_aggregates_sum_count_max():
    qr = {"results": {"q": {"rows": [{"a": 1, "b": 10}, {"a": 2, "b": 20}]}}}
    aggs = {(round(v, 2), col, kind) for v, _q, col, kind in _MOD._column_aggregates(qr)}
    assert (3.0, "a", "sum") in aggs
    assert (2.0, "a", "count") in aggs
    assert (20.0, "b", "max") in aggs


def test_column_aggregates_skips_non_numeric():
    qr = {"results": {"q": {"rows": [{"name": "ACME", "v": "5"}, {"name": "X", "v": "7"}]}}}
    aggs = {(round(v, 2), col, kind) for v, _q, col, kind in _MOD._column_aggregates(qr)}
    # "name" is non-numeric → no aggregates; numeric-strings parse.
    assert (12.0, "v", "sum") in aggs
    assert not any(col == "name" for _v, col, _k in aggs)


def test_raw_floats_collects_numeric_cells():
    qr = {"results": {"q": {"rows": [{"a": 1, "b": "x"}, {"a": "2.5"}]}}}
    assert sorted(_MOD._raw_floats(qr)) == [1.0, 2.5]
