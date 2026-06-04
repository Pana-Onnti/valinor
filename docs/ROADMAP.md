# Valinor SaaS — Roadmap & Status

> Historia a nivel de fases. **Estado vivo verificado: `docs/PROJECT_STATE.md`.** Linear es canónico para el status de cada issue.
> Última sync: 2026-06-01

---

## Fase 1: Foundation (DONE — Mar 2026)

Swarm E2E funcional contra Gloria (Etendo/PostgreSQL).

| Issue | Que | Estado |
|-------|-----|--------|
| VAL-1 | Swarm E2E: Cartografo -> Analista -> Narrador | Done |
| VAL-2 | Business abstraction layer (schema-agnostic) | Done |
| VAL-3 | KO Report template (Minto + loss framing + Tufte) | Done |
| VAL-5 | Centinela + Cazador en swarm | Done |
| VAL-7 | Tests E2E sobre Gloria | Done |
| VAL-17 | Bootstrap agent infrastructure | Done |

## Fase 2: Arsenal Sprint (DONE — Mar 2026)

Stack moderno: FastMCP, lmnr, Pydantic-AI, KV-cache, Vanna AI, dlt, promptfoo.

| Issue | Que | Estado |
|-------|-----|--------|
| VAL-28–34 | 7 issues del arsenal | Done |
| VAL-36 | Security fixes + core improvements | Done |

## Fase 3: Anti-Hallucination (DONE — Mar 2026)

Knowledge Graph + Verification Engine + Calibration Loop.

| Issue | Que | Estado |
|-------|-----|--------|
| VAL-37–46 | 10 issues: cash flow, temporal verification, quorum, etc | Done |

## Fase 4: Hardening (DONE — Mar 2026)

Security P0s, code decomposition, test infrastructure.

| Issue | Que | Estado |
|-------|-----|--------|
| VAL-47 | Epic: 12 P0/P1/P2 issues | Done (12/12) |
| VAL-68 | Sprint de Perfeccionamiento: 13 issues | Done (13/13) |

## Fase 5: Self-Serve & File Ingestion (DONE — Mar 2026)

Onboarding wizard, file upload pipeline, demo mode.

| Issue | Que | Estado |
|-------|-----|--------|
| VAL-6/14 | Self-serve onboarding wizard | Done |
| VAL-82 | File Ingestion Epic (CSV/Excel): 8 issues | Done (8/8) |
| VAL-62 | Demo mode con datos sinteticos | Done |

## Fase 6: CI/CD (DONE — Mar/Apr 2026)

GHCR, staging, PR checks, deploy automation.

| Issue | Que | Estado |
|-------|-----|--------|
| VAL-18 | CI/CD Epic: Fases 1-3 | Done |
| VAL-19/20/21/23 | Foundation + Staging + Multi-tenant + Accesos | Done |

## Fase 7: UI/UX Professionalization (DONE — Apr 2026)

Design system, transparency engine, journey wizard, KO report revelation.

| Issue | Que | Estado |
|-------|-----|--------|
| VAL-91 | Theme toggle + skeletons + design tokens | Done |
| VAL-93 | Transparency Engine (audit trail, trust score, badges) | Done (5/5 sub-issues) |
| VAL-95 | Journey Wizard (onboarding redesign, live analysis) | Done (4/4 sub-issues) |
| VAL-104 | KO Report Revelation | Done |
| VAL-105 | SSE/Redis real-time progress | Done |

**Total Done: ~105 issues across 7 phases**

---

## Fase 8: SQL Server / segundo-ERP support (track de cliente DESCOPED)

> El track de inventory-runner para un cliente single-tenant fue **descoped** de
> valinor-saas (el deal externo no avanzó). Nada cliente-específico vive en este
> repo. Las **capacidades genéricas** que sí quedaron acá son reutilizables para
> cualquier ERP sobre SQL Server y se validarán contra una DB real más adelante.

