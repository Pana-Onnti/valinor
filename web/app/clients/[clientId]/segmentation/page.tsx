'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, Trophy, TrendingUp, Clock, AlertTriangle } from 'lucide-react'
import Link from 'next/link'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Segment {
  name: string
  count: number
  pct_of_total: number
  revenue_share: number
  avg_revenue: number
}

interface SegmentationData {
  client_name: string
  total_customers: number
  currency: string | null
  segments: Segment[]
}

const SEGMENT_META: Record<string, { icon: React.ElementType; color: string; barColor: string }> = {
  Champions: {
    icon: Trophy,
    color: T.accent.yellow,
    barColor: T.accent.yellow,
  },
  Growth: {
    icon: TrendingUp,
    color: T.accent.teal,
    barColor: T.accent.teal,
  },
  Maintenance: {
    icon: Clock,
    color: T.accent.blue,
    barColor: T.accent.blue,
  },
  'At-Risk': {
    icon: AlertTriangle,
    color: T.accent.red,
    barColor: T.accent.red,
  },
}

const STACKED_COLORS = [
  T.accent.teal,
  T.accent.blue,
  T.accent.orange,
  T.accent.yellow,
]

function formatCurrency(value: number, currency: string | null) {
  const symbol = currency ?? '$'
  if (value >= 1_000_000) return `${symbol}${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${symbol}${(value / 1_000).toFixed(0)}K`
  return `${symbol}${value.toFixed(0)}`
}

function SegmentCard({
  segment,
  i,
  currency,
}: {
  segment: Segment
  i: number
  currency: string | null
}) {
  const meta = SEGMENT_META[segment.name] ?? SEGMENT_META['Maintenance']
  const Icon = meta.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: i * 0.07 }}
      style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, padding: 20 }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ padding: 8, borderRadius: T.radius.md, backgroundColor: meta.color + '20' }}>
            <Icon style={{ height: 16, width: 16, color: meta.color }} />
          </div>
          <div>
            <p style={{ fontSize: 14, fontWeight: 600, color: T.text.primary, margin: 0 }}>{segment.name}</p>
            <p style={{ fontSize: 12, color: T.text.tertiary, marginTop: 2, marginBottom: 0 }}>
              {segment.count.toLocaleString('es')} clientes
            </p>
          </div>
        </div>
        <span style={{ fontSize: 12, fontWeight: 600, padding: '4px 10px', borderRadius: 999, border: `1px solid ${meta.color}40`, backgroundColor: meta.color + '20', color: meta.color }}>
          {segment.pct_of_total.toFixed(1)}%
        </span>
      </div>

      {/* Revenue share bar */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ fontSize: 12, color: T.text.tertiary }}>Revenue share</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: T.text.primary }}>
            {segment.revenue_share.toFixed(1)}%
          </span>
        </div>
        <div style={{ height: 8, backgroundColor: T.bg.elevated, borderRadius: 999, overflow: 'hidden' }}>
          <motion.div
            initial={{ width: 0 }}
            animate={{ width: `${segment.revenue_share}%` }}
            transition={{ delay: i * 0.07 + 0.2, duration: 0.6, ease: 'easeOut' }}
            style={{ height: '100%', backgroundColor: meta.barColor, borderRadius: 999 }}
          />
        </div>
      </div>

      {/* Avg revenue */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 12, borderTop: T.border.card }}>
        <span style={{ fontSize: 12, color: T.text.tertiary }}>Revenue promedio</span>
        <span style={{ fontSize: 14, fontWeight: 700, color: T.text.primary }}>
          {formatCurrency(segment.avg_revenue, currency)}
        </span>
      </div>
    </motion.div>
  )
}

