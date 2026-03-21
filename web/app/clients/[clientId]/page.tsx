'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import {
  ArrowLeft, RefreshCw, TrendingUp, AlertOctagon, PlayCircle,
  History, Bell, BarChart2, ShieldAlert, CheckCircle2
} from 'lucide-react'
import Link from 'next/link'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface ClientProfileData {
  client_name: string
  run_count: number
  last_run_date: string | null
  industry_inferred: string | null
  currency_detected: string | null
  focus_tables: string[]
  known_findings: Record<string, any>
  resolved_findings: Record<string, any>
  baseline_history: Record<string, any[]>
  run_history: Array<{
    run_date: string
    period: string
    success: boolean
    findings_count: number
    new: number
    resolved: number
    dq_score?: number
  }>
  refinement: {
    focus_areas?: string[]
    query_hints?: string[]
  } | null
}

interface DQHistory {
  dq_history: Array<{ run_date: string; score: number }>
  avg_score: number | null
  trend: string | null
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  accent?: 'violet' | 'emerald' | 'amber' | 'red'
}) {
  const accentMap = {
    violet: 'bg-violet-50 dark:bg-violet-900/30 text-violet-500',
    emerald: 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-500',
    amber: 'bg-amber-50 dark:bg-amber-900/30 text-amber-500',
    red: 'bg-red-50 dark:bg-red-900/30 text-red-500',
  }
  const iconClass = accentMap[accent ?? 'violet']
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-xl ${iconClass}`}>
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <p className="text-xs text-gray-400 mb-1">{label}</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
          {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
        </div>
      </div>
    </div>
  )
}

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    critical: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    high: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400',
    medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400',
    low: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full uppercase tracking-wide ${map[severity] ?? map.low}`}>
      {severity}
    </span>
  )
}

function FindingCard({ id, finding, idx }: { id: string; finding: any; idx: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: idx * 0.06 }}
      className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-4 shadow-sm flex flex-col gap-2"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-semibold text-gray-800 dark:text-gray-100 leading-snug line-clamp-2">
          {finding.title ?? id}
        </p>
        <SeverityBadge severity={finding.severity ?? 'low'} />
      </div>
      {finding.description && (
        <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">{finding.description}</p>
      )}
      {finding.affected_table && (
        <p className="text-xs font-mono text-violet-600 dark:text-violet-400 truncate">{finding.affected_table}</p>
      )}
      {finding.first_seen && (
        <p className="text-xs text-gray-400 mt-auto">
          Detectado: {new Date(finding.first_seen).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' })}
        </p>
      )}
    </motion.div>
  )
}

