# Testing Guide — Valinor SaaS

## Filosofía

1. **DB real, nunca mocks** — Integration tests contra PostgreSQL (producción) o SQLite (dev). Nunca se mockea la base de datos.
2. **LLM agents: SIEMPRE REALES** — Agents corren contra Claude via CLI/proxy (Plan Max = gratis). Si no está disponible, se skipean. Nunca mocks silenciosos.
3. **Assertions sobre estructura, no valores** — Claude es no-determinista. Tests validan que findings sean parseables con schema correcto, no que `value_eur == 720000`.
4. **Entity map alineado con la DB** — Lección aprendida: si entity_map describe una DB distinta a la que se ejecutan los queries, los agentes "alucinan" cruzando metadata con datos reales.

## Prerequisitos

```bash
# Gloria PostgreSQL (para test de producción)
PGPASSWORD=tad psql -h localhost -U tad -d gloria -c "SELECT COUNT(*) FROM c_invoice"

# Claude CLI o proxy (para agentes reales)
curl -s http://localhost:8099/health || which claude

# Si el proxy no está corriendo:
python3 scripts/claude_proxy.py &
```

## Ejecución rápida

```bash
# ══ PRODUCTION (recomendado — Gloria PostgreSQL, agentes + narrators reales) ══
pytest tests/test_pipeline_production.py -v -s          # ~6 min, output en tests/output/production/

# ══ POR PERÍODO (SQLite 434 invoices, 3 períodos) ══
pytest tests/test_pipeline_periods.py -v -s             # ~5 min (3 períodos)
pytest tests/test_pipeline_periods.py -k "1-month" -v -s  # ~2 min (solo 1 mes)

# ══ E2E BÁSICO (SQLite 25 rows, agentes reales si hay LLM) ══
pytest tests/test_pipeline_gloria_e2e.py -v             # ~3.5 min con LLM, <1s sin

# ══ STAGES DETERMINISTAS (sin LLM, siempre corre) ══
pytest tests/test_pipeline_gloria_e2e.py::TestGloriaPipelineStages -v  # <1s

# ══ FULL SUITE (~3000 tests) ══
pytest tests/ -v --tb=short                             # varios minutos
pytest tests/ -x --tb=short                             # para en primer fallo
```

## Test de producción: `test_pipeline_production.py`

**El test definitivo.** Corre el mismo pipeline que la app contra la Gloria real.

```
PostgreSQL (260K invoices, 7K customers, 14 años)
  → DQ Gate (100/100)
  → Calibration (PASS)
  → Query Builder (8 queries)
  → Execute Queries (8/8 — DATE_TRUNC, EXTRACT funcionan en PG)
  → Baseline (€4.8M revenue, 9K invoices, 2K customers)
  → 3 Agents REALES (analyst 8 + sentinel 9 + hunter 7 = 24 findings)
  → Reconciliation (0 conflicts)
  → 4 Narrators REALES (CEO 3.7K + Controller 16K + Sales 11K + Executive 14K chars)
```

Resultado verificado: **90-100% de findings grounded** en datos reales.

### Output

```
tests/output/production/
├── gloria_Q1-2025_YYYY-MM-DD_HH-MM-SS.json   (pipeline completo: findings, baseline, queries)
└── reports/
    ├── briefing_ceo_*.md         (5 números + 3 decisiones)
    ├── reporte_controller_*.md   (detalle financiero completo)
    ├── reporte_ventas_*.md       (oportunidades comerciales)
    └── reporte_ejecutivo_*.md    (resumen ejecutivo consolidado)
```

### Qué validar en el output

| Métrica | Bueno | Alerta | Mal |
|---------|-------|--------|-----|
| DQ Score | >80 | 50-80 | <50 o HALT |
| Queries OK | 8/8 | 6-7/8 | <6 |
| Agents con findings | 3/3 | 2/3 | <2 |
| Findings grounded | >90% | 70-90% | <70% |
| Narrators completos | 4/4 | 2-3/4 | <2 |
| CEO briefing | Números específicos + acciones | Genérico | Error/timeout |

## Tests por período: `test_pipeline_periods.py`

DB SQLite con ~434 invoices realistas (50 clientes, 2 años, patrón de concentración). Entity map construido dinámicamente desde la DB real.

Períodos parametrizados: 1 mes (Jun-2025), 1 trimestre (Q2-2025), 1 año (FY-2025).

Sirve para ver cómo se comportan los agentes con distinta cantidad de datos sin depender de PostgreSQL.

## Tests E2E: `test_pipeline_gloria_e2e.py`

Dos clases:

- `TestGloriaPipelineStages` — Stages deterministas (query builder, baseline, narrator context, schema). Siempre corre, sin LLM.
- `TestGloriaE2EReal` — Agentes reales contra SQLite. Skip si no hay LLM.

## Otros tests

| Archivo | Qué cubre | Tests |
|---------|-----------|-------|
| `test_pipeline_integration.py` | Cada componente en profundidad (DQ gate, segmentación, anomalías, reconciliación, etc.) | 20+ suites, 70+ tests |
| `test_smoke_pipeline.py` | Smoke rápido: nada crashea | 6 tests, <5s |
| `test_grounded_v2_integration.py` | Knowledge Graph + Verification Engine | 4 suites |
| `test_mvp.py` | API adapter (SSH → pipeline → storage) | 3 flow tests |
| `test_api_endpoints.py` | HTTP endpoints con httpx | 50+ tests |

## Lecciones aprendidas

### Entity map debe coincidir con la DB

Si el entity_map dice `row_count: 4117` pero la DB tiene 25 rows, los agentes cruzan ambos datos y "descubren" que faltan 4,092 invoices. No es un bug del agente — es input contradictorio.

**Fix**: construir entity_map dinámicamente desde la DB real (como hace `test_pipeline_production.py`).

### SQLite vs PostgreSQL

Las queries usan `DATE_TRUNC`, `EXTRACT`, `::date` — PostgreSQL nativo. En SQLite fallan 4 de 8 queries. Esto no es un bug — el producto usa PostgreSQL en producción.

Tests en SQLite son útiles para stages deterministas, pero para evaluar la calidad real del análisis: **usar PostgreSQL**.

### Narrators necesitan timeout >60s

Con datos reales (~9K invoices, 24 findings), los narrators tardan 30-160s. El default de 60s es poco para producción. El test usa 180s.

## Pipeline completo vs cobertura

```
Stage 0:    DQ Gate              → test_production ✅ REAL (PostgreSQL)
Stage 1:    Cartographer         → ⚠ No testeado (se usa entity_map fijo)
Stage 1.5:  Guard Rail           → test_production ✅ REAL
Stage 2:    Query Builder        → test_production ✅ REAL
Stage 2.5:  Execute Queries      → test_production ✅ REAL (8/8 en PG)
Post-2.5:   Compute Baseline     → test_production ✅ REAL
Stage 3:    Analysis Agents      → test_production ✅ REAL (3/3 Claude)
Stage 3.5:  Reconciliation       → test_production ✅ REAL
Stage 3.75: Narrator Context     → test_production ✅ REAL
Stage 4:    Narrators            → test_production ✅ REAL (4/4 Claude)
Stage 5:    Deliver              → ⚠ No testeado aisladamente
```

## Skill

Para correr tests de producción rápidamente: decile a Claude "correr test real" o "test producción" y se activa el skill `production-test`.
