'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, usePathname } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, RefreshCw, FileDown, ShieldCheck } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

type JobStatus = 'completed' | 'failed' | 'running' | 'pending'

interface Job {
  id: string
  client_name: string
  period: string
  status: JobStatus
  created_at: string
  started_at: string | null
  completed_at: string | null
}

interface JobsResponse {
  jobs: Job[]
  total: number
  page: number
  page_size: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
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

// ── Status Badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: JobStatus }) {
  switch (status) {
    case 'completed':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          Completado
        </span>
      )
    case 'failed':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400">
          <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
          Fallido
        </span>
      )
    case 'running':
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          En curso
        </span>
      )
    case 'pending':
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
          <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
          Pendiente
        </span>
      )
  }
}

// ── Loading Skeleton ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8 animate-pulse">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
        <div className="h-12 bg-gray-200 dark:bg-gray-800 rounded-xl w-64" />
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-14 bg-gray-200 dark:bg-gray-800 rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Tab Nav ───────────────────────────────────────────────────────────────────

function TabNav({ clientId, pathname }: { clientId: string; pathname: string }) {
  const tabs = [
    { label: 'Resumen',       href: `/clients/${clientId}` },
    { label: 'Historial',     href: `/clients/${clientId}/history` },
    { label: 'Hallazgos',     href: `/clients/${clientId}/findings` },
    { label: 'Reportes',      href: `/clients/${clientId}/reports` },
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

// ── Page ──────────────────────────────────────────────────────────────────────

const PAGE_SIZE = 20

export default function ClientReportsPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  const [data, setData] = useState<JobsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)

  const fetchJobs = useCallback(
    (pageNum: number, append = false) => {
      if (!append) setLoading(true)
      else setLoadingMore(true)

      const url = `${API_URL}/api/jobs?client_name=${encodeURIComponent(clientId)}&page=${pageNum}&page_size=${PAGE_SIZE}`
      fetch(url)
        .then(r => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.json() as Promise<JobsResponse>
        })
        .then(d => {
          if (append) {
            setData(prev =>
              prev
                ? { ...d, jobs: [...prev.jobs, ...d.jobs] }
                : d
            )
          } else {
            setData(d)
          }
        })
        .catch(err => setError(err.message || 'Error cargando reportes'))
        .finally(() => {
          setLoading(false)
          setLoadingMore(false)
        })
    },
    [clientId]
  )

  useEffect(() => {
    fetchJobs(1)
  }, [fetchJobs])

  const handleLoadMore = () => {
    const nextPage = page + 1
    setPage(nextPage)
    fetchJobs(nextPage, true)
  }

  const handleRefresh = () => {
    setPage(1)
    fetchJobs(1)
  }

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

  const jobs = data?.jobs ?? []
  const total = data?.total ?? 0
  const hasMore = jobs.length < total

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
              <p className="text-xs text-gray-400">Reportes de análisis</p>
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
        <div className="max-w-5xl mx-auto px-6">
          <TabNav clientId={clientId} pathname={pathname} />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">

        {/* ── Page title + count ── */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Reportes</h2>
            {total > 0 && (
              <p className="text-sm text-gray-400 mt-0.5">{total} análisis en total</p>
            )}
          </div>
          <Link
            href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
          >
            Nuevo análisis
          </Link>
        </div>

        {/* ── Empty state ── */}
        {jobs.length === 0 ? (
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 p-12 flex flex-col items-center gap-4 text-center">
            <div className="p-4 rounded-2xl bg-violet-50 dark:bg-violet-900/20">
              <FileDown className="h-8 w-8 text-violet-400" />
            </div>
            <div>
              <p className="font-semibold text-gray-800 dark:text-gray-100 mb-1">Sin reportes todavía</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Ejecuta el primer análisis para empezar a generar reportes para {clientId}.
              </p>
            </div>
            <Link
              href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
              className="mt-1 inline-flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
            >
              Nuevo análisis
            </Link>
          </div>
        ) : (
          /* ── Reports table ── */
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
            {/* Table header */}
            <div className="grid grid-cols-[1fr_1.5fr_1fr_1.2fr_1fr] gap-4 px-6 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50 text-xs font-semibold text-gray-400 uppercase tracking-widest">
              <span>Job ID</span>
              <span>Período</span>
              <span>Estado</span>
              <span>Iniciado</span>
              <span className="text-right">Acciones</span>
            </div>

            {/* Table rows */}
            <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
              {jobs.map((job) => (
                <div
                  key={job.id}
                  className="grid grid-cols-[1fr_1.5fr_1fr_1.2fr_1fr] gap-4 px-6 py-3.5 items-center hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors"
                >
                  {/* Job ID */}
                  <span className="text-xs font-mono text-gray-500 dark:text-gray-400 truncate">
                    {job.id.slice(0, 8)}
                  </span>

                  {/* Period */}
                  <span className="text-sm text-gray-700 dark:text-gray-300 font-mono truncate">
                    {job.period || '—'}
                  </span>

                  {/* Status badge */}
                  <div>
                    <StatusBadge status={job.status} />
                  </div>

                  {/* Started at */}
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    {formatDate(job.started_at ?? job.created_at)}
                  </span>

                  {/* Actions */}
                  <div className="flex items-center justify-end gap-2">
                    {job.status === 'completed' && (
                      <>
                        <a
                          href={`${API_URL}/api/jobs/${job.id}/export/pdf`}
                          download
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-violet-50 hover:bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:hover:bg-violet-900/50 dark:text-violet-400 transition-colors"
                          title="Descargar PDF"
                        >
                          <FileDown className="h-3.5 w-3.5" />
                          PDF
                        </a>
                        <Link
                          href={`/clients/${clientId}/quality/${job.id}`}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-50 hover:bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:hover:bg-emerald-900/50 dark:text-emerald-400 transition-colors"
                          title="Ver reporte de calidad"
                        >
                          <ShieldCheck className="h-3.5 w-3.5" />
                          Calidad
                        </Link>
                      </>
                    )}
                    {job.status === 'running' && (
                      <Link
                        href={`/results/${job.id}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-blue-50 hover:bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:hover:bg-blue-900/50 dark:text-blue-400 transition-colors"
                      >
                        Ver progreso
                      </Link>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Load more */}
            {hasMore && (
              <div className="px-6 py-4 border-t border-gray-100 dark:border-gray-800 flex justify-center">
                <button
                  onClick={handleLoadMore}
                  disabled={loadingMore}
                  className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-xl transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loadingMore ? (
                    <>
                      <RefreshCw className="h-4 w-4 animate-spin" />
                      Cargando...
                    </>
                  ) : (
                    `Cargar más (${total - jobs.length} restantes)`
                  )}
                </button>
              </div>
            )}
          </div>
        )}

      </main>
    </div>
  )
}
