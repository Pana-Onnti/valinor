'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import SkeletonCard from '@/components/SkeletonCard'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

interface ClientComparison {
  client_name?: string
  name?: string          // API returns "name" — normalised on render
  avg_dq_score: number
  dq_trend: string
  critical_findings: number
  last_run: string
  industry: string
  run_count?: number
}

// ── DQ Score Badge (inline, compact pill) ─────────────────────────────────────

function DQBadge({ score }: { score: number | null }) {
  if (score === null || score === undefined) {
    return (
      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-400">
        DQ —
      </span>
    )
  }
  const cls =
    score >= 90
      ? 'bg-emerald-100 text-emerald-700'
      : score >= 75
      ? 'bg-amber-100 text-amber-700'
      : score >= 50
      ? 'bg-orange-100 text-orange-700'
      : 'bg-red-100 text-red-700'
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${cls}`}>
      DQ {score}
    </span>
  )
}

// ── Trend indicator ───────────────────────────────────────────────────────────

function TrendBadge({ trend }: { trend?: string }) {
  if (trend === 'improving') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-600">
        ↑ Mejorando
      </span>
    )
  }
  if (trend === 'declining' || trend === 'degrading') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-600">
        ↓ Bajando
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500">
      → Estable
    </span>
  )
}

// ── Client Card ───────────────────────────────────────────────────────────────

function ClientCard({ client }: { client: ClientComparison }) {
  const formatDate = (iso: string) => {
    if (!iso) return 'Nunca'
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

  return (
    <Link href={`/clients/${encodeURIComponent(client.client_name ?? (client as any).name)}`}>
      <div className="bg-white rounded-2xl border border-gray-100 hover:border-violet-300 hover:shadow-md transition-all p-5 cursor-pointer h-full flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="font-semibold text-gray-900 truncate">{client.client_name ?? (client as any).name}</h3>
            {client.industry && (
              <p className="text-xs text-gray-400 mt-0.5 truncate">{client.industry}</p>
            )}
          </div>
          {client.critical_findings > 0 && (
            <span className="flex-shrink-0 px-2 py-0.5 bg-red-100 text-red-700 text-xs font-bold rounded-full">
              {client.critical_findings} CRIT
            </span>
          )}
        </div>

        {/* Metrics row */}
        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-xl font-bold text-gray-900">{client.run_count ?? '—'}</p>
            <p className="text-xs text-gray-400 mt-0.5">análisis</p>
          </div>
          <div>
            <p className="text-xl font-bold text-gray-900">{client.critical_findings}</p>
            <p className="text-xs text-gray-400 mt-0.5">críticos</p>
          </div>
          <div className="flex flex-col items-center gap-1">
            <DQBadge score={client.avg_dq_score} />
            <TrendBadge trend={client.dq_trend} />
          </div>
        </div>

        {/* Footer */}
        <div className="mt-auto pt-3 border-t border-gray-50 flex items-center justify-between text-xs text-gray-400">
          <span>Último: {formatDate(client.last_run)}</span>
          <span className="text-violet-600 font-medium">Ver detalle →</span>
        </div>
      </div>
    </Link>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyClients() {
  return (
    <div className="col-span-full flex flex-col items-center justify-center py-20 text-center">
      <div className="p-4 rounded-2xl bg-violet-50 mb-4">
        <svg className="h-10 w-10 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
          />
        </svg>
      </div>
      <h3 className="text-lg font-semibold text-gray-900">Sin clientes todavía</h3>
      <p className="text-sm text-gray-500 mt-1 max-w-sm">
        Ejecuta tu primer análisis para que un cliente aparezca aquí.
      </p>
      <Link
        href="/new-analysis"
        className="mt-5 inline-flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
      >
        Nuevo análisis
      </Link>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ClientsPage() {
  const [clients, setClients] = useState<ClientComparison[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/api/clients/comparison`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data: { clients: ClientComparison[] } | ClientComparison[]) => {
        const list = Array.isArray(data) ? data : (data as { clients: ClientComparison[] }).clients || []
        setClients(list)
      })
      .catch(err => setError(err.message || 'Error cargando clientes'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* ── Header ── */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Clientes</h1>
            {!loading && (
              <p className="text-sm text-gray-500 mt-0.5">
                {clients.length} cliente{clients.length !== 1 ? 's' : ''} activo{clients.length !== 1 ? 's' : ''}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/dashboard"
              className="text-sm text-gray-500 hover:text-violet-600 transition-colors"
            >
              Dashboard
            </Link>
            <Link
              href="/new-analysis"
              className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl shadow-sm transition-colors"
            >
              Nuevo análisis
            </Link>
          </div>
        </div>

        {/* ── Error state ── */}
        {error && (
          <div className="mb-6 bg-red-50 border border-red-200 text-red-700 rounded-xl px-5 py-3 text-sm">
            Error al cargar clientes: {error}
          </div>
        )}

        {/* ── Grid ── */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {loading ? (
            <>
              {[1, 2, 3, 4, 5, 6].map(i => (
                <SkeletonCard key={i} hasHeader hasStats lines={2} />
              ))}
            </>
          ) : clients.length === 0 ? (
            <EmptyClients />
          ) : (
            clients.map(client => (
              <ClientCard key={client.client_name ?? (client as any).name} client={client} />
            ))
          )}
        </div>
      </div>
    </div>
  )
}
