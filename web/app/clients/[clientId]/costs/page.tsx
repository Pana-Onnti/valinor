'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, DollarSign, TrendingUp, Calendar, BarChart2 } from 'lucide-react'
import Link from 'next/link'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const COST_PER_RUN = 8

interface CostData {
  client_id: string
  total_runs: number
  total_cost_usd: number
  avg_cost_per_run: number
  runs_this_month: number
  cost_this_month: number
  cost_by_month: Array<{
    month: string
    runs: number
    cost: number
  }>
}

interface RunHistoryEntry {
  run_date: string
  period: string
  success: boolean
  findings_count: number
  new: number
  resolved: number
  dq_score?: number
}

interface ClientProfileData {
  client_name: string
  run_count: number
  industry_inferred: string | null
  currency_detected: string | null
  run_history: RunHistoryEntry[]
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent = 'green',
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  accent?: 'green' | 'amber' | 'violet'
}) {
  const accentMap = {
    green: 'bg-green-50 dark:bg-green-900/30 text-green-500',
    amber: 'bg-amber-50 dark:bg-amber-900/30 text-amber-500',
    violet: 'bg-violet-50 dark:bg-violet-900/30 text-violet-500',
  }
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className={`p-2 rounded-xl ${accentMap[accent]}`}>
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

function RunCostBar({ run, maxCost, i }: { run: RunHistoryEntry; maxCost: number; i: number }) {
  const cost = COST_PER_RUN
  const widthPct = maxCost > 0 ? (cost / maxCost) * 100 : 100
  const date = new Date(run.run_date).toLocaleDateString('es', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: i * 0.05 }}
      className="flex items-center gap-4 py-2.5"
    >
      {/* Date + period */}
      <div className="w-36 flex-shrink-0">
        <p className="text-xs font-mono text-gray-400">{run.period}</p>
        <p className="text-xs text-gray-500 dark:text-gray-500">{date}</p>
      </div>

      {/* Bar */}
      <div className="flex-1 h-7 bg-gray-100 dark:bg-gray-800 rounded-lg overflow-hidden relative">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${widthPct}%` }}
          transition={{ duration: 0.5, delay: i * 0.05, ease: 'easeOut' }}
          className={`h-full rounded-lg ${run.success ? 'bg-green-400 dark:bg-green-500' : 'bg-red-400 dark:bg-red-500'}`}
        />
        <span className="absolute inset-0 flex items-center px-2.5 text-xs font-semibold text-gray-900 dark:text-white mix-blend-difference pointer-events-none">
          ${cost.toFixed(2)}
        </span>
      </div>

      {/* Status badge */}
      <div className="w-24 flex-shrink-0 text-right">
        {run.success ? (
          <span className="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/30 px-2 py-0.5 rounded-full">
            Exitoso
          </span>
        ) : (
          <span className="text-xs text-red-500 bg-red-50 dark:bg-red-900/30 px-2 py-0.5 rounded-full">
            Fallido
          </span>
        )}
      </div>
    </motion.div>
  )
}

export default function ClientCostsPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  const [costs, setCosts] = useState<CostData | null>(null)
  const [profile, setProfile] = useState<ClientProfileData | null>(null)
  const [loadingCosts, setLoadingCosts] = useState(true)
  const [loadingProfile, setLoadingProfile] = useState(true)
  const [errorCosts, setErrorCosts] = useState<string | null>(null)
  const [errorProfile, setErrorProfile] = useState<string | null>(null)

  const fetchCosts = () => {
    setLoadingCosts(true)
    setErrorCosts(null)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/costs`)
      .then(res => setCosts(res.data))
      .catch(err => {
        // If endpoint not yet implemented, derive costs from profile
        setErrorCosts(err.response?.data?.detail || 'endpoint_missing')
      })
      .finally(() => setLoadingCosts(false))
  }

  const fetchProfile = () => {
    setLoadingProfile(true)
    setErrorProfile(null)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setErrorProfile(err.response?.data?.detail || 'Error cargando perfil'))
      .finally(() => setLoadingProfile(false))
  }

  const handleRefresh = () => {
    fetchCosts()
    fetchProfile()
  }

  useEffect(() => {
    fetchCosts()
    fetchProfile()
  }, [clientId])

  // Derive cost summary from profile when the /costs endpoint is unavailable
  const derivedCosts: CostData | null =
    costs ??
    (profile
      ? (() => {
          const runs = profile.run_history
          const now = new Date()
          const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
          const runsThisMonth = runs.filter(r => r.run_date.startsWith(currentMonth))

          // Group by month
          const byMonth: Record<string, { runs: number; cost: number }> = {}
          runs.forEach(r => {
            const m = r.run_date.slice(0, 7)
            if (!byMonth[m]) byMonth[m] = { runs: 0, cost: 0 }
            byMonth[m].runs += 1
            byMonth[m].cost += COST_PER_RUN
          })

          return {
            client_id: clientId,
            total_runs: profile.run_count,
            total_cost_usd: profile.run_count * COST_PER_RUN,
            avg_cost_per_run: COST_PER_RUN,
            runs_this_month: runsThisMonth.length,
            cost_this_month: runsThisMonth.length * COST_PER_RUN,
            cost_by_month: Object.entries(byMonth)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([month, v]) => ({ month, ...v })),
          }
        })()
      : null)

  const loading = loadingCosts && loadingProfile
  const isError = !loading && errorProfile && !profile

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
        <div className="max-w-6xl mx-auto space-y-6 animate-pulse">
          <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
          <div className="grid grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
            ))}
          </div>
          <div className="h-64 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-500 mb-4">{errorProfile || 'No hay datos para este cliente'}</p>
          <Link href="/" className="text-violet-600 hover:underline text-sm">
            ← Volver
          </Link>
        </div>
      </div>
    )
  }

  const clientName = profile?.client_name ?? clientId
  const industry = profile?.industry_inferred
  const currency = profile?.currency_detected
  const recentRuns = [...(profile?.run_history ?? [])].reverse().slice(0, 10)

  const tabs = [
    { label: 'Historial', href: `/clients/${clientId}/history` },
    { label: 'Hallazgos', href: `/clients/${clientId}/findings` },
    { label: 'Alertas', href: `/clients/${clientId}/alerts` },
    { label: 'Costos', href: `/clients/${clientId}/costs` },
  ]

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
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
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">{clientName}</h1>
              <p className="text-xs text-gray-400">
                {[industry, currency].filter(Boolean).join(' · ')}
              </p>
            </div>
          </div>
          <button
            onClick={handleRefresh}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 rounded-lg transition-all"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Actualizar
          </button>
        </div>

        {/* Tab navigation */}
        <div className="max-w-6xl mx-auto px-6">
          <nav className="flex gap-1 -mb-px">
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
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">

        {/* Summary cards */}
        {derivedCosts && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              icon={BarChart2}
              label="Total Runs"
              value={derivedCosts.total_runs}
              sub="desde el inicio"
              accent="violet"
            />
            <StatCard
              icon={DollarSign}
              label="Costo Total"
              value={`$${derivedCosts.total_cost_usd.toFixed(2)}`}
              sub="USD estimado"
              accent="green"
            />
            <StatCard
              icon={TrendingUp}
              label="Costo Promedio"
              value={`$${derivedCosts.avg_cost_per_run.toFixed(2)}`}
              sub="por análisis"
              accent="amber"
            />
            <StatCard
              icon={Calendar}
              label="Este Mes"
              value={`$${derivedCosts.cost_this_month.toFixed(2)}`}
              sub={`${derivedCosts.runs_this_month} run${derivedCosts.runs_this_month !== 1 ? 's' : ''}`}
              accent="green"
            />
          </div>
        )}

        {/* Monthly cost summary */}
        {derivedCosts && derivedCosts.cost_by_month.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Costo por Mes
            </h2>
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm">
              <div className="space-y-3">
                {(() => {
                  const maxMonthCost = Math.max(...derivedCosts.cost_by_month.map(m => m.cost), 1)
                  return derivedCosts.cost_by_month
                    .slice()
                    .reverse()
                    .map((entry, i) => {
                      const pct = (entry.cost / maxMonthCost) * 100
                      const [year, month] = entry.month.split('-')
                      const label = new Date(Number(year), Number(month) - 1, 1).toLocaleDateString(
                        'es',
                        { month: 'long', year: 'numeric' }
                      )
                      return (
                        <motion.div
                          key={entry.month}
                          initial={{ opacity: 0, x: -8 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.06 }}
                          className="flex items-center gap-4"
                        >
                          <span className="w-32 text-xs text-gray-500 dark:text-gray-400 capitalize flex-shrink-0">
                            {label}
                          </span>
                          <div className="flex-1 h-6 bg-gray-100 dark:bg-gray-800 rounded-lg overflow-hidden relative">
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${pct}%` }}
                              transition={{ duration: 0.5, delay: i * 0.06, ease: 'easeOut' }}
                              className="h-full rounded-lg bg-green-400 dark:bg-green-500"
                            />
                          </div>
                          <div className="w-28 flex-shrink-0 text-right space-y-0.5">
                            <p className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                              ${entry.cost.toFixed(2)}
                            </p>
                            <p className="text-xs text-gray-400">
                              {entry.runs} run{entry.runs !== 1 ? 's' : ''}
                            </p>
                          </div>
                        </motion.div>
                      )
                    })
                })()}
              </div>
            </div>
          </div>
        )}

        {/* Last 10 runs bar chart */}
        {recentRuns.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Últimos 10 Runs — Costo por Ejecución
            </h2>
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm">
              {/* Column headers */}
              <div className="flex items-center gap-4 pb-3 border-b border-gray-100 dark:border-gray-800 mb-2">
                <span className="w-36 flex-shrink-0 text-xs font-semibold text-gray-400 uppercase tracking-widest">
                  Período / Fecha
                </span>
                <span className="flex-1 text-xs font-semibold text-gray-400 uppercase tracking-widest">
                  Costo (USD)
                </span>
                <span className="w-24 flex-shrink-0 text-xs font-semibold text-gray-400 uppercase tracking-widest text-right">
                  Estado
                </span>
              </div>

              <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
                {recentRuns.map((run, i) => (
                  <RunCostBar key={i} run={run} maxCost={COST_PER_RUN} i={i} />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Note about estimation */}
        <div className="flex items-start gap-2 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800/50 rounded-xl">
          <span className="text-amber-500 text-sm mt-0.5">*</span>
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Los costos son estimados basados en ~${COST_PER_RUN} USD por análisis (Claude API + infraestructura).
            El costo real puede variar según la complejidad de la base de datos y número de agentes utilizados.
          </p>
        </div>

      </main>
    </div>
  )
}
