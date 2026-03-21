'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, TrendingUp, TrendingDown, Minus, BarChart2 } from 'lucide-react'
import Link from 'next/link'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface KPIDataPoint {
  period: string
  value: string
  numeric_value: number | null
  run_date: string
}

interface KPIsResponse {
  client_name: string
  kpis: Record<string, KPIDataPoint[]>
  kpi_count: number
  earliest_period: string | null
  latest_period: string | null
}

function TrendIndicator({ points }: { points: KPIDataPoint[] }) {
  const numeric = points.filter(p => p.numeric_value !== null)
  if (numeric.length < 2) {
    return <Minus className="h-4 w-4 text-gray-400" />
  }
  const last = numeric[numeric.length - 1].numeric_value as number
  const prev = numeric[numeric.length - 2].numeric_value as number
  if (last > prev) {
    return <TrendingUp className="h-4 w-4 text-emerald-400" />
  } else if (last < prev) {
    return <TrendingDown className="h-4 w-4 text-red-400" />
  }
  return <Minus className="h-4 w-4 text-gray-400" />
}

function MiniBarChart({ points }: { points: KPIDataPoint[] }) {
  const numeric = points.filter(p => p.numeric_value !== null)
  if (numeric.length === 0) {
    return (
      <div className="flex items-end gap-0.5 h-12">
        <span className="text-xs text-gray-500">Sin datos numéricos</span>
      </div>
    )
  }

  const values = numeric.map(p => p.numeric_value as number)
  const max = Math.max(...values)
  const min = Math.min(...values)
  const range = max - min

  return (
    <div className="flex items-end gap-0.5 h-12 overflow-x-auto pb-1">
      {numeric.map((point, i) => {
        const heightPct = range === 0
          ? 50
          : ((point.numeric_value as number - min) / range) * 80 + 20
        const isLast = i === numeric.length - 1
        return (
          <div key={i} className="flex flex-col items-center flex-shrink-0" style={{ minWidth: 18 }}>
            <div
              title={`${point.period}: ${point.value}`}
              className={`w-3 rounded-t transition-all ${
                isLast
                  ? 'bg-violet-500'
                  : 'bg-violet-800/60 hover:bg-violet-600'
              }`}
              style={{ height: `${heightPct}%` }}
            />
            <span
              className="text-gray-500 mt-1 leading-none"
              style={{
                fontSize: '8px',
                transform: 'rotate(45deg)',
                transformOrigin: 'left center',
                display: 'block',
                width: 18,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'clip',
              }}
            >
              {point.period}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function KPICard({ label, points, index }: { label: string; points: KPIDataPoint[]; index: number }) {
  const latest = points[points.length - 1]
  const numeric = points.filter(p => p.numeric_value !== null)
  const latestNumeric = numeric.length > 0 ? numeric[numeric.length - 1] : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm flex flex-col gap-3"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide leading-snug line-clamp-2 flex-1">
          {label}
        </p>
        <TrendIndicator points={points} />
      </div>

      {/* Latest value */}
      <div>
        <p className="text-2xl font-bold text-white leading-none truncate">
          {latest ? latest.value : '—'}
        </p>
        {latest && (
          <p className="text-xs text-gray-500 mt-1">{latest.period}</p>
        )}
      </div>

      {/* Mini bar chart */}
      <div className="pt-1" style={{ paddingBottom: 18 }}>
        <MiniBarChart points={points} />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-gray-500 border-t border-gray-800 pt-2">
        <span>{points.length} período{points.length !== 1 ? 's' : ''}</span>
        {latestNumeric && (
          <span className="font-mono text-gray-400">{latestNumeric.numeric_value}</span>
        )}
      </div>
    </motion.div>
  )
}

export default function ClientKPIsPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()
  const [data, setData] = useState<KPIsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchKPIs = () => {
    setLoading(true)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/kpis`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Error cargando KPIs'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchKPIs() }, [clientId])

  if (loading) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-6xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-44 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
      </div>
    </div>
  )

  if (error || !data) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <p className="text-gray-500 mb-4">{error || 'No hay datos para este cliente'}</p>
        <Link href="/" className="text-violet-600 hover:underline text-sm">← Volver</Link>
      </div>
    </div>
  )

  const kpiEntries = Object.entries(data.kpis)

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
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">{data.client_name}</h1>
              <p className="text-xs text-gray-400">
                {data.kpi_count} KPI{data.kpi_count !== 1 ? 's' : ''}
                {data.earliest_period && data.latest_period
                  ? ` · ${data.earliest_period} → ${data.latest_period}`
                  : ''}
              </p>
            </div>
          </div>
          <button
            onClick={fetchKPIs}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 rounded-lg transition-all"
          >
            <RefreshCw className="h-3.5 w-3.5" />Actualizar
          </button>
        </div>

        {/* Tab navigation */}
        <div className="max-w-6xl mx-auto px-6">
          <nav className="flex gap-1 -mb-px">
            {[
              { label: 'Historial', href: `/clients/${clientId}/history` },
              { label: 'Hallazgos', href: `/clients/${clientId}/findings` },
              { label: 'Alertas',   href: `/clients/${clientId}/alerts` },
              { label: 'Costos',    href: `/clients/${clientId}/costs` },
              { label: 'KPIs',      href: `/clients/${clientId}/kpis` },
            ].map(tab => {
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
        {/* Summary bar */}
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-violet-900/30">
            <BarChart2 className="h-4 w-4 text-violet-400" />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-200">
              {data.kpi_count} KPI{data.kpi_count !== 1 ? 's' : ''} rastreados
            </p>
            {data.earliest_period && data.latest_period && (
              <p className="text-xs text-gray-500">
                Desde {data.earliest_period} hasta {data.latest_period}
              </p>
            )}
          </div>
        </div>

        {/* KPI grid */}
        {kpiEntries.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {kpiEntries.map(([label, points], i) => (
              <KPICard key={label} label={label} points={points} index={i} />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <BarChart2 className="h-10 w-10 text-gray-700 mb-4" />
            <p className="text-gray-400 text-sm">No hay KPIs registrados para este cliente aún.</p>
            <p className="text-gray-600 text-xs mt-1">
              Los KPIs se extraen automáticamente en cada análisis.
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
