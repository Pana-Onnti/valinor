'use client'

import { T } from '@/components/d4c/tokens'
import { motion } from 'framer-motion'
import type { TrustScoreBreakdown as TrustScoreBreakdownType } from '@/lib/confidence-types'

// ── Types ────────────────────────────────────────────────────────────────────

interface BreakdownBarDef {
  label: string
  value: number
  max: number
  tooltip: string
}

interface TrustScoreBreakdownProps {
  breakdown: TrustScoreBreakdownType
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getBarColor(ratio: number): string {
  if (ratio >= 0.9) return T.accent.teal
  if (ratio >= 0.7) return T.accent.yellow
  if (ratio >= 0.5) return T.accent.orange
  return T.accent.red
}

// ── Component ────────────────────────────────────────────────────────────────

export function TrustScoreBreakdown({ breakdown }: TrustScoreBreakdownProps) {
  const bars: BreakdownBarDef[] = [
    {
      label: 'Calidad de datos',
      value: breakdown.dq_component,
      max: 30,
      tooltip: 'Puntaje del gate de calidad de datos: completitud, formato, consistencia temporal y duplicados.',
    },
    {
      label: 'Verificación',
      value: breakdown.verification_component,
      max: 25,
      tooltip: 'Verificación cruzada de cifras contra el Knowledge Graph y motor anti-alucinación.',
    },
    {
      label: 'Cobertura NULL',
      value: breakdown.null_density_component,
      max: 15,
      tooltip: 'Densidad de valores nulos en columnas clave. Menor densidad = mayor puntaje.',
    },
    {
      label: 'Cobertura de schema',
      value: breakdown.schema_coverage_component,
      max: 15,
      tooltip: 'Proporción de tablas y columnas esperadas que fueron encontradas en la fuente.',
    },
    {
      label: 'Reconciliación agentes',
      value: breakdown.reconciliation_component,
      max: 15,
      tooltip: 'Grado de acuerdo entre los agentes del swarm al verificar hallazgos.',
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>
      {bars.map((bar, i) => {
        const ratio = bar.max > 0 ? bar.value / bar.max : 0
        const color = getBarColor(ratio)

        return (
          <motion.div
            key={bar.label}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, delay: i * 0.1 }}
            title={bar.tooltip}
            style={{ cursor: 'help' }}
          >
            {/* Label row */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              marginBottom: T.space.xs,
            }}>
              <span style={{
                fontFamily: T.font.display,
                fontSize: 13,
                color: T.text.secondary,
              }}>
                {bar.label}
              </span>
              <span style={{
                fontFamily: T.font.mono,
                fontSize: 13,
                fontWeight: 600,
                color: T.text.primary,
              }}>
                {Math.round(bar.value)}/{bar.max}
              </span>
            </div>

            {/* Bar track */}
            <div style={{
              width: '100%',
              height: 4,
              background: T.bg.elevated,
              borderRadius: 2,
              overflow: 'hidden',
            }}>
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${Math.min(ratio * 100, 100)}%` }}
                transition={{ duration: 0.6, delay: i * 0.1, ease: 'easeOut' }}
                style={{
                  height: '100%',
                  background: color,
                  borderRadius: 2,
                }}
              />
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
