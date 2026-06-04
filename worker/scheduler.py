"""
ScheduleManager — dynamic per-client+vertical scheduling via redbeat.

Reads `ClientProfile.schedule_config` (list of VerticalSchedule dicts)
and creates / updates / deletes redbeat entries in Redis. Each entry
triggers `worker.tasks.run_vertical_schedule(client_id, vertical, ...)`
at the cron specified.

Redbeat is an optional dependency. When it isn't installed the manager
is a no-op (logs a warning) so the worker keeps running on the static
`celery_app.conf.beat_schedule`.

Refs: VAL-130 (L2)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────


@dataclass
class VerticalSchedule:
    """One (client, vertical) scheduling record."""
    vertical: str                        # "inventory", "financial"
    cron: str                            # "0 6 * * 1-5" (min hr dom mon dow)
    mode: str = "run"                    # "run" | "discovery" | "monitor"
    enabled: bool = True
    channels: list[str] = field(default_factory=list)      # ["email", "whatsapp", "webhook"]
    recipients: list[str] = field(default_factory=list)    # ["ops@example.com", "+5491100000000"]

    def to_dict(self) -> dict:
        return {
            "vertical": self.vertical,
            "cron": self.cron,
            "mode": self.mode,
            "enabled": self.enabled,
            "channels": list(self.channels),
            "recipients": list(self.recipients),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VerticalSchedule":
        return cls(
            vertical=data["vertical"],
            cron=data["cron"],
            mode=data.get("mode", "run"),
            enabled=bool(data.get("enabled", True)),
            channels=list(data.get("channels", [])),
            recipients=list(data.get("recipients", [])),
        )


# ─────────────────────────────────────────────────────────────────────
# Cron parsing
# ─────────────────────────────────────────────────────────────────────


def crontab_from_string(cron: str):
    """
    Parse a 5-field cron string into celery.schedules.crontab kwargs.

    Celery's crontab() accepts minute, hour, day_of_month, month_of_year,
    day_of_week. A plain string is not accepted — so we split ourselves.
    """
    parts = cron.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron must have 5 fields, got {len(parts)}: {cron!r}")
    from celery.schedules import crontab
    minute, hour, dom, month, dow = parts
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=dom,
        month_of_year=month,
        day_of_week=dow,
    )


# ─────────────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────────────


ENTRY_PREFIX = "valinor"
ENTRY_TASK = "worker.tasks.run_vertical_schedule"


def entry_name(client_id: str, vertical: str) -> str:
    return f"{ENTRY_PREFIX}:{client_id}:{vertical}"


class ScheduleManager:
    """
    Syncs a client's schedule_config (list of VerticalSchedule dicts)
    to redbeat entries in Redis.

    Injectable entry_factory for testing: replaces
    `redbeat.RedBeatSchedulerEntry` with a fake so tests don't need
    a Redis connection.
    """

    def __init__(
        self,
        celery_app=None,
        entry_factory=None,
    ):
        self._celery_app = celery_app
        self._entry_factory = entry_factory  # callable or None = lazy-redbeat

    def _get_entry_factory(self):
        if self._entry_factory is not None:
            return self._entry_factory
        try:
            from redbeat import RedBeatSchedulerEntry
            return RedBeatSchedulerEntry
        except ImportError as exc:
            raise RuntimeError(
                "celery-redbeat not installed — install it or inject entry_factory",
            ) from exc

    def sync_client_schedules(
        self,
        client_id: str,
        schedules: Iterable[VerticalSchedule | dict],
    ) -> list[str]:
        """
        Upsert redbeat entries for a client's schedules.

        Returns the list of entry names that were created/updated.
        Disabled schedules are removed.
        """
        factory = self._get_entry_factory()
        written: list[str] = []
        for item in schedules:
            sched = item if isinstance(item, VerticalSchedule) else VerticalSchedule.from_dict(item)
            name = entry_name(client_id, sched.vertical)
            if not sched.enabled:
                # Disabled → try to delete
                self._delete_entry(name, factory)
                continue
            schedule_obj = crontab_from_string(sched.cron)
            entry = factory(
                name=name,
                task=ENTRY_TASK,
                schedule=schedule_obj,
                args=[client_id, sched.vertical],
                kwargs={
                    "mode": sched.mode,
                    "channels": sched.channels,
                    "recipients": sched.recipients,
                },
                app=self._celery_app,
            )
            entry.save()
            written.append(name)
            logger.info("schedule.sync: upserted %s (cron=%r)", name, sched.cron)
        return written

    def _delete_entry(self, name: str, factory) -> bool:
        """Best-effort delete; returns True if something was removed."""
        try:
            entry = factory.from_key(name, app=self._celery_app)
        except Exception:
            return False
        try:
            entry.delete()
            logger.info("schedule.sync: deleted %s", name)
            return True
        except Exception as exc:
            logger.warning("schedule.sync: delete failed for %s: %s", name, exc)
            return False

    def list_entries(self) -> list[str]:
        """List redbeat entry names matching our prefix. Optional helper."""
        try:
            from redbeat.schedulers import get_redis
        except ImportError:
            return []
        try:
            redis = get_redis(self._celery_app)
            pattern = f"{ENTRY_PREFIX}:*"
            return sorted(k.decode() for k in redis.keys(pattern))
        except Exception as exc:
            logger.warning("schedule.list_entries: failed: %s", exc)
            return []


# ─────────────────────────────────────────────────────────────────────
# Convenience helper — syncs from a ClientProfile
# ─────────────────────────────────────────────────────────────────────


def sync_from_profile(
    client_id: str,
    profile_schedule_config: list[dict],
    celery_app=None,
    entry_factory=None,
) -> list[str]:
    """
    One-liner for the common path: read ClientProfile.schedule_config (a
    list of dicts) and sync it.
    """
    mgr = ScheduleManager(celery_app=celery_app, entry_factory=entry_factory)
    return mgr.sync_client_schedules(client_id, profile_schedule_config)
