'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams, usePathname } from 'next/navigation'
import { motion } from 'framer-motion'
import axios from 'axios'
import {
  ArrowLeft,
  Settings,
  Globe,
  Layers,
  Table2,
  Webhook,
  Trash2,
  Plus,
  Save,
  AlertTriangle,
  RefreshCw,
  Check,
  X,
  Link as LinkIcon,
} from 'lucide-react'
import Link from 'next/link'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const FOCUS_AREA_OPTIONS = [
  { value: 'receivables',  label: 'Cuentas por cobrar' },
  { value: 'fraud',        label: 'Fraude' },
  { value: 'inventory',    label: 'Inventario' },
  { value: 'margins',      label: 'Márgenes' },
  { value: 'customers',    label: 'Clientes' },
  { value: 'cash_flow',    label: 'Flujo de caja' },
]

const DEPTH_OPTIONS = [
  { value: 'basic',    label: 'Básico',     desc: 'Métricas esenciales, análisis rápido' },
  { value: 'standard', label: 'Estándar',   desc: 'Profundidad balanceada (recomendado)' },
  { value: 'detailed', label: 'Detallado',  desc: 'Análisis exhaustivo, más tiempo' },
]

const LANGUAGE_OPTIONS = [
  { value: 'es', label: 'Español' },
  { value: 'en', label: 'English' },
]

interface RefinementSettings {
  preferred_analysis_depth?: 'basic' | 'standard' | 'detailed'
  focus_areas?: string[]
  language?: string
  excluded_tables?: string[]
}

interface Webhook {
  id: string
  url: string
  created_at: string
  active: boolean
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

// ── helpers ──────────────────────────────────────────────────────────────────

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{ fontSize: 11, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 16 }}>
      {children}
    </h2>
  )
}

function Card({ children, style: extraStyle = {} }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, ...extraStyle }}>
      {children}
    </div>
  )
}

// ── Tab nav (shared across all client pages) ──────────────────────────────────

