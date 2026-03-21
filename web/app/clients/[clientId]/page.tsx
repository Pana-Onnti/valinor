'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import {
  ArrowLeft, RefreshCw, TrendingUp, AlertOctagon, PlayCircle,
  History, Bell, BarChart2, ShieldAlert, CheckCircle2
} from 'lucide-react'
import Link from 'next/link'
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

interface DQHistory {
  dq_history: Array<{ run_date: string; score: number }>
  avg_score: number | null
  trend: string | null
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  accent?: 'violet' | 'emerald' | 'amber' | 'red'
}) {
  const accentColor: Record<string, string> = {
    violet: T.accent.teal,
    emerald: T.accent.teal,
    amber: T.accent.yellow,
    red: T.accent.red,
  }
  const iconColor = accentColor[accent ?? 'violet']
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
          color: iconColor,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          <Icon style={{ width: 16, height: 16, color: iconColor }} />
        </div>
        <div>
          <p style={{ fontSize: 11, color: T.text.tertiary, marginBottom: 4 }}>{label}</p>
          <p style={{ fontSize: 24, fontWeight: 700, color: T.text.primary, fontFamily: T.font.display }}>{value}</p>
          {sub && <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2 }}>{sub}</p>}
        </div>
      </div>
    </div>
  )
}

function SeverityBadge({ severity }: { severity: string }) {
  const colorMap: Record<string, string> = {
    critical: T.accent.red,
    high: T.accent.orange,
    medium: T.accent.yellow,
    low: T.accent.blue,
  }
  const color = colorMap[severity] ?? T.accent.blue
  return (
    <span style={{
      fontSize: 10,
      fontWeight: 600,
      padding: '2px 8px',
      borderRadius: 999,
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
      color: T.text.inverse,
      backgroundColor: color,
      whiteSpace: 'nowrap',
    }}>
      {severity}
    </span>
  )
}

function FindingCard({ id, finding, idx }: { id: string; finding: any; idx: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: idx * 0.06 }}
      style={{
        backgroundColor: T.bg.card,
        borderRadius: T.radius.lg,
        border: T.border.card,
        padding: T.space.md,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.sm,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: T.space.sm }}>
        <p style={{
          fontSize: 13,
          fontWeight: 600,
          color: T.text.primary,
          lineHeight: 1.4,
          overflow: 'hidden',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
        }}>
          {finding.title ?? id}
        </p>
        <SeverityBadge severity={finding.severity ?? 'low'} />
      </div>
      {finding.description && (
        <p style={{
          fontSize: 12,
          color: T.text.secondary,
          overflow: 'hidden',
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
        }}>{finding.description}</p>
      )}
      {finding.affected_table && (
        <p style={{
          fontSize: 12,
          fontFamily: T.font.mono,
          color: T.accent.teal,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}>{finding.affected_table}</p>
      )}
      {finding.first_seen && (
        <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 'auto' }}>
          Detectado: {new Date(finding.first_seen).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' })}
        </p>
      )}
    </motion.div>
  )
}