function DQSparkline({ dqHistory }: { dqHistory: DQHistory }) {
  const { dq_history, avg_score, trend } = dqHistory
  if (!dq_history.length) return null

  const strokeColor =
    avg_score !== null && avg_score >= 90 ? '#34d399' :
    avg_score !== null && avg_score >= 75 ? '#fbbf24' : '#fb923c'

  const ringClass =
    avg_score !== null && avg_score >= 90
      ? 'border-emerald-400 text-emerald-600 dark:text-emerald-400'
      : avg_score !== null && avg_score >= 75
      ? 'border-amber-400 text-amber-600 dark:text-amber-400'
      : 'border-orange-400 text-orange-600 dark:text-orange-400'

  const trendLabel =
    trend === 'improving' ? '↑ Mejorando' :
    trend === 'declining' ? '↓ Bajando' :
    trend === 'stable' ? '→ Estable' : '—'

  const trendClass =
    trend === 'improving' ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400' :
    trend === 'declining' ? 'bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-400' :
    'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm flex items-center gap-6">
      {/* Average ring */}
      <div className="flex-shrink-0 flex flex-col items-center gap-1">
        <div className={`w-14 h-14 rounded-full flex items-center justify-center border-4 ${ringClass}`}>
          <span className="text-sm font-bold">{avg_score ?? '—'}</span>
        </div>
        <span className="text-xs text-gray-400">Promedio</span>
      </div>

      {/* Sparkline */}
      <div className="flex-1 min-w-0">
        <svg
          viewBox={`0 0 ${dq_history.length * 24} 40`}
          className="w-full h-10"
          preserveAspectRatio="none"
        >
          {dq_history.length > 1 && (
            <polyline
              points={dq_history.map((d, i) => `${i * 24 + 12},${40 - (d.score / 100) * 36}`).join(' ')}
              fill="none"
              stroke={strokeColor}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          {dq_history.map((d, i) => (
            <circle
              key={i}
              cx={i * 24 + 12}
              cy={40 - (d.score / 100) * 36}
              r="3"
              fill={d.score >= 90 ? '#34d399' : d.score >= 75 ? '#fbbf24' : '#fb923c'}
            >
              <title>{`${d.run_date?.slice(0, 10)}: ${d.score}`}</title>
            </circle>
          ))}
        </svg>
      </div>

      {/* Trend pill + count */}
      <div className="flex-shrink-0 flex flex-col items-center gap-1">
        <span className={`text-sm font-semibold px-3 py-1 rounded-full ${trendClass}`}>
          {trendLabel}
        </span>
        <span className="text-xs text-gray-400">{dq_history.length} runs</span>
      </div>
    </div>
  )
}

function RunRow({ run, i }: { run: ClientProfileData['run_history'][0]; i: number }) {
  const date = new Date(run.run_date).toLocaleDateString('es', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  const scoreColor =
    run.dq_score === undefined || run.dq_score === null ? 'text-gray-400' :
    run.dq_score >= 90 ? 'text-emerald-600 dark:text-emerald-400' :
    run.dq_score >= 75 ? 'text-amber-600 dark:text-amber-400' :
    'text-red-600 dark:text-red-400'

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: i * 0.05 }}
      className="flex items-center gap-4 px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors"
    >
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${run.success ? 'bg-emerald-400' : 'bg-red-400'}`} />
      <span className="text-sm text-gray-500 dark:text-gray-400 font-mono w-28 flex-shrink-0">{run.period}</span>
      <span className="text-sm text-gray-400 flex-1">{date}</span>
      <span className="text-sm font-medium text-gray-800 dark:text-gray-200">{run.findings_count} hallazgos</span>
      {run.new > 0 && (
        <span className="text-xs text-red-500 bg-red-50 dark:bg-red-900/30 px-2 py-0.5 rounded-full">
          +{run.new} nuevo{run.new > 1 ? 's' : ''}
        </span>
      )}
      {run.resolved > 0 && (
        <span className="text-xs text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 px-2 py-0.5 rounded-full">
          -{run.resolved} resuelto{run.resolved > 1 ? 's' : ''}
        </span>
      )}
      {run.dq_score !== undefined && run.dq_score !== null && (
        <span className={`text-xs font-semibold hidden sm:block ${scoreColor}`}>{run.dq_score}</span>
      )}
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Tab navigation (shared pattern from history page)
// ---------------------------------------------------------------------------

function TabNav({ clientId, pathname }: { clientId: string; pathname: string }) {
  const tabs = [
    { label: 'Resumen',       href: `/clients/${clientId}` },
    { label: 'Historial',     href: `/clients/${clientId}/history` },
    { label: 'Hallazgos',     href: `/clients/${clientId}/findings` },
    { label: 'Alertas',       href: `/clients/${clientId}/alerts` },
    { label: 'Costos',        href: `/clients/${clientId}/costs` },
    { label: 'KPIs',          href: `/clients/${clientId}/kpis` },
    { label: 'Segmentación',  href: `/clients/${clientId}/segmentation` },
    { label: 'Configuración', href: `/clients/${clientId}/settings` },
  ]
  return (
    <nav className="flex gap-1 -mb-px overflow-x-auto">
      {tabs.map(tab => {
        const isActive = pathname === tab.href
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              isActive
                ? 'border-violet-500 text-violet-600 dark:text-violet-400'
                : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:border-gray-300 dark:hover:border-gray-600'
            }`}
          >
            {tab.label}
          </Link>
        )
      })}
    </nav>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ClientOverviewPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  const [profile, setProfile] = useState<ClientProfileData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dqHistory, setDqHistory] = useState<DQHistory>({ dq_history: [], avg_score: null, trend: null })

  const fetchProfile = () => {
    setLoading(true)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Error cargando perfil'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchProfile() }, [clientId])

  useEffect(() => {
    fetch(`${API_URL}/api/clients/${clientId}/dq-history`)
      .then(r => r.json())
      .then(setDqHistory)
      .catch(() => {})
  }, [clientId])

  // ----- Loading skeleton -----
  if (loading) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-6xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-64" />
        <div className="grid grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
        <div className="h-16 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
        <div className="grid grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-32 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
        <div className="h-40 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
        <div className="h-40 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
      </div>
    </div>
  )

  // ----- Error state -----
  if (error || !profile) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <p className="text-gray-500 mb-4">{error || 'No hay datos para este cliente'}</p>
        <Link href="/" className="text-violet-600 hover:underline text-sm">← Volver</Link>
      </div>
    </div>
  )

  // Derived data
  const latestDQScore = (() => {
    if (dqHistory.dq_history.length > 0) {
      return dqHistory.dq_history[dqHistory.dq_history.length - 1].score
    }
    const lastRunWithScore = [...profile.run_history].reverse().find(r => r.dq_score !== undefined)
    return lastRunWithScore?.dq_score ?? null
  })()

  const totalFindings = Object.keys(profile.known_findings).length + Object.keys(profile.resolved_findings).length

  const criticalHighFindings = Object.entries(profile.known_findings)
    .filter(([, f]) => f.severity === 'critical' || f.severity === 'high')
    .sort(([, a], [, b]) => {
      const order: Record<string, number> = { critical: 0, high: 1 }
      return (order[a.severity] ?? 2) - (order[b.severity] ?? 2)
    })
    .slice(0, 3)

  const lastThreeRuns = [...profile.run_history].reverse().slice(0, 3)

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* ------------------------------------------------------------------ */}
      {/* Header                                                               */}
      {/* ------------------------------------------------------------------ */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">{profile.client_name}</h1>
              <p className="text-xs text-gray-400">
                {[profile.industry_inferred, profile.currency_detected].filter(Boolean).join(' · ')}
              </p>
            </div>
          </div>
          <button
            onClick={fetchProfile}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 rounded-lg transition-all"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Actualizar
          </button>
        </div>
        <div className="max-w-6xl mx-auto px-6">
          <TabNav clientId={clientId} pathname={pathname} />
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">

        {/* ---------------------------------------------------------------- */}
        {/* Hero — client name + subtitle                                     */}
        {/* ---------------------------------------------------------------- */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col gap-1"
        >
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Bienvenido a {profile.client_name}
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Vista general del estado de inteligencia de negocio para este cliente.
            {profile.last_run_date && (
              <> Último análisis: <span className="font-medium">{new Date(profile.last_run_date).toLocaleDateString('es', { day: 'numeric', month: 'long', year: 'numeric' })}</span>.</>
            )}
          </p>
        </motion.div>

        {/* ---------------------------------------------------------------- */}
        {/* Quick action buttons                                              */}
        {/* ---------------------------------------------------------------- */}
        <div className="flex flex-wrap gap-3">
          <Link
            href="/new-analysis"
            className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
          >
            <PlayCircle className="h-4 w-4" />
            Nuevo análisis
          </Link>
          <Link
            href={`/clients/${clientId}/history`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 text-sm font-semibold rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors"
          >
            <History className="h-4 w-4" />
            Ver historial
          </Link>
          <Link
            href={`/clients/${clientId}/alerts`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 text-sm font-semibold rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm transition-colors"
          >
            <Bell className="h-4 w-4" />
            Ver alertas
          </Link>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Stat cards: DQ score / total findings / total runs                */}
        {/* ---------------------------------------------------------------- */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard
            icon={BarChart2}
            label="Último Score DQ"
            value={latestDQScore !== null ? latestDQScore : '—'}
            sub={latestDQScore !== null
              ? latestDQScore >= 90 ? 'Excelente calidad'
              : latestDQScore >= 75 ? 'Calidad aceptable'
              : 'Requiere atención'
              : 'Sin datos aún'}
            accent={
              latestDQScore === null ? 'violet' :
              latestDQScore >= 90 ? 'emerald' :
              latestDQScore >= 75 ? 'amber' : 'red'
            }
          />
          <StatCard
            icon={AlertOctagon}
            label="Total Hallazgos"
            value={totalFindings}
            sub={`${Object.keys(profile.known_findings).length} activos · ${Object.keys(profile.resolved_findings).length} resueltos`}
            accent="amber"
          />
          <StatCard
            icon={TrendingUp}
            label="Total Runs"
            value={profile.run_count}
            sub={profile.last_run_date
              ? `Último: ${new Date(profile.last_run_date).toLocaleDateString('es', { day: 'numeric', month: 'short' })}`
              : 'Sin runs aún'}
            accent="violet"
          />
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* DQ history sparkline                                              */}
        {/* ---------------------------------------------------------------- */}
        {dqHistory.dq_history.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Tendencia de Calidad de Datos
            </h3>
            <DQSparkline dqHistory={dqHistory} />
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* 3 most recent critical/high findings                              */}
        {/* ---------------------------------------------------------------- */}
        {criticalHighFindings.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                <ShieldAlert className="h-3.5 w-3.5 text-red-400" />
                Hallazgos Críticos / Altos
              </h3>
              <Link
                href={`/clients/${clientId}/findings`}
                className="text-xs text-violet-600 hover:underline"
              >
                Ver todos →
              </Link>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {criticalHighFindings.map(([id, finding], idx) => (
                <FindingCard key={id} id={id} finding={finding} idx={idx} />
              ))}
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Last 3 runs                                                       */}
        {/* ---------------------------------------------------------------- */}
        {lastThreeRuns.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                Runs Recientes
              </h3>
              <Link
                href={`/clients/${clientId}/history`}
                className="text-xs text-violet-600 hover:underline"
              >
                Ver historial completo →
              </Link>
            </div>
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
              {/* Column headers */}
              <div className="flex items-center gap-4 px-5 py-2 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
                <span className="w-2 flex-shrink-0" />
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest w-28 flex-shrink-0">Período</span>
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex-1">Fecha</span>
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest">Hallazgos</span>
                <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest hidden sm:block">Cal. Datos</span>
              </div>
              <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
                {lastThreeRuns.map((run, i) => (
                  <RunRow key={i} run={run} i={i} />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Empty state when there is no data yet                             */}
        {/* ---------------------------------------------------------------- */}
        {profile.run_count === 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="bg-white dark:bg-gray-900 rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 p-10 flex flex-col items-center gap-4 text-center"
          >
            <div className="p-4 rounded-2xl bg-violet-50 dark:bg-violet-900/20">
              <PlayCircle className="h-8 w-8 text-violet-400" />
            </div>
            <div>
              <p className="font-semibold text-gray-800 dark:text-gray-100 mb-1">Sin análisis todavía</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Lanza el primer análisis para empezar a ver datos de inteligencia de negocio para {profile.client_name}.
              </p>
            </div>
            <Link
              href="/new-analysis"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
            >
              <PlayCircle className="h-4 w-4" />
              Nuevo análisis
            </Link>
          </motion.div>
        )}

      </main>
    </div>
  )
}
