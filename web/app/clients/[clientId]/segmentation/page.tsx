'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, Trophy, TrendingUp, Clock, AlertTriangle } from 'lucide-react'
import Link from 'next/link'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Segment {
  name: string
  count: number
  pct_of_total: number
  revenue_share: number
  avg_revenue: number
}

interface SegmentationData {
  client_name: string
  total_customers: number
  currency: string | null
  segments: Segment[]
}

const SEGMENT_META: Record<string, { icon: React.ElementType; color: string; bg: string; border: string; bar: string }> = {
  Champions: {
    icon: Trophy,
    color: 'text-amber-600 dark:text-amber-400',
    bg: 'bg-amber-50 dark:bg-amber-900/30',
    border: 'border-amber-200 dark:border-amber-800',
    bar: 'bg-violet-500',
  },
  Growth: {
    icon: TrendingUp,
    color: 'text-emerald-600 dark:text-emerald-400',
    bg: 'bg-emerald-50 dark:bg-emerald-900/30',
    border: 'border-emerald-200 dark:border-emerald-800',
    bar: 'bg-violet-500',
  },
  Maintenance: {
    icon: Clock,
    color: 'text-blue-600 dark:text-blue-400',
    bg: 'bg-blue-50 dark:bg-blue-900/30',
    border: 'border-blue-200 dark:border-blue-800',
    bar: 'bg-violet-500',
  },
  'At-Risk': {
    icon: AlertTriangle,
    color: 'text-red-600 dark:text-red-400',
    bg: 'bg-red-50 dark:bg-red-900/30',
    border: 'border-red-200 dark:border-red-800',
    bar: 'bg-violet-500',
  },
}

const STACKED_COLORS = [
  'bg-violet-600',
  'bg-violet-400',
  'bg-violet-300',
  'bg-violet-200',
]

function formatCurrency(value: number, currency: string | null) {
  const symbol = currency ?? '$'
  if (value >= 1_000_000) return `${symbol}${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${symbol}${(value / 1_000).toFixed(0)}K`
  return `${symbol}${value.toFixed(0)}`
}

function SegmentCard({
  segment,
  i,
  currency,
}: {
  segment: Segment
  i: number
  currency: string | null
}) {
  const meta = SEGMENT_META[segment.name] ?? SEGMENT_META['Maintenance']
  const Icon = meta.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: i * 0.07 }}
      className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm"
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-xl ${meta.bg}`}>
            <Icon className={`h-4 w-4 ${meta.color}`} />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900 dark:text-white">{segment.name}</p>
            <p className="text-xs text-gray-400 mt-0.5">
              {segment.count.toLocaleString('es')} clientes
            </p>
          </div>
        </div>
        <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${meta.bg} ${meta.color} ${meta.border}`}>
          {segment.pct_of_total.toFixed(1)}%
        </span>
      </div>

      {/* Revenue share bar */}
      <div className="mb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-400">Revenue share</span>
          <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">
            {segment.revenue_share.toFixed(1)}%
          </span>
        </div>
        <div className="h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${segment.revenue_share}%` }}
            transition={{ delay: i * 0.07 + 0.2, duration: 0.6, ease: 'easeOut' }}
            className="h-full bg-violet-500 rounded-full"
          />
        </div>
      </div>

      {/* Avg revenue */}
      <div className="flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-800">
        <span className="text-xs text-gray-400">Revenue promedio</span>
        <span className="text-sm font-bold text-gray-900 dark:text-white">
          {formatCurrency(segment.avg_revenue, currency)}
        </span>
      </div>
    </motion.div>
  )
}

export default function ClientSegmentationPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()
  const [data, setData] = useState<SegmentationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchSegmentation = () => {
    setLoading(true)
    setError(null)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/segmentation`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Error cargando segmentación'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchSegmentation() }, [clientId])

  const tabs = [
    { label: 'Historial',      href: `/clients/${clientId}/history` },
    { label: 'Hallazgos',      href: `/clients/${clientId}/findings` },
    { label: 'Alertas',        href: `/clients/${clientId}/alerts` },
    { label: 'Costos',         href: `/clients/${clientId}/costs` },
    { label: 'Segmentación',   href: `/clients/${clientId}/segmentation` },
  ]

  const clientName = data?.client_name ?? clientId

  if (loading) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-6xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-40 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
        <div className="h-20 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
      </div>
    </div>
  )

  if (error || !data) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <p className="text-gray-500 mb-4">{error || 'No hay datos de segmentación para este cliente'}</p>
        <Link href={`/clients/${clientId}/history`} className="text-violet-600 hover:underline text-sm">
          ← Volver al historial
        </Link>
      </div>
    </div>
  )

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
                {data.total_customers.toLocaleString('es')} clientes totales
                {data.currency ? ` · ${data.currency}` : ''}
              </p>
            </div>
          </div>
          <button
            onClick={fetchSegmentation}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 rounded-lg transition-all"
          >
            <RefreshCw className="h-3.5 w-3.5" />Actualizar
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
        {/* Section title */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1">
            Segmentación de Clientes
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Distribución por segmento de valor · {data.total_customers.toLocaleString('es')} clientes
          </p>
        </div>

        {/* Segment cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {data.segments.map((segment, i) => (
            <SegmentCard
              key={segment.name}
              segment={segment}
              i={i}
              currency={data.currency}
            />
          ))}
        </div>

        {/* Stacked bar — Distribución de Revenue */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">
            Distribución de Revenue
          </h2>
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-6 shadow-sm">
            {/* Stacked bar */}
            <div className="flex h-10 rounded-xl overflow-hidden gap-0.5 mb-5">
              {data.segments.map((segment, i) => (
                <motion.div
                  key={segment.name}
                  initial={{ flex: 0 }}
                  animate={{ flex: segment.revenue_share }}
                  transition={{ delay: i * 0.08 + 0.1, duration: 0.7, ease: 'easeOut' }}
                  className={`${STACKED_COLORS[i % STACKED_COLORS.length]} first:rounded-l-xl last:rounded-r-xl`}
                  title={`${segment.name}: ${segment.revenue_share.toFixed(1)}%`}
                />
              ))}
            </div>

            {/* Legend */}
            <div className="flex flex-wrap gap-x-6 gap-y-3">
              {data.segments.map((segment, i) => {
                const meta = SEGMENT_META[segment.name] ?? SEGMENT_META['Maintenance']
                const Icon = meta.icon
                return (
                  <div key={segment.name} className="flex items-center gap-2">
                    <span className={`w-3 h-3 rounded-sm flex-shrink-0 ${STACKED_COLORS[i % STACKED_COLORS.length]}`} />
                    <Icon className={`h-3.5 w-3.5 ${meta.color}`} />
                    <span className="text-sm text-gray-600 dark:text-gray-300 font-medium">
                      {segment.name}
                    </span>
                    <span className="text-sm text-gray-400">
                      {segment.revenue_share.toFixed(1)}%
                    </span>
                  </div>
                )
              })}
            </div>

            {/* Summary row */}
            <div className="mt-5 pt-5 border-t border-gray-100 dark:border-gray-800 grid grid-cols-2 sm:grid-cols-4 gap-4">
              {data.segments.map(segment => (
                <div key={segment.name} className="text-center">
                  <p className="text-xs text-gray-400 mb-1">{segment.name}</p>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">
                    {formatCurrency(segment.avg_revenue, data.currency)}
                  </p>
                  <p className="text-xs text-gray-400">avg / cliente</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
