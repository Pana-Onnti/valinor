# 09 - Security Suite: Analisis Exhaustivo

**Fecha:** 2026-03-22
**Scope:** `security/`, `shared/connectors/`, `api/routers/nl_query.py`, `core/valinor/nl/vanna_adapter.py`
**Issue:** VAL-34

---

## Resumen

La security suite de Valinor SaaS implementa un enfoque defensivo de tres capas contra ataques adversariales en un sistema que procesa datos financieros sensibles de clientes via NL-to-SQL (Vanna AI + Anthropic). La suite consta de:

- **30 payloads adversariales** organizados en `adversarial_inputs.py` (12 prompt injection, 8 tenant isolation, 10 SQL safety)
- **~30 tests** en `test_prompt_injection.py` cubriendo SQL safety, validacion de input NL, y deteccion de patrones peligrosos
- **~10 tests** en `test_tenant_isolation.py` verificando aislamiento de tenants via entity_map, adapters per-tenant, y filtros base
- **Controles de connector** en `shared/connectors/base.py` con `_require_select()` como gate de solo-lectura

La postura de seguridad es **razonablemente solida para una etapa alpha/beta**, con brechas criticas identificadas en la capa NL-to-SQL y ausencia de autenticacion/autorizacion en la API.

---

## Tests Adversariales

### Inventario de Payloads (`adversarial_inputs.py`)

| Categoria | IDs | Cantidad | Descripcion |
|-----------|-----|----------|-------------|
| Direct Injection | PI-001 a PI-003 | 3 | System prompt extraction, role override, instruction termination |
| Data-Embedded Injection | PI-004 a PI-006 | 3 | SQL injection en campos de datos, LLM instruction en invoice, XSS |
| Jailbreak | PI-007 a PI-009 | 3 | Hypothetical framing, token smuggling, repetition coercion |
| SQL Injection via NL | PI-010 a PI-012 | 3 | UNION-based, time-based (pg_sleep), comment-based injection |
| Tenant Bypass | TI-001 a TI-004 | 4 | Cross-tenant request, wildcard, admin escalation, null tenant |
| Data Leakage | TI-005 a TI-006 | 2 | Indirect cross-tenant aggregation, subquery access |
| Privilege Escalation | TI-007 a TI-008 | 2 | Write access, DDL requests |
| SQL Safety | SS-001 a SS-010 | 10 | DELETE, DROP, TRUNCATE, UPDATE, INSERT, COPY, pg_read_file, pg_shadow |

### Patron de Deteccion de SQL Peligroso

`DANGEROUS_SQL_PATTERNS` contiene 20+ patrones incluyendo:
- DDL/DML: DROP, DELETE, TRUNCATE, INSERT, UPDATE, CREATE, ALTER, GRANT, REVOKE
- Funciones peligrosas: pg_read_file, pg_sleep, lo_import, lo_export, dblink
- Tablas sensibles: pg_shadow, pg_authid, pg_user, pg_roles
- Inyeccion: UNION SELECT, COPY TO/FROM

---

## Prompt Injection Defense

### Capas de Defensa Implementadas

1. **Validacion de Input (Pydantic):** `NLQueryRequest` valida `question` con `min_length=3, max_length=500`. Rechaza inputs vacios, muy cortos o excesivamente largos.

2. **SQL Safety Checker (`is_safe_sql`):** Funcion que analiza SQL generado buscando:
   - Statements peligrosos al inicio de la query (DROP, DELETE, etc.)
   - Keywords inline (COPY TO/FROM)
   - Funciones peligrosas (pg_read_file, pg_sleep, dblink)
   - Acceso a tablas sensibles del sistema (pg_shadow, pg_authid)

3. **Injection Success Indicator Detection (`contains_injection_indicators`):** Detecta strings que solo aparecerian si un prompt injection tuvo exito (ej: "SYSTEM PROMPT:", "I AM NOW DAN").

4. **Connector Layer (`_require_select`):** Gate a nivel de base de datos que rechaza cualquier statement que no comience con SELECT o WITH.

### Hallazgo Critico: Brecha en `ask_and_run`

**`VannaAdapter.ask_and_run()`** (lineas 284-333 de `vanna_adapter.py`) ejecuta SQL generado por el LLM directamente contra la base de datos usando SQLAlchemy `create_engine` + `conn.execute()` **sin pasar por `_require_select()`**. La pipeline es:

```
question -> Vanna.generate_sql() -> conn.execute(sql) -> return results
```

No hay ninguna verificacion `is_safe_sql()` ni `_require_select()` entre la generacion y la ejecucion. Si un atacante logra que Vanna genere un `DELETE` o `DROP`, se ejecutaria sin restriccion. El connector `PostgreSQLConnector` si llama `_require_select`, pero `ask_and_run` no usa el connector -- usa SQLAlchemy directamente.

