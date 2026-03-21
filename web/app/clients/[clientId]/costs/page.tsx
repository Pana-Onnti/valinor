'use client'

import { useEffect, useState } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import { ArrowLeft, RefreshCw, DollarSign, TrendingUp, Calendar, BarChart2 } from 'lucide-react'
import Link from 'next/link'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const COST_PER_RUN = 8

interface CostData {
  client_id: string
  total_runs: number
  total_cost_usd: number
  avg_cost_per_run: number
  runs_this_month: number
  cost_this_month: number
  cost_by_month: Array<{
    month: string
    runs: number
    cost: number
  }>
}

interface RunHistoryEntry {
  run_date: string
  period: string
  success: boolean
  findings_count: number
  new: number
  resolved: number
  dq_score?: number
}

interface ClientProfileData {
  client_name: string
  run_count: number
  industry_inferred: string | null
  currency_detected: string | null
  run_history: RunHistoryEntry[]
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent = 'teal',
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  accent?: 'teal' | 'yellow' | 'blue'
}) {
  const accentMap = {
    teal: T.accent.teal,
    yellow: T.accent.yellow,
    blue: T.accent.blue,
  }
  const color = accentMap[accent]
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
          borderRadius: T.radius.md,
          backgroundColor: color + '15',
          color: color,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          <Icon style={{ width: 16, height: 16 }} />
        </div>
        <div>
          <p style={{ fontSize: 11, color: T.text.tertiary, marginBottom: 4 }}>{label}</p>
          <p style={{ fontSize: 24, fontWeight: 700, color: T.text.primary, lineHeight: 1 }}>{value}</p>
          {sub && <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 2 }}>{sub}</p>}
        </div>
      </div>
    </div>
  )
}

