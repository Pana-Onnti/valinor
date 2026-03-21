'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import Link from 'next/link'
import { ArrowLeft, Bell, BellOff, Plus, Trash2, RefreshCw, AlertTriangle, CheckCircle2, X } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

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

// ── Helpers ───────────────────────────────────────────────────────────────────

function getSevColor(severity: string): string {
  const map: Record<string, string> = {
    CRITICAL: T.accent.red,
    HIGH: T.accent.orange,
    MEDIUM: T.accent.yellow,
    LOW: T.accent.blue,
  }
  return map[severity] ?? T.text.tertiary
}

function conditionLabel(cond: string) {
  return CONDITIONS.find(c => c.value === cond)?.label ?? cond
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// ── Helper sub-components ─────────────────────────────────────────────────────

function SeverityBadge({ severity, triggered = false }: { severity: string; triggered?: boolean }) {
  const color = getSevColor(severity)
  const labels: Record<string, string> = {
    CRITICAL: 'Crítico', HIGH: 'Alto', MEDIUM: 'Medio', LOW: 'Bajo',
  }
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 8px',
      borderRadius: '9999px',
      fontSize: 11,
      fontWeight: 600,
      backgroundColor: color + (triggered ? '25' : '15'),
      border: `1px solid ${color}${triggered ? '60' : '40'}`,
      color,
    }}>
      {labels[severity] ?? severity}
    </span>
  )
}

