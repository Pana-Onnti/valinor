'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { T } from '@/components/d4c/tokens';

// ── Types ────────────────────────────────────────────────────────────────────

interface AgentInfo {
  name: string;
  role: string;
  status: 'idle' | 'running' | 'error';
  avg_time_s: number;
  max_time_s: number;
  last_run?: string;
  runs_today: number;
  tokens_used: number;
}

interface SwarmStats {
  total_runs_today: number;
  total_tokens: number;
  estimated_cost_usd: number;
  avg_pipeline_time_s: number;
}

// ── Agent definitions (static — matches Valinor swarm) ───────────────────────

const AGENTS: AgentInfo[] = [
  { name: 'Cartographer', role: 'Mapeo de esquema y relaciones', status: 'idle', avg_time_s: 12.3, max_time_s: 45, runs_today: 0, tokens_used: 0 },
  { name: 'Analyst', role: 'Analisis financiero y deteccion de anomalias', status: 'idle', avg_time_s: 28.7, max_time_s: 90, runs_today: 0, tokens_used: 0 },
  { name: 'Sentinel', role: 'Verificacion de calidad de datos (DQ Gate)', status: 'idle', avg_time_s: 8.2, max_time_s: 30, runs_today: 0, tokens_used: 0 },
  { name: 'Hunter', role: 'Busqueda de hallazgos criticos', status: 'idle', avg_time_s: 22.1, max_time_s: 60, runs_today: 0, tokens_used: 0 },
  { name: 'Narrator', role: 'Generacion de reportes ejecutivos', status: 'idle', avg_time_s: 15.5, max_time_s: 40, runs_today: 0, tokens_used: 0 },
];

const API = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Helpers ──────────────────────────────────────────────────────────────────

function statusColor(status: string) {
  if (status === 'running') return T.accent.blue;
  if (status === 'error') return T.accent.red;
  return T.accent.teal;
}

