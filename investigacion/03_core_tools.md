# Investigacion 03 — Core Tools (`core/valinor/tools/`)

## Resumen

El paquete `core/valinor/tools/` implementa **14 herramientas** organizadas en 4 modulos, registradas como MCP servers in-process mediante el decorador `@tool` de `claude-agent-sdk`. Estas tools son funciones async que reciben un dict `args` y retornan un dict MCP con formato `{"content": [{"type": "text", "text": "..."}]}`. Solo el agente Cartographer las usa directamente via `create_sdk_mcp_server`; los demas agentes (Analyst, Sentinel, Hunter, Narrators) trabajan con datos pre-computados sin acceso directo a tools.

**Ubicacion real**: `core/valinor/tools/` (no `core/tools/` — el paquete `valinor` es el namespace).

---

## Catalogo de Tools

### `db_tools.py` — 6 herramientas de base de datos

| Tool | Descripcion | Parametros |
|------|-------------|------------|
| `connect_database` | Conecta a BD, verifica acceso read-only, retorna schemas y tablas | `connection_string`, `client_name` |
| `introspect_schema` | Introspection profunda: columnas, tipos, PK, FK, indices, row count | `connection_string`, `table_name`, `schema` |
| `sample_table` | Muestra N filas de una tabla para data discovery | `connection_string`, `table_name`, `schema`, `limit` |
| `classify_entity` | Clasifica tabla como MASTER/TRANSACTIONAL/CONFIG/BRIDGE via heuristicas | `table_name`, `columns`, `sample_data`, `row_count` |
| `probe_column_values` | SELECT DISTINCT con COUNT — descubre valores reales de columnas discriminadoras | `connection_string`, `table_name`, `column_name`, `schema` |
| `execute_query` | Ejecuta SQL read-only con limites de seguridad (bloquea INSERT/UPDATE/DELETE/DROP/etc.) | `connection_string`, `sql`, `max_rows` |

### `analysis_tools.py` — 3 herramientas de calculo

| Tool | Descripcion | Parametros |
|------|-------------|------------|
| `revenue_calc` | Agrega revenue por periodo, calcula MoM/YoY, totales, promedios | `data`, `group_by`, `amount_field` |
| `aging_calc` | Buckets de aging para cuentas por cobrar/pagar con tasas de provision | `data`, `due_date_field`, `amount_field`, `reference_date` |
| `pareto_analysis` | Analisis de concentracion: top-N, indice Herfindahl, nivel de riesgo | `data`, `entity_field`, `value_field`, `top_n` |

### `excel_tools.py` — 2 herramientas de ingesta

| Tool | Descripcion | Parametros |
|------|-------------|------------|
| `excel_to_sqlite` | Convierte .xlsx/.xls a SQLite (cada sheet = tabla) | `file_path`, `client_name` |
| `csv_to_sqlite` | Convierte .csv a SQLite (tabla unica) | `file_path`, `client_name`, `table_name` |

### `memory_tools.py` — 3 herramientas de persistencia

| Tool | Descripcion | Parametros |
|------|-------------|------------|
| `read_memory` | Lee memoria de swarm previa de un cliente (por periodo o la mas reciente) | `client_name`, `period` |
| `write_memory` | Escribe/actualiza memoria de swarm con metadata automatica | `client_name`, `period`, `memory_data` |
| `write_artifact` | Escribe artefacto de output (entity_map, findings, report) | `client_name`, `period`, `filename`, `content` |

---

## Interfaz

### Patron de registro

Todas las tools usan el decorador `@tool` de `claude_agent_sdk`:

```python
from claude_agent_sdk import tool

@tool(
    "nombre_de_la_tool",           # nombre MCP
    "Descripcion para el agente",   # description string
    {                               # schema de parametros (dict simple tipo: type)
        "param1": str,
        "param2": int,
    },
)
async def nombre_de_la_tool(args):  # siempre recibe dict `args`
    # ... logica ...
    return {
        "content": [
            {"type": "text", "text": json.dumps(resultado, indent=2)}
        ]
    }
```

### Contrato de retorno

Todas retornan un dict MCP estandar:
```python
{"content": [{"type": "text", "text": "<JSON serializado>"}]}
```

En caso de error:
```python
{"content": [{"type": "text", "text": json.dumps({"error": "mensaje"})}]}
```

### Convenciones clave

- **Todas son async** (aunque muchas no hacen I/O async real — SQLAlchemy sync bajo el capot).
- **Parametros via `args` dict** — no keyword arguments, se acceden con `args["key"]` o `args.get("key", default)`.
- **Serialization manual** — cada tool convierte tipos no-standard a string antes de serializar.
- **Engine lifecycle** — cada tool crea y dispone su propio `engine`. No hay connection pooling compartido.

---

## Registro y Exposicion a Agentes

### Mecanismo: `create_sdk_mcp_server`

Las tools se exponen a agentes LLM a traves de `create_sdk_mcp_server` de `claude_agent_sdk`:

