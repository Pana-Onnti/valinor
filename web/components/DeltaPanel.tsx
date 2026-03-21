'use client'

import { motion, AnimatePresence } from 'framer-motion'
import { TrendingUp, AlertOctagon, CheckCircle2, Minus, Clock, ArrowUp, ArrowDown } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

export interface FindingDelta {
  id: string
  title: string
  severity: string
  status: 'NEW' | 'PERSISTS' | 'WORSENED' | 'IMPROVED' | 'RESOLVED'
  runsOpen?: number
  previousSeverity?: string
}

interface DeltaPanelProps {
  runDelta: {
    new?: string[]
    persists?: string[]
    resolved?: string[]
    worsened?: string[]
    improved?: string[]
  }
  knownFindings?: Record<string, {
    id: string
    title: string
    severity: string
    runs_open: number
  }>
  runCount?: number
  style?: React.CSSProperties
}

const STATUS_CONFIG = {
  NEW:      { label: 'Nuevo',    icon: AlertOctagon, color: T.accent.red,    pulse: true  },
  WORSENED: { label: 'Empeoró',  icon: ArrowUp,      color: T.accent.orange, pulse: true  },
  PERSISTS: { label: 'Persiste', icon: Minus,         color: T.accent.yellow, pulse: false },
  IMPROVED: { label: 'Mejoró',   icon: ArrowDown,     color: T.accent.blue,   pulse: false },
  RESOLVED: { label: 'Resuelto', icon: CheckCircle2,  color: T.accent.teal,   pulse: false },
}

function DeltaBadge({ status, count }: { status: keyof typeof STATUS_CONFIG; count: number }) {
  if (count === 0) return null
  const cfg = STATUS_CONFIG[status]
  const Icon = cfg.icon
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      fontSize: 11,
      fontWeight: 600,
      padding: '3px 10px',
      borderRadius: 999,
      border: `1px solid ${cfg.color}40`,
      backgroundColor: cfg.color + '15',
      color: cfg.color,
    }}>
      {cfg.pulse && (
        <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: cfg.color, animation: 'pulse 1.5s ease-in-out infinite' }} />
      )}
      <Icon size={10} />
      {count} {cfg.label}{count > 1 ? 's' : ''}
    </span>
  )
}

function DeltaRow({ id, status, title, runsOpen }: {
  id: string
  status: keyof typeof STATUS_CONFIG
  title?: string
  runsOpen?: number
}) {
  const cfg = STATUS_CONFIG[status]
  const Icon = cfg.icon
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: `${T.space.sm} ${T.space.md}`,
        borderRadius: T.radius.sm,
        border: `1px solid ${cfg.color}30`,
        backgroundColor: cfg.color + '0D',
      }}
    >
      <span style={{
        flexShrink: 0,
        width: 24,
        height: 24,
        borderRadius: '50%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: cfg.color + '20',
        color: cfg.color,
      }}>
        <Icon size={12} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ fontSize: 13, fontWeight: 500, color: cfg.color, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {title || id}
        </p>
        {runsOpen && runsOpen > 1 && (
          <p style={{ fontSize: 11, color: T.text.tertiary, display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
            <Clock size={10} />
            Abierto hace {runsOpen} runs
          </p>
        )}
      </div>
      <span style={{ fontSize: 11, fontFamily: T.font.mono, color: T.text.tertiary, flexShrink: 0 }}>{id}</span>
    </motion.div>
  )
}

export function DeltaPanel({ runDelta, knownFindings, runCount, style }: DeltaPanelProps) {
  const newIds = runDelta.new || []
  const resolvedIds = runDelta.resolved || []
  const worsenedIds = runDelta.worsened || []
  const improvedIds = runDelta.improved || []
  const persistsIds = runDelta.persists || []

  const totalChanges = newIds.length + resolvedIds.length + worsenedIds.length + improvedIds.length
  if (totalChanges === 0 && persistsIds.length === 0) return null

  const getTitle = (id: string) => knownFindings?.[id]?.title
  const getRunsOpen = (id: string) => knownFindings?.[id]?.runs_open

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        borderRadius: T.radius.md,
        border: T.border.card,
        overflow: 'hidden',
        ...style,
      }}
    >
      {/* Header */}
      <div style={{
        padding: `${T.space.sm} ${T.space.lg}`,
        backgroundColor: T.bg.elevated,
        borderBottom: T.border.card,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap' as const,
        gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <TrendingUp size={14} style={{ color: T.accent.teal }} />
          <h3 style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', textTransform: 'uppercase' as const, color: T.text.tertiary, margin: 0, fontFamily: T.font.mono }}>
            Delta vs Run Anterior
          </h3>
          {runCount && runCount > 1 && (
            <span style={{ fontSize: 11, color: T.text.tertiary, fontFamily: T.font.mono }}>Run #{runCount}</span>
          )}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap' as const, gap: 6 }}>
          <DeltaBadge status="NEW" count={newIds.length} />
          <DeltaBadge status="WORSENED" count={worsenedIds.length} />
          <DeltaBadge status="IMPROVED" count={improvedIds.length} />
          <DeltaBadge status="RESOLVED" count={resolvedIds.length} />
        </div>
      </div>

      {/* Content */}
      <div style={{ padding: T.space.md, backgroundColor: T.bg.card, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <AnimatePresence>
          {worsenedIds.map(id => <DeltaRow key={id} id={id} status="WORSENED" title={getTitle(id)} runsOpen={getRunsOpen(id)} />)}
          {newIds.map(id => <DeltaRow key={id} id={id} status="NEW" title={getTitle(id)} runsOpen={getRunsOpen(id)} />)}
          {improvedIds.map(id => <DeltaRow key={id} id={id} status="IMPROVED" title={getTitle(id)} runsOpen={getRunsOpen(id)} />)}
          {resolvedIds.map(id => <DeltaRow key={id} id={id} status="RESOLVED" title={getTitle(id)} runsOpen={undefined} />)}
          {persistsIds.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: `${T.space.xs} ${T.space.sm}` }}>
              <Minus size={12} style={{ color: T.accent.yellow, flexShrink: 0 }} />
              <p style={{ fontSize: 12, color: T.text.secondary, margin: 0 }}>
                {persistsIds.length} hallazgo{persistsIds.length > 1 ? 's persisten' : ' persiste'} sin cambios
              </p>
            </div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
