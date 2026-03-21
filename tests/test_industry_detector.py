"""
Tests for IndustryDetector — shared/memory/industry_detector.py

Covers:
  - Distributor schema tables → distribución mayorista
  - Manufacturer schema tables → manufactura
  - Retail / POS schema tables → retail / punto de venta
  - Unknown table names → "desconocida" (generic fallback)
  - detect() always returns a non-empty string
  - update_profile() sets profile.industry_inferred
  - update_profile() logs when industry changes
  - Same entity_map always yields same industry (determinism)
  - Empty entity map handled without exception
  - Different industries may suggest different default thresholds
  - Confidence proxy: _match_industry score boundary
  - Table name normalisation — "PEDIDOS" vs "pedidos" treated identically
"""
import sys
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, "shared")
sys.path.insert(0, ".")

from memory.industry_detector import IndustryDetector
from memory.client_profile import ClientProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity_map(*table_names: str) -> dict:
    """Build a minimal entity_map whose entity keys are the given table names."""
    return {
        "entities": {
            name: {"table": name, "columns": []}
            for name in table_names
        }
    }


def _make_profile(name: str = "TestCorp") -> ClientProfile:
    return ClientProfile.new(name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIndustryDetectorHeuristics:

    def setup_method(self):
        self.detector = IndustryDetector()

    # 1 — Distributor tables
    def test_distributor_tables_detected(self):
        """entity_map with distributor keywords → distribución mayorista."""
        entity_map = _make_entity_map("c_invoice", "c_bpartner", "m_warehouse")
        result = self.detector.detect(entity_map, {})
        assert result["industry"] == "distribución mayorista"

    # 2 — Manufacturer tables
    def test_manufacturer_tables_detected(self):
        """entity_map with manufacturing keywords → manufactura."""
        entity_map = _make_entity_map("mrp_production", "bom", "workcenter")
        result = self.detector.detect(entity_map, {})
        assert result["industry"] == "manufactura"

    # 3 — Retail / POS tables
    def test_retail_tables_detected(self):
        """entity_map with POS keywords → retail / punto de venta."""
        entity_map = _make_entity_map("pos_order", "pos_session", "ticket")
        result = self.detector.detect(entity_map, {})
        assert result["industry"] == "retail / punto de venta"

    # 4 — Unknown tables return generic fallback
    def test_unknown_tables_returns_generic(self):
        """Random table names produce 'desconocida' (the generic fallback)."""
        entity_map = _make_entity_map("zz_foo", "yy_bar", "xx_baz")
        result = self.detector.detect(entity_map, {})
        assert result["industry"] == "desconocida"

    # 5 — detect() always returns a non-empty string
    def test_detect_returns_string(self):
        """detect() result['industry'] is always a non-empty string."""
        entity_map = _make_entity_map("some_table")
        result = self.detector.detect(entity_map, {})
        assert isinstance(result["industry"], str)
        assert len(result["industry"]) > 0

    # 8 — Determinism
    def test_detection_is_deterministic(self):
        """Same entity_map always returns the same industry string."""
        entity_map = _make_entity_map("mrp_production", "bom", "manufacturing")
        first = self.detector.detect(entity_map, {})
        second = self.detector.detect(entity_map, {})
        assert first["industry"] == second["industry"]

    # 9 — Empty entity map handled without exception
    def test_empty_entity_map_handled(self):
        """An entity_map with no entities must not raise any exception."""
        empty_map = {"entities": {}}
        try:
            result = self.detector.detect(empty_map, {})
        except Exception as exc:
            pytest.fail(f"detect() raised {exc!r} on an empty entity_map")
        assert isinstance(result, dict)
        assert "industry" in result

    # 10 — Different industries produce different threshold suggestions (structural)
    def test_industry_affects_default_thresholds(self):
        """
        Two different industry detections should not be identical industry strings,
        confirming the detector distinguishes them (which is a prerequisite for
        downstream threshold logic).
        """
        retail_map = _make_entity_map("pos_order", "pos_session")
        mfg_map = _make_entity_map("mrp_production", "bom", "routing")
        retail_result = self.detector.detect(retail_map, {})
        mfg_result = self.detector.detect(mfg_map, {})
        assert retail_result["industry"] != mfg_result["industry"]

    # 12 — Table name normalisation
    def test_table_name_normalization(self):
        """
        Upper-case and lower-case versions of the same keyword should be
        detected identically, since the detector lowercases everything.
        """
        lower_map = _make_entity_map("mrp_production", "bom")
        upper_map = _make_entity_map("MRP_PRODUCTION", "BOM")
        lower_result = self.detector.detect(lower_map, {})
        upper_result = self.detector.detect(upper_map, {})
        assert lower_result["industry"] == upper_result["industry"]


class TestIndustryDetectorUpdateProfile:

    def setup_method(self):
        self.detector = IndustryDetector()

    # 6 — update_profile() sets profile.industry_inferred
    def test_update_profile_sets_industry(self):
        """update_profile() must write a value into profile.industry_inferred."""
        profile = _make_profile()
        assert profile.industry_inferred is None
        entity_map = _make_entity_map("mrp_production", "bom")
        self.detector.update_profile(profile, entity_map, {})
        assert profile.industry_inferred is not None
        assert isinstance(profile.industry_inferred, str)

    # 7 — update_profile() logs when industry changes
    def test_update_profile_logs_change(self):
        """When industry changes from a previous value, structlog.info is called."""
        profile = _make_profile()
        profile.industry_inferred = "retail / punto de venta"  # previous run value

        entity_map = _make_entity_map("mrp_production", "bom", "workcenter")

        with patch("memory.industry_detector.logger") as mock_logger:
            self.detector.update_profile(profile, entity_map, {})
            # The module calls logger.info("Industry detected", ...)
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            # First positional arg is the event name
            assert call_args[0][0] == "Industry detected"

    def test_update_profile_no_log_when_unchanged(self):
        """When industry does not change, logger.info must NOT be called."""
        profile = _make_profile()
        entity_map = _make_entity_map("mrp_production", "bom")
        # Pre-seed the profile with the value the detector would return
        self.detector.update_profile(profile, entity_map, {})
        already_set = profile.industry_inferred

        with patch("memory.industry_detector.logger") as mock_logger:
            self.detector.update_profile(profile, entity_map, {})
            mock_logger.info.assert_not_called()


class TestIndustryDetectorConfidence:

    def setup_method(self):
        self.detector = IndustryDetector()

    # 11 — Confidence proxy: _match_industry score is non-negative
    def test_confidence_score_returned(self):
        """
        IndustryDetector does not expose an explicit 0-1 confidence value,
        but _match_industry() is driven by a keyword-hit score that must be
        >= 0. Verify indirectly that a high-signal entity_map scores higher
        than an empty one by confirming the industry is detected (score > 0)
        vs. fallback 'desconocida' for no-match (score == 0).
        """
        high_signal_map = _make_entity_map(
            "mrp_production", "bom", "routing", "workcenter", "manufacturing"
        )
        no_signal_map = _make_entity_map("zzz_table")

        high_result = self.detector.detect(high_signal_map, {})
        no_result = self.detector.detect(no_signal_map, {})

        # High-signal → known industry (score > 0)
        assert high_result["industry"] != "desconocida"
        # No-signal → fallback (score == 0)
        assert no_result["industry"] == "desconocida"


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------

class TestIndustryDetectorAdditional:
    """Additional edge cases for IndustryDetector."""

    def setup_method(self):
        self.detector = IndustryDetector()

    def test_detect_returns_dict_with_industry_key(self):
        """detect() must return a dict with 'industry' key."""
        result = self.detector.detect(_make_entity_map("some_table"), {})
        assert isinstance(result, dict)
        assert "industry" in result

    def test_detect_returns_dict_with_currency_key(self):
        """detect() result must contain 'currency' key."""
        result = self.detector.detect(_make_entity_map("some_table"), {})
        assert "currency" in result

    def test_detect_industry_is_string(self):
        """detect() result['industry'] must be a non-empty string."""
        result = self.detector.detect(_make_entity_map("account_invoice"), {})
        assert isinstance(result["industry"], str)
        assert len(result["industry"]) > 0

    def test_detect_currency_is_string(self):
        """detect() result['currency'] must be a non-empty string."""
        result = self.detector.detect(_make_entity_map(), {})
        assert isinstance(result["currency"], str)
        assert len(result["currency"]) > 0

    def test_detect_deterministic_same_input(self):
        """Same entity_map always returns same industry."""
        em = _make_entity_map("res_partner", "account_move", "stock_picking")
        r1 = self.detector.detect(em, {})
        r2 = self.detector.detect(em, {})
        assert r1["industry"] == r2["industry"]

    def test_update_profile_sets_industry(self):
        """update_profile() sets profile.industry_inferred."""
        profile = _make_profile("UpdateTest")
        em = _make_entity_map("mrp_production", "bom")
        self.detector.update_profile(profile, em, {})
        assert profile.industry_inferred is not None
        assert isinstance(profile.industry_inferred, str)

    def test_detect_with_empty_entity_map(self):
        """detect() with empty entity dict doesn't raise."""
        result = self.detector.detect({"entities": {}}, {})
        assert isinstance(result, dict)
        assert "industry" in result

    def test_detect_with_missing_entities_key(self):
        """detect() with completely empty dict doesn't raise."""
        result = self.detector.detect({}, {})
        assert isinstance(result, dict)

    def test_table_name_case_insensitive(self):
        """Upper and lower case table names yield the same industry."""
        upper = self.detector.detect(_make_entity_map("MRP_PRODUCTION", "BOM"), {})
        lower = self.detector.detect(_make_entity_map("mrp_production", "bom"), {})
        assert upper["industry"] == lower["industry"]

    def test_update_profile_currency_detected(self):
        """update_profile() may set profile.currency_detected."""
        profile = _make_profile("CurrencyTest")
        em = _make_entity_map("account_move", "res_partner")
        self.detector.update_profile(profile, em, {"currency": "EUR"})
        # Either it was set or remained None — no crash is the main check
        assert profile.currency_detected is None or isinstance(profile.currency_detected, str)


# ---------------------------------------------------------------------------
# Extended industry detection tests
# ---------------------------------------------------------------------------

class TestIndustryDetectorExtended:
    """More coverage for IndustryDetector heuristics and profile integration."""

    def setup_method(self):
        self.detector = IndustryDetector()

    def test_finanzas_tables_detected(self):
        """account_move related tables → finanzas / contabilidad."""
        em = _make_entity_map("account_move", "account_journal", "account_account")
        result = self.detector.detect(em, {})
        assert result["industry"] == "finanzas / contabilidad"

    def test_detect_returns_currency_string(self):
        """detect() result always has a non-empty 'currency' string."""
        em = _make_entity_map("account_move")
        result = self.detector.detect(em, {})
        assert "currency" in result
        assert isinstance(result["currency"], str)
        assert len(result["currency"]) > 0

    def test_detect_two_different_industries_differ(self):
        """Two clearly different domain tables should yield different industry labels."""
        mfg_em = _make_entity_map("mrp_production", "bom", "routing")
        dist_em = _make_entity_map("c_invoice", "c_bpartner", "m_warehouse")
        mfg = self.detector.detect(mfg_em, {})
        dist = self.detector.detect(dist_em, {})
        assert mfg["industry"] != dist["industry"]

    def test_update_profile_is_idempotent(self):
        """Calling update_profile twice with the same entity_map leaves the same industry."""
        profile = _make_profile("IdempotentTest")
        em = _make_entity_map("mrp_production", "bom")
        self.detector.update_profile(profile, em, {})
        industry_after_first = profile.industry_inferred
        self.detector.update_profile(profile, em, {})
        assert profile.industry_inferred == industry_after_first

    def test_detect_with_none_entity_map_fallback(self):
        """detect() with None entities dict falls back gracefully (no crash)."""
        try:
            result = self.detector.detect({}, {})
        except Exception as exc:
            pytest.fail(f"detect({{}}) raised {exc!r}")
        assert isinstance(result, dict)

    def test_single_table_returns_valid_industry(self):
        """Even a single-table entity_map must return a valid industry string."""
        em = _make_entity_map("pos_order")
        result = self.detector.detect(em, {})
        assert isinstance(result["industry"], str)
        assert len(result["industry"]) > 0

    def test_multiple_industry_tables_resolves_dominant(self):
        """When tables from 2+ industries are present, the dominant one wins."""
        # Mix of manufacturing (stronger signal) + one retail table
        em = _make_entity_map(
            "mrp_production", "bom", "routing", "workcenter",
            "pos_order",
        )
        result = self.detector.detect(em, {})
        # manufactura should win (4 keyword hits vs 1)
        assert result["industry"] == "manufactura"

    def test_profile_industry_is_str_after_update(self):
        """profile.industry_inferred is always a str after update_profile."""
        profile = _make_profile("StrCheck")
        em = _make_entity_map("zz_unknown")
        self.detector.update_profile(profile, em, {})
        assert isinstance(profile.industry_inferred, str)

    def test_detect_with_dict_without_entities_key(self):
        """detect() with a dict that has no 'entities' key must not raise."""
        try:
            result = self.detector.detect({"other_key": {}}, {})
        except Exception as exc:
            pytest.fail(f"detect() raised {exc!r} when 'entities' key missing")
        assert isinstance(result, dict)

    def test_update_profile_sets_non_empty_industry(self):
        """After update_profile(), profile.industry_inferred is never an empty string."""
        profile = _make_profile("NonEmptyTest")
        em = _make_entity_map("res_partner", "account_move")
        self.detector.update_profile(profile, em, {})
        assert profile.industry_inferred is not None
        assert len(profile.industry_inferred) > 0