function RunCostBar({ run, maxCost, i }: { run: RunHistoryEntry; maxCost: number; i: number }) {
  const cost = COST_PER_RUN
  const widthPct = maxCost > 0 ? (cost / maxCost) * 100 : 100
  const date = new Date(run.run_date).toLocaleDateString('es', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: i * 0.05 }}
      style={{ display: 'flex', alignItems: 'center', gap: T.space.xl, paddingTop: 10, paddingBottom: 10 }}
    >
      {/* Date + period */}
      <div style={{ width: 144, flexShrink: 0 }}>
        <p style={{ fontSize: 11, fontFamily: T.font.mono, color: T.text.tertiary }}>{run.period}</p>
        <p style={{ fontSize: 11, color: T.text.secondary }}>{date}</p>
      </div>

      {/* Bar */}
      <div style={{
        flex: 1,
        height: 28,
        backgroundColor: T.bg.elevated,
        borderRadius: T.radius.md,
        overflow: 'hidden',
        position: 'relative',
      }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${widthPct}%` }}
          transition={{ duration: 0.5, delay: i * 0.05, ease: 'easeOut' }}
          style={{
            height: '100%',
            borderRadius: T.radius.md,
            backgroundColor: run.success ? T.accent.teal : T.accent.red,
          }}
        />
        <span style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          paddingLeft: 10,
          fontSize: 11,
          fontWeight: 600,
          color: T.text.primary,
          pointerEvents: 'none',
        }}>
          ${cost.toFixed(2)}
        </span>
      </div>

      {/* Status badge */}
      <div style={{ width: 96, flexShrink: 0, textAlign: 'right' }}>
        {run.success ? (
          <span style={{
            fontSize: 11,
            color: T.accent.teal,
            backgroundColor: T.accent.teal + '15',
            padding: '2px 8px',
            borderRadius: 999,
          }}>
            Exitoso
          </span>
        ) : (
          <span style={{
            fontSize: 11,
            color: T.accent.red,
            backgroundColor: T.accent.red + '15',
            padding: '2px 8px',
            borderRadius: 999,
          }}>
            Fallido
          </span>
        )}
      </div>
    </motion.div>
  )
}

export default function ClientCostsPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  const [costs, setCosts] = useState<CostData | null>(null)
  const [profile, setProfile] = useState<ClientProfileData | null>(null)
  const [loadingCosts, setLoadingCosts] = useState(true)
  const [loadingProfile, setLoadingProfile] = useState(true)
  const [errorCosts, setErrorCosts] = useState<string | null>(null)
  const [errorProfile, setErrorProfile] = useState<string | null>(null)

  const fetchCosts = () => {
    setLoadingCosts(true)
    setErrorCosts(null)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/costs`)
      .then(res => setCosts(res.data))
      .catch(err => {
        // If endpoint not yet implemented, derive costs from profile
        setErrorCosts(err.response?.data?.detail || 'endpoint_missing')
      })
      .finally(() => setLoadingCosts(false))
  }

  const fetchProfile = () => {
    setLoadingProfile(true)
    setErrorProfile(null)
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
      .then(res => setProfile(res.data))
      .catch(err => setErrorProfile(err.response?.data?.detail || 'Error cargando perfil'))
      .finally(() => setLoadingProfile(false))
  }

  const handleRefresh = () => {
    fetchCosts()
    fetchProfile()
  }

  useEffect(() => {
    fetchCosts()
    fetchProfile()
  }, [clientId])

  // Derive cost summary from profile when the /costs endpoint is unavailable
  const derivedCosts: CostData | null =
    costs ??
    (profile
      ? (() => {
          const runs = profile.run_history
          const now = new Date()
          const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
          const runsThisMonth = runs.filter(r => r.run_date.startsWith(currentMonth))

          // Group by month
          const byMonth: Record<string, { runs: number; cost: number }> = {}
          runs.forEach(r => {
            const m = r.run_date.slice(0, 7)
            if (!byMonth[m]) byMonth[m] = { runs: 0, cost: 0 }
            byMonth[m].runs += 1
            byMonth[m].cost += COST_PER_RUN
          })

          return {
            client_id: clientId,
            total_runs: profile.run_count,
            total_cost_usd: profile.run_count * COST_PER_RUN,
            avg_cost_per_run: COST_PER_RUN,
            runs_this_month: runsThisMonth.length,
            cost_this_month: runsThisMonth.length * COST_PER_RUN,
            cost_by_month: Object.entries(byMonth)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([month, v]) => ({ month, ...v })),
          }
        })()
      : null)

  const loading = loadingCosts && loadingProfile
  const isError = !loading && errorProfile && !profile

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xxl }}>
        <div style={{ maxWidth: 1152, margin: '0 auto' }}>
          <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 192, marginBottom: T.space.xl }} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.lg, marginBottom: T.space.xl }}>
            {[...Array(4)].map((_, i) => (
              <div key={i} style={{ height: 96, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
            ))}
          </div>
          <div style={{ height: 256, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: T.text.secondary, marginBottom: T.space.lg }}>{errorProfile || 'No hay datos para este cliente'}</p>
          <Link href="/" style={{ color: T.accent.teal, fontSize: 13, textDecoration: 'none' }}>
            ← Volver
          </Link>
        </div>
      </div>
    )
  }

  const clientName = profile?.client_name ?? clientId
  const industry = profile?.industry_inferred
  const currency = profile?.currency_detected
  const recentRuns = [...(profile?.run_history ?? [])].reverse().slice(0, 10)

  const tabs = [
    { label: 'Historial', href: `/clients/${clientId}/history` },
    { label: 'Hallazgos', href: `/clients/${clientId}/findings` },
    { label: 'Alertas', href: `/clients/${clientId}/alerts` },
    { label: 'Costos', href: `/clients/${clientId}/costs` },
  ]

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
              <h1 style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0 }}>{clientName}</h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
                {[industry, currency].filter(Boolean).join(' · ')}
              </p>
            </div>
          </div>
          <button
            onClick={handleRefresh}
            className="d4c-btn-ghost"
            style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
          >
            <RefreshCw style={{ width: 14, height: 14 }} />
            Actualizar
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

        {/* Summary cards */}
        {derivedCosts && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: T.space.lg, marginBottom: T.space.xxl }}>
            <StatCard
              icon={BarChart2}
              label="Total Runs"
              value={derivedCosts.total_runs}
              sub="desde el inicio"
              accent="blue"
            />
            <StatCard
              icon={DollarSign}
              label="Costo Total"
              value={`$${derivedCosts.total_cost_usd.toFixed(2)}`}
              sub="USD estimado"
              accent="teal"
            />
            <StatCard
              icon={TrendingUp}
              label="Costo Promedio"
              value={`$${derivedCosts.avg_cost_per_run.toFixed(2)}`}
              sub="por análisis"
              accent="yellow"
            />
            <StatCard
              icon={Calendar}
              label="Este Mes"
              value={`$${derivedCosts.cost_this_month.toFixed(2)}`}
              sub={`${derivedCosts.runs_this_month} run${derivedCosts.runs_this_month !== 1 ? 's' : ''}`}
              accent="teal"
            />
          </div>
        )}

        {/* Monthly cost summary */}
        {derivedCosts && derivedCosts.cost_by_month.length > 0 && (
          <div style={{ marginBottom: T.space.xxl }}>
            <h2 style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.sm }}>
              Costo por Mes
            </h2>
            <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, padding: T.space.lg }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
                {(() => {
                  const maxMonthCost = Math.max(...derivedCosts.cost_by_month.map(m => m.cost), 1)
                  return derivedCosts.cost_by_month
                    .slice()
                    .reverse()
                    .map((entry, i) => {
                      const pct = (entry.cost / maxMonthCost) * 100
                      const [year, month] = entry.month.split('-')
                      const label = new Date(Number(year), Number(month) - 1, 1).toLocaleDateString(
                        'es',
                        { month: 'long', year: 'numeric' }
                      )
                      return (
                        <motion.div
                          key={entry.month}
                          initial={{ opacity: 0, x: -8 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: i * 0.06 }}
                          style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}
                        >
                          <span style={{ width: 128, fontSize: 11, color: T.text.secondary, textTransform: 'capitalize', flexShrink: 0 }}>
                            {label}
                          </span>
                          <div style={{
                            flex: 1,
                            height: 24,
                            backgroundColor: T.bg.elevated,
                            borderRadius: T.radius.md,
                            overflow: 'hidden',
                            position: 'relative',
                          }}>
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${pct}%` }}
                              transition={{ duration: 0.5, delay: i * 0.06, ease: 'easeOut' }}
                              style={{ height: '100%', borderRadius: T.radius.md, backgroundColor: T.accent.teal }}
                            />
                          </div>
                          <div style={{ width: 112, flexShrink: 0, textAlign: 'right' }}>
                            <p style={{ fontSize: 13, fontWeight: 600, color: T.text.primary, margin: 0 }}>
                              ${entry.cost.toFixed(2)}
                            </p>
                            <p style={{ fontSize: 11, color: T.text.tertiary, margin: 0 }}>
                              {entry.runs} run{entry.runs !== 1 ? 's' : ''}
                            </p>
                          </div>
                        </motion.div>
                      )
                    })
                })()}
              </div>
            </div>
          </div>
        )}

        {/* Last 10 runs bar chart */}
        {recentRuns.length > 0 && (
          <div style={{ marginBottom: T.space.xxl }}>
            <h2 style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.sm }}>
              Últimos 10 Runs — Costo por Ejecución
            </h2>
            <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, padding: T.space.lg }}>
              {/* Column headers */}
              <div style={{ display: 'flex', alignItems: 'center', gap: T.space.xl, paddingBottom: T.space.sm, borderBottom: T.border.card, marginBottom: T.space.sm }}>
                <span style={{ width: 144, flexShrink: 0, fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Período / Fecha
                </span>
                <span style={{ flex: 1, fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Costo (USD)
                </span>
                <span style={{ width: 96, flexShrink: 0, fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', textAlign: 'right' }}>
                  Estado
                </span>
              </div>

              <div>
                {recentRuns.map((run, i) => (
                  <RunCostBar key={i} run={run} maxCost={COST_PER_RUN} i={i} />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Note about estimation */}
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: T.space.sm,
          padding: T.space.lg,
          backgroundColor: T.accent.yellow + '10',
          border: `1px solid ${T.accent.yellow}30`,
          borderRadius: T.radius.md,
        }}>
          <span style={{ color: T.accent.yellow, fontSize: 13, marginTop: 2 }}>*</span>
          <p style={{ fontSize: 11, color: T.accent.yellow, margin: 0 }}>
            Los costos son estimados basados en ~${COST_PER_RUN} USD por análisis (Claude API + infraestructura).
            El costo real puede variar según la complejidad de la base de datos y número de agentes utilizados.
          </p>
        </div>

      </main>
    </div>
  )
}
