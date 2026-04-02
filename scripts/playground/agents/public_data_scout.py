"""
Playground Swarm — Agent 1: Public Data Scout.

Tier: hunter — fetches real public datasets from World Bank and SEC EDGAR.
Falls back to mock data generation if external APIs are unreachable.
"""

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

# Countries for World Bank queries
WORLD_BANK_COUNTRIES = ["US", "GB", "DE", "FR", "JP", "CN", "BR", "IN", "MX", "AR"]

WORLD_BANK_INDICATORS = {
    "NY.GDP.MKTP.CD": "gdp_current_usd",
    "FP.CPI.TOTL.ZG": "inflation_pct",
}

SEC_EDGAR_URL = (
    "https://efts.sec.gov/LATEST/search-index"
    '?q="annual report"'
    "&dateRange=custom&startdt=2024-01-01&enddt=2024-12-31&forms=10-K"
)


class PublicDataScoutAgent(PlaygroundAgent):
    """Fetches real public datasets from World Bank API and SEC EDGAR."""

    def __init__(self) -> None:
        self.name = "public_data_scout"
        self.tier = "hunter"
        super().__init__()

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        datasets: List[DatasetRecord] = []
        errors: List[str] = []

        # Source 1: World Bank
        try:
            ds = await self._fetch_world_bank(ctx)
            if ds:
                datasets.append(ds)
                await ctx.generated_datasets.put(ds)
        except Exception as exc:
            msg = f"World Bank fetch failed: {exc}"
            self.logger.warning(msg)
            errors.append(msg)

        # Source 2: SEC EDGAR
        try:
            ds = await self._fetch_sec_edgar(ctx)
            if ds:
                datasets.append(ds)
                await ctx.generated_datasets.put(ds)
        except Exception as exc:
            msg = f"SEC EDGAR fetch failed: {exc}"
            self.logger.warning(msg)
            errors.append(msg)

        # Fallback: mock public data if both sources failed
        if not datasets:
            self.logger.warning("All API sources failed — generating mock public data")
            try:
                ds = self._generate_mock_data(ctx)
                datasets.append(ds)
                await ctx.generated_datasets.put(ds)
            except Exception as exc:
                msg = f"Mock data generation failed: {exc}"
                self.logger.error(msg)
                errors.append(msg)

        self._datasets_produced += len(datasets)
        return AgentResult(
            agent_name=self.name,
            success=len(datasets) > 0,
            datasets=datasets,
            errors=errors if errors else None,
            stats={"datasets_produced": len(datasets)},
        )

    # ── World Bank ────────────────────────────────────────────────────

    async def _fetch_world_bank(self, ctx: PlaygroundContext) -> Optional[DatasetRecord]:
        try:
            import aiohttp
        except ImportError:
            self.logger.warning("aiohttp not installed — skipping World Bank")
            return None

        db_path = ctx.datasets_dir / "real" / "world_bank_macro.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS macro_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_code TEXT NOT NULL,
                indicator_code TEXT NOT NULL,
                indicator_name TEXT,
                year INTEGER,
                value REAL,
                fetched_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM macro_indicators")

        rows_inserted = 0
        now = datetime.utcnow().isoformat()

        async with aiohttp.ClientSession() as session:
            for country in WORLD_BANK_COUNTRIES:
                for indicator_code, indicator_name in WORLD_BANK_INDICATORS.items():
                    url = (
                        f"http://api.worldbank.org/v2/country/{country}"
                        f"/indicator/{indicator_code}?format=json&per_page=50"
                    )
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            if resp.status != 200:
                                self.logger.warning(
                                    "World Bank %s/%s returned %d", country, indicator_code, resp.status
                                )
                                continue
                            payload = await resp.json(content_type=None)
                            if not payload or len(payload) < 2 or not payload[1]:
                                continue
                            for entry in payload[1]:
                                value = entry.get("value")
                                year = entry.get("date")
                                if value is not None and year is not None:
                                    conn.execute(
                                        "INSERT INTO macro_indicators "
                                        "(country_code, indicator_code, indicator_name, year, value, fetched_at) "
                                        "VALUES (?, ?, ?, ?, ?, ?)",
                                        (country, indicator_code, indicator_name, int(year), float(value), now),
                                    )
                                    rows_inserted += 1
                    except asyncio.TimeoutError:
                        self.logger.warning("Timeout fetching World Bank %s/%s", country, indicator_code)
                    except Exception as exc:
                        self.logger.warning("Error fetching World Bank %s/%s: %s", country, indicator_code, exc)

        conn.commit()
        conn.close()

        if rows_inserted == 0:
            return None

        self.logger.info("World Bank: inserted %d rows", rows_inserted)
        return DatasetRecord(
            name="world_bank_macro",
            path=str(db_path),
            source_agent=self.name,
            tier=self.tier,
            created_at=now,
            row_counts={"macro_indicators": rows_inserted},
            tags=["real", "macro", "world_bank", "gdp", "inflation"],
        )

    # ── SEC EDGAR ─────────────────────────────────────────────────────

    async def _fetch_sec_edgar(self, ctx: PlaygroundContext) -> Optional[DatasetRecord]:
        try:
            import aiohttp
        except ImportError:
            self.logger.warning("aiohttp not installed — skipping SEC EDGAR")
            return None

        db_path = ctx.datasets_dir / "real" / "sec_edgar_filings.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT,
                cik TEXT,
                form_type TEXT,
                filed_date TEXT,
                accession_number TEXT,
                file_url TEXT,
                fetched_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM filings")

        rows_inserted = 0
        now = datetime.utcnow().isoformat()

        headers = {
            "User-Agent": "ValinorSaaS/1.0 playground-agent research@delta4c.com",
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            try:
                async with session.get(SEC_EDGAR_URL, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        self.logger.warning("SEC EDGAR returned %d", resp.status)
                        return None
                    payload = await resp.json(content_type=None)
                    hits = payload.get("hits", {}).get("hits", [])
                    if not hits:
                        # Try alternative response structure
                        hits = payload.get("filings", []) if isinstance(payload, dict) else []

                    for hit in hits[:100]:
                        source = hit.get("_source", hit)
                        conn.execute(
                            "INSERT INTO filings "
                            "(company_name, cik, form_type, filed_date, accession_number, file_url, fetched_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                source.get("company_name", source.get("entity_name", "")),
                                source.get("cik", ""),
                                source.get("form_type", source.get("file_type", "10-K")),
                                source.get("file_date", source.get("filed_date", "")),
                                source.get("accession_no", source.get("accession_number", "")),
                                source.get("file_url", ""),
                                now,
                            ),
                        )
                        rows_inserted += 1
            except asyncio.TimeoutError:
                self.logger.warning("Timeout fetching SEC EDGAR")
            except Exception as exc:
                self.logger.warning("Error fetching SEC EDGAR: %s", exc)

        conn.commit()
        conn.close()

        if rows_inserted == 0:
            return None

        self.logger.info("SEC EDGAR: inserted %d filings", rows_inserted)
        return DatasetRecord(
            name="sec_edgar_filings",
            path=str(db_path),
            source_agent=self.name,
            tier=self.tier,
            created_at=now,
            row_counts={"filings": rows_inserted},
            tags=["real", "finance", "sec", "10-K", "edgar"],
        )

    # ── Mock fallback ─────────────────────────────────────────────────

    def _generate_mock_data(self, ctx: PlaygroundContext) -> DatasetRecord:
        import random

        db_path = ctx.datasets_dir / "real" / "mock_public_data.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path))
        now = datetime.utcnow().isoformat()

        # Mock GDP data
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS macro_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_code TEXT NOT NULL,
                indicator_code TEXT NOT NULL,
                indicator_name TEXT,
                year INTEGER,
                value REAL,
                fetched_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM macro_indicators")

        rows = 0
        for country in WORLD_BANK_COUNTRIES:
            base_gdp = random.uniform(1e11, 2e13)
            for year in range(2015, 2025):
                gdp = base_gdp * (1 + random.uniform(-0.03, 0.05)) ** (year - 2015)
                inflation = random.uniform(0.5, 12.0)
                conn.execute(
                    "INSERT INTO macro_indicators "
                    "(country_code, indicator_code, indicator_name, year, value, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (country, "NY.GDP.MKTP.CD", "gdp_current_usd", year, gdp, now),
                )
                conn.execute(
                    "INSERT INTO macro_indicators "
                    "(country_code, indicator_code, indicator_name, year, value, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (country, "FP.CPI.TOTL.ZG", "inflation_pct", year, inflation, now),
                )
                rows += 2

        # Mock filings
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT,
                cik TEXT,
                form_type TEXT,
                filed_date TEXT,
                accession_number TEXT,
                file_url TEXT,
                fetched_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM filings")

        mock_companies = [
            ("Acme Corp", "0001234567"),
            ("Globex Inc", "0009876543"),
            ("Initech LLC", "0005551234"),
            ("Umbrella Corp", "0007778899"),
            ("Soylent Industries", "0003334455"),
        ]
        filings_count = 0
        for name, cik in mock_companies:
            for month in range(1, 13):
                conn.execute(
                    "INSERT INTO filings "
                    "(company_name, cik, form_type, filed_date, accession_number, file_url, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        cik,
                        "10-K" if month == 3 else "10-Q",
                        f"2024-{month:02d}-15",
                        f"{cik}-24-{month:06d}",
                        f"https://mock.sec.gov/{cik}/{month}",
                        now,
                    ),
                )
                filings_count += 1

        conn.commit()
        conn.close()

        self.logger.info("Mock public data: %d indicator rows, %d filings", rows, filings_count)
        return DatasetRecord(
            name="mock_public_data",
            path=str(db_path),
            source_agent=self.name,
            tier=self.tier,
            created_at=now,
            row_counts={"macro_indicators": rows, "filings": filings_count},
            tags=["real", "mock", "fallback", "gdp", "sec"],
            metadata={"mock": True},
        )
