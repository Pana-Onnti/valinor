'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, TrendingUp, Clock, Target, AlertOctagon } from 'lucide-react'
import Link from 'next/link'
import { KPITrendChart } from '@/components/KPITrendChart'
import { FindingTimeline } from '@/components/FindingTimeline'
import { DeltaPanel } from '@/components/DeltaPanel'

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
  }>
  refinement: {
    focus_areas?: string[]
    query_hints?: string[]
  } | null
}

function StatCard({ icon: Icon, label, value, sub }: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-xl bg-violet-50 dark:bg-violet-900/30">
          <Icon className="h-4 w-4 text-violet-500" />
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

function RunHistoryRow({ run, i }: { run: ClientProfileData['run_history'][0]; i: number }) {
  const date = new Date(run.run_date).toLocaleDateString('es', {
    day: 'numeric', month: 'short', year: 'numeric'
  })
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: i * 0.04 }}
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
    </motion.div>
  )
}

export default function ClientHistoryPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const [profile, setProfile] = useState<ClientProfileData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchProfile = () => {
    setLoading(true)
    axios.get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Error cargando perfil'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchProfile() }, [clientId])

  if (loading) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-6xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
        <div className="h-48 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
        <div className="grid grid-cols-4 gap-3">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-28 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
      </div>
    </div>
  )

  if (error || !profile) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <p className="text-gray-500 mb-4">{error || 'No hay datos para este cliente'}</p>
        <Link href="/" className="text-violet-600 hover:underline text-sm">← Volver</Link>
      </div>
    </div>
  )

  const kpiLabels = Object.keys(profile.baseline_history).slice(0, 8)
  const lastRun = profile.run_history[profile.run_history.length - 1]

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors">
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
            <RefreshCw className="h-3.5 w-3.5" />Actualizar
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard icon={TrendingUp} label="Total Runs" value={profile.run_count} />
          <StatCard icon={AlertOctagon} label="Activos" value={Object.keys(profile.known_findings).length}
            sub="hallazgos abiertos" />
          <StatCard icon={Clock} label="Resueltos" value={Object.keys(profile.resolved_findings).length}
            sub="hallazgos cerrados" />
          <StatCard icon={Target} label="Tablas foco" value={profile.focus_tables.length}
            sub={profile.focus_tables.slice(0, 2).join(', ')} />
        </div>

        {/* Last run delta */}
        {lastRun && (lastRun.new > 0 || lastRun.resolved > 0) && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Último Run · {lastRun.period}
            </h2>
            <DeltaPanel
              runDelta={{ new: [], resolved: [], persists: [], worsened: [], improved: [] }}
              knownFindings={profile.known_findings}
              runCount={profile.run_count}
            />
          </div>
        )}

        {/* KPI trends */}
        {kpiLabels.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">
              Evolución de KPIs
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {kpiLabels.map(label => (
                <KPITrendChart
                  key={label}
                  label={label}
                  dataPoints={profile.baseline_history[label]}
                />
              ))}
            </div>
          </div>
        )}

        {/* Finding timeline */}
        {(Object.keys(profile.known_findings).length > 0 || Object.keys(profile.resolved_findings).length > 0) && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">
              Historial de Hallazgos
            </h2>
            <FindingTimeline
              active={profile.known_findings}
              resolved={profile.resolved_findings}
            />
          </div>
        )}

        {/* Run history table */}
        {profile.run_history.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">
              Historial de Runs
            </h2>
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
              <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
                {[...profile.run_history].reverse().map((run, i) => (
                  <RunHistoryRow key={i} run={run} i={i} />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Focus areas from refinement */}
        {profile.refinement?.focus_areas?.length ? (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Áreas de Foco (Auto-Refinement)
            </h2>
            <div className="flex flex-wrap gap-2">
              {profile.refinement.focus_areas.map(area => (
                <span key={area} className="px-3 py-1.5 bg-violet-50 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 text-sm font-medium rounded-full border border-violet-200 dark:border-violet-800">
                  {area}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </main>
    </div>
  )
}
