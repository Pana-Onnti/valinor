"""
Tests for ClientProfile (data model) and ProfileStore (async I/O).

ProfileStore tests use a temporary directory as the local file backend so
they never touch /tmp/valinor_profiles or a real PostgreSQL instance.
asyncpg is patched / avoided by leaving DATABASE_URL empty, which forces
ProfileStore into file-only mode.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "shared")
sys.path.insert(0, "core")
sys.path.insert(0, ".")

from memory.client_profile import ClientProfile, ClientRefinement
from memory.profile_store import ProfileStore, detect_schema_drift


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_store(tmp_dir: Path) -> ProfileStore:
    """
    Return a ProfileStore that writes only to *tmp_dir* and never touches
    PostgreSQL (DATABASE_URL is empty so _use_db is False from the start).
    """
    store = ProfileStore.__new__(ProfileStore)
    store._db_url = ""
    store._pool = None
    store._use_db = False
    # Monkey-patch the internal path used by save() / load()
    import memory.profile_store as _ps_module
    store._local_dir = tmp_dir
    # We patch the module-level _LOCAL_DIR used inside load/save via the
    # instance attribute approach: override the methods to use tmp_dir.
    original_save = ProfileStore.save
    original_load = ProfileStore.load

    async def _patched_save(self, profile: ClientProfile) -> bool:
        profile.updated_at = __import__("datetime").datetime.utcnow().isoformat()
        data = json.dumps(profile.to_dict())
        path = tmp_dir / f"{profile.client_name}.json"
        path.write_text(data)
        return True

    async def _patched_load(self, client_name: str):
        path = tmp_dir / f"{client_name}.json"
        if path.exists():
            data = json.loads(path.read_text())
            return ClientProfile.from_dict(data)
        return None

    store.save = lambda profile: _patched_save(store, profile)
    store.load = lambda client_name: _patched_load(store, client_name)

    async def _patched_load_or_create(client_name: str) -> ClientProfile:
        existing = await store.load(client_name)
        if existing:
            return existing
        return ClientProfile.new(client_name)

    store.load_or_create = _patched_load_or_create

    return store


def _make_tmp_dir() -> Path:
    """Create and return a unique temp directory for one test."""
    d = Path(f"/tmp/test_profile_store_{uuid.uuid4().hex}")
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# TestClientProfile — pure data-model tests (no I/O)
# ---------------------------------------------------------------------------

class TestClientProfile:
    """Unit tests for the ClientProfile dataclass and its helpers."""

    def test_default_fields_are_correct_types(self):
        """A freshly created profile has the expected field types."""
        profile = ClientProfile.new("Acme Corp")

        assert isinstance(profile.client_name, str)
        assert isinstance(profile.created_at, str)
        assert isinstance(profile.updated_at, str)
        assert isinstance(profile.known_findings, dict)
        assert isinstance(profile.resolved_findings, dict)
        assert isinstance(profile.focus_tables, list)
        assert isinstance(profile.table_weights, dict)
        assert isinstance(profile.baseline_history, dict)
        assert isinstance(profile.preferred_queries, list)
        assert isinstance(profile.false_positives, list)
        assert isinstance(profile.run_history, list)
        assert isinstance(profile.alert_thresholds, list)
        assert isinstance(profile.triggered_alerts, list)
        assert isinstance(profile.segmentation_history, list)
        assert isinstance(profile.dq_history, list)
        assert isinstance(profile.webhooks, list)
        assert isinstance(profile.metadata, dict)
        assert profile.run_count == 0
        assert profile.entity_map_cache is None
        assert profile.refinement is None

    def test_add_to_known_findings(self):
        """Storing a finding dict in known_findings is retrievable."""
        profile = ClientProfile.new("Beta Corp")
        finding = {
            "id": "F001",
            "title": "High AR overdue",
            "severity": "HIGH",
            "agent": "analyst",
            "first_seen": "2025-01-01T00:00:00",
            "last_seen": "2025-01-01T00:00:00",
            "runs_open": 1,
        }
        profile.known_findings["F001"] = finding

        assert "F001" in profile.known_findings
        assert profile.known_findings["F001"]["severity"] == "HIGH"
        assert profile.known_findings["F001"]["title"] == "High AR overdue"

    def test_dq_history_append(self):
        """Appending entries to dq_history works and the length grows correctly."""
        profile = ClientProfile.new("Gamma Ltd")
        assert len(profile.dq_history) == 0

        for i in range(3):
            profile.dq_history.append({"run": i, "score": 90 - i * 5})

        assert len(profile.dq_history) == 3
        assert profile.dq_history[0]["run"] == 0
        assert profile.dq_history[2]["score"] == 80

    def test_webhooks_list_starts_empty(self):
        """webhooks is an empty list on a brand-new profile."""
        profile = ClientProfile.new("Delta Industries")
        assert profile.webhooks == []
        assert isinstance(profile.webhooks, list)

    def test_metadata_dict_operations(self):
        """Arbitrary key/value pairs can be stored and retrieved from metadata."""
        profile = ClientProfile.new("Epsilon Trading")
        profile.metadata["contract_tier"] = "enterprise"
        profile.metadata["max_analyses_per_month"] = 50
        profile.metadata["notify_on_critical"] = True

        assert profile.metadata["contract_tier"] == "enterprise"
        assert profile.metadata["max_analyses_per_month"] == 50
        assert profile.metadata["notify_on_critical"] is True

    def test_profile_serialization_round_trip(self):
        """Converting to dict via dataclasses.asdict and back preserves all fields."""
        original = ClientProfile.new("Zeta Logistics")
        original.run_count = 7
        original.industry_inferred = "logistics"
        original.currency_detected = "USD"
        original.known_findings["F001"] = {"id": "F001", "severity": "MEDIUM"}
        original.dq_history.append({"score": 88})
        original.metadata["key"] = "value"

        as_dict = dataclasses.asdict(original)
        restored = ClientProfile.from_dict(as_dict)

        assert restored.client_name == original.client_name
        assert restored.run_count == 7
        assert restored.industry_inferred == "logistics"
        assert restored.currency_detected == "USD"
        assert restored.known_findings["F001"]["severity"] == "MEDIUM"
        assert restored.dq_history[0]["score"] == 88
        assert restored.metadata["key"] == "value"


# ---------------------------------------------------------------------------
# TestProfileStore — async I/O with local file backend
# ---------------------------------------------------------------------------

class TestProfileStore:
    """
    Integration-style tests for ProfileStore using a temp directory.
    No real PostgreSQL connection is made; DATABASE_URL is not set so the
    store falls back entirely to local JSON files.
    """

    # pytest-asyncio is not required: we drive coroutines via asyncio.run().

    def _run(self, coro):
        """Run a coroutine synchronously."""
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_save_and_load_roundtrip(self):
        """Saving a profile and loading it back yields identical field values."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile = ClientProfile.new("Roundtrip Corp")
        profile.run_count = 3
        profile.industry_inferred = "retail"
        profile.currency_detected = "EUR"

        saved = self._run(store.save(profile))
        assert saved is True

        loaded = self._run(store.load("Roundtrip Corp"))
        assert loaded is not None
        assert loaded.client_name == "Roundtrip Corp"
        assert loaded.run_count == 3
        assert loaded.industry_inferred == "retail"
        assert loaded.currency_detected == "EUR"

    def test_load_nonexistent_returns_none(self):
        """Loading a client that was never saved returns None."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        result = self._run(store.load("Ghost Client"))
        assert result is None

    def test_load_or_create_creates_new_profile(self):
        """load_or_create() returns a fresh ClientProfile when none exists yet."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile = self._run(store.load_or_create("New Client"))
        assert profile is not None
        assert profile.client_name == "New Client"
        assert profile.run_count == 0

    def test_load_or_create_returns_existing(self):
        """load_or_create() returns the previously saved profile, not a fresh one."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile = ClientProfile.new("Existing Client")
        profile.run_count = 12
        self._run(store.save(profile))

        loaded = self._run(store.load_or_create("Existing Client"))
        assert loaded.run_count == 12

    def test_save_updates_run_count(self):
        """A profile saved with run_count=5 is reloaded with run_count=5."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile = ClientProfile.new("Run Count Corp")
        profile.run_count = 5
        self._run(store.save(profile))

        reloaded = self._run(store.load("Run Count Corp"))
        assert reloaded is not None
        assert reloaded.run_count == 5

    def test_save_persists_known_findings(self):
        """Findings added to known_findings are present after a save/load cycle."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile = ClientProfile.new("Findings Corp")
        profile.known_findings["F001"] = {
            "id": "F001",
            "title": "Overdue AR",
            "severity": "HIGH",
            "agent": "analyst",
            "first_seen": "2025-01-01T00:00:00",
            "last_seen": "2025-02-01T00:00:00",
            "runs_open": 2,
        }
        profile.known_findings["F002"] = {
            "id": "F002",
            "title": "Duplicate invoices",
            "severity": "MEDIUM",
            "agent": "sentinel",
            "first_seen": "2025-01-15T00:00:00",
            "last_seen": "2025-01-15T00:00:00",
            "runs_open": 1,
        }
        self._run(store.save(profile))

        reloaded = self._run(store.load("Findings Corp"))
        assert reloaded is not None
        assert "F001" in reloaded.known_findings
        assert "F002" in reloaded.known_findings
        assert reloaded.known_findings["F001"]["severity"] == "HIGH"
        assert reloaded.known_findings["F002"]["title"] == "Duplicate invoices"

    def test_save_persists_dq_history(self):
        """dq_history entries are fully preserved across a save/load cycle."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile = ClientProfile.new("DQ History Corp")
        profile.dq_history.append({"period": "2025-01", "score": 92, "tag": "FINAL"})
        profile.dq_history.append({"period": "2025-02", "score": 85, "tag": "REVISED"})
        self._run(store.save(profile))

        reloaded = self._run(store.load("DQ History Corp"))
        assert reloaded is not None
        assert len(reloaded.dq_history) == 2
        assert reloaded.dq_history[0]["score"] == 92
        assert reloaded.dq_history[1]["tag"] == "REVISED"

    def test_load_or_create_preserves_existing_fields(self):
        """load_or_create() must not overwrite fields of an already-saved profile."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile = ClientProfile.new("Preserved Corp")
        profile.industry_inferred = "manufacturing"
        profile.run_count = 8
        profile.metadata["custom_flag"] = True
        self._run(store.save(profile))

        # Call load_or_create a second time — should return the saved version.
        retrieved = self._run(store.load_or_create("Preserved Corp"))
        assert retrieved.industry_inferred == "manufacturing"
        assert retrieved.run_count == 8
        assert retrieved.metadata["custom_flag"] is True

    def test_concurrent_saves_do_not_corrupt(self):
        """
        Saving two different profiles concurrently must not corrupt either one.
        Each profile is loaded back and verified to carry its own client_name.
        """
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        profile_a = ClientProfile.new("Alpha Corp")
        profile_a.run_count = 1
        profile_b = ClientProfile.new("Beta Corp")
        profile_b.run_count = 2

        async def _run_concurrent():
            await asyncio.gather(
                store.save(profile_a),
                store.save(profile_b),
            )

        self._run(_run_concurrent())

        loaded_a = self._run(store.load("Alpha Corp"))
        loaded_b = self._run(store.load("Beta Corp"))

        assert loaded_a is not None
        assert loaded_b is not None
        assert loaded_a.client_name == "Alpha Corp"
        assert loaded_b.client_name == "Beta Corp"
        assert loaded_a.run_count == 1
        assert loaded_b.run_count == 2


# ---------------------------------------------------------------------------
# TestDetectSchemaDrift — utility function tests
# ---------------------------------------------------------------------------

class TestDetectSchemaDrift:
    """Unit tests for the detect_schema_drift() helper function."""

    def test_empty_cached_map_is_always_drift(self):
        """An empty cached entity map is treated as full drift."""
        result = detect_schema_drift({}, {"entities": {"orders": {}}})
        assert result is True

    def test_identical_maps_have_no_drift(self):
        """Identical entity maps produce no drift."""
        entity_map = {"entities": {"orders": {}, "customers": {}, "invoices": {}}}
        result = detect_schema_drift(entity_map, entity_map)
        assert result is False

    def test_adding_two_of_ten_tables_is_drift(self):
        """Adding 2 tables to a 10-table map (20%) exceeds the 10% threshold."""
        base = {"entities": {f"table_{i}": {} for i in range(10)}}
        extended = {"entities": {f"table_{i}": {} for i in range(12)}}
        result = detect_schema_drift(base, extended)
        assert result is True

    def test_removing_one_of_twenty_tables_is_not_drift(self):
        """Removing 1 table from a 20-table map stays within the 10% threshold (5%)."""
        base = {"entities": {f"table_{i}": {} for i in range(20)}}
        reduced = {"entities": {f"table_{i}": {} for i in range(19)}}
        result = detect_schema_drift(base, reduced)
        assert result is False

    def test_exact_10_percent_change_is_not_drift(self):
        """A change of exactly 10% (boundary) does NOT trigger drift (> not >=)."""
        # 10 tables, remove 1 → 10% change, which is NOT > 0.10
        base = {"entities": {f"table_{i}": {} for i in range(10)}}
        reduced = {"entities": {f"table_{i}": {} for i in range(9)}}
        result = detect_schema_drift(base, reduced)
        assert result is False

    def test_replacing_one_table_name_is_drift(self):
        """Renaming a table (remove old + add new) doubles the change ratio."""
        base = {"entities": {"orders": {}, "customers": {}, "invoices": {}}}
        updated = {"entities": {"orders": {}, "customers": {}, "payments": {}}}
        # 1 removed + 1 added = 2 changes / 3 baseline = 66%
        result = detect_schema_drift(base, updated)
        assert result is True

    def test_both_maps_empty_entities_no_drift(self):
        """Two maps with empty entities dicts: cached has no tables → drift."""
        result = detect_schema_drift({"entities": {}}, {"entities": {}})
        assert result is True  # empty cached_tables → always drift

    def test_no_entities_key_in_cached(self):
        """cached_entity_map without 'entities' key is treated as empty → drift."""
        result = detect_schema_drift({}, {"entities": {"t1": {}}})
        assert result is True


# ---------------------------------------------------------------------------
# TestClientRefinement — ClientRefinement dataclass and helpers
# ---------------------------------------------------------------------------

class TestClientRefinement:
    """Tests for ClientRefinement and how ClientProfile uses it."""

    def test_default_refinement_is_none(self):
        """A new profile has refinement == None."""
        profile = ClientProfile.new("Fresh Corp")
        assert profile.refinement is None

    def test_get_refinement_returns_default_when_none(self):
        """get_refinement() returns an empty ClientRefinement when refinement is None."""
        profile = ClientProfile.new("Fresh Corp")
        refinement = profile.get_refinement()
        assert isinstance(refinement, ClientRefinement)
        assert refinement.table_weights == {}
        assert refinement.query_hints == []
        assert refinement.focus_areas == []
        assert refinement.suppress_ids == []
        assert refinement.context_block == ""

    def test_get_refinement_returns_stored_data(self):
        """get_refinement() reconstructs the ClientRefinement from the stored dict."""
        profile = ClientProfile.new("Refined Corp")
        profile.refinement = {
            "table_weights": {"orders": 0.8},
            "query_hints": ["focus on AR"],
            "focus_areas": ["accounts_receivable"],
            "suppress_ids": ["F999"],
            "context_block": "Client is in retail sector.",
            "generated_at": "2025-01-01T00:00:00",
        }
        refinement = profile.get_refinement()
        assert refinement.table_weights == {"orders": 0.8}
        assert "focus on AR" in refinement.query_hints
        assert refinement.context_block == "Client is in retail sector."

    def test_to_prompt_block_returns_context_block(self):
        """to_prompt_block() returns the context_block when it is non-empty."""
        ref = ClientRefinement(context_block="Inject this into the prompt.")
        assert ref.to_prompt_block() == "Inject this into the prompt."

    def test_to_prompt_block_returns_empty_string_when_no_context(self):
        """to_prompt_block() returns '' when context_block is empty."""
        ref = ClientRefinement()
        assert ref.to_prompt_block() == ""


# ---------------------------------------------------------------------------
# TestClientProfileEntityMap — is_entity_map_fresh()
# ---------------------------------------------------------------------------

class TestClientProfileEntityMap:
    """Tests for the entity_map freshness helper."""

    def test_no_cache_is_not_fresh(self):
        """A profile with no entity_map_cache is never considered fresh."""
        profile = ClientProfile.new("No Cache Corp")
        assert profile.is_entity_map_fresh() is False

    def test_cache_without_timestamp_is_not_fresh(self):
        """entity_map_cache set but entity_map_updated_at == None → not fresh."""
        profile = ClientProfile.new("Partial Cache Corp")
        profile.entity_map_cache = {"entities": {"orders": {}}}
        profile.entity_map_updated_at = None
        assert profile.is_entity_map_fresh() is False

    def test_recently_updated_cache_is_fresh(self):
        """A cache updated just now is fresh under the default 72-hour window."""
        profile = ClientProfile.new("Recent Corp")
        profile.entity_map_cache = {"entities": {"orders": {}}}
        profile.entity_map_updated_at = datetime.utcnow().isoformat()
        assert profile.is_entity_map_fresh() is True

    def test_old_cache_is_not_fresh(self):
        """A cache updated 100 hours ago is not fresh under the default 72-hour window."""
        from datetime import timedelta
        profile = ClientProfile.new("Stale Corp")
        profile.entity_map_cache = {"entities": {"orders": {}}}
        old_time = datetime.utcnow() - timedelta(hours=100)
        profile.entity_map_updated_at = old_time.isoformat()
        assert profile.is_entity_map_fresh() is False

    def test_custom_max_age_respected(self):
        """is_entity_map_fresh(max_age_hours=1) rejects a 2-hour-old cache."""
        from datetime import timedelta
        profile = ClientProfile.new("Tight TTL Corp")
        profile.entity_map_cache = {"entities": {}}
        two_hours_ago = datetime.utcnow() - timedelta(hours=2)
        profile.entity_map_updated_at = two_hours_ago.isoformat()
        assert profile.is_entity_map_fresh(max_age_hours=1) is False
        assert profile.is_entity_map_fresh(max_age_hours=3) is True


# ---------------------------------------------------------------------------
# TestGetProfileStoreSingleton — module-level singleton
# ---------------------------------------------------------------------------

class TestGetProfileStoreSingleton:
    """Tests for the get_profile_store() singleton factory."""

    def test_returns_profile_store_instance(self):
        """get_profile_store() always returns a ProfileStore."""
        from memory.profile_store import get_profile_store, ProfileStore
        store = get_profile_store()
        assert isinstance(store, ProfileStore)

    def test_same_instance_on_repeated_calls(self):
        """get_profile_store() returns the exact same object each time."""
        from memory.profile_store import get_profile_store
        a = get_profile_store()
        b = get_profile_store()
        assert a is b


# ---------------------------------------------------------------------------
# TestProfileStoreFallbackOnDbFailure
# ---------------------------------------------------------------------------

class TestProfileStoreFallbackOnDbFailure:
    """Ensures ProfileStore falls back to file storage when DB pool fails."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_db_failure_falls_back_to_file(self):
        """If the DB pool raises on creation, _use_db is flipped to False."""
        from memory.profile_store import ProfileStore
        store = ProfileStore.__new__(ProfileStore)
        store._db_url = "postgresql://bad:bad@localhost:9999/nonexistent"
        store._pool = None
        store._use_db = True

        # _get_pool should catch the connection error and disable DB
        pool = self._run(store._get_pool())
        assert pool is None
        assert store._use_db is False


