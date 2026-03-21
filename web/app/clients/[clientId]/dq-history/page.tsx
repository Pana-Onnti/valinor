'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

interface DQEntry {
  run_date: string
  score: number
  passed_checks?: number
  total_checks?: number
  gate_decision?: string
}

interface DQHistoryResponse {
  dq_history: DQEntry[]
  avg_score: number | null
  trend: string | null
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreColorClass(score: number): string {
  if (score >= 90) return 'text-emerald-600 font-semibold'
  if (score >= 75) return 'text-amber-600 font-semibold'
  if (score >= 50) return 'text-orange-600 font-semibold'
  return 'text-red-600 font-semibold'
}

function scoreBgClass(score: number): string {
  if (score >= 90) return 'bg-emerald-100 text-emerald-700'
  if (score >= 75) return 'bg-amber-100 text-amber-700'
  if (score >= 50) return 'bg-orange-100 text-orange-700'
  return 'bg-red-100 text-red-700'
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('es-ES', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

// ── Gate Decision Badge ───────────────────────────────────────────────────────

function GateDecisionBadge({ decision }: { decision?: string }) {
  if (!decision) {
    return <span className="text-gray-400 text-xs">—</span>
  }
  const normalized = decision.toLowerCase()
  const cls =
    normalized === 'pass' || normalized === 'approved'
      ? 'bg-emerald-100 text-emerald-700'
      : normalized === 'warn' || normalized === 'warning'
      ? 'bg-amber-100 text-amber-700'
      : normalized === 'fail' || normalized === 'rejected' || normalized === 'abort'
      ? 'bg-red-100 text-red-700'
      : 'bg-gray-100 text-gray-600'

  return (
    <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase ${cls}`}>
      {decision}
    </span>
  )
}

// ── Trend Indicator ───────────────────────────────────────────────────────────

function TrendIndicator({ trend }: { trend: string | null }) {
  if (trend === 'improving') {
    return (
      <div className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-50 border border-emerald-200">
        <span className="text-2xl font-bold text-emerald-600">↑</span>
        <div>
          <p className="text-sm font-semibold text-emerald-700">Mejorando</p>
          <p className="text-xs text-emerald-500">La calidad de datos está en tendencia positiva</p>
        </div>
      </div>
    )
  }
  if (trend === 'declining') {
    return (
      <div className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-red-50 border border-red-200">
        <span className="text-2xl font-bold text-red-600">↓</span>
        <div>
          <p className="text-sm font-semibold text-red-700">Bajando</p>
          <p className="text-xs text-red-500">La calidad de datos está en tendencia negativa</p>
        </div>
      </div>
    )
  }
  if (trend === 'stable') {
    return (
      <div className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gray-50 border border-gray-200">
        <span className="text-2xl font-bold text-gray-500">→</span>
        <div>
          <p className="text-sm font-semibold text-gray-700">Estable</p>
          <p className="text-xs text-gray-500">La calidad de datos se mantiene sin cambios significativos</p>
        </div>
      </div>
    )
  }
  return null
}

// ── Loading Skeleton ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8 animate-pulse">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-56" />
        <div className="h-12 bg-gray-200 dark:bg-gray-800 rounded-xl w-64" />
        <div className="h-64 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
      </div>
    </div>
  )
}

// ── Tab Nav (replicates the pattern used across client pages) ─────────────────

function TabNav({ clientId, pathname }: { clientId: string; pathname: string }) {
  const tabs = [
    { label: 'Resumen',       href: `/clients/${clientId}` },
    { label: 'Historial',     href: `/clients/${clientId}/history` },
    { label: 'Hallazgos',     href: `/clients/${clientId}/findings` },
    { label: 'Alertas',       href: `/clients/${clientId}/alerts` },
    { label: 'Costos',        href: `/clients/${clientId}/costs` },
    { label: 'KPIs',          href: `/clients/${clientId}/kpis` },
    { label: 'Segmentación',  href: `/clients/${clientId}/segmentation` },
    { label: 'Historial DQ',  href: `/clients/${clientId}/dq-history` },
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

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DQHistoryPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  const [data, setData] = useState<DQHistoryResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/dq-history`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: DQHistoryResponse) => setData(d))
      .catch(err => setError(err.message || 'Error cargando historial DQ'))
      .finally(() => setLoading(false))
  }, [clientId])