### Capacidades genéricas que landearon (reutilizables, agnósticas de cliente)

| Issue | Qué | Estado |
|-------|-----|--------|
| VAL-126 | SchemaExtractor dialect-aware (SQLAlchemy) | Done |
| VAL-122 | MSSQLConnector en `shared/connectors/` (+ prescan dialect-aware) | Done parcial |
| VAL-128 | BusinessContext + `argentina_gestion.yaml` | Done |
| VAL-127 | Multi-Agent Inference + Ensemble Evaluator | Done |
| VAL-129 | Golden Dataset + Benchmark P/R | Done |
| VAL-130 | Scheduling + Reporting composable (redbeat) | Done |
| VAL-175 | Hint-pack ablation — métrica de moat sobre el benchmark | Done |

Nota: **cero código** de inventory-agent o de cualquier cliente concreto vive en
este repo — el engine es genérico y agnóstico de cliente por diseño.

---

## Fase 9: Scale & YC Prep (BACKLOG — Jul/Aug 2026)

| Issue | Que | Due | Prioridad |
|-------|-----|-----|-----------|
| VAL-22 | Load testing + zero-downtime + auto-scaling + alerting | Jul 31 | High |
| GRO-11 | YC application con metricas reales | Aug 1 | Urgent |
| GRO-12 | Video founders YC (1 min) | Aug 1 | High |

## Fase 10: Growth & Revenue (BACKLOG)

| Issue | Que | Due | Prioridad |
|-------|-----|-----|-----------|
| VAL-120 | Demo Valinor para Bio4 | Apr 18 | High |
| GRO-7 | Cerrar 2-3 diagnosticos pagados $400 USD | Apr 30 | Urgent |
| GRO-8 | Primer testimonio escrito | Apr 30 | High |
| GRO-9 | Convertir diagnosticos en retencion mensual | May 31 | Urgent |
| GRO-10 | Definir ICP real basado en 5 clientes | May 31 | High |

## Backlog Tecnico (sin deadline)

| Issue | Que | Prioridad |
|-------|-----|-----------|
| VAL-106 | Externalizar prompts a archivos versionados | Urgent (Todo) |
| ~~VAL-107~~ | ~~Rate limiting en API endpoints~~ | ✅ Done (2026-05-29) |
| VAL-108 | Auth wiring + JWT claims — ver `docs/PROJECT_STATE.md` | Urgent |
| VAL-109 | Semantic cache para queries LLM | High |
| VAL-110 | Adaptive agent router (skip por DQ score) | High |
| VAL-111 | Cost tracking a PostgreSQL para billing | High |
| VAL-112 | Query-level cost attribution | High |
| VAL-113 | Grafana dashboards para Prometheus | High |
| VAL-114 | LLM eval pipeline offline | Medium |
| VAL-115 | Feedback loop UI (usuario corrige findings) | Medium |
| VAL-116 | Export Excel/CSV a reportes | Medium |
| VAL-117 | Versionar golden dataset Gloria | Low |
| VAL-118 | Encriptar campos sensibles at-rest | Medium |
| VAL-119 | Catalogo centralizado de prompts | Urgent |

## Otro proyecto: Annatar (separado)

| Issue | Que | Estado |
|-------|-----|--------|
| ANN-1 | Roadmap & Arquitectura Tecnica v1.0 | In Progress |

---

## Metricas del producto

- **Tests:** ~3358 (~3302 en tests/ + 56 en security/), suite verde, 0 errores de colección
- **Pipeline production:** 90-100% findings grounded (Gloria, Q1-2025)
- **Costo por analisis:** ~$8 (Claude API)
- **Precio:** $200/mes (25 analisis), margen bruto 92%
- **Discovery v2 (VAL-125):** Done (2026-04-18)
- **Hardening 2026-05/06:** VAL-107/164/165 Done; foundations audit VAL-166→170 (2026-06-01)
- **Release:** `master` = producción (PR desde `develop`). **No existe rama `main`.**