# ---------------------------------------------------------------------------
# TestClientProfileExtraFields — additional ClientProfile behaviours
# ---------------------------------------------------------------------------

class TestClientProfileExtraFields:
    """Tests for fields and methods not yet covered by the main suites."""

    def test_false_positives_list_operations(self):
        """false_positives starts empty and accepts string entries."""
        profile = ClientProfile.new("FP Corp")
        assert profile.false_positives == []
        profile.false_positives.append("F100")
        profile.false_positives.append("F200")
        assert len(profile.false_positives) == 2
        assert "F100" in profile.false_positives

    def test_preferred_queries_store_dicts(self):
        """preferred_queries accepts dict entries and preserves order."""
        profile = ClientProfile.new("Query Corp")
        q1 = {"sql": "SELECT COUNT(*) FROM orders", "label": "order_count"}
        q2 = {"sql": "SELECT SUM(amount) FROM invoices", "label": "invoice_total"}
        profile.preferred_queries.append(q1)
        profile.preferred_queries.append(q2)
        assert len(profile.preferred_queries) == 2
        assert profile.preferred_queries[0]["label"] == "order_count"
        assert profile.preferred_queries[1]["label"] == "invoice_total"

    def test_focus_tables_list_append_and_contains(self):
        """focus_tables is a mutable list that supports contains-checks."""
        profile = ClientProfile.new("Focus Corp")
        assert profile.focus_tables == []
        profile.focus_tables.extend(["orders", "invoices", "customers"])
        assert "invoices" in profile.focus_tables
        assert len(profile.focus_tables) == 3

    def test_table_weights_mapping(self):
        """table_weights stores float values keyed by table name."""
        profile = ClientProfile.new("Weight Corp")
        profile.table_weights["orders"] = 0.9
        profile.table_weights["customers"] = 0.5
        assert profile.table_weights["orders"] == 0.9
        assert profile.table_weights["customers"] == 0.5

    def test_baseline_history_accepts_lists(self):
        """baseline_history maps a label to a list of KPI data-points."""
        profile = ClientProfile.new("Baseline Corp")
        profile.baseline_history["revenue"] = [
            {"period": "2025-01", "value": "1000000"},
            {"period": "2025-02", "value": "1050000"},
        ]
        assert len(profile.baseline_history["revenue"]) == 2
        assert profile.baseline_history["revenue"][1]["period"] == "2025-02"

    def test_resolved_findings_separate_from_known(self):
        """Resolving a finding moves it from known_findings to resolved_findings."""
        profile = ClientProfile.new("Resolved Corp")
        finding = {
            "id": "F001",
            "title": "Stale invoices",
            "severity": "LOW",
            "agent": "sentinel",
            "first_seen": "2025-01-01T00:00:00",
            "last_seen": "2025-01-10T00:00:00",
            "runs_open": 3,
        }
        profile.known_findings["F001"] = finding
        profile.resolved_findings["F001"] = profile.known_findings.pop("F001")

        assert "F001" not in profile.known_findings
        assert "F001" in profile.resolved_findings
        assert profile.resolved_findings["F001"]["severity"] == "LOW"

    def test_from_dict_ignores_unknown_keys(self):
        """ClientProfile.from_dict silently ignores keys not in __dataclass_fields__."""
        d = ClientProfile.new("Safe Corp").to_dict()
        d["unknown_future_field"] = "ignored"
        restored = ClientProfile.from_dict(d)
        assert restored.client_name == "Safe Corp"
        assert not hasattr(restored, "unknown_future_field")

    def test_last_run_date_none_by_default(self):
        """A new profile has last_run_date == None."""
        profile = ClientProfile.new("No Run Corp")
        assert profile.last_run_date is None

    def test_run_history_stores_summaries(self):
        """run_history accumulates per-run summary dicts."""
        profile = ClientProfile.new("History Corp")
        for i in range(3):
            profile.run_history.append({"run_id": f"job_{i}", "status": "success"})
        profile.run_count = 3
        assert profile.run_count == 3
        assert len(profile.run_history) == 3
        assert profile.run_history[2]["run_id"] == "job_2"


