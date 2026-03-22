"""
Database tools — In-process MCP server tools for database operations.

These tools use the @tool decorator from claude-agent-sdk to register
as in-process MCP tools that run within the agent process.

Connection pooling: when shared.db_pool is available, engines are
obtained from the pool (reuse + health checks). Falls back to
create_engine() if the pool module is not importable.
"""

import json
from pathlib import Path

from claude_agent_sdk import tool

# Connection pooling integration — graceful fallback
try:
    from shared.db_pool import get_pooled_engine as _get_engine
except ImportError:
    _get_engine = None


def _create_engine(connection_string: str):
    """Get a SQLAlchemy engine — pooled if available, direct otherwise."""
    if _get_engine is not None:
        return _get_engine(connection_string)
    from sqlalchemy import create_engine
    return create_engine(connection_string)


@tool(
    "connect_database",
    "Connect to a client database and verify read-only access. Returns schema/table metadata.",
    {
        "connection_string": str,
        "client_name": str,
    },
)
async def connect_database(args):
    """Validates connection, tests SELECT, returns metadata."""
    from sqlalchemy import inspect, text

    connection_string = args["connection_string"]
    client_name = args["client_name"]

    engine = _create_engine(connection_string)
    inspector = inspect(engine)

    # Test read-only access
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    schemas = inspector.get_schema_names()
    tables = {}
    total_tables = 0
    for schema in schemas:
        schema_tables = inspector.get_table_names(schema=schema)
        tables[schema] = schema_tables
        total_tables += len(schema_tables)

    engine.dispose()

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "connected",
                        "client": client_name,
                        "schemas": schemas,
                        "table_count": total_tables,
                        "tables": tables,
                    },
                    indent=2,
                ),
            }
        ]
    }


@tool(
    "introspect_schema",
    "Deep introspect a database table: columns, types, constraints, indexes, row count.",
    {
        "connection_string": str,
        "table_name": str,
        "schema": str,
    },
)
async def introspect_schema(args):
    """Returns detailed schema information for a table."""
    from sqlalchemy import inspect, text

    engine = _create_engine(args["connection_string"])
    inspector = inspect(engine)
    schema = args.get("schema", "public")
    table = args["table_name"]

    try:
        columns = []
        for col in inspector.get_columns(table, schema=schema):
            columns.append(
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": str(col.get("default", "")) if col.get("default") else None,
                }
            )

        # Primary keys
        pk = inspector.get_pk_constraint(table, schema=schema)

        # Foreign keys
        fks = inspector.get_foreign_keys(table, schema=schema)
        foreign_keys = []
        for fk in fks:
            foreign_keys.append(
                {
                    "columns": fk["constrained_columns"],
                    "referred_table": fk["referred_table"],
                    "referred_columns": fk["referred_columns"],
                    "referred_schema": fk.get("referred_schema"),
                }
            )

        # Indexes
        indexes = []
        for idx in inspector.get_indexes(table, schema=schema):
            indexes.append(
                {
                    "name": idx["name"],
                    "columns": idx["column_names"],
                    "unique": idx.get("unique", False),
                }
            )

        # Row count (approximate)
        with engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM "{schema}"."{table}"'))
            row_count = result.scalar()

        engine.dispose()

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "table": table,
                            "schema": schema,
                            "columns": columns,
                            "primary_key": pk,
                            "foreign_keys": foreign_keys,
                            "indexes": indexes,
                            "row_count": row_count,
                        },
                        indent=2,
                    ),
                }
            ]
        }
    except Exception as e:
        engine.dispose()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Failed to introspect table {table}: {str(e)}"}
                    ),
                }
            ]
        }


@tool(
    "sample_table",
    "Sample N rows from a table for data discovery. ALWAYS sample before classifying.",
    {
        "connection_string": str,
        "table_name": str,
        "schema": str,
        "limit": int,
    },
)
async def sample_table(args):
    """Returns a sample of rows from the table as JSON."""
    from sqlalchemy import text

    engine = _create_engine(args["connection_string"])
    schema = args.get("schema", "public")
    table = args["table_name"]
    limit = args.get("limit", 5)

    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f'SELECT * FROM "{schema}"."{table}" LIMIT :limit'),
                {"limit": limit},
            )
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

        engine.dispose()

        # Convert non-serializable types to strings
        for row in rows:
            for key, value in row.items():
                if not isinstance(value, (str, int, float, bool, type(None))):
                    row[key] = str(value)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "table": table,
                            "schema": schema,
                            "columns": columns,
                            "sample_rows": rows,
                            "row_count": len(rows),
                        },
                        indent=2,
                    ),
                }
            ]
        }
    except Exception as e:
        engine.dispose()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Failed to sample table {table}: {str(e)}"}
                    ),
                }
            ]
        }


