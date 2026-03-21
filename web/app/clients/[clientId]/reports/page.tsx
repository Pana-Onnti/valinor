'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, usePathname } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, RefreshCw, FileDown, ShieldCheck, Plus } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

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
  const config: Record<JobStatus, { label: string; color: string; bg: string }> = {
    completed: {
      label: 'Completado',
      color: T.accent.teal,
      bg: T.accent.teal + '15',
    },
    failed: {
      label: 'Fallido',
      color: T.accent.red,
      bg: T.accent.red + '15',
    },
    error: {
      label: 'Error',
      color: T.accent.red,
      bg: T.accent.red + '15',
    },
    running: {
      label: 'En curso',
      color: T.accent.blue,
      bg: T.accent.blue + '15',
    },
    pending: {
      label: 'Pendiente',
      color: T.text.tertiary,
      bg: T.text.tertiary + '15',
    },
  }
  const { label, color, bg } = config[status] ?? config.pending
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '2px 10px',
      borderRadius: 999,
      fontSize: 11,
      fontWeight: 600,
      color,
      backgroundColor: bg,
    }}>
      <span style={{
        width: 6,
        height: 6,
        borderRadius: '50%',
        flexShrink: 0,
        backgroundColor: color,
      }} />
      {label}
    </span>
  )
}

// ── Job Card ──────────────────────────────────────────────────────────────────

