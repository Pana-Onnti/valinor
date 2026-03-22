"""
Etendo connector (VAL-33).

Subclass of PostgreSQLConnector that adds SSH tunnel support.
Uses SSHTunnelManager from shared/ssh_tunnel.py — fully backward compatible.

Config keys:
    connection_string (required): PostgreSQL DSN for the Etendo database
    ssh_host (required): SSH bastion hostname
    ssh_user (required): SSH username
    ssh_key_path (required): Path to SSH private key
    db_host (optional): DB host as seen from bastion (default: parsed from conn string)
    db_port (optional): DB port (default 5432)
    schema (optional): Default schema (default "public")
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

import structlog

from .base import SourceType
from .postgresql import PostgreSQLConnector

logger = structlog.get_logger()


class EtendoConnector(PostgreSQLConnector):
    """
    Etendo ERP connector — PostgreSQL over SSH tunnel.

    Extends PostgreSQLConnector with SSH tunnel lifecycle management.
    The tunnel is created on connect() and torn down on close().
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._tunnel_manager = None
        self._tunnel_context = None
        self._local_conn_str: Optional[str] = None

    @property
    def source_type(self) -> SourceType:
        return SourceType.ETENDO

    def connect(self) -> None:
        """
        Create SSH tunnel and then connect via PostgreSQLConnector.

        The tunnel is kept open until close() is called.
        """
        from shared.ssh_tunnel import SSHTunnelManager

        ssh_host = self.config.get("ssh_host", "")
        ssh_user = self.config.get("ssh_user", "")
        ssh_key_path = self.config.get("ssh_key_path", "")
        original_conn = self.config.get("connection_string", "")

        if not all([ssh_host, ssh_user, ssh_key_path, original_conn]):
            raise ConnectionError(
                "EtendoConnector requires: ssh_host, ssh_user, ssh_key_path, connection_string"
            )

        # Parse DB host/port from connection string if not provided
        db_host = self.config.get("db_host") or self._extract_host(original_conn)
        db_port = int(self.config.get("db_port", 5432))

        ssh_cfg = {
            "host": ssh_host,
            "username": ssh_user,
            "private_key_path": ssh_key_path,
            "port": 22,
        }
        db_cfg = {
            "host": db_host,
            "port": db_port,
            "connection_string": original_conn,
        }

        self._tunnel_manager = SSHTunnelManager()

        # Enter the context manager and hold it open
        import uuid
        self._job_id = f"etendo-connector-{uuid.uuid4().hex[:8]}"
        self._tunnel_cm = self._tunnel_manager.create_tunnel(ssh_cfg, db_cfg, self._job_id)

        try:
            self._local_conn_str = self._tunnel_cm.__enter__()
        except Exception as exc:
            self._tunnel_cm = None
            raise ConnectionError(f"Etendo SSH tunnel failed: {exc}") from exc

        # Now connect via parent (PostgreSQL) with the tunneled connection string
        self.config = {**self.config, "connection_string": self._local_conn_str}
        super().connect()

        logger.info("etendo.connect", ssh_host=ssh_host, job_id=self._job_id)

    def close(self) -> None:
        """Close PostgreSQL connection and tear down SSH tunnel."""
        super().close()  # Close the SQLAlchemy engine first

        if self._tunnel_cm is not None:
            try:
                self._tunnel_cm.__exit__(None, None, None)
                logger.info("etendo.tunnel_closed", job_id=getattr(self, "_job_id", "?"))
            except Exception as exc:
                logger.warning("etendo.tunnel_close_failed", error=str(exc))
            self._tunnel_cm = None

    @staticmethod
    def _extract_host(conn_str: str) -> str:
        """Extract hostname from a SQLAlchemy DSN."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(conn_str)
            return parsed.hostname or "localhost"
        except Exception:
            return "localhost"
