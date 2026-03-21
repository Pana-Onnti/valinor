'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, TrendingUp, TrendingDown, Minus, BarChart2 } from 'lucide-react'
import Link from 'next/link'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface KPIDataPoint {
  period: string
  value: string
  numeric_value: number | null
  run_date: string
}

interface KPIsResponse {
  client_name: string
  kpis: Record<string, KPIDataPoint[]>
  kpi_count: number
  earliest_period: string | null
  latest_period: string | null
}

function TrendIndicator({ points }: { points: KPIDataPoint[] }) {
  const numeric = points.filter(p => p.numeric_value !== null)
  if (numeric.length < 2) {
    return <Minus style={{ width: 16, height: 16, color: T.text.tertiary }} />
  }
  const last = numeric[numeric.length - 1].numeric_value as number
  const prev = numeric[numeric.length - 2].numeric_value as number
  if (last > prev) {
    return <TrendingUp style={{ width: 16, height: 16, color: T.accent.teal }} />
  } else if (last < prev) {
    return <TrendingDown style={{ width: 16, height: 16, color: T.accent.red }} />
  }
  return <Minus style={{ width: 16, height: 16, color: T.text.tertiary }} />
}

function MiniBarChart({ points }: { points: KPIDataPoint[] }) {
  const numeric = points.filter(p => p.numeric_value !== null)
  if (numeric.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 48 }}>
        <span style={{ fontSize: 11, color: T.text.secondary }}>Sin datos numéricos</span>
      </div>
    )
  }

  const values = numeric.map(p => p.numeric_value as number)
  const max = Math.max(...values)
  const min = Math.min(...values)
  const range = max - min

  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 48, overflowX: 'auto', paddingBottom: 4 }}>
      {numeric.map((point, i) => {
        const heightPct = range === 0
          ? 50
          : ((point.numeric_value as number - min) / range) * 80 + 20
        const isLast = i === numeric.length - 1
        return (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0, minWidth: 18 }}>
            <div
              title={`${point.period}: ${point.value}`}
              style={{
                width: 12,
                borderRadius: '2px 2px 0 0',
                backgroundColor: isLast ? T.accent.teal : T.bg.hover,
                height: `${heightPct}%`,
                transition: 'all 0.2s',
              }}
            />
            <span
              style={{
                color: T.text.tertiary,
                marginTop: 4,
                lineHeight: 1,
                fontSize: '8px',
                transform: 'rotate(45deg)',
                transformOrigin: 'left center',
                display: 'block',
                width: 18,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'clip',
              }}
            >
              {point.period}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function KPICard({ label, points, index }: { label: string; points: KPIDataPoint[]; index: number }) {
  const latest = points[points.length - 1]
  const numeric = points.filter(p => p.numeric_value !== null)
  const latestNumeric = numeric.length > 0 ? numeric[numeric.length - 1] : null

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      style={{
        backgroundColor: T.bg.card,
        borderRadius: T.radius.lg,
        border: T.border.card,
        padding: T.space.lg,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.sm,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: T.space.sm }}>
        <p style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.05em', lineHeight: 1.4, flex: 1, margin: 0 }}>
          {label}
        </p>
        <TrendIndicator points={points} />
      </div>

      {/* Latest value */}
      <div>
        <p style={{ fontSize: 24, fontWeight: 700, color: T.text.primary, lineHeight: 1, margin: 0 }}>
          {latest ? latest.value : '—'}
        </p>
        {latest && (
          <p style={{ fontSize: 11, color: T.text.secondary, marginTop: 4, marginBottom: 0 }}>{latest.period}</p>
        )}
      </div>

      {/* Mini bar chart */}
      <div style={{ paddingTop: 4, paddingBottom: 18 }}>
        <MiniBarChart points={points} />
      </div>

      {/* Footer */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontSize: 11,
        color: T.text.secondary,
        borderTop: T.border.card,
        paddingTop: T.space.sm,
      }}>
        <span>{points.length} período{points.length !== 1 ? 's' : ''}</span>
        {latestNumeric && (
          <span style={{ fontFamily: T.font.mono, color: T.text.tertiary }}>{latestNumeric.numeric_value}</span>
        )}
      </div>
    </motion.div>
  )
}

