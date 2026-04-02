"""
Playground Swarm — Agent 9: Pipeline Smoker.

Continuous agent that picks random datasets, submits them to the Valinor
analysis API, polls for completion, and records pass/fail smoke reports.

Strategy: loads each SQLite dataset into a temporary PostgreSQL schema
inside the Gloria database so the Valinor pipeline can query it normally.
"""

import asyncio
import random
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import aiohttp

from scripts.playground.agents.base import (
    AgentResult,
    DatasetRecord,
    PlaygroundAgent,
    PlaygroundContext,
)

POLL_INTERVAL = 10     # seconds between status polls
JOB_TIMEOUT = 300      # seconds before we consider a job stuck


class PipelineSmokerAgent(PlaygroundAgent):
    """Smoke-tests the analysis pipeline against random datasets."""

    name = "pipeline_smoker"
    tier = "tester"
    interval = 30

    def __init__(self) -> None:
        super().__init__()
        self._tested: Set[str] = set()
        self._total_tests = 0
        self._passed = 0
        self._failed = 0
        self._times: List[float] = []

    async def run(self, ctx: PlaygroundContext) -> AgentResult:
        errors: List[str] = []

        # Find all .db files under datasets/
        db_files = list(ctx.datasets_dir.rglob("*.db"))
        # Filter out already-tested
        untested = [p for p in db_files if str(p) not in self._tested]

        if not untested:
            self.logger.info("All datasets already tested (%d total).", len(self._tested))
            return AgentResult(
                self.name,
                success=True,
                stats=self._stats(),
            )

        db_path = random.choice(untested)
        self._tested.add(str(db_path))
        db_name = db_path.stem

        self.logger.info("Smoke-testing dataset: %s", db_name)

        report: Dict[str, Any] = {
            "dataset_name": db_name,
            "dataset_path": str(db_path),
            "timestamp": datetime.utcnow().isoformat(),
        }

        cleanup_schema = None
        try:
            request_body = self._build_request(db_path, db_name, ctx)
            cleanup_schema = request_body.pop("_cleanup_schema", None)
            async with aiohttp.ClientSession() as session:
                # Submit analysis
                job_id = await self._submit_job(session, ctx.api_base_url, request_body)
                report["job_id"] = job_id

                # Poll for completion
                t0 = time.monotonic()
                status, details = await self._poll_job(session, ctx, job_id)
                elapsed = time.monotonic() - t0

                report["status"] = status
                report["execution_time"] = round(elapsed, 2)

                passed = False
                if status == "completed":
                    has_findings = bool(details.get("findings"))
                    report["has_findings"] = has_findings
                    passed = True
                elif status == "failed":
                    report["error"] = details.get("error", "unknown")
                    passed = False
                else:
                    # stuck / timeout
                    report["error"] = f"Job stuck or timed out (status={status})"
                    passed = False

                report["pass"] = passed
                self._total_tests += 1
                self._times.append(elapsed)
                if passed:
                    self._passed += 1
                else:
                    self._failed += 1

        except Exception as exc:
            msg = f"Smoke test error for {db_name}: {exc}"
            self.logger.error(msg)
            errors.append(msg)
            report["pass"] = False
            report["error"] = str(exc)
            self._total_tests += 1
            self._failed += 1
        finally:
            if cleanup_schema:
                self._cleanup_pg_schema(cleanup_schema, ctx)

        self._save_report(ctx, report, "smoke")
        self.logger.info(
            "Smoke result: %s — %s (%.1fs)",
            db_name,
            "PASS" if report.get("pass") else "FAIL",
            report.get("execution_time", 0),
        )

        return AgentResult(
            self.name,
            success=len(errors) == 0,
            errors=errors,
            stats=self._stats(),
        )

    # ── helpers ───────────────────────────────────────────────────────

    def _load_sqlite_to_postgres(
        self, db_path: Path, schema_name: str, ctx: PlaygroundContext
    ) -> None:
        """Load SQLite tables into a temporary PostgreSQL schema."""
        import pandas as pd
        from sqlalchemy import create_engine, text

        pg_url = (
            f"postgresql://{ctx.db_config['user']}:{ctx.db_config['password']}"
            f"@{ctx.db_config['host']}:{ctx.db_config['port']}/{ctx.db_config['name']}"
        )
        pg_engine = create_engine(pg_url)

        # Read all tables from SQLite
        sqlite_conn = sqlite3.connect(str(db_path))
        cursor = sqlite_conn.cursor()
        tables = [
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
            ).fetchall()
        ]

        if not tables:
            sqlite_conn.close()
            return

        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {schema_name}"))

        for table in tables:
            try:
                df = pd.read_sql_query(f"SELECT * FROM [{table}]", sqlite_conn)
                if df.empty:
                    continue
                df.to_sql(
                    table,
                    pg_engine,
                    schema=schema_name,
                    if_exists="replace",
                    index=False,
                )
            except Exception as e:
                self.logger.warning("Skip table %s: %s", table, e)

        sqlite_conn.close()
        pg_engine.dispose()

    def _cleanup_pg_schema(self, schema_name: str, ctx: PlaygroundContext) -> None:
        """Drop the temporary PostgreSQL schema."""
        try:
            from sqlalchemy import create_engine, text

            pg_url = (
                f"postgresql://{ctx.db_config['user']}:{ctx.db_config['password']}"
                f"@{ctx.db_config['host']}:{ctx.db_config['port']}/{ctx.db_config['name']}"
            )
            engine = create_engine(pg_url)
            with engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE"))
            engine.dispose()
        except Exception as e:
            self.logger.warning("Cleanup failed for schema %s: %s", schema_name, e)

    def _build_request(
        self, db_path: Path, db_name: str, ctx: PlaygroundContext
    ) -> Dict[str, Any]:
        # Sanitize schema name (postgres identifiers — avoid pg_ prefix, it's reserved)
        schema_name = f"play_{db_name[:40]}".replace("-", "_").replace(".", "_").lower()

        # Load SQLite data into a temp PG schema
        self._load_sqlite_to_postgres(db_path, schema_name, ctx)

        return {
            "client_name": f"play_{db_name[:90]}"[:100],
            "period": "2025",
            "db_config": {
                "host": ctx.db_config["host"],
                "port": ctx.db_config["port"],
                "name": ctx.db_config["name"],
                "type": "postgres",
                "user": ctx.db_config["user"],
                "password": ctx.db_config["password"],
            },
            "overrides": {"search_path": schema_name},
            "_cleanup_schema": schema_name,
        }

    @staticmethod
    async def _submit_job(
        session: aiohttp.ClientSession, base_url: str, body: Dict[str, Any]
    ) -> str:
        url = f"{base_url}/api/analyze"
        async with session.post(url, json=body) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["job_id"]

    async def _poll_job(
        self,
        session: aiohttp.ClientSession,
        ctx: PlaygroundContext,
        job_id: str,
    ) -> tuple:
        """Poll job status until completion or timeout. Returns (status, details)."""
        url = f"{ctx.api_base_url}/api/jobs/{job_id}/status"
        deadline = time.monotonic() + JOB_TIMEOUT

        while time.monotonic() < deadline:
            if ctx.stop_event.is_set():
                return ("cancelled", {})
            try:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    status = data.get("status", "unknown")
                    if status in ("completed", "failed"):
                        return (status, data)
            except Exception as exc:
                self.logger.warning("Poll error for job %s: %s", job_id, exc)

            await asyncio.sleep(POLL_INTERVAL)

        return ("timeout", {})

    def _stats(self) -> Dict[str, Any]:
        avg = sum(self._times) / len(self._times) if self._times else 0.0
        return {
            "total_tests": self._total_tests,
            "passed": self._passed,
            "failed": self._failed,
            "avg_time": round(avg, 2),
        }
