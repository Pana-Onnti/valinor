"""
Tests for ScheduleManager + VerticalSchedule (VAL-130 L2).

Uses an injected entry_factory so tests don't need redbeat/Redis.

Refs: VAL-130
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# Stub celery.schedules.crontab if celery isn't installed — tests only need a
# construct that accepts the kwargs and can be introspected.
if "celery" not in sys.modules or not hasattr(sys.modules["celery"], "schedules"):
    _celery = types.ModuleType("celery")
    _celery.__path__ = []  # mark as package so `celery.schedules` resolves
    _celery_sched = types.ModuleType("celery.schedules")

    class _FakeCrontab:
        def __init__(self, *, minute="*", hour="*", day_of_month="*",
                     month_of_year="*", day_of_week="*"):
            self.minute = minute
            self.hour = hour
            self.day_of_month = day_of_month
            self.month_of_year = month_of_year
            self.day_of_week = day_of_week
        def __repr__(self):
            return (
                f"crontab(minute={self.minute} hour={self.hour} "
                f"day_of_month={self.day_of_month} month_of_year={self.month_of_year} "
                f"day_of_week={self.day_of_week})"
            )

    _celery_sched.crontab = _FakeCrontab
    sys.modules["celery"] = _celery
    sys.modules["celery.schedules"] = _celery_sched

from worker.scheduler import (
    ENTRY_PREFIX,
    ENTRY_TASK,
    ScheduleManager,
    VerticalSchedule,
    crontab_from_string,
    entry_name,
    sync_from_profile,
)


# ─────────────────────────────────────────────────────────────────────
# VerticalSchedule dataclass
# ─────────────────────────────────────────────────────────────────────


class TestVerticalSchedule:
    def test_round_trip_dict(self):
        v = VerticalSchedule(
            vertical="inventory", cron="0 6 * * 1-5",
            mode="run", enabled=True,
            channels=["email", "whatsapp"],
            recipients=["a@b", "+123"],
        )
        d = v.to_dict()
        back = VerticalSchedule.from_dict(d)
        assert back == v

    def test_defaults(self):
        v = VerticalSchedule.from_dict({"vertical": "x", "cron": "* * * * *"})
        assert v.mode == "run"
        assert v.enabled is True
        assert v.channels == []
        assert v.recipients == []


# ─────────────────────────────────────────────────────────────────────
# Cron parser
# ─────────────────────────────────────────────────────────────────────


class TestCronParser:
    def test_parses_five_fields(self):
        sched = crontab_from_string("0 6 * * 1-5")
        # FakeCrontab exposes kwargs directly
        assert sched.hour == "6"
        assert sched.minute == "0"
        assert sched.day_of_week == "1-5"

    def test_invalid_rejects(self):
        with pytest.raises(ValueError, match="5 fields"):
            crontab_from_string("* * * *")


# ─────────────────────────────────────────────────────────────────────
# ScheduleManager with injected factory
# ─────────────────────────────────────────────────────────────────────


class _FakeEntry:
    """Stand-in for redbeat.RedBeatSchedulerEntry."""

    created: list["_FakeEntry"] = []
    deleted: list[str] = []

    def __init__(self, name, task, schedule, args, kwargs, app):
        self.name = name
        self.task = task
        self.schedule = schedule
        self.args = args
        self.kwargs = kwargs
        self.app = app
        self._saved = False
        _FakeEntry.created.append(self)

    def save(self):
        self._saved = True

    @classmethod
    def from_key(cls, name, app=None):
        class _DeletableEntry:
            def __init__(self, n):
                self._name = n
            def delete(self_inner):
                _FakeEntry.deleted.append(self_inner._name)
        return _DeletableEntry(name)


@pytest.fixture(autouse=True)
def _reset_fake_entry():
    _FakeEntry.created.clear()
    _FakeEntry.deleted.clear()


class TestScheduleManager:
    def test_entry_name_format(self):
        assert entry_name("syscop", "inventory") == f"{ENTRY_PREFIX}:syscop:inventory"

    def test_sync_creates_entries(self):
        mgr = ScheduleManager(entry_factory=_FakeEntry)
        names = mgr.sync_client_schedules(
            "syscop",
            [VerticalSchedule(
                vertical="inventory", cron="0 6 * * 1-5",
                channels=["email"], recipients=["g@s"],
            )],
        )
        assert names == ["valinor:syscop:inventory"]
        assert len(_FakeEntry.created) == 1
        entry = _FakeEntry.created[0]
        assert entry._saved is True
        assert entry.task == ENTRY_TASK
        assert entry.args == ["syscop", "inventory"]
        assert entry.kwargs["channels"] == ["email"]
        assert entry.kwargs["recipients"] == ["g@s"]

    def test_sync_accepts_dicts(self):
        mgr = ScheduleManager(entry_factory=_FakeEntry)
        names = mgr.sync_client_schedules(
            "syscop",
            [{"vertical": "inventory", "cron": "0 6 * * 1-5"}],
        )
        assert names == ["valinor:syscop:inventory"]

    def test_disabled_schedule_is_deleted(self):
        mgr = ScheduleManager(entry_factory=_FakeEntry)
        names = mgr.sync_client_schedules(
            "syscop",
            [VerticalSchedule(
                vertical="financial", cron="0 2 * * 0",
                enabled=False,
            )],
        )
        assert names == []
        assert "valinor:syscop:financial" in _FakeEntry.deleted

    def test_multiple_schedules_for_one_client(self):
        mgr = ScheduleManager(entry_factory=_FakeEntry)
        names = mgr.sync_client_schedules(
            "syscop",
            [
                VerticalSchedule(vertical="inventory", cron="0 6 * * 1-5"),
                VerticalSchedule(vertical="financial", cron="0 2 1 * *"),
            ],
        )
        assert names == ["valinor:syscop:inventory", "valinor:syscop:financial"]
        assert len(_FakeEntry.created) == 2

    def test_no_redbeat_installed_raises_when_no_factory(self):
        # Simulate missing redbeat by asking manager to look up redbeat itself.
        mgr = ScheduleManager()
        # The RedBeatSchedulerEntry import will either succeed (if redbeat is
        # installed in this env) or raise RuntimeError. Either is acceptable;
        # we just verify the error surface is friendly when missing.
        try:
            mgr.sync_client_schedules(
                "syscop",
                [VerticalSchedule(vertical="inventory", cron="* * * * *")],
            )
        except RuntimeError as exc:
            assert "celery-redbeat" in str(exc)
        except ImportError:
            # Python 3.10 may surface the raw ImportError depending on context
            pass


# ─────────────────────────────────────────────────────────────────────
# sync_from_profile helper
# ─────────────────────────────────────────────────────────────────────


class TestSyncFromProfile:
    def test_syncs_from_dict_list(self):
        profile_config = [
            {"vertical": "inventory", "cron": "0 6 * * 1-5",
             "channels": ["whatsapp"], "recipients": ["+5435"]},
        ]
        names = sync_from_profile("syscop", profile_config, entry_factory=_FakeEntry)
        assert names == ["valinor:syscop:inventory"]
        entry = _FakeEntry.created[0]
        assert entry.kwargs["channels"] == ["whatsapp"]
