'use client'

import { useEffect, useState, useMemo } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useClientProfile } from '@/lib/hooks'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'

interface Finding {
  id: string
  title: string
  description?: string
  severity: Severity
  agent: string
  first_seen: string
  runs_open: number
  status: 'active' | 'resolved' | 'false_positive'
  auto_escalated?: boolean
}

interface FindingsData {
  client_name: string
  findings: Finding[]
}

type FilterValue = 'ALL' | Severity

// ── Constants ─────────────────────────────────────────────────────────────────

const SEVERITY_ORDER: Record<Severity, number> = {
  CRITICAL: 0,
  HIGH: 1,
  MEDIUM: 2,
  LOW: 3,
}

const FILTER_OPTIONS: { value: FilterValue; label: string }[] = [
  { value: 'ALL',      label: 'Todos' },
  { value: 'CRITICAL', label: 'CRITICAL' },
  { value: 'HIGH',     label: 'HIGH' },
  { value: 'MEDIUM',   label: 'MEDIUM' },
  { value: 'LOW',      label: 'LOW' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function getSevColor(severity: Severity | string): string {
  const map: Record<string, string> = {
    CRITICAL: T.accent.red,
    HIGH: T.accent.orange,
    MEDIUM: T.accent.yellow,
    LOW: T.accent.blue,
  }
  return map[severity] ?? T.text.tertiary
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function agentLabel(agent: string) {
  const map: Record<string, string> = {
    analyst: 'Analyst',
    sentinel: 'Sentinel',
    hunter: 'Hunter',
  }
  return map[agent.toLowerCase()] ?? agent
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: Severity }) {
  const color = getSevColor(severity)
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 8px',
      borderRadius: '9999px',
      fontSize: 11,
      fontWeight: 600,
      backgroundColor: color + '15',
      border: `1px solid ${color}40`,
      color,
    }}>
      {severity}
    </span>
  )
}

function AgentChip({ agent }: { agent: string }) {
  const key = agent.toLowerCase()
  const agentColors: Record<string, string> = {
    analyst:  T.accent.teal,
    sentinel: T.accent.blue,
    hunter:   T.accent.orange,
  }
  const color = agentColors[key] ?? T.text.tertiary
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 8px',
      borderRadius: '9999px',
      fontSize: 11,
      fontWeight: 500,
      backgroundColor: color + '15',
      border: `1px solid ${color}40`,
      color,
    }}>
      {agentLabel(agent)}
    </span>
  )
}

// ── Summary bar ───────────────────────────────────────────────────────────────

function SummaryBar({ findings }: { findings: Finding[] }) {
  const active   = findings.filter(f => f.status === 'active').length
  const critical = findings.filter(f => f.status === 'active' && f.severity === 'CRITICAL').length
  const high     = findings.filter(f => f.status === 'active' && f.severity === 'HIGH').length
  const resolved = findings.filter(f => f.status === 'resolved').length

  const stats = [
    { label: 'Activos',   value: active,   color: T.text.primary,    accentColor: T.text.secondary },
    { label: 'Críticos',  value: critical,  color: T.accent.red,      accentColor: T.accent.red },
    { label: 'Altos',     value: high,      color: T.accent.orange,   accentColor: T.accent.orange },
    { label: 'Resueltos', value: resolved,  color: T.accent.teal,     accentColor: T.accent.teal },
  ]

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.md }}>
      {stats.map(s => (
        <div key={s.label} style={{
          backgroundColor: T.bg.card,
          border: T.border.card,
          borderRadius: T.radius.lg,
          padding: `${T.space.lg} ${T.space.xl}`,
        }}>
          <p style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }}>
            {s.label}
          </p>
          <p style={{ fontSize: 24, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: s.color }}>
            {s.value}
          </p>
        </div>
      ))}
    </div>
  )
}

// ── Severity filter tabs ───────────────────────────────────────────────────────

