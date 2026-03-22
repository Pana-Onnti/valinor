# Active Plan — Arsenal Features Sprint

**Última actualización:** 2026-03-21
**Branch:** develop
**Objetivo:** Implementar las 7 features críticas del arsenal D4C secuencialmente

## Issues a implementar (en orden)

| # | Issue | Feature | Effort | Prioridad |
|---|-------|---------|--------|-----------|
| 1 | **VAL-28** | FastMCP — MCP server layer | 2 días | Urgent |
| 2 | **VAL-29** | lmnr — observabilidad del swarm | 3 días | Urgent |
| 3 | **VAL-30** | Pydantic-AI — type-safe agents | 3 días | High |
| 4 | **VAL-31** | KV-cache + token tracking | 3 días | High |
| 5 | **VAL-32** | Vanna AI — NL→SQL conversacional | 4 días | High |
| 6 | **VAL-33** | dlt — generalización de fuentes | 5 días | High |
| 7 | **VAL-34** | promptfoo — red-teaming seguridad | 3 días | High |

## Protocolo por feature

Para cada issue:
1. Mover a "In Progress" en Linear
2. Leer issue completo + explorar código existente
3. Implementar
4. `pytest tests/ -v` — arreglar hasta que pase
5. Commit atómico con `Refs: VAL-XX`
6. Mover a "Done" en Linear
7. Pasar al siguiente

## Estado de implementación

### ✅ Completados (sesiones anteriores)
- VAL-17, VAL-10, VAL-11, VAL-16, VAL-24, VAL-26

### ✅ Completados este sprint (rama develop)
- [x] VAL-28 — FastMCP
- [x] VAL-29 — lmnr / observabilidad
- [x] VAL-30 — Pydantic-AI
- [x] VAL-31 — KV-cache
- [x] VAL-32 — Vanna AI
- [x] VAL-33 — dlt
- [x] VAL-34 — promptfoo security

## Decisiones arquitecturales clave

- **FastMCP**: estructura `mcp_servers/` en root, patrón `@mcp.tool()`
- **lmnr**: instrumentar en `shared/llm/` y en cada agente, NO en api/main.py
- **Pydantic-AI**: output models en `core/valinor/schemas/`, no inline en agents
- **KV-cache**: modificar solo `shared/llm/providers/anthropic_provider.py`
- **Vanna AI**: endpoint separado en `api/routers/nl_query.py` + componente Next.js
- **dlt**: capa `shared/connectors/` — DataQualityGate y Cartographer NO se tocan
- **promptfoo**: `security/` en root + CI check — no tocar código de agentes

## Checkpoint

Última feature completada: VAL-34 — SPRINT COMPLETO ✅
Próxima acción: PR develop → master
