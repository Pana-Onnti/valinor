'use client'

import { motion, AnimatePresence } from 'framer-motion'
import {
  TrendingUp, TrendingDown, AlertOctagon, CheckCircle2,
  Minus, Clock, AlertTriangle, ArrowUp, ArrowDown
} from 'lucide-react'

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
  className?: string
}

const STATUS_CONFIG = {
  NEW: {
    label: 'Nuevo',
    icon: AlertOctagon,
    bg: 'bg-red-50 dark:bg-red-900/20',
    border: 'border-red-200 dark:border-red-800',
    text: 'text-red-700 dark:text-red-300',
    dot: 'bg-red-500',
    pulse: true,
  },
  WORSENED: {
    label: 'Empeoró',
    icon: ArrowUp,
    bg: 'bg-orange-50 dark:bg-orange-900/20',
    border: 'border-orange-200 dark:border-orange-800',
    text: 'text-orange-700 dark:text-orange-300',
    dot: 'bg-orange-500',
    pulse: true,
  },
  PERSISTS: {
    label: 'Persiste',
    icon: Minus,
    bg: 'bg-amber-50 dark:bg-amber-900/20',
    border: 'border-amber-200 dark:border-amber-800',
    text: 'text-amber-700 dark:text-amber-300',
    dot: 'bg-amber-400',
    pulse: false,
  },
  IMPROVED: {
    label: 'Mejoró',
    icon: ArrowDown,
    bg: 'bg-blue-50 dark:bg-blue-900/20',
    border: 'border-blue-200 dark:border-blue-800',
    text: 'text-blue-700 dark:text-blue-300',
    dot: 'bg-blue-400',
    pulse: false,
  },
  RESOLVED: {
    label: 'Resuelto',
    icon: CheckCircle2,
    bg: 'bg-emerald-50 dark:bg-emerald-900/20',
    border: 'border-emerald-200 dark:border-emerald-800',
    text: 'text-emerald-700 dark:text-emerald-300',
    dot: 'bg-emerald-400',
    pulse: false,
  },
}

function DeltaBadge({ status, count }: { status: keyof typeof STATUS_CONFIG; count: number }) {
  if (count === 0) return null
  const cfg = STATUS_CONFIG[status]
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${cfg.bg} ${cfg.border} ${cfg.text}`}>
      {cfg.pulse && <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot} animate-pulse`} />}
      <Icon className="h-3 w-3" />
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
      className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border ${cfg.border} ${cfg.bg}`}
    >
      <span className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${cfg.bg} ${cfg.text}`}>
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="flex-1 min-w-0">
        <p className={`text-sm font-medium ${cfg.text} truncate`}>{title || id}</p>
        {runsOpen && runsOpen > 1 && (
          <p className="text-xs text-gray-400 flex items-center gap-1 mt-0.5">
            <Clock className="h-3 w-3" />
            Abierto hace {runsOpen} runs
          </p>
        )}
      </div>
      <span className="text-xs font-mono text-gray-400 flex-shrink-0">{id}</span>
    </motion.div>
  )
}

export function DeltaPanel({ runDelta, knownFindings, runCount, className = '' }: DeltaPanelProps) {
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
      className={`rounded-2xl border border-gray-200 dark:border-gray-700 overflow-hidden shadow-sm ${className}`}
    >
      {/* Header */}
      <div className="px-5 py-3 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-violet-500" />
            <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
              Delta vs Run Anterior
            </h3>
            {runCount && runCount > 1 && (
              <span className="text-xs text-gray-400 font-mono">Run #{runCount}</span>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <DeltaBadge status="NEW" count={newIds.length} />
            <DeltaBadge status="WORSENED" count={worsenedIds.length} />
            <DeltaBadge status="IMPROVED" count={improvedIds.length} />
            <DeltaBadge status="RESOLVED" count={resolvedIds.length} />
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-4 bg-white dark:bg-gray-900 space-y-2">
        <AnimatePresence>
          {/* Worsened first — most urgent */}
          {worsenedIds.map(id => (
            <DeltaRow key={id} id={id} status="WORSENED"
              title={getTitle(id)} runsOpen={getRunsOpen(id)} />
          ))}
          {/* New findings */}
          {newIds.map(id => (
            <DeltaRow key={id} id={id} status="NEW"
              title={getTitle(id)} runsOpen={getRunsOpen(id)} />
          ))}
          {/* Improved */}
          {improvedIds.map(id => (
            <DeltaRow key={id} id={id} status="IMPROVED"
              title={getTitle(id)} runsOpen={getRunsOpen(id)} />
          ))}
          {/* Resolved — good news */}
          {resolvedIds.map(id => (
            <DeltaRow key={id} id={id} status="RESOLVED"
              title={getTitle(id)} runsOpen={undefined} />
          ))}
          {/* Persistent findings (compact) */}
          {persistsIds.length > 0 && (
            <div className="flex items-center gap-2 px-3 py-2">
              <Minus className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" />
              <p className="text-xs text-gray-400">
                {persistsIds.length} hallazgo{persistsIds.length > 1 ? 's persisten' : ' persiste'} sin cambios
              </p>
            </div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
