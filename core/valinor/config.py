"""
Client configuration loader for Valinor.
Loads client configs from clients/{name}/config.json and resolves data sources.
"""

import json
from pathlib import Path
from typing import Any


# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
CLIENTS_DIR = PROJECT_ROOT / "clients"
MEMORY_DIR = PROJECT_ROOT / "memory"
OUTPUT_DIR = PROJECT_ROOT / "output"


def load_client_config(client: str, source: str | None = None) -> dict[str, Any]:
    """
    Load client configuration from clients/{client}/config.json.
    
    If source is provided (Excel/CSV path), it overrides the connection_string
    and sets up the config for file-based analysis.
    
    Args:
        client: Client name (directory name under clients/)
        source: Optional path to Excel/CSV file
        
    Returns:
        Complete client configuration dict
    """
    config_path = CLIENTS_DIR / client / "config.json"
    
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        # Create minimal config for new clients
        config = {
            "name": client,
            "display_name": client.replace("_", " ").title(),
            "sector": "unknown",
            "country": "unknown",
            "currency": "USD",
            "erp": "unknown",
            "language": "es",
            "fiscal_context": "generic",
            "overrides": {},
        }
    
    # Override with file source if provided
    if source:
        source_path = Path(source).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source}")
        
        config["source_path"] = str(source_path)
        config["erp"] = "Excel/CSV"
        # SQLite path will be set by excel_to_sqlite tool
        config["connection_string"] = f"sqlite:////tmp/valinor/{client}.db"
    
    # Ensure connection_string exists
    if "connection_string" not in config and "source_path" not in config:
        raise ValueError(
            f"Client '{client}' has no connection_string or source_path. "
            f"Either add connection_string to config.json or use --source flag."
        )
    
    return config


def load_memory(client: str) -> dict[str, Any] | None:
    """
    Load the most recent swarm memory for a client.
    
    Looks for the latest swarm_memory_*.json in memory/{client}/.
    Returns None if no previous memory exists (first run).
    """
    memory_dir = MEMORY_DIR / client
    
    if not memory_dir.exists():
        return None
    
    # Find all memory files and sort by name (period) descending
    memory_files = sorted(
        memory_dir.glob("swarm_memory_*.json"),
        key=lambda p: p.stem,
        reverse=True,
    )
    
    if not memory_files:
        return None
    
    # Load the most recent one
    with open(memory_files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def load_overrides(client: str) -> str | None:
    """
    Load client-specific skill overrides from clients/{client}/overrides.md.
    Returns the markdown content or None.
    """
    overrides_path = CLIENTS_DIR / client / "overrides.md"
    
    if overrides_path.exists():
        return overrides_path.read_text(encoding="utf-8")
    
    return None


def parse_period(period: str) -> dict[str, str]:
    """
    Parse a period string into start/end dates.
    
    Supports formats:
    - 'Q1-2025' → 2025-01-01 to 2025-03-31
    - 'Q2-2025' → 2025-04-01 to 2025-06-30
    - 'Q3-2025' → 2025-07-01 to 2025-09-30
    - 'Q4-2025' → 2025-10-01 to 2025-12-31
    - 'H1-2025' → 2025-01-01 to 2025-06-30
    - 'H2-2025' → 2025-07-01 to 2025-12-31
    - '2025'    → 2025-01-01 to 2025-12-31
    """
    period = period.strip().upper()
    
    # Full year
    if period.isdigit() and len(period) == 4:
        year = period
        return {"start": f"{year}-01-01", "end": f"{year}-12-31", "label": period}
    
    # Quarter
    if period.startswith("Q") and "-" in period:
        quarter, year = period.split("-")
        q = int(quarter[1])
        quarter_ranges = {
            1: ("01-01", "03-31"),
            2: ("04-01", "06-30"),
            3: ("07-01", "09-30"),
            4: ("10-01", "12-31"),
        }
        if q not in quarter_ranges:
            raise ValueError(f"Invalid quarter: {quarter}")
        start_md, end_md = quarter_ranges[q]
        return {
            "start": f"{year}-{start_md}",
            "end": f"{year}-{end_md}",
            "label": period,
        }
    
    # Half
    if period.startswith("H") and "-" in period:
        half, year = period.split("-")
        h = int(half[1])
        half_ranges = {
            1: ("01-01", "06-30"),
            2: ("07-01", "12-31"),
        }
        if h not in half_ranges:
            raise ValueError(f"Invalid half: {half}")
        start_md, end_md = half_ranges[h]
        return {
            "start": f"{year}-{start_md}",
            "end": f"{year}-{end_md}",
            "label": period,
        }
    
    # Monthly: YYYY-MM (e.g. 2025-04)
    import re as _re
    if _re.match(r'^\d{4}-\d{2}$', period):
        year, month = period.split("-")
        m = int(month)
        import calendar as _cal
        last_day = _cal.monthrange(int(year), m)[1]
        return {
            "start": f"{year}-{month.zfill(2)}-01",
            "end":   f"{year}-{month.zfill(2)}-{last_day:02d}",
            "label": period,
        }

    raise ValueError(
        f"Unrecognized period format: '{period}'. "
        f"Use: 2025-04, Q1-2025, H1-2025, or 2025"
    )
