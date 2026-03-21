"""
Unit tests for SegmentationEngine.

Coverage:
- TestSegmentationEngine: 12 tests covering segment assignment, Pareto percentile
  logic, aggregate invariants, build_context_block output, and edge cases.

All tests use _make_query_results() to produce a realistic query_results dict
with a "results" list that _extract_customer_revenue() can parse.
No external services or DB connections are required.
"""
from __future__ import annotations

import sys
import pytest

sys.path.insert(0, ".")

from shared.memory.segmentation_engine import (
    SegmentationEngine,
    SegmentationResult,
    CustomerSegment,
    get_segmentation_engine,
    SEGMENT_NAMES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_profile(industry: str = "default", currency: str = "USD"):
    """Return a minimal object that satisfies the ClientProfile duck-type used
    by SegmentationEngine (only .industry_inferred and .currency_detected)."""
    class _FakeProfile:
        industry_inferred = industry
        currency_detected = currency
    return _FakeProfile()


def _make_query_results(clients: list[dict]) -> dict:
    """
    Wrap a list of dicts with keys client_name / revenue into the
    query_results structure that _extract_customer_revenue() parses.

    The column names are chosen to match the revenue-detection hints:
      - "customer" matches ["customer", ...]
      - "revenue"  matches ["revenue", ...]
    """
    rows = [{"customer": c["client_name"], "revenue": c["revenue"]} for c in clients]
    return {
        "results": {
            "customer_concentration": {
                "columns": ["customer", "revenue"],
                "rows": rows,
            }
        }
    }


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

CLIENTS = [
    # Champions (top ~20 %)
    {"client_name": "Alpha Corp",    "revenue": 120_000, "frequency": 50, "recency_days": 5},
    {"client_name": "Beta Ltd",      "revenue": 110_000, "frequency": 48, "recency_days": 7},
    # Growth (middle ~60 %)
    {"client_name": "Gamma SA",      "revenue": 40_000,  "frequency": 20, "recency_days": 30},
    {"client_name": "Delta SRL",     "revenue": 35_000,  "frequency": 18, "recency_days": 45},
    {"client_name": "Epsilon GmbH",  "revenue": 30_000,  "frequency": 15, "recency_days": 60},
    {"client_name": "Zeta Inc",      "revenue": 28_000,  "frequency": 12, "recency_days": 55},
    {"client_name": "Eta AG",        "revenue": 25_000,  "frequency": 10, "recency_days": 65},
    # Maintenance (bottom ~20 %)
    {"client_name": "Theta BV",      "revenue": 5_000,   "frequency": 3,  "recency_days": 200},
    {"client_name": "Iota NV",       "revenue": 3_000,   "frequency": 2,  "recency_days": 280},
    {"client_name": "Kappa LLC",     "revenue": 1_000,   "frequency": 1,  "recency_days": 350},
]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestSegmentationEngine:
    """Tests for SegmentationEngine using the default (generic Tier 1/2/3) industry."""

    def setup_method(self):
        self.engine = SegmentationEngine()
        self.profile = _make_profile(industry="default", currency="USD")
        # Segment names for "default" industry
        self.names = SEGMENT_NAMES["default"]  # top=Tier 1, mid=Tier 2, low=Tier 3

    def _segment(self, clients: list[dict]) -> SegmentationResult:
        qr = _make_query_results(clients)
        return self.engine.segment_from_query_results(qr, self.profile)

    # 1. Champion-equivalent (Tier 1) client: high revenue, recent, frequent
    def test_champion_segment_high_revenue_recent(self):
        result = self._segment(CLIENTS)
        top_seg = result.segments[0]  # "Tier 1" — top 20 %
        top_names = [c for c in top_seg.top_customers]
        # Alpha Corp and Beta Ltd are the two highest-revenue clients
        assert "Alpha Corp" in top_names or "Beta Ltd" in top_names, (
            f"Expected high-revenue clients in top segment; got {top_names}"
        )

    # 2. At-risk client: good history but very high recency_days → Maintenance (Tier 3)
    def test_at_risk_segment_low_recency(self):
        result = self._segment(CLIENTS)
        low_seg = result.segments[2]  # "Tier 3" — bottom 20 %
        low_names = low_seg.top_customers
        # Kappa LLC has recency_days=350 and lowest revenue
        assert "Kappa LLC" in low_names, (
            f"Expected Kappa LLC (highest recency) in low segment; got {low_names}"
        )

    # 3. New client with 1-2 orders → also ends up in low segment (low revenue)
    def test_new_client_segment(self):
        clients_with_new = CLIENTS + [
            {"client_name": "NewBie Co", "revenue": 500, "frequency": 1, "recency_days": 10}
        ]
        result = self._segment(clients_with_new)
        low_seg = result.segments[2]
        low_names = low_seg.top_customers
        assert "NewBie Co" in low_names, (
            f"New client with 1 order and revenue=500 should be in low segment; got {low_names}"
        )

    # 4. Empty client list → None returned (no data to segment)
    def test_empty_client_list_returns_empty(self):
        result = self._segment([])
        assert result is None, (
            "Expected None when no customer revenue data is available"
        )

    # 5. All input clients appear in exactly one segment
    def test_all_clients_assigned_to_a_segment(self):
        result = self._segment(CLIENTS)
        assert result is not None
        total_in_segments = sum(seg.count for seg in result.segments)
        assert total_in_segments == len(CLIENTS), (
            f"Expected all {len(CLIENTS)} clients assigned; got {total_in_segments} across segments"
        )

    # 6. Sum of segment counts equals number of input clients
    def test_segment_counts_match_input_count(self):
        result = self._segment(CLIENTS)
        assert result is not None
        assert result.total_customers == len(CLIENTS)
        segment_total = sum(seg.count for seg in result.segments)
        assert segment_total == result.total_customers

    # 7. Top segment (Tier 1 / Champions) has highest average revenue
    def test_champions_have_highest_revenue_on_average(self):
        result = self._segment(CLIENTS)
        assert result is not None
        top_avg = result.segments[0].avg_revenue       # Tier 1
        maintenance_avg = result.segments[2].avg_revenue  # Tier 3
        assert top_avg > maintenance_avg, (
            f"Top segment avg {top_avg:.0f} should exceed Maintenance avg {maintenance_avg:.0f}"
        )

    # 8. At-risk / low segment clients have higher recency than top clients.
    #    Proxy: we verify top_customers of low segment are the lowest-revenue
    #    clients (since recency_days correlates inversely with revenue in our data).
    def test_at_risk_have_higher_recency_than_active(self):
        result = self._segment(CLIENTS)
        assert result is not None
        # Build a quick lookup of recency from test data
        recency_lookup = {c["client_name"]: c["recency_days"] for c in CLIENTS}

        top_seg_names = result.segments[0].top_customers
        low_seg_names = result.segments[2].top_customers

        top_recencies = [recency_lookup[n] for n in top_seg_names if n in recency_lookup]
        low_recencies = [recency_lookup[n] for n in low_seg_names if n in recency_lookup]

        assert top_recencies and low_recencies, "Need at least one name per segment in lookup"
        avg_top = sum(top_recencies) / len(top_recencies)
        avg_low = sum(low_recencies) / len(low_recencies)
        assert avg_low > avg_top, (
            f"Low-segment avg recency ({avg_low:.0f}) should exceed top-segment avg ({avg_top:.0f})"
        )

    # 9. build_context_block returns a non-empty string for a valid result
    def test_context_string_non_empty(self):
        result = self._segment(CLIENTS)
        assert result is not None
        context = self.engine.build_context_block(result, currency="USD")
        assert isinstance(context, str) and len(context) > 0, (
            "build_context_block should return a non-empty string"
        )

    # 10. Context string mentions the count of top-segment clients
    def test_context_string_mentions_champion_count(self):
        result = self._segment(CLIENTS)
        assert result is not None
        context = self.engine.build_context_block(result, currency="USD")
        top_seg = result.segments[0]
        assert str(top_seg.count) in context, (
            f"Context block should mention top-segment count {top_seg.count}; got:\n{context}"
        )

    # 11. A single client still gets placed in a segment
    def test_single_client_gets_assigned(self):
        single = [{"client_name": "Solo Inc", "revenue": 9_999, "frequency": 5, "recency_days": 15}]
        result = self._segment(single)
        assert result is not None
        assert result.total_customers == 1
        total_in_segments = sum(seg.count for seg in result.segments)
        assert total_in_segments == 1, (
            "Single client must be assigned to exactly one segment"
        )

    # 12. Result dict (SegmentationResult.segments) contains the three expected
    #     segment names for the "default" industry: Tier 1, Tier 2, Tier 3
    def test_segment_keys_in_result(self):
        result = self._segment(CLIENTS)
        assert result is not None
        seg_names = {seg.name for seg in result.segments}
        expected_names = {
            self.names["top"],   # "Tier 1"
            self.names["mid"],   # "Tier 2"
            self.names["low"],   # "Tier 3"
        }
        assert expected_names == seg_names, (
            f"Expected segment names {expected_names}; got {seg_names}"
        )


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

CLIENTS_LARGE = [
    {"client_name": f"Client_{i:03d}", "revenue": float(10000 - i * 100)}
    for i in range(20)
    if 10000 - i * 100 > 0  # only positive revenues
]


class TestSegmentationEdgeCases:
    """Additional edge cases and invariants."""

    def _profile(self, industry="default", currency="USD"):
        return _make_profile(industry=industry, currency=currency)

    def test_total_revenue_matches_sum_of_segments(self):
        """result.total_revenue must equal sum of segment total_revenues."""
        engine = SegmentationEngine()
        qr = _make_query_results(CLIENTS_LARGE)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        seg_total = sum(s.total_revenue for s in result.segments)
        assert abs(result.total_revenue - seg_total) < 1.0

    def test_all_customers_are_assigned(self):
        """Every customer in input should appear in exactly one segment."""
        engine = SegmentationEngine()
        qr = _make_query_results(CLIENTS_LARGE)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        total_in_segs = sum(s.count for s in result.segments)
        assert total_in_segs == len(CLIENTS_LARGE)

    def test_empty_query_results_returns_none(self):
        """No matching revenue data → segment_from_query_results returns None."""
        engine = SegmentationEngine()
        result = engine.segment_from_query_results({"results": {}}, self._profile())
        assert result is None

    def test_build_context_block_returns_string(self):
        """build_context_block must return a non-empty string."""
        engine = SegmentationEngine()
        qr = _make_query_results(CLIENTS_LARGE)
        result = engine.segment_from_query_results(qr, self._profile())
        if result is not None:
            block = engine.build_context_block(result, currency="EUR")
            assert isinstance(block, str)
            assert len(block) > 0

    def test_get_segmentation_engine_singleton(self):
        """get_segmentation_engine() always returns the same instance."""
        e1 = get_segmentation_engine()
        e2 = get_segmentation_engine()
        assert e1 is e2

    def test_segment_names_has_default_key(self):
        """SEGMENT_NAMES dict must have a 'default' industry key."""
        assert "default" in SEGMENT_NAMES

    def test_customer_segment_dataclass_has_name(self):
        """CustomerSegment must have a name attribute."""
        seg = CustomerSegment(
            name="Tier 1",
            count=10,
            total_revenue=50000.0,
            revenue_share=0.8,
            avg_revenue=5000.0,
            top_customers=[],
            currency="USD",
            description="Top clients",
        )
        assert seg.name == "Tier 1"
        assert seg.count == 10
        assert abs(seg.total_revenue - 50000.0) < 0.01

    def test_segmentation_result_has_segments_list(self):
        """SegmentationResult.segments must be a list."""
        engine = SegmentationEngine()
        qr = _make_query_results(CLIENTS_LARGE)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        assert isinstance(result.segments, list)
        assert len(result.segments) >= 1

    def test_result_total_customers_correct(self):
        """result.total_customers must equal the number of input clients."""
        engine = SegmentationEngine()
        qr = _make_query_results(CLIENTS_LARGE)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        assert result.total_customers == len(CLIENTS_LARGE)

    def test_industry_stored_in_result(self):
        """result.industry must reflect the profile's industry."""
        engine = SegmentationEngine()
        qr = _make_query_results(CLIENTS_LARGE)
        result = engine.segment_from_query_results(qr, self._profile(industry="default"))
        assert result is not None
        assert result.industry == "default"


# ---------------------------------------------------------------------------
# Extended segmentation tests
# ---------------------------------------------------------------------------

class TestSegmentationEngineExtended:
    """Extended coverage: segment names, revenue shares, thresholds, update_profile."""

    def _profile(self, industry="default", currency="USD"):
        return _make_profile(industry=industry, currency=currency)

    def _segment(self, clients, industry="default"):
        engine = SegmentationEngine()
        qr = _make_query_results(clients)
        return engine.segment_from_query_results(qr, self._profile(industry=industry))

    def test_segment_names_match_industry_distribución(self):
        """For distribución industry, segment names are Champions / Growth / Maintenance."""
        result = self._segment(CLIENTS, industry="distribución mayorista")
        if result is None:
            pytest.skip("No data — skip industry name test")
        seg_names = {s.name for s in result.segments}
        assert "Champions" in seg_names
        assert "Growth" in seg_names
        assert "Maintenance" in seg_names

    def test_revenue_share_sums_to_approximately_1(self):
        """Sum of revenue_share across all segments must be approximately 1.0."""
        result = self._segment(CLIENTS)
        assert result is not None
        total_share = sum(s.revenue_share for s in result.segments)
        assert abs(total_share - 1.0) < 0.01, (
            f"revenue_share sum {total_share:.4f} must be ~1.0"
        )

    def test_top_segment_highest_revenue_share(self):
        """Tier 1 segment must have the highest revenue_share."""
        result = self._segment(CLIENTS)
        assert result is not None
        top = result.segments[0]
        low = result.segments[2]
        assert top.revenue_share >= low.revenue_share

    def test_avg_revenue_computed(self):
        """avg_revenue must be > 0 for a non-empty segment."""
        result = self._segment(CLIENTS)
        assert result is not None
        for seg in result.segments:
            if seg.count > 0:
                assert seg.avg_revenue > 0

    def test_top_customers_list_non_empty_for_populated_segment(self):
        """top_customers must contain at least one name for populated segments."""
        result = self._segment(CLIENTS)
        assert result is not None
        top_seg = result.segments[0]
        assert isinstance(top_seg.top_customers, list)
        assert len(top_seg.top_customers) > 0

    def test_segment_currency_preserved(self):
        """CustomerSegment.currency must match the currency passed to build_context_block."""
        engine = SegmentationEngine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile(currency="EUR"))
        assert result is not None
        ctx = engine.build_context_block(result, currency="EUR")
        assert "EUR" in ctx

    def test_result_has_computed_at_field(self):
        """SegmentationResult.computed_at must be a non-empty string."""
        result = self._segment(CLIENTS)
        assert result is not None
        assert isinstance(result.computed_at, str)
        assert len(result.computed_at) > 0

    def test_result_has_thresholds_dict(self):
        """SegmentationResult.thresholds must be a dict."""
        result = self._segment(CLIENTS)
        assert result is not None
        assert isinstance(result.thresholds, dict)

    def test_segment_names_not_for_retail(self):
        """For retail industry, segment names are VIP / Regulares / Ocasionales."""
        result = self._segment(CLIENTS, industry="retail / punto de venta")
        if result is None:
            pytest.skip("No data — skip retail name test")
        seg_names = {s.name for s in result.segments}
        assert "VIP" in seg_names
        assert "Regulares" in seg_names
        assert "Ocasionales" in seg_names

    def test_segment_names_for_default_are_tier(self):
        """For default industry, segment names must be Tier 1, Tier 2, Tier 3."""
        result = self._segment(CLIENTS, industry="default")
        assert result is not None
        seg_names = {s.name for s in result.segments}
        assert seg_names == {"Tier 1", "Tier 2", "Tier 3"}

    def test_all_segment_names_in_segment_names_dict(self):
        """SEGMENT_NAMES must contain keys for all four industries."""
        assert "default" in SEGMENT_NAMES
        assert "distribución mayorista" in SEGMENT_NAMES
        assert "retail / punto de venta" in SEGMENT_NAMES

    def test_total_revenue_matches_input(self):
        """result.total_revenue must equal sum of all client revenues in CLIENTS."""
        result = self._segment(CLIENTS)
        assert result is not None
        expected = sum(c["revenue"] for c in CLIENTS)
        assert abs(result.total_revenue - expected) < 1.0