function DQSparkline({ dqHistory }: { dqHistory: DQHistory }) {
  const { dq_history, avg_score, trend } = dqHistory
  if (!dq_history.length) return null

  const strokeColor =
    avg_score !== null && avg_score >= 90 ? T.accent.teal :
    avg_score !== null && avg_score >= 75 ? T.accent.yellow : T.accent.orange

  const ringColor =
    avg_score !== null && avg_score >= 90 ? T.accent.teal :
    avg_score !== null && avg_score >= 75 ? T.accent.yellow : T.accent.orange

  const trendLabel =
    trend === 'improving' ? '↑ Mejorando' :
    trend === 'declining' ? '↓ Bajando' :
    trend === 'stable' ? '→ Estable' : '—'

  const trendColor =
    trend === 'improving' ? T.accent.teal :
    trend === 'declining' ? T.accent.red :
    T.text.tertiary

  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.lg,
      border: T.border.card,
      padding: T.space.lg,
      display: 'flex',
      alignItems: 'center',
      gap: T.space.lg,
    }}>
      {/* Average ring */}
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
          <span style={{ fontSize: 13, fontWeight: 700 }}>{avg_score ?? '—'}</span>
        </div>
        <span style={{ fontSize: 11, color: T.text.tertiary }}>Promedio</span>
      </div>

      {/* Sparkline */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <svg
          viewBox={`0 0 ${dq_history.length * 24} 40`}
          style={{ width: '100%', height: 40 }}
          preserveAspectRatio="none"
        >
          {dq_history.length > 1 && (
            <polyline
              points={dq_history.map((d, i) => `${i * 24 + 12},${40 - (d.score / 100) * 36}`).join(' ')}
              fill="none"
              stroke={strokeColor}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}
          {dq_history.map((d, i) => (
            <circle
              key={i}
              cx={i * 24 + 12}
              cy={40 - (d.score / 100) * 36}
              r="3"
              fill={d.score >= 90 ? T.accent.teal : d.score >= 75 ? T.accent.yellow : T.accent.orange}
            >
              <title>{`${d.run_date?.slice(0, 10)}: ${d.score}`}</title>
            </circle>
          ))}
        </svg>
      </div>

      {/* Trend pill + count */}
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
        <span style={{
          fontSize: 13,
          fontWeight: 600,
          padding: '4px 12px',
          borderRadius: 999,
          backgroundColor: T.bg.elevated,
          color: trendColor,
        }}>
          {trendLabel}
        </span>
        <span style={{ fontSize: 11, color: T.text.tertiary }}>{dq_history.length} runs</span>
      </div>
    </div>
  )
}

