# 08 — MCP Servers: Servidor Etendo y Protocolo MCP

**Fecha:** 2026-03-22
**Scope:** `/mcp_servers/`, integración con `shared/`, `core/`, tests

---

## Resumen

El directorio `mcp_servers/` contiene un servidor MCP (Model Context Protocol) basado en **FastMCP >=2.2.0** que expone operaciones de base de datos del ERP Etendo como herramientas invocables por agentes LLM. Actualmente hay un solo servidor (`etendo_server.py`) con 3 tools. El diseño sigue un patrón claro: cada archivo del directorio es un servidor MCP independiente que wrappea un conector existente. La arquitectura es extensible -- el README documenta 4 servidores futuros planificados (AFIP, BCR, Shopify, HubSpot).

---

## Servidor Etendo (`etendo_server.py`)

### Instancia FastMCP

```python
mcp = FastMCP(
    name="etendo-server",
    instructions="MCP server for Etendo ERP. Provides tools to connect to an Etendo PostgreSQL "
                 "database via SSH tunnel, introspect its schema, and execute read-only queries.",
)
```

### Configuracion

La funcion `_get_etendo_config()` construye `ssh_config` y `db_config` con fallback a variables de entorno:

| Parametro | Env var | Default |
|-----------|---------|---------|
| `ssh_host` | `ETENDO_SSH_HOST` | `""` |
| `ssh_user` | `ETENDO_SSH_USER` | `""` |
| `ssh_key_path` | `ETENDO_SSH_KEY_PATH` | `""` |
| `db_host` | `ETENDO_DB_HOST` | `"localhost"` |
| `db_port` | `ETENDO_DB_PORT` | `5432` |
| `db_connection_string` | `ETENDO_DB_CONN_STR` | `""` |

### Modos de conexion

1. **Con SSH tunnel** -- cuando `ssh_host` y `ssh_key_path` estan presentes, usa `SSHTunnelManager` de `shared/ssh_tunnel.py`. Cada tool crea su propio tunnel efimero con un `job_id` unico.
2. **Conexion directa** -- cuando no hay SSH config, usa el `connection_string` directamente con SQLAlchemy.

### Ejecucion

- **stdio mode:** `python -m mcp_servers.etendo_server` (compatible con Claude Desktop)
- **Programatico:** `from mcp_servers.etendo_server import mcp`

---

## Protocolo MCP

### Transporte

El servidor usa el protocolo **stdio** de MCP: se ejecuta como subproceso y se comunica via stdin/stdout con mensajes JSON-RPC. Esto lo hace compatible con Claude Desktop y con el Claude Agent SDK.

### Dependencias

- `mcp>=1.8.0` -- SDK base del protocolo MCP
- `fastmcp>=2.2.0` -- wrapper de alto nivel con decoradores `@mcp.tool()`

### Configuracion para Claude Desktop

```json
{
  "mcpServers": {
    "etendo": {
      "command": "python",
      "args": ["-m", "mcp_servers.etendo_server"],
      "cwd": "/path/to/valinor-saas",
      "env": { "ETENDO_SSH_HOST": "...", "ETENDO_DB_CONN_STR": "..." }
    }
  }
}
```

### Patron de registro de tools

Cada tool se registra con `@mcp.tool()`. FastMCP genera automaticamente el JSON Schema a partir de los type hints de Python. El agente ve la docstring como descripcion y los parametros tipados como inputs.

---

## Tools Expuestas

### 1. `etendo_list_tables`

| Aspecto | Detalle |
|---------|---------|
| **Proposito** | Listar todas las tablas de un schema |
| **Parametros clave** | `schema` (default `"public"`), config SSH/DB |
| **Retorno OK** | `{"tables": [...], "schema": "...", "count": N}` |
| **Retorno error** | `{"error": "..."}` |
| **Mecanismo** | `sqlalchemy.inspect().get_table_names()` |

### 2. `etendo_describe_table`

| Aspecto | Detalle |
|---------|---------|
| **Proposito** | Describir columnas y tipos de una tabla |
| **Parametros clave** | `table_name` (requerido), `schema` |
| **Retorno OK** | `{"table": "...", "schema": "...", "columns": [{"name": ..., "type": ...}]}` |
| **Retorno error** | `{"error": "..."}` |
| **Mecanismo** | `sqlalchemy.inspect().get_columns()` |

### 3. `etendo_execute_query`