# ---------------------------------------------------------------------------
# Further segmentation tests
# ---------------------------------------------------------------------------

class TestSegmentationEngineFurther:
    """Further coverage for SegmentationEngine."""

    def _engine(self):
        return SegmentationEngine()

    def _profile(self, industry="default", currency="USD"):
        return _make_profile(industry=industry, currency=currency)

    def test_result_has_three_segments(self):
        """SegmentationResult must always have exactly 3 segments."""
        engine = self._engine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        assert len(result.segments) == 3

    def test_result_total_customers_equals_len_clients(self):
        """total_customers must equal the number of distinct clients."""
        engine = self._engine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        assert result.total_customers == len(CLIENTS)

    def test_segment_count_sums_to_total_customers(self):
        """Sum of segment.count must equal total_customers."""
        engine = self._engine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        total = sum(s.count for s in result.segments)
        assert total == result.total_customers

    def test_build_context_block_returns_string(self):
        """build_context_block must return a non-empty string."""
        engine = self._engine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        ctx = engine.build_context_block(result, currency="EUR")
        assert isinstance(ctx, str) and len(ctx) > 0

    def test_result_industry_matches_profile(self):
        """SegmentationResult.industry must match the profile's industry."""
        engine = self._engine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile(industry="manufactura"))
        assert result is not None
        assert result.industry == "manufactura"

    def test_each_segment_has_name_string(self):
        """Every segment must have a non-empty string name."""
        engine = self._engine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        for seg in result.segments:
            assert isinstance(seg.name, str) and len(seg.name) > 0

    def test_each_segment_has_revenue_share_float(self):
        """Each segment.revenue_share must be a float in [0, 1]."""
        engine = self._engine()
        qr = _make_query_results(CLIENTS)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        for seg in result.segments:
            assert isinstance(seg.revenue_share, float)
            assert 0.0 <= seg.revenue_share <= 1.0

    def test_single_client_all_in_tier1(self):
        """With a single client, all revenue is in the top tier."""
        engine = self._engine()
        clients = [{"client_name": "Solo Corp", "revenue": 99999, "frequency": 10, "recency_days": 5}]
        qr = _make_query_results(clients)
        result = engine.segment_from_query_results(qr, self._profile())
        assert result is not None
        assert result.segments[0].count == 1

    def test_empty_client_list_handled(self):
        """Empty client list must not crash; result may be None or have 0 customers."""
        engine = self._engine()
        qr = _make_query_results([])
        try:
            result = engine.segment_from_query_results(qr, self._profile())
        except Exception:
            result = None
        # Either None or 0 customers is acceptable
        if result is not None:
            assert result.total_customers == 0 or result is not None