function JobCard({ job, clientId }: { job: Job; clientId: string }) {
  const canExport = job.status === 'completed'

  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.lg,
      border: T.border.card,
      padding: '16px 20px',
    }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.lg }}>

        {/* Left: metadata */}
        <div style={{ flex: 1, minWidth: 0 }}>

          {/* Top row: ID + period + status */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: T.space.sm }}>
            <span
              title={job.job_id}
              style={{
                fontFamily: T.font.mono,
                fontSize: 11,
                backgroundColor: T.accent.teal + '10',
                border: `1px solid ${T.accent.teal}30`,
                color: T.accent.teal,
                borderRadius: T.radius.sm,
                padding: '2px 8px',
                cursor: 'pointer',
                userSelect: 'all',
              }}
            >
              #{shortId(job.job_id)}
            </span>

            {job.period && (
              <span style={{
                fontSize: 11,
                fontWeight: 500,
                color: T.text.primary,
                backgroundColor: T.bg.elevated,
                padding: '2px 8px',
                borderRadius: T.radius.sm,
                fontFamily: T.font.mono,
              }}>
                {job.period}
              </span>
            )}

            <StatusBadge status={job.status} />
          </div>

          {/* Started at */}
          <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
            Iniciado:{' '}
            <span style={{ color: T.text.primary, fontWeight: 500 }}>
              {formatDate(job.started_at ?? job.created_at)}
            </span>
          </p>
        </div>

        {/* Right: action buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, flexWrap: 'wrap' }}>

          {/* Quality report link */}
          <Link
            href={`/api/jobs/${encodeURIComponent(job.job_id)}/quality`}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              fontSize: 11,
              fontWeight: 500,
              color: T.accent.teal,
              backgroundColor: T.accent.teal + '10',
              border: `1px solid ${T.accent.teal}30`,
              borderRadius: T.radius.md,
              textDecoration: 'none',
            }}
          >
            <ShieldCheck style={{ width: 14, height: 14 }} />
            Calidad
          </Link>

          {/* PDF export */}
          {canExport ? (
            <a
              href={`${API_URL}/api/jobs/${encodeURIComponent(job.job_id)}/export/pdf`}
              target="_blank"
              rel="noopener noreferrer"
              download
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                fontSize: 11,
                fontWeight: 500,
                color: T.accent.teal,
                backgroundColor: T.accent.teal + '10',
                border: `1px solid ${T.accent.teal}30`,
                borderRadius: T.radius.md,
                textDecoration: 'none',
              }}
            >
              <FileDown style={{ width: 14, height: 14 }} />
              PDF
            </a>
          ) : (
            <span
              title="Disponible cuando el análisis complete"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                fontSize: 11,
                fontWeight: 500,
                color: T.text.tertiary,
                backgroundColor: T.bg.elevated,
                border: T.border.card,
                borderRadius: T.radius.md,
                opacity: 0.6,
                cursor: 'not-allowed',
              }}
            >
              <FileDown style={{ width: 14, height: 14 }} />
              PDF
            </span>
          )}

          {/* Live progress for running jobs */}
          {job.status === 'running' && (
            <Link
              href={`/results/${encodeURIComponent(job.job_id)}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 12px',
                fontSize: 11,
                fontWeight: 500,
                color: T.accent.blue,
                backgroundColor: T.accent.blue + '10',
                border: `1px solid ${T.accent.blue}30`,
                borderRadius: T.radius.md,
                textDecoration: 'none',
              }}
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
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xxl }}>
      <div style={{ maxWidth: 896, margin: '0 auto' }}>
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 192, marginBottom: T.space.xl }} />
        <div style={{ height: 40, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, marginBottom: T.space.sm }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
          {[...Array(5)].map((_, i) => (
            <div key={i} style={{ height: 80, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
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
    <nav style={{ display: 'flex', gap: 4, overflowX: 'auto' }}>
      {tabs.map(tab => {
        const isActive = pathname === tab.href
        return (
          <Link
            key={tab.href}
            href={tab.href}
            style={isActive
              ? { borderBottom: `2px solid ${T.accent.teal}`, color: T.accent.teal, padding: '10px 16px', fontSize: 13, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap' }
              : { borderBottom: '2px solid transparent', color: T.text.tertiary, padding: '10px 16px', fontSize: 13, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap' }}
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
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <svg style={{ width: 40, height: 40, color: T.accent.red, margin: '0 auto 12px' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <p style={{ color: T.text.secondary, marginBottom: T.space.lg }}>{error}</p>
        <button onClick={handleRefresh} style={{ color: T.accent.teal, fontSize: 13, background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>
          Reintentar
        </button>
      </div>
    </div>
  )

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>

      {/* ── Sticky header ── */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: T.bg.card,
        borderBottom: T.border.card,
      }}>
        <div style={{ maxWidth: 896, margin: '0 auto', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}>
            <Link
              href={`/clients/${clientId}`}
              style={{ color: T.text.tertiary, display: 'flex', alignItems: 'center' }}
            >
              <ArrowLeft style={{ width: 20, height: 20 }} />
            </Link>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                <svg style={{ width: 16, height: 16, color: T.accent.teal }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                Reportes · {clientId.replace(/_/g, ' ')}
              </h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
                {total} análisis en total
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
            <Link
              href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
              className="d4c-btn-primary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13 }}
            >
              <Plus style={{ width: 14, height: 14 }} />
              Nuevo análisis
            </Link>
            <button
              onClick={handleRefresh}
              className="d4c-btn-ghost"
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
            >
              <RefreshCw style={{ width: 14, height: 14 }} />
              Actualizar
            </button>
          </div>
        </div>

        {/* Tab nav */}
        <div style={{ maxWidth: 896, margin: '0 auto', padding: '0 24px' }}>
          <TabNav clientId={clientId} pathname={pathname} />
        </div>
      </header>

      <main style={{ maxWidth: 896, margin: '0 auto', padding: '32px 24px' }}>

        {/* Non-fatal error banner */}
        {error && jobs.length > 0 && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: T.space.sm,
            padding: '12px 16px',
            backgroundColor: T.accent.red + '10',
            border: `1px solid ${T.accent.red}30`,
            borderRadius: T.radius.md,
            color: T.accent.red,
            fontSize: 13,
            marginBottom: T.space.xl,
          }}>
            <svg style={{ width: 16, height: 16, flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            {error}
          </div>
        )}

        {/* Empty state */}
        {jobs.length === 0 ? (
          <div style={{
            backgroundColor: T.bg.card,
            borderRadius: T.radius.lg,
            border: `1px dashed #1E1E28`,
            padding: '64px 24px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: T.space.lg,
            textAlign: 'center',
          }}>
            <div style={{
              padding: T.space.lg,
              borderRadius: T.radius.lg,
              backgroundColor: T.accent.teal + '10',
            }}>
              <FileDown style={{ width: 32, height: 32, color: T.accent.teal }} />
            </div>
            <div>
              <p style={{ fontWeight: 600, color: T.text.primary, marginBottom: 4 }}>Sin reportes todavía</p>
              <p style={{ fontSize: 13, color: T.text.secondary, maxWidth: 300, margin: '0 auto' }}>
                Ejecuta el primer análisis para empezar a generar reportes para {clientId.replace(/_/g, ' ')}.
              </p>
            </div>
            <Link
              href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
              className="d4c-btn-primary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginTop: 4, fontSize: 13 }}
            >
              <Plus style={{ width: 16, height: 16 }} />
              Ejecutar análisis
            </Link>
          </div>
        ) : (
          <>
            {/* Section header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.sm }}>
              <h2 style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', margin: 0 }}>
                Análisis ejecutados
                <span style={{ marginLeft: 8, fontWeight: 700, color: T.text.secondary, textTransform: 'none' }}>({total})</span>
              </h2>
            </div>

            {/* Job cards */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm, marginBottom: T.space.xl }}>
              {jobs.map(job => (
                <JobCard key={job.job_id} job={job} clientId={clientId} />
              ))}
            </div>

            {/* Load more */}
            {hasMore && (
              <div style={{ display: 'flex', justifyContent: 'center', paddingTop: T.space.sm }}>
                <button
                  onClick={handleLoadMore}
                  disabled={loadingMore}
                  className="d4c-btn-ghost"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, opacity: loadingMore ? 0.5 : 1, cursor: loadingMore ? 'not-allowed' : 'pointer' }}
                >
                  {loadingMore ? (
                    <>
                      <RefreshCw style={{ width: 16, height: 16 }} />
                      Cargando…
                    </>
                  ) : (
                    <>
                      <svg style={{ width: 16, height: 16 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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
