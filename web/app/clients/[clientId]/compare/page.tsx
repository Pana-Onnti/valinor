'use client'

import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import Link from 'next/link'
import { ArrowLeft, ArrowRight, TrendingUp, TrendingDown, Minus, AlertOctagon, CheckCircle2 } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface RunSummary {
  run_date: string
  period: string
  findings_count: number
  new: number
  resolved: number
  success: boolean
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric' })
}

function CompareCell({ labelA, labelB, label, type = 'number' }: {
  labelA: string | number
  labelB: string | number
  label: string
  type?: 'number' | 'text' | 'status'
}) {
  const numA = typeof labelA === 'number' ? labelA : parseFloat(String(labelA)) || 0
  const numB = typeof labelB === 'number' ? labelB : parseFloat(String(labelB)) || 0

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', alignItems: 'center', padding: '12px 20px' }}>
      <div style={{ textAlign: 'center', fontSize: 14, fontWeight: 600, color: numA > numB ? T.accent.orange : T.text.primary }}>
        {labelA}
      </div>
      <div style={{ textAlign: 'center', fontSize: 12, color: T.text.tertiary, fontWeight: 500 }}>{label}</div>
      <div style={{ textAlign: 'center', fontSize: 14, fontWeight: 600, color: numB > numA ? T.accent.orange : T.text.primary }}>
        {labelB}
      </div>
    </div>
  )
}

