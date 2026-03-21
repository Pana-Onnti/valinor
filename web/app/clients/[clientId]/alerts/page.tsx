'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft, Bell, BellOff, Plus, Trash2, RefreshCw, AlertTriangle, CheckCircle2, X } from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types ──────────────────────────────────────────────────────────────────────

interface AlertThreshold {
  label: string
  metric: string
  condition: string
  value: number
  severity: string
  triggered?: boolean
  last_triggered?: string
  created_at?: string
  message?: string
}

interface TriggeredAlert {
  threshold_label: string
  metric: string
  condition: string
  computed_value: number | null
  threshold_value: number
  severity: string
  message?: string
  triggered_at: string
  period?: string
}

interface AlertsData {
  client_name: string
  thresholds: AlertThreshold[]
  triggered_alerts: TriggeredAlert[]
}

interface NewAlertForm {
  label: string
  metric: string
  condition: string
  value: string
  severity: string
}

// ── Constants ─────────────────────────────────────────────────────────────────

const CONDITIONS = [
  { value: 'pct_change_below', label: '% cambio por debajo de' },
  { value: 'pct_change_above', label: '% cambio por encima de' },
  { value: 'absolute_below',   label: 'Valor absoluto por debajo de' },
  { value: 'absolute_above',   label: 'Valor absoluto por encima de' },
  { value: 'z_score_above',    label: 'Z-score por encima de' },
]

const SEVERITIES = [
  { value: 'CRITICAL', label: 'Crítico' },
  { value: 'HIGH',     label: 'Alto' },
  { value: 'MEDIUM',   label: 'Medio' },
  { value: 'LOW',      label: 'Bajo' },
]

const EMPTY_FORM: NewAlertForm = {
  label: '',
  metric: '',
  condition: 'pct_change_below',
  value: '',
  severity: 'HIGH',
}

// ── Helper sub-components ─────────────────────────────────────────────────────

function SeverityBadge({ severity, triggered = false }: { severity: string; triggered?: boolean }) {
  const base = 'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold'
  const styles: Record<string, string> = {
    CRITICAL: triggered
      ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
      : 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400',
    HIGH: triggered
      ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300'
      : 'bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-400',
    MEDIUM: 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400',
    LOW:    'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
  }
  const labels: Record<string, string> = {
    CRITICAL: 'Crítico', HIGH: 'Alto', MEDIUM: 'Medio', LOW: 'Bajo',
  }
  return (
    <span className={`${base} ${styles[severity] ?? styles['MEDIUM']}`}>
      {labels[severity] ?? severity}
    </span>
  )
}

function StatusBadge({ triggered }: { triggered?: boolean }) {
  if (triggered) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">
        <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
        Disparada
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400">
      <CheckCircle2 className="w-3 h-3" />
      OK
    </span>
  )
}

