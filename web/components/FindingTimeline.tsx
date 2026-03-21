'use client'

import { motion } from 'framer-motion'
import { Clock, CheckCircle2 } from 'lucide-react'
import { T, SEV_COLOR } from '@/components/d4c/tokens'

interface FindingRecord {
  id: string
  title: string
  severity: string
  first_seen: string
  last_seen: string
  runs_open: number
  resolved_at?: string
}

interface FindingTimelineProps {
  active: Record<string, FindingRecord>
  resolved: Record<string, FindingRecord>
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short' })
  } catch {
    return iso.slice(0, 10)
  }
}

function TimelineRow({ rec, resolved = false }: { rec: FindingRecord; resolved?: boolean }) {
  const dotColor = resolved ? T.accent.teal : (SEV_COLOR[rec.severity] ?? T.text.tertiary)

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: `${T.space.sm} 0` }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0, marginTop: 4 }}>
        <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: dotColor, display: 'block' }} />
        {!resolved && rec.runs_open > 1 && (
          <div style={{ width: 1, height: 32, backgroundColor: T.bg.hover, marginTop: 4 }} />
        )}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <p style={{
            fontSize: 13,
            fontWeight: 500,
            lineHeight: 1.4,
            color: resolved ? T.text.tertiary : T.text.primary,
            textDecoration: resolved ? 'line-through' : 'none',
            margin: 0,
          }}>
            {rec.title}
          </p>
          {!resolved && rec.runs_open > 1 && (
            <span style={{
              flexShrink: 0,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 11,
              color: T.accent.yellow,
              backgroundColor: T.accent.yellow + '15',
              border: `1px solid ${T.accent.yellow}30`,
              borderRadius: 999,
              padding: '2px 8px',
            }}>
              <Clock size={10} />{rec.runs_open} runs
            </span>
          )}
          {resolved && (
            <span style={{
              flexShrink: 0,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              fontSize: 11,
              color: T.accent.teal,
            }}>
              <CheckCircle2 size={10} />resuelto
            </span>
          )}
        </div>
        <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2, fontFamily: T.font.mono }}>
          {rec.id} · desde {formatDate(rec.first_seen)}
          {resolved && rec.resolved_at && ` → ${formatDate(rec.resolved_at)}`}
        </p>
      </div>
    </motion.div>
  )
}

export function FindingTimeline({ active, resolved }: FindingTimelineProps) {
  const activeList = Object.values(active).sort((a, b) => b.runs_open - a.runs_open)
  const resolvedList = Object.values(resolved).sort((a, b) =>
    (b.resolved_at || '').localeCompare(a.resolved_at || '')
  ).slice(0, 10)

  if (activeList.length === 0 && resolvedList.length === 0) return null

  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.md,
      border: T.border.card,
      overflow: 'hidden',
    }}>
      <div style={{
        padding: `${T.space.sm} ${T.space.lg}`,
        borderBottom: T.border.card,
        backgroundColor: T.bg.elevated,
      }}>
        <h3 style={{
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.1em',
          textTransform: 'uppercase',
          color: T.text.tertiary,
          margin: 0,
          fontFamily: T.font.mono,
        }}>
          Timeline de Hallazgos
        </h3>
      </div>
      <div style={{ padding: `0 ${T.space.lg}` }}>
        {activeList.map(rec => <TimelineRow key={rec.id} rec={rec} />)}
        {resolvedList.map(rec => <TimelineRow key={rec.id} rec={rec} resolved />)}
      </div>
    </div>
  )
}