| Aspecto | Detalle |
|---------|---------|
| **Proposito** | Ejecutar queries SQL de solo lectura |
| **Parametros clave** | `sql` (requerido), `max_rows` (default 100, cap 1000) |
| **Retorno OK** | `{"columns": [...], "rows": [[...]], "row_count": N}` |
| **Retorno error** | `{"error": "..."}` |
| **Safety check** | Solo permite sentencias que empiecen con `SELECT` |
| **Mecanismo** | `sqlalchemy.text()` + `conn.execute()` + `fetchmany(max_rows)` |

---

## Integracion con Core

### Relacion con el Conector Etendo (`shared/connectors/etendo.py`)

El servidor MCP y el conector Etendo son **capas paralelas, no dependientes entre si**:

- `shared/connectors/etendo.py` -- `EtendoConnector` extiende `PostgreSQLConnector`. Usado por el pipeline interno (API, jobs).
- `mcp_servers/etendo_server.py` -- reimplementa la logica de conexion usando directamente `SSHTunnelManager` y SQLAlchemy. No importa `EtendoConnector`.

Ambos comparten la dependencia en `shared/ssh_tunnel.py` (`SSHTunnelManager`).

### Relacion con Agentes (`core/valinor/agents/cartographer.py`)

El Cartographer agent usa `create_sdk_mcp_server()` del Claude Agent SDK para exponer sus propias tools (db_tools, memory_tools) como servidor MCP in-process. **No consume el servidor Etendo MCP directamente** -- usa sus propias herramientas de base de datos. Sin embargo, el patron de MCP servers es el mismo.

### Flujo de datos

```
Claude Desktop / Agent
    |
    v (stdio JSON-RPC)
etendo_server.py (FastMCP)
    |
    v
SSHTunnelManager (shared/ssh_tunnel.py)
    |
    v (SSH tunnel)
PostgreSQL (Etendo ERP)
```

---

## Tests (`tests/test_fastmcp_etendo.py`)

- **222 lineas**, 10 test cases con mocks completos
- Verifican: instancia MCP, list_tables (con y sin tunnel), describe_table, execute_query
- Safety checks: rechazo de DELETE, INSERT, UPDATE; cap de max_rows a 1000
- Todos los tests usan mocks de SQLAlchemy -- no requieren conexion real
- Referenciados como VAL-28

---

## Fortalezas

1. **Patron claro y replicable.** El README documenta un template para crear nuevos servidores MCP. Cualquier integracion futura sigue el mismo esquema: `FastMCP` + `@mcp.tool()` + `__main__`.

2. **Safety-first en queries.** Solo permite SELECT, con cap en max_rows (1000). Previene modificaciones accidentales al ERP.

3. **Doble modo de conexion.** SSH tunnel para produccion, conexion directa para desarrollo/testing. La decision es automatica segun la presencia de parametros SSH.

4. **Fallback a env vars.** Todos los parametros de conexion aceptan valores explicitos o variables de entorno, facilitando la configuracion en diferentes entornos.

5. **Compatibilidad con Claude Desktop.** El modo stdio permite que el servidor se use directamente desde Claude Desktop sin infraestructura adicional.

6. **Tests solidos.** Buena cobertura de los 3 tools y de los edge cases de seguridad.

7. **Logging estructurado.** Usa `structlog` consistente con el resto del proyecto.

---

## Debilidades

1. **Duplicacion de logica de conexion.** `etendo_server.py` reimplementa la logica de SSH tunnel + SQLAlchemy en lugar de reutilizar `EtendoConnector` de `shared/connectors/etendo.py`. Esto significa que cualquier fix o mejora al conector debe replicarse manualmente en el servidor MCP.

2. **Tunnel efimero por cada tool call.** Cada invocacion de tool crea y destruye un SSH tunnel. En una sesion donde un agente llama multiples tools en secuencia (list_tables -> describe_table -> execute_query), esto genera 3 conexiones SSH separadas. No hay connection pooling ni reutilizacion de tunnel.

3. **Validacion SQL naive.** El check `sql.strip().upper().startswith("SELECT")` es facilmente evadible con CTEs (`WITH ... AS (DELETE ...)`), o con `SELECT` seguido de subqueries destructivas via funciones PostgreSQL (`SELECT lo_unlink(...)`, `SELECT pg_terminate_backend(...)`). No hay parsing real del SQL.

4. **Sin autenticacion MCP.** El servidor stdio no implementa autenticacion propia. La seguridad depende enteramente del control de acceso al proceso (quien puede ejecutarlo) y de las credenciales de la DB.

