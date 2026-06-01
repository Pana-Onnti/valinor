# docs/_archive — Documentos archivados (VAL-166, 2026-06-01)

Documentación histórica o desactualizada, movida acá por la auditoría de cimientos
2026-06-01 para que no se confunda con el estado vivo. **Nada acá describe el sistema
actual** — para eso ver `docs/PROJECT_STATE.md`.

| Archivo | Por qué se archivó |
|---|---|
| `STRUCTURE.md` | Ficción: describía un monorepo TypeScript/Turborepo (`packages/@valinor/*`, Cloudflare Workers) que nunca existió en Python. El scaffolding real está en `_archived/ts-scaffolding/`. |
| `MIGRATION_PLAN.md` | Plan de migración CLI→SaaS de 5 semanas, ya completado. Prescribía Supabase + Cloudflare que no se adoptaron (prod es Railway/Vercel). |
| `audit-2026-03/` | Snapshot forense de 28 archivos (auditoría 2026-03-22). Sus top findings ya están resueltos (God modules descompuestos, auth agregada, conftest, MSSQLConnector, TS archivado). Útil como registro histórico, no como estado actual. |

El track "simple/MVP" muerto vive aparte en `_archived/simple-stack/`.
