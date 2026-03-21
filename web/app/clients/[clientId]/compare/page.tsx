'use client'

import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import Link from 'next/link'
import { ArrowLeft, ArrowRight, TrendingUp, TrendingDown, Minus, AlertOctagon, CheckCircle2 } from 'lucide-react'

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
    <div className="grid grid-cols-3 items-center px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors">
      <div className={`text-sm font-semibold text-center ${
        numA > numB ? 'text-orange-600 dark:text-orange-400' : 'text-gray-700 dark:text-gray-300'
      }`}>{labelA}</div>
      <div className="text-xs text-gray-400 text-center font-medium">{label}</div>
      <div className={`text-sm font-semibold text-center ${
        numB > numA ? 'text-orange-600 dark:text-orange-400' : 'text-gray-700 dark:text-gray-300'
      }`}>{labelB}</div>
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
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="relative h-12 w-12">
        <div className="absolute inset-0 rounded-full border-4 border-violet-100 dark:border-violet-900" />
        <div className="absolute inset-0 rounded-full border-4 border-t-violet-600 animate-spin" />
      </div>
    </div>
  )

  const runs: RunSummary[] = profile?.run_history || []
  const runA = selectedA !== null ? runs[selectedA] : null
  const runB = selectedB !== null ? runs[selectedB] : null
  const kpiLabels = Object.keys(profile?.baseline_history || {})

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-4">
          <Link href={`/clients/${clientId}/history`} className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-lg font-bold text-gray-900 dark:text-white">{clientId.replace(/_/g, ' ')}</h1>
            <p className="text-xs text-gray-400">Comparación de runs</p>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        {runs.length < 2 ? (
          <div className="text-center py-20">
            <p className="text-gray-400">Se necesitan al menos 2 runs para comparar.</p>
            <Link href={`/clients/${clientId}/history`} className="text-violet-600 text-sm mt-2 inline-block hover:underline">← Ver historial</Link>
          </div>
        ) : (
          <>
            {/* Run selectors */}
            <div className="grid grid-cols-3 gap-4 mb-8 items-center">
              <div>
                <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Run anterior (A)</p>
                <select
                  value={selectedA ?? ''}
                  onChange={e => setSelectedA(Number(e.target.value))}
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
                >
                  {runs.map((r, i) => (
                    <option key={i} value={i}>{r.period} — {formatDate(r.run_date)}</option>
                  ))}
                </select>
              </div>
              <div className="flex justify-center">
                <ArrowRight className="h-5 w-5 text-gray-400" />
              </div>
              <div>
                <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Run actual (B)</p>
                <select
                  value={selectedB ?? ''}
                  onChange={e => setSelectedB(Number(e.target.value))}
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
                >
                  {runs.map((r, i) => (
                    <option key={i} value={i}>{r.period} — {formatDate(r.run_date)}</option>
                  ))}
                </select>
              </div>
            </div>

            {runA && runB && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
                {/* Metrics comparison */}
                <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
                  {/* Header row */}
                  <div className="grid grid-cols-3 px-5 py-3 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-800">
                    <div className="text-sm font-semibold text-violet-600 dark:text-violet-400 text-center">{runA.period}</div>
                    <div className="text-xs text-gray-400 text-center font-medium uppercase tracking-wide">Métrica</div>
                    <div className="text-sm font-semibold text-violet-600 dark:text-violet-400 text-center">{runB.period}</div>
                  </div>

                  <CompareCell labelA={runA.findings_count} labelB={runB.findings_count} label="Hallazgos totales" />
                  <CompareCell labelA={runA.new} labelB={runB.new} label="Hallazgos nuevos" />
                  <CompareCell labelA={runA.resolved} labelB={runB.resolved} label="Resueltos" />

                  {/* Status */}
                  <div className="grid grid-cols-3 items-center px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/30 border-t border-gray-50 dark:border-gray-800/50">
                    <div className={`text-xs font-semibold text-center ${runA.success ? 'text-emerald-500' : 'text-red-500'}`}>
                      {runA.success ? '✅ Exitoso' : '❌ Error'}
                    </div>
                    <div className="text-xs text-gray-400 text-center font-medium">Estado</div>
                    <div className={`text-xs font-semibold text-center ${runB.success ? 'text-emerald-500' : 'text-red-500'}`}>
                      {runB.success ? '✅ Exitoso' : '❌ Error'}
                    </div>
                  </div>
                </div>

                {/* KPI comparison */}
                {kpiLabels.length > 0 && (
                  <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
                    <div className="px-5 py-3 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-800">
                      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">KPIs Comparados</h3>
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
                        <div key={label} className="grid grid-cols-3 items-center px-5 py-3 border-t border-gray-50 dark:border-gray-800/50 hover:bg-gray-50 dark:hover:bg-gray-800/30">
                          <div className="text-sm font-semibold text-gray-700 dark:text-gray-300 text-center">{pointA?.value || '—'}</div>
                          <div className="text-center">
                            <p className="text-xs text-gray-400 font-medium">{label}</p>
                            {pct && (
                              <span className={`text-xs font-bold ${Number(pct) >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                                {Number(pct) >= 0 ? '▲' : '▼'} {Math.abs(Number(pct))}%
                              </span>
                            )}
                          </div>
                          <div className="text-sm font-semibold text-gray-700 dark:text-gray-300 text-center">{pointB?.value || '—'}</div>
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
