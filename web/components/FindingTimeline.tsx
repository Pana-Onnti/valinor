'use client'

import { motion } from 'framer-motion'
import { AlertOctagon, AlertTriangle, Info, CheckCircle2, Clock } from 'lucide-react'

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

const SEV_COLORS: Record<string, string> = {
  CRITICAL: 'bg-red-500',
  HIGH: 'bg-orange-500',
  MEDIUM: 'bg-yellow-400',
  LOW: 'bg-blue-400',
  INFO: 'bg-gray-400',
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short' })
  } catch {
    return iso.slice(0, 10)
  }
}

function TimelineRow({ rec, resolved = false }: { rec: FindingRecord; resolved?: boolean }) {
  const dotColor = resolved ? 'bg-emerald-400' : (SEV_COLORS[rec.severity] || 'bg-gray-400')
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      className="flex items-start gap-3 py-3"
    >
      <div className="flex flex-col items-center flex-shrink-0 mt-1">
        <span className={`w-2.5 h-2.5 rounded-full ${dotColor}`} />
        {!resolved && rec.runs_open > 1 && (
          <div className="w-px h-8 bg-gray-200 dark:bg-gray-700 mt-1" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className={`text-sm font-medium leading-snug ${resolved ? 'text-gray-400 line-through' : 'text-gray-800 dark:text-gray-200'}`}>
            {rec.title}
          </p>
          {!resolved && rec.runs_open > 1 && (
            <span className="flex-shrink-0 flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/30 px-2 py-0.5 rounded-full">
              <Clock className="h-3 w-3" />{rec.runs_open} runs
            </span>
          )}
          {resolved && (
            <span className="flex-shrink-0 flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="h-3 w-3" />resuelto
            </span>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-0.5 font-mono">
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
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
      <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
        <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
          Timeline de Hallazgos
        </h3>
      </div>
      <div className="px-5 divide-y divide-gray-50 dark:divide-gray-800/50">
        {activeList.map(rec => <TimelineRow key={rec.id} rec={rec} />)}
        {resolvedList.map(rec => <TimelineRow key={rec.id} rec={rec} resolved />)}
      </div>
    </div>
  )
}
