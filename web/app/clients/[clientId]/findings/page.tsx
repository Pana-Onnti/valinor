'use client'

import { useEffect, useState, useMemo } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useClientProfile } from '@/lib/hooks'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

interface Finding {
  id: string
  title: string
  description?: string
  severity: Severity
  agent: string
  first_seen: string
  runs_open: number
  status: 'active' | 'resolved' | 'false_positive'
  auto_escalated?: boolean
}

interface FindingsData {
  client_name: string
  findings: Finding[]
}

type FilterValue = 'ALL' | Severity

// ── Constants ─────────────────────────────────────────────────────────────────

const SEVERITY_ORDER: Record<Severity, number> = {
  CRITICAL: 0,
  HIGH: 1,
  MEDIUM: 2,
  LOW: 3,
}

const FILTER_OPTIONS: { value: FilterValue; label: string; color: string; activeColor: string }[] = [
  { value: 'ALL',      label: 'Todos',    color: 'border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400', activeColor: 'bg-violet-600 text-white border-violet-600' },
  { value: 'CRITICAL', label: 'CRITICAL', color: 'border-red-200 dark:border-red-800 text-red-600 dark:text-red-400',     activeColor: 'bg-red-600 text-white border-red-600' },
  { value: 'HIGH',     label: 'HIGH',     color: 'border-orange-200 dark:border-orange-800 text-orange-600 dark:text-orange-400', activeColor: 'bg-orange-500 text-white border-orange-500' },
  { value: 'MEDIUM',   label: 'MEDIUM',   color: 'border-yellow-200 dark:border-yellow-700 text-yellow-600 dark:text-yellow-400', activeColor: 'bg-yellow-500 text-white border-yellow-500' },
  { value: 'LOW',      label: 'LOW',      color: 'border-blue-200 dark:border-blue-800 text-blue-600 dark:text-blue-400',  activeColor: 'bg-blue-500 text-white border-blue-500' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function agentLabel(agent: string) {
  const map: Record<string, string> = {
    analyst: 'Analyst',
    sentinel: 'Sentinel',
    hunter: 'Hunter',
  }
  return map[agent.toLowerCase()] ?? agent
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: Severity }) {
  const base = 'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold'
  const styles: Record<Severity, string> = {
    CRITICAL: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    HIGH:     'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
    MEDIUM:   'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
    LOW:      'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300',
  }
  return (
    <span className={`${base} ${styles[severity]}`}>
      {severity}
    </span>
  )
}

function AgentChip({ agent }: { agent: string }) {
  const base = 'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium'
  const styles: Record<string, string> = {
    analyst:  'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
    sentinel: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
    hunter:   'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
  }
  const key = agent.toLowerCase()
  return (
    <span className={`${base} ${styles[key] ?? 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'}`}>
      {agentLabel(agent)}
    </span>
  )
}

// ── Summary bar ───────────────────────────────────────────────────────────────

function SummaryBar({ findings }: { findings: Finding[] }) {
  const active   = findings.filter(f => f.status === 'active').length
  const critical = findings.filter(f => f.status === 'active' && f.severity === 'CRITICAL').length
  const high     = findings.filter(f => f.status === 'active' && f.severity === 'HIGH').length
  const resolved = findings.filter(f => f.status === 'resolved').length

  const stats = [
    { label: 'Activos',  value: active,   color: 'text-gray-900 dark:text-white',       bg: 'bg-white dark:bg-gray-900',           border: 'border-gray-200 dark:border-gray-700' },
    { label: 'Críticos', value: critical,  color: 'text-red-600 dark:text-red-400',      bg: 'bg-red-50 dark:bg-red-900/20',        border: 'border-red-200 dark:border-red-800' },
    { label: 'Altos',    value: high,      color: 'text-orange-600 dark:text-orange-400', bg: 'bg-orange-50 dark:bg-orange-900/20', border: 'border-orange-200 dark:border-orange-800' },
    { label: 'Resueltos', value: resolved, color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-900/20', border: 'border-emerald-200 dark:border-emerald-800' },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {stats.map(s => (
        <div key={s.label} className={`${s.bg} ${s.border} border rounded-2xl px-5 py-4 shadow-sm`}>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1">{s.label}</p>
          <p className={`text-2xl font-bold tabular-nums ${s.color}`}>{s.value}</p>
        </div>
      ))}
    </div>
  )
}

// ── Severity filter tabs ───────────────────────────────────────────────────────

