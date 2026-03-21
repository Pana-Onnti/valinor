'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

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

function scoreAccent(score: number): string {
  if (score >= 90) return T.accent.teal
  if (score >= 75) return T.accent.yellow
  if (score >= 50) return T.accent.orange
  return T.accent.red
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
    return <span style={{ color: T.text.tertiary, fontSize: 12 }}>—</span>
  }
  const normalized = decision.toLowerCase()
  const color =
    normalized === 'pass' || normalized === 'approved' || normalized === 'proceed'
      ? T.accent.teal
      : normalized === 'warn' || normalized === 'warning'
      ? T.accent.yellow
      : normalized === 'fail' || normalized === 'rejected' || normalized === 'abort' || normalized === 'halt'
      ? T.accent.red
      : T.text.tertiary

  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: 999,
      fontSize: 11,
      fontWeight: 600,
      fontFamily: T.font.mono,
      textTransform: 'uppercase',
      backgroundColor: color + '15',
      border: `1px solid ${color}40`,
      color,
    }}>
      {decision}
    </span>
  )
}

// ── Trend Indicator ───────────────────────────────────────────────────────────

function TrendIndicator({ trend }: { trend: string | null }) {
  const config = trend === 'improving'
    ? { arrow: '↑', label: 'Mejorando', sub: 'La calidad de datos está en tendencia positiva', color: T.accent.teal }
    : trend === 'declining'
    ? { arrow: '↓', label: 'Bajando', sub: 'La calidad de datos está en tendencia negativa', color: T.accent.red }
    : trend === 'stable'
    ? { arrow: '→', label: 'Estable', sub: 'La calidad de datos se mantiene sin cambios significativos', color: T.text.tertiary }
    : null

  if (!config) return null

  return (
    <div style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 12,
      padding: `${T.space.sm} ${T.space.md}`,
      borderRadius: T.radius.md,
      backgroundColor: config.color + '10',
      border: `1px solid ${config.color}30`,
    }}>
      <span style={{ fontSize: 24, fontWeight: 700, color: config.color }}>{config.arrow}</span>
      <div>
        <p style={{ fontSize: 13, fontWeight: 600, color: config.color, margin: 0 }}>{config.label}</p>
        <p style={{ fontSize: 11, color: config.color, opacity: 0.7, margin: 0 }}>{config.sub}</p>
      </div>
    </div>
  )
}

