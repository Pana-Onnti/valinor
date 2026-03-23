"""Manages file storage for uploaded CSV/Excel files.

Provides tenant-isolated, path-traversal-safe file storage under
a configurable base directory. Files are stored with 600 permissions,
directories with 700, and are never served statically via HTTP.

Refs: VAL-89
"""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = "/data/valinor/uploads"


class PathTraversalError(ValueError):
    """Raised when a path component contains '..' or other traversal attempts."""


def _validate_component(component: str, label: str = "component") -> str:
    """Validate a single path component against traversal and empty strings."""
    if not component:
        raise ValueError(f"{label} must not be empty")
    # Reject any path separator or traversal sequence
    if ".." in component:
        raise PathTraversalError(
            f"{label} '{component}' contains path traversal sequence '..'"
        )
    if "/" in component or "\\" in component:
        raise PathTraversalError(
            f"{label} '{component}' contains path separator character"
        )
    return component


class StorageManager:
    """Manages file storage for uploaded CSV/Excel files.

    Directory layout:
        {base_dir}/{tenant_id}/{client_name}/raw/{uuid}_{filename}
        {base_dir}/{tenant_id}/{client_name}/processed/{upload_id}.db

    Security:
        - Path traversal prevention on every user-supplied component.
        - Directories created with mode 0o700.
        - Files written with mode 0o600.
        - No static HTTP serving.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        raw = base_dir or os.environ.get("UPLOAD_DIR", _DEFAULT_BASE_DIR)
        self.base_dir = Path(raw).resolve()
        logger.debug("StorageManager initialised with base_dir=%s", self.base_dir)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tenant_dir(self, tenant_id: str, client_name: str) -> Path:
        """Return the tenant/client directory without creating it."""
        _validate_component(tenant_id, "tenant_id")
        _validate_component(client_name, "client_name")
        return self.base_dir / tenant_id / client_name

    def _ensure_dir(self, path: Path) -> None:
        """Create directory tree with 700 permissions."""
        path.mkdir(parents=True, exist_ok=True)
        # Enforce permissions even if the directory already existed.
        path.chmod(0o700)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_upload(
        self,
        tenant_id: str,
        client_name: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Save an uploaded file.

        Args:
            tenant_id: UUID string identifying the tenant.
            client_name: Slug-safe name of the client.
            filename: Original filename (basename only).
            content: Raw file bytes.

        Returns:
            Absolute path string of the stored file.

        Raises:
            PathTraversalError: If any component contains '..'.
        """
        _validate_component(filename, "filename")
        raw_dir = self._tenant_dir(tenant_id, client_name) / "raw"
        self._ensure_dir(raw_dir)

        upload_id = uuid.uuid4().hex
        stored_name = f"{upload_id}_{filename}"
        dest = raw_dir / stored_name

        dest.write_bytes(content)
        dest.chmod(0o600)

        logger.info(
            "Saved upload tenant=%s client=%s filename=%s path=%s size=%d",
            tenant_id,
            client_name,
            filename,
            dest,
            len(content),
        )
        return str(dest)

    def get_upload_path(
        self,
        tenant_id: str,
        client_name: str,
        filename: str,
    ) -> Path:
        """Return the expected storage Path for a raw upload.

        Note: The returned path may not exist if the file hasn't been saved yet
        or has been deleted.  Use :meth:`save_upload` to persist content.
        """
        _validate_component(tenant_id, "tenant_id")
        _validate_component(client_name, "client_name")
        _validate_component(filename, "filename")
        return self._tenant_dir(tenant_id, client_name) / "raw" / filename

    def save_sqlite(
        self,
        tenant_id: str,
        client_name: str,
        upload_id: str,
        db_bytes: bytes,
    ) -> str:
        """Save a converted SQLite database file.

        Args:
            tenant_id: UUID string identifying the tenant.
            client_name: Slug-safe name of the client.
            upload_id: Unique identifier for this upload (hex UUID).
            db_bytes: Raw SQLite file bytes.

        Returns:
            Absolute path string of the stored .db file.
        """
        _validate_component(tenant_id, "tenant_id")
        _validate_component(client_name, "client_name")
        _validate_component(upload_id, "upload_id")

        processed_dir = self._tenant_dir(tenant_id, client_name) / "processed"
        self._ensure_dir(processed_dir)

        dest = processed_dir / f"{upload_id}.db"
        dest.write_bytes(db_bytes)
        dest.chmod(0o600)

        logger.info(
            "Saved SQLite tenant=%s client=%s upload_id=%s path=%s size=%d",
            tenant_id,
            client_name,
            upload_id,
            dest,
            len(db_bytes),
        )
        return str(dest)

    def get_sqlite_path(
        self,
        tenant_id: str,
        client_name: str,
        upload_id: str,
    ) -> Path:
        """Return the Path to a processed SQLite file."""
        _validate_component(tenant_id, "tenant_id")
        _validate_component(client_name, "client_name")
        _validate_component(upload_id, "upload_id")
        return self._tenant_dir(tenant_id, client_name) / "processed" / f"{upload_id}.db"

    def delete_upload(self, path: str) -> bool:
        """Delete a specific upload file.

        Args:
            path: Absolute path string returned by :meth:`save_upload` or
                  :meth:`save_sqlite`.

        Returns:
            True if the file was deleted, False if it did not exist.

        Raises:
            PathTraversalError: If path escapes base_dir.
        """
        target = Path(path).resolve()

        # Ensure the resolved path is still inside base_dir
        try:
            target.relative_to(self.base_dir)
        except ValueError:
            raise PathTraversalError(
                f"Path '{path}' is outside storage base_dir '{self.base_dir}'"
            )

        if not target.exists():
            logger.warning("delete_upload: file not found: %s", target)
            return False

        target.unlink()
        logger.info("Deleted upload: %s", target)
        return True

    def cleanup_old(self, max_age_days: int = 30) -> int:
        """Delete files older than *max_age_days*.

        Walks the entire base_dir tree and removes files whose modification
        time is older than the given threshold.  Empty directories are NOT
        removed to avoid race conditions with concurrent writes.

        Args:
            max_age_days: Files last modified more than this many days ago
                          will be deleted.

        Returns:
            Number of files deleted.
        """
        if not self.base_dir.exists():
            logger.info("cleanup_old: base_dir does not exist, nothing to clean")
            return 0

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
        cutoff_ts = cutoff.timestamp()

        deleted = 0
        for file_path in self.base_dir.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                mtime = file_path.stat().st_mtime
                if mtime < cutoff_ts:
                    file_path.unlink()
                    deleted += 1
                    logger.info(
                        "cleanup_old: deleted %s (mtime=%s)",
                        file_path,
                        datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    )
            except OSError as exc:
                logger.error("cleanup_old: could not process %s: %s", file_path, exc)

        logger.info("cleanup_old: deleted %d file(s) older than %d days", deleted, max_age_days)
        return deleted
