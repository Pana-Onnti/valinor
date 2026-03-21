'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { T } from '@/components/d4c/tokens';

interface JobSummary { job_id: string; client_name: string; status: string; period?: string; started_at?: string }
interface JobsResponse { jobs: JobSummary[]; total?: number }
interface ClientComparison { client_name: string; avg_dq_score: number; dq_trend: string; critical_findings: number; last_run: string; industry: string }
interface ClientSummary { client_name: string; run_count: number; last_run_date: string; known_findings_count: number; industry?: string; currency?: string; active_findings?: number; critical_active?: number; avg_dq_score?: number; dq_trend?: string }
interface SystemMetrics { total_cost_estimate: number; avg_dq_score: number; success_rate: number; running_jobs: number }
interface SystemStatus { features?: { data_quality?: { dq_gate?: boolean; factor_model?: boolean; benford?: boolean; stl_decomp?: boolean; cointegration?: boolean } } }

// ── Helpers ───────────────────────────────────────────────────────────────────

function scoreAccent(v: number) {
  if (v >= 85) return T.accent.teal
  if (v >= 65) return T.accent.yellow
  return T.accent.red
}

function pill(label: string, color: string) {
  return {
    display: 'inline-flex' as const, alignItems: 'center' as const,
    fontSize: 11, fontWeight: 600, fontFamily: T.font.mono,
    padding: '3px 10px', borderRadius: 999,
    backgroundColor: color + '15', border: `1px solid ${color}40`, color,
  }
}

function Pill({ label, color }: { label: string; color: string }) {
  return <span style={pill(label, color)}>{label}</span>
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: T.accent.teal, success: T.accent.teal,
    running: T.accent.blue, pending: T.accent.yellow, queued: T.accent.yellow,
    failed: T.accent.red, error: T.accent.red,
  }
  const color = map[status?.toLowerCase()] ?? T.text.tertiary
  return <Pill label={status} color={color} />
}

// ── DQ Sparkline ──────────────────────────────────────────────────────────────

function DQSparkline({ trend }: { trend?: string }) {
  const color = trend === 'improving' ? T.accent.teal : trend === 'declining' ? T.accent.red : T.accent.yellow
  const heights = trend === 'improving' ? [4, 8, 12] : trend === 'declining' ? [12, 8, 4] : [8, 8, 8]
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, justifyContent: 'center', marginTop: 4 }}>
      {heights.map((h, i) => (
        <div key={i} style={{ width: 6, height: h, backgroundColor: color, borderRadius: 2 }} />
      ))}
    </div>
  )
}

// ── System health bar ─────────────────────────────────────────────────────────

function SystemHealthBar() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null)
  const [status, setStatus]   = useState<SystemStatus | null>(null)
  const [mErr, setMErr]       = useState(false)
  const [sErr, setSErr]       = useState(false)

  useEffect(() => {
    const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    fetch(`${API}/api/system/metrics`).then(r => r.json()).then(setMetrics).catch(() => setMErr(true))
    fetch(`${API}/api/system/status`).then(r => r.json()).then(setStatus).catch(() => setSErr(true))
  }, [])

  const features = status?.features?.data_quality ?? {}
  const featureList: { key: keyof typeof features; label: string }[] = [
    { key: 'dq_gate', label: 'DQ Gate' }, { key: 'factor_model', label: 'Factor Model' },
    { key: 'benford', label: 'Benford' }, { key: 'stl_decomp', label: 'STL Decomp' },
    { key: 'cointegration', label: 'Cointegración' },
  ]

  return (
    <div style={{
      backgroundColor: T.bg.card, border: T.border.card, borderRadius: T.radius.sm,
      padding: `${T.space.sm} ${T.space.lg}`, marginBottom: T.space.lg,
      display: 'flex', flexWrap: 'wrap' as const, alignItems: 'center', gap: '12px 20px',
    }}>
      <span style={{ fontSize: 10, fontWeight: 600, fontFamily: T.font.mono, letterSpacing: '0.08em', textTransform: 'uppercase' as const, color: T.text.tertiary }}>
        Sistema
      </span>
      {mErr ? (
        <Pill label="metrics unavailable" color={T.accent.red} />
      ) : metrics ? (
        <>
          <Pill label={`Costo: $${(metrics.total_cost_estimate ?? 0).toFixed(2)}`} color={T.text.tertiary} />
          <Pill label={`DQ avg: ${Math.round(metrics.avg_dq_score ?? 0)}/100`} color={scoreAccent(metrics.avg_dq_score ?? 0)} />
          <Pill label={`Exito: ${Math.round(metrics.success_rate ?? 0)}%`} color={scoreAccent(metrics.success_rate ?? 0)} />
          <Pill label={`Jobs activos: ${metrics.running_jobs ?? 0}`} color={metrics.running_jobs ? T.accent.blue : T.text.tertiary} />
        </>
      ) : (
        [1, 2, 3, 4].map(i => <span key={i} style={{ ...pill('', T.text.tertiary), width: 80, animation: 'pulse 1.5s ease-in-out infinite' }}>&nbsp;</span>)
      )}

      <div style={{ width: 1, height: 16, backgroundColor: T.bg.hover, margin: '0 4px' }} />
      <span style={{ fontSize: 10, fontWeight: 600, fontFamily: T.font.mono, letterSpacing: '0.08em', textTransform: 'uppercase' as const, color: T.text.tertiary }}>
        Features activas
      </span>
      {sErr ? (
        <Pill label="status unavailable" color={T.accent.red} />
      ) : status ? (
        featureList.map(({ key, label }) => {
          const active = features[key] ?? false
          return <Pill key={key} label={`${active ? '✓' : '○'} ${label}`} color={active ? T.accent.teal : T.text.tertiary} />
        })
      ) : (
        [1, 2, 3, 4, 5].map(i => <span key={i} style={{ ...pill('', T.text.tertiary), width: 72, animation: 'pulse 1.5s ease-in-out infinite' }}>&nbsp;</span>)
      )}
    </div>
  )
}

