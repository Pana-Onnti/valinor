'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';

interface ClientSummary {
  client_name: string;
  run_count: number;
  last_run_date: string;
  known_findings_count: number;
  // from stats endpoint
  industry?: string;
  currency?: string;
  active_findings?: number;
  critical_active?: number;
  avg_dq_score?: number;
  dq_trend?: string;
}

// ─── System Health types ────────────────────────────────────────────────────

interface SystemMetrics {
  total_cost_estimate: number;
  avg_dq_score: number;
  success_rate: number;
  running_jobs: number;
}

interface SystemStatus {
  features?: {
    data_quality?: {
      dq_gate?: boolean;
      factor_model?: boolean;
      benford?: boolean;
      stl_decomp?: boolean;
      cointegration?: boolean;
    };
  };
}

// ─── SystemHealthBar component ───────────────────────────────────────────────

function SystemHealthBar() {
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [metricsError, setMetricsError] = useState(false);
  const [statusError, setStatusError] = useState(false);

  useEffect(() => {
    const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

    fetch(`${API}/api/system/metrics`)
      .then(r => r.json())
      .then(setMetrics)
      .catch(() => setMetricsError(true));

    fetch(`${API}/api/system/status`)
      .then(r => r.json())
      .then(setStatus)
      .catch(() => setStatusError(true));
  }, []);

  // Colour helpers
  const successColor = (v: number) =>
    v >= 90 ? 'bg-green-100 text-green-700' : v >= 70 ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700';
  const dqColor = (v: number) =>
    v >= 80 ? 'bg-green-100 text-green-700' : v >= 60 ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700';
  const runningColor = (v: number) =>
    v === 0 ? 'bg-gray-100 text-gray-500' : 'bg-blue-100 text-blue-700';

  const features = status?.features ?? null;
  const dq = features?.data_quality ?? {};
  const featureList: { key: keyof typeof dq; label: string }[] = [
    { key: 'dq_gate',        label: 'DQ Gate' },
    { key: 'factor_model',   label: 'Factor Model' },
    { key: 'benford',        label: 'Benford' },
    { key: 'stl_decomp',     label: 'STL Decomp' },
    { key: 'cointegration',  label: 'Cointegración' },
  ];

  return (
    <div className="bg-white border rounded-xl px-5 py-3 mb-6 flex flex-wrap items-center gap-x-6 gap-y-3">
      {/* ── Metrics pills ── */}
      <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Sistema</span>

      {metricsError ? (
        <span className="px-2.5 py-1 rounded-full text-xs bg-red-50 text-red-400">metrics unavailable</span>
      ) : metrics ? (
        <>
          <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
            Costo estimado: <strong>${metrics.total_cost_estimate.toFixed(2)}</strong>
          </span>
          <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${dqColor(metrics.avg_dq_score)}`}>
            DQ avg: <strong>{Math.round(metrics.avg_dq_score)}/100</strong>
          </span>
          <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${successColor(metrics.success_rate)}`}>
            Exito: <strong>{Math.round(metrics.success_rate)}%</strong>
          </span>
          <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${runningColor(metrics.running_jobs)}`}>
            Jobs activos: <strong>{metrics.running_jobs}</strong>
          </span>
        </>
      ) : (
        <>
          {[1, 2, 3, 4].map(i => (
            <span key={i} className="px-2.5 py-1 rounded-full text-xs bg-gray-100 text-gray-300 animate-pulse w-24">&nbsp;</span>
          ))}
        </>
      )}

      {/* ── Divider ── */}
      <span className="h-4 w-px bg-gray-200 hidden sm:inline-block" />

      {/* ── Feature flags ── */}
      <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Features activas</span>

      {statusError ? (
        <span className="px-2.5 py-1 rounded-full text-xs bg-red-50 text-red-400">status unavailable</span>
      ) : features ? (
        featureList.map(({ key, label }) => {
          const active = features.data_quality?.[key] ?? false;
          return (
            <span
              key={key}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${
                active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'
              }`}
            >
              {active ? '✓' : '○'} {label}
            </span>
          );
        })
      ) : (
        <>
          {[1, 2, 3, 4, 5].map(i => (
            <span key={i} className="px-2.5 py-1 rounded-full text-xs bg-gray-100 text-gray-300 animate-pulse w-20">&nbsp;</span>
          ))}
        </>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<'critical' | 'last_run' | 'dq_score'>('critical');

  useEffect(() => {
    const load = async () => {
      const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const base = await fetch(`${API}/api/clients`).then(r => r.json());

      // Enrich with stats and DQ history in parallel
      const enriched = await Promise.all(
        (base.clients || []).map(async (c: ClientSummary) => {
          try {
            const [stats, dq] = await Promise.all([
              fetch(`${API}/api/clients/${c.client_name}/stats`).then(r => r.json()),
              fetch(`${API}/api/clients/${c.client_name}/dq-history`).then(r => r.json()),
            ]);
            return {
              ...c,
              industry: stats.industry,
              currency: stats.currency,
              active_findings: stats.active_findings,
              critical_active: stats.critical_active,
              avg_dq_score: dq.avg_score,
              dq_trend: dq.trend,
            };
          } catch {
            return c;
          }
        })
      );
      setClients(enriched);
      setLoading(false);
    };
    load();
  }, []);

  const sorted = [...clients].sort((a, b) => {
    if (sortBy === 'critical') return (b.critical_active || 0) - (a.critical_active || 0);
    if (sortBy === 'last_run') return (b.last_run_date || '').localeCompare(a.last_run_date || '');
    if (sortBy === 'dq_score') return (b.avg_dq_score || 0) - (a.avg_dq_score || 0);
    return 0;
  });

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {/* Header */}
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Dashboard Operador</h1>
            <p className="text-sm text-gray-500 mt-0.5">{clients.length} clientes activos</p>
          </div>
          <div className="flex gap-2 items-center">
            {(['critical', 'last_run', 'dq_score'] as const).map(s => (
              <button
                key={s}
                onClick={() => setSortBy(s)}
                className={`px-3 py-1.5 rounded-lg text-sm ${sortBy === s ? 'bg-violet-600 text-white' : 'bg-white border text-gray-600 hover:border-violet-300'}`}
              >
                {s === 'critical' ? 'Por criticidad' : s === 'last_run' ? 'Ultimo analisis' : 'DQ Score'}
              </button>
            ))}
            <Link href="/" className="ml-4 text-xs text-gray-400 hover:text-violet-600">
              Inicio
            </Link>
          </div>
        </div>

        {/* System health */}
        <SystemHealthBar />

        {/* Summary bar */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { label: 'Clientes', value: clients.length, color: 'violet' },
            { label: 'Hallazgos criticos', value: clients.reduce((s, c) => s + (c.critical_active || 0), 0), color: 'red' },
            { label: 'DQ Score promedio', value: clients.length ? Math.round(clients.reduce((s, c) => s + (c.avg_dq_score || 75), 0) / clients.length) + '/100' : '\u2014', color: 'green' },
            { label: 'Analisis totales', value: clients.reduce((s, c) => s + c.run_count, 0), color: 'blue' },
          ].map(stat => (
            <div key={stat.label} className="bg-white rounded-xl border p-4">
              <p className="text-xs text-gray-500">{stat.label}</p>
              <p className={`text-2xl font-bold mt-1 text-${stat.color}-600`}>{stat.value}</p>
            </div>
          ))}
        </div>

        {/* Client cards grid */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-white rounded-xl border p-5 animate-pulse">
                <div className="h-4 bg-gray-200 rounded w-2/3 mb-3" />
                <div className="h-3 bg-gray-200 rounded w-1/3 mb-2" />
                <div className="h-3 bg-gray-200 rounded w-1/2" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {sorted.map(client => (
              <ClientCard key={client.client_name} client={client} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ClientCard({ client }: { client: ClientSummary }) {
  const criticalCount = client.critical_active || 0;
  const dqScore = client.avg_dq_score;
  const dqColor = !dqScore ? 'gray' : dqScore >= 85 ? 'green' : dqScore >= 65 ? 'amber' : 'orange';
  const trendIcon = client.dq_trend === 'improving' ? '\u2191' : client.dq_trend === 'declining' ? '\u2193' : '\u2192';

  return (
    <Link href={`/clients/${client.client_name}/history`}>
      <div className="bg-white rounded-xl border hover:border-violet-300 hover:shadow-md transition-all p-5 cursor-pointer">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="font-semibold text-gray-900">{client.client_name}</h3>
            <p className="text-xs text-gray-500 mt-0.5">{client.industry || 'Sin sector'} &middot; {client.currency || 'USD'}</p>
          </div>
          {criticalCount > 0 && (
            <span className="px-2 py-0.5 bg-red-100 text-red-700 text-xs font-bold rounded-full">
              {criticalCount} CRIT
            </span>
          )}
        </div>

        {/* Metrics row */}
        <div className="grid grid-cols-3 gap-2 mb-3">
          <div className="text-center">
            <p className="text-lg font-bold text-gray-900">{client.run_count}</p>
            <p className="text-xs text-gray-400">analisis</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-gray-900">{client.active_findings ?? client.known_findings_count}</p>
            <p className="text-xs text-gray-400">activos</p>
          </div>
          <div className="text-center">
            <p className={`text-lg font-bold text-${dqColor}-600`}>
              {dqScore ? `${dqScore}` : '\u2014'}
            </p>
            <p className="text-xs text-gray-400">DQ {trendIcon}</p>
          </div>
        </div>

        {/* Footer */}
        <div className="pt-2 border-t text-xs text-gray-400 flex justify-between">
          <span>Ultimo: {client.last_run_date ? new Date(client.last_run_date).toLocaleDateString('es-ES') : 'nunca'}</span>
          <span className="text-violet-600">Ver historial &rarr;</span>
        </div>
      </div>
    </Link>
  );
}