function SeverityTabs({
  filter,
  onChange,
  counts,
}: {
  filter: FilterValue
  onChange: (v: FilterValue) => void
  counts: Record<FilterValue, number>
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, flexWrap: 'wrap' }}>
      {FILTER_OPTIONS.map(opt => {
        const isActive = filter === opt.value
        const color = opt.value === 'ALL' ? T.accent.teal : getSevColor(opt.value as Severity)
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 14px',
              borderRadius: T.radius.md,
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.15s',
              backgroundColor: isActive ? color + '20' : T.bg.card,
              border: isActive ? `1px solid ${color}60` : T.border.card,
              color: isActive ? color : T.text.tertiary,
            }}
          >
            {opt.label}
            <span style={{
              fontSize: 11,
              fontWeight: 700,
              fontVariantNumeric: 'tabular-nums',
              padding: '1px 6px',
              borderRadius: '9999px',
              minWidth: 20,
              textAlign: 'center',
              backgroundColor: isActive ? color + '25' : T.bg.elevated,
              color: isActive ? color : T.text.tertiary,
            }}>
              {counts[opt.value]}
            </span>
          </button>
        )
      })}
    </div>
  )
}

// ── Finding card ──────────────────────────────────────────────────────────────

interface FindingCardProps {
  finding: Finding
  clientId: string
  onMarkFalsePositive: (id: string) => void
  marking: boolean
}