export default function RunComparePage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const clientId = params.clientId as string
  const [profile, setProfile] = useState<any>(null)
  const [selectedA, setSelectedA] = useState<number | null>(null)
  const [selectedB, setSelectedB] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
      .then(res => {
        setProfile(res.data)
        const runs = res.data.run_history || []
        if (runs.length >= 2) {
          setSelectedA(runs.length - 2)
          setSelectedB(runs.length - 1)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [clientId])

  if (loading) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ position: 'relative', height: 48, width: 48 }}>
        <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', border: `4px solid ${T.bg.elevated}` }} />
        <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', border: `4px solid transparent`, borderTopColor: T.accent.teal, animation: 'spin 1s linear infinite' }} />
      </div>
    </div>
  )

  const runs: RunSummary[] = profile?.run_history || []
  const runA = selectedA !== null ? runs[selectedA] : null
  const runB = selectedB !== null ? runs[selectedB] : null
  const kpiLabels = Object.keys(profile?.baseline_history || {})

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      <header style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 960, margin: '0 auto', padding: '16px 24px', display: 'flex', alignItems: 'center', gap: 16 }}>
          <Link href={`/clients/${clientId}/history`} style={{ color: T.text.tertiary }}>
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, margin: 0 }}>{clientId.replace(/_/g, ' ')}</h1>
            <p style={{ fontSize: 12, color: T.text.tertiary, margin: 0 }}>Comparación de runs</p>
          </div>
        </div>
      </header>

      <main style={{ maxWidth: 960, margin: '0 auto', padding: '32px 24px' }}>
        {runs.length < 2 ? (
          <div style={{ textAlign: 'center', paddingTop: 80, paddingBottom: 80 }}>
            <p style={{ color: T.text.tertiary }}>Se necesitan al menos 2 runs para comparar.</p>
            <Link href={`/clients/${clientId}/history`} style={{ color: T.accent.teal, fontSize: 14, marginTop: 8, display: 'inline-block' }}>← Ver historial</Link>
          </div>
        ) : (
          <>
            {/* Run selectors */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 32, alignItems: 'center' }}>
              <div>
                <p style={{ fontSize: 11, fontWeight: 500, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Run anterior (A)</p>
                <select
                  value={selectedA ?? ''}
                  onChange={e => setSelectedA(Number(e.target.value))}
                  className="d4c-input"
                  style={{ width: '100%' }}
                >
                  {runs.map((r, i) => (
                    <option key={i} value={i}>{r.period} — {formatDate(r.run_date)}</option>
                  ))}
                </select>
              </div>
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <ArrowRight style={{ height: 20, width: 20, color: T.text.tertiary }} />
              </div>
              <div>
                <p style={{ fontSize: 11, fontWeight: 500, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Run actual (B)</p>
                <select
                  value={selectedB ?? ''}
                  onChange={e => setSelectedB(Number(e.target.value))}
                  className="d4c-input"
                  style={{ width: '100%' }}
                >
                  {runs.map((r, i) => (
                    <option key={i} value={i}>{r.period} — {formatDate(r.run_date)}</option>
                  ))}
                </select>
              </div>
            </div>

            {runA && runB && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                {/* Metrics comparison */}
                <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, overflow: 'hidden' }}>
                  {/* Header row */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', padding: '12px 20px', backgroundColor: T.bg.elevated, borderBottom: T.border.card }}>
                    <div style={{ textAlign: 'center', fontSize: 14, fontWeight: 600, color: T.accent.teal }}>{runA.period}</div>
                    <div style={{ textAlign: 'center', fontSize: 12, color: T.text.tertiary, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Métrica</div>
                    <div style={{ textAlign: 'center', fontSize: 14, fontWeight: 600, color: T.accent.teal }}>{runB.period}</div>
                  </div>

                  <CompareCell labelA={runA.findings_count} labelB={runB.findings_count} label="Hallazgos totales" />
                  <CompareCell labelA={runA.new} labelB={runB.new} label="Hallazgos nuevos" />
                  <CompareCell labelA={runA.resolved} labelB={runB.resolved} label="Resueltos" />

                  {/* Status */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', alignItems: 'center', padding: '12px 20px', borderTop: T.border.subtle }}>
                    <div style={{ textAlign: 'center', fontSize: 12, fontWeight: 600, color: runA.success ? T.accent.teal : T.accent.red }}>
                      {runA.success ? '✓ Exitoso' : '✕ Error'}
                    </div>
                    <div style={{ textAlign: 'center', fontSize: 12, color: T.text.tertiary, fontWeight: 500 }}>Estado</div>
                    <div style={{ textAlign: 'center', fontSize: 12, fontWeight: 600, color: runB.success ? T.accent.teal : T.accent.red }}>
                      {runB.success ? '✓ Exitoso' : '✕ Error'}
                    </div>
                  </div>
                </div>

                {/* KPI comparison */}
                {kpiLabels.length > 0 && (
                  <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, overflow: 'hidden' }}>
                    <div style={{ padding: '12px 20px', backgroundColor: T.bg.elevated, borderBottom: T.border.card }}>
                      <h3 style={{ fontSize: 11, fontWeight: 600, color: T.text.secondary, textTransform: 'uppercase', letterSpacing: '0.12em', margin: 0 }}>KPIs Comparados</h3>
                    </div>
                    {kpiLabels.map(label => {
                      const history = profile.baseline_history[label] || []
                      const pointA = history.find((p: any) => p.period === runA.period)
                      const pointB = history.find((p: any) => p.period === runB.period)
                      if (!pointA && !pointB) return null
                      const numA = pointA?.numeric_value
                      const numB = pointB?.numeric_value
                      const delta = numA != null && numB != null ? numB - numA : null
                      const pct = numA && numA !== 0 && delta !== null ? ((delta / numA) * 100).toFixed(1) : null
                      return (
                        <div key={label} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', alignItems: 'center', padding: '12px 20px', borderTop: T.border.subtle }}>
                          <div style={{ textAlign: 'center', fontSize: 14, fontWeight: 600, color: T.text.primary }}>{pointA?.value || '—'}</div>
                          <div style={{ textAlign: 'center' }}>
                            <p style={{ fontSize: 12, color: T.text.tertiary, fontWeight: 500, margin: 0 }}>{label}</p>
                            {pct && (
                              <span style={{ fontSize: 12, fontWeight: 700, color: Number(pct) >= 0 ? T.accent.teal : T.accent.red }}>
                                {Number(pct) >= 0 ? '▲' : '▼'} {Math.abs(Number(pct))}%
                              </span>
                            )}
                          </div>
                          <div style={{ textAlign: 'center', fontSize: 14, fontWeight: 600, color: T.text.primary }}>{pointB?.value || '—'}</div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </motion.div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
