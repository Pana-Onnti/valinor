# Domain Model — Valinor SaaS

Entidades del dominio del swarm. Para implementar features, este es el vocabulario que usamos.

## Los Valar — Agentes del Swarm

Cada agente tiene un nombre de Tolkien y una responsabilidad única:

| Vala | Responsabilidad | Input | Output |
|------|----------------|-------|--------|
| **Cartógrafo** | Descubrir y catalogar el schema de la DB | Conexión DB | SchemaMap |
| **QueryBuilder** | Construir queries optimizadas para el análisis | SchemaMap + AnalysisConfig | QuerySet |
| **Analista** | Analizar datos financieros y de negocio | QuerySet + DataSnapshot | AnalysisResults |
| **Centinela** | Data quality monitoring y alertas | DataSnapshot | QualityReport |
| **Cazador** | Buscar oportunidades de negocio y anomalías | DataSnapshot | OpportunityList |
| **Narrador** | Generar el KO Report ejecutivo | AnalysisResults + QualityReport | KOReport |
| **Vairë** (VAL-16) | Renderizar el KO Report como HTML/PDF | KOReport | RenderedReport |

## Pipeline Flow

```
Cliente DB
    ↓
[DataQualityGate] — 8+1 checks pre-análisis
    ↓
Cartógrafo → SchemaMap
    ↓
QueryBuilder → QuerySet
    ↓
[PARALELO]
├── Analista ────────┐
├── Centinela ───────┤ → AnalysisBundle
└── Cazador ─────────┘
    ↓
Narrador → KOReport (markdown)
    ↓
Vairë → RenderedReport (HTML/PDF)
```

## Entidades de Negocio (Business Abstraction Layer — VAL-2)

El schema-agnostic layer mapea tablas reales a entidades universales:

| Entidad Universal | Ejemplo Tango | Ejemplo Etendo | Ejemplo Excel |
|-------------------|---------------|----------------|---------------|
| Cliente | `cuentas_corrientes` | `c_bpartner` | Hoja "Clientes" |
| Transacción | `comprobantes` | `c_invoice` | Hoja "Ventas" |
| Producto | `articulos` | `m_product` | Hoja "Productos" |
| Pago | `pagos_cobros` | `c_payment` | Hoja "Pagos" |
| Empleado | `empleados` | `ad_user` | Hoja "RRHH" |

## DataQualityGate Checks

Antes de cualquier análisis, el DQ Gate corre 8+1 checks:

| Check | Descripción | Severidad |
|-------|-------------|-----------|
| DQ-1 | Row count vs baseline (schema drift) | Critical |
| DQ-2 | Null ratio por columna (threshold configurable) | High |
| DQ-3 | Type consistency (no silent cast coercions) | High |
| DQ-4 | PK uniqueness enforcement | Critical |
| DQ-5 | Referential integrity spot-check | Medium |
| DQ-6 | Numeric range / outlier pre-screen | Medium |
| DQ-7 | Date range plausibility (no future timestamps) | High |
| DQ-8 | Freshness check via CurrencyGuard | Medium |
| DQ+1 | REPEATABLE READ isolation snapshot | Critical |

Si checks Critical fallan → análisis abortado automáticamente.

## KO Report Structure (Minto Pyramid)

```
KO Report
├── Hero Numbers (Kahneman loss framing — "perdés $X/mes", no "podrías ganar $X")
├── Executive Summary
│   ├── Situación (qué está pasando)
│   ├── Complicación (por qué es un problema)
│   └── Resolución (qué hacer)
├── Findings (ordenados por severity: Critical → High → Medium)
│   └── FindingCard
│       ├── título
│       ├── severity badge
│       ├── impacto económico estimado
│       ├── evidencia (tabla fuente + query hash — provenance)
│       └── acción recomendada
├── Data Quality Score
└── Anomaly Explorer
```

## Analysis Job Lifecycle

```
Estado         → Descripción
───────────────────────────────
pending        → Job creado, esperando worker
running        → Pipeline ejecutándose
quality_check  → DataQualityGate corriendo
analyzing      → Valar trabajando (paralelo)
narrating      → Narrador generando KO Report
completed      → Análisis terminado con éxito
failed         → Error en algún paso (ver error_details)
```

## Conexión a DB del Cliente

```python
# Siempre via SSH Tunnel (máximo 1 hora)
# Nunca conexión directa

SSHTunnel(
    host=client.ssh_host,
    user=client.ssh_user,
    key=client.ssh_key,  # Encrypted, TTL-based
    remote_host="localhost",
    remote_port=5432,  # o el puerto real del cliente
    local_port=auto  # asignado dinámicamente
)
```

## Períodos de Análisis

Formatos soportados:
- `2025-04` → Mensual (abril 2025)
- `Q1-2025` → Trimestral (Q1 2025)
- `H1-2025` → Semestral (primer semestre 2025)
- `2025` → Anual (año completo)
