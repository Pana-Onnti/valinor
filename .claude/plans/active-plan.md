# Active Plan — SYSCOP Sprint

**Ultima actualizacion:** 2026-04-14
**Branch:** develop (31 commits ahead of main)
**Foco:** GRO-15 — Agente de Inventario para SYSCOP (Gerardo), primer cliente pagante
**Deadline:** 2026-04-25

---

## Estado actual de Linear (post-limpieza)

### In Progress (3 reales)
| Issue | Que | Deadline | Estado real en codigo |
|-------|-----|----------|----------------------|
| VAL-125 | Discovery Engine v2: Multi-Agent Schema Understanding | Apr 25 | Sin codigo — los sub-issues son el trabajo |
| VAL-121 | Agente Valinor para Gerardo — DB+Excel, WhatsApp | Apr 25 | Sin codigo — depende de VAL-125 + VAL-122 |
| ANN-1 | Annatar Roadmap & Arquitectura v1.0 | — | Otro proyecto, no bloquea |

### Sprint SYSCOP — Camino critico (VAL-125 sub-issues)
| Dia | Issue | Que | Due | Bloqueado por |
|-----|-------|-----|-----|---------------|
| 1-2 | VAL-126 | SchemaExtractor dialect-aware (SQLAlchemy) | Apr 16 | Nada — ARRANCAR ACA |
| 1-2 | VAL-122 | MSSQLConnector en shared/connectors/ | — | Puede ir en paralelo con VAL-126 |
| 2-3 | VAL-128 | BusinessContext model + argentina_gestion.yaml | Apr 17 | VAL-126 |
| 3-4 | VAL-127 | Multi-Agent Inference + Ensemble Evaluator | Apr 18 | VAL-126 + VAL-128 |
| 4-5 | VAL-129 | Golden Dataset + Benchmark precision/recall | Apr 18 | VAL-127 |
| Post | VAL-130 | Scheduling + Reporting composable (redbeat) | Apr 25 | VAL-125 completo |

### Gaps detectados (codigo vs Linear)
- SQL Server: solo hay ping/onboarding. Falta `MSSQLConnector` class para queries del pipeline
- Discovery Engine: existe v1 (`discovery/profiler.py`, `fk_discovery.py`) pero no es multi-dialect ni multi-agent
- BusinessContext: no existe como abstraccion. ERP hints distribuidos en cartographer/KG/narrators
- Scheduling: solo email digest + webhooks. No redbeat ni NotificationRouter
- Inventory Agent: cero codigo

### Otros en backlog (no bloquean SYSCOP)
| Issue | Que | Due |
|-------|-----|-----|
| VAL-120 | Demo Valinor para Bio4 | Apr 18 |
| VAL-22 | Scale: load testing, zero-downtime | Jul 31 |
| GRO-11 | YC application con metricas reales | Aug 1 |
| VAL-107-119 | Backlog tecnico (security, caching, prompts) | — |

---

## Completado (sesiones anteriores)

### Sprint UI/Transparency (cerrado, en develop)
- VAL-91: Theme toggle + skeletons + design tokens
- VAL-92/93: Transparency Engine (audit trail, trust score, confidence badges)
- VAL-95: Journey Wizard (onboarding redesign, live analysis, KO revelation)
- VAL-97: Confidence metadata API
- VAL-104: KO Report Revelation
- VAL-105: SSE/Redis real-time progress

### Infra (cerrado)
- VAL-18: CI/CD Epic — Fases 1-3 Done (GHCR, staging, PR checks)
- VAL-47: Hardening Epic — todos los P0/P1/P2 Done
- VAL-68: Sprint de Perfeccionamiento — 13/13 Done
- VAL-82: File Ingestion Epic — 8/8 Done
- 3055/3058 tests green, Next.js build OK

---

## Proximos pasos (hoy)

1. **VAL-126**: SchemaExtractor dialect-aware con SQLAlchemy Inspector
2. **VAL-122**: MSSQLConnector class en shared/connectors/ (en paralelo)
3. Merge develop -> main cuando SYSCOP sprint este estable
