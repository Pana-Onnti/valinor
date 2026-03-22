"""
ProfileStore — persist ClientProfile to PostgreSQL or local file fallback.
Uses the same backend as MetadataStorage (Docker PostgreSQL on port 5450).
"""
from __future__ import annotations
import os
import json
import contextlib
from typing import Optional
from datetime import datetime
from pathlib import Path

import structlog

from .client_profile import ClientProfile

logger = structlog.get_logger()

_LOCAL_DIR = Path("/tmp/valinor_profiles")
_LOCAL_DIR.mkdir(parents=True, exist_ok=True)


class ProfileStore:
    """
    Loads and saves ClientProfile objects.
    Primary backend: PostgreSQL (asyncpg).
    Fallback: local JSON files.
    """

    def __init__(self):
        db_url = os.getenv("DATABASE_URL", "")
        # Normalize: some envs use 'valinor_saas' but DB is 'valinor_metadata'
        if db_url and "valinor_saas" in db_url:
            db_url = db_url.replace("valinor_saas", "valinor_metadata")
        self._db_url = db_url
        self._pool = None
        self._use_db = bool(self._db_url)

    # ── Pool management ───────────────────────────────────────────────────────

    async def _get_pool(self):
        if self._pool is None and self._use_db:
            try:
                import asyncpg
                self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=3)
                await self._ensure_table()
            except Exception as e:
                logger.warning("ProfileStore: DB pool failed, using local files", error=str(e))
                self._use_db = False
                self._pool = None
        return self._pool

    async def _ensure_table(self):
        """Create client_profiles table if it doesn't exist."""
        pool = self._pool
        if not pool:
            return
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS client_profiles (
                    client_name TEXT PRIMARY KEY,
                    profile     JSONB NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)

    # ── Public API ────────────────────────────────────────────────────────────

    async def load(self, client_name: str) -> Optional[ClientProfile]:
        """Load profile. Returns None if client has no profile yet.
        Tries DB first, falls back to local file."""
        try:
            pool = await self._get_pool()
            if pool:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT profile FROM client_profiles WHERE client_name = $1",
                        client_name
                    )
                    if row:
                        data = json.loads(row["profile"])
                        logger.info("ProfileStore: loaded from DB", client=client_name)
                        return ClientProfile.from_dict(data)
                # Not found in DB — try local file as fallback
            path = _LOCAL_DIR / f"{client_name}.json"
            if path.exists():
                data = json.loads(path.read_text())
                logger.info("ProfileStore: loaded from file (fallback)", client=client_name)
                return ClientProfile.from_dict(data)
        except Exception as e:
            logger.error("ProfileStore.load failed", client=client_name, error=str(e))
        return None

    async def save(self, profile: ClientProfile) -> bool:
        """Upsert profile. Always writes to local file as backup, then attempts PostgreSQL upsert."""
        try:
            profile.updated_at = datetime.utcnow().isoformat()
            data = json.dumps(profile.to_dict())

            # 1. Always persist to local file first (backup / fallback).
            path = _LOCAL_DIR / f"{profile.client_name}.json"
            path.write_text(data)
            logger.info("ProfileStore: saved to file", client=profile.client_name)

            # 2. Best-effort upsert to PostgreSQL — never raise on failure.
            try:
                pool = await self._get_pool()
                if pool:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO client_profiles (client_name, profile, updated_at)
                            VALUES ($1, $2, NOW())
                            ON CONFLICT (client_name) DO UPDATE
                                SET profile = EXCLUDED.profile, updated_at = NOW()
                            """,
                            profile.client_name,
                            data,
                        )
                    logger.info("ProfileStore: saved to DB", client=profile.client_name)
            except Exception as db_exc:
                logger.warning(
                    "ProfileStore: DB upsert failed, file backup retained",
                    client=profile.client_name,
                    error=str(db_exc),
                )

            return True
        except Exception as e:
            logger.error("ProfileStore.save failed", client=profile.client_name, error=str(e))
            return False

    async def load_or_create(self, client_name: str) -> ClientProfile:
        """Load existing profile or create a new blank one."""
        existing = await self.load(client_name)
        if existing:
            return existing
        return ClientProfile.new(client_name)

    @contextlib.asynccontextmanager
    async def with_profile(self, client_name: str):
        """
        Async context manager that loads a profile, yields it, and auto-saves on exit.

        Usage:
            async with store.with_profile("client_name") as profile:
                profile.run_count += 1
                # auto-saved on exit
        """
        profile = await self.load_or_create(client_name)
        try:
            yield profile
        finally:
            await self.save(profile)

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None


def detect_schema_drift(cached_entity_map: dict, new_entity_map: dict) -> bool:
    """
    Returns True if the schema has drifted enough to invalidate the cache.
    Drift = more than 10% difference in entity count, or new entities detected.
    """
    cached_tables = set(cached_entity_map.get("entities", {}).keys())
    new_tables = set(new_entity_map.get("entities", {}).keys())

    if not cached_tables:
        return True

    added = new_tables - cached_tables
    removed = cached_tables - new_tables
    drift_ratio = (len(added) + len(removed)) / len(cached_tables)

    return drift_ratio > 0.10  # >10% change = drift


# Module-level singleton
_store: Optional[ProfileStore] = None


def get_profile_store() -> ProfileStore:
    global _store
    if _store is None:
        _store = ProfileStore()
    return _store
