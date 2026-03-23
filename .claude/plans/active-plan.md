# Active Plan — V3 File Ingestion Sprint

**Ultima actualizacion:** 2026-03-23
**Branch:** develop (pushed to origin)

## Estado actual

### ✅ Completados

#### Sprint V3 — File Ingestion Pipeline (VAL-82 epic)
- **VAL-83**: Backend upload endpoint — `POST /api/upload/{client_name}`, validacion, tenant isolation
- **VAL-84**: File→SQLite service — SQLiteConnector, FileIngestionService, `/process` endpoint
- **VAL-85**: Preview + schema endpoints — `GET /preview`, `GET /schema`
- **VAL-86**: Frontend upload component — FileUpload.tsx, drag-drop, progress, multi-file
- **VAL-87**: Data preview UI — DataPreview.tsx, ColumnMapper.tsx (6 entity auto-detection), SheetSelector.tsx
- **VAL-88**: AnalysisForm integration — comingSoon removido, flujo condicional file vs DB, Step 2.5
- **VAL-89**: Infra storage — StorageManager, Alembic 003, Docker volume, cleanup script

#### Sprints anteriores (todo Done)
- VAL-1→61 (backlog vaciado en sprints previos)
- VAL-65, VAL-66, VAL-67 (bug fixes smoke tests)

### ⏳ Pendiente inmediato (post-sprint V3)
1. `alembic upgrade head` — activar tabla `uploaded_files` con RLS
2. Test manual del flujo upload en browser
3. Migrar `_uploads_registry` in-memory dict a queries PostgreSQL
4. Agregar Celery task para conversion async de archivos grandes
5. Fix preexistente: `test_analysis_tools.py::test_passes_with_2_high_confidence`

### 🚫 Backlog no urgente
- VAL-22: Fase 4 Scale — load testing, zero-downtime (due: julio 31)
- VAL-35: UI/UX Refactoring (plan en `.claude/plans/VAL-35-ui-ux-refactor.md`)
- VAL-47: EPIC Hardening — P2s pendientes

### 🧹 Limpieza realizada
- 9 worktrees huerfanos eliminados
- 12 branches huerfanas borradas
- Solo queda `develop` limpio

## Proximos pasos
1. Correr alembic migration en dev/prod
2. QA manual del flujo file upload end-to-end
3. Evaluar VAL-35 UI/UX refactor como siguiente sprint
