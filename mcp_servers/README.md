# MCP Servers — Valinor SaaS

Each file in this directory is a **FastMCP server** that wraps a specific external
integration (ERP, API, database, etc.) and exposes it as standard MCP tools.

## Pattern for new MCP servers

```python
# mcp_servers/my_integration_server.py
import sys
from pathlib import Path
from fastmcp import FastMCP

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

mcp = FastMCP(
    name="my-integration-server",
    instructions="Description of what this server does.",
)

@mcp.tool()
def my_tool(param: str) -> dict:
    """Tool description — shown to the agent."""
    # implementation
    return {"result": ...}

if __name__ == "__main__":
    mcp.run()  # stdio mode for Claude Desktop
```

## Available servers

| Server | File | Description |
|--------|------|-------------|
| etendo-server | `etendo_server.py` | Etendo ERP via SSH tunnel: list tables, describe schema, execute SELECT |

## Running a server (Claude Desktop config)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "etendo": {
      "command": "python",
      "args": ["-m", "mcp_servers.etendo_server"],
      "cwd": "/path/to/valinor-saas",
      "env": {
        "ETENDO_SSH_HOST": "bastion.client.com",
        "ETENDO_SSH_USER": "readonly",
        "ETENDO_SSH_KEY_PATH": "/keys/client_rsa",
        "ETENDO_DB_HOST": "db.internal",
        "ETENDO_DB_PORT": "5432",
        "ETENDO_DB_CONN_STR": "postgresql://user:pass@db.internal:5432/etendo"
      }
    }
  }
}
```

## Adding future integrations

Planned servers:
- `afip_server.py` — AFIP (Argentina tax agency) REST API
- `bcr_server.py` — Banco Central de la República Argentina rates API
- `shopify_server.py` — Shopify orders + customers
- `hubspot_server.py` — HubSpot CRM contacts + deals

Each follows the same pattern: wrap existing connector/client in `@mcp.tool()`.