function FindingCard({ finding, clientId, onMarkFalsePositive, marking }: FindingCardProps) {
  const sevColor = getSevColor(finding.severity)

  // Truncate finding ID to 8 chars for display
  const shortId = finding.id.length > 8 ? finding.id.slice(0, 8) : finding.id

  const runsColor = finding.runs_open >= 5
    ? T.accent.red
    : finding.runs_open >= 3
    ? T.accent.orange
    : T.text.tertiary

  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.lg,
      border: T.border.card,
      borderLeft: `3px solid ${sevColor}`,
      padding: `${T.space.lg} ${T.space.xl}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: T.space.lg }}>
        {/* Left: content */}
        <div style={{ flex: 1, minWidth: 0 }}>

          {/* Badges row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, flexWrap: 'wrap', marginBottom: T.space.sm }}>
            <SeverityBadge severity={finding.severity} />
            <AgentChip agent={finding.agent} />
            {finding.auto_escalated && (
              <span style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 8px',
                borderRadius: '9999px',
                fontSize: 11,
                fontWeight: 600,
                backgroundColor: T.accent.yellow + '15',
                border: `1px solid ${T.accent.yellow}40`,
                color: T.accent.yellow,
              }}>
                <svg style={{ height: 12, width: 12 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18" />
                </svg>
                Escalado
              </span>
            )}
          </div>

          {/* Title */}
          <p style={{ fontSize: 13, fontWeight: 700, color: T.text.primary, lineHeight: 1.4, marginBottom: T.space.sm }}>
            {finding.title}
          </p>

          {/* Description */}
          {finding.description && (
            <p style={{ fontSize: 12, color: T.text.secondary, lineHeight: 1.6, marginBottom: T.space.sm, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
              {finding.description}
            </p>
          )}

          {/* Meta row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg, flexWrap: 'wrap' }}>
            {/* Finding ID */}
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, fontFamily: T.font.mono, color: T.text.tertiary }}>
              <svg style={{ height: 12, width: 12 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 8.25h15m-16.5 7.5h15m-1.8-13.5l-3.9 19.5m-2.1-19.5l-3.9 19.5" />
              </svg>
              <span style={{ userSelect: 'all' }}>{shortId}</span>
            </span>

            {/* First seen */}
            <span style={{ fontSize: 11, color: T.text.tertiary }}>
              Detectado:{' '}
              <span style={{ color: T.text.secondary, fontWeight: 500 }}>
                {formatDate(finding.first_seen)}
              </span>
            </span>

            {/* Runs open badge */}
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <span style={{ fontWeight: 500, color: T.text.tertiary }}>Runs abierto:</span>
              <span style={{
                fontVariantNumeric: 'tabular-nums',
                fontWeight: 700,
                padding: '1px 6px',
                borderRadius: '9999px',
                fontSize: 11,
                backgroundColor: runsColor + '15',
                border: `1px solid ${runsColor}40`,
                color: runsColor,
              }}>
                {finding.runs_open}
              </span>
            </span>
          </div>
        </div>

        {/* Right: action */}
        {finding.status === 'active' && (
          <button
            onClick={() => onMarkFalsePositive(finding.id)}
            disabled={marking}
            style={{
              flexShrink: 0,
              padding: '6px 12px',
              fontSize: 12,
              fontWeight: 500,
              color: T.text.tertiary,
              backgroundColor: 'transparent',
              border: T.border.card,
              borderRadius: T.radius.md,
              cursor: marking ? 'not-allowed' : 'pointer',
              opacity: marking ? 0.4 : 1,
              whiteSpace: 'nowrap',
              transition: 'all 0.15s',
            }}
          >
            {marking ? (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 12, height: 12, border: `2px solid ${T.text.tertiary}`, borderTopColor: T.text.secondary, borderRadius: '50%', animation: 'spin 0.8s linear infinite', display: 'inline-block' }} />
                Guardando…
              </span>
            ) : (
              'Falso positivo'
            )}
          </button>
        )}

        {finding.status === 'false_positive' && (
          <span style={{
            flexShrink: 0,
            display: 'inline-flex',
            alignItems: 'center',
            padding: '4px 10px',
            borderRadius: T.radius.md,
            fontSize: 12,
            fontWeight: 500,
            backgroundColor: T.bg.elevated,
            color: T.text.tertiary,
          }}>
            Falso positivo
          </span>
        )}
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ severity }: { severity: FilterValue }) {
  const msgs: Record<FilterValue, { title: string; sub?: string }> = {
    ALL:      { title: 'No hay hallazgos activos.',      sub: 'Los hallazgos aparecerán tras ejecutar un análisis.' },
    CRITICAL: { title: 'No hay hallazgos CRITICAL.',     sub: 'Este cliente no presenta hallazgos de severidad crítica.' },
    HIGH:     { title: 'No hay hallazgos HIGH.',         sub: 'No se detectaron hallazgos de severidad alta.' },
    MEDIUM:   { title: 'No hay hallazgos MEDIUM.',       sub: 'No se detectaron hallazgos de severidad media.' },
    LOW:      { title: 'No hay hallazgos LOW.',          sub: 'No se detectaron hallazgos de severidad baja.' },
  }
  const { title, sub } = msgs[severity]
  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.lg,
      border: T.border.card,
      padding: '56px 24px',
      textAlign: 'center',
    }}>
      <div style={{
        margin: '0 auto 16px',
        width: 48,
        height: 48,
        borderRadius: '50%',
        backgroundColor: T.bg.elevated,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <svg style={{ width: 24, height: 24, color: T.text.tertiary }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <p style={{ fontSize: 13, fontWeight: 500, color: T.text.secondary }}>{title}</p>
      {sub && <p style={{ fontSize: 12, color: T.text.tertiary, marginTop: 4 }}>{sub}</p>}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ClientFindingsPage() {
  const params   = useParams()
  const clientId = params.clientId as string

  // Client profile via hook (used for header context: industry, last run)
  const { data: profile } = useClientProfile(clientId)

  const [data,      setData]      = useState<FindingsData | null>(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState<string | null>(null)
  const [filter,    setFilter]    = useState<FilterValue>('ALL')
  const [markingId, setMarkingId] = useState<string | null>(null)
  const [toastMsg,  setToastMsg]  = useState<string | null>(null)

  const fetchFindings = () => {
    setLoading(true)
    setError(null)
    fetch(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/findings`)
      .then(async res => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body?.detail || `Error ${res.status}`)
        }
        return res.json()
      })
      .then((d: FindingsData) => setData(d))
      .catch(err => setError(err.message || 'Error cargando hallazgos'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchFindings() }, [clientId])

  const showToast = (msg: string) => {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(null), 3500)
  }

  const handleMarkFalsePositive = async (findingId: string) => {
    setMarkingId(findingId)
    try {
      const res = await fetch(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile/false-positive?finding_id=${encodeURIComponent(findingId)}`,
        { method: 'PUT' }
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || `Error ${res.status}`)
      }
      setData(prev =>
        prev
          ? { ...prev, findings: prev.findings.map(f => f.id === findingId ? { ...f, status: 'false_positive' } : f) }
          : prev
      )
      showToast('Hallazgo marcado como falso positivo.')
    } catch (err: any) {
      setError(err.message || 'Error al actualizar el hallazgo')
    } finally {
      setMarkingId(null)
    }
  }

  // ── Derived data ────────────────────────────────────────────────────────────

  const allFindings = data?.findings ?? []

  // Sort by severity (CRITICAL first) then by runs_open desc
  const sortedFindings = useMemo(() =>
    [...allFindings].sort((a, b) => {
      const sev = SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
      return sev !== 0 ? sev : b.runs_open - a.runs_open
    }),
    [allFindings]
  )

  const filteredFindings = filter === 'ALL'
    ? sortedFindings
    : sortedFindings.filter(f => f.severity === filter)

  // Per-tab counts
  const counts = useMemo(() => {
    const base: Record<FilterValue, number> = { ALL: allFindings.length, CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }
    allFindings.forEach(f => { base[f.severity] = (base[f.severity] ?? 0) + 1 })
    return base
  }, [allFindings])

  // ── Render states ──────────────────────────────────────────────────────────

  if (loading) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xxl }}>
      <div style={{ maxWidth: 896, margin: '0 auto' }} className="animate-pulse">
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 192, marginBottom: T.space.xl }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.md, marginBottom: T.space.xl }}>
          {[...Array(4)].map((_, i) => (
            <div key={i} style={{ height: 96, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
          ))}
        </div>
        <div style={{ height: 40, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 320, marginBottom: T.space.xl }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>
          {[...Array(3)].map((_, i) => (
            <div key={i} style={{ height: 112, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
          ))}
        </div>
      </div>
    </div>
  )

  if (error && !data) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <svg style={{ height: 40, width: 40, color: T.accent.red, margin: '0 auto 12px' }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
        </svg>
        <p style={{ color: T.text.secondary, marginBottom: T.space.lg }}>{error}</p>
        <Link href={`/clients/${clientId}`} style={{ color: T.accent.teal, textDecoration: 'none', fontSize: 13 }}>
          ← Volver
        </Link>
      </div>
    </div>
  )

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Header */}
      <header style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 896, margin: '0 auto', padding: `${T.space.lg} ${T.space.xl}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}>
            <Link
              href={`/clients/${clientId}`}
              style={{ color: T.text.tertiary, lineHeight: 0 }}
            >
              <svg style={{ height: 20, width: 20 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
              </svg>
            </Link>
            <div>
              <h1 style={{ fontSize: 16, fontWeight: 700, color: T.text.primary, display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
                <svg style={{ height: 16, width: 16, color: T.accent.teal }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
                Hallazgos · {(profile?.client_name ?? clientId).replace(/_/g, ' ')}
              </h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: '2px 0 0' }}>
                {allFindings.length} hallazgo{allFindings.length !== 1 ? 's' : ''} en total
                {profile?.industry_inferred && (
                  <> · <span style={{ fontWeight: 500 }}>{profile.industry_inferred}</span></>
                )}
              </p>
            </div>
          </div>

          <button
            onClick={fetchFindings}
            className="d4c-btn-ghost"
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
          >
            <svg style={{ height: 14, width: 14 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Actualizar
          </button>
        </div>
      </header>

      <main style={{ maxWidth: 896, margin: '0 auto', padding: `${T.space.xxl} ${T.space.xl}`, display: 'flex', flexDirection: 'column', gap: T.space.xxl }}>

        {/* Toast notification */}
        {toastMsg && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: T.space.sm,
            padding: `${T.space.md} ${T.space.lg}`,
            backgroundColor: T.accent.teal + '15',
            border: `1px solid ${T.accent.teal}40`,
            borderRadius: T.radius.lg,
            color: T.accent.teal,
            fontSize: 13,
          }}>
            <svg style={{ height: 16, width: 16, flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {toastMsg}
          </div>
        )}

        {/* Error banner (non-fatal) */}
        {error && data && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: T.space.sm,
            padding: `${T.space.md} ${T.space.lg}`,
            backgroundColor: T.accent.red + '15',
            border: `1px solid ${T.accent.red}40`,
            borderRadius: T.radius.lg,
            color: T.accent.red,
            fontSize: 13,
          }}>
            <svg style={{ height: 16, width: 16, flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            {error}
          </div>
        )}

        {/* Summary bar */}
        <SummaryBar findings={allFindings} />

        {/* Severity filter tabs */}
        <div>
          <h2 style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.md }}>
            Filtrar por severidad
          </h2>
          <SeverityTabs filter={filter} onChange={setFilter} counts={counts} />
        </div>

        {/* Findings list */}
        <div>
          <h2 style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.md, display: 'flex', alignItems: 'center', gap: T.space.sm }}>
            Hallazgos
            <span style={{ fontSize: 11, fontWeight: 700, color: T.text.secondary, textTransform: 'none' }}>
              ({filteredFindings.length})
            </span>
          </h2>

          {filteredFindings.length === 0 ? (
            <EmptyState severity={filter} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>
              {filteredFindings.map(finding => (
                <FindingCard
                  key={finding.id}
                  finding={finding}
                  clientId={clientId}
                  onMarkFalsePositive={handleMarkFalsePositive}
                  marking={markingId === finding.id}
                />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