# ---------------------------------------------------------------------------
# TestFindingRecordAndKPIDataPoint — auxiliary dataclasses
# ---------------------------------------------------------------------------

class TestFindingRecordAndKPIDataPoint:
    """Smoke tests for FindingRecord and KPIDataPoint dataclasses."""

    def test_finding_record_default_runs_open(self):
        """FindingRecord defaults runs_open to 1."""
        from memory.client_profile import FindingRecord
        fr = FindingRecord(
            id="F010",
            title="Late payments",
            severity="HIGH",
            agent="analyst",
            first_seen="2025-03-01T00:00:00",
            last_seen="2025-03-01T00:00:00",
        )
        assert fr.runs_open == 1
        assert fr.severity == "HIGH"

    def test_kpi_data_point_nullable_numeric(self):
        """KPIDataPoint accepts None for numeric_value."""
        from memory.client_profile import KPIDataPoint
        kpi = KPIDataPoint(
            period="2025-Q1",
            label="Revenue",
            value="N/A",
            numeric_value=None,
            run_date="2025-04-01T00:00:00",
        )
        assert kpi.numeric_value is None
        assert kpi.value == "N/A"


# ---------------------------------------------------------------------------
# TestClientRefinementEdgeCases — additional ClientRefinement behaviours
# ---------------------------------------------------------------------------