export default function ClientKPIsPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()
  const [data, setData] = useState<KPIsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchKPIs = () => {
    setLoading(true)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/kpis`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Error cargando KPIs'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchKPIs() }, [clientId])

  if (loading) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xxl }}>
      <div style={{ maxWidth: 1152, margin: '0 auto' }}>
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 192, marginBottom: T.space.xl }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.lg }}>
          {[...Array(8)].map((_, i) => (
            <div key={i} style={{ height: 176, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
          ))}
        </div>
      </div>
    </div>
  )

  if (error || !data) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ color: T.text.secondary, marginBottom: T.space.lg }}>{error || 'No hay datos para este cliente'}</p>
        <Link href="/" style={{ color: T.accent.teal, fontSize: 13, textDecoration: 'none' }}>← Volver</Link>
      </div>
    </div>
  )

  const kpiEntries = Object.entries(data.kpis)

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
        <div style={{ maxWidth: 1152, margin: '0 auto', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}>
            <Link href="/" style={{ color: T.text.tertiary, display: 'flex', alignItems: 'center' }}>
              <ArrowLeft style={{ width: 20, height: 20 }} />
            </Link>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0 }}>{data.client_name}</h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
                {data.kpi_count} KPI{data.kpi_count !== 1 ? 's' : ''}
                {data.earliest_period && data.latest_period
                  ? ` · ${data.earliest_period} → ${data.latest_period}`
                  : ''}
              </p>
            </div>
          </div>
          <button
            onClick={fetchKPIs}
            className="d4c-btn-ghost"
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
          >
            <RefreshCw style={{ width: 14, height: 14 }} />Actualizar
          </button>
        </div>

        {/* Tab navigation */}
        <div style={{ maxWidth: 1152, margin: '0 auto', padding: '0 24px' }}>
          <nav style={{ display: 'flex', gap: 4, overflowX: 'auto' }}>
            {[
              { label: 'Historial', href: `/clients/${clientId}/history` },
              { label: 'Hallazgos', href: `/clients/${clientId}/findings` },
              { label: 'Alertas',   href: `/clients/${clientId}/alerts` },
              { label: 'Costos',    href: `/clients/${clientId}/costs` },
              { label: 'KPIs',      href: `/clients/${clientId}/kpis` },
            ].map(tab => {
              const isActive = pathname === tab.href
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  style={isActive
                    ? { borderBottom: `2px solid ${T.accent.teal}`, color: T.accent.teal, padding: '10px 16px', fontSize: 13, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap' }
                    : { borderBottom: '2px solid transparent', color: T.text.tertiary, padding: '10px 16px', fontSize: 13, fontWeight: 600, textDecoration: 'none', whiteSpace: 'nowrap' }}
                >
                  {tab.label}
                </Link>
              )
            })}
          </nav>
        </div>
      </header>

      <main style={{ maxWidth: 1152, margin: '0 auto', padding: '32px 24px' }}>
        {/* Summary bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, marginBottom: T.space.xxl }}>
          <div style={{
            padding: T.space.sm,
            borderRadius: T.radius.md,
            backgroundColor: T.accent.teal + '15',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <BarChart2 style={{ width: 16, height: 16, color: T.accent.teal }} />
          </div>
          <div>
            <p style={{ fontSize: 13, fontWeight: 600, color: T.text.primary, margin: 0 }}>
              {data.kpi_count} KPI{data.kpi_count !== 1 ? 's' : ''} rastreados
            </p>
            {data.earliest_period && data.latest_period && (
              <p style={{ fontSize: 11, color: T.text.secondary, margin: 0 }}>
                Desde {data.earliest_period} hasta {data.latest_period}
              </p>
            )}
          </div>
        </div>

        {/* KPI grid */}
        {kpiEntries.length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.lg }}>
            {kpiEntries.map(([label, points], i) => (
              <KPICard key={label} label={label} points={points} index={i} />
            ))}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '96px 0', textAlign: 'center' }}>
            <BarChart2 style={{ width: 40, height: 40, color: T.text.tertiary, marginBottom: T.space.lg }} />
            <p style={{ color: T.text.secondary, fontSize: 13, margin: 0 }}>No hay KPIs registrados para este cliente aún.</p>
            <p style={{ color: T.text.tertiary, fontSize: 11, marginTop: 4, marginBottom: 0 }}>
              Los KPIs se extraen automáticamente en cada análisis.
            </p>
          </div>
        )}
      </main>
    </div>
  )
}