function conditionLabel(cond: string) {
  return CONDITIONS.find(c => c.value === cond)?.label ?? cond
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ClientAlertsPage() {
  const params = useParams()
  const clientId = params.clientId as string

  const [data, setData] = useState<AlertsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingLabel, setDeletingLabel] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<NewAlertForm>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const fetchAlerts = () => {
    setLoading(true)
    setError(null)
    fetch(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/alerts`)
      .then(async res => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body?.detail || `Error ${res.status}`)
        }
        return res.json()
      })
      .then((d: AlertsData) => setData(d))
      .catch(err => setError(err.message || 'Error cargando alertas'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchAlerts() }, [clientId])

  const handleDelete = async (label: string) => {
    setDeletingLabel(label)
    try {
      const res = await fetch(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/alerts/${encodeURIComponent(label)}`,
        { method: 'DELETE' }
      )
      if (!res.ok) throw new Error('No se pudo eliminar')
      setData(prev => prev ? {
        ...prev,
        thresholds: prev.thresholds.filter(t => t.label !== label)
      } : prev)
      setSuccessMsg(`Alerta "${label}" eliminada.`)
      setTimeout(() => setSuccessMsg(null), 3000)
    } catch (err: any) {
      setError(err.message || 'Error al eliminar')
    } finally {
      setDeletingLabel(null)
    }
  }

  const handleFormChange = (key: keyof NewAlertForm, val: string) => {
    setForm(prev => ({ ...prev, [key]: val }))
    setFormError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.label.trim()) { setFormError('El label es obligatorio'); return }
    if (!form.metric.trim()) { setFormError('La métrica es obligatoria'); return }
    const numVal = parseFloat(form.value)
    if (isNaN(numVal)) { setFormError('El valor debe ser un número'); return }

    setSubmitting(true)
    setFormError(null)
    try {
      const res = await fetch(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/alerts`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            label: form.label.trim(),
            metric: form.metric.trim(),
            condition: form.condition,
            value: numVal,
            severity: form.severity,
            operator: '>',
          }),
        }
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || `Error ${res.status}`)
      }
      setForm(EMPTY_FORM)
      setShowForm(false)
      setSuccessMsg('Alerta creada correctamente.')
      setTimeout(() => setSuccessMsg(null), 3000)
      fetchAlerts()
    } catch (err: any) {
      setFormError(err.message || 'Error al crear la alerta')
    } finally {
      setSubmitting(false)
    }
  }

  // ── Render states ──────────────────────────────────────────────────────────

  if (loading) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-4xl mx-auto space-y-5 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-40" />
        <div className="h-48 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
        <div className="h-32 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
      </div>
    </div>
  )

  if (error && !data) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <AlertTriangle className="h-10 w-10 text-red-400 mx-auto mb-3" />
        <p className="text-gray-600 dark:text-gray-400 mb-4">{error}</p>
        <Link href="/" className="text-violet-600 hover:underline text-sm">← Volver</Link>
      </div>
    </div>
  )

  const thresholds = data?.thresholds ?? []
  const triggered = data?.triggered_alerts ?? []
  const triggeredCount = thresholds.filter(t => t.triggered).length

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href={`/clients/${clientId}/history`}
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <Bell className="h-4 w-4 text-violet-500" />
                Alertas · {clientId.replace(/_/g, ' ')}
              </h1>
              <p className="text-xs text-gray-400">
                {thresholds.length} umbral{thresholds.length !== 1 ? 'es' : ''} configurado{thresholds.length !== 1 ? 's' : ''}
                {triggeredCount > 0 && (
                  <span className="ml-2 text-red-500 font-medium">· {triggeredCount} disparad{triggeredCount > 1 ? 'os' : 'o'}</span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={fetchAlerts}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 rounded-lg transition-all"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Actualizar
            </button>
            <button
              onClick={() => { setShowForm(v => !v); setFormError(null) }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-violet-600 hover:bg-violet-700 text-white rounded-lg transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
              Nueva Alerta
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8 space-y-8">
        {/* Success toast */}
        <AnimatePresence>
          {successMsg && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="flex items-center gap-2 px-4 py-3 bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 rounded-xl text-emerald-700 dark:text-emerald-300 text-sm"
            >
              <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
              {successMsg}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Error banner */}
        {error && (
          <div className="flex items-center gap-2 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-400 text-sm">
            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* Nueva Alerta form */}
        <AnimatePresence>
          {showForm && (
            <motion.div
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              className="bg-white dark:bg-gray-900 rounded-2xl border border-violet-200 dark:border-violet-800 p-6 shadow-sm"
            >
              <div className="flex items-center justify-between mb-5">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                  <Bell className="h-4 w-4 text-violet-500" />
                  Nueva Alerta
                </h2>
                <button
                  onClick={() => { setShowForm(false); setFormError(null); setForm(EMPTY_FORM) }}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Label */}
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                      Label <span className="text-red-400">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.label}
                      onChange={e => handleFormChange('label', e.target.value)}
                      placeholder="Ej: Alerta cobranza"
                      className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 transition-shadow"
                    />
                  </div>

                  {/* Metric */}
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                      Métrica <span className="text-red-400">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.metric}
                      onChange={e => handleFormChange('metric', e.target.value)}
                      placeholder="Ej: Cobranza Pendiente"
                      className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 transition-shadow"
                    />
                  </div>

                  {/* Condition */}
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                      Condicion
                    </label>
                    <select
                      value={form.condition}
                      onChange={e => handleFormChange('condition', e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 transition-shadow"
                    >
                      {CONDITIONS.map(c => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </select>
                  </div>

                  {/* Value */}
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                      Valor umbral <span className="text-red-400">*</span>
                    </label>
                    <input
                      type="number"
                      step="any"
                      value={form.value}
                      onChange={e => handleFormChange('value', e.target.value)}
                      placeholder="Ej: -10"
                      className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 transition-shadow"
                    />
                  </div>

                  {/* Severity */}
                  <div>
                    <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
                      Severidad
                    </label>
                    <select
                      value={form.severity}
                      onChange={e => handleFormChange('severity', e.target.value)}
                      className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 transition-shadow"
                    >
                      {SEVERITIES.map(s => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {formError && (
                  <p className="text-xs text-red-500 flex items-center gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
                    {formError}
                  </p>
                )}

                <div className="flex items-center justify-end gap-3 pt-1">
                  <button
                    type="button"
                    onClick={() => { setShowForm(false); setFormError(null); setForm(EMPTY_FORM) }}
                    className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
                  >
                    Cancelar
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="flex items-center gap-2 px-4 py-2 text-sm bg-violet-600 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl transition-colors"
                  >
                    {submitting ? (
                      <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    ) : (
                      <Plus className="h-3.5 w-3.5" />
                    )}
                    {submitting ? 'Guardando...' : 'Crear alerta'}
                  </button>
                </div>
              </form>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Thresholds table */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
            Umbrales Configurados
          </h2>

          {thresholds.length === 0 ? (
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-12 text-center shadow-sm">
              <BellOff className="h-8 w-8 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
              <p className="text-sm text-gray-400">No hay umbrales configurados.</p>
              <button
                onClick={() => setShowForm(true)}
                className="mt-3 text-sm text-violet-600 hover:underline"
              >
                Crear la primera alerta
              </button>
            </div>
          ) : (
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
              {/* Column headers */}
              <div className="grid grid-cols-[1.5fr_1.5fr_2fr_1fr_1fr_1fr_auto] gap-3 px-5 py-2.5 bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-800">
                {['Label', 'Métrica', 'Condicion', 'Valor', 'Severidad', 'Estado', ''].map((h, i) => (
                  <span key={i} className="text-xs font-semibold text-gray-400 uppercase tracking-widest">{h}</span>
                ))}
              </div>

              <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
                {thresholds.map((t, i) => (
                  <motion.div
                    key={t.label}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className={`grid grid-cols-[1.5fr_1.5fr_2fr_1fr_1fr_1fr_auto] gap-3 items-center px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors ${
                      t.triggered ? 'bg-red-50/30 dark:bg-red-900/5' : ''
                    }`}
                  >
                    <span className="text-sm font-medium text-gray-800 dark:text-gray-200 truncate" title={t.label}>
                      {t.label}
                    </span>
                    <span className="text-sm text-gray-600 dark:text-gray-400 truncate font-mono text-xs" title={t.metric}>
                      {t.metric}
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400 truncate" title={conditionLabel(t.condition)}>
                      {conditionLabel(t.condition)}
                    </span>
                    <span className="text-sm font-semibold text-gray-900 dark:text-white tabular-nums">
                      {t.value}
                    </span>
                    <SeverityBadge severity={t.severity} triggered={t.triggered} />
                    <StatusBadge triggered={t.triggered} />
                    <button
                      onClick={() => handleDelete(t.label)}
                      disabled={deletingLabel === t.label}
                      title={`Eliminar "${t.label}"`}
                      className="p-1.5 text-gray-300 hover:text-red-500 dark:text-gray-600 dark:hover:text-red-400 disabled:opacity-40 transition-colors rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20"
                    >
                      {deletingLabel === t.label ? (
                        <div className="w-3.5 h-3.5 border-2 border-red-300 border-t-red-500 rounded-full animate-spin" />
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </motion.div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Triggered alerts section */}
        {triggered.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              Disparadas
              <span className="text-xs font-bold text-red-500 normal-case">({triggered.length})</span>
            </h2>

            <div className="space-y-3">
              {[...triggered].reverse().map((alert, i) => {
                const isCritical = alert.severity === 'CRITICAL'
                const isHigh = alert.severity === 'HIGH'
                const bgColor = isCritical
                  ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                  : isHigh
                  ? 'bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800'
                  : 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'

                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className={`flex items-start gap-4 px-5 py-4 rounded-2xl border ${bgColor}`}
                  >
                    <AlertTriangle className={`h-4 w-4 mt-0.5 flex-shrink-0 ${
                      isCritical ? 'text-red-500' : isHigh ? 'text-orange-500' : 'text-amber-500'
                    }`} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-gray-900 dark:text-white">
                          {alert.threshold_label}
                        </span>
                        <SeverityBadge severity={alert.severity} triggered />
                        {alert.period && (
                          <span className="text-xs text-gray-400 font-mono">{alert.period}</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        <span className="font-mono">{alert.metric}</span>
                        {' · '}
                        {conditionLabel(alert.condition)}
                        {alert.computed_value != null && (
                          <> — valor calculado: <span className="font-semibold">{Number(alert.computed_value).toFixed(2)}</span> (umbral: {alert.threshold_value})</>
                        )}
                      </p>
                      {alert.message && (
                        <p className="text-xs text-gray-400 mt-1 italic">{alert.message}</p>
                      )}
                    </div>
                    <span className="text-xs text-gray-400 whitespace-nowrap flex-shrink-0">
                      {formatDate(alert.triggered_at)}
                    </span>
                  </motion.div>
                )
              })}
            </div>
          </div>
        )}

        {/* Empty triggered section placeholder */}
        {triggered.length === 0 && thresholds.length > 0 && (
          <div>
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
              Disparadas
            </h2>
            <div className="flex items-center gap-3 px-5 py-4 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm">
              <CheckCircle2 className="h-5 w-5 text-emerald-400 flex-shrink-0" />
              <p className="text-sm text-gray-400">Sin alertas disparadas recientemente.</p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
