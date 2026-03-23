# Sprint: Product Features (VAL-62, 63, 64)

**Esfuerzo estimado**: 8-10 días, 2 lanes paralelas
**Dependencias**: Beneficia de VAL-68 bugs cerrados primero

## Lane A: Verification + Demo Pipeline

### VAL-63: Dimension-aware verification (S, 1-2 días)
**Problema**: Verification Engine no filtra por dimensión. Un claim EUR 3,139 puede matchear `num_invoices = 3,139` (COUNT). Enum `Dimension` existe pero solo se usa para storage, no para filtering.

**Fix**:
1. Agregar dimension guard a `_verify_claim` (línea 671 de verification.py)
2. Agregar guard a `_check_derived_value` (línea 774)
3. Agregar guard a `_search_raw_results` (línea 822)
4. Mapear `claimed_unit` a `Dimension` enum en `_decompose_finding`
5. `Dimension.UNKNOWN` matchea todo como fallback
6. Tests: EUR no matchea COUNT, COUNT no matchea PERCENT

### VAL-62: Demo Mode pipeline completo (L, 4-5 días)
**Relación con VAL-8**: VAL-8 (DONE) es frontend-only con datos hardcoded. VAL-62 corre el pipeline REAL contra DB sintética.

**Assets existentes**:
- `scripts/playground/agents/erp_forge.py` — genera DBs SQLite con schema Etendo/Odoo completo
- Pipeline ya soporta SQLite via `sqlite:///` connection strings

**Steps**:
1. Crear `scripts/seed_demo_db.py` — usa ERPForge con seed fijo para DB determinística
2. Crear `core/clients/demo/config.json` — client config apuntando a SQLite
3. Crear `api/routes/demo.py` — `POST /api/demo/run`, `GET /api/demo/report` (cached)
4. Conectar frontend `/demo` para fetch de backend (fallback a datos estáticos)
5. Docker: profile `demo` que seedea DB al start

## Lane B: SQL Server Connector

### VAL-64: SQL Server connector (M, 2-3 días)
**Estado**: `pyproject.toml` ya tiene `mssql = ["pyodbc>=5.0"]`. SQLAlchemy soporta `mssql+pyodbc://`.

**Steps**:
1. Extender onboarding connection builder (api/routes/onboarding.py línea 97-102)
2. Agregar `mssql` a DB types list
3. SSH tunnel support para MSSQL
4. SQL dialect differences: TOP vs LIMIT, DATEPART vs DATE_TRUNC, brackets vs quotes
5. ODBC driver en Dockerfile API
6. ERP detection: Dynamics 365, SAP B1 patterns
7. Tests con SQL Server Docker container

## Timeline

```
Day 1-2:  Lane A: VAL-63 | Lane B: VAL-64 starts
Day 3:    Lane A: VAL-62 starts | Lane B: VAL-64 continues
Day 4-5:  Lane A: VAL-62 (seed + API) | Lane B: VAL-64 finishes
Day 6-8:  Lane A: VAL-62 (frontend + tests)
```