function RunRow({ run, i }: { run: ClientProfileData['run_history'][0]; i: number }) {
  const date = new Date(run.run_date).toLocaleDateString('es', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
  const scoreColor =
    run.dq_score === undefined || run.dq_score === null ? T.text.tertiary :
    run.dq_score >= 90 ? T.accent.teal :
    run.dq_score >= 75 ? T.accent.yellow :
    T.accent.red

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: i * 0.05 }}
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
      {run.dq_score !== undefined && run.dq_score !== null && (
        <span style={{ fontSize: 11, fontWeight: 600, color: scoreColor }}>{run.dq_score}</span>
      )}
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

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
    <nav style={{ display: 'flex', gap: 4, overflowX: 'auto', marginBottom: -1 }}>
      {tabs.map(tab => {
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
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ClientOverviewPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  const [profile, setProfile] = useState<ClientProfileData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dqHistory, setDqHistory] = useState<DQHistory>({ dq_history: [], avg_score: null, trend: null })

  const fetchProfile = () => {
    setLoading(true)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
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

  // ----- Loading skeleton -----
  if (loading) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xl }}>
      <div style={{ maxWidth: 1152, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 256, animation: 'pulse 1.5s ease-in-out infinite' }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: T.space.md }}>
          {[...Array(3)].map((_, i) => (
            <div key={i} style={{ height: 96, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
          ))}
        </div>
        <div style={{ height: 64, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: T.space.md }}>
          {[...Array(3)].map((_, i) => (
            <div key={i} style={{ height: 128, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
          ))}
        </div>
        <div style={{ height: 160, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
        <div style={{ height: 160, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, animation: 'pulse 1.5s ease-in-out infinite' }} />
      </div>
    </div>
  )

  // ----- Error state -----
  if (error || !profile) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ color: T.text.secondary, marginBottom: T.space.md }}>{error || 'No hay datos para este cliente'}</p>
        <Link href="/" style={{ color: T.accent.teal, fontSize: 13, textDecoration: 'none' }}>← Volver</Link>
      </div>
    </div>
  )

  // Derived data
  const latestDQScore = (() => {
    if (dqHistory.dq_history.length > 0) {
      return dqHistory.dq_history[dqHistory.dq_history.length - 1].score
    }
    const lastRunWithScore = [...profile.run_history].reverse().find(r => r.dq_score !== undefined)
    return lastRunWithScore?.dq_score ?? null
  })()

  const totalFindings = Object.keys(profile.known_findings).length + Object.keys(profile.resolved_findings).length

  const criticalHighFindings = Object.entries(profile.known_findings)
    .filter(([, f]) => f.severity === 'critical' || f.severity === 'high')
    .sort(([, a], [, b]) => {
      const order: Record<string, number> = { critical: 0, high: 1 }
      return (order[a.severity] ?? 2) - (order[b.severity] ?? 2)
    })
    .slice(0, 3)

  const lastThreeRuns = [...profile.run_history].reverse().slice(0, 3)

  // DQ score card colors
  const dqBgColor =
    latestDQScore === null ? T.bg.card :
    latestDQScore >= 90 ? T.bg.elevated :
    latestDQScore >= 75 ? T.bg.elevated :
    T.bg.elevated

  const dqTextColor =
    latestDQScore === null ? T.text.tertiary :
    latestDQScore >= 90 ? T.accent.teal :
    latestDQScore >= 75 ? T.accent.yellow :
    T.accent.orange

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* ------------------------------------------------------------------ */}
      {/* Header                                                               */}
      {/* ------------------------------------------------------------------ */}
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
            <Link
              href="/"
              style={{ color: T.text.tertiary, display: 'flex', textDecoration: 'none' }}
            >
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
            <RefreshCw style={{ width: 14, height: 14 }} />
            Actualizar
          </button>
        </div>
        <div style={{ maxWidth: 1152, margin: '0 auto', padding: `0 ${T.space.lg}` }}>
          <TabNav clientId={clientId} pathname={pathname} />
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

        {/* ---------------------------------------------------------------- */}
        {/* Hero — client name + subtitle                                     */}
        {/* ---------------------------------------------------------------- */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
        >
          <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, margin: 0 }}>
            Bienvenido a {profile.client_name}
          </h2>
          <p style={{ fontSize: 13, color: T.text.secondary, margin: 0 }}>
            Vista general del estado de inteligencia de negocio para este cliente.
            {profile.last_run_date && (
              <> Último análisis: <span style={{ fontWeight: 500 }}>{new Date(profile.last_run_date).toLocaleDateString('es', { day: 'numeric', month: 'long', year: 'numeric' })}</span>.</>
            )}
          </p>
        </motion.div>

        {/* ---------------------------------------------------------------- */}
        {/* Quick stats row                                                   */}
        {/* ---------------------------------------------------------------- */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {/* Total findings */}
          <Link
            href={`/clients/${clientId}/findings`}
            style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.lg,
              border: T.border.card,
              padding: `${T.space.md} ${T.space.lg}`,
              textDecoration: 'none',
              display: 'block',
            }}
          >
            <p style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4, margin: '0 0 4px 0' }}>Total Hallazgos</p>
            <p style={{ fontSize: 24, fontWeight: 700, color: T.text.primary, margin: '0 0 2px 0', fontVariantNumeric: 'tabular-nums' }}>
              {totalFindings}
            </p>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
              {Object.keys(profile.known_findings).length} activos
            </p>
          </Link>

          {/* Critical count */}
          <Link
            href={`/clients/${clientId}/findings`}
            style={{
              backgroundColor: T.bg.elevated,
              borderRadius: T.radius.lg,
              border: `1px solid ${T.accent.red}40`,
              padding: `${T.space.md} ${T.space.lg}`,
              textDecoration: 'none',
              display: 'block',
            }}
          >
            <p style={{ fontSize: 10, fontWeight: 600, color: T.accent.red, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 4px 0' }}>Críticos</p>
            <p style={{ fontSize: 24, fontWeight: 700, color: T.accent.red, margin: '0 0 2px 0', fontVariantNumeric: 'tabular-nums' }}>
              {Object.values(profile.known_findings).filter((f: any) => f.severity === 'critical').length}
            </p>
            <p style={{ fontSize: 11, color: T.accent.red, opacity: 0.7, margin: 0 }}>Requieren atención</p>
          </Link>

          {/* DQ score */}
          <div style={{
            backgroundColor: dqBgColor,
            borderRadius: T.radius.lg,
            border: `1px solid ${dqTextColor}40`,
            padding: `${T.space.md} ${T.space.lg}`,
          }}>
            <p style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 4px 0' }}>Score DQ</p>
            <p style={{ fontSize: 24, fontWeight: 700, color: dqTextColor, margin: '0 0 2px 0', fontVariantNumeric: 'tabular-nums' }}>
              {latestDQScore !== null ? latestDQScore : '—'}
            </p>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
              {latestDQScore === null ? 'Sin datos' : latestDQScore >= 90 ? 'Excelente' : latestDQScore >= 75 ? 'Aceptable' : 'Revisar'}
            </p>
          </div>

          {/* Last run date */}
          <div style={{
            backgroundColor: T.bg.card,
            borderRadius: T.radius.lg,
            border: T.border.card,
            padding: `${T.space.md} ${T.space.lg}`,
          }}>
            <p style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 4px 0' }}>Último Run</p>
            <p style={{ fontSize: 14, fontWeight: 700, color: T.text.primary, lineHeight: 1.3, margin: '0 0 2px 0' }}>
              {profile.last_run_date
                ? new Date(profile.last_run_date).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' })
                : '—'}
            </p>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>{profile.run_count} run{profile.run_count !== 1 ? 's' : ''} totales</p>
          </div>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Quick action buttons                                              */}
        {/* ---------------------------------------------------------------- */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          <Link
            href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
            className="d4c-btn-primary"
            style={{ display: 'inline-flex', alignItems: 'center', gap: T.space.sm, textDecoration: 'none' }}
          >
            <PlayCircle style={{ width: 16, height: 16 }} />
            Ejecutar análisis
          </Link>
          <Link
            href={`/clients/${clientId}/history`}
            className="d4c-btn-ghost"
            style={{ display: 'inline-flex', alignItems: 'center', gap: T.space.sm, textDecoration: 'none' }}
          >
            <History style={{ width: 16, height: 16 }} />
            Ver historial
          </Link>
          <Link
            href={`/clients/${clientId}/alerts`}
            className="d4c-btn-ghost"
            style={{ display: 'inline-flex', alignItems: 'center', gap: T.space.sm, textDecoration: 'none' }}
          >
            <Bell style={{ width: 16, height: 16 }} />
            Ver alertas
          </Link>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Stat cards: DQ trend / total findings / total runs               */}
        {/* ---------------------------------------------------------------- */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: T.space.md }}>
          <StatCard
            icon={BarChart2}
            label="Último Score DQ"
            value={latestDQScore !== null ? latestDQScore : '—'}
            sub={latestDQScore !== null
              ? latestDQScore >= 90 ? 'Excelente calidad'
              : latestDQScore >= 75 ? 'Calidad aceptable'
              : 'Requiere atención'
              : 'Sin datos aún'}
            accent={
              latestDQScore === null ? 'violet' :
              latestDQScore >= 90 ? 'emerald' :
              latestDQScore >= 75 ? 'amber' : 'red'
            }
          />
          <StatCard
            icon={AlertOctagon}
            label="Total Hallazgos"
            value={totalFindings}
            sub={`${Object.keys(profile.known_findings).length} activos · ${Object.keys(profile.resolved_findings).length} resueltos`}
            accent="amber"
          />
          <StatCard
            icon={TrendingUp}
            label="Total Runs"
            value={profile.run_count}
            sub={profile.last_run_date
              ? `Último: ${new Date(profile.last_run_date).toLocaleDateString('es', { day: 'numeric', month: 'short' })}`
              : 'Sin runs aún'}
            accent="violet"
          />
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* DQ history sparkline                                              */}
        {/* ---------------------------------------------------------------- */}
        {dqHistory.dq_history.length > 0 && (
          <div>
            <h3 style={{
              fontSize: 10,
              fontWeight: 600,
              color: T.text.tertiary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: 12,
            }}>
              Tendencia de Calidad de Datos
            </h3>
            <DQSparkline dqHistory={dqHistory} />
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* 3 most recent critical/high findings                              */}
        {/* ---------------------------------------------------------------- */}
        {criticalHighFindings.length > 0 && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h3 style={{
                fontSize: 10,
                fontWeight: 600,
                color: T.text.tertiary,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                display: 'flex',
                alignItems: 'center',
                gap: T.space.sm,
                margin: 0,
              }}>
                <ShieldAlert style={{ width: 14, height: 14, color: T.accent.red }} />
                Hallazgos Críticos / Altos
              </h3>
              <Link
                href={`/clients/${clientId}/findings`}
                style={{ fontSize: 12, color: T.accent.teal, textDecoration: 'none' }}
              >
                Ver todos →
              </Link>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: T.space.md }}>
              {criticalHighFindings.map(([id, finding], idx) => (
                <FindingCard key={id} id={id} finding={finding} idx={idx} />
              ))}
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Last 3 runs                                                       */}
        {/* ---------------------------------------------------------------- */}
        {lastThreeRuns.length > 0 && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <h3 style={{
                fontSize: 10,
                fontWeight: 600,
                color: T.text.tertiary,
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                display: 'flex',
                alignItems: 'center',
                gap: T.space.sm,
                margin: 0,
              }}>
                <CheckCircle2 style={{ width: 14, height: 14, color: T.accent.teal }} />
                Runs Recientes
              </h3>
              <Link
                href={`/clients/${clientId}/history`}
                style={{ fontSize: 12, color: T.accent.teal, textDecoration: 'none' }}
              >
                Ver historial completo →
              </Link>
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
                <span style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Cal. Datos</span>
              </div>
              <div style={{ borderTop: T.border.subtle }}>
                {lastThreeRuns.map((run, i) => (
                  <div key={i} style={{ borderBottom: i < lastThreeRuns.length - 1 ? T.border.subtle : 'none' }}>
                    <RunRow run={run} i={i} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ---------------------------------------------------------------- */}
        {/* Empty state when there is no data yet                             */}
        {/* ---------------------------------------------------------------- */}
        {profile.run_count === 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.lg,
              border: `1px dashed ${T.text.tertiary}`,
              padding: T.space.xxl,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: T.space.md,
              textAlign: 'center',
            }}
          >
            <div style={{
              padding: T.space.md,
              borderRadius: T.radius.lg,
              backgroundColor: T.bg.elevated,
              color: T.accent.teal,
              display: 'flex',
            }}>
              <PlayCircle style={{ width: 32, height: 32, color: T.accent.teal }} />
            </div>
            <div>
              <p style={{ fontWeight: 600, color: T.text.primary, margin: '0 0 4px 0' }}>Sin análisis todavía</p>
              <p style={{ fontSize: 13, color: T.text.secondary, margin: 0 }}>
                Lanza el primer análisis para empezar a ver datos de inteligencia de negocio para {profile.client_name}.
              </p>
            </div>
            <Link
              href={`/new-analysis?client=${encodeURIComponent(clientId)}`}
              className="d4c-btn-primary"
              style={{ display: 'inline-flex', alignItems: 'center', gap: T.space.sm, textDecoration: 'none' }}
            >
              <PlayCircle style={{ width: 16, height: 16 }} />
              Ejecutar análisis
            </Link>
          </motion.div>
        )}

      </main>
    </div>
  )
}
