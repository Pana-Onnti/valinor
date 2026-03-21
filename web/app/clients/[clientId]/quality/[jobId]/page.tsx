'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, CheckCircle2, XCircle } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

type GateDecision = 'PROCEED' | 'WARN' | 'HALT' | string

interface DQCheck {
  check_name: string
  passed: boolean
  severity: 'critical' | 'high' | 'medium' | 'low' | string
  score_impact: number
  message?: string
}

interface QualityReport {
  job_id: string
  dq_score: number
  gate_decision: GateDecision
  data_quality_tag: string
  checks: DQCheck[]
  run_date?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso?: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleDateString('es-ES', {
      day: '2-digit',
      month: 'long',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}

// ── DQ Score display ──────────────────────────────────────────────────────────

function scoreColors(score: number) {
  if (score >= 90)
    return {
      text: 'text-emerald-600 dark:text-emerald-400',
      bg: 'bg-emerald-50 dark:bg-emerald-900/20',
      border: 'border-emerald-200 dark:border-emerald-800',
      ring: '#34d399',
    }
  if (score >= 75)
    return {
      text: 'text-amber-600 dark:text-amber-400',
      bg: 'bg-amber-50 dark:bg-amber-900/20',
      border: 'border-amber-200 dark:border-amber-800',
      ring: '#fbbf24',
    }
  if (score >= 50)
    return {
      text: 'text-orange-600 dark:text-orange-400',
      bg: 'bg-orange-50 dark:bg-orange-900/20',
      border: 'border-orange-200 dark:border-orange-800',
      ring: '#fb923c',
    }
  return {
    text: 'text-red-600 dark:text-red-400',
    bg: 'bg-red-50 dark:bg-red-900/20',
    border: 'border-red-200 dark:border-red-800',
    ring: '#f87171',
  }
}

function ScoreRing({ score }: { score: number }) {
  const radius = 44
  const circumference = 2 * Math.PI * radius
  const filled = (score / 100) * circumference
  const colors = scoreColors(score)

  return (
    <div className="relative w-28 h-28 flex-shrink-0">
      <svg className="w-28 h-28 -rotate-90" viewBox="0 0 112 112">
        <circle
          cx="56" cy="56" r={radius}
          fill="none"
          strokeWidth="8"
          className="stroke-gray-200 dark:stroke-gray-700"
        />
        <circle
          cx="56" cy="56" r={radius}
          fill="none"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          stroke={colors.ring}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-3xl font-bold ${colors.text}`}>{score}</span>
        <span className="text-xs text-gray-400">/100</span>
      </div>
    </div>
  )
}

// ── Gate Decision Badge ───────────────────────────────────────────────────────

function GateDecisionBadge({ decision }: { decision: GateDecision }) {
  const normalized = decision?.toUpperCase()
  if (normalized === 'PROCEED') {
    return (
      <span className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-bold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
        <CheckCircle2 className="h-4 w-4" />
        PROCEED
      </span>
    )
  }
  if (normalized === 'WARN') {
    return (
      <span className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-bold bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 border border-amber-200 dark:border-amber-800">
        WARN
      </span>
    )
  }
  if (normalized === 'HALT') {
    return (
      <span className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-bold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400 border border-red-200 dark:border-red-800">
        <XCircle className="h-4 w-4" />
        HALT
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-4 py-1.5 rounded-full text-sm font-bold bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
      {decision || '—'}
    </span>
  )
}

// ── Severity Badge ────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    critical: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400',
    high:     'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400',
    medium:   'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400',
    low:      'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  }
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full uppercase tracking-wide ${map[severity] ?? map.low}`}>
      {severity}
    </span>
  )
}

// ── Loading Skeleton ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8 animate-pulse">
      <div className="max-w-4xl mx-auto space-y-6">
        <div className="h-5 bg-gray-200 dark:bg-gray-800 rounded w-80" />
        <div className="h-40 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
        <div className="space-y-3">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-12 bg-gray-200 dark:bg-gray-800 rounded-xl" />
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function QualityReportPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const jobId = params.jobId as string