### Efectividad de los Tests

Los tests de prompt injection en `test_prompt_injection.py` son **principalmente de caja blanca**:
- `test_injection_payload_does_not_generate_dangerous_sql`: Mockea Vanna para devolver el payload como SQL y luego corre `is_safe_sql`. Pero el assert final esta comentado de facto -- solo recopila `dangerous_found` sin hacer assertion real sobre el resultado.
- Los tests de `TestConnectorSQLSafety` si son efectivos, verifican que `_require_select` rechaza statements DML/DDL.
- Los tests de `TestNLQueryInjection` (input validation) son solidos.

---

## Tenant Isolation

### Mecanismos de Aislamiento

1. **`base_filter` en entity_map:** El Cartographer genera un `base_filter` por entidad (ej: `AND ad_client_id = '1000000'`) que `query_builder.build_queries()` inyecta en cada query SQL generada. Este es el mecanismo primario.

2. **Per-tenant adapter cache:** `api/routers/nl_query.py` mantiene un `_adapter_cache: Dict[str, Any]` con un `VannaAdapter` separado por `tenant_id`, previniendo contaminacion de estado.

3. **tenant_id en request/response:** El endpoint NL-query requiere `tenant_id` y lo refleja en la respuesta para trazabilidad.

### Tests de Aislamiento

| Test | Que Verifica |
|------|-------------|
| `test_entity_with_base_filter_propagates_to_query_builder` | base_filter aparece en SQL generado |
| `test_different_tenant_filters_produce_different_sql` | Dos tenants producen SQL diferente |
| `test_different_tenant_ids_get_different_adapters` | Adapters separados por tenant |
| `test_tenant_id_in_response_matches_request` | tenant_id no se intercambia |
| `test_isolation_scenario` (parametrizado x8) | Cada payload TI tiene categoria y expected_behavior validos |

### Debilidades del Aislamiento

- **base_filter es string concatenado, no parametrizado.** Si el valor de `ad_client_id` viniera de user input, seria vulnerable a SQL injection. Actualmente viene del Cartographer (confiable), pero es fragil.
- **Vanna no valida tenant scope en SQL generado.** El adaptador NL no verifica que el SQL generado contenga el filtro de tenant correcto. Un LLM enganiado podria generar SQL sin filtro de tenant.
- **No hay Row-Level Security (RLS) en PostgreSQL.** Todo el aislamiento depende de logica de aplicacion, no de la base de datos.
- **`_adapter_cache` es un dict en memoria** sin expiracion ni limites. Un atacante podria crear adapters ilimitados via tenant_ids fabricados (memory exhaustion).

---

## Cobertura de Seguridad

### Que ESTA Cubierto

| Control | Mecanismo | Nivel de Confianza |
|---------|-----------|-------------------|
| SQL injection clasico | `_require_select` + `is_safe_sql` | Alto (connector layer) |
| DML/DDL prevention | `_require_select` (SELECT/WITH only) | Alto |
| Prompt injection detection | `contains_injection_indicators` | Medio (string matching) |
| Input validation | Pydantic min/max length | Alto |
| Cross-tenant query isolation | `base_filter` en entity_map | Medio |
| Per-tenant state isolation | `_adapter_cache` por tenant_id | Medio |
| Dangerous PG function access | Pattern list en `is_safe_sql` | Medio |

### Que NO ESTA Cubierto

| Control Ausente | Riesgo |
|----------------|--------|
| Autenticacion/Autorizacion API | Critico -- cualquiera puede llamar `/api/v1/nl-query` |
| Rate limiting | Alto -- sin proteccion contra brute force / DoS |
| Audit logging de queries NL | Alto -- no hay registro persistente de queries adversariales |
| JWT/OAuth para tenant_id | Critico -- tenant_id viene del request body sin validacion de identidad |
| HTTPS/TLS enforcement | Medio -- no visible en el codigo |
| CORS policy | Medio -- no configurada en routers |
| SQL AST validation | Medio -- solo string matching, bypasseable con encoding/spacing |
| Secrets management | Medio -- connection_string viene del request body en `ask_and_run` |

---

## OWASP Compliance

Evaluacion contra OWASP Top 10 2021 y OWASP LLM Top 10 2025:

### OWASP Top 10 (Web)