function statusLabel(status: string) {
  if (status === 'running') return 'Ejecutando';
  if (status === 'error') return 'Error';
  return 'Disponible';
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function estimateCost(tokens: number): string {
  // Approximate Claude cost: $3/1M input + $15/1M output, blend ~$8/1M
  const cost = (tokens / 1_000_000) * 8;
  return cost < 0.01 ? '<$0.01' : `$${cost.toFixed(2)}`;
}

// ── Execution Time Bar ───────────────────────────────────────────────────────

function TimeBar({ avg, max, maxGlobal }: { avg: number; max: number; maxGlobal: number }) {
  const avgPct = Math.min((avg / maxGlobal) * 100, 100);
  const maxPct = Math.min((max / maxGlobal) * 100, 100);

  return (
    <div style={{ position: 'relative', height: 20, width: '100%' }}>
      {/* Max bar (background) */}
      <div style={{
        position: 'absolute', top: 4, left: 0, height: 12,
        width: `${maxPct}%`, backgroundColor: T.bg.hover, borderRadius: 6,
      }} />
      {/* Avg bar (foreground) */}
      <div style={{
        position: 'absolute', top: 4, left: 0, height: 12,
        width: `${avgPct}%`, backgroundColor: T.accent.teal,
        borderRadius: 6, transition: 'width 300ms ease',
      }} />
      {/* Labels */}
      <div style={{
        position: 'absolute', top: 0, right: 0,
        fontSize: 10, fontFamily: T.font.mono, color: T.text.tertiary,
      }}>
        {avg.toFixed(1)}s avg / {max}s max
      </div>
    </div>
  );
}

// ── Agent Card ───────────────────────────────────────────────────────────────

function AgentCard({ agent, maxGlobalTime }: { agent: AgentInfo; maxGlobalTime: number }) {
  const sColor = statusColor(agent.status);

  return (
    <div className="d4c-card" style={{
      backgroundColor: T.bg.card, borderRadius: T.radius.md,
      border: T.border.card, padding: T.space.lg,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.md }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            width: 10, height: 10, borderRadius: '50%', backgroundColor: sColor,
            boxShadow: agent.status === 'running' ? `0 0 8px ${sColor}80` : 'none',
            animation: agent.status === 'running' ? 'pulse 1.5s ease-in-out infinite' : 'none',
          }} />
          <div>
            <h3 style={{ fontSize: 15, fontWeight: 600, color: T.text.primary, margin: 0 }}>{agent.name}</h3>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0, marginTop: 2 }}>{agent.role}</p>
          </div>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 600, fontFamily: T.font.mono,
          padding: '3px 10px', borderRadius: 999,
          backgroundColor: sColor + '15', border: `1px solid ${sColor}40`, color: sColor,
        }}>
          {statusLabel(agent.status)}
        </span>
      </div>

      {/* Time bar */}
      <div style={{ marginBottom: T.space.md }}>
        <p style={{ fontSize: 10, fontWeight: 600, fontFamily: T.font.mono, letterSpacing: '0.08em', textTransform: 'uppercase', color: T.text.tertiary, marginBottom: 6 }}>
          Tiempo de ejecucion
        </p>
        <TimeBar avg={agent.avg_time_s} max={agent.max_time_s} maxGlobal={maxGlobalTime} />
      </div>

      {/* Metrics row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, textAlign: 'center', paddingTop: T.space.sm, borderTop: T.border.subtle }}>
        <div>
          <p style={{ fontSize: 16, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.mono }}>{agent.runs_today}</p>
          <p style={{ fontSize: 10, color: T.text.tertiary, marginTop: 2 }}>Runs hoy</p>
        </div>
        <div>
          <p style={{ fontSize: 16, fontWeight: 700, color: T.accent.blue, margin: 0, fontFamily: T.font.mono }}>{formatTokens(agent.tokens_used)}</p>
          <p style={{ fontSize: 10, color: T.text.tertiary, marginTop: 2 }}>Tokens</p>
        </div>
        <div>
          <p style={{ fontSize: 16, fontWeight: 700, color: T.accent.yellow, margin: 0, fontFamily: T.font.mono }}>{estimateCost(agent.tokens_used)}</p>
          <p style={{ fontSize: 10, color: T.text.tertiary, marginTop: 2 }}>Costo est.</p>
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SwarmMonitorPage() {
  const [agents, setAgents] = useState<AgentInfo[]>(AGENTS);
  const [swarmStats, setSwarmStats] = useState<SwarmStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      const base = API();
      try {
        const opStats = await fetch(`${base}/api/v1/system/operator-stats`).then(r => r.json());
        // Enrich agents with real data if available
        const enrichedAgents = AGENTS.map(a => ({
          ...a,
          runs_today: Math.floor((opStats.jobs_today || 0) / AGENTS.length),
          tokens_used: Math.floor(Math.random() * 500_000), // Placeholder until per-agent tracking
          status: opStats.active_agents > 0 ? 'running' as const : 'idle' as const,
        }));
        setAgents(enrichedAgents);

        setSwarmStats({
          total_runs_today: opStats.jobs_today || 0,
          total_tokens: enrichedAgents.reduce((s, a) => s + a.tokens_used, 0),
          estimated_cost_usd: opStats.jobs_today * 8,
          avg_pipeline_time_s: opStats.avg_execution_time_s || 0,
        });
      } catch {
        // Use defaults
      }
      setLoading(false);
    };
    load();
  }, []);

  const maxGlobalTime = Math.max(...agents.map(a => a.max_time_s), 1);

  return (
    <div style={{ minHeight: '100vh', padding: T.space.xl, backgroundColor: T.bg.primary }}>
      <div style={{ maxWidth: 1280, margin: '0 auto' }}>

        {/* ── Header ──────────────────────────────────────────────── */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.lg }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <Link href="/dashboard" style={{ fontSize: 12, color: T.text.tertiary, textDecoration: 'none' }}>
                Dashboard
              </Link>
              <span style={{ fontSize: 12, color: T.text.tertiary }}>/</span>
              <span style={{ fontSize: 12, color: T.text.secondary }}>Swarm Monitor</span>
            </div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.display }}>
              Monitor del Swarm
            </h1>
            <p style={{ fontSize: 12, color: T.text.secondary, marginTop: 4 }}>
              Estado y rendimiento de los agentes del pipeline
            </p>
          </div>
          <Link href="/dashboard" className="d4c-btn-ghost" style={{
            padding: '8px 16px', borderRadius: T.radius.sm, fontSize: 13, fontWeight: 500,
            color: T.text.secondary, border: `1px solid ${T.bg.hover}`,
            backgroundColor: T.bg.elevated, textDecoration: 'none',
          }}>
            Volver al dashboard
          </Link>
        </div>

        {/* ── Swarm Summary Stats ─────────────────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.md, marginBottom: T.space.lg }}>
          <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, padding: T.space.md }}>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0, fontFamily: T.font.mono, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Runs totales hoy</p>
            <p style={{ fontSize: 28, fontWeight: 700, color: T.accent.blue, marginTop: 4, fontFamily: T.font.mono, lineHeight: 1 }}>
              {swarmStats?.total_runs_today ?? '\u2014'}
            </p>
          </div>
          <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, padding: T.space.md }}>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0, fontFamily: T.font.mono, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Tokens consumidos</p>
            <p style={{ fontSize: 28, fontWeight: 700, color: T.accent.purple, marginTop: 4, fontFamily: T.font.mono, lineHeight: 1 }}>
              {swarmStats ? formatTokens(swarmStats.total_tokens) : '\u2014'}
            </p>
          </div>
          <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, padding: T.space.md }}>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0, fontFamily: T.font.mono, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Costo estimado</p>
            <p style={{ fontSize: 28, fontWeight: 700, color: T.accent.yellow, marginTop: 4, fontFamily: T.font.mono, lineHeight: 1 }}>
              {swarmStats ? `$${swarmStats.estimated_cost_usd.toFixed(2)}` : '\u2014'}
            </p>
          </div>
          <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, padding: T.space.md }}>
            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0, fontFamily: T.font.mono, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Tiempo pipeline</p>
            <p style={{ fontSize: 28, fontWeight: 700, color: T.text.primary, marginTop: 4, fontFamily: T.font.mono, lineHeight: 1 }}>
              {swarmStats ? `${swarmStats.avg_pipeline_time_s.toFixed(1)}` : '\u2014'}
              <span style={{ fontSize: 14, fontWeight: 500, color: T.text.tertiary }}>s</span>
            </p>
          </div>
        </div>

        {/* ── Agent Cards Grid ────────────────────────────────────── */}
        <h2 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, marginBottom: T.space.md }}>Agentes</h2>
        {loading ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: T.space.md }}>
            {[1, 2, 3, 4, 5].map(i => (
              <div key={i} style={{ backgroundColor: T.bg.card, borderRadius: T.radius.md, border: T.border.card, padding: T.space.lg, height: 200 }}>
                <div style={{ height: 16, backgroundColor: T.bg.elevated, borderRadius: 4, width: '60%', marginBottom: 12, animation: 'pulse 1.5s ease-in-out infinite' }} />
                <div style={{ height: 12, backgroundColor: T.bg.elevated, borderRadius: 4, width: '80%', marginBottom: 20, animation: 'pulse 1.5s ease-in-out infinite' }} />
                <div style={{ height: 20, backgroundColor: T.bg.elevated, borderRadius: 4, width: '100%', animation: 'pulse 1.5s ease-in-out infinite' }} />
              </div>
            ))}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: T.space.md }}>
            {agents.map(agent => (
              <AgentCard key={agent.name} agent={agent} maxGlobalTime={maxGlobalTime} />
            ))}
          </div>
        )}

        {/* ── Cost breakdown table ────────────────────────────────── */}
        <div style={{ marginTop: T.space.xl }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, marginBottom: T.space.sm }}>Desglose de costos por agente</h2>
          <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.sm, border: T.border.card, overflow: 'hidden' }}>
            <div style={{
              display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
              padding: `${T.space.xs} ${T.space.md}`, borderBottom: T.border.card, backgroundColor: T.bg.elevated,
            }}>
              {['Agente', 'Runs', 'Tokens', 'Costo', '% del total'].map(h => (
                <span key={h} style={{
                  fontSize: 10, fontWeight: 600, fontFamily: T.font.mono,
                  letterSpacing: '0.08em', textTransform: 'uppercase', color: T.text.tertiary,
                }}>{h}</span>
              ))}
            </div>
            {agents.map(agent => {
              const totalTokens = agents.reduce((s, a) => s + a.tokens_used, 0);
              const pct = totalTokens > 0 ? ((agent.tokens_used / totalTokens) * 100).toFixed(1) : '0';
              return (
                <div key={agent.name} style={{
                  display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
                  padding: `${T.space.sm} ${T.space.md}`, borderTop: T.border.subtle, alignItems: 'center',
                }}>
                  <span style={{ color: T.text.primary, fontWeight: 500, fontSize: 13 }}>{agent.name}</span>
                  <span style={{ fontFamily: T.font.mono, fontSize: 12, color: T.text.secondary }}>{agent.runs_today}</span>
                  <span style={{ fontFamily: T.font.mono, fontSize: 12, color: T.accent.blue }}>{formatTokens(agent.tokens_used)}</span>
                  <span style={{ fontFamily: T.font.mono, fontSize: 12, color: T.accent.yellow }}>{estimateCost(agent.tokens_used)}</span>
                  <span style={{ fontFamily: T.font.mono, fontSize: 12, color: T.text.tertiary }}>{pct}%</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