  const [report, setReport] = useState<QualityReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/api/jobs/${encodeURIComponent(jobId)}/quality`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<QualityReport>
      })
      .then(setReport)
      .catch(err => setError(err.message || 'Error cargando reporte de calidad'))
      .finally(() => setLoading(false))
  }, [jobId])

  if (loading) return <LoadingSkeleton />

  if (error || !report) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-500 mb-4">{error || 'Reporte no disponible'}</p>
          <Link href={`/clients/${clientId}/reports`} className="text-violet-600 hover:underline text-sm">
            ← Volver a Reportes
          </Link>
        </div>
      </div>
    )
  }

  const colors = scoreColors(report.dq_score)
  const passedCount = report.checks.filter(c => c.passed).length
  const totalCount = report.checks.length

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* ── Sticky header ── */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href={`/clients/${clientId}/reports`}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">Reporte de Calidad</h1>
              <p className="text-xs text-gray-400 font-mono">{jobId.slice(0, 8)}</p>
            </div>
          </div>
          {report.run_date && (
            <span className="text-xs text-gray-400">{formatDate(report.run_date)}</span>
          )}
        </div>
      </header>

      {/* ── Breadcrumb ── */}
      <div className="max-w-4xl mx-auto px-6 pt-6">
        <nav className="flex items-center gap-1.5 text-xs text-gray-400">
          <Link href="/clients" className="hover:text-violet-600 transition-colors">Clientes</Link>
          <span>/</span>
          <Link href={`/clients/${clientId}`} className="hover:text-violet-600 transition-colors">{clientId}</Link>
          <span>/</span>
          <Link href={`/clients/${clientId}/reports`} className="hover:text-violet-600 transition-colors">Reportes</Link>
          <span>/</span>
          <span className="text-gray-600 dark:text-gray-300 font-medium">Calidad</span>
        </nav>
      </div>

      <main className="max-w-4xl mx-auto px-6 py-6 space-y-8">

        {/* ── Hero score card ── */}
        <div className={`rounded-2xl border p-6 flex flex-col sm:flex-row items-start sm:items-center gap-6 ${colors.bg} ${colors.border}`}>
          <ScoreRing score={report.dq_score} />

          <div className="flex-1 min-w-0 space-y-3">
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1">
                Data Quality Score
              </p>
              <p className={`text-4xl font-bold tabular-nums ${colors.text}`}>
                {report.dq_score}
                <span className="text-base font-normal text-gray-400">/100</span>
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <GateDecisionBadge decision={report.gate_decision} />
              <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold border ${colors.bg} ${colors.border} ${colors.text}`}>
                {report.data_quality_tag}
              </span>
            </div>

            <p className="text-sm text-gray-500 dark:text-gray-400">
              {passedCount} de {totalCount} checks superados
            </p>
          </div>
        </div>

        {/* ── Individual checks table ── */}
        {report.checks.length > 0 ? (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Checks individuales
            </h2>
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
              {/* Table header */}
              <div className="grid grid-cols-[2fr_0.8fr_0.8fr_0.8fr] gap-4 px-6 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50 text-xs font-semibold text-gray-400 uppercase tracking-widest">
                <span>Check</span>
                <span className="text-center">Resultado</span>
                <span className="text-center">Severidad</span>
                <span className="text-right">Impacto</span>
              </div>

              {/* Table rows */}
              <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
                {report.checks.map((check, idx) => (
                  <div
                    key={idx}
                    className="grid grid-cols-[2fr_0.8fr_0.8fr_0.8fr] gap-4 px-6 py-3.5 items-center hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors"
                  >
                    {/* Check name + optional message */}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate">
                        {check.check_name}
                      </p>
                      {check.message && (
                        <p className="text-xs text-gray-400 truncate mt-0.5">{check.message}</p>
                      )}
                    </div>

                    {/* Passed / Failed */}
                    <div className="flex justify-center">
                      {check.passed ? (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                          <CheckCircle2 className="h-4 w-4" />
                          OK
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600 dark:text-red-400">
                          <XCircle className="h-4 w-4" />
                          Fail
                        </span>
                      )}
                    </div>

                    {/* Severity */}
                    <div className="flex justify-center">
                      <SeverityBadge severity={check.severity} />
                    </div>

                    {/* Score impact */}
                    <div className="text-right">
                      <span className={`text-sm font-mono font-semibold ${
                        check.score_impact < 0
                          ? 'text-red-600 dark:text-red-400'
                          : check.score_impact > 0
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : 'text-gray-400'
                      }`}>
                        {check.score_impact > 0 ? '+' : ''}{check.score_impact}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 p-10 text-center">
            <p className="text-sm text-gray-400">No hay checks disponibles para este análisis.</p>
          </div>
        )}

      </main>
    </div>
  )
}
