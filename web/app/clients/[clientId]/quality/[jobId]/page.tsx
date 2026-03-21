'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, CheckCircle2, XCircle } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

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
      textColor: T.accent.teal,
      bgColor: T.accent.teal + '15',
      borderColor: T.accent.teal + '40',
      ring: T.accent.teal,
    }
  if (score >= 75)
    return {
      textColor: T.accent.yellow,
      bgColor: T.accent.yellow + '15',
      borderColor: T.accent.yellow + '40',
      ring: T.accent.yellow,
    }
  if (score >= 50)
    return {
      textColor: T.accent.orange,
      bgColor: T.accent.orange + '15',
      borderColor: T.accent.orange + '40',
      ring: T.accent.orange,
    }
  return {
    textColor: T.accent.red,
    bgColor: T.accent.red + '15',
    borderColor: T.accent.red + '40',
    ring: T.accent.red,
  }
}

function ScoreRing({ score }: { score: number }) {
  const radius = 44
  const circumference = 2 * Math.PI * radius
  const filled = (score / 100) * circumference
  const colors = scoreColors(score)

  return (
    <div style={{ position: 'relative', width: 112, height: 112, flexShrink: 0 }}>
      <svg style={{ width: 112, height: 112, transform: 'rotate(-90deg)' }} viewBox="0 0 112 112">
        <circle
          cx="56" cy="56" r={radius}
          fill="none"
          strokeWidth="8"
          stroke={T.bg.hover}
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
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ fontSize: 30, fontWeight: 700, color: colors.textColor }}>{score}</span>
        <span style={{ fontSize: 12, color: T.text.tertiary }}>/100</span>
      </div>
    </div>
  )
}

// ── Gate Decision Badge ───────────────────────────────────────────────────────

function GateDecisionBadge({ decision }: { decision: GateDecision }) {
  const normalized = decision?.toUpperCase()
  if (normalized === 'PROCEED') {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 16px', borderRadius: 999, fontSize: 14, fontWeight: 700, backgroundColor: T.accent.teal + '20', color: T.accent.teal, border: `1px solid ${T.accent.teal}40` }}>
        <CheckCircle2 size={16} />
        PROCEED
      </span>
    )
  }
  if (normalized === 'WARN') {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 16px', borderRadius: 999, fontSize: 14, fontWeight: 700, backgroundColor: T.accent.yellow + '20', color: T.accent.yellow, border: `1px solid ${T.accent.yellow}40` }}>
        WARN
      </span>
    )
  }
  if (normalized === 'HALT') {
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 16px', borderRadius: 999, fontSize: 14, fontWeight: 700, backgroundColor: T.accent.red + '20', color: T.accent.red, border: `1px solid ${T.accent.red}40` }}>
        <XCircle size={16} />
        HALT
      </span>
    )
  }
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', padding: '6px 16px', borderRadius: 999, fontSize: 14, fontWeight: 700, backgroundColor: T.bg.elevated, color: T.text.secondary }}>
      {decision || '—'}
    </span>
  )
}

// ── Severity Badge ────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const colorMap: Record<string, { bg: string; color: string }> = {
    critical: { bg: T.accent.red + '20',    color: T.accent.red },
    high:     { bg: T.accent.orange + '20', color: T.accent.orange },
    medium:   { bg: T.accent.yellow + '20', color: T.accent.yellow },
    low:      { bg: T.bg.elevated,           color: T.text.secondary },
  }
  const c = colorMap[severity] ?? colorMap.low
  return (
    <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999, textTransform: 'uppercase', letterSpacing: '0.06em', backgroundColor: c.bg, color: c.color }}>
      {severity}
    </span>
  )
}

