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
    <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">
      {children}
    </h2>
  )
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm ${className}`}>
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
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 p-8">
      <div className="max-w-6xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 bg-gray-200 dark:bg-gray-800 rounded-xl w-48" />
        <div className="h-64 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
        <div className="h-48 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
      </div>
    </div>
  )

  // ── Error state ─────────────────────────────────────────────────────────────
  if (settingsError) return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex items-center justify-center">
      <div className="text-center">
        <p className="text-gray-500 mb-4">{settingsError}</p>
        <button
          onClick={fetchSettings}
          className="text-violet-600 hover:underline text-sm"
        >
          Reintentar
        </button>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* ── Header ── */}
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </Link>
            <div>
              <h1 className="text-lg font-bold text-gray-900 dark:text-white">{clientName}</h1>
              <p className="text-xs text-gray-400">Configuración del cliente</p>
            </div>
          </div>
          {/* Save button */}
          <button
            onClick={handleSave}
            disabled={saveState === 'saving'}
            className={`flex items-center gap-2 px-4 py-1.5 text-sm font-medium rounded-lg transition-all ${
              saveState === 'saved'
                ? 'bg-emerald-50 text-emerald-600 border border-emerald-200 dark:bg-emerald-900/30 dark:border-emerald-700'
                : saveState === 'error'
                ? 'bg-red-50 text-red-600 border border-red-200 dark:bg-red-900/30 dark:border-red-700'
                : 'bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60'
            }`}
          >
            {saveState === 'saving' ? (
              <><RefreshCw className="h-3.5 w-3.5 animate-spin" />Guardando…</>
            ) : saveState === 'saved' ? (
              <><Check className="h-3.5 w-3.5" />Guardado</>
            ) : saveState === 'error' ? (
              <><X className="h-3.5 w-3.5" />Error</>
            ) : (
              <><Save className="h-3.5 w-3.5" />Guardar cambios</>
            )}
          </button>
        </div>

        {/* Tab navigation */}
        <div className="max-w-6xl mx-auto px-6">
          <nav className="flex gap-1 -mb-px">
            {TABS(clientId).map(tab => {
              const isActive = pathname === tab.href
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                    isActive
                      ? 'border-violet-500 text-violet-600 dark:text-violet-400'
                      : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:border-gray-300 dark:hover:border-gray-600'
                  }`}
                >
                  {tab.label}
                </Link>
              )
            })}
          </nav>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-10">

        {/* ── Save error banner ── */}
        {saveState === 'error' && saveError && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-3 px-4 py-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl text-sm text-red-700 dark:text-red-300"
          >
            <AlertTriangle className="h-4 w-4 flex-shrink-0" />
            {saveError}
          </motion.div>
        )}

        {/* ── Analysis depth ── */}
        <section>
          <SectionHeading>
            <span className="inline-flex items-center gap-2">
              <Layers className="h-3.5 w-3.5" />
              Profundidad de análisis
            </span>
          </SectionHeading>
          <Card className="p-5">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {DEPTH_OPTIONS.map(opt => {
                const active = settings.preferred_analysis_depth === opt.value
                return (
                  <button
                    key={opt.value}
                    onClick={() => setSettings(prev => ({ ...prev, preferred_analysis_depth: opt.value as any }))}
                    className={`text-left px-4 py-3 rounded-xl border-2 transition-all ${
                      active
                        ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                        : 'border-gray-100 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    <p className={`text-sm font-semibold mb-0.5 ${active ? 'text-violet-700 dark:text-violet-300' : 'text-gray-800 dark:text-gray-200'}`}>
                      {opt.label}
                    </p>
                    <p className="text-xs text-gray-400">{opt.desc}</p>
                  </button>
                )
              })}
            </div>
          </Card>
        </section>

        {/* ── Focus areas ── */}
        <section>
          <SectionHeading>
            <span className="inline-flex items-center gap-2">
              <Settings className="h-3.5 w-3.5" />
              Áreas de foco
            </span>
          </SectionHeading>
          <Card className="p-5">
            <p className="text-xs text-gray-400 mb-4">
              Selecciona las áreas en las que los agentes deben concentrar el análisis. Puedes elegir varias.
            </p>
            <div className="flex flex-wrap gap-2">
              {FOCUS_AREA_OPTIONS.map(opt => {
                const active = (settings.focus_areas ?? []).includes(opt.value)
                return (
                  <button
                    key={opt.value}
                    onClick={() => toggleFocusArea(opt.value)}
                    className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-all ${
                      active
                        ? 'bg-violet-600 text-white border-violet-600 shadow-sm'
                        : 'bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-700 hover:border-violet-400 dark:hover:border-violet-600'
                    }`}
                  >
                    {active && <span className="mr-1">✓</span>}
                    {opt.label}
                  </button>
                )
              })}
            </div>
            {(settings.focus_areas ?? []).length === 0 && (
              <p className="text-xs text-amber-500 mt-3">
                Sin áreas seleccionadas: los agentes analizarán todas las áreas disponibles.
              </p>
            )}
          </Card>
        </section>

        {/* ── Language ── */}
        <section>
          <SectionHeading>
            <span className="inline-flex items-center gap-2">
              <Globe className="h-3.5 w-3.5" />
              Idioma del reporte
            </span>
          </SectionHeading>
          <Card className="p-5">
            <div className="flex gap-3">
              {LANGUAGE_OPTIONS.map(opt => {
                const active = settings.language === opt.value
                return (
                  <button
                    key={opt.value}
                    onClick={() => setSettings(prev => ({ ...prev, language: opt.value }))}
                    className={`flex items-center gap-2 px-5 py-2.5 rounded-xl border-2 text-sm font-medium transition-all ${
                      active
                        ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300'
                        : 'border-gray-100 dark:border-gray-800 text-gray-600 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-600'
                    }`}
                  >
                    {opt.label}
                    {active && <Check className="h-3.5 w-3.5" />}
                  </button>
                )
              })}
            </div>
          </Card>
        </section>

        {/* ── Excluded tables ── */}
        <section>
          <SectionHeading>
            <span className="inline-flex items-center gap-2">
              <Table2 className="h-3.5 w-3.5" />
              Tablas excluidas
            </span>
          </SectionHeading>
          <Card className="p-5">
            <p className="text-xs text-gray-400 mb-3">
              Tablas que los agentes deben ignorar completamente. Separa los nombres con comas.
            </p>
            <textarea
              value={excludedTablesText}
              onChange={e => setExcludedTablesText(e.target.value)}
              rows={3}
              placeholder="logs, temp_cache, audit_trail, sessions"
              className="w-full px-3 py-2.5 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent resize-none font-mono"
            />
            {excludedTablesText.trim() && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {excludedTablesText.split(',').map(t => t.trim()).filter(Boolean).map(t => (
                  <span
                    key={t}
                    className="px-2 py-0.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 text-xs rounded font-mono"
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
            <span className="inline-flex items-center gap-2">
              <Webhook className="h-3.5 w-3.5" />
              Webhooks
            </span>
          </SectionHeading>
          <Card>
            {/* Existing webhooks */}
            {loadingWebhooks ? (
              <div className="p-5 space-y-3 animate-pulse">
                {[1, 2].map(i => (
                  <div key={i} className="h-10 bg-gray-100 dark:bg-gray-800 rounded-xl" />
                ))}
              </div>
            ) : webhooks.length > 0 ? (
              <div className="divide-y divide-gray-50 dark:divide-gray-800/50">
                {webhooks.map((wh, i) => (
                  <motion.div
                    key={wh.id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className="flex items-center gap-4 px-5 py-3.5"
                  >
                    <LinkIcon className="h-4 w-4 text-gray-400 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-800 dark:text-gray-200 truncate font-mono">
                        {wh.url}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        Creado {new Date(wh.created_at).toLocaleDateString('es', {
                          day: 'numeric', month: 'short', year: 'numeric',
                        })}
                      </p>
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      wh.active
                        ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400'
                        : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
                    }`}>
                      {wh.active ? 'Activo' : 'Inactivo'}
                    </span>
                    <button
                      onClick={() => handleDeleteWebhook(wh.id)}
                      title="Eliminar webhook"
                      className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="px-5 py-8 text-center">
                <Webhook className="h-8 w-8 text-gray-300 dark:text-gray-700 mx-auto mb-2" />
                <p className="text-sm text-gray-400">Sin webhooks configurados</p>
              </div>
            )}

            {/* Add webhook form */}
            <div className="px-5 pb-5 pt-4 border-t border-gray-50 dark:border-gray-800/50">
              {webhookError && (
                <p className="text-xs text-red-500 mb-2">{webhookError}</p>
              )}
              <div className="flex gap-2">
                <input
                  type="url"
                  value={newWebhookUrl}
                  onChange={e => setNewWebhookUrl(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddWebhook()}
                  placeholder="https://hooks.example.com/notify"
                  className="flex-1 px-3 py-2 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                />
                <button
                  onClick={handleAddWebhook}
                  disabled={addingWebhook || !newWebhookUrl.trim()}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium bg-violet-600 text-white rounded-xl hover:bg-violet-700 disabled:opacity-50 transition-colors"
                >
                  {addingWebhook
                    ? <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    : <Plus className="h-3.5 w-3.5" />
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
            <span className="inline-flex items-center gap-2 text-red-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              Zona de peligro
            </span>
          </SectionHeading>
          <Card className="border-red-100 dark:border-red-900/40">
            <div className="p-5 flex items-start justify-between gap-6">
              <div>
                <p className="text-sm font-medium text-gray-800 dark:text-gray-200 mb-1">
                  Restablecer perfil de refinamiento
                </p>
                <p className="text-xs text-gray-400 leading-relaxed max-w-md">
                  Borra todas las preferencias de análisis: profundidad, áreas de foco, idioma y tablas excluidas.
                  El historial de runs y los hallazgos no se ven afectados.
                </p>
              </div>
              <div className="flex-shrink-0 flex flex-col items-end gap-2">
                <button
                  onClick={handleReset}
                  disabled={resetting}
                  className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-xl border transition-all ${
                    confirmReset
                      ? 'bg-red-600 text-white border-red-600 hover:bg-red-700'
                      : 'bg-white dark:bg-gray-900 text-red-600 border-red-200 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-900/20'
                  } disabled:opacity-60`}
                >
                  {resetting ? (
                    <><RefreshCw className="h-3.5 w-3.5 animate-spin" />Restableciendo…</>
                  ) : confirmReset ? (
                    <><AlertTriangle className="h-3.5 w-3.5" />Confirmar restablecimiento</>
                  ) : (
                    <><Trash2 className="h-3.5 w-3.5" />Restablecer perfil</>
                  )}
                </button>
                {confirmReset && !resetting && (
                  <button
                    onClick={() => setConfirmReset(false)}
                    className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
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