| # | Categoria | Estado | Detalle |
|---|-----------|--------|---------|
| A01 | Broken Access Control | NO CUMPLE | Sin autenticacion ni autorizacion. tenant_id es autodeclarado. |
| A02 | Cryptographic Failures | PARCIAL | No se almacenan passwords en la app, pero connection_string viaja en el request body. |
| A03 | Injection | PARCIAL | `_require_select` cubre SQL injection clasico. Prompt injection tiene gaps (ver ask_and_run). |
| A04 | Insecure Design | PARCIAL | Buen diseno hexagonal, pero tenant isolation depende solo de logica de app. |
| A05 | Security Misconfiguration | NO EVALUABLE | Depende del deployment (Docker Compose). No hay hardening visible. |
| A06 | Vulnerable Components | NO EVALUABLE | No se analizo supply chain. |
| A07 | Auth Failures | NO CUMPLE | Sin autenticacion. |
| A08 | Software/Data Integrity | PARCIAL | Conventional commits con hooks. Sin firma de artefactos. |
| A09 | Logging/Monitoring | PARCIAL | structlog presente pero sin persistencia ni alertas de seguridad. |
| A10 | SSRF | BAJO RIESGO | No hay endpoints que acepten URLs externas (excepto connection_string). |

### OWASP LLM Top 10 (2025)

| # | Categoria | Estado | Detalle |
|---|-----------|--------|---------|
| LLM01 | Prompt Injection | PARCIAL | Tests defensivos existen. Brecha: `ask_and_run` no filtra SQL generado. |
| LLM02 | Insecure Output Handling | PARCIAL | Output del LLM pasa a SQL execution sin sanitizacion completa. |
| LLM03 | Training Data Poisoning | BAJO RIESGO | Training viene de entity_map (Cartographer propio), no datos externos. |
| LLM04 | Model Denial of Service | NO CUBIERTO | Sin rate limiting ni token budgeting. |
| LLM05 | Supply Chain | NO EVALUADO | Dependencia en Vanna AI + Anthropic API. |
| LLM06 | Sensitive Info Disclosure | PARCIAL | base_filter previene cross-tenant, pero no hay validacion post-LLM. |
| LLM07 | Insecure Plugin Design | N/A | No hay plugins LLM. |
| LLM08 | Excessive Agency | BAJO | Solo SELECT permitido via connectors. ask_and_run es la excepcion. |
| LLM09 | Overreliance | PARCIAL | Verification engine y Knowledge Graph mitigan, pero no en NL path. |
| LLM10 | Model Theft | BAJO | No hay modelo propio. Usa Anthropic API. |

---

## Fortalezas

1. **Arquitectura de defensa en profundidad (connector layer).** `_require_select()` en `DeltaConnector` es un gate solido que rechaza todo lo que no sea SELECT/WITH antes de tocar la base de datos. Los tests parametrizados lo verifican exhaustivamente.

2. **Catalogo de payloads adversariales bien organizado.** `adversarial_inputs.py` con 30 payloads categorizados por tipo de ataque es una base excelente para red-teaming continuo. Incluye ataques sofisticados (token smuggling, repetition, data-embedded injection).

3. **Aislamiento de tenants por diseno.** El patron `base_filter` + `_adapter_cache` per-tenant + `tenant_id` en request/response demuestra que multi-tenancy fue considerado desde la arquitectura, no como parche.

4. **Tests que cubren el worst-case.** El test `test_injection_payload_does_not_generate_dangerous_sql` simula el peor escenario (Vanna devuelve el payload como SQL) para verificar que los guardrails atrapan el SQL peligroso incluso si el LLM falla.

5. **Deteccion de funciones PostgreSQL peligrosas.** `pg_read_file`, `pg_sleep`, `dblink`, `lo_import/export` estan en la lista de deteccion, lo cual previene exfiltracion de datos del sistema operativo y ataques time-based.

6. **Validacion de input via Pydantic.** min_length/max_length en NLQueryRequest previene payloads triviales y ataques de repeticion excesiva.

---

## Debilidades

1. **`ask_and_run` bypasses ALL security controls.** Este es el hallazgo mas critico. `VannaAdapter.ask_and_run()` recibe un `connection_string` del request body y ejecuta SQL generado por el LLM sin pasar por `_require_select()` ni `is_safe_sql()`. Un atacante podria:
   - Enviar una pregunta que haga que Vanna genere `DROP TABLE` o `DELETE FROM`
   - Proveer su propia connection_string apuntando a cualquier base de datos accesible

2. **Sin autenticacion ni autorizacion.** El endpoint `/api/v1/nl-query` no tiene middleware de autenticacion. `tenant_id` viene del request body -- cualquier cliente puede declararse como cualquier tenant.

3. **connection_string en request body.** El campo `connection_string` en `NLQueryRequest` permite que el caller controle a que base de datos se conecta el server. Esto es un vector de SSRF y credential leaking.

