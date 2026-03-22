"""
Etendo MCP Server — FastMCP wrapper for the Etendo ERP connector.

Exposes Etendo database operations as MCP tools that agents can call
via the standard MCP protocol. Uses the existing SSHTunnelManager for
all connections — fully backward compatible.

Usage (stdio mode, for Claude Desktop):
    python -m mcp_servers.etendo_server

Usage (programmatic, in tests):
    from mcp_servers.etendo_server import mcp
    # mcp is a FastMCP instance exposing all tools
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional

import structlog

# Ensure project root is on sys.path so shared/ is importable
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from fastmcp import FastMCP
except ImportError as e:
    raise ImportError(
        "fastmcp is not installed. Add 'fastmcp>=2.2.0' to requirements.txt and run pip install."
    ) from e

logger = structlog.get_logger()

# ── FastMCP instance ──────────────────────────────────────────────────────────

mcp = FastMCP(
    name="etendo-server",
    instructions=(
        "MCP server for Etendo ERP. Provides tools to connect to an Etendo PostgreSQL "
        "database via SSH tunnel, introspect its schema, and execute read-only queries."
    ),
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_etendo_config(
    ssh_host: Optional[str] = None,
    ssh_user: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
    db_host: Optional[str] = None,
    db_port: Optional[int] = None,
    db_connection_string: Optional[str] = None,
) -> tuple[dict, dict]:
    """
    Build ssh_config and db_config dicts, falling back to environment variables.

    Env vars:
        ETENDO_SSH_HOST, ETENDO_SSH_USER, ETENDO_SSH_KEY_PATH
        ETENDO_DB_HOST, ETENDO_DB_PORT, ETENDO_DB_CONN_STR
    """
    ssh_config = {
        "host": ssh_host or os.getenv("ETENDO_SSH_HOST", ""),
        "username": ssh_user or os.getenv("ETENDO_SSH_USER", ""),
        "private_key_path": ssh_key_path or os.getenv("ETENDO_SSH_KEY_PATH", ""),
        "port": 22,
    }
    db_config = {
        "host": db_host or os.getenv("ETENDO_DB_HOST", "localhost"),
        "port": int(db_port or os.getenv("ETENDO_DB_PORT", "5432")),
        "connection_string": (
            db_connection_string or os.getenv("ETENDO_DB_CONN_STR", "")
        ),
    }
    return ssh_config, db_config


# ── MCP Tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def etendo_list_tables(
    ssh_host: str = "",
    ssh_user: str = "",
    ssh_key_path: str = "",
    db_host: str = "",
    db_port: int = 5432,
    db_connection_string: str = "",
    schema: str = "public",
) -> dict[str, Any]:
    """
    List all tables in the Etendo database.

    Connects via SSH tunnel (if SSH params provided) and returns the list
    of table names in the given schema.  Falls back to env-vars when params
    are empty strings.

    Args:
        ssh_host: SSH bastion hostname (or ETENDO_SSH_HOST env var).
        ssh_user: SSH username (or ETENDO_SSH_USER env var).
        ssh_key_path: Path to SSH private key (or ETENDO_SSH_KEY_PATH env var).
        db_host: Database host as seen from bastion (or ETENDO_DB_HOST env var).
        db_port: Database port (default 5432).
        db_connection_string: Full SQLAlchemy connection string.
        schema: DB schema to inspect (default "public").

    Returns:
        {"tables": [...], "schema": "..."}  or  {"error": "..."}
    """
    try:
        from sqlalchemy import create_engine, inspect as sa_inspect

        ssh_cfg, db_cfg = _get_etendo_config(
            ssh_host or None,
            ssh_user or None,
            ssh_key_path or None,
            db_host or None,
            db_port or None,
            db_connection_string or None,
        )

        # Decide whether to use SSH tunnel
        use_tunnel = bool(ssh_cfg.get("host") and ssh_cfg.get("private_key_path"))

        if use_tunnel:
            from shared.ssh_tunnel import SSHTunnelManager

            manager = SSHTunnelManager()
            with manager.create_tunnel(ssh_cfg, db_cfg, job_id="mcp-list-tables") as conn_str:
                engine = create_engine(conn_str)
                inspector = sa_inspect(engine)
                tables = inspector.get_table_names(schema=schema)
                engine.dispose()
        else:
            conn_str = db_cfg["connection_string"]
            if not conn_str:
                return {"error": "No connection string provided and ETENDO_DB_CONN_STR not set"}
            engine = create_engine(conn_str)
            inspector = sa_inspect(engine)
            tables = inspector.get_table_names(schema=schema)
            engine.dispose()

        logger.info("etendo_list_tables", count=len(tables), schema=schema)
        return {"tables": tables, "schema": schema, "count": len(tables)}

    except Exception as exc:
        logger.error("etendo_list_tables failed", error=str(exc))
        return {"error": str(exc)}


@mcp.tool()
def etendo_describe_table(
    table_name: str,
    ssh_host: str = "",
    ssh_user: str = "",
    ssh_key_path: str = "",
    db_host: str = "",
    db_port: int = 5432,
    db_connection_string: str = "",
    schema: str = "public",
) -> dict[str, Any]:
    """
    Describe columns and types of a specific Etendo table.

    Args:
        table_name: Name of the table to describe.
        ssh_host: SSH bastion hostname (or ETENDO_SSH_HOST env var).
        ssh_user: SSH username.
        ssh_key_path: Path to SSH private key.
        db_host: Database host.
        db_port: Database port.
        db_connection_string: Full SQLAlchemy connection string.
        schema: DB schema (default "public").

    Returns:
        {"table": "...", "columns": [{"name": ..., "type": ...}, ...]}  or  {"error": "..."}
    """
    try:
        from sqlalchemy import create_engine, inspect as sa_inspect

        ssh_cfg, db_cfg = _get_etendo_config(
            ssh_host or None,
            ssh_user or None,
            ssh_key_path or None,
            db_host or None,
            db_port or None,
            db_connection_string or None,
        )

        use_tunnel = bool(ssh_cfg.get("host") and ssh_cfg.get("private_key_path"))

        def _describe(conn_str: str) -> dict:
            engine = create_engine(conn_str)
            inspector = sa_inspect(engine)
            cols = inspector.get_columns(table_name, schema=schema)
            engine.dispose()
            return {
                "table": table_name,
                "schema": schema,
                "columns": [
                    {"name": c["name"], "type": str(c["type"])} for c in cols
                ],
            }

        if use_tunnel:
            from shared.ssh_tunnel import SSHTunnelManager

            manager = SSHTunnelManager()
            with manager.create_tunnel(ssh_cfg, db_cfg, job_id="mcp-describe-table") as conn_str:
                result = _describe(conn_str)
        else:
            conn_str = db_cfg["connection_string"]
            if not conn_str:
                return {"error": "No connection string provided"}
            result = _describe(conn_str)

        logger.info("etendo_describe_table", table=table_name, col_count=len(result["columns"]))
        return result

    except Exception as exc:
        logger.error("etendo_describe_table failed", error=str(exc))
        return {"error": str(exc)}


@mcp.tool()
def etendo_execute_query(
    sql: str,
    db_connection_string: str = "",
    ssh_host: str = "",
    ssh_user: str = "",
    ssh_key_path: str = "",
    db_host: str = "",
    db_port: int = 5432,
    max_rows: int = 100,
) -> dict[str, Any]:
    """
    Execute a read-only SQL query against the Etendo database.

    Only SELECT statements are allowed.  Results are limited to max_rows rows.

    Args:
        sql: SELECT SQL to execute.
        db_connection_string: Full SQLAlchemy connection string.
        ssh_host: SSH bastion hostname (optional).
        ssh_user: SSH username (optional).
        ssh_key_path: Path to SSH private key (optional).
        db_host: Database host.
        db_port: Database port.
        max_rows: Maximum rows to return (default 100, capped at 1000).

    Returns:
        {"columns": [...], "rows": [[...], ...], "row_count": int}  or  {"error": "..."}
    """
    # Safety check — only allow SELECT
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT"):
        return {"error": "Only SELECT statements are allowed via this tool"}

    max_rows = min(max_rows, 1000)

    try:
        from sqlalchemy import create_engine, text as sa_text

        ssh_cfg, db_cfg = _get_etendo_config(
            ssh_host or None,
            ssh_user or None,
            ssh_key_path or None,
            db_host or None,
            db_port or None,
            db_connection_string or None,
        )

        use_tunnel = bool(ssh_cfg.get("host") and ssh_cfg.get("private_key_path"))

        def _run_query(conn_str: str) -> dict:
            engine = create_engine(conn_str)
            with engine.connect() as conn:
                result = conn.execute(sa_text(sql))
                cols = list(result.keys())
                rows = [list(row) for row in result.fetchmany(max_rows)]
            engine.dispose()
            return {"columns": cols, "rows": rows, "row_count": len(rows)}

        if use_tunnel:
            from shared.ssh_tunnel import SSHTunnelManager

            manager = SSHTunnelManager()
            with manager.create_tunnel(ssh_cfg, db_cfg, job_id="mcp-execute-query") as conn_str:
                result = _run_query(conn_str)
        else:
            conn_str = db_cfg["connection_string"]
            if not conn_str:
                return {"error": "No connection string provided"}
            result = _run_query(conn_str)

        logger.info("etendo_execute_query", row_count=result["row_count"])
        return result

    except Exception as exc:
        logger.error("etendo_execute_query failed", error=str(exc))
        return {"error": str(exc)}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run as stdio MCP server (compatible with Claude Desktop)
    mcp.run()
