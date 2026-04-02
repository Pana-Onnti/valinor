'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { X, Eye } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

// Synthetic demo job ID — the API will serve demo data when this ID is requested
export const DEMO_JOB_ID = '__demo__'

export function DemoModeButton({ onEnter }: { onEnter: () => void }) {
  return (
    <button
      onClick={onEnter}
      className="d4c-btn-ghost"
    >
      <Eye size={14} />
      Ver demo
    </button>
  )
}

const DEMO_REPORT = `# Gloria Pet Distribution — Análisis Q1-2026
**Fecha de análisis:** 20/03/2026 · **Datos hasta:** 31/03/2026 · **Divisa:** EUR

> ⚠️ ANÁLISIS DEMO — Datos sintéticos para ilustrar las capacidades del sistema

---

## Las Cifras que Importan

**Facturación Total**: €11.2M | MEASURED
**Cobranza Pendiente**: €1.6M (14.3%) | MEASURED
**Clientes Activos**: 149 | MEASURED
**Margen Bruto**: 40% | ESTIMATED

---

## 🔴 CRITICAL — CRIT-1 — Cartera vencida crítica >90 días
- 42 clientes con facturas sin cobrar por más de 90 días
- Monto total en riesgo: **€840,000** (7.5% de facturación)
- Top 3: Nexum SL (€280K), Distribuciones Pepe (€145K), ZooPet Madrid (€98K)
- Acción: Activar cobranza judicial para los 8 casos >€50K

\`\`\`sql
SELECT c_bpartner.name, SUM(c_invoice.grandtotal) as deuda
FROM c_invoice
JOIN c_bpartner ON c_invoice.c_bpartner_id = c_bpartner.c_bpartner_id
WHERE c_invoice.docstatus = 'CO'
AND c_invoice.dateinvoiced < NOW() - INTERVAL '90 days'
AND c_invoice.ispaid = 'N'
GROUP BY c_bpartner.name
ORDER BY deuda DESC
\`\`\`

---

## 🟠 HIGH — HIGH-2 — Concentración de riesgo en top clientes

- 38 clientes concentran el 80% del revenue (€8.96M)
- Los 5 mayores clientes representan €4.2M — riesgo de churn crítico
- **3 de los top 10 no compraron en el último mes**

---

## 🟠 HIGH — HIGH-3 — Margen comprimido en categoría accesorios

- Margen bruto en accesorios: 28% vs 40% del promedio
- 847 SKUs con margen <15% (candidatos a discontinuar)
- Impacto de corrección estimado: +€180K anuales

---

## 🟡 MEDIUM — MED-4 — Champions inactivos

- 12 clientes clasificados como Champions (>€50K/año) sin compra en 45+ días
- Potencial de recuperación: €600K si vuelven a ritmo normal

---

## ✅ Acciones Prioritarias

1. **Cobrar €840K** — Activar protocolos de cobranza para vencidos >90d
2. **Retener Champions** — Contactar los 12 Champions inactivos esta semana
3. **Revisar pricing accesorios** — Eliminar 847 SKUs con margen <15%
4. **Diversificar cartera** — Reducir dependencia del top 5 a <60%
5. **Renegociar plazos** — Proponer financiación a los 3 clientes grandes en dificultad
`

export function DemoModeWrapper() {
  const [active, setActive] = useState(false)

  if (active) {
    return (
      <div style={{ position: 'relative' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.lg }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 10,
              fontWeight: 700,
              fontFamily: T.font.mono,
              letterSpacing: '0.08em',
              padding: '3px 10px',
              borderRadius: 999,
              backgroundColor: T.accent.teal + '15',
              border: `1px solid ${T.accent.teal}40`,
              color: T.accent.teal,
            }}>
              <Eye size={10} />MODO DEMO
            </span>
            <span style={{ fontSize: 12, color: T.text.tertiary }}>Datos sintéticos — Gloria Pet Distribution</span>
          </div>
          <button
            onClick={() => setActive(false)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 12,
              color: T.text.tertiary,
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontFamily: T.font.display,
            }}
          >
            <X size={12} />Salir del demo
          </button>
        </div>
        <DemoResultsDisplay />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center' }}>
      <DemoModeButton onEnter={() => setActive(true)} />
    </div>
  )
}

// Inline demo results without needing a real job ID
function DemoResultsDisplay() {
  const badges = [
    { label: '✓ Demo completado', color: T.accent.teal },
    { label: '1 crítico',         color: T.accent.red },
    { label: '2 altos',           color: T.accent.orange },
  ]

  const kpis = [
    { label: 'Facturación Total',   value: '€11.2M' },
    { label: 'Cobranza Pendiente',  value: '€1.6M' },
    { label: 'Clientes Activos',    value: '149' },
    { label: 'Margen Bruto',        value: '40%' },
  ]

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', paddingBottom: 80, display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
      {/* Status badges */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {badges.map(({ label, color }) => (
          <span key={label} style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 11,
            fontWeight: 600,
            fontFamily: T.font.mono,
            padding: '3px 10px',
            borderRadius: 999,
            backgroundColor: color + '15',
            border: `1px solid ${color}40`,
            color,
          }}>
            {label}
          </span>
        ))}
      </div>

      <h1 style={{ fontSize: 28, fontWeight: 700, color: T.text.primary, margin: 0 }}>
        Gloria Pet Distribution
      </h1>
      <p style={{ fontSize: 12, color: T.text.tertiary, fontFamily: T.font.mono, margin: 0 }}>
        Q1-2026 · EUR · Análisis demo
      </p>

      {/* Hero finding */}
      <div style={{
        borderRadius: T.radius.lg,
        backgroundColor: T.accent.red + '15',
        border: `1px solid ${T.accent.red}50`,
        padding: T.space.xl,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: T.accent.red, animation: 'pulse 1.5s ease-in-out infinite' }} />
          <span style={{ fontSize: 10, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.accent.red + 'CC' }}>
            Acción prioritaria · CRIT-1
          </span>
        </div>
        <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, margin: '0 0 8px' }}>
          Cartera vencida crítica &gt;90 días
        </h2>
        <p style={{ fontSize: 14, color: T.text.secondary, margin: 0 }}>
          42 clientes con facturas sin cobrar. Monto total en riesgo:{' '}
          <strong style={{ color: T.accent.red }}>€840,000</strong>
        </p>
      </div>

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
        {kpis.map((kpi, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
            style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.md,
              border: T.border.card,
              padding: T.space.lg,
            }}
          >
            <p style={{ fontSize: 11, color: T.text.tertiary, marginBottom: 4 }}>{kpi.label}</p>
            <p style={{ fontSize: 24, fontWeight: 700, color: T.text.primary, fontFamily: T.font.mono, margin: 0 }}>
              {kpi.value}
            </p>
          </motion.div>
        ))}
      </div>

      <p style={{ fontSize: 11, color: T.text.tertiary, textAlign: 'center' }}>
        Esto es una demostración con datos sintéticos. Conectá tu base de datos para ver un análisis real.
      </p>
    </div>
  )
}
