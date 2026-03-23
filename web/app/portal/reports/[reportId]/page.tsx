'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { T, SEV_COLOR, SEV_LABEL } from '@/components/d4c/tokens'
import { getToken } from '@/lib/auth'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Finding {
  id: string
  severity: string
  headline: string
  evidence: string
  value_eur: number | null
  action: string
  domain: string
}

interface ReportDetail {
  id: string
  period: string
  date: string
  client_name: string
  findings: Finding[]
  summary: string
}

export default function PortalReportDetailPage() {
  const params = useParams()
  const router = useRouter()
  const reportId = params.reportId as string
  const [report, setReport] = useState<ReportDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      try {
        const token = getToken()
        const res = await fetch(`${BASE_URL}/api/v1/portal/reports/${reportId}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) {
          throw new Error(res.status === 404 ? 'Reporte no encontrado' : 'Error al cargar reporte')
        }
        setReport(await res.json())
      } catch (err: any) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [reportId])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: T.space.xxl, color: T.text.tertiary }}>
        Cargando reporte...
      </div>
    )
  }

  if (error || !report) {
    return (
      <div style={{ textAlign: 'center', padding: T.space.xxl }}>
        <p style={{ color: T.accent.red }}>{error || 'Reporte no encontrado'}</p>
        <button onClick={() => router.push('/portal/reports')} className="d4c-btn-ghost" style={{ marginTop: T.space.md }}>
          Volver a reportes
        </button>
      </div>
    )
  }

  const severityOrder = ['critical', 'warning', 'opportunity', 'info']
  const grouped = report.findings.reduce<Record<string, Finding[]>>((acc, f) => {
    const key = f.severity.toLowerCase()
    ;(acc[key] ??= []).push(f)
    return acc
  }, {})

  return (
    <div>
      {/* Back + Header */}
      <button
        onClick={() => router.push('/portal/reports')}
        style={{
          background: 'none',
          border: 'none',
          color: T.text.secondary,
          cursor: 'pointer',
          fontSize: '0.875rem',
          padding: 0,
          marginBottom: T.space.md,
        }}
      >
        &larr; Volver a reportes
      </button>

      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: T.space.xl,
      }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0 }}>
            Diagnostico {report.period}
          </h1>
          <p style={{ color: T.text.tertiary, marginTop: T.space.xs }}>
            {new Date(report.date).toLocaleDateString('es-AR', {
              day: 'numeric', month: 'long', year: 'numeric',
            })}
          </p>
        </div>
        <div style={{ display: 'flex', gap: T.space.sm }}>
          {Object.entries(grouped).map(([sev, findings]) => (
            <span
              key={sev}
              style={{
                backgroundColor: T.bg.elevated,
                borderRadius: T.radius.sm,
                padding: `${T.space.xs} ${T.space.md}`,
                fontSize: '0.813rem',
                fontWeight: 600,
                color: SEV_COLOR[sev.toUpperCase()] || T.text.secondary,
              }}
            >
              {findings.length} {SEV_LABEL[sev.toUpperCase()] || sev}
            </span>
          ))}
        </div>
      </div>

      {/* Summary */}
      {report.summary && (
        <div style={{
          backgroundColor: T.bg.card,
          borderRadius: T.radius.md,
          border: T.border.card,
          padding: T.space.lg,
          marginBottom: T.space.xl,
        }}>
          <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: T.accent.teal, marginTop: 0 }}>
            Resumen ejecutivo
          </h3>
          <p style={{ color: T.text.secondary, lineHeight: 1.6, margin: 0 }}>
            {report.summary}
          </p>
        </div>
      )}

      {/* Findings */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>
        {report.findings.map((f) => (
          <div
            key={f.id}
            style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.md,
              borderLeft: `3px solid ${SEV_COLOR[f.severity.toUpperCase()] || T.accent.blue}`,
              border: T.border.card,
              borderLeftWidth: 3,
              borderLeftColor: SEV_COLOR[f.severity.toUpperCase()] || T.accent.blue,
              padding: T.space.lg,
            }}
          >
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'flex-start',
              marginBottom: T.space.sm,
            }}>
              <div style={{ flex: 1 }}>
                <span style={{
                  fontSize: '0.688rem',
                  fontWeight: 600,
                  color: SEV_COLOR[f.severity.toUpperCase()] || T.text.tertiary,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}>
                  {SEV_LABEL[f.severity.toUpperCase()] || f.severity} &middot; {f.id}
                </span>
                <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: `${T.space.xs} 0` }}>
                  {f.headline}
                </h3>
              </div>
              {f.value_eur != null && (
                <span style={{
                  fontSize: '1.25rem',
                  fontWeight: 700,
                  fontFamily: T.font.mono,
                  color: f.value_eur < 0 ? T.accent.red : T.accent.teal,
                  whiteSpace: 'nowrap',
                  marginLeft: T.space.md,
                }}>
                  EUR {f.value_eur.toLocaleString('es-AR')}
                </span>
              )}
            </div>

            <p style={{ color: T.text.secondary, fontSize: '0.875rem', lineHeight: 1.5, margin: 0 }}>
              {f.evidence}
            </p>

            {f.action && (
              <div style={{
                marginTop: T.space.md,
                padding: `${T.space.sm} ${T.space.md}`,
                backgroundColor: T.bg.elevated,
                borderRadius: T.radius.sm,
                fontSize: '0.813rem',
              }}>
                <span style={{ color: T.accent.teal, fontWeight: 600 }}>Accion recomendada: </span>
                <span style={{ color: T.text.secondary }}>{f.action}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