export default function ClientSegmentationPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()
  const [data, setData] = useState<SegmentationData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchSegmentation = () => {
    setLoading(true)
    setError(null)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/segmentation`)
      .then(res => setData(res.data))
      .catch(err => setError(err.response?.data?.detail || 'Error cargando segmentación'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchSegmentation() }, [clientId])

  const tabs = [
    { label: 'Historial',      href: `/clients/${clientId}/history` },
    { label: 'Hallazgos',      href: `/clients/${clientId}/findings` },
    { label: 'Alertas',        href: `/clients/${clientId}/alerts` },
    { label: 'Costos',         href: `/clients/${clientId}/costs` },
    { label: 'Segmentación',   href: `/clients/${clientId}/segmentation` },
  ]

  const clientName = data?.client_name ?? clientId

  if (loading) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: 32 }}>
      <div style={{ maxWidth: 1152, margin: '0 auto' }}>
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 192, marginBottom: 24 }} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
          {[...Array(4)].map((_, i) => (
            <div key={i} style={{ height: 160, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
          ))}
        </div>
        <div style={{ height: 80, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
      </div>
    </div>
  )

  if (error || !data) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ color: T.text.secondary, marginBottom: 16 }}>{error || 'No hay datos de segmentación para este cliente'}</p>
        <Link href={`/clients/${clientId}/history`} style={{ color: T.accent.teal, fontSize: 14 }}>
          ← Volver al historial
        </Link>
      </div>
    </div>
  )

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Header */}
      <header style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 1152, margin: '0 auto', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
            <Link
              href="/"
              style={{ color: T.text.tertiary }}
            >
              <ArrowLeft size={20} />
            </Link>
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0 }}>{clientName}</h1>
              <p style={{ fontSize: 12, color: T.text.tertiary, margin: 0 }}>
                {data.total_customers.toLocaleString('es')} clientes totales
                {data.currency ? ` · ${data.currency}` : ''}
              </p>
            </div>
          </div>
          <button
            onClick={fetchSegmentation}
            className="d4c-btn-ghost"
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', fontSize: 14 }}
          >
            <RefreshCw size={14} />Actualizar
          </button>
        </div>

        {/* Tab navigation */}
        <div style={{ maxWidth: 1152, margin: '0 auto', padding: '0 24px' }}>
          <nav style={{ display: 'flex', gap: 4 }}>
            {tabs.map(tab => {
              const isActive = pathname === tab.href
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  style={isActive
                    ? { borderBottom: `2px solid ${T.accent.teal}`, color: T.accent.teal, padding: '10px 16px', fontSize: 13, fontWeight: 600, textDecoration: 'none', display: 'inline-block' }
                    : { borderBottom: '2px solid transparent', color: T.text.tertiary, padding: '10px 16px', fontSize: 13, fontWeight: 600, textDecoration: 'none', display: 'inline-block' }
                  }
                >
                  {tab.label}
                </Link>
              )
            })}
          </nav>
        </div>
      </header>

      <main style={{ maxWidth: 1152, margin: '0 auto', padding: '32px 24px' }}>
        {/* Section title */}
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 4 }}>
            Segmentación de Clientes
          </h2>
          <p style={{ fontSize: 14, color: T.text.secondary, margin: 0 }}>
            Distribución por segmento de valor · {data.total_customers.toLocaleString('es')} clientes
          </p>
        </div>

        {/* Segment cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 32 }}>
          {data.segments.map((segment, i) => (
            <SegmentCard
              key={segment.name}
              segment={segment}
              i={i}
              currency={data.currency}
            />
          ))}
        </div>

        {/* Stacked bar — Distribución de Revenue */}
        <div>
          <h2 style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 16 }}>
            Distribución de Revenue
          </h2>
          <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, padding: 24 }}>
            {/* Stacked bar */}
            <div style={{ display: 'flex', height: 40, borderRadius: T.radius.md, overflow: 'hidden', gap: 2, marginBottom: 20 }}>
              {data.segments.map((segment, i) => (
                <motion.div
                  key={segment.name}
                  initial={{ flex: 0 }}
                  animate={{ flex: segment.revenue_share }}
                  transition={{ delay: i * 0.08 + 0.1, duration: 0.7, ease: 'easeOut' }}
                  style={{ backgroundColor: STACKED_COLORS[i % STACKED_COLORS.length] }}
                  title={`${segment.name}: ${segment.revenue_share.toFixed(1)}%`}
                />
              ))}
            </div>

            {/* Legend */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px 24px' }}>
              {data.segments.map((segment, i) => {
                const meta = SEGMENT_META[segment.name] ?? SEGMENT_META['Maintenance']
                const Icon = meta.icon
                return (
                  <div key={segment.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 12, height: 12, borderRadius: 2, flexShrink: 0, backgroundColor: STACKED_COLORS[i % STACKED_COLORS.length], display: 'inline-block' }} />
                    <Icon style={{ height: 14, width: 14, color: meta.color }} />
                    <span style={{ fontSize: 14, color: T.text.primary, fontWeight: 500 }}>
                      {segment.name}
                    </span>
                    <span style={{ fontSize: 14, color: T.text.tertiary }}>
                      {segment.revenue_share.toFixed(1)}%
                    </span>
                  </div>
                )
              })}
            </div>

            {/* Summary row */}
            <div style={{ marginTop: 20, paddingTop: 20, borderTop: T.border.card, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
              {data.segments.map(segment => (
                <div key={segment.name} style={{ textAlign: 'center' }}>
                  <p style={{ fontSize: 12, color: T.text.tertiary, marginBottom: 4 }}>{segment.name}</p>
                  <p style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: '0 0 2px' }}>
                    {formatCurrency(segment.avg_revenue, data.currency)}
                  </p>
                  <p style={{ fontSize: 12, color: T.text.tertiary, margin: 0 }}>avg / cliente</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