```python
from claude_agent_sdk import create_sdk_mcp_server

tools_server = create_sdk_mcp_server(
    name="cartographer-tools",
    version="1.0.0",
    tools=[
        connect_database,
        introspect_schema,
        sample_table,
        classify_entity,
        probe_column_values,
        write_artifact,
    ],
)

options = ClaudeAgentOptions(
    model="sonnet",
    mcp_servers={"tools": tools_server},
    allowed_tools=[
        "mcp__tools__connect_database",
        "mcp__tools__introspect_schema",
        # ...
    ],
)
```

Los nombres MCP siguen el patron `mcp__<server_name>__<tool_name>`, donde `<server_name>` es el key del dict `mcp_servers` (en este caso "tools").

### Invocacion directa (sin MCP)

`run.py` invoca `excel_to_sqlite` y `csv_to_sqlite` directamente como funciones Python (sin pasar por MCP):

```python
from valinor.tools.excel_tools import excel_to_sqlite
result = await excel_to_sqlite({"file_path": source_path, "client_name": client})
```

---

## Uso por Agentes

| Agente | Tools que usa | Mecanismo |
|--------|--------------|-----------|
| **Cartographer** | `connect_database`, `introspect_schema`, `sample_table`, `classify_entity`, `probe_column_values`, `write_artifact` | MCP server in-process (`create_sdk_mcp_server`) |
| **run.py (pipeline)** | `excel_to_sqlite`, `csv_to_sqlite` | Invocacion directa Python |
| **pipeline.py** | `execute_query` (reimplementado inline) | No usa la tool — tiene su propia implementacion con REPEATABLE READ |
| **Analyst** | Ninguna directamente | Recibe `query_results` pre-ejecutados |
| **Sentinel** | Ninguna directamente | Recibe `query_results` pre-ejecutados |
| **Hunter** | Ninguna directamente | Recibe `query_results` pre-ejecutados |
| **Narrators** | Ninguna directamente | Reciben `findings` y `reports` |

### Observacion critica

- **`analysis_tools.py`** (`revenue_calc`, `aging_calc`, `pareto_analysis`) **no es usado por ningun agente ni modulo**. Las 3 tools estan definidas pero no se importan en ningun otro archivo del proyecto. Son "dead code" funcional — probablemente diseñadas para uso futuro cuando los agentes de analisis se conecten a MCP tools.
- **`execute_query`** tampoco se usa como tool MCP — `pipeline.py` tiene su propia version con aislamiento REPEATABLE READ y safety checks mas robustos.
- **`read_memory` y `write_memory`** no se usan como tools MCP — la memoria se gestiona directamente en `run.py` y `config.py` via filesystem.

---

## Extensibilidad

### Agregar una nueva tool

1. Crear funcion async con decorador `@tool(name, description, schema)` en el modulo correspondiente (o nuevo archivo `.py`).
2. Importarla en el agente que la necesite.
3. Agregarla a la lista `tools=[...]` de `create_sdk_mcp_server`.
4. Agregar `"mcp__<server>__<nombre>"` a `allowed_tools`.

### Limitaciones del patron actual

- **Schema de parametros primitivo**: El dict `{param: type}` no soporta parametros opcionales, validacion, ni tipos complejos. No hay Pydantic ni JSON Schema.
- **No hay registry centralizado**: Cada agente importa y monta sus tools manualmente. No hay auto-discovery.
- **No hay middleware**: No hay hooks pre/post ejecucion (logging, rate limiting, auth).
- **Sin tests de integracion del registro MCP**: Los tests unitarios prueban las funciones Python directamente, no el flujo MCP completo.

---

## Fortalezas

1. **Seguridad read-only**: `execute_query` bloquea operaciones de escritura (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE). Validacion por prefijo SQL.
2. **Patron Schema-Then-Data**: El Cartographer ejecuta un pre-scan determinista (Phase 1) sin LLM antes de invocar tools via MCP (Phase 2). Reduce costos y mejora precision.
3. **Clasificacion heuristica**: `classify_entity` usa señales multiples (nombre de tabla, columnas, row count) con scoring de confianza. No depende del LLM para clasificacion inicial.
4. **Probe de valores reales**: `probe_column_values` implementa el patron ReFoRCE — verifica valores reales de la BD antes de construir filtros. Evita filtros inventados.
5. **Provision rates configurados**: `aging_calc` incluye tasas de provision progresivas (0% a 90%) por bucket de aging — listo para reportes financieros.
6. **Indice Herfindahl**: `pareto_analysis` calcula HHI ademas del ranking, dando una medida cuantitativa de concentracion.
7. **Ingesta flexible**: Soporte para Excel multi-sheet y CSV con conversion automatica a SQLite.
8. **Memoria cross-run**: `read_memory`/`write_memory` permiten aprendizaje incremental entre ejecuciones.
9. **Respuesta MCP estandar**: Todas las tools siguen el mismo contrato de retorno, facilitando composicion.

---

## Debilidades