const TABS = (clientId: string) => [
  { label: 'Historial',      href: `/clients/${clientId}/history` },
  { label: 'Hallazgos',      href: `/clients/${clientId}/findings` },
  { label: 'Alertas',        href: `/clients/${clientId}/alerts` },
  { label: 'Costos',         href: `/clients/${clientId}/costs` },
  { label: 'KPIs',           href: `/clients/${clientId}/kpis` },
  { label: 'Segmentación',   href: `/clients/${clientId}/segmentation` },
  { label: 'Configuración',  href: `/clients/${clientId}/settings` },
]

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ClientSettingsPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const pathname = usePathname()

  // Refinement state
  const [settings, setSettings] = useState<RefinementSettings>({
    preferred_analysis_depth: 'standard',
    focus_areas: [],
    language: 'es',
    excluded_tables: [],
  })
  const [loadingSettings, setLoadingSettings] = useState(true)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)

  // Excluded tables raw textarea value
  const [excludedTablesText, setExcludedTablesText] = useState('')

  // Webhook state
  const [webhooks, setWebhooks] = useState<Webhook[]>([])
  const [loadingWebhooks, setLoadingWebhooks] = useState(true)
  const [newWebhookUrl, setNewWebhookUrl] = useState('')
  const [addingWebhook, setAddingWebhook] = useState(false)
  const [webhookError, setWebhookError] = useState<string | null>(null)

  // Reset danger state
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetting, setResetting] = useState(false)

  // Client display name
  const [clientName, setClientName] = useState<string>(clientId)

  // ── Fetch refinement settings ───────────────────────────────────────────────
  const fetchSettings = useCallback(() => {
    setLoadingSettings(true)
    setSettingsError(null)
    axios
      .get<RefinementSettings>(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/refinement`)
      .then(res => {
        const data = res.data
        setSettings({
          preferred_analysis_depth: data.preferred_analysis_depth ?? 'standard',
          focus_areas: data.focus_areas ?? [],
          language: data.language ?? 'es',
          excluded_tables: data.excluded_tables ?? [],
        })
        setExcludedTablesText((data.excluded_tables ?? []).join(', '))
      })
      .catch(err => {
        setSettingsError(err.response?.data?.detail || 'Error cargando configuración')
      })
      .finally(() => setLoadingSettings(false))
  }, [clientId])

  // ── Fetch webhooks ──────────────────────────────────────────────────────────
  const fetchWebhooks = useCallback(() => {
    setLoadingWebhooks(true)
    axios
      .get<Webhook[]>(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/webhooks`)
      .then(res => setWebhooks(res.data))
      .catch(() => setWebhooks([]))
      .finally(() => setLoadingWebhooks(false))
  }, [clientId])

  // ── Fetch client name from profile ─────────────────────────────────────────
  useEffect(() => {
    axios
      .get(`${API_URL}/api/clients/${encodeURIComponent(clientId)}/profile`)
      .then(res => setClientName(res.data.client_name ?? clientId))
      .catch(() => {})
  }, [clientId])

  useEffect(() => { fetchSettings() }, [fetchSettings])
  useEffect(() => { fetchWebhooks() }, [fetchWebhooks])

  // ── Derived helpers ─────────────────────────────────────────────────────────

  const toggleFocusArea = (value: string) => {
    setSettings(prev => {
      const areas = prev.focus_areas ?? []
      return {
        ...prev,
        focus_areas: areas.includes(value)
          ? areas.filter(a => a !== value)
          : [...areas, value],
      }
    })
  }

  // ── Submit settings ─────────────────────────────────────────────────────────
  const handleSave = async () => {
    setSaveState('saving')
    setSaveError(null)

    // Parse excluded tables from textarea
    const excluded = excludedTablesText
      .split(',')
      .map(t => t.trim())
      .filter(Boolean)

    const payload: RefinementSettings = {
      ...settings,
      excluded_tables: excluded,
    }

    try {
      await axios.patch(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/refinement`,
        payload,
      )
      setSaveState('saved')
      setTimeout(() => setSaveState('idle'), 2500)
    } catch (err: any) {
      setSaveState('error')
      setSaveError(err.response?.data?.detail || 'Error guardando configuración')
    }
  }

  // ── Reset profile ───────────────────────────────────────────────────────────
  const handleReset = async () => {
    if (!confirmReset) { setConfirmReset(true); return }
    setResetting(true)
    try {
      await axios.delete(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/refinement`,
      )
      setConfirmReset(false)
      fetchSettings()
    } catch {
      // fall back to patching with empty payload
      try {
        await axios.patch(
          `${API_URL}/api/clients/${encodeURIComponent(clientId)}/refinement`,
          { preferred_analysis_depth: 'standard', focus_areas: [], language: 'es', excluded_tables: [] },
        )
        setConfirmReset(false)
        fetchSettings()
      } catch {}
    } finally {
      setResetting(false)
    }
  }

  // ── Add webhook ─────────────────────────────────────────────────────────────
  const handleAddWebhook = async () => {
    if (!newWebhookUrl.trim()) return
    setAddingWebhook(true)
    setWebhookError(null)
    try {
      await axios.post(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/webhooks`,
        { url: newWebhookUrl.trim() },
      )
      setNewWebhookUrl('')
      fetchWebhooks()
    } catch (err: any) {
      setWebhookError(err.response?.data?.detail || 'Error agregando webhook')
    } finally {
      setAddingWebhook(false)
    }
  }

  // ── Delete webhook ──────────────────────────────────────────────────────────
  const handleDeleteWebhook = async (webhookId: string) => {
    try {
      await axios.delete(
        `${API_URL}/api/clients/${encodeURIComponent(clientId)}/webhooks/${webhookId}`,
      )
      fetchWebhooks()
    } catch {}
  }

  // ── Loading skeleton ────────────────────────────────────────────────────────
  if (loadingSettings) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, padding: 32 }}>
      <div style={{ maxWidth: 1152, margin: '0 auto' }}>
        <div style={{ height: 32, backgroundColor: T.bg.elevated, borderRadius: T.radius.md, width: 192, marginBottom: 24 }} />
        <div style={{ height: 256, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg, marginBottom: 24 }} />
        <div style={{ height: 192, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
      </div>
    </div>
  )

  // ── Error state ─────────────────────────────────────────────────────────────
  if (settingsError) return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ textAlign: 'center' }}>
        <p style={{ color: T.text.secondary, marginBottom: 16 }}>{settingsError}</p>
        <button
          onClick={fetchSettings}
          style={{ color: T.accent.teal, fontSize: 14, background: 'none', border: 'none', cursor: 'pointer' }}
        >
          Reintentar
        </button>
      </div>
    </div>
  )

  // ── Save button style helper ────────────────────────────────────────────────
  const saveBtnStyle: React.CSSProperties = saveState === 'saved'
    ? { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 16px', fontSize: 14, fontWeight: 500, borderRadius: T.radius.md, border: `1px solid ${T.accent.teal}40`, backgroundColor: T.accent.teal + '20', color: T.accent.teal, cursor: 'pointer' }
    : saveState === 'error'
    ? { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 16px', fontSize: 14, fontWeight: 500, borderRadius: T.radius.md, border: `1px solid ${T.accent.red}40`, backgroundColor: T.accent.red + '20', color: T.accent.red, cursor: 'pointer' }
    : { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 16px', fontSize: 14, fontWeight: 500, borderRadius: T.radius.md, cursor: 'pointer' }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* ── Header ── */}
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
              <p style={{ fontSize: 12, color: T.text.tertiary, margin: 0 }}>Configuración del cliente</p>
            </div>
          </div>
          {/* Save button */}
          <button
            onClick={handleSave}
            disabled={saveState === 'saving'}
            className={saveState === 'idle' || saveState === 'saving' ? 'd4c-btn-primary' : ''}
            style={saveBtnStyle}
          >
            {saveState === 'saving' ? (
              <><RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} />Guardando…</>
            ) : saveState === 'saved' ? (
              <><Check size={14} />Guardado</>
            ) : saveState === 'error' ? (
              <><X size={14} />Error</>
            ) : (
              <><Save size={14} />Guardar cambios</>
            )}
          </button>
        </div>

        {/* Tab navigation */}
        <div style={{ maxWidth: 1152, margin: '0 auto', padding: '0 24px' }}>
          <nav style={{ display: 'flex', gap: 4 }}>
            {TABS(clientId).map(tab => {
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

      <main style={{ maxWidth: 1152, margin: '0 auto', padding: '32px 24px', display: 'flex', flexDirection: 'column', gap: 40 }}>

        {/* ── Save error banner ── */}
        {saveState === 'error' && saveError && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', backgroundColor: T.accent.red + '20', border: `1px solid ${T.accent.red}40`, borderRadius: T.radius.md, fontSize: 14, color: T.accent.red }}
          >
            <AlertTriangle size={16} style={{ flexShrink: 0 }} />
            {saveError}
          </motion.div>
        )}

        {/* ── Analysis depth ── */}
        <section>
          <SectionHeading>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <Layers size={14} />
              Profundidad de análisis
            </span>
          </SectionHeading>
          <Card style={{ padding: 20 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
              {DEPTH_OPTIONS.map(opt => {
                const active = settings.preferred_analysis_depth === opt.value
                return (
                  <button
                    key={opt.value}
                    onClick={() => setSettings(prev => ({ ...prev, preferred_analysis_depth: opt.value as any }))}
                    style={active
                      ? { textAlign: 'left', padding: '12px 16px', borderRadius: T.radius.md, border: `2px solid ${T.accent.teal}`, backgroundColor: T.accent.teal + '10', cursor: 'pointer', background: T.accent.teal + '10' }
                      : { textAlign: 'left', padding: '12px 16px', borderRadius: T.radius.md, border: T.border.card, cursor: 'pointer', background: 'transparent' }
                    }
                  >
                    <p style={{ fontSize: 14, fontWeight: 600, marginBottom: 2, color: active ? T.accent.teal : T.text.primary }}>
                      {opt.label}
                    </p>
                    <p style={{ fontSize: 12, color: T.text.tertiary, margin: 0 }}>{opt.desc}</p>
                  </button>
                )
              })}
            </div>
          </Card>
        </section>

        {/* ── Focus areas ── */}
        <section>
          <SectionHeading>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <Settings size={14} />
              Áreas de foco
            </span>
          </SectionHeading>
          <Card style={{ padding: 20 }}>
            <p style={{ fontSize: 12, color: T.text.tertiary, marginBottom: 16, marginTop: 0 }}>
              Selecciona las áreas en las que los agentes deben concentrar el análisis. Puedes elegir varias.
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {FOCUS_AREA_OPTIONS.map(opt => {
                const active = (settings.focus_areas ?? []).includes(opt.value)
                return (
                  <button
                    key={opt.value}
                    onClick={() => toggleFocusArea(opt.value)}
                    style={active
                      ? { backgroundColor: T.accent.teal, color: T.text.inverse, borderRadius: 999, padding: '6px 12px', fontSize: 14, fontWeight: 500, border: `1px solid ${T.accent.teal}`, cursor: 'pointer' }
                      : { borderRadius: 999, padding: '6px 12px', fontSize: 14, fontWeight: 500, cursor: 'pointer' }
                    }
                    className={active ? '' : 'd4c-btn-ghost'}
                  >
                    {active && <span style={{ marginRight: 4 }}>✓</span>}
                    {opt.label}
                  </button>
                )
              })}
            </div>
            {(settings.focus_areas ?? []).length === 0 && (
              <p style={{ fontSize: 12, color: T.accent.yellow, marginTop: 12, marginBottom: 0 }}>
                Sin áreas seleccionadas: los agentes analizarán todas las áreas disponibles.
              </p>
            )}
          </Card>
        </section>

        {/* ── Language ── */}
        <section>
          <SectionHeading>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <Globe size={14} />
              Idioma del reporte
            </span>
          </SectionHeading>
          <Card style={{ padding: 20 }}>
            <div style={{ display: 'flex', gap: 12 }}>
              {LANGUAGE_OPTIONS.map(opt => {
                const active = settings.language === opt.value
                return (
                  <button
                    key={opt.value}
                    onClick={() => setSettings(prev => ({ ...prev, language: opt.value }))}
                    style={active
                      ? { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 20px', borderRadius: T.radius.md, border: `2px solid ${T.accent.teal}`, backgroundColor: T.accent.teal + '10', fontSize: 14, fontWeight: 500, color: T.accent.teal, cursor: 'pointer' }
                      : { display: 'flex', alignItems: 'center', gap: 8, padding: '10px 20px', borderRadius: T.radius.md, border: T.border.card, fontSize: 14, fontWeight: 500, color: T.text.secondary, cursor: 'pointer', background: 'transparent' }
                    }
                  >
                    {opt.label}
                    {active && <Check size={14} />}
                  </button>
                )
              })}
            </div>
          </Card>
        </section>

        {/* ── Excluded tables ── */}
        <section>
          <SectionHeading>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <Table2 size={14} />
              Tablas excluidas
            </span>
          </SectionHeading>
          <Card style={{ padding: 20 }}>
            <p style={{ fontSize: 12, color: T.text.tertiary, marginBottom: 12, marginTop: 0 }}>
              Tablas que los agentes deben ignorar completamente. Separa los nombres con comas.
            </p>
            <textarea
              value={excludedTablesText}
              onChange={e => setExcludedTablesText(e.target.value)}
              rows={3}
              placeholder="logs, temp_cache, audit_trail, sessions"
              className="d4c-input"
              style={{ width: '100%', resize: 'none', fontFamily: T.font.mono, boxSizing: 'border-box' }}
            />
            {excludedTablesText.trim() && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
                {excludedTablesText.split(',').map(t => t.trim()).filter(Boolean).map(t => (
                  <span
                    key={t}
                    style={{ padding: '2px 8px', backgroundColor: T.bg.elevated, color: T.text.secondary, fontSize: 12, borderRadius: T.radius.sm, fontFamily: T.font.mono }}
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}
          </Card>
        </section>

        {/* ── Webhooks ── */}
        <section>
          <SectionHeading>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <Webhook size={14} />
              Webhooks
            </span>
          </SectionHeading>
          <Card>
            {/* Existing webhooks */}
            {loadingWebhooks ? (
              <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[1, 2].map(i => (
                  <div key={i} style={{ height: 40, backgroundColor: T.bg.elevated, borderRadius: T.radius.md }} />
                ))}
              </div>
            ) : webhooks.length > 0 ? (
              <div>
                {webhooks.map((wh, i) => (
                  <motion.div
                    key={wh.id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.05 }}
                    style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '14px 20px', borderBottom: i < webhooks.length - 1 ? T.border.subtle : 'none' }}
                  >
                    <LinkIcon style={{ height: 16, width: 16, color: T.text.tertiary, flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ fontSize: 14, color: T.text.primary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: T.font.mono, margin: 0 }}>
                        {wh.url}
                      </p>
                      <p style={{ fontSize: 12, color: T.text.tertiary, marginTop: 2, marginBottom: 0 }}>
                        Creado {new Date(wh.created_at).toLocaleDateString('es', {
                          day: 'numeric', month: 'short', year: 'numeric',
                        })}
                      </p>
                    </div>
                    <span style={{
                      fontSize: 12,
                      padding: '2px 8px',
                      borderRadius: 999,
                      fontWeight: 500,
                      backgroundColor: wh.active ? T.accent.teal + '20' : T.bg.elevated,
                      color: wh.active ? T.accent.teal : T.text.tertiary,
                    }}>
                      {wh.active ? 'Activo' : 'Inactivo'}
                    </span>
                    <button
                      onClick={() => handleDeleteWebhook(wh.id)}
                      title="Eliminar webhook"
                      style={{ padding: 6, color: T.text.tertiary, background: 'none', border: 'none', cursor: 'pointer', borderRadius: T.radius.sm }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div style={{ padding: '32px 20px', textAlign: 'center' }}>
                <Webhook style={{ height: 32, width: 32, color: T.text.tertiary, margin: '0 auto 8px' }} />
                <p style={{ fontSize: 14, color: T.text.tertiary, margin: 0 }}>Sin webhooks configurados</p>
              </div>
            )}

            {/* Add webhook form */}
            <div style={{ padding: '16px 20px 20px', borderTop: T.border.subtle }}>
              {webhookError && (
                <p style={{ fontSize: 12, color: T.accent.red, marginBottom: 8 }}>{webhookError}</p>
              )}
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  type="url"
                  value={newWebhookUrl}
                  onChange={e => setNewWebhookUrl(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddWebhook()}
                  placeholder="https://hooks.example.com/notify"
                  className="d4c-input"
                  style={{ flex: 1 }}
                />
                <button
                  onClick={handleAddWebhook}
                  disabled={addingWebhook || !newWebhookUrl.trim()}
                  className="d4c-btn-primary"
                  style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', fontSize: 14, fontWeight: 500 }}
                >
                  {addingWebhook
                    ? <RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} />
                    : <Plus size={14} />
                  }
                  Agregar
                </button>
              </div>
            </div>
          </Card>
        </section>

        {/* ── Danger zone ── */}
        <section>
          <SectionHeading>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: T.accent.red }}>
              <AlertTriangle size={14} />
              Zona de peligro
            </span>
          </SectionHeading>
          <Card style={{ border: `1px solid ${T.accent.red}30` }}>
            <div style={{ padding: 20, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 24 }}>
              <div>
                <p style={{ fontSize: 14, fontWeight: 500, color: T.text.primary, marginBottom: 4 }}>
                  Restablecer perfil de refinamiento
                </p>
                <p style={{ fontSize: 12, color: T.text.tertiary, lineHeight: 1.6, maxWidth: 480, margin: 0 }}>
                  Borra todas las preferencias de análisis: profundidad, áreas de foco, idioma y tablas excluidas.
                  El historial de runs y los hallazgos no se ven afectados.
                </p>
              </div>
              <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
                <button
                  onClick={handleReset}
                  disabled={resetting}
                  style={confirmReset
                    ? { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', fontSize: 14, fontWeight: 500, borderRadius: T.radius.md, border: 'none', backgroundColor: T.accent.red, color: 'white', cursor: 'pointer' }
                    : { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', fontSize: 14, fontWeight: 500, borderRadius: T.radius.md, border: `1px solid ${T.accent.red}40`, backgroundColor: 'transparent', color: T.accent.red, cursor: 'pointer' }
                  }
                >
                  {resetting ? (
                    <><RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} />Restableciendo…</>
                  ) : confirmReset ? (
                    <><AlertTriangle size={14} />Confirmar restablecimiento</>
                  ) : (
                    <><Trash2 size={14} />Restablecer perfil</>
                  )}
                </button>
                {confirmReset && !resetting && (
                  <button
                    onClick={() => setConfirmReset(false)}
                    style={{ fontSize: 12, color: T.text.tertiary, background: 'none', border: 'none', cursor: 'pointer' }}
                  >
                    Cancelar
                  </button>
                )}
              </div>
            </div>
          </Card>
        </section>

      </main>
    </div>
  )
}
