'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { T } from '@/components/d4c/tokens'
import type { ConfidenceLevel, FindingConfidence } from '@/lib/confidence-types'

// ── Config por nivel ─────────────────────────────────────────────────────────

const LEVEL_CONFIG: Record<ConfidenceLevel, { color: string; icon: string; label: string }> = {
  verified:       { color: T.accent.teal,   icon: '\u2713', label: 'Verificado' },
  estimated:      { color: T.accent.yellow, icon: '~',      label: 'Estimado' },
  low_confidence: { color: T.accent.red,    icon: '!',      label: 'Baja confianza' },
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

function ConfidenceTooltip({ data }: { data: Pick<FindingConfidence, 'record_count' | 'null_rate' | 'source_tables'> }) {
  return (
    <div style={{
      position: 'absolute',
      bottom: 'calc(100% + 6px)',
      left: '50%',
      transform: 'translateX(-50%)',
      background: T.bg.elevated,
      border: T.border.card,
      borderRadius: T.radius.sm,
      padding: `${T.space.sm} ${T.space.md}`,
      fontFamily: T.font.mono,
      fontSize: 11,
      color: T.text.secondary,
      whiteSpace: 'nowrap',
      zIndex: 1000,
      pointerEvents: 'none',
      minWidth: 180,
    }}>
      {/* Arrow */}
      <div style={{
        position: 'absolute',
        bottom: -4,
        left: '50%',
        transform: 'translateX(-50%) rotate(45deg)',
        width: 8,
        height: 8,
        background: T.bg.elevated,
        borderRight: T.border.card,
        borderBottom: T.border.card,
      }} />
      <div style={{ marginBottom: 4 }}>
        <span style={{ color: T.text.tertiary }}>Registros: </span>
        <span style={{ color: T.text.primary }}>{data.record_count.toLocaleString('es-AR')}</span>
      </div>
      <div style={{ marginBottom: 4 }}>
        <span style={{ color: T.text.tertiary }}>NULL rate: </span>
        <span style={{ color: T.text.primary }}>{(data.null_rate * 100).toFixed(1)}%</span>
      </div>
      {data.source_tables.length > 0 && (
        <div>
          <span style={{ color: T.text.tertiary }}>Tablas: </span>
          <span style={{ color: T.text.primary }}>{data.source_tables.join(', ')}</span>
        </div>
      )}
    </div>
  )
}

// ── ConfidenceBadge ──────────────────────────────────────────────────────────

interface ConfidenceBadgeProps {
  level: ConfidenceLevel
  tooltip?: Pick<FindingConfidence, 'record_count' | 'null_rate' | 'source_tables'>
  delay?: number  // stagger delay in seconds
}

export function ConfidenceBadge({ level, tooltip, delay = 0 }: ConfidenceBadgeProps) {
  const [hovered, setHovered] = useState(false)
  const config = LEVEL_CONFIG[level]

  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25, delay }}
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span style={{
        fontFamily: T.font.mono,
        fontSize: 11,
        fontWeight: 600,
        letterSpacing: '0.5px',
        textTransform: 'uppercase' as const,
        color: config.color,
        background: config.color + '18',
        border: `1px solid ${config.color}40`,
        borderRadius: T.radius.sm,
        padding: '2px 8px',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        cursor: 'default',
        lineHeight: 1.4,
      }}>
        <span style={{ fontSize: 12, lineHeight: 1 }}>{config.icon}</span>
        {config.label}
      </span>
      {hovered && tooltip && <ConfidenceTooltip data={tooltip} />}
    </motion.span>
  )
}

// ── MicroBadge (icon only, for KPI cards) ────────────────────────────────────

interface MicroBadgeProps {
  level: ConfidenceLevel
  tooltip?: Pick<FindingConfidence, 'record_count' | 'null_rate' | 'source_tables'>
  delay?: number
}

export function MicroBadge({ level, tooltip, delay = 0 }: MicroBadgeProps) {
  const [hovered, setHovered] = useState(false)
  const config = LEVEL_CONFIG[level]

  return (
    <motion.span
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25, delay }}
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span style={{
        fontFamily: T.font.mono,
        fontSize: 10,
        fontWeight: 700,
        width: 18,
        height: 18,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: config.color,
        background: config.color + '18',
        border: `1px solid ${config.color}40`,
        borderRadius: '50%',
        cursor: 'default',
        lineHeight: 1,
      }}>
        {config.icon}
      </span>
      {hovered && tooltip && <ConfidenceTooltip data={tooltip} />}
    </motion.span>
  )
}