@tool(
    "classify_entity",
    "Classify a database table as MASTER, TRANSACTIONAL, CONFIG, or BRIDGE based on its structure and data.",
    {
        "table_name": str,
        "columns": str,
        "sample_data": str,
        "row_count": int,
    },
)
async def classify_entity(args):
    """
    Deterministic classification helper.
    Returns a suggested classification with reasoning.
    """
    table_name = args["table_name"].lower()
    row_count = args.get("row_count", 0)
    columns_str = args.get("columns", "")

    # Heuristic classification
    classification = "CONFIG"
    confidence = 0.5
    reasoning = []

    # Parse columns if they're a JSON string
    try:
        columns = json.loads(columns_str) if isinstance(columns_str, str) else columns_str
        col_names = [c.get("name", "").lower() if isinstance(c, dict) else c.lower() for c in columns]
    except (json.JSONDecodeError, AttributeError):
        col_names = []

    # Check for transactional indicators
    date_cols = [c for c in col_names if any(d in c for d in ["date", "fecha", "created", "updated", "time"])]
    amount_cols = [c for c in col_names if any(a in c for a in ["amount", "total", "price", "qty", "quantity", "importe"])]

    if date_cols and amount_cols and row_count > 100:
        classification = "TRANSACTIONAL"
        confidence = 0.8
        reasoning.append(f"Has date columns ({date_cols[:3]}) and amount columns ({amount_cols[:3]})")
        reasoning.append(f"High row count ({row_count})")
    elif row_count > 50 and not amount_cols:
        classification = "MASTER"
        confidence = 0.7
        reasoning.append("Moderate row count without amount columns suggests master data")
    elif row_count < 50 and len(col_names) < 5:
        classification = "BRIDGE"
        confidence = 0.6
        reasoning.append("Few columns and low row count suggest junction/bridge table")
    else:
        classification = "CONFIG"
        confidence = 0.5
        reasoning.append("Default classification — needs agent review")

    # Name-based hints (secondary signal)
    transactional_hints = ["invoice", "payment", "order", "shipment", "delivery", "transaction", "movement"]
    master_hints = ["customer", "partner", "product", "employee", "location", "warehouse", "category"]
    config_hints = ["config", "setting", "parameter", "preference", "system", "ad_"]

    for hint in transactional_hints:
        if hint in table_name:
            if classification != "TRANSACTIONAL":
                reasoning.append(f"Name hint '{hint}' suggests TRANSACTIONAL")
            confidence = min(confidence + 0.1, 1.0)
            break

    for hint in master_hints:
        if hint in table_name:
            if classification != "MASTER":
                reasoning.append(f"Name hint '{hint}' suggests MASTER")
            confidence = min(confidence + 0.1, 1.0)
            break

    for hint in config_hints:
        if hint in table_name:
            reasoning.append(f"Name hint '{hint}' suggests CONFIG")
            break

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "table": args["table_name"],
                        "classification": classification,
                        "confidence": round(confidence, 2),
                        "reasoning": reasoning,
                        "note": "This is a heuristic suggestion. Always verify with sample data.",
                    },
                    indent=2,
                ),
            }
        ]
    }


@tool(
    "probe_column_values",
    "Probe a column's distinct values with counts (max 20). Use BEFORE writing any filter — verifies actual values in the database. Pattern: ReFoRCE Column Exploration.",
    {
        "connection_string": str,
        "table_name": str,
        "column_name": str,
        "schema": str,
    },
)
async def probe_column_values(args):
    """
    SELECT DISTINCT col, COUNT(*) FROM table GROUP BY 1 ORDER BY cnt DESC LIMIT 20.

    Critical for discovering:
    - Tenant IDs (ad_client_id values)
    - Transaction direction flags (issotrx='Y' vs 'N')
    - Status codes (docstatus='CO'/'VO'/etc.)
    - Boolean-like strings ('Y'/'N', 'true'/'false', '1'/'0')
    """
    from sqlalchemy import text as sa_text

    engine = _create_engine(args["connection_string"])
    schema = args.get("schema", "public")
    table = args["table_name"]
    column = args["column_name"]

    try:
        with engine.connect() as conn:
            result = conn.execute(
                sa_text(
                    f'SELECT "{column}", COUNT(*) AS cnt '
                    f'FROM "{schema}"."{table}" '
                    f"GROUP BY 1 ORDER BY cnt DESC LIMIT 20"
                )
            )
            rows = [{"value": str(r[0]), "count": r[1]} for r in result.fetchall()]

        engine.dispose()

        total = sum(r["count"] for r in rows)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "table": table,
                            "column": column,
                            "schema": schema,
                            "distinct_values": rows,
                            "total_rows_sampled": total,
                            "note": (
                                "Use the dominant values to construct base_filter. "
                                "E.g. if issotrx has Y=30100 and N=15134, "
                                "set base_filter to include \"issotrx='Y'\" for sales invoices."
                            ),
                        },
                        indent=2,
                    ),
                }
            ]
        }
    except Exception as e:
        engine.dispose()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Failed to probe {table}.{column}: {str(e)}"}
                    ),
                }
            ]
        }


@tool(
    "execute_query",
    "Execute a read-only SQL query and return results. Has a row limit for safety.",
    {
        "connection_string": str,
        "sql": str,
        "max_rows": int,
    },
)
async def execute_query(args):
    """Execute SQL with safety limits. Returns results as JSON."""
    from sqlalchemy import text

    engine = _create_engine(args["connection_string"])
    sql = args["sql"].strip()
    max_rows = args.get("max_rows", 1000)

    # Safety: block write operations
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"]
    sql_upper = sql.upper().strip()
    for keyword in forbidden:
        if sql_upper.startswith(keyword):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": f"Write operation blocked: {keyword}",
                                "sql": sql[:100],
                            }
                        ),
                    }
                ]
            }

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = []
            for i, row in enumerate(result):
                if i >= max_rows:
                    break
                row_dict = dict(zip(columns, row))
                # Serialize non-standard types
                for key, value in row_dict.items():
                    if not isinstance(value, (str, int, float, bool, type(None))):
                        row_dict[key] = str(value)
                rows.append(row_dict)

        engine.dispose()

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "success",
                            "columns": columns,
                            "rows": rows,
                            "row_count": len(rows),
                            "truncated": len(rows) >= max_rows,
                        },
                        indent=2,
                    ),
                }
            ]
        }

    except Exception as e:
        engine.dispose()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "error",
                            "error": str(e),
                            "sql": sql[:200],
                        }
                    ),
                }
            ]
        }
