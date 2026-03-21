"""
MCP Servers for Valinor SaaS.

Each module here exposes a FastMCP server wrapping a specific integration.
Use @mcp.tool() to expose tools that agents can call via MCP protocol.

Available servers:
- etendo_server: Etendo ERP integration via SSH tunnel
"""
