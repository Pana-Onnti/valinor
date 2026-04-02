'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, TrendingUp, Clock, Target, AlertOctagon } from 'lucide-react'
import Link from 'next/link'
import { KPITrendChart } from '@/components/KPITrendChart'
import { FindingTimeline } from '@/components/FindingTimeline'
import { DeltaPanel } from '@/components/DeltaPanel'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface ClientProfileData {
  client_name: string
  run_count: number
  last_run_date: string | null
  industry_inferred: string | null
  currency_detected: string | null
  focus_tables: string[]
  known_findings: Record<string, any>
  resolved_findings: Record<string, any>
  baseline_history: Record<string, any[]>
  run_history: Array<{
    run_date: string
    period: string
    success: boolean
    findings_count: number
    new: number
    resolved: number
    dq_score?: number
  }>
  refinement: {
    focus_areas?: string[]
    query_hints?: string[]
  } | null
}

function StatCard({ icon: Icon, label, value, sub }: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.lg,
      border: T.border.card,
      padding: T.space.lg,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: T.space.sm }}>
        <div style={{
          padding: T.space.sm,
          borderRadius: T.radius.sm,
          backgroundColor: T.bg.elevated,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          <Icon style={{ width: 16, height: 16, color: T.accent.teal }} />
        </div>
        <div>
          <p style={{ fontSize: 11, color: T.text.tertiary, margin: '0 0 4px 0' }}>{label}</p>
          <p style={{ fontSize: 24, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.display }}>{value}</p>
          {sub && <p style={{ fontSize: 11, color: T.text.tertiary, margin: '2px 0 0 0' }}>{sub}</p>}
        </div>
      </div>
    </div>
  )
}

function DQDot({ score }: { score?: number }) {
  if (score === undefined || score === null) {
    return (
      <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.text.tertiary }} title="Sin dato de calidad">
        <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: T.bg.elevated, flexShrink: 0, display: 'inline-block' }} />
        <span>—</span>
      </span>
    )
  }
  const dotColor =
    score >= 90 ? T.accent.teal :
    score >= 75 ? T.accent.yellow :
    score >= 50 ? T.accent.orange :
    T.accent.red
  const textColor =
    score >= 90 ? T.accent.teal :
    score >= 75 ? T.accent.yellow :
    score >= 50 ? T.accent.orange :
    T.accent.red
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, fontWeight: 500, color: textColor }} title={`Calidad de datos: ${score}/100`}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0, backgroundColor: dotColor, display: 'inline-block' }} />
      <span>{score}</span>
    </span>
  )
}

function RunHistoryRow({ run, i }: { run: ClientProfileData['run_history'][0]; i: number }) {
  const date = new Date(run.run_date).toLocaleDateString('es', {
    day: 'numeric', month: 'short', year: 'numeric'
  })
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: i * 0.04 }}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: T.space.md,
        padding: `${T.space.sm} ${T.space.lg}`,
      }}
    >
      <span style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        flexShrink: 0,
        backgroundColor: run.success ? T.accent.teal : T.accent.red,
        display: 'inline-block',
      }} />
      <span style={{
        fontSize: 13,
        color: T.text.secondary,
        fontFamily: T.font.mono,
        width: 112,
        flexShrink: 0,
      }}>{run.period}</span>
      <span style={{ fontSize: 13, color: T.text.tertiary, flex: 1 }}>{date}</span>
      <span style={{ fontSize: 13, fontWeight: 500, color: T.text.primary }}>{run.findings_count} hallazgos</span>
      {run.new > 0 && (
        <span style={{
          fontSize: 11,
          color: T.accent.red,
          backgroundColor: T.bg.elevated,
          padding: '2px 8px',
          borderRadius: 999,
        }}>
          +{run.new} nuevo{run.new > 1 ? 's' : ''}
        </span>
      )}
      {run.resolved > 0 && (
        <span style={{
          fontSize: 11,
          color: T.accent.teal,
          backgroundColor: T.bg.elevated,
          padding: '2px 8px',
          borderRadius: 999,
        }}>
          -{run.resolved} resuelto{run.resolved > 1 ? 's' : ''}
        </span>
      )}
      <DQDot score={run.dq_score} />
    </motion.div>
  )
}