class TestClientRefinementEdgeCases:
    """Edge cases for ClientRefinement not covered by TestClientRefinement."""

    def test_suppress_ids_populated(self):
        """suppress_ids holds a list of finding IDs to ignore on next run."""
        ref = ClientRefinement(suppress_ids=["F001", "F002", "F003"])
        assert len(ref.suppress_ids) == 3
        assert "F002" in ref.suppress_ids

    def test_generated_at_stored(self):
        """generated_at preserves the ISO timestamp."""
        ts = "2025-06-15T12:00:00"
        ref = ClientRefinement(generated_at=ts)
        assert ref.generated_at == ts

    def test_multiple_query_hints(self):
        """query_hints accepts multiple strings."""
        ref = ClientRefinement(query_hints=["focus on AR", "ignore test accounts", "use EUR"])
        assert len(ref.query_hints) == 3
        assert "use EUR" in ref.query_hints

    def test_get_refinement_roundtrip_via_to_dict(self):
        """A ClientRefinement stored as dict on a profile is reconstructed correctly."""
        import dataclasses
        profile = ClientProfile.new("Full Refinement Corp")
        original_ref = ClientRefinement(
            table_weights={"invoices": 0.95},
            query_hints=["check duplicates"],
            focus_areas=["billing"],
            suppress_ids=["F005"],
            context_block="Focus on billing anomalies.",
            generated_at="2025-07-01T00:00:00",
        )
        profile.refinement = dataclasses.asdict(original_ref)
        restored = profile.get_refinement()
        assert restored.table_weights == {"invoices": 0.95}
        assert restored.focus_areas == ["billing"]
        assert restored.suppress_ids == ["F005"]
        assert restored.generated_at == "2025-07-01T00:00:00"


