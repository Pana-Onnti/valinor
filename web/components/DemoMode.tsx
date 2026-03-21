'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, X, Eye } from 'lucide-react'

// Synthetic demo job ID — the API will serve demo data when this ID is requested
export const DEMO_JOB_ID = '__demo__'

interface DemoModeProps {
  onExit?: () => void
}

export function DemoModeButton({ onEnter }: { onEnter: () => void }) {
  return (
    <button
      onClick={onEnter}
      className="flex items-center gap-2 px-4 py-2 border border-gray-200 dark:border-gray-700 rounded-xl text-sm text-gray-600 dark:text-gray-400 hover:border-violet-400 dark:hover:border-violet-600 hover:text-violet-600 dark:hover:text-violet-400 transition-all"
    >
      <Eye className="h-4 w-4" />
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
      <div className="relative">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-800">
              <Eye className="h-3 w-3" />MODO DEMO
            </span>
            <span className="text-xs text-gray-400">Datos sintéticos — Gloria Pet Distribution</span>
          </div>
          <button
            onClick={() => setActive(false)}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
          >
            <X className="h-3.5 w-3.5" />Salir del demo
          </button>
        </div>
        <DemoResultsDisplay />
      </div>
    )
  }

  return (
    <div className="flex justify-center">
      <DemoModeButton onEnter={() => setActive(true)} />
    </div>
  )
}

// Inline demo results without needing a real job ID
function DemoResultsDisplay() {
  return (
    <div className="max-w-5xl mx-auto space-y-6 pb-20">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
          ✓ Demo completado
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-red-50 text-red-700 border border-red-200">
          ⚠ 1 crítico
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-orange-50 text-orange-700 border border-orange-200">
          2 altos
        </span>
      </div>

      <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Gloria Pet Distribution</h1>
      <p className="text-sm text-gray-400 font-mono">Q1-2026 · EUR · Análisis demo</p>

      {/* Hero finding */}
      <div className="rounded-3xl bg-gradient-to-br from-red-950 via-red-900 to-red-800 border border-red-700 p-7">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
          <span className="text-xs font-mono tracking-widest text-red-300/80 uppercase">Acción prioritaria · CRIT-1</span>
        </div>
        <h2 className="text-2xl font-bold text-white mb-2">Cartera vencida crítica &gt;90 días</h2>
        <p className="text-red-100/80">42 clientes con facturas sin cobrar. Monto total en riesgo: <strong>€840,000</strong></p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Facturación Total', value: '€11.2M' },
          { label: 'Cobranza Pendiente', value: '€1.6M' },
          { label: 'Clientes Activos', value: '149' },
          { label: 'Margen Bruto', value: '40%' },
        ].map((kpi, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
            className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm"
          >
            <p className="text-xs text-gray-500 mb-1">{kpi.label}</p>
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{kpi.value}</p>
          </motion.div>
        ))}
      </div>

      <p className="text-xs text-gray-400 text-center">
        Esto es una demostración con datos sintéticos. Conectá tu base de datos para ver un análisis real.
      </p>
    </div>
  )
}