  if (loading) return <LoadingSkeleton />

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-500 mb-4">{error}</p>
          <Link href={`/clients/${clientId}`} className="text-violet-600 hover:underline text-sm">
            ← Volver al cliente
          </Link>
        </div>
      </div>
    )
  }

  const history = data?.dq_history ?? []
  const avgScore = data?.avg_score ?? null
  const trend = data?.trend ?? null

  // ── Empty state ──
  const isEmpty = history.length === 0

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* ── Sticky header ── */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href={`/clients/${clientId}`}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">{clientId}</h1>
              <p className="text-xs text-gray-400">Historial de Calidad de Datos</p>
            </div>
          </div>
          {avgScore !== null && (
            <span className={`px-3 py-1.5 rounded-full text-sm font-bold ${scoreBgClass(avgScore)}`}>
              Promedio: {avgScore}/100
            </span>
          )}
        </div>
        <div className="max-w-5xl mx-auto px-6">
          <TabNav clientId={clientId} pathname={pathname} />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-8">

        {/* ── Trend indicator at top ── */}
        {trend && !isEmpty && (
          <div>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Tendencia general
            </p>
            <TrendIndicator trend={trend} />
          </div>
        )}

        {/* ── Empty state ── */}
        {isEmpty ? (
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 p-12 flex flex-col items-center gap-4 text-center">
            <div className="p-4 rounded-2xl bg-violet-50 dark:bg-violet-900/20">
              <svg className="h-8 w-8 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                />
              </svg>
            </div>
            <div>
              <p className="font-semibold text-gray-800 dark:text-gray-100 mb-1">Sin historial de DQ todavía</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Ejecuta un análisis para comenzar a registrar puntuaciones de calidad de datos.
              </p>
            </div>
            <Link
              href="/new-analysis"
              className="mt-1 inline-flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
            >
              Nuevo análisis
            </Link>
          </div>
        ) : (
          /* ── DQ History table ── */
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
                {history.length} entrada{history.length !== 1 ? 's' : ''}
              </h2>
            </div>
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
              {/* Table header */}
              <div className="grid grid-cols-4 gap-4 px-6 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50 text-xs font-semibold text-gray-400 uppercase tracking-widest">
                <span>Fecha</span>
                <span className="text-center">Score DQ</span>
                <span className="text-center">Checks superados</span>
                <span className="text-center">Gate</span>
              </div>

              {/* Table rows */}
              <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
                {[...history].reverse().map((entry, idx) => (
                  <div
                    key={idx}
                    className="grid grid-cols-4 gap-4 px-6 py-3.5 items-center hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors"
                  >
                    {/* Date */}
                    <span className="text-sm text-gray-700 dark:text-gray-300 font-mono">
                      {formatDate(entry.run_date)}
                    </span>

                    {/* Score */}
                    <div className="flex justify-center">
                      <span className={`text-sm ${scoreColorClass(entry.score)}`}>
                        {entry.score}
                        <span className="text-xs font-normal text-gray-400">/100</span>
                      </span>
                    </div>

                    {/* Passed checks */}
                    <div className="flex justify-center">
                      {entry.passed_checks !== undefined && entry.total_checks !== undefined ? (
                        <span className="text-sm text-gray-700 dark:text-gray-300">
                          <span className="font-semibold">{entry.passed_checks}</span>
                          <span className="text-gray-400">/{entry.total_checks}</span>
                        </span>
                      ) : (
                        <span className="text-sm text-gray-400">—</span>
                      )}
                    </div>

                    {/* Gate decision */}
                    <div className="flex justify-center">
                      <GateDecisionBadge decision={entry.gate_decision} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