1. **3 de 14 tools son dead code**: `revenue_calc`, `aging_calc`, `pareto_analysis` no se usan en ningun flujo. `execute_query`, `read_memory`, `write_memory` tampoco se usan como tools MCP (se reimplementan o se invocan diferente).
2. **SQL injection potencial**: `probe_column_values` y `sample_table` interpolan nombres de columna/tabla directamente en SQL strings (`f'SELECT "{column}"...'`). Aunque estan quoted, no hay validacion de que los nombres sean identificadores seguros. `pipeline.py` tiene `_is_safe_identifier()` pero las tools no.
3. **Sin connection pooling**: Cada invocacion de tool crea un `create_engine()` nuevo y lo dispone. En un flujo con 20+ llamadas a tools de BD, esto genera overhead de conexiones.
4. **Bypass de seguridad en `execute_query`**: Solo valida por `startswith()` — un SQL como `WITH cte AS (DELETE ...)` o `SELECT * FROM t; DROP TABLE t` podria pasar la validacion.
5. **Sin timeout de queries**: No hay limite de tiempo para queries SQL. Una query costosa podria bloquear el agente indefinidamente.
6. **Limite de filas fijo**: `execute_query` defaultea a 1000 rows pero no estima el tamaño del resultado en memoria. Datasets grandes podrian causar OOM.
7. **Encoding hardcodeado**: `csv_to_sqlite` asume UTF-8 y `on_bad_lines="skip"` silenciosamente descarta lineas problematicas sin reportar cuantas.
8. **`write_artifact` sin validacion**: Acepta cualquier filename sin sanitizar. Path traversal teoricamente posible (`../../etc/passwd`).
9. **Memory tools usan MEMORY_DIR global**: No es configurable per-run, lo que dificulta testing y multi-tenancy.
10. **Sin tipado fuerte de retorno**: Las tools retornan `dict` generico. No hay dataclasses/Pydantic para los resultados.

---

## Recomendaciones

### Prioridad Alta

1. **Activar `analysis_tools.py`**: Conectar `revenue_calc`, `aging_calc` y `pareto_analysis` al agente Analyst via MCP server. Reducira tokens LLM al delegar calculos deterministas.
2. **Sanitizar SQL identifiers**: Aplicar `_is_safe_identifier()` (ya existe en `pipeline.py`) a todas las tools que interpolan nombres de tabla/columna. Crear un util compartido.
3. **Fortalecer `execute_query`**: Usar un parser SQL (sqlparse) o al menos buscar keywords prohibidos en todo el string, no solo al inicio. Agregar statement-level timeout.
4. **Connection pooling**: Crear un engine registry por `connection_string` que reutilice engines con pool configurado. Inyectarlo en las tools via parametro o singleton.

### Prioridad Media

5. **Unificar `execute_query`**: Eliminar la reimplementacion en `pipeline.py` y hacer que use la tool (con opciones de isolation level). O bien, marcar la tool como deprecated y usar solo pipeline.
6. **Sanitizar `write_artifact` filename**: Validar que el filename no contenga `..` ni separadores de path. Usar `Path.name` para forzar nombre plano.
7. **Registry centralizado de tools**: Crear un modulo `tool_registry.py` que auto-descubra tools por modulo y las agrupe por categoria. Simplifica el montaje en agentes.
8. **Reportar lineas descartadas en CSV**: `csv_to_sqlite` deberia contar y retornar cuantas lineas se saltaron por errores de parsing.

### Prioridad Baja

9. **Pydantic schemas para tools**: Reemplazar `{param: type}` con modelos Pydantic que soporten opcionales, validacion, y documentacion.
10. **Middleware de logging**: Agregar decorador que loguee cada invocacion de tool (nombre, duracion, tamaño de respuesta) para observabilidad.
11. **Tests de integracion MCP**: Probar el flujo completo `create_sdk_mcp_server` → `query()` → tool execution, no solo las funciones Python aisladas.
12. **Timeout configurable**: Agregar parametro `timeout_seconds` a las tools de BD con `statement_timeout` a nivel SQL.

---

## Archivos Relevantes

| Archivo | Rol |
|---------|-----|
| `core/valinor/tools/__init__.py` | Package — docstring unico |
| `core/valinor/tools/db_tools.py` | 6 tools de BD |
| `core/valinor/tools/analysis_tools.py` | 3 tools de calculo (sin uso actual) |
| `core/valinor/tools/excel_tools.py` | 2 tools de ingesta |
| `core/valinor/tools/memory_tools.py` | 3 tools de persistencia |
| `core/valinor/agents/cartographer.py` | Unico agente que usa tools via MCP |
| `core/valinor/run.py` | Pipeline principal — invoca excel_tools directamente |
| `core/valinor/pipeline.py` | Reimplementa execute_query con REPEATABLE READ |
| `core/valinor/config.py` | Define MEMORY_DIR y OUTPUT_DIR usados por memory_tools |
| `tests/test_db_tools.py` | Tests unitarios db_tools |
| `tests/test_analysis_tools.py` | Tests unitarios analysis_tools |
| `tests/test_excel_tools.py` | Tests unitarios excel_tools |
| `tests/test_memory_tools.py` | Tests unitarios memory_tools |
