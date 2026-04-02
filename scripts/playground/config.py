"""
Playground Swarm — Configuration.

Central settings for dataset generation, API endpoints, and public data sources.
"""

from pathlib import Path
from typing import Dict, Any

# ── Paths ──────────────────────────────────────────────────────────────
DATASETS_DIR: Path = Path(__file__).parent / "datasets"
REPORTS_DIR: Path = Path(__file__).parent / "reports"

# ── Valinor API ────────────────────────────────────────────────────────
API_BASE_URL: str = "http://localhost:8000"

# ── Agent intervals (seconds) ─────────────────────────────────────────
SMOKER_INTERVAL: int = 30
AUDITOR_INTERVAL: int = 60

# ── Concurrency ───────────────────────────────────────────────────────
MAX_CONCURRENT_JOBS: int = 3

# ── Gloria DB (local) ─────────────────────────────────────────────────
DB_CONFIG: Dict[str, Any] = {
    "host": "localhost",
    "port": 5432,
    "name": "gloria",
    "type": "postgres",
    "user": "tad",
    "password": "tad",
}

# ── Public data sources ───────────────────────────────────────────────
PUBLIC_DATA_SOURCES: Dict[str, str] = {
    "SEC EDGAR": "https://efts.sec.gov/LATEST/search-index?q=*&dateRange=custom",
    "World Bank API": "https://api.worldbank.org/v2/country/all/indicator",
    "Eurostat": "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data",
}