4. **`is_safe_sql` es string matching, no AST parsing.** Puede ser bypasseado con:
   - Case variations no cubiertas (el checker hace `.upper()`, asi que esto esta mitigado)
   - Unicode homoglyphs
   - SQL comments que ocultan keywords
   - Whitespace/newline tricks entre keywords

5. **Tests de prompt injection no hacen assertions completas.** `test_injection_payload_does_not_generate_dangerous_sql` recopila violations pero no hace assert final sobre si el SQL es seguro o no. El resultado se descarta sin verificacion.

6. **`_adapter_cache` sin limites.** Dict en memoria sin TTL ni max size. Riesgo de memory exhaustion via tenant_id enumeration.

7. **Sin audit trail.** structlog registra requests pero no hay persistencia dedicada para forensics de seguridad. Un ataque no dejaria rastro persistente.

8. **Tenant isolation no validada post-LLM.** No hay verificacion de que el SQL generado por Vanna realmente contenga el `base_filter` del tenant solicitante.

---

## Recomendaciones 2026

### Prioridad Critica (Sprint Inmediato)

1. **Agregar `_require_select` + `is_safe_sql` a `ask_and_run`.** Antes de ejecutar SQL generado por Vanna, pasar por ambos checks. Esto cierra la brecha mas peligrosa. Ejemplo:
   ```python
   sql = self._vn.generate_sql(question=question)
   is_safe, violations = is_safe_sql(sql)
   if not is_safe:
       return {"sql": sql, "result": [], "error": f"Unsafe SQL: {violations}"}
   ```

2. **Eliminar `connection_string` del request body.** La connection string debe venir de la configuracion del servidor, no del cliente. Mapear `tenant_id` a connection_string en el backend.

3. **Implementar autenticacion en la API.** Minimo JWT con tenant_id en el token. El tenant_id del request debe coincidir con el del token. Middleware en FastAPI.

### Prioridad Alta (Q2 2026)

4. **SQL AST validation.** Reemplazar string matching con parsing AST (ej: `sqlglot` o `sqlparse`) para detectar inyecciones sofisticadas. Verificar que el arbol AST solo contenga nodos SELECT.

5. **Row-Level Security (RLS) en PostgreSQL.** Implementar RLS con `SET ROLE` per-tenant para que el aislamiento sea enforced a nivel de base de datos, no solo logica de aplicacion.

6. **Rate limiting per tenant.** Implementar rate limiting en el endpoint NL-query (ej: 10 requests/minuto por tenant) para prevenir DoS y enumeracion.

7. **Audit logging persistente.** Registrar cada query NL con: tenant_id, question, SQL generado, timestamp, IP, resultado de safety check. Usar tabla dedicada o servicio de logging.

8. **Fix assertions en test de prompt injection.** Completar el assert en `test_injection_payload_does_not_generate_dangerous_sql` para que realmente falle cuando se detecta SQL peligroso.

### Prioridad Media (Q3 2026)

9. **Validacion post-LLM de tenant scope.** Verificar que el SQL generado por Vanna contiene el `base_filter` del tenant solicitante antes de ejecutarlo.

10. **Integration tests con LLM real (sandboxed).** Ejecutar los 12 payloads de prompt injection contra Vanna+Anthropic en un entorno sandbox para medir la tasa real de exito de ataques.

11. **CORS, HTTPS, y security headers.** Configurar CORS restrictivo, forzar HTTPS, agregar headers de seguridad (X-Content-Type-Options, X-Frame-Options, CSP).

12. **TTL y max-size en `_adapter_cache`.** Implementar cache con expiracion (ej: `cachetools.TTLCache`) para prevenir memory exhaustion.

13. **Parametrizar `base_filter`.** Cambiar de string concatenation a parametros SQL bindados para prevenir SQL injection en el propio filtro de tenant.

---

## Archivos Clave

| Archivo | Rol |
|---------|-----|
| `security/adversarial_inputs.py` | 30 payloads adversariales categorizados |
| `security/test_prompt_injection.py` | Tests de SQL safety, injection detection, NL validation |
| `security/test_tenant_isolation.py` | Tests de aislamiento cross-tenant |
| `security/__init__.py` | Docstring de la suite |
| `shared/connectors/base.py` | `_require_select()` -- gate de solo-lectura |
| `shared/connectors/postgresql.py` | Connector que aplica `_require_select` |
| `api/routers/nl_query.py` | Endpoint NL-query con cache per-tenant |
| `core/valinor/nl/vanna_adapter.py` | Adapter NL-to-SQL con brecha en `ask_and_run` |
| `docs/SECURITY_TESTING.md` | Documentacion de la suite de seguridad |
