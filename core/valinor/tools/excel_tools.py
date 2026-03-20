"""
Excel/CSV tools — Convert spreadsheet files to SQLite for querying.

These tools handle Stage 0 (Intake) for file-based data sources.
"""

import json
from pathlib import Path

from claude_agent_sdk import tool


@tool(
    "excel_to_sqlite",
    "Convert an Excel file (.xlsx, .xls) to SQLite database for querying. Each sheet becomes a table.",
    {
        "file_path": str,
        "client_name": str,
    },
)
async def excel_to_sqlite(args):
    """Converts Excel workbook to SQLite. Each sheet → a table."""
    import pandas as pd
    import sqlite3

    file_path = args["file_path"]
    client_name = args["client_name"]
    db_path = f"/tmp/valinor/{client_name}.db"

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    if not Path(file_path).exists():
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": f"File not found: {file_path}"}),
                }
            ]
        }

    try:
        # Read all sheets
        sheets = pd.read_excel(file_path, sheet_name=None)
        conn = sqlite3.connect(db_path)

        tables_created = []
        for name, df in sheets.items():
            # Normalize table name
            table_name = (
                name.lower()
                .replace(" ", "_")
                .replace("-", "_")
                .replace(".", "_")
                .strip("_")
            )
            df.to_sql(table_name, conn, if_exists="replace", index=False)
            tables_created.append(
                {
                    "sheet": name,
                    "table": table_name,
                    "rows": len(df),
                    "columns": list(df.columns),
                }
            )

        conn.close()

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "converted",
                            "source": file_path,
                            "sqlite_path": db_path,
                            "connection_string": f"sqlite:///{db_path}",
                            "tables": tables_created,
                        },
                        indent=2,
                    ),
                }
            ]
        }

    except Exception as e:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Failed to convert Excel: {str(e)}"}
                    ),
                }
            ]
        }


@tool(
    "csv_to_sqlite",
    "Convert a CSV file to SQLite database for querying. Creates a single table named 'data'.",
    {
        "file_path": str,
        "client_name": str,
        "table_name": str,
    },
)
async def csv_to_sqlite(args):
    """Converts CSV to SQLite. Creates a single table."""
    import pandas as pd
    import sqlite3

    file_path = args["file_path"]
    client_name = args["client_name"]
    table_name = args.get("table_name", "data")
    db_path = f"/tmp/valinor/{client_name}.db"

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    if not Path(file_path).exists():
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": f"File not found: {file_path}"}),
                }
            ]
        }

    try:
        # Try to detect encoding and separator
        df = pd.read_csv(file_path, encoding="utf-8", on_bad_lines="skip")

        conn = sqlite3.connect(db_path)
        df.to_sql(table_name, conn, if_exists="replace", index=False)
        conn.close()

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "status": "converted",
                            "source": file_path,
                            "sqlite_path": db_path,
                            "connection_string": f"sqlite:///{db_path}",
                            "table": table_name,
                            "rows": len(df),
                            "columns": list(df.columns),
                        },
                        indent=2,
                    ),
                }
            ]
        }

    except Exception as e:
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"error": f"Failed to convert CSV: {str(e)}"}
                    ),
                }
            ]
        }
