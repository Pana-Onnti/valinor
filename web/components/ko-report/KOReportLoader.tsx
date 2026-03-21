'use client'

import { useEffect, useState } from 'react'
import axios from 'axios'
import { parseReport, type ParsedReport } from '@/lib/reportParser'
import { KOReportV2 } from './KOReportV2'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface KOReportLoaderProps {
  jobId: string
  onNewAnalysis?: () => void
}

export function KOReportLoader({ jobId, onNewAnalysis }: KOReportLoaderProps) {
  const [report, setReport] = useState<ParsedReport | null>(null)
  const [dqScore, setDqScore] = useState<number | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    axios
      .get(`${API_URL}/api/jobs/${jobId}/results`)
      .then(res => {
        const raw = res.data.reports || {}
        // Preferir report ejecutivo; fallback al primero disponible
        const content: string =
          raw.executive ??
          raw.ceo ??
          Object.values(raw).find(v => typeof v === 'string') ??
          ''

        if (!content) {
          setError('No se encontró reporte ejecutivo.')
          return
        }

        setReport(parseReport(content))
        setDqScore(res.data.data_quality?.overall_score ?? undefined)
      })
      .catch(err => {
        setError(err?.response?.data?.detail ?? err?.message ?? 'Error al cargar el reporte.')
      })
      .finally(() => setLoading(false))
  }, [jobId])

  if (loading) {
    return (
      <div style={{
        minHeight: '100vh',
        background: T.bg.primary,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: T.space.md,
        fontFamily: T.font.mono,
      }}>
        <div style={{
          width: 40,
          height: 40,
          borderRadius: '50%',
          border: `2px solid ${T.bg.elevated}`,
          borderTopColor: T.accent.teal,
          animation: 'spin 0.8s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        <span style={{ fontSize: 12, color: T.text.tertiary }}>Cargando reporte…</span>
      </div>
    )
  }

  if (error || !report) {
    return (
      <div style={{
        minHeight: '100vh',
        background: T.bg.primary,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: T.space.md,
        fontFamily: T.font.display,
      }}>
        <div style={{ fontSize: 13, color: T.accent.red }}>{error ?? 'Reporte no disponible.'}</div>
        {onNewAnalysis && (
          <button
            onClick={onNewAnalysis}
            style={{
              fontFamily: T.font.mono,
              fontSize: 12,
              color: T.accent.teal,
              background: 'transparent',
              border: `1px solid ${T.accent.teal}40`,
              borderRadius: T.radius.sm,
              padding: `${T.space.xs} ${T.space.md}`,
              cursor: 'pointer',
            }}
          >
            ◂ Nuevo análisis
          </button>
        )}
      </div>
    )
  }

  return <KOReportV2 report={report} dqScore={dqScore} />
}
