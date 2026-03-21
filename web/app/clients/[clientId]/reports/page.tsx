'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, usePathname } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, RefreshCw, FileDown, ShieldCheck, Plus } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const PAGE_SIZE = 20

// ── Types ──────────────────────────────────────────────────────────────────────

type JobStatus = 'completed' | 'failed' | 'running' | 'pending' | 'error'

interface Job {
  job_id: string
  client_name: string
  period: string
  status: JobStatus
  created_at: string
  started_at: string | null
  completed_at?: string | null
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
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id
}

// ── Status Badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: JobStatus }) {
  const config: Record<JobStatus, { label: string; dot: string; pill: string }> = {
    completed: {
      label: 'Completado',
      dot: 'bg-emerald-500',
      pill: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400',
    },
    failed: {
      label: 'Fallido',
      dot: 'bg-red-500',
      pill: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    },
    error: {
      label: 'Error',
      dot: 'bg-red-500',
      pill: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    },
    running: {
      label: 'En curso',
      dot: 'bg-blue-500 animate-pulse',
      pill: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400',
    },
    pending: {
      label: 'Pendiente',
      dot: 'bg-gray-400',
      pill: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    },
  }
  const { label, dot, pill } = config[status] ?? config.pending
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ${pill}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      {label}
    </span>
  )
}

// ── Job Card ──────────────────────────────────────────────────────────────────

function JobCard({ job, clientId }: { job: Job; clientId: string }) {
  const canExport = job.status === 'completed'

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 px-5 py-4 shadow-sm hover:border-violet-100 dark:hover:border-violet-900 transition-colors">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">

        {/* Left: metadata */}
        <div className="flex-1 min-w-0 space-y-2">

          {/* Top row: ID + period + status */}
          <div className="flex items-center gap-2.5 flex-wrap">
            <span
              title={job.job_id}
              className="font-mono text-xs font-semibold text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20 border border-violet-100 dark:border-violet-900 px-2 py-0.5 rounded-lg select-all cursor-pointer"
            >
              #{shortId(job.job_id)}
            </span>

            {job.period && (
              <span className="text-xs font-medium text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-lg font-mono">
                {job.period}
              </span>
            )}

            <StatusBadge status={job.status} />
          </div>

          {/* Started at */}
          <p className="text-xs text-gray-400">
            Iniciado:{' '}
            <span className="text-gray-600 dark:text-gray-300 font-medium">
              {formatDate(job.started_at ?? job.created_at)}
            </span>
          </p>
        </div>

        {/* Right: action buttons */}
        <div className="flex items-center gap-2 flex-shrink-0 flex-wrap">

          {/* Quality report link */}
          <Link
            href={`/api/jobs/${encodeURIComponent(job.job_id)}/quality`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-teal-700 dark:text-teal-400 bg-teal-50 dark:bg-teal-900/20 border border-teal-200 dark:border-teal-800 rounded-xl hover:bg-teal-100 dark:hover:bg-teal-900/40 transition-colors"
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            Calidad
          </Link>

          {/* PDF export */}
          {canExport ? (
            <a
              href={`${API_URL}/api/jobs/${encodeURIComponent(job.job_id)}/export/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              download
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-violet-700 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded-xl hover:bg-violet-100 dark:hover:bg-violet-900/40 transition-colors"
            >
              <FileDown className="h-3.5 w-3.5" />
              PDF
            </a>
          ) : (
            <span
              title="Disponible cuando el análisis complete"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-400 dark:text-gray-600 bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-xl opacity-60 cursor-not-allowed"
            >
              <FileDown className="h-3.5 w-3.5" />
              PDF
            </span>
          )}

          {/* Live progress for running jobs */}
          {job.status === 'running' && (
            <Link
              href={`/results/${encodeURIComponent(job.job_id)}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-700 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors"
            >
              Ver progreso →
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Loading Skeleton ───────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8 animate-pulse">
      <div className="max-w-4xl mx-auto space-y-5">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
        <div className="h-10 bg-gray-200 dark:bg-gray-800 rounded-xl w-full" />
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
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

export default function ClientReportsPage() {
  const params   = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  const [jobs,        setJobs]        = useState<Job[]>([])
  const [total,       setTotal]       = useState(0)
  const [page,        setPage]        = useState(1)
  const [loading,     setLoading]     = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error,       setError]       = useState<string | null>(null)

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
          setJobs(prev => append ? [...prev, ...d.jobs] : d.jobs)
          setTotal(d.total)
          setPage(pageNum)
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

  const handleLoadMore = () => fetchJobs(page + 1, true)
  const handleRefresh  = () => { setPage(1); fetchJobs(1) }

  const hasMore = jobs.length < total

  // ── Loading ───────────────────────────────────────────────────────────────

  if (loading) return <LoadingSkeleton />

  // ── Fatal error ───────────────────────────────────────────────────────────

  if (error && jobs.length === 0) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <svg className="h-10 w-10 text-red-400 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <p className="text-gray-600 dark:text-gray-400 mb-4">{error}</p>
        <button onClick={handleRefresh} className="text-violet-600 hover:underline text-sm">
          Reintentar
        </button>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">

      {/* ── Sticky header ── */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href={`/clients/${clientId}`}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <svg className="h-4 w-4 text-violet-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                Reportes · {clientId.replace(/_/g, ' ')}
              </h1>
              <p className="text-xs text-gray-400">
                {total} análisis en total
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold text-white bg-violet-600 hover:bg-violet-700 rounded-xl shadow-sm transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
              Nuevo análisis
            </Link>
            <button
              onClick={handleRefresh}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 rounded-lg transition-all"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Actualizar
            </button>
          </div>
        </div>

        {/* Tab nav */}
        <div className="max-w-4xl mx-auto px-6">
          <TabNav clientId={clientId} pathname={pathname} />
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-6">

        {/* Non-fatal error banner */}
        {error && jobs.length > 0 && (
          <div className="flex items-center gap-2 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-400 text-sm">
            <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            {error}
          </div>
        )}

        {/* Empty state */}
        {jobs.length === 0 ? (
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 p-16 flex flex-col items-center gap-4 text-center">
            <div className="p-4 rounded-2xl bg-violet-50 dark:bg-violet-900/20">
              <FileDown className="h-8 w-8 text-violet-400" />
            </div>
            <div>
              <p className="font-semibold text-gray-800 dark:text-gray-100 mb-1">Sin reportes todavía</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 max-w-xs">
                Ejecuta el primer análisis para empezar a generar reportes para {clientId.replace(/_/g, ' ')}.
              </p>
            </div>
            <Link
              href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
              className="mt-1 inline-flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
            >
              <Plus className="h-4 w-4" />
              Ejecutar análisis
            </Link>
          </div>
        ) : (
          <>
            {/* Section header */}
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
                Análisis ejecutados
                <span className="ml-2 font-bold text-gray-500 normal-case">({total})</span>
              </h2>
            </div>

            {/* Job cards */}
            <div className="space-y-3">
              {jobs.map(job => (
                <JobCard key={job.job_id} job={job} clientId={clientId} />
              ))}
            </div>

            {/* Load more */}
            {hasMore && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={handleLoadMore}
                  disabled={loadingMore}
                  className="inline-flex items-center gap-2 px-5 py-2.5 text-sm font-semibold text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loadingMore ? (
                    <>
                      <RefreshCw className="h-4 w-4 animate-spin" />
                      Cargando…
                    </>
                  ) : (
                    <>
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                      </svg>
                      Cargar más ({total - jobs.length} restantes)
                    </>
                  )}
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