function SeverityTabs({
  filter,
  onChange,
  counts,
}: {
  filter: FilterValue
  onChange: (v: FilterValue) => void
  counts: Record<FilterValue, number>
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {FILTER_OPTIONS.map(opt => {
        const isActive = filter === opt.value
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-sm font-semibold transition-all border ${
              isActive ? opt.activeColor + ' shadow-sm' : `bg-white dark:bg-gray-900 hover:opacity-80 ${opt.color}`
            }`}
          >
            {opt.label}
            <span
              className={`text-xs font-bold tabular-nums px-1.5 py-0.5 rounded-full min-w-[20px] text-center ${
                isActive
                  ? 'bg-white/20'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'
              }`}
            >
              {counts[opt.value]}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ── Finding card ──────────────────────────────────────────────────────────────

interface FindingCardProps {
  finding: Finding
  clientId: string
  onMarkFalsePositive: (id: string) => void
  marking: boolean
}

function FindingCard({ finding, clientId, onMarkFalsePositive, marking }: FindingCardProps) {
  const severityBorder: Record<Severity, string> = {
    CRITICAL: 'border-l-red-500',
    HIGH:     'border-l-orange-400',
    MEDIUM:   'border-l-yellow-400',
    LOW:      'border-l-blue-400',
  }

  // Truncate finding ID to 8 chars for display
  const shortId = finding.id.length > 8 ? finding.id.slice(0, 8) : finding.id

  return (
    <div
      className={`bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 border-l-4 ${severityBorder[finding.severity]} px-5 py-4 shadow-sm`}
    >
      <div className="flex items-start justify-between gap-4">
        {/* Left: content */}
        <div className="flex-1 min-w-0 space-y-2">

          {/* Badges row */}
          <div className="flex items-center gap-2 flex-wrap">
            <SeverityBadge severity={finding.severity} />
            <AgentChip agent={finding.agent} />
            {finding.auto_escalated && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18" />
                </svg>
                Escalado
              </span>
            )}
          </div>

          {/* Title */}
          <p className="text-sm font-bold text-gray-900 dark:text-white leading-snug">
            {finding.title}
          </p>

          {/* Description */}
          {finding.description && (
            <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed line-clamp-2">
              {finding.description}
            </p>
          )}

          {/* Meta row */}
          <div className="flex items-center gap-4 flex-wrap pt-0.5">
            {/* Finding ID */}
            <span className="inline-flex items-center gap-1 text-xs font-mono text-gray-400 dark:text-gray-500">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 8.25h15m-16.5 7.5h15m-1.8-13.5l-3.9 19.5m-2.1-19.5l-3.9 19.5" />
              </svg>
              <span className="select-all">{shortId}</span>
            </span>

            {/* First seen */}
            <span className="text-xs text-gray-400">
              Detectado:{' '}
              <span className="text-gray-600 dark:text-gray-300 font-medium">
                {formatDate(finding.first_seen)}
              </span>
            </span>

            {/* Runs open badge */}
            <span className="inline-flex items-center gap-1 text-xs">
              <span className="font-medium text-gray-400">Runs abierto:</span>
              <span className={`tabular-nums font-bold px-1.5 py-0.5 rounded-full text-xs ${
                finding.runs_open >= 5
                  ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                  : finding.runs_open >= 3
                  ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400'
                  : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'
              }`}>
                {finding.runs_open}
              </span>
            </span>
          </div>
        </div>

        {/* Right: action */}
        {finding.status === 'active' && (
          <button
            onClick={() => onMarkFalsePositive(finding.id)}
            disabled={marking}
            className="flex-shrink-0 px-3 py-1.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 border border-gray-200 dark:border-gray-700 hover:border-red-300 dark:hover:border-red-700 rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {marking ? (
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 border-2 border-gray-300 border-t-gray-500 rounded-full animate-spin" />
                Guardando…
              </span>
            ) : (
              'Falso positivo'
            )}
          </button>
        )}

        {finding.status === 'false_positive' && (
          <span className="flex-shrink-0 inline-flex items-center px-2.5 py-1 rounded-xl text-xs font-medium bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500">
            Falso positivo
          </span>
        )}
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ severity }: { severity: FilterValue }) {
  const msgs: Record<FilterValue, { title: string; sub?: string }> = {
    ALL:      { title: 'No hay hallazgos activos.',      sub: 'Los hallazgos aparecerán tras ejecutar un análisis.' },
    CRITICAL: { title: 'No hay hallazgos CRITICAL.',     sub: 'Este cliente no presenta hallazgos de severidad crítica.' },
    HIGH:     { title: 'No hay hallazgos HIGH.',         sub: 'No se detectaron hallazgos de severidad alta.' },
    MEDIUM:   { title: 'No hay hallazgos MEDIUM.',       sub: 'No se detectaron hallazgos de severidad media.' },
    LOW:      { title: 'No hay hallazgos LOW.',          sub: 'No se detectaron hallazgos de severidad baja.' },
  }
  const { title, sub } = msgs[severity]
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-14 text-center shadow-sm">
      <div className="mx-auto mb-4 w-12 h-12 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
        <svg className="w-6 h-6 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <p className="text-sm font-medium text-gray-500 dark:text-gray-400">{title}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ClientFindingsPage() {
  const params   = useParams()
  const clientId = params.clientId as string

  // Client profile via hook (used for header context: industry, last run)
  const { data: profile } = useClientProfile(clientId)

  const [data,      setData]      = useState<FindingsData | null>(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState<string | null>(null)
  const [filter,    setFilter]    = useState<FilterValue>('ALL')
  const [markingId, setMarkingId] = useState<string | null>(null)
  const [toastMsg,  setToastMsg]  = useState<string | null>(null)

  const fetchFindings = () => {
    setLoading(true)
    setError(null)
    fetch(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/findings`)
      .then(async res => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body?.detail || `Error ${res.status}`)
        }
        return res.json()
      })
      .then((d: FindingsData) => setData(d))
      .catch(err => setError(err.message || 'Error cargando hallazgos'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchFindings() }, [clientId])

  const showToast = (msg: string) => {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(null), 3500)
  }

  const handleMarkFalsePositive = async (findingId: string) => {
    setMarkingId(findingId)
    try {
      const res = await fetch(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile/false-positive?finding_id=${encodeURIComponent(findingId)}`,
        { method: 'PUT' }
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || `Error ${res.status}`)
      }
      setData(prev =>
        prev
          ? { ...prev, findings: prev.findings.map(f => f.id === findingId ? { ...f, status: 'false_positive' } : f) }
          : prev
      )
      showToast('Hallazgo marcado como falso positivo.')
    } catch (err: any) {
      setError(err.message || 'Error al actualizar el hallazgo')
    } finally {
      setMarkingId(null)
    }
  }

  // ── Derived data ────────────────────────────────────────────────────────────

  const allFindings = data?.findings ?? []

  // Sort by severity (CRITICAL first) then by runs_open desc
  const sortedFindings = useMemo(() =>
    [...allFindings].sort((a, b) => {
      const sev = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
      return sev !== 0 ? sev : b.runs_open - a.runs_open
    }),
    [allFindings]
  )

  const filteredFindings = filter === 'ALL'
    ? sortedFindings
    : sortedFindings.filter(f => f.severity === filter)

  // Per-tab counts
  const counts = useMemo(() => {
    const base: Record<FilterValue, number> = { ALL: allFindings.length, CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
    allFindings.forEach(f => { base[f.severity] = (base[f.severity] ?? 0) + 1 })
    return base
  }, [allFindings])

  // ── Render states ──────────────────────────────────────────────────────────

  if (loading) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-4xl mx-auto space-y-5 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
        <div className="h-10 bg-gray-200 dark:bg-gray-800 rounded-xl w-80" />
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-28 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
      </div>
    </div>
  )

  if (error && !data) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <svg className="h-10 w-10 text-red-400 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <p className="text-gray-600 dark:text-gray-400 mb-4">{error}</p>
        <Link href={`/clients/${clientId}`} className="text-violet-600 hover:underline text-sm">
          ← Volver
        </Link>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href={`/clients/${clientId}`}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
              </svg>
            </Link>
            <div>
              <h1 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <svg className="h-4 w-4 text-violet-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
                Hallazgos · {(profile?.client_name ?? clientId).replace(/_/g, ' ')}
              </h1>
              <p className="text-xs text-gray-400">
                {allFindings.length} hallazgo{allFindings.length !== 1 ? 's' : ''} en total
                {profile?.industry_inferred && (
                  <> · <span className="font-medium">{profile.industry_inferred}</span></>
                )}
              </p>
            </div>
          </div>

          <button
            onClick={fetchFindings}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 rounded-lg transition-all"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Actualizar
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-8">

        {/* Toast notification */}
        {toastMsg && (
          <div className="flex items-center gap-2 px-4 py-3 bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 rounded-xl text-emerald-700 dark:text-emerald-300 text-sm">
            <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {toastMsg}
          </div>
        )}

        {/* Error banner (non-fatal) */}
        {error && data && (
          <div className="flex items-center gap-2 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-400 text-sm">
            <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            {error}
          </div>
        )}

        {/* Summary bar */}
        <SummaryBar findings={allFindings} />

        {/* Severity filter tabs */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
            Filtrar por severidad
          </h2>
          <SeverityTabs filter={filter} onChange={setFilter} counts={counts} />
        </div>

        {/* Findings list */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
            Hallazgos
            <span className="text-xs font-bold text-gray-500 normal-case">
              ({filteredFindings.length})
            </span>
          </h2>

          {filteredFindings.length === 0 ? (
            <EmptyState severity={filter} />
          ) : (
            <div className="space-y-3">
              {filteredFindings.map(finding => (
                <FindingCard
                  key={finding.id}
                  finding={finding}
                  clientId={clientId}
                  onMarkFalsePositive={handleMarkFalsePositive}
                  marking={markingId === finding.id}
                />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
