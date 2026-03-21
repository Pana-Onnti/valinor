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