// ── Loading Skeleton ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  const pulse: React.CSSProperties = { backgroundColor: T.bg.elevated, borderRadius: T.radius.md }
  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xl }}>
      <div style={{ maxWidth: 960, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
        <div style={{ ...pulse, height: 32, width: 224 }} />
        <div style={{ ...pulse, height: 48, width: 256 }} />
        <div style={{ ...pulse, height: 256, borderRadius: T.radius.lg }} />
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
    { label: 'Alertas',       href: `/clients/${clientId}/alerts` },
    { label: 'Costos',        href: `/clients/${clientId}/costs` },
    { label: 'KPIs',          href: `/clients/${clientId}/kpis` },
    { label: 'Segmentación',  href: `/clients/${clientId}/segmentation` },
    { label: 'Historial DQ',  href: `/clients/${clientId}/dq-history` },
    { label: 'Configuración', href: `/clients/${clientId}/settings` },
  ]
  return (
    <nav style={{ display: 'flex', gap: 0, overflowX: 'auto' }}>
      {tabs.map(tab => {
        const isActive = pathname === tab.href
        return (
          <Link
            key={tab.href}
            href={tab.href}
            style={{
              display: 'inline-block',
              padding: '10px 16px',
              fontSize: 13,
              fontWeight: isActive ? 600 : 400,
              color: isActive ? T.accent.teal : T.text.tertiary,
              borderBottom: isActive ? `2px solid ${T.accent.teal}` : '2px solid transparent',
              textDecoration: 'none',
              whiteSpace: 'nowrap',
              transition: 'color 150ms',
            }}
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
      <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: T.text.secondary, marginBottom: T.space.md }}>{error}</p>
          <Link href={`/clients/${clientId}`} style={{ color: T.accent.teal, fontSize: 13, textDecoration: 'none' }}>
            ← Volver al cliente
          </Link>
        </div>
      </div>
    )
  }

  const history = data?.dq_history ?? []
  const avgScore = data?.avg_score ?? null
  const trend = data?.trend ?? null
  const isEmpty = history.length === 0
  const avgColor = avgScore !== null ? scoreAccent(avgScore) : T.text.tertiary

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Sticky header */}
      <header style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 960, margin: '0 auto', padding: `${T.space.md} ${T.space.xl}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.md }}>
            <Link href={`/clients/${clientId}`} style={{ color: T.text.tertiary, display: 'flex' }}>
              <ArrowLeft size={20} />
            </Link>
            <div>
              <h1 style={{ fontSize: 16, fontWeight: 700, color: T.text.primary, margin: 0 }}>{clientId}</h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>Historial de Calidad de Datos</p>
            </div>
          </div>
          {avgScore !== null && (
            <span style={{
              padding: '6px 12px',
              borderRadius: 999,
              fontSize: 13,
              fontWeight: 700,
              fontFamily: T.font.mono,
              backgroundColor: avgColor + '15',
              border: `1px solid ${avgColor}40`,
              color: avgColor,
            }}>
              Promedio: {avgScore}/100
            </span>
          )}
        </div>
        <div style={{ maxWidth: 960, margin: '0 auto', padding: `0 ${T.space.xl}` }}>
          <TabNav clientId={clientId} pathname={pathname} />
        </div>
      </header>

      <main style={{ maxWidth: 960, margin: '0 auto', padding: T.space.xl, display: 'flex', flexDirection: 'column', gap: T.space.xl }}>

        {/* Trend indicator */}
        {trend && !isEmpty && (
          <div>
            <p style={{ fontSize: 10, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.text.tertiary, marginBottom: T.space.sm }}>
              Tendencia general
            </p>
            <TrendIndicator trend={trend} />
          </div>
        )}

        {/* Empty state */}
        {isEmpty ? (
          <div style={{
            backgroundColor: T.bg.card,
            borderRadius: T.radius.lg,
            border: `1px dashed ${T.bg.hover}`,
            padding: `${T.space.xxl} ${T.space.lg}`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: T.space.md,
            textAlign: 'center',
          }}>
            <div style={{ padding: T.space.md, borderRadius: T.radius.md, backgroundColor: T.accent.teal + '10' }}>
              <svg width="32" height="32" fill="none" viewBox="0 0 24 24" stroke={T.accent.teal} strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
            </div>
            <div>
              <p style={{ fontWeight: 600, color: T.text.primary, marginBottom: 4 }}>Sin historial de DQ todavía</p>
              <p style={{ fontSize: 13, color: T.text.secondary }}>
                Ejecuta un análisis para comenzar a registrar puntuaciones de calidad de datos.
              </p>
            </div>
            <Link href="/new-analysis" className="d4c-btn-primary">
              Nuevo análisis
            </Link>
          </div>
        ) : (
          <div>
            <p style={{ fontSize: 10, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.text.tertiary, marginBottom: T.space.sm }}>
              {history.length} entrada{history.length !== 1 ? 's' : ''}
            </p>
            <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, overflow: 'hidden' }}>
              {/* Table header */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: '2fr 1fr 1fr 1fr',
                gap: T.space.md,
                padding: `${T.space.sm} ${T.space.xl}`,
                backgroundColor: T.bg.elevated,
                borderBottom: T.border.card,
              }}>
                {['Fecha', 'Score DQ', 'Checks superados', 'Gate'].map(h => (
                  <span key={h} style={{ fontSize: 10, fontWeight: 600, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.text.tertiary }}>
                    {h}
                  </span>
                ))}
              </div>

              {/* Table rows */}
              <div>
                {[...history].reverse().map((entry, idx) => {
                  const color = scoreAccent(entry.score)
                  return (
                    <div
                      key={idx}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '2fr 1fr 1fr 1fr',
                        gap: T.space.md,
                        padding: `14px ${T.space.xl}`,
                        alignItems: 'center',
                        borderTop: idx > 0 ? T.border.subtle : undefined,
                      }}
                    >
                      <span style={{ fontSize: 13, color: T.text.secondary, fontFamily: T.font.mono }}>
                        {formatDate(entry.run_date)}
                      </span>

                      <div>
                        <span style={{ fontSize: 13, fontWeight: 600, color }}>
                          {entry.score}
                        </span>
                        <span style={{ fontSize: 11, color: T.text.tertiary }}>/100</span>
                      </div>

                      <div>
                        {entry.passed_checks !== undefined && entry.total_checks !== undefined ? (
                          <span style={{ fontSize: 13, color: T.text.secondary }}>
                            <span style={{ fontWeight: 600, color: T.text.primary }}>{entry.passed_checks}</span>
                            <span style={{ color: T.text.tertiary }}>/{entry.total_checks}</span>
                          </span>
                        ) : (
                          <span style={{ fontSize: 13, color: T.text.tertiary }}>—</span>
                        )}
                      </div>

                      <div>
                        <GateDecisionBadge decision={entry.gate_decision} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
