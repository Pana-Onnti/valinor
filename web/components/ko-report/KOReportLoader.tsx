'use client'

import { useEffect, useState } from 'react'
import axios from 'axios'
import { parseReport, type ParsedReport } from '@/lib/reportParser'
import { KOReportReveal } from '@/components/reveal/KOReportReveal'
import { T } from '@/components/d4c/tokens'
import { SkeletonCard, SkeletonKPIRow, SkeletonFindingList } from '@/components/ui/Skeleton'
import type { AnalysisConfidenceMetadata } from '@/lib/confidence-types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface KOReportLoaderProps {
  jobId: string
  onNewAnalysis?: () => void
}

export function KOReportLoader({ jobId, onNewAnalysis }: KOReportLoaderProps) {
  const [report, setReport] = useState<ParsedReport | null>(null)
  const [dqScore, setDqScore] = useState<number | undefined>(undefined)
  const [confidenceMetadata, setConfidenceMetadata] = useState<AnalysisConfidenceMetadata | undefined>(undefined)
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
        setConfidenceMetadata(res.data.confidence_metadata ?? undefined)
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
        padding: T.space.xl,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.lg,
        fontFamily: T.font.display,
      }}>
        <SkeletonCard />
        <SkeletonKPIRow />
        <SkeletonFindingList />
        <span style={{
          fontSize: 12,
          color: T.text.tertiary,
          fontFamily: T.font.mono,
          textAlign: 'center',
        }}>
          Cargando reporte…
        </span>
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

  return <KOReportReveal report={report} dqScore={dqScore} confidenceMetadata={confidenceMetadata} />
}
