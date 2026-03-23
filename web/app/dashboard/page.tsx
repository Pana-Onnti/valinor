'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { T } from '@/components/d4c/tokens';

// ── Types ────────────────────────────────────────────────────────────────────

interface ClientSummary {
  client_name: string;
  run_count: number;
  last_run_date: string;
  known_findings_count: number;
  industry?: string;
  currency?: string;
  active_findings?: number;
  critical_active?: number;
  avg_dq_score?: number;
  dq_trend?: string;
}

interface OperatorStats {
  total_clients: number;
  jobs_today: number;
  success_rate: number;
  avg_execution_time_s: number;
  active_agents: number;
}

interface JobSummary {
  job_id: string;
  client_name: string;
  status: string;
  period?: string;
  started_at?: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const API = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function scoreAccent(v: number) {
  if (v >= 85) return T.accent.teal;
  if (v >= 65) return T.accent.yellow;
  return T.accent.red;
}

function pillStyle(color: string): React.CSSProperties {
  return {
    display: 'inline-flex', alignItems: 'center',
    fontSize: 11, fontWeight: 600, fontFamily: T.font.mono,
    padding: '3px 10px', borderRadius: 999,
    backgroundColor: color + '15', border: `1px solid ${color}40`, color,
  };
}

function Pill({ label, color }: { label: string; color: string }) {
  return <span style={pillStyle(color)}>{label}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: T.accent.teal, success: T.accent.teal,
    running: T.accent.blue, pending: T.accent.yellow,
    failed: T.accent.red, error: T.accent.red,
  };
  const color = map[status?.toLowerCase()] ?? T.text.tertiary;
  return <Pill label={status} color={color} />;
}

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      backgroundColor: connected ? T.accent.teal : T.accent.red,
      boxShadow: connected ? `0 0 6px ${T.accent.teal}60` : 'none',
    }} />
  );
}

function DQSparkline({ trend }: { trend?: string }) {
  const color = trend === 'improving' ? T.accent.teal : trend === 'declining' ? T.accent.red : T.accent.yellow;
  const heights = trend === 'improving' ? [4, 8, 12] : trend === 'declining' ? [12, 8, 4] : [8, 8, 8];
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, justifyContent: 'center', marginTop: 4 }}>
      {heights.map((h, i) => (
        <div key={i} style={{ width: 6, height: h, backgroundColor: color, borderRadius: 2 }} />
      ))}
    </div>
  );
}