// ── Loading Skeleton ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: 32 }}>
      <div style={{ maxWidth: 896, margin: '0 auto' }}>
        <div style={{ height: 20, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 320, marginBottom: 24 }} />
        <div style={{ height: 160, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, marginBottom: 24 }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[...Array(8)].map((_, i) => (
            <div key={i} style={{ height: 48, backgroundColor: T.bg.elevated, borderRadius: T.radius.md }} />
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
      <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: T.text.secondary, marginBottom: 16 }}>{error || 'Reporte no disponible'}</p>
          <Link href={`/clients/${clientId}/reports`} style={{ color: T.accent.teal, fontSize: 14 }}>
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
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* ── Sticky header ── */}
      <header style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 896, margin: '0 auto', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Link
              href={`/clients/${clientId}/reports`}
              style={{ color: T.text.tertiary }}
            >
              <ArrowLeft size={20} />
            </Link>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0 }}>Reporte de Calidad</h1>
              <p style={{ fontSize: 12, color: T.text.tertiary, fontFamily: T.font.mono, margin: 0 }}>{jobId.slice(0, 8)}</p>
            </div>
          </div>
          {report.run_date && (
            <span style={{ fontSize: 12, color: T.text.tertiary }}>{formatDate(report.run_date)}</span>
          )}
        </div>
      </header>

      {/* ── Breadcrumb ── */}
      <div style={{ maxWidth: 896, margin: '0 auto', padding: '24px 24px 0' }}>
        <nav style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.text.tertiary }}>
          <Link href="/clients" style={{ color: T.text.tertiary, textDecoration: 'none' }}>Clientes</Link>
          <span>/</span>
          <Link href={`/clients/${clientId}`} style={{ color: T.text.tertiary, textDecoration: 'none' }}>{clientId}</Link>
          <span>/</span>
          <Link href={`/clients/${clientId}/reports`} style={{ color: T.text.tertiary, textDecoration: 'none' }}>Reportes</Link>
          <span>/</span>
          <span style={{ color: T.text.primary, fontWeight: 500 }}>Calidad</span>
        </nav>
      </div>

      <main style={{ maxWidth: 896, margin: '0 auto', padding: '24px 24px', display: 'flex', flexDirection: 'column', gap: 32 }}>

        {/* ── Hero score card ── */}
        <div style={{ borderRadius: T.radius.lg, border: `1px solid ${colors.borderColor}`, padding: 24, display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 24, backgroundColor: colors.bgColor, flexWrap: 'wrap' }}>
          <ScoreRing score={report.dq_score} />

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ marginBottom: 12 }}>
              <p style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 4, marginTop: 0 }}>
                Data Quality Score
              </p>
              <p style={{ fontSize: 36, fontWeight: 700, color: colors.textColor, margin: 0, fontVariantNumeric: 'tabular-nums' }}>
                {report.dq_score}
                <span style={{ fontSize: 16, fontWeight: 400, color: T.text.tertiary }}>/100</span>
              </p>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <GateDecisionBadge decision={report.gate_decision} />
              <span style={{ display: 'inline-flex', alignItems: 'center', padding: '4px 12px', borderRadius: 999, fontSize: 12, fontWeight: 600, border: `1px solid ${colors.borderColor}`, backgroundColor: colors.bgColor, color: colors.textColor }}>
                {report.data_quality_tag}
              </span>
            </div>

            <p style={{ fontSize: 14, color: T.text.secondary, margin: 0 }}>
              {passedCount} de {totalCount} checks superados
            </p>
          </div>
        </div>

        {/* ── Individual checks table ── */}
        {report.checks.length > 0 ? (
          <div>
            <h2 style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 12, marginTop: 0 }}>
              Checks individuales
            </h2>
            <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, overflow: 'hidden' }}>
              {/* Table header */}
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 0.8fr 0.8fr 0.8fr', gap: 16, padding: '12px 24px', borderBottom: T.border.card, backgroundColor: T.bg.elevated, fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                <span>Check</span>
                <span style={{ textAlign: 'center' }}>Resultado</span>
                <span style={{ textAlign: 'center' }}>Severidad</span>
                <span style={{ textAlign: 'right' }}>Impacto</span>
              </div>

              {/* Table rows */}
              <div>
                {report.checks.map((check, idx) => (
                  <div
                    key={idx}
                    style={{ display: 'grid', gridTemplateColumns: '2fr 0.8fr 0.8fr 0.8fr', gap: 16, padding: '14px 24px', alignItems: 'center', borderTop: idx > 0 ? T.border.subtle : 'none' }}
                  >
                    {/* Check name + optional message */}
                    <div style={{ minWidth: 0 }}>
                      <p style={{ fontSize: 14, fontWeight: 500, color: T.text.primary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', margin: 0 }}>
                        {check.check_name}
                      </p>
                      {check.message && (
                        <p style={{ fontSize: 12, color: T.text.tertiary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginTop: 2, marginBottom: 0 }}>{check.message}</p>
                      )}
                    </div>

                    {/* Passed / Failed */}
                    <div style={{ display: 'flex', justifyContent: 'center' }}>
                      {check.passed ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: T.accent.teal }}>
                          <CheckCircle2 size={16} />
                          OK
                        </span>
                      ) : (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: T.accent.red }}>
                          <XCircle size={16} />
                          Fail
                        </span>
                      )}
                    </div>

                    {/* Severity */}
                    <div style={{ display: 'flex', justifyContent: 'center' }}>
                      <SeverityBadge severity={check.severity} />
                    </div>

                    {/* Score impact */}
                    <div style={{ textAlign: 'right' }}>
                      <span style={{ fontSize: 14, fontFamily: T.font.mono, fontWeight: 600, color: check.score_impact < 0 ? T.accent.red : check.score_impact > 0 ? T.accent.teal : T.text.tertiary }}>
                        {check.score_impact > 0 ? '+' : ''}{check.score_impact}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: `1px dashed ${T.text.tertiary}`, padding: 40, textAlign: 'center' }}>
            <p style={{ fontSize: 14, color: T.text.tertiary, margin: 0 }}>No hay checks disponibles para este análisis.</p>
          </div>
        )}

      </main>
    </div>
  )
}
