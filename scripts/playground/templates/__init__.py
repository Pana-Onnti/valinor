"""
Playground Swarm — Schema templates.

Provides SQLite schema creators for Etendo, Odoo, and generic ERP models.
"""

from scripts.playground.templates.etendo_schema import (
    create_etendo_schema,
    get_table_names as get_etendo_table_names,
)
from scripts.playground.templates.odoo_schema import (
    create_odoo_schema,
    get_table_names as get_odoo_table_names,
)
from scripts.playground.templates.generic_erp import (
    create_generic_schema,
    get_table_names as get_generic_table_names,
)

__all__ = [
    "create_etendo_schema",
    "get_etendo_table_names",
    "create_odoo_schema",
    "get_odoo_table_names",
    "create_generic_schema",
    "get_generic_table_names",
]
