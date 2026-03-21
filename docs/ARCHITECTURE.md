# Valinor SaaS v2 — Arquitectura Técnica

> Estado: Marzo 2026. Fases 1–4 y 6 completadas.

---

## Vista de alto nivel

```
Cliente
  │
  ▼
FastAPI (puerto 8000)
  │
  ├── Middleware: rate-limiting / request_id / audit log
  │
  ├── POST /api/analyze ──► Celery Worker (Redis queue, puerto 6380)
  │                              │
  │                              ▼
  │                    SSHTunnelManager (Paramiko)
  │                              │
  │                              ▼
  │                    DB del Cliente (túnel efímero, max 1h)
  │                              │
  │                              ▼
  │                    Valinor Pipeline v0 (core/valinor/)
  │                    ┌─────────────────────────────┐
  │                    │ 1. DataQualityGate (8+1)     │
  │                    │ 2. Cartographer               │
  │                    │ 3. QueryEvolver               │
  │                    │ 4. QueryBuilder               │
  │                    │ 5. Analysts + Sentinels        │
  │                    │ 6. CurrencyGuard              │
  │                    │ 7. SegmentationEngine         │
  │                    │ 8. AnomalyDetector            │
  │                    │ 9. SentinelPatterns (16)      │
  │                    │ 10. AlertEngine               │
  │                    │ 11. Narrators                 │
  │                    └─────────────────────────────┘
  │                              │
  │                    ProfileExtractor ──► ProfileStore (Redis/PG)
  │                    AdaptiveContextBuilder
  │                              │
  │                    Outputs: JSON + PDF + Email + Webhooks
  │
  ├── GET /api/jobs/{id}/status   ──► Redis
  ├── GET /api/jobs/{id}/results  ──► PostgreSQL (puerto 5450 en dev)
  ├── WS  /api/jobs/{id}/ws       ──► WebSocket streaming
  └── GET /metrics                ──► Prometheus scrape
```

---

## Pipeline de análisis — detalle

### 0. Pre-check: DataQualityGate
Antes de cualquier análisis, 8+1 checks bloqueantes:
1. Row count vs baseline (schema drift)
2. Null ratio por columna (threshold configurable)
3. Type consistency (no silent coercions)
4. PK uniqueness
5. Referential integrity spot-check
6. Numeric range / outlier pre-screen
7. Date range plausibility (no timestamps futuros)
8. Freshness check via CurrencyGuard
+1. REPEATABLE READ isolation snapshot

Si DQ score < threshold configurado → `DQGateHaltError` → job abortado con reporte.

### 1. Cartographer
Mapea el schema de la DB del cliente. Detecta entidades conocidas:
`customers / invoices / products / payments / ...`

### 2. QueryEvolver
Lee el historial del cliente (ProfileStore) y adapta qué queries priorizar basado en qué dio resultados valiosos en análisis anteriores.

### 3. QueryBuilder
Genera las queries SQL según el schema mapeado y las preferencias del QueryEvolver.

### 4. Analysts + Sentinels
- **Analyst**: revenue_calc, aging_calc, pareto_analysis, segmentation
- **Sentinel**: fraud detection, anomalies, pattern matching
- **Hunter**: busca oportunidades de revenue no capturadas

### 5. Quality post-análisis
- **CurrencyGuard**: detecta si los datos están stale
- **SegmentationEngine**: segmenta clientes por RFM (recencia/frecuencia/monto)
- **AnomalyDetector**: STL decomposition + Z-score
- **SentinelPatterns**: 16 patrones de fraude incluyendo Benford's Law

### 6. AlertEngine
Evalúa umbrales configurados por cliente. Genera alerts si hay desvíos.

### 7. Narrators
Reciben contexto inyectado por AdaptiveContextBuilder (histórico del cliente, findings persistentes, currency context, segmentation) y generan el reporte ejecutivo.

### 8. ProfileExtractor
Post-análisis, extrae el perfil actualizado del cliente y lo persiste para el próximo análisis.

---

## Intelligence Layer (Memory)

```
ProfileStore (Redis + PostgreSQL)
    ▲                │
    │                ▼
ProfileExtractor    AdaptiveContextBuilder
    │                    │
    │                    ▼
    │              Inyección en system prompt de Narrators
    │
    ▼
IndustryDetector → detecta industria por tablas presentes
SegmentationEngine → RFM segmentation
AlertEngine → umbrales por cliente
```

---

## Módulos clave y sus responsabilidades

| Módulo | Archivo | Responsabilidad |
|---|---|---|
| `ValinorAdapter` | `api/adapters/valinor_adapter.py` | Punto de entrada al pipeline v0 |
| `SSHTunnelManager` | `shared/ssh_tunnel.py` | Túneles SSH efímeros + ZeroTrust |
| `DataQualityGate` | `core/valinor/gates.py` | 8+1 checks pre-análisis |
| `CurrencyGuard` | `core/valinor/quality/` | Detección de datos stale |
| `ProfileStore` | `shared/memory/profile_store.py` | Persistencia de perfiles de cliente |
| `AdaptiveContextBuilder` | `shared/memory/adaptive_context_builder.py` | Contexto histórico para agentes |
| `QueryEvolver` | `api/refinement/query_evolver.py` | Aprendizaje de queries valiosas |
| `AlertEngine` | `shared/memory/alert_engine.py` | Umbrales y alertas por cliente |
| `WebhookDispatcher` | `shared/webhook_dispatcher.py` | Webhooks con retry exponencial |
| `PDFGenerator` | `api/pdf_generator.py` | Export PDF con DQ bar + alerts |
| `DigestComposer` | `api/email_digest.py` | Email digest con delta entre runs |

---

## Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend API | FastAPI + Pydantic v2 |
| Queue | Celery + Redis |
| DB Metadata | PostgreSQL (dev: puerto 5450) |
| Cache/State | Redis (dev: puerto 6380) |
| SSH Tunneling | Paramiko |
| AI Agents | Claude API (claude-sonnet-4-6 / claude-opus-4-6) |
| Frontend | Next.js + Tailwind CSS |
| Monitoring | Prometheus (puerto 9090) |
| Testing | pytest (2481 tests) |
| Deployment target | Cloudflare Workers + GitHub Actions + Supabase |

---

## Decisiones de diseño

**Zero Data Storage**: nunca se almacenan datos del cliente, solo metadata del job y resultados agregados. Las conexiones SSH son efímeras (max 1 hora, cleanup automático).

**Wrapper sobre v0**: todo el código en `core/valinor/` es preservado intacto. La API v2 lo envuelve con adapter pattern. Esto permite rollback inmediato a CLI si algo falla.

**Costo operativo**: ~$8 por análisis (Claude API). Precio al cliente: $200/mes (25 análisis). Margen bruto: 92%.

---

*Última actualización: Marzo 2026 — Delta 4C*
