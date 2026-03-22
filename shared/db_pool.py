"""
Connection Pool Manager — VAL-59.

Provides connection pooling for database operations using SQLAlchemy's
QueuePool. Supports both direct and SSH tunnel connections.

Usage:
    from shared.db_pool import ConnectionPoolManager

    pool = ConnectionPoolManager()
    engine = pool.get_engine("postgresql://user:pass@host/db")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))

    # Cleanup
    pool.dispose_all()

Configuration via environment variables:
    VALINOR_DB_POOL_SIZE       — default pool size (default: 5)
    VALINOR_DB_POOL_MAX        — max overflow connections (default: 10)
    VALINOR_DB_POOL_TIMEOUT    — connection checkout timeout in seconds (default: 30)
    VALINOR_DB_POOL_RECYCLE    — connection recycle time in seconds (default: 1800)
    VALINOR_DB_POOL_PRE_PING   — enable health checks on checkout (default: true)
"""

from __future__ import annotations

import os
import threading
from typing import Optional

import structlog
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

logger = structlog.get_logger()


class ConnectionPoolManager:
    """
    Manages a registry of pooled SQLAlchemy engines keyed by connection string.

    Thread-safe: uses a lock to guard the engine registry.
    Supports both direct connections and SSH-tunneled connections.
    """

    def __init__(
        self,
        pool_size: Optional[int] = None,
        max_overflow: Optional[int] = None,
        pool_timeout: Optional[int] = None,
        pool_recycle: Optional[int] = None,
        pool_pre_ping: Optional[bool] = None,
    ):
        self._pool_size = pool_size or int(os.getenv("VALINOR_DB_POOL_SIZE", "5"))
        self._max_overflow = max_overflow or int(os.getenv("VALINOR_DB_POOL_MAX", "10"))
        self._pool_timeout = pool_timeout or int(os.getenv("VALINOR_DB_POOL_TIMEOUT", "30"))
        self._pool_recycle = pool_recycle or int(os.getenv("VALINOR_DB_POOL_RECYCLE", "1800"))
        self._pool_pre_ping = (
            pool_pre_ping
            if pool_pre_ping is not None
            else os.getenv("VALINOR_DB_POOL_PRE_PING", "true").lower() == "true"
        )

        self._engines: dict[str, Engine] = {}
        self._lock = threading.Lock()

        logger.info(
            "ConnectionPoolManager initialized",
            pool_size=self._pool_size,
            max_overflow=self._max_overflow,
            pool_timeout=self._pool_timeout,
            pool_recycle=self._pool_recycle,
            pool_pre_ping=self._pool_pre_ping,
        )

    def get_engine(
        self,
        connection_string: str,
        pool_size: Optional[int] = None,
        max_overflow: Optional[int] = None,
    ) -> Engine:
        """
        Get or create a pooled engine for the given connection string.

        Args:
            connection_string: SQLAlchemy connection URL.
            pool_size: Override default pool size for this engine.
            max_overflow: Override default max overflow for this engine.

        Returns:
            A SQLAlchemy Engine with connection pooling enabled.
        """
        with self._lock:
            if connection_string in self._engines:
                engine = self._engines[connection_string]
                # Verify the engine is still usable
                if self._is_engine_healthy(engine):
                    return engine
                else:
                    logger.warning(
                        "Stale engine detected, recreating",
                        connection_string=self._mask_connection_string(connection_string),
                    )
                    try:
                        engine.dispose()
                    except Exception:
                        pass

            engine = self._create_engine(
                connection_string,
                pool_size=pool_size or self._pool_size,
                max_overflow=max_overflow or self._max_overflow,
            )
            self._engines[connection_string] = engine
            return engine

    def _create_engine(
        self,
        connection_string: str,
        pool_size: int,
        max_overflow: int,
    ) -> Engine:
        """Create a new SQLAlchemy engine with connection pooling."""
        # SQLite doesn't support pooling in the same way
        is_sqlite = connection_string.startswith("sqlite")

        engine_kwargs: dict = {
            "pool_pre_ping": self._pool_pre_ping,
            "pool_recycle": self._pool_recycle,
        }

        if not is_sqlite:
            engine_kwargs.update({
                "poolclass": QueuePool,
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_timeout": self._pool_timeout,
            })

        engine = create_engine(connection_string, **engine_kwargs)

        # Register event listeners for monitoring
        self._register_pool_events(engine, connection_string)

        logger.info(
            "Engine created with connection pooling",
            connection_string=self._mask_connection_string(connection_string),
            pool_size=pool_size,
            max_overflow=max_overflow,
            is_sqlite=is_sqlite,
        )

        return engine

    def _is_engine_healthy(self, engine: Engine) -> bool:
        """Check if an engine's pool is still healthy."""
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.warning("Engine health check failed", error=str(e))
            return False

    def _register_pool_events(self, engine: Engine, connection_string: str) -> None:
        """Register SQLAlchemy pool event listeners for observability."""
        masked = self._mask_connection_string(connection_string)

        @event.listens_for(engine, "checkout")
        def on_checkout(dbapi_conn, connection_record, connection_proxy):
            logger.debug("Pool checkout", connection=masked)

        @event.listens_for(engine, "checkin")
        def on_checkin(dbapi_conn, connection_record):
            logger.debug("Pool checkin", connection=masked)

        @event.listens_for(engine, "invalidate")
        def on_invalidate(dbapi_conn, connection_record, exception):
            logger.warning(
                "Pool connection invalidated",
                connection=masked,
                error=str(exception) if exception else "manual",
            )

    def get_pool_status(self, connection_string: str) -> dict:
        """
        Get pool statistics for a given connection string.

        Returns:
            Dict with pool_size, checkedin, checkedout, overflow, and total.
        """
        with self._lock:
            engine = self._engines.get(connection_string)
            if not engine:
                return {"error": "No engine found for this connection string"}

        pool = engine.pool
        try:
            # QueuePool exposes these as methods; StaticPool/NullPool may differ
            size = pool.size() if callable(getattr(pool, "size", None)) else getattr(pool, "size", 0)
            checkedin = pool.checkedin() if callable(getattr(pool, "checkedin", None)) else 0
            checkedout = pool.checkedout() if callable(getattr(pool, "checkedout", None)) else 0
            overflow = pool.overflow() if callable(getattr(pool, "overflow", None)) else 0
            return {
                "pool_size": size,
                "checked_in": checkedin,
                "checked_out": checkedout,
                "overflow": overflow,
                "total_connections": checkedin + checkedout,
            }
        except (AttributeError, TypeError):
            return {"pool_type": type(pool).__name__, "note": "Pool stats not available"}

    def dispose_engine(self, connection_string: str) -> bool:
        """
        Dispose of a specific engine and its pool.

        Returns:
            True if the engine was found and disposed, False otherwise.
        """
        with self._lock:
            engine = self._engines.pop(connection_string, None)

        if engine:
            try:
                engine.dispose()
                logger.info(
                    "Engine disposed",
                    connection=self._mask_connection_string(connection_string),
                )
                return True
            except Exception as e:
                logger.error(
                    "Error disposing engine",
                    connection=self._mask_connection_string(connection_string),
                    error=str(e),
                )
        return False

    def dispose_all(self) -> int:
        """
        Dispose of all engines. Call during application shutdown.

        Returns:
            Number of engines disposed.
        """
        with self._lock:
            engines = list(self._engines.items())
            self._engines.clear()

        count = 0
        for conn_str, engine in engines:
            try:
                engine.dispose()
                count += 1
                logger.info(
                    "Engine disposed",
                    connection=self._mask_connection_string(conn_str),
                )
            except Exception as e:
                logger.error(
                    "Error disposing engine during shutdown",
                    connection=self._mask_connection_string(conn_str),
                    error=str(e),
                )

        logger.info("All engines disposed", count=count)
        return count

    @staticmethod
    def _mask_connection_string(connection_string: str) -> str:
        """Mask password in connection string for logging."""
        import re
        return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", connection_string)

    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.dispose_all()
        except Exception:
            pass


# ── Module-level singleton ──────────────────────────────────────────────

_default_pool: Optional[ConnectionPoolManager] = None
_singleton_lock = threading.Lock()


def get_pool() -> ConnectionPoolManager:
    """Get or create the module-level singleton pool manager."""
    global _default_pool
    if _default_pool is None:
        with _singleton_lock:
            if _default_pool is None:
                _default_pool = ConnectionPoolManager()
    return _default_pool


def get_pooled_engine(connection_string: str, **kwargs) -> Engine:
    """
    Convenience function: get a pooled engine from the singleton pool.

    Drop-in replacement for create_engine() — uses connection pooling
    and reuses engines for the same connection string.

    Args:
        connection_string: SQLAlchemy connection URL.
        **kwargs: Forwarded to ConnectionPoolManager.get_engine().

    Returns:
        A SQLAlchemy Engine with connection pooling enabled.
    """
    return get_pool().get_engine(connection_string, **kwargs)


def dispose_pool() -> None:
    """Dispose of the singleton pool manager. Call during shutdown."""
    global _default_pool
    if _default_pool is not None:
        _default_pool.dispose_all()
        _default_pool = None
