'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, Shield } from 'lucide-react'
import { T } from '@/components/d4c/tokens'
import { TrustScoreBreakdown } from './TrustScoreBreakdown'
import type { TrustScoreBreakdown as TrustScoreBreakdownType } from '@/lib/confidence-types'

// ── Types ────────────────────────────────────────────────────────────────────

interface TrustScoreHeaderProps {
  trustScore: TrustScoreBreakdownType
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function getScoreColor(score: number): string {
  if (score >= 90) return T.accent.teal
  if (score >= 70) return T.accent.yellow
  if (score >= 50) return T.accent.orange
  return T.accent.red
}

function getScoreLabel(score: number): string {
  if (score >= 90) return 'Confianza alta'
  if (score >= 70) return 'Confianza moderada'
  if (score >= 50) return 'Confianza limitada'
  return 'Verificación requerida'
}

// ── Component ────────────────────────────────────────────────────────────────

export function TrustScoreHeader({ trustScore }: TrustScoreHeaderProps) {
  const [expanded, setExpanded] = useState(false)
  const [displayValue, setDisplayValue] = useState(0)

  const targetValue = trustScore.overall
  const color = getScoreColor(targetValue)
  const label = getScoreLabel(targetValue)

  // Count-up animation
  useEffect(() => {
    const duration = 1200
    const start = performance.now()
    let raf: number

    const animate = (now: number) => {
      const elapsed = now - start
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3) // ease-out cubic
      setDisplayValue(Math.round(eased * targetValue))
      if (progress < 1) {
        raf = requestAnimationFrame(animate)
      }
    }

    raf = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(raf)
  }, [targetValue])

  return (
    <div style={{
      padding: T.space.xl,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
    }}>
      {/* Shield icon */}
      <Shield
        size={20}
        style={{ color, marginBottom: T.space.sm, opacity: 0.7 }}
      />

      {/* Big number */}
      <div style={{
        fontFamily: T.font.display,
        fontSize: 46,
        fontWeight: 600,
        color,
        lineHeight: 1.1,
        letterSpacing: '-0.02em',
      }}>
        {displayValue}
      </div>

      {/* Label */}
      <div style={{
        fontFamily: T.font.display,
        fontSize: 13,
        color: T.text.secondary,
        marginTop: T.space.xs,
        marginBottom: T.space.md,
      }}>
        {label}
      </div>

      {/* Progress bar */}
      <div style={{
        width: '100%',
        maxWidth: 320,
        height: 6,
        background: T.bg.elevated,
        borderRadius: 3,
        overflow: 'hidden',
        marginBottom: T.space.md,
      }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(targetValue, 100)}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          style={{
            height: '100%',
            background: color,
            borderRadius: 3,
          }}
        />
      </div>

      {/* Toggle */}
      <button
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: T.space.xs,
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          fontFamily: T.font.display,
          fontSize: 12,
          color: T.text.tertiary,
          padding: `${T.space.xs} ${T.space.sm}`,
          borderRadius: T.radius.sm,
          transition: 'color 0.15s',
        }}
        onMouseEnter={e => (e.currentTarget.style.color = T.text.secondary)}
        onMouseLeave={e => (e.currentTarget.style.color = T.text.tertiary)}
      >
        Ver detalle
        <motion.span
          animate={{ rotate: expanded ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          style={{ display: 'flex', alignItems: 'center' }}
        >
          <ChevronDown size={14} />
        </motion.span>
      </button>

      {/* Breakdown panel */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: 'easeInOut' }}
            style={{
              overflow: 'hidden',
              width: '100%',
              maxWidth: 480,
            }}
          >
            <div style={{
              paddingTop: T.space.lg,
              borderTop: T.border.subtle,
              marginTop: T.space.md,
            }}>
              <TrustScoreBreakdown breakdown={trustScore} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
