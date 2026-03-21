# Supported Data Sources — Valinor SaaS

This document lists all data sources that Valinor can connect to via the
`shared/connectors/` layer (VAL-33).

## Currently available

| Source Type | Class | Connection String Format | Notes |
|-------------|-------|--------------------------|-------|
| `postgresql` | `PostgreSQLConnector` | `postgresql+psycopg2://user:pass@host:5432/db` | Also: `postgres`, `pg` alias |
| `mysql` | `MySQLConnector` | `mysql+pymysql://user:pass@host:3306/db` | Also: `mariadb` alias |
| `etendo` | `EtendoConnector` | `postgresql+psycopg2://user:pass@db-internal:5432/etendo` + SSH config | Etendo ERP via SSH tunnel |

## Usage example

```python
from shared.connectors import ConnectorFactory

# PostgreSQL
connector = ConnectorFactory.create("postgresql", {
    "connection_string": "postgresql+psycopg2://analyst:pass@db.client.com:5432/prod"
})
with connector:
    schema = connector.get_schema()
    rows = connector.execute_query("SELECT COUNT(*) FROM c_invoice")

# MySQL / MariaDB
connector = ConnectorFactory.create("mysql", {
    "connection_string": "mysql+pymysql://analyst:pass@db.client.com:3306/prod"
})

# Etendo (PostgreSQL over SSH tunnel)
connector = ConnectorFactory.create("etendo", {
    "connection_string": "postgresql+psycopg2://user:pass@db-internal:5432/etendo",
    "ssh_host": "bastion.client.com",
    "ssh_user": "readonly",
    "ssh_key_path": "/keys/client_rsa",
    "db_host": "db-internal",
    "db_port": 5432,
})
with connector:
    schema = connector.get_schema()
```

## Adding a new connector

1. Create `shared/connectors/my_source.py` subclassing `DeltaConnector`
2. Implement `connect()`, `close()`, `execute_query()`, `get_schema()`
3. Add `SourceType.MY_SOURCE = "my_source"` to `base.py`
4. Register in `factory.py` `_CONNECTOR_REGISTRY`
5. Add to `__init__.py` exports
6. Add tests in `tests/test_connectors.py`
7. Document here

## Roadmap

| Source | Priority | Notes |
|--------|----------|-------|
| SAP HANA | High | Large enterprise market |
| Microsoft SQL Server | High | Windows-heavy enterprises |
| Oracle Database | Medium | Legacy ERP market |
| BigQuery | Medium | Analytics-first clients |
| Snowflake | Medium | Cloud data warehouse |
| MongoDB | Low | Document stores |
| Salesforce | High | CRM data integration |
| HubSpot | Medium | SMB CRM |

Each new connector unblocks a new market segment.