// ── Recent jobs ───────────────────────────────────────────────────────────────

function RecentJobsSection() {
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    fetch(`${API}/api/jobs?page=1&page_size=5`).then(r => r.json())
      .then((data: JobsResponse) => setJobs(data.jobs || []))
      .catch(() => setJobs([])).finally(() => setLoading(false))
  }, [])

  const formatDate = (iso?: string) => {
    if (!iso) return '—'
    try { return new Date(iso).toLocaleString('es-ES', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) }
    catch { return iso }
  }
  const truncateId = (id: string) => id.length > 12 ? `${id.slice(0, 8)}…` : id

  const colHeaders = ['Job ID', 'Cliente', 'Estado', 'Período', 'Iniciado']

  return (
    <div style={{ marginTop: T.space.xl }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, marginBottom: T.space.sm }}>Jobs recientes</h2>
      <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1.5fr 1fr 1fr 1.5fr',
          padding: `${T.space.xs} ${T.space.md}`,
          borderBottom: T.border.card,
          backgroundColor: T.bg.elevated,
        }}>
          {colHeaders.map((h, i) => (
            <span key={h} style={{ fontSize: 10, fontWeight: 600, fontFamily: T.font.mono, letterSpacing: '0.08em', textTransform: 'uppercase' as const, color: T.text.tertiary, textAlign: i === colHeaders.length - 1 ? 'right' as const : 'left' as const }}>
              {h}
            </span>
          ))}
        </div>
        {loading ? (
          [1, 2, 3, 4, 5].map(i => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr 1fr 1fr 1.5fr', padding: `${T.space.sm} ${T.space.md}`, gap: 8 }}>
              {[1, 2, 3, 4, 5].map(j => (
                <div key={j} style={{ height: 12, backgroundColor: T.bg.elevated, borderRadius: 4, width: '75%', animation: 'pulse 1.5s ease-in-out infinite' }} />
              ))}
            </div>
          ))
        ) : jobs.length === 0 ? (
          <div style={{ padding: `${T.space.xl} ${T.space.md}`, textAlign: 'center', fontSize: 13, color: T.text.tertiary }}>
            Sin jobs recientes
          </div>
        ) : (
          jobs.map(job => (
            <Link key={job.job_id} href={`/clients/${encodeURIComponent(job.client_name)}`}
              style={{
                display: 'grid', gridTemplateColumns: '1fr 1.5fr 1fr 1fr 1.5fr',
                padding: `${T.space.sm} ${T.space.md}`,
                fontSize: 13, textDecoration: 'none',
                borderTop: T.border.subtle,
                alignItems: 'center',
              }}
            >
              <span style={{ fontFamily: T.font.mono, fontSize: 11, color: T.text.tertiary }} title={job.job_id}>{truncateId(job.job_id)}</span>
              <span style={{ color: T.text.primary, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.client_name}</span>
              <span><StatusBadge status={job.status} /></span>
              <span style={{ fontFamily: T.font.mono, fontSize: 11, color: T.text.secondary }}>{job.period || '—'}</span>
              <span style={{ textAlign: 'right', fontSize: 11, color: T.text.tertiary }}>{formatDate(job.started_at)}</span>
            </Link>
          ))
        )}
      </div>
    </div>
  )
}

// ── Comparison table ──────────────────────────────────────────────────────────