# ---------------------------------------------------------------------------
# TestDetectSchemaDriftEdgeCases — additional drift scenarios
# ---------------------------------------------------------------------------

class TestDetectSchemaDriftEdgeCases:
    """Additional edge cases for detect_schema_drift not covered above."""

    def test_new_tables_only_triggers_drift(self):
        """Only additions (no removals) above the 10% threshold counts as drift."""
        # 5 base tables + 1 added = 20% → drift
        base = {"entities": {f"t{i}": {} for i in range(5)}}
        extended = {"entities": {f"t{i}": {} for i in range(6)}}
        assert detect_schema_drift(base, extended) is True

    def test_new_tables_below_threshold_no_drift(self):
        """Adding 1 table to a 20-table map (5%) does not trigger drift."""
        base = {"entities": {f"t{i}": {} for i in range(20)}}
        extended = {"entities": {f"t{i}": {} for i in range(21)}}
        assert detect_schema_drift(base, extended) is False

    def test_completely_different_schemas_is_drift(self):
        """Two fully disjoint entity sets produce maximum drift."""
        base = {"entities": {"a": {}, "b": {}, "c": {}}}
        new = {"entities": {"x": {}, "y": {}, "z": {}}}
        # 3 removed + 3 added = 6 / 3 = 200% drift
        assert detect_schema_drift(base, new) is True

    def test_single_table_cached_any_change_is_drift(self):
        """With a single cached table, removing it is 100% drift."""
        base = {"entities": {"only_table": {}}}
        reduced = {"entities": {}}
        assert detect_schema_drift(base, reduced) is True


# ---------------------------------------------------------------------------
# TestProfileStoreWithProfile — context manager
# ---------------------------------------------------------------------------

class TestProfileStoreWithProfile:
    """Tests for the with_profile() async context manager."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_with_profile_creates_and_auto_saves(self):
        """with_profile() creates a new profile, yields it, and auto-saves on exit."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        async def _use():
            async with store.with_profile("Context Corp") as profile:
                profile.run_count = 42
                profile.industry_inferred = "finance"

        self._run(_use())

        loaded = self._run(store.load("Context Corp"))
        assert loaded is not None
        assert loaded.run_count == 42
        assert loaded.industry_inferred == "finance"

    def test_with_profile_loads_existing_and_auto_saves(self):
        """with_profile() loads an existing profile and persists mutations."""
        tmp = _make_tmp_dir()
        store = _tmp_store(tmp)

        # Pre-populate a profile
        pre = ClientProfile.new("Existing Context Corp")
        pre.run_count = 5
        self._run(store.save(pre))

        async def _increment():
            async with store.with_profile("Existing Context Corp") as profile:
                profile.run_count += 1

        self._run(_increment())

        loaded = self._run(store.load("Existing Context Corp"))
        assert loaded is not None
        assert loaded.run_count == 6
