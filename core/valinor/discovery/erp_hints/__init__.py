"""
ERP Hint Pack loader — provides ERP-specific naming conventions and patterns
for the Cartographer's schema discovery.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

_HINTS_DIR = Path(__file__).parent


def load_hint_pack(country: str, erp_type: str) -> Dict[str, Any]:
    """Load ERP-specific naming conventions and patterns.

    Resolution order:
      1. {country}_{erp_type}.yaml  (e.g. argentina_gestion.yaml)
      2. {country}.yaml             (e.g. argentina.yaml)
      3. generic.yaml
      4. empty dict (graceful degradation)

    Returns:
        Dict with keys like naming_conventions, table_patterns, fiscal_patterns, etc.
        Empty dict if no hint pack is found.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("erp_hints: PyYAML not installed, returning empty hint pack")
        return {}

    candidates = [
        _HINTS_DIR / f"{country}_{erp_type}.yaml",
        _HINTS_DIR / f"{country}.yaml",
        _HINTS_DIR / "generic.yaml",
    ]

    for path in candidates:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                logger.info("erp_hints: loaded hint pack from %s", path.name)
                return data if isinstance(data, dict) else {}
            except Exception as exc:
                logger.warning("erp_hints: failed to parse %s: %s", path.name, exc)
                continue

    logger.debug("erp_hints: no hint pack found for country=%s erp_type=%s", country, erp_type)
    return {}