export default function ClientHistoryPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()
  const [profile, setProfile] = useState<ClientProfileData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dqHistory, setDqHistory] = useState<{dq_history: any[], avg_score: number|null, trend: string|null}>({
    dq_history: [], avg_score: null, trend: null
  })

  const fetchProfile = () => {
    setLoading(true)
    axios.get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Error cargando perfil'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchProfile() }, [clientId])

  useEffect(() => {
    fetch(`${API_URL}/api/clients/${clientId}/dq-history`)
      .then(r => r.json())
      .then(setDqHistory)
      .catch(() => {})
  }, [clientId])

  if (loading) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xl }}>
      <div style={{ maxWidth: 1152, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 192, animation: 'pulse 1.5s ease-in-out infinite' }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.md }}>
          {[...Array(4)].map((_, i) => (
            <div key={i} style={{ height: 96, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
          ))}
        </div>
        <div style={{ height: 192, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[...Array(8)].map((_, i) => (
            <div key={i} style={{ height: 112, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
          ))}
        </div>
      </div>
    </div>
  )

  if (error || !profile) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ color: T.text.secondary, marginBottom: T.space.md }}>{error || 'No hay datos para este cliente'}</p>
        <Link href="/" style={{ color: T.accent.teal, fontSize: 13, textDecoration: 'none' }}>← Volver</Link>
      </div>
    </div>
  )

  const kpiLabels = Object.keys(profile.baseline_history).slice(0, 8)
  const lastRun = profile.run_history[profile.run_history.length - 1]

  // DQ ring color
  const ringColor =
    dqHistory.avg_score !== null && dqHistory.avg_score >= 90 ? T.accent.teal :
    dqHistory.avg_score !== null && dqHistory.avg_score >= 75 ? T.accent.yellow :
    T.accent.orange

  const trendColor =
    dqHistory.trend === 'improving' ? T.accent.teal :
    dqHistory.trend === 'declining' ? T.accent.red :
    T.text.tertiary

  const sparkStrokeColor =
    dqHistory.avg_score !== null && dqHistory.avg_score >= 90 ? T.accent.teal :
    dqHistory.avg_score !== null && dqHistory.avg_score >= 75 ? T.accent.yellow : T.accent.orange

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Header */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        backgroundColor: T.bg.card,
        borderBottom: T.border.card,
      }}>
        <div style={{
          maxWidth: 1152,
          margin: '0 auto',
          padding: `${T.space.md} ${T.space.lg}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.md }}>
            <Link href="/" style={{ color: T.text.tertiary, display: 'flex', textDecoration: 'none' }}>
              <ArrowLeft style={{ width: 20, height: 20 }} />
            </Link>
            <div>
              <h1 style={{ fontSize: 17, fontWeight: 700, color: T.text.primary, margin: 0 }}>{profile.client_name}</h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
                {[profile.industry_inferred, profile.currency_detected].filter(Boolean).join(' · ')}
              </p>
            </div>
          </div>
          <button
            onClick={fetchProfile}
            className="d4c-btn-ghost"
            style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, fontSize: 13 }}
          >
            <RefreshCw style={{ width: 14, height: 14 }} />Actualizar
          </button>
        </div>
        {/* Tab navigation */}
        <div style={{ maxWidth: 1152, margin: '0 auto', padding: `0 ${T.space.lg}` }}>
          <nav style={{ display: 'flex', gap: 4, marginBottom: -1 }}>
            {[
              { label: 'Historial',     href: `/clients/${clientId}/history` },
              { label: 'Hallazgos',     href: `/clients/${clientId}/findings` },
              { label: 'Alertas',       href: `/clients/${clientId}/alerts` },
              { label: 'Costos',        href: `/clients/${clientId}/costs` },
              { label: 'KPIs',          href: `/clients/${clientId}/kpis` },
              { label: 'Segmentación',  href: `/clients/${clientId}/segmentation` },
              { label: 'Configuración', href: `/clients/${clientId}/settings` },
            ].map(tab => {
              const isActive = pathname === tab.href
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  style={isActive ? {
                    borderBottom: `2px solid ${T.accent.teal}`,
                    color: T.accent.teal,
                    padding: '10px 16px',
                    fontSize: 13,
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    textDecoration: 'none',
                    display: 'inline-block',
                  } : {
                    borderBottom: '2px solid transparent',
                    color: T.text.tertiary,
                    padding: '10px 16px',
                    fontSize: 13,
                    fontWeight: 500,
                    whiteSpace: 'nowrap',
                    textDecoration: 'none',
                    display: 'inline-block',
                  }}
                >
                  {tab.label}
                </Link>
              )
            })}
          </nav>
        </div>
      </header>

      <main style={{
        maxWidth: 1152,
        margin: '0 auto',
        padding: `${T.space.xl} ${T.space.lg}`,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.xl,
      }}>
        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.md }}>
          <StatCard icon={TrendingUp} label="Total Runs" value={profile.run_count} />
          <StatCard icon={AlertOctagon} label="Activos" value={Object.keys(profile.known_findings).length}
            sub="hallazgos abiertos" />
          <StatCard icon={Clock} label="Resueltos" value={Object.keys(profile.resolved_findings).length}
            sub="hallazgos cerrados" />
          <StatCard icon={Target} label="Tablas foco" value={profile.focus_tables.length}
            sub={profile.focus_tables.slice(0, 2).join(', ')} />
        </div>

        {/* DQ Trend section */}
        {dqHistory.dq_history.length > 0 && (
          <div>
            <h2 style={{
              fontSize: 10,
              fontWeight: 600,
              color: T.text.tertiary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 12,
            }}>
              Tendencia de Calidad de Datos
            </h2>
            <div style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.lg,
              border: T.border.card,
              padding: T.space.lg,
              display: 'flex',
              alignItems: 'center',
              gap: T.space.lg,
            }}>
              {/* Average score ring */}
              <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <div style={{
                  width: 56,
                  height: 56,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: `4px solid ${ringColor}`,
                  color: ringColor,
                }}>
                  <span style={{ fontSize: 13, fontWeight: 700 }}>{dqHistory.avg_score ?? '—'}</span>
                </div>
                <span style={{ fontSize: 11, color: T.text.tertiary }}>Promedio</span>
              </div>
              {/* Sparkline SVG */}
              <div style={{ flex: 1 }}>
                <svg viewBox={`0 0 ${dqHistory.dq_history.length * 24} 40`} style={{ width: '100%', height: 40 }} preserveAspectRatio="none">
                  {dqHistory.dq_history.length > 1 && (
                    <polyline
                      points={dqHistory.dq_history.map((d, i) => `${i * 24 + 12},${40 - (d.score / 100) * 36}`).join(' ')}
                      fill="none"
                      stroke={sparkStrokeColor}
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  )}
                  {dqHistory.dq_history.map((d, i) => (
                    <circle key={i} cx={i * 24 + 12} cy={40 - (d.score / 100) * 36} r="3"
                      fill={d.score >= 90 ? T.accent.teal : d.score >= 75 ? T.accent.yellow : T.accent.orange}
                    >
                      <title>{`${d.run_date?.slice(0, 10)}: ${d.score}`}</title>
                    </circle>
                  ))}
                </svg>
              </div>
              {/* Trend label */}
              <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <span style={{
                  fontSize: 13,
                  fontWeight: 600,
                  padding: '4px 12px',
                  borderRadius: 999,
                  backgroundColor: T.bg.elevated,
                  color: trendColor,
                }}>
                  {dqHistory.trend === 'improving' ? '↑ Mejorando' :
                   dqHistory.trend === 'declining' ? '↓ Bajando' :
                   dqHistory.trend === 'stable' ? '→ Estable' : '—'}
                </span>
                <span style={{ fontSize: 11, color: T.text.tertiary }}>{dqHistory.dq_history.length} runs</span>
              </div>
            </div>
          </div>
        )}

        {/* Last run delta */}
        {lastRun && (lastRun.new > 0 || lastRun.resolved > 0) && (
          <div>
            <h2 style={{
              fontSize: 10,
              fontWeight: 600,
              color: T.text.tertiary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 12,
            }}>
              Último Run · {lastRun.period}
            </h2>
            <DeltaPanel
              runDelta={{ new: [], resolved: [], persists: [], worsened: [], improved: [] }}
              knownFindings={profile.known_findings}
              runCount={profile.run_count}
            />
          </div>
        )}

        {/* KPI trends */}
        {kpiLabels.length > 0 && (
          <div>
            <h2 style={{
              fontSize: 10,
              fontWeight: 600,
              color: T.text.tertiary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: T.space.md,
            }}>
              Evolución de KPIs
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
              {kpiLabels.map(label => (
                <KPITrendChart
                  key={label}
                  label={label}
                  dataPoints={profile.baseline_history[label]}
                />
              ))}
            </div>
          </div>
        )}

        {/* Finding timeline */}
        {(Object.keys(profile.known_findings).length > 0 || Object.keys(profile.resolved_findings).length > 0) && (
          <div>
            <h2 style={{
              fontSize: 10,
              fontWeight: 600,
              color: T.text.tertiary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: T.space.md,
            }}>
              Historial de Hallazgos
            </h2>
            <FindingTimeline
              active={profile.known_findings}
              resolved={profile.resolved_findings}
            />
          </div>
        )}

        {/* Run history table */}
        {profile.run_history.length > 0 && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.md }}>
              <h2 style={{
                fontSize: 10,
                fontWeight: 600,
                color: T.text.tertiary,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                margin: 0,
              }}>
                Historial de Runs
              </h2>
              <a href={`/clients/${clientId}/compare`} style={{ fontSize: 12, color: T.accent.teal, textDecoration: 'none' }}>Comparar runs →</a>
            </div>
            <div style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.lg,
              border: T.border.card,
              overflow: 'hidden',
            }}>
              {/* Column headers */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: T.space.md,
                padding: `${T.space.sm} ${T.space.lg}`,
                borderBottom: T.border.subtle,
                backgroundColor: T.bg.elevated,
              }}>
                <span style={{ width: 8, flexShrink: 0 }} />
                <span style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', width: 112, flexShrink: 0 }}>Período</span>
                <span style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', flex: 1 }}>Fecha</span>
                <span style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Hallazgos</span>
                <span style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', width: 64, textAlign: 'right' }}>Cal. Datos</span>
              </div>
              <div>
                {[...profile.run_history].reverse().map((run, i) => (
                  <div key={i} style={{ borderTop: i > 0 ? T.border.subtle : 'none' }}>
                    <RunHistoryRow run={run} i={i} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Focus areas from refinement */}
        {profile.refinement?.focus_areas?.length ? (
          <div>
            <h2 style={{
              fontSize: 10,
              fontWeight: 600,
              color: T.text.tertiary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 12,
            }}>
              Áreas de Foco (Auto-Refinement)
            </h2>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: T.space.sm }}>
              {profile.refinement.focus_areas.map(area => (
                <span key={area} style={{
                  padding: '6px 12px',
                  backgroundColor: T.bg.elevated,
                  color: T.accent.teal,
                  fontSize: 13,
                  fontWeight: 500,
                  borderRadius: 999,
                  border: `1px solid ${T.accent.teal}40`,
                }}>
                  {area}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </main>
    </div>
  )
}