function ClientComparisonTable({ rows }: { rows: ClientComparison[] }) {
  const formatDate = (iso: string) => {
    if (!iso) return '—'
    try { return new Date(iso).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' }) }
    catch { return iso }
  }
  const thStyle: React.CSSProperties = {
    padding: `${T.space.xs} ${T.space.md}`, textAlign: 'left',
    fontSize: 10, fontWeight: 600, fontFamily: T.font.mono,
    letterSpacing: '0.08em', textTransform: 'uppercase', color: T.text.tertiary,
  }
  return (
    <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ backgroundColor: T.bg.elevated, borderBottom: T.border.card }}>
            <th style={thStyle}>Cliente</th>
            <th style={{ ...thStyle, textAlign: 'center' }}>DQ Score</th>
            <th style={{ ...thStyle, textAlign: 'center' }}>Tendencia</th>
            <th style={{ ...thStyle, textAlign: 'center' }}>Críticos</th>
            <th style={thStyle}>Industria</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Último análisis</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const scoreColor = scoreAccent(row.avg_dq_score)
            return (
              <tr key={row.client_name} style={{ borderTop: T.border.subtle }}>
                <td style={{ padding: `${T.space.sm} ${T.space.md}`, fontWeight: 500, color: T.text.primary }}>
                  <Link href={`/clients/${row.client_name}/history`} style={{ color: T.accent.teal, textDecoration: 'none' }}>
                    {row.client_name}
                  </Link>
                </td>
                <td style={{ padding: `${T.space.sm} ${T.space.md}`, textAlign: 'center', color: scoreColor, fontWeight: 600, fontFamily: T.font.mono }}>
                  {row.avg_dq_score ?? '—'}
                </td>
                <td style={{ padding: `${T.space.sm} ${T.space.md}` }}>
                  <div style={{ display: 'flex', justifyContent: 'center' }}>
                    <DQSparkline trend={row.dq_trend} />
                  </div>
                </td>
                <td style={{ padding: `${T.space.sm} ${T.space.md}`, textAlign: 'center' }}>
                  {row.critical_findings > 0 ? (
                    <span style={{ ...pill(`${row.critical_findings}`, T.accent.red) }}>{row.critical_findings}</span>
                  ) : (
                    <span style={{ color: T.text.tertiary }}>—</span>
                  )}
                </td>
                <td style={{ padding: `${T.space.sm} ${T.space.md}`, color: T.text.secondary }}>{row.industry || '—'}</td>
                <td style={{ padding: `${T.space.sm} ${T.space.md}`, textAlign: 'right', color: T.text.tertiary }}>{formatDate(row.last_run)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Client card ───────────────────────────────────────────────────────────────

function ClientCard({ client }: { client: ClientSummary }) {
  const criticalCount = client.critical_active || 0
  const dqScore = client.avg_dq_score
  const scoreColor = !dqScore ? T.text.tertiary : scoreAccent(dqScore)

  return (
    <Link href={`/clients/${client.client_name}/history`} style={{ textDecoration: 'none', display: 'block' }}>
      <div style={{
        backgroundColor: T.bg.card, borderRadius: T.radius.md,
        border: T.border.card, padding: T.space.lg, cursor: 'pointer',
        transition: 'border-color 150ms ease',
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: T.space.sm }}>
          <div>
            <h3 style={{ fontWeight: 600, color: T.text.primary, fontSize: 14, margin: 0 }}>{client.client_name}</h3>
            <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2 }}>
              {client.industry || 'Sin sector'} · {client.currency || 'USD'}
            </p>
          </div>
          {criticalCount > 0 && (
            <span style={{ ...pill(`${criticalCount} CRIT`, T.accent.red) }}>{criticalCount} CRIT</span>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: T.space.sm, textAlign: 'center' }}>
          {[
            { v: client.run_count, l: 'análisis' },
            { v: client.active_findings ?? client.known_findings_count, l: 'activos' },
          ].map(({ v, l }) => (
            <div key={l}>
              <p style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.mono }}>{v}</p>
              <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2 }}>{l}</p>
            </div>
          ))}
          <div style={{ textAlign: 'center' }}>
            <p style={{ fontSize: 18, fontWeight: 700, color: scoreColor, margin: 0, fontFamily: T.font.mono }}>
              {dqScore ?? '—'}
            </p>
            <DQSparkline trend={client.dq_trend} />
            <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2 }}>DQ</p>
          </div>
        </div>
        <div style={{ paddingTop: T.space.sm, borderTop: T.border.subtle, display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
          <span style={{ color: T.text.tertiary }}>
            Ultimo: {client.last_run_date ? new Date(client.last_run_date).toLocaleDateString('es-ES') : 'nunca'}
          </span>
          <span style={{ color: T.accent.teal }}>Ver historial →</span>
        </div>
      </div>
    </Link>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [clients, setClients]       = useState<ClientSummary[]>([])
  const [loading, setLoading]       = useState(true)
  const [sortBy, setSortBy]         = useState<'critical' | 'last_run' | 'dq_score'>('critical')
  const [comparison, setComparison] = useState<ClientComparison[]>([])

  useEffect(() => {
    const load = async () => {
      const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      const base = await fetch(`${API}/api/clients`).then(r => r.json())
      const enriched = await Promise.all(
        (base.clients || []).map(async (c: ClientSummary) => {
          try {
            const [stats, dq] = await Promise.all([
              fetch(`${API}/api/clients/${c.client_name}/stats`).then(r => r.json()),
              fetch(`${API}/api/clients/${c.client_name}/dq-history`).then(r => r.json()),
            ])
            return { ...c, industry: stats.industry, currency: stats.currency, active_findings: stats.active_findings, critical_active: stats.critical_active, avg_dq_score: dq.avg_score, dq_trend: dq.trend }
          } catch { return c }
        })
      )
      setClients(enriched)
      try {
        const comp = await fetch(`${API}/api/clients/comparison`).then(r => r.json())
        setComparison(comp || [])
      } catch {}
      setLoading(false)
    }
    load()
  }, [])

  const sorted = [...clients].sort((a, b) => {
    if (sortBy === 'critical') return (b.critical_active || 0) - (a.critical_active || 0)
    if (sortBy === 'last_run') return (b.last_run_date || '').localeCompare(a.last_run_date || '')
    return (b.avg_dq_score || 0) - (a.avg_dq_score || 0)
  })

  const SORT_OPTIONS = [
    { key: 'critical' as const, label: 'Por criticidad' },
    { key: 'last_run' as const, label: 'Ultimo análisis' },
    { key: 'dq_score' as const, label: 'DQ Score' },
  ]

  const SUMMARY = [
    { label: 'Clientes',            value: clients.length,                                                                                     color: T.accent.teal },
    { label: 'Hallazgos críticos',  value: clients.reduce((s, c) => s + (c.critical_active || 0), 0),                                          color: T.accent.red },
    { label: 'DQ Score promedio',   value: clients.length ? `${Math.round(clients.reduce((s, c) => s + (c.avg_dq_score || 75), 0) / clients.length)}/100` : '—', color: T.accent.teal },
    { label: 'Análisis totales',    value: clients.reduce((s, c) => s + c.run_count, 0),                                                        color: T.accent.blue },
  ]

  return (
    <div style={{ minHeight: '100vh', padding: T.space.xl }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.lg }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, margin: 0 }}>Dashboard Operador</h1>
            <p style={{ fontSize: 12, color: T.text.secondary, marginTop: 4 }}>{clients.length} clientes activos</p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {SORT_OPTIONS.map(s => (
              <button key={s.key} onClick={() => setSortBy(s.key)}
                style={{
                  padding: '6px 12px', borderRadius: T.radius.sm, fontSize: 12, fontWeight: 500,
                  border: `1px solid ${sortBy === s.key ? T.accent.teal : T.bg.hover}`,
                  backgroundColor: sortBy === s.key ? T.accent.teal + '15' : T.bg.elevated,
                  color: sortBy === s.key ? T.accent.teal : T.text.secondary,
                  cursor: 'pointer', fontFamily: T.font.display, transition: 'all 150ms ease',
                }}
              >{s.label}</button>
            ))}
          </div>
        </div>

        {/* System health */}
        <SystemHealthBar />

        {/* Summary bar */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.md, marginBottom: T.space.lg }}>
          {SUMMARY.map(stat => (
            <div key={stat.label} style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, padding: T.space.md }}>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>{stat.label}</p>
              <p style={{ fontSize: 24, fontWeight: 700, color: stat.color, marginTop: 4, fontFamily: T.font.mono }}>{stat.value}</p>
            </div>
          ))}
        </div>

        {/* Client cards */}
        {loading ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: T.space.md }}>
            {[1, 2, 3].map(i => (
              <div key={i} style={{ backgroundColor: T.bg.card, borderRadius: T.radius.md, border: T.border.card, padding: T.space.lg }}>
                {[0.67, 0.33, 0.5].map((w, j) => (
                  <div key={j} style={{ height: j === 0 ? 16 : 12, backgroundColor: T.bg.elevated, borderRadius: 4, width: `${w * 100}%`, marginBottom: j < 2 ? 12 : 0, animation: 'pulse 1.5s ease-in-out infinite' }} />
                ))}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: T.space.md }}>
            {sorted.map(client => <ClientCard key={client.client_name} client={client} />)}
          </div>
        )}

        {/* Comparison table */}
        {!loading && comparison.length >= 2 && (
          <div style={{ marginTop: T.space.xl }}>
            <h2 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, marginBottom: T.space.sm }}>Comparar clientes</h2>
            <ClientComparisonTable rows={comparison} />
          </div>
        )}

        <RecentJobsSection />
      </div>
    </div>
  )
}
