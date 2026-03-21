'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import SkeletonCard from '@/components/SkeletonCard'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface ClientComparison {
  client_name?: string
  name?: string
  avg_dq_score: number
  dq_trend: string
  critical_findings: number
  last_run: string
  industry: string
  run_count?: number
}

function dqColor(score: number | null): string {
  if (score === null || score === undefined) return T.text.tertiary
  if (score >= 90) return T.accent.teal
  if (score >= 75) return T.accent.yellow
  if (score >= 50) return T.accent.orange
  return T.accent.red
}

function DQBadge({ score }: { score: number | null }) {
  const color = dqColor(score)
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      fontSize: 11,
      fontWeight: 600,
      fontFamily: T.font.mono,
      padding: '2px 10px',
      borderRadius: 999,
      backgroundColor: color + '15',
      border: `1px solid ${color}40`,
      color,
    }}>
      DQ {score ?? '—'}
    </span>
  )
}

function TrendBadge({ trend }: { trend?: string }) {
  const isImproving = trend === 'improving'
  const isDeclining = trend === 'declining' || trend === 'degrading'
  const color = isImproving ? T.accent.teal : isDeclining ? T.accent.red : T.text.tertiary
  const label = isImproving ? '↑ Mejorando' : isDeclining ? '↓ Bajando' : '→ Estable'
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      fontSize: 11,
      fontWeight: 500,
      padding: '2px 8px',
      borderRadius: 999,
      backgroundColor: color + '10',
      border: `1px solid ${color}30`,
      color,
    }}>
      {label}
    </span>
  )
}

function ClientCard({ client }: { client: ClientComparison }) {
  const name = client.client_name ?? (client as any).name ?? ''
  const formatDate = (iso: string) => {
    if (!iso) return 'Nunca'
    try {
      return new Date(iso).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' })
    } catch { return iso }
  }

  return (
    <Link href={`/clients/${encodeURIComponent(name)}`} style={{ textDecoration: 'none', display: 'block' }}>
      <div style={{
        backgroundColor: T.bg.card,
        borderRadius: T.radius.md,
        border: T.border.card,
        padding: T.space.lg,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.md,
        cursor: 'pointer',
        transition: 'border-color 150ms ease',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ minWidth: 0 }}>
            <h3 style={{ fontWeight: 600, color: T.text.primary, fontSize: 14, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {name}
            </h3>
            {client.industry && (
              <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {client.industry}
              </p>
            )}
          </div>
          {client.critical_findings > 0 && (
            <span style={{
              flexShrink: 0,
              fontSize: 10,
              fontWeight: 700,
              fontFamily: T.font.mono,
              padding: '2px 8px',
              borderRadius: 999,
              backgroundColor: T.accent.red + '15',
              border: `1px solid ${T.accent.red}40`,
              color: T.accent.red,
            }}>
              {client.critical_findings} CRIT
            </span>
          )}
        </div>

        {/* Metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, textAlign: 'center' }}>
          {[
            { value: client.run_count ?? '—', label: 'análisis' },
            { value: client.critical_findings, label: 'críticos' },
          ].map(({ value, label }) => (
            <div key={label}>
              <p style={{ fontSize: 20, fontWeight: 700, color: T.text.primary, margin: 0, fontFamily: T.font.mono }}>{value}</p>
              <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2 }}>{label}</p>
            </div>
          ))}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <DQBadge score={client.avg_dq_score} />
            <TrendBadge trend={client.dq_trend} />
          </div>
        </div>

        {/* Footer */}
        <div style={{ marginTop: 'auto', paddingTop: T.space.sm, borderTop: T.border.subtle, display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11 }}>
          <span style={{ color: T.text.tertiary }}>Último: {formatDate(client.last_run)}</span>
          <span style={{ color: T.accent.teal, fontWeight: 500 }}>Ver detalle →</span>
        </div>
      </div>
    </Link>
  )
}

function EmptyClients() {
  return (
    <div style={{ gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: `${T.space.xxl} ${T.space.lg}`, textAlign: 'center' }}>
      <div style={{ padding: T.space.md, borderRadius: T.radius.md, backgroundColor: T.accent.teal + '10', marginBottom: T.space.md }}>
        <svg width="40" height="40" fill="none" viewBox="0 0 24 24" stroke={T.accent.teal} strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"
          />
        </svg>
      </div>
      <h3 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, margin: '0 0 8px' }}>Sin clientes todavía</h3>
      <p style={{ fontSize: 13, color: T.text.secondary, maxWidth: 360, margin: '0 0 20px' }}>
        Ejecuta tu primer análisis para que un cliente aparezca aquí.
      </p>
      <Link href="/new-analysis" className="d4c-btn-primary">Nuevo análisis</Link>
    </div>
  )
}

export default function ClientsPage() {
  const [clients, setClients] = useState<ClientComparison[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/api/clients/comparison`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((data: { clients: ClientComparison[] } | ClientComparison[]) => {
        const list = Array.isArray(data) ? data : (data as { clients: ClientComparison[] }).clients || []
        setClients(list)
      })
      .catch(err => setError(err.message || 'Error cargando clientes'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div style={{ minHeight: '100vh', padding: T.space.xl }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.xl }}>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, margin: 0 }}>Clientes</h1>
            {!loading && (
              <p style={{ fontSize: 12, color: T.text.secondary, marginTop: 4 }}>
                {clients.length} cliente{clients.length !== 1 ? 's' : ''} activo{clients.length !== 1 ? 's' : ''}
              </p>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
            <Link href="/dashboard" style={{ fontSize: 12, color: T.text.secondary, textDecoration: 'none' }}>Dashboard</Link>
            <Link href="/new-analysis" className="d4c-btn-primary">Nuevo análisis</Link>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div style={{
            marginBottom: T.space.lg,
            backgroundColor: T.accent.red + '10',
            border: `1px solid ${T.accent.red}30`,
            color: T.accent.red,
            borderRadius: T.radius.sm,
            padding: `${T.space.sm} ${T.space.md}`,
            fontSize: 13,
          }}>
            Error al cargar clientes: {error}
          </div>
        )}

        {/* Grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: T.space.md }}>
          {loading ? (
            [1, 2, 3, 4, 5, 6].map(i => <SkeletonCard key={i} hasHeader hasStats lines={2} />)
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