function StatusBadge({ triggered }: { triggered?: boolean }) {
  if (triggered) {
    return (
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: '9999px',
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: T.accent.red + '15',
        border: `1px solid ${T.accent.red}40`,
        color: T.accent.red,
      }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: T.accent.red }} className="animate-pulse" />
        Disparada
      </span>
    )
  }
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      padding: '2px 8px',
      borderRadius: '9999px',
      fontSize: 11,
      fontWeight: 600,
      backgroundColor: T.accent.teal + '15',
      border: `1px solid ${T.accent.teal}40`,
      color: T.accent.teal,
    }}>
      <CheckCircle2 style={{ width: 12, height: 12 }} />
      OK
    </span>
  )
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
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: T.space.xxl }}>
      <div style={{ maxWidth: 896, margin: '0 auto' }} className="animate-pulse">
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 160, marginBottom: T.space.xl }} />
        <div style={{ height: 192, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, marginBottom: T.space.lg }} />
        <div style={{ height: 128, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
      </div>
    </div>
  )

  if (error && !data) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <AlertTriangle style={{ height: 40, width: 40, color: T.accent.red, margin: '0 auto 12px' }} />
        <p style={{ color: T.text.secondary, marginBottom: T.space.lg }}>{error}</p>
        <Link href="/" style={{ color: T.accent.teal, textDecoration: 'none', fontSize: 13 }}>← Volver</Link>
      </div>
    </div>
  )

  const thresholds = data?.thresholds ?? []
  const triggered = data?.triggered_alerts ?? []
  const triggeredCount = thresholds.filter(t => t.triggered).length

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Header */}
      <header style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 896, margin: '0 auto', padding: `${T.space.lg} ${T.space.xl}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}>
            <Link
              href={`/clients/${clientId}/history`}
              style={{ color: T.text.tertiary, lineHeight: 0 }}
            >
              <ArrowLeft style={{ height: 20, width: 20 }} />
            </Link>
            <div>
              <h1 style={{ fontSize: 16, fontWeight: 700, color: T.text.primary, display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
                <Bell style={{ height: 16, width: 16, color: T.accent.teal }} />
                Alertas · {clientId.replace(/_/g, ' ')}
              </h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: '2px 0 0' }}>
                {thresholds.length} umbral{thresholds.length !== 1 ? 'es' : ''} configurado{thresholds.length !== 1 ? 's' : ''}
                {triggeredCount > 0 && (
                  <span style={{ marginLeft: 8, color: T.accent.red, fontWeight: 500 }}>
                    · {triggeredCount} disparad{triggeredCount > 1 ? 'os' : 'o'}
                  </span>
                )}
              </p>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
            <button
              onClick={fetchAlerts}
              className="d4c-btn-ghost"
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
            >
              <RefreshCw style={{ height: 14, width: 14 }} />
              Actualizar
            </button>
            <button
              onClick={() => { setShowForm(v => !v); setFormError(null) }}
              className="d4c-btn-primary"
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}
            >
              <Plus style={{ height: 14, width: 14 }} />
              Nueva Alerta
            </button>
          </div>
        </div>
      </header>

      <main style={{ maxWidth: 896, margin: '0 auto', padding: `${T.space.xxl} ${T.space.xl}`, display: 'flex', flexDirection: 'column', gap: T.space.xxl }}>
        {/* Success toast */}
        <AnimatePresence>
          {successMsg && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: T.space.sm,
                padding: `${T.space.md} ${T.space.lg}`,
                backgroundColor: T.accent.teal + '15',
                border: `1px solid ${T.accent.teal}40`,
                borderRadius: T.radius.lg,
                color: T.accent.teal,
                fontSize: 13,
              }}
            >
              <CheckCircle2 style={{ height: 16, width: 16, flexShrink: 0 }} />
              {successMsg}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Error banner */}
        {error && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: T.space.sm,
            padding: `${T.space.md} ${T.space.lg}`,
            backgroundColor: T.accent.red + '15',
            border: `1px solid ${T.accent.red}40`,
            borderRadius: T.radius.lg,
            color: T.accent.red,
            fontSize: 13,
          }}>
            <AlertTriangle style={{ height: 16, width: 16, flexShrink: 0 }} />
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
              style={{
                backgroundColor: T.bg.card,
                borderRadius: T.radius.lg,
                border: `1px solid ${T.accent.teal}40`,
                padding: T.space.xl,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: T.space.xl }}>
                <h2 style={{ fontSize: 13, fontWeight: 600, color: T.text.primary, display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
                  <Bell style={{ height: 16, width: 16, color: T.accent.teal }} />
                  Nueva Alerta
                </h2>
                <button
                  onClick={() => { setShowForm(false); setFormError(null); setForm(EMPTY_FORM) }}
                  style={{ color: T.text.tertiary, background: 'none', border: 'none', cursor: 'pointer', lineHeight: 0 }}
                >
                  <X style={{ height: 16, width: 16 }} />
                </button>
              </div>

              <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: T.space.lg }}>
                  {/* Label */}
                  <div>
                    <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: T.text.secondary, marginBottom: 6 }}>
                      Label <span style={{ color: T.accent.red }}>*</span>
                    </label>
                    <input
                      type="text"
                      value={form.label}
                      onChange={e => handleFormChange('label', e.target.value)}
                      placeholder="Ej: Alerta cobranza"
                      className="d4c-input"
                    />
                  </div>

                  {/* Metric */}
                  <div>
                    <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: T.text.secondary, marginBottom: 6 }}>
                      Métrica <span style={{ color: T.accent.red }}>*</span>
                    </label>
                    <input
                      type="text"
                      value={form.metric}
                      onChange={e => handleFormChange('metric', e.target.value)}
                      placeholder="Ej: Cobranza Pendiente"
                      className="d4c-input"
                    />
                  </div>

                  {/* Condition */}
                  <div>
                    <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: T.text.secondary, marginBottom: 6 }}>
                      Condicion
                    </label>
                    <select
                      value={form.condition}
                      onChange={e => handleFormChange('condition', e.target.value)}
                      className="d4c-input"
                    >
                      {CONDITIONS.map(c => (
                        <option key={c.value} value={c.value}>{c.label}</option>
                      ))}
                    </select>
                  </div>

                  {/* Value */}
                  <div>
                    <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: T.text.secondary, marginBottom: 6 }}>
                      Valor umbral <span style={{ color: T.accent.red }}>*</span>
                    </label>
                    <input
                      type="number"
                      step="any"
                      value={form.value}
                      onChange={e => handleFormChange('value', e.target.value)}
                      placeholder="Ej: -10"
                      className="d4c-input"
                    />
                  </div>

                  {/* Severity */}
                  <div>
                    <label style={{ display: 'block', fontSize: 11, fontWeight: 500, color: T.text.secondary, marginBottom: 6 }}>
                      Severidad
                    </label>
                    <select
                      value={form.severity}
                      onChange={e => handleFormChange('severity', e.target.value)}
                      className="d4c-input"
                    >
                      {SEVERITIES.map(s => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {formError && (
                  <p style={{ fontSize: 12, color: T.accent.red, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <AlertTriangle style={{ height: 14, width: 14, flexShrink: 0 }} />
                    {formError}
                  </p>
                )}

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: T.space.md }}>
                  <button
                    type="button"
                    onClick={() => { setShowForm(false); setFormError(null); setForm(EMPTY_FORM) }}
                    style={{ padding: '8px 16px', fontSize: 13, color: T.text.secondary, background: 'none', border: 'none', cursor: 'pointer' }}
                  >
                    Cancelar
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="d4c-btn-primary"
                    style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, opacity: submitting ? 0.5 : 1, cursor: submitting ? 'not-allowed' : 'pointer' }}
                  >
                    {submitting ? (
                      <div style={{ width: 14, height: 14, border: `2px solid rgba(255,255,255,0.3)`, borderTopColor: '#fff', borderRadius: '50%' }} className="animate-spin" />
                    ) : (
                      <Plus style={{ height: 14, width: 14 }} />
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
          <h2 style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.md }}>
            Umbrales Configurados
          </h2>

          {thresholds.length === 0 ? (
            <div style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.lg,
              border: T.border.card,
              padding: '48px 24px',
              textAlign: 'center',
            }}>
              <BellOff style={{ height: 32, width: 32, color: T.text.tertiary, margin: '0 auto 12px' }} />
              <p style={{ fontSize: 13, color: T.text.tertiary }}>No hay umbrales configurados.</p>
              <button
                onClick={() => setShowForm(true)}
                style={{ marginTop: 12, fontSize: 13, color: T.accent.teal, background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}
              >
                Crear la primera alerta
              </button>
            </div>
          ) : (
            <div style={{
              backgroundColor: T.bg.card,
              borderRadius: T.radius.lg,
              border: T.border.card,
              overflow: 'hidden',
            }}>
              {/* Column headers */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1.5fr 1.5fr 2fr 1fr 1fr 1fr auto',
                gap: T.space.md,
                padding: `10px ${T.space.xl}`,
                backgroundColor: T.bg.elevated,
                borderBottom: T.border.card,
              }}>
                {['Label', 'Métrica', 'Condicion', 'Valor', 'Severidad', 'Estado', ''].map((h, i) => (
                  <span key={i} style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{h}</span>
                ))}
              </div>

              <div>
                {thresholds.map((t, i) => (
                  <motion.div
                    key={t.label}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04 }}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1.5fr 1.5fr 2fr 1fr 1fr 1fr auto',
                      gap: T.space.md,
                      alignItems: 'center',
                      padding: `${T.space.md} ${T.space.xl}`,
                      borderBottom: T.border.subtle,
                      backgroundColor: t.triggered ? T.accent.red + '08' : 'transparent',
                      transition: 'background-color 0.15s',
                    }}
                  >
                    <span style={{ fontSize: 13, fontWeight: 500, color: T.text.primary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.label}>
                      {t.label}
                    </span>
                    <span style={{ fontSize: 11, color: T.text.secondary, fontFamily: T.font.mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.metric}>
                      {t.metric}
                    </span>
                    <span style={{ fontSize: 11, color: T.text.tertiary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={conditionLabel(t.condition)}>
                      {conditionLabel(t.condition)}
                    </span>
                    <span style={{ fontSize: 13, fontWeight: 600, color: T.text.primary, fontVariantNumeric: 'tabular-nums' }}>
                      {t.value}
                    </span>
                    <SeverityBadge severity={t.severity} triggered={t.triggered} />
                    <StatusBadge triggered={t.triggered} />
                    <button
                      onClick={() => handleDelete(t.label)}
                      disabled={deletingLabel === t.label}
                      title={`Eliminar "${t.label}"`}
                      style={{
                        padding: 6,
                        color: T.text.tertiary,
                        background: 'none',
                        border: 'none',
                        cursor: deletingLabel === t.label ? 'not-allowed' : 'pointer',
                        opacity: deletingLabel === t.label ? 0.4 : 1,
                        borderRadius: T.radius.sm,
                        lineHeight: 0,
                        transition: 'color 0.15s',
                      }}
                    >
                      {deletingLabel === t.label ? (
                        <div style={{ width: 14, height: 14, border: `2px solid ${T.accent.red}50`, borderTopColor: T.accent.red, borderRadius: '50%' }} className="animate-spin" />
                      ) : (
                        <Trash2 style={{ height: 14, width: 14 }} />
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
            <h2 style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.md, display: 'flex', alignItems: 'center', gap: T.space.sm }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: T.accent.red }} className="animate-pulse" />
              Disparadas
              <span style={{ fontSize: 11, fontWeight: 700, color: T.accent.red, textTransform: 'none' }}>({triggered.length})</span>
            </h2>

            <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>
              {[...triggered].reverse().map((alert, i) => {
                const sevColor = getSevColor(alert.severity)
                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: T.space.lg,
                      padding: `${T.space.lg} ${T.space.xl}`,
                      borderRadius: T.radius.lg,
                      backgroundColor: sevColor + '10',
                      border: `1px solid ${sevColor}30`,
                    }}
                  >
                    <AlertTriangle style={{ height: 16, width: 16, marginTop: 2, flexShrink: 0, color: sevColor }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, flexWrap: 'wrap', marginBottom: 4 }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: T.text.primary }}>
                          {alert.threshold_label}
                        </span>
                        <SeverityBadge severity={alert.severity} triggered />
                        {alert.period && (
                          <span style={{ fontSize: 11, color: T.text.tertiary, fontFamily: T.font.mono }}>{alert.period}</span>
                        )}
                      </div>
                      <p style={{ fontSize: 11, color: T.text.secondary, margin: 0 }}>
                        <span style={{ fontFamily: T.font.mono }}>{alert.metric}</span>
                        {' · '}
                        {conditionLabel(alert.condition)}
                        {alert.computed_value != null && (
                          <> — valor calculado: <span style={{ fontWeight: 600 }}>{Number(alert.computed_value).toFixed(2)}</span> (umbral: {alert.threshold_value})</>
                        )}
                      </p>
                      {alert.message && (
                        <p style={{ fontSize: 11, color: T.text.tertiary, marginTop: 4, fontStyle: 'italic' }}>{alert.message}</p>
                      )}
                    </div>
                    <span style={{ fontSize: 11, color: T.text.tertiary, whiteSpace: 'nowrap', flexShrink: 0 }}>
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
            <h2 style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.md }}>
              Disparadas
            </h2>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: T.space.md,
              padding: `${T.space.lg} ${T.space.xl}`,
              backgroundColor: T.bg.card,
              borderRadius: T.radius.lg,
              border: T.border.card,
            }}>
              <CheckCircle2 style={{ height: 20, width: 20, color: T.accent.teal, flexShrink: 0 }} />
              <p style={{ fontSize: 13, color: T.text.tertiary, margin: 0 }}>Sin alertas disparadas recientemente.</p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