5. **Sin rate limiting ni audit log.** No hay control de frecuencia de llamadas ni registro persistente de queries ejecutadas por agentes. En un contexto multi-tenant, esto es un gap de compliance.

6. **Solo un servidor implementado.** De los 5 planificados (Etendo, AFIP, BCR, Shopify, HubSpot), solo Etendo existe. Los demas son placeholders en el README.

7. **Sin MCP Resources ni Prompts.** FastMCP soporta `@mcp.resource()` y `@mcp.prompt()` ademas de `@mcp.tool()`. El servidor solo usa tools. Podria exponer resources (schema cache, metadata) y prompts (templates de queries comunes).

8. **No hay integracion directa con el pipeline de agentes.** El Cartographer y otros agentes del core usan sus propias herramientas via `create_sdk_mcp_server()` in-process. El servidor Etendo MCP es una isla -- solo accesible via Claude Desktop, no desde el pipeline de agentes internos.

---

## Recomendaciones 2026

### Corto plazo (Q2 2026)

1. **Reutilizar `EtendoConnector`** dentro de `etendo_server.py` en lugar de reimplementar la logica de conexion. Eliminar duplicacion:
   ```python
   @mcp.tool()
   def etendo_list_tables(...):
       connector = EtendoConnector(config)
       connector.connect()
       tables = connector.list_tables(schema)
       connector.close()
       return {"tables": tables}
   ```

2. **Implementar connection pooling por sesion.** Mantener un tunnel abierto durante la sesion MCP en lugar de crear uno por cada tool call. Usar el context manager de `SSHTunnelManager` a nivel de servidor, no de tool.

3. **Mejorar la validacion SQL.** Reemplazar el check naive por un parser SQL real (e.g., `sqlglot` o `sqlparse`). Verificar que el AST contenga solo SELECT, sin side effects:
   ```python
   import sqlglot
   parsed = sqlglot.parse(sql)
   if any(not isinstance(stmt, sqlglot.exp.Select) for stmt in parsed):
       return {"error": "Only SELECT allowed"}
   ```

4. **Agregar audit logging.** Registrar cada query ejecutada via MCP con timestamp, usuario (si disponible), SQL, y row_count. Almacenar en la tabla de audit del sistema.

### Mediano plazo (Q3-Q4 2026)

5. **Integrar con el pipeline de agentes.** Permitir que agentes internos (Cartographer, etc.) consuman el servidor Etendo MCP via el protocolo estandar en lugar de usar tools ad-hoc. Esto unifica la capa de acceso a datos.

6. **Implementar los servidores planificados.** Priorizar `afip_server.py` y `bcr_server.py` (necesidades fiscales argentinas), luego `shopify_server.py` y `hubspot_server.py`.

7. **Agregar MCP Resources.** Exponer metadata como resources cacheados:
   - `etendo://schema/{schema_name}` -- schema completo en JSON
   - `etendo://tables/{table_name}/sample` -- sample de datos
   - `etendo://metadata/last_sync` -- timestamp de ultima sincronizacion

8. **Implementar autenticacion.** Cuando MCP soporte auth nativo (en desarrollo en el SDK), agregar tokens por cliente para el modo HTTP/SSE.

### Largo plazo

9. **MCP Gateway.** Un servidor MCP unificado que componga todos los sub-servidores (Etendo, AFIP, BCR, etc.) bajo un unico endpoint. Simplifica la configuracion del agente.

10. **Modo SSE/HTTP ademas de stdio.** Para despliegues en la nube donde el servidor MCP no corre como subproceso local sino como servicio remoto.

---

## Archivos clave

| Archivo | Rol |
|---------|-----|
| `mcp_servers/etendo_server.py` | Servidor MCP principal, 3 tools |
| `mcp_servers/__init__.py` | Package init, docstring |
| `mcp_servers/README.md` | Documentacion, template, servidores planificados |
| `shared/ssh_tunnel.py` | SSHTunnelManager compartido |
| `shared/connectors/etendo.py` | EtendoConnector (pipeline, no MCP) |
| `core/valinor/agents/cartographer.py` | Ejemplo de agente que usa MCP pattern in-process |
| `tests/test_fastmcp_etendo.py` | 10 tests con mocks, VAL-28 |
| `requirements.txt` | `mcp>=1.8.0`, `fastmcp>=2.2.0` |
