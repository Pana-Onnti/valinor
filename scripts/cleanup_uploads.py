#!/usr/bin/env python3
"""cleanup_uploads.py — Lifecycle cleanup for uploaded files.

Reads uploaded_files rows whose status is NOT already 'expired' and whose
uploaded_at is older than --max-age-days.  For each matching row it:

  1. Deletes the file from disk via StorageManager.delete_upload().
  2. Marks the DB row status='expired' and sets processed_at = now().

Designed to run:
  - via cron:        0 3 * * * python scripts/cleanup_uploads.py
  - via Celery beat: add a periodic task that calls this script or wraps the
                     logic in a Celery task.

Usage:
    python scripts/cleanup_uploads.py [--max-age-days N] [--dry-run]

Environment variables:
    DATABASE_URL  — PostgreSQL DSN (required)
    UPLOAD_DIR    — Base upload directory (optional, default /data/valinor/uploads)

Refs: VAL-89
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import api.services
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from api.services.storage_manager import StorageManager  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("cleanup_uploads")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        logger.error("DATABASE_URL environment variable is not set")
        sys.exit(1)
    return url


def run_cleanup(max_age_days: int = 30, dry_run: bool = False) -> dict:
    """Run the cleanup job.

    Args:
        max_age_days: Files uploaded more than this many days ago are expired.
        dry_run: If True, log what would be deleted but perform no mutations.

    Returns:
        Dict with keys ``found``, ``deleted_files``, ``marked_expired``,
        ``errors``.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)

    logger.info(
        "Starting cleanup — max_age_days=%d dry_run=%s cutoff=%s",
        max_age_days,
        dry_run,
        cutoff.isoformat(),
    )

    storage = StorageManager()
    db_url = _get_database_url()

    stats = {"found": 0, "deleted_files": 0, "marked_expired": 0, "errors": 0}

    conn = psycopg2.connect(db_url)
    try:
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Fetch rows eligible for expiry.
            # We skip rows that are already expired to make the query idempotent.
            cur.execute(
                """
                SELECT id, tenant_id, client_name, stored_path, original_filename, uploaded_at
                FROM uploaded_files
                WHERE status != 'expired'
                  AND uploaded_at < %(cutoff)s
                ORDER BY uploaded_at ASC
                """,
                {"cutoff": cutoff},
            )
            rows = cur.fetchall()
            stats["found"] = len(rows)
            logger.info("Found %d file(s) eligible for expiry", len(rows))

            for row in rows:
                row_id = str(row["id"])
                stored_path = row["stored_path"]
                tenant_id = str(row["tenant_id"])
                client_name = row["client_name"]
                original_filename = row["original_filename"]
                uploaded_at = row["uploaded_at"]

                logger.info(
                    "[%s] tenant=%s client=%s file=%s uploaded_at=%s",
                    row_id,
                    tenant_id,
                    client_name,
                    original_filename,
                    uploaded_at.isoformat() if uploaded_at else "unknown",
                )

                if dry_run:
                    logger.info("[DRY-RUN] Would delete file: %s", stored_path)
                    logger.info("[DRY-RUN] Would mark row %s as expired", row_id)
                    continue

                # Delete from disk
                try:
                    deleted = storage.delete_upload(stored_path)
                    if deleted:
                        stats["deleted_files"] += 1
                        logger.info("Deleted file from disk: %s", stored_path)
                    else:
                        logger.warning(
                            "File not found on disk (already removed?): %s", stored_path
                        )
                except Exception as exc:
                    logger.error(
                        "Failed to delete file %s: %s", stored_path, exc
                    )
                    stats["errors"] += 1
                    # Continue processing remaining rows even if one fails

                # Mark DB row as expired regardless of whether the file existed
                # (avoids re-trying a missing file on every run)
                try:
                    cur.execute(
                        """
                        UPDATE uploaded_files
                        SET status = 'expired',
                            processed_at = now()
                        WHERE id = %(id)s
                        """,
                        {"id": row_id},
                    )
                    stats["marked_expired"] += 1
                except Exception as exc:
                    logger.error(
                        "Failed to mark row %s as expired: %s", row_id, exc
                    )
                    stats["errors"] += 1

        if not dry_run:
            conn.commit()
            logger.info("Transaction committed")
        else:
            conn.rollback()
            logger.info("[DRY-RUN] Transaction rolled back — no changes made")

    except Exception as exc:
        conn.rollback()
        logger.error("Unexpected error, transaction rolled back: %s", exc)
        stats["errors"] += 1
        raise
    finally:
        conn.close()

    logger.info(
        "Cleanup complete — found=%d deleted_files=%d marked_expired=%d errors=%d",
        stats["found"],
        stats["deleted_files"],
        stats["marked_expired"],
        stats["errors"],
    )
    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean up expired uploaded files from disk and database.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=30,
        metavar="N",
        help="Delete files uploaded more than N days ago (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log what would be deleted without making any changes",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    stats = run_cleanup(max_age_days=args.max_age_days, dry_run=args.dry_run)

    if stats["errors"] > 0:
        logger.warning("Cleanup finished with %d error(s)", stats["errors"])
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