function formatDate(iso?: string) {
  if (!iso) return '\u2014';
  try {
    return new Date(iso).toLocaleString('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

// ── Stat Card ────────────────────────────────────────────────────────────────

function StatCard({ label, value, color, suffix }: { label: string; value: string | number; color: string; suffix?: string }) {
  return (
    <div style={{
      backgroundColor: T.bg.card, borderRadius: T.radius.sm,
      border: T.border.card, padding: T.space.md,
    }}>
      <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0, fontFamily: T.font.mono, letterSpacing: '0.05em', textTransform: 'uppercase' }}>{label}</p>
      <p style={{ fontSize: 28, fontWeight: 700, color, marginTop: 4, fontFamily: T.font.mono, lineHeight: 1 }}>
        {value}{suffix && <span style={{ fontSize: 14, fontWeight: 500, color: T.text.tertiary }}>{suffix}</span>}
      </p>
    </div>
  );
}

// ── Client Card ──────────────────────────────────────────────────────────────

function ClientCard({ client }: { client: ClientSummary }) {
  const dqScore = client.avg_dq_score;
  const scoreColor = !dqScore ? T.text.tertiary : scoreAccent(dqScore);
  const criticalCount = client.critical_active || 0;
  const connected = (client.run_count || 0) > 0;

  return (
    <Link href={`/clients/${client.client_name}/history`} style={{ textDecoration: 'none', display: 'block' }}>
      <div className="d4c-card" style={{
        backgroundColor: T.bg.card, borderRadius: T.radius.md,
        border: T.border.card, padding: T.space.lg, cursor: 'pointer',
        transition: 'border-color 150ms ease',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: T.space.sm }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ConnectionDot connected={connected} />
            <div>
              <h3 style={{ fontWeight: 600, color: T.text.primary, fontSize: 14, margin: 0 }}>{client.client_name}</h3>
              <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2 }}>
                {client.industry || 'Sin sector'} &middot; {client.currency || 'USD'}
              </p>
            </div>
          </div>
          {criticalCount > 0 && <Pill label={`${criticalCount} CRIT`} color={T.accent.red} />}
        </div>

        {/* Metrics grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: T.space.sm, textAlign: 'center' }}>
          <div>
            <p style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.mono }}>{client.run_count}</p>
            <p style={{ fontSize: 10, color: T.text.tertiary, marginTop: 2 }}>analisis</p>
          </div>
          <div>
            <p style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.mono }}>
              {client.active_findings ?? client.known_findings_count}
            </p>
            <p style={{ fontSize: 10, color: T.text.tertiary, marginTop: 2 }}>hallazgos</p>
          </div>
          <div>
            <p style={{ fontSize: 18, fontWeight: 700, color: scoreColor, margin: 0, fontFamily: T.font.mono }}>
              {dqScore ?? '\u2014'}
            </p>
            <DQSparkline trend={client.dq_trend} />
            <p style={{ fontSize: 10, color: T.text.tertiary, marginTop: 2 }}>DQ</p>
          </div>
        </div>

        {/* Footer */}
        <div style={{ paddingTop: T.space.sm, borderTop: T.border.subtle, display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
          <span style={{ color: T.text.tertiary }}>
            Ultimo: {client.last_run_date ? new Date(client.last_run_date).toLocaleDateString('es-ES') : 'nunca'}
          </span>
          <span style={{ color: T.accent.teal }}>Ver historial &rarr;</span>
        </div>
      </div>
    </Link>
  );
}

// ── Recent Jobs Table ────────────────────────────────────────────────────────

function RecentJobsSection() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API()}/api/jobs?page=1&page_size=5`).then(r => r.json())
      .then(data => setJobs(data.jobs || []))
      .catch(() => setJobs([]))
      .finally(() => setLoading(false));
  }, []);

  const cols = ['Job ID', 'Cliente', 'Estado', 'Periodo', 'Iniciado'];

  return (
    <div style={{ marginTop: T.space.xl }}>
      <h2 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, marginBottom: T.space.sm }}>Jobs recientes</h2>
      <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, overflow: 'hidden' }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1.5fr 1fr 1fr 1.5fr',
          padding: `${T.space.xs} ${T.space.md}`, borderBottom: T.border.card, backgroundColor: T.bg.elevated,
        }}>
          {cols.map((h, i) => (
            <span key={h} style={{
              fontSize: 10, fontWeight: 600, fontFamily: T.font.mono,
              letterSpacing: '0.08em', textTransform: 'uppercase', color: T.text.tertiary,
              textAlign: i === cols.length - 1 ? 'right' : 'left',
            }}>{h}</span>
          ))}
        </div>
        {loading ? (
          [1, 2, 3].map(i => (
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
                padding: `${T.space.sm} ${T.space.md}`, fontSize: 13, textDecoration: 'none',
                borderTop: T.border.subtle, alignItems: 'center',
              }}>
              <span style={{ fontFamily: T.font.mono, fontSize: 11, color: T.text.tertiary }} title={job.job_id}>
                {job.job_id.length > 12 ? `${job.job_id.slice(0, 8)}...` : job.job_id}
              </span>
              <span style={{ color: T.text.primary, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{job.client_name}</span>
              <span><StatusBadge status={job.status} /></span>
              <span style={{ fontFamily: T.font.mono, fontSize: 11, color: T.text.secondary }}>{job.period || '\u2014'}</span>
              <span style={{ textAlign: 'right', fontSize: 11, color: T.text.tertiary }}>{formatDate(job.started_at)}</span>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [stats, setStats] = useState<OperatorStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'critical' | 'last_run' | 'dq_score'>('critical');

  useEffect(() => {
    const load = async () => {
      const base = API();
      // Fetch operator stats
      try {
        const s = await fetch(`${base}/api/v1/system/operator-stats`).then(r => r.json());
        setStats(s);
      } catch { /* stats unavailable */ }

      // Fetch and enrich clients
      try {
        const data = await fetch(`${base}/api/clients`).then(r => r.json());
        const enriched = await Promise.all(
          (data.clients || []).map(async (c: ClientSummary) => {
            try {
              const [clientStats, dq] = await Promise.all([
                fetch(`${base}/api/clients/${c.client_name}/stats`).then(r => r.json()),
                fetch(`${base}/api/clients/${c.client_name}/dq-history`).then(r => r.json()),
              ]);
              return {
                ...c,
                industry: clientStats.industry, currency: clientStats.currency,
                active_findings: clientStats.active_findings, critical_active: clientStats.critical_active,
                avg_dq_score: dq.avg_score, dq_trend: dq.trend,
              };
            } catch { return c; }
          })
        );
        setClients(enriched);
      } catch { /* clients unavailable */ }
      setLoading(false);
    };
    load();
  }, []);

  const sorted = [...clients].sort((a, b) => {
    if (sortBy === 'critical') return (b.critical_active || 0) - (a.critical_active || 0);
    if (sortBy === 'last_run') return (b.last_run_date || '').localeCompare(a.last_run_date || '');
    return (b.avg_dq_score || 0) - (a.avg_dq_score || 0);
  });

  const SORT_OPTIONS = [
    { key: 'critical' as const, label: 'Por criticidad' },
    { key: 'last_run' as const, label: 'Ultimo analisis' },
    { key: 'dq_score' as const, label: 'DQ Score' },
  ];

  return (
    <div style={{ minHeight: '100vh', padding: T.space.xl, backgroundColor: T.bg.primary }}>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>

        {/* ── Header ──────────────────────────────────────────────────── */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.lg }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.display }}>
              Dashboard Operador
            </h1>
            <p style={{ fontSize: 12, color: T.text.secondary, marginTop: 4 }}>
              {stats ? `${stats.total_clients} clientes activos` : `${clients.length} clientes`}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Link href="/dashboard/swarm" className="d4c-btn-ghost" style={{
              padding: '8px 16px', borderRadius: T.radius.sm, fontSize: 13, fontWeight: 500,
              color: T.accent.purple, border: `1px solid ${T.accent.purple}40`,
              backgroundColor: T.accent.purple + '10', textDecoration: 'none',
              fontFamily: T.font.display, transition: 'all 150ms ease',
            }}>
              Monitor Swarm
            </Link>
            <Link href="/clients" className="d4c-btn-primary" style={{
              padding: '8px 16px', borderRadius: T.radius.sm, fontSize: 13, fontWeight: 600,
              color: T.text.inverse, backgroundColor: T.accent.teal, textDecoration: 'none',
              fontFamily: T.font.display, transition: 'all 150ms ease',
            }}>
              Nuevo Analisis
            </Link>
          </div>
        </div>

        {/* ── System Health Stats ─────────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: T.space.md, marginBottom: T.space.lg }}>
          <StatCard
            label="Clientes totales"
            value={stats?.total_clients ?? clients.length}
            color={T.accent.teal}
          />
          <StatCard
            label="Jobs hoy"
            value={stats?.jobs_today ?? '\u2014'}
            color={T.accent.blue}
          />
          <StatCard
            label="Tasa de exito"
            value={stats ? `${Math.round(stats.success_rate)}` : '\u2014'}
            color={stats && stats.success_rate >= 90 ? T.accent.teal : T.accent.yellow}
            suffix="%"
          />
          <StatCard
            label="Tiempo promedio"
            value={stats ? `${stats.avg_execution_time_s.toFixed(1)}` : '\u2014'}
            color={T.text.primary}
            suffix="s"
          />
          <StatCard
            label="Agentes activos"
            value={stats?.active_agents ?? '\u2014'}
            color={T.accent.purple}
          />
        </div>

        {/* ── Sort bar ────────────────────────────────────────────────── */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: T.space.md,
        }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, margin: 0 }}>Clientes</h2>
          <div style={{ display: 'flex', gap: 6 }}>
            {SORT_OPTIONS.map(s => (
              <button key={s.key} onClick={() => setSortBy(s.key)}
                style={{
                  padding: '5px 12px', borderRadius: T.radius.sm, fontSize: 12, fontWeight: 500,
                  border: `1px solid ${sortBy === s.key ? T.accent.teal : T.bg.hover}`,
                  backgroundColor: sortBy === s.key ? T.accent.teal + '15' : T.bg.elevated,
                  color: sortBy === s.key ? T.accent.teal : T.text.secondary,
                  cursor: 'pointer', fontFamily: T.font.display, transition: 'all 150ms ease',
                }}
              >{s.label}</button>
            ))}
          </div>
        </div>

        {/* ── Client Cards Grid ───────────────────────────────────────── */}
        {loading ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: T.space.md }}>
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} style={{ backgroundColor: T.bg.card, borderRadius: T.radius.md, border: T.border.card, padding: T.space.lg }}>
                {[0.67, 0.33, 0.5].map((w, j) => (
                  <div key={j} style={{
                    height: j === 0 ? 16 : 12, backgroundColor: T.bg.elevated,
                    borderRadius: 4, width: `${w * 100}%`, marginBottom: j < 2 ? 12 : 0,
                    animation: 'pulse 1.5s ease-in-out infinite',
                  }} />
                ))}
              </div>
            ))}
          </div>
        ) : sorted.length === 0 ? (
          <div style={{
            backgroundColor: T.bg.card, borderRadius: T.radius.md, border: T.border.card,
            padding: T.space.xxl, textAlign: 'center',
          }}>
            <p style={{ fontSize: 14, color: T.text.tertiary }}>Sin clientes registrados</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: T.space.md }}>
            {sorted.map(client => <ClientCard key={client.client_name} client={client} />)}
          </div>
        )}

        {/* ── Recent Jobs ─────────────────────────────────────────────── */}
        <RecentJobsSection />
      </div>
    </div>
  );
}
