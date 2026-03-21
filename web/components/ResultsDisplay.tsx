'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import {
  RefreshCw, FileText, AlertOctagon, AlertTriangle,
  Info, CheckCircle2, TrendingUp, Clock, Database,
  ChevronDown, ChevronUp, Copy, Check, Zap, HelpCircle, XCircle, Share2,
} from 'lucide-react'
import {
  parseReport,
  type ParsedReport, type Finding, type KPI,
  type ContradictionRow, type ActionRow,
} from '@/lib/reportParser'
import { DeltaPanel } from '@/components/DeltaPanel'
import { DQScoreBadge } from '@/components/DQScoreBadge'

interface DataQuality {
  score: number
  confidence_label: string
  data_quality_tag: string
  warnings?: string[]
  decision?: string
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Report { type: string; title: string; content: string }
interface ResultsDisplayProps { analysisId: string; onNewAnalysis: () => void }

// Extends the base Finding with optional DQ fields injected from API data
type FindingWithDQ = Finding & {
  confidence_label?: string
  confidence_score?: number
}

// ── Severity config ───────────────────────────────────────────────────────────
const SEV = {
  CRITICAL: {
    icon: <AlertOctagon className="h-4 w-4" />,
    label: 'Crítico',
    pill: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    border: 'border-red-200 dark:border-red-800',
    header: 'bg-red-50 dark:bg-red-900/20',
    dot: 'bg-red-500',
    bar: 'bg-red-500',
  },
  HIGH: {
    icon: <AlertTriangle className="h-4 w-4" />,
    label: 'Alto',
    pill: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
    border: 'border-orange-200 dark:border-orange-800',
    header: 'bg-orange-50 dark:bg-orange-900/20',
    dot: 'bg-orange-500',
    bar: 'bg-orange-500',
  },
  MEDIUM: {
    icon: <AlertTriangle className="h-4 w-4" />,
    label: 'Medio',
    pill: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
    border: 'border-yellow-200 dark:border-yellow-800',
    header: 'bg-yellow-50 dark:bg-yellow-900/20',
    dot: 'bg-yellow-500',
    bar: 'bg-yellow-400',
  },
  LOW: {
    icon: <Info className="h-4 w-4" />,
    label: 'Bajo',
    pill: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    border: 'border-blue-200 dark:border-blue-800',
    header: 'bg-blue-50 dark:bg-blue-900/20',
    dot: 'bg-blue-400',
    bar: 'bg-blue-400',
  },
  INFO: {
    icon: <Info className="h-4 w-4" />,
    label: 'Info',
    pill: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
    border: 'border-gray-200 dark:border-gray-700',
    header: 'bg-gray-50 dark:bg-gray-800/50',
    dot: 'bg-gray-400',
    bar: 'bg-gray-400',
  },
}

const CONF = {
  MEASURED:  { label: 'Medido',   icon: <CheckCircle2 className="h-3 w-3" />, cls: 'text-emerald-700 bg-emerald-50 dark:text-emerald-300 dark:bg-emerald-900/30' },
  ESTIMATED: { label: 'Estimado', icon: <Clock className="h-3 w-3" />,        cls: 'text-amber-700 bg-amber-50 dark:text-amber-300 dark:bg-amber-900/30' },
  INFERRED:  { label: 'Inferido', icon: <TrendingUp className="h-3 w-3" />,   cls: 'text-blue-700 bg-blue-50 dark:text-blue-300 dark:bg-blue-900/30' },
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-4">
      {children}
    </h2>
  )
}

function KPICard({ kpi, i }: { kpi: KPI; i: number }) {
  const conf = CONF[kpi.confidence]
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.05 * i, duration: 0.35 }}
      className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-5 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all"
    >
      <p className="text-xs text-gray-500 dark:text-gray-400 leading-snug mb-2">{kpi.label}</p>
      <p className="text-2xl font-bold text-gray-900 dark:text-white tracking-tight leading-none">{kpi.value}</p>
      <div className="mt-3">
        <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${conf.cls}`}>
          {conf.icon}{conf.label}
        </span>
      </div>
    </motion.div>
  )
}

function SqlBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(sql)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <div className="mt-4 rounded-xl overflow-hidden border border-gray-800">
      <div className="flex items-center justify-between bg-gray-900 px-4 py-2">
        <span className="flex items-center gap-2 text-xs text-gray-400">
          <Database className="h-3.5 w-3.5" />SQL diagnóstico
        </span>
        <button onClick={copy} className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors">
          {copied
            ? <><Check className="h-3.5 w-3.5 text-emerald-400" />Copiado</>
            : <><Copy className="h-3.5 w-3.5" />Copiar</>}
        </button>
      </div>
      <pre className="bg-gray-950 text-emerald-300 text-xs p-4 overflow-x-auto leading-relaxed">{sql}</pre>
    </div>
  )
}

function BodyText({ text }: { text: string }) {
  const paras = text.split('\n\n').map(p => p.trim()).filter(Boolean)
  return (
    <div className="space-y-2">
      {paras.map((para, i) => (
        <p key={i} className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">{para}</p>
      ))}
    </div>
  )
}

function ConfidenceBadge({ label }: { label: string }) {
  const map: Record<string, string> = {
    CONFIRMED: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800',
    PROVISIONAL: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800',
    UNVERIFIED: 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-900/30 dark:text-orange-300 dark:border-orange-800',
    BLOCKED: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800',
  }
  const cls = map[label] ?? map['PROVISIONAL']
  return (
    <span className={`inline-flex items-center text-xs font-semibold px-2 py-0.5 rounded-full border ${cls}`}>
      {label}
    </span>
  )
}

function FindingCard({ finding, i, onFalsePositive }: {
  finding: FindingWithDQ;
  i: number;
  onFalsePositive?: (id: string) => void
}) {
  const [open, setOpen] = useState(i === 0)
  const [note, setNote] = useState('')
  const [savedNote, setSavedNote] = useState('')
  const [showNoteInput, setShowNoteInput] = useState(false)
  const s = SEV[finding.severity]

  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.06 * i, duration: 0.3 }}
      className={`rounded-2xl border overflow-hidden ${s.border}`}
    >
      {/* Accent bar */}
      <div className={`h-0.5 w-full ${s.bar}`} />

      <button
        onClick={() => setOpen(o => !o)}
        className={`w-full flex items-center gap-3 px-5 py-4 text-left ${s.header} hover:brightness-[0.97] transition-all`}
      >
        <span className={`flex-shrink-0 inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full ${s.pill}`}>
          {s.icon}{s.label.toUpperCase()}
        </span>
        <span className="flex-1 text-sm font-semibold text-gray-900 dark:text-white">{finding.title}</span>
        {(finding.confidence_label || finding.confidence_score !== undefined) && (
          <ConfidenceBadge label={finding.confidence_label ?? 'PROVISIONAL'} />
        )}
        <span className="text-xs text-gray-400 font-mono mr-2 hidden sm:block">{finding.id}</span>
        {open
          ? <ChevronUp className="h-4 w-4 text-gray-400 flex-shrink-0" />
          : <ChevronDown className="h-4 w-4 text-gray-400 flex-shrink-0" />}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25 }}
            className="overflow-hidden"
          >
            <div className="px-5 py-4 bg-white dark:bg-gray-900 border-t border-gray-100 dark:border-gray-800">
              {finding.bullets.length > 0 ? (
                <ul className="space-y-1.5 mb-3">
                  {finding.bullets.map((b, j) => (
                    <li key={j} className="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
                      <span className={`flex-shrink-0 mt-1.5 w-1.5 h-1.5 rounded-full ${s.dot}`} />
                      {b}
                    </li>
                  ))}
                </ul>
              ) : finding.body ? (
                <BodyText text={finding.body} />
              ) : null}
              {finding.sql && <SqlBlock sql={finding.sql} />}
              {onFalsePositive && (
                <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
                  <button
                    onClick={(e) => { e.stopPropagation(); onFalsePositive(finding.id) }}
                    className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 flex items-center gap-1.5 transition-colors"
                  >
                    <XCircle className="h-3.5 w-3.5" />
                    Marcar como falso positivo
                  </button>
                </div>
              )}
              {/* Annotation */}
              <div className="mt-2">
                {savedNote ? (
                  <div className="flex items-start gap-2 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl px-3 py-2">
                    <span className="text-xs text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5">📝</span>
                    <p className="text-xs text-amber-800 dark:text-amber-200 flex-1">{savedNote}</p>
                    <button onClick={() => { setSavedNote(''); setNote('') }} className="text-amber-400 hover:text-amber-600 text-xs flex-shrink-0">×</button>
                  </div>
                ) : showNoteInput ? (
                  <div className="flex gap-2">
                    <input
                      autoFocus
                      value={note}
                      onChange={e => setNote(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && note.trim()) { setSavedNote(note.trim()); setShowNoteInput(false) } if (e.key === 'Escape') setShowNoteInput(false) }}
                      placeholder="Ej: llamé al cliente, promete pagar el 25..."
                      className="flex-1 text-xs border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-1.5 bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-400"
                    />
                    <button onClick={() => { if (note.trim()) { setSavedNote(note.trim()); setShowNoteInput(false) } }} className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded-lg hover:bg-violet-700 flex-shrink-0">
                      Guardar
                    </button>
                  </div>
                ) : (
                  <button onClick={() => setShowNoteInput(true)} className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 flex items-center gap-1 transition-colors">
                    <span className="text-base leading-none">+</span> Agregar nota interna
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

function ContradictionsTable({ rows }: { rows: ContradictionRow[] }) {
  if (!rows.length) return null
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
      <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
        <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
          Reconciliación de Contradicciones
        </h3>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {rows.map((row, i) => (
          <div key={i} className="grid grid-cols-2 gap-4 px-5 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{row.contradiction}</p>
            <p className="text-sm text-gray-500 dark:text-gray-400">{row.explanation}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function ActionsTable({ rows }: { rows: ActionRow[] }) {
  if (!rows.length) return null
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 overflow-hidden shadow-sm">
      <div className="px-5 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/50">
        <div className="flex items-center gap-2">
          <Zap className="h-4 w-4 text-violet-500" />
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
            5 Acciones Prioritarias
          </h3>
        </div>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {rows.map((row, i) => (
          <div key={i} className="flex items-start gap-4 px-5 py-4 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors">
            <span className="flex-shrink-0 w-7 h-7 rounded-full bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 text-xs font-bold flex items-center justify-center">
              {row.num || i + 1}
            </span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 dark:text-gray-200 leading-snug">{row.action}</p>
              {(row.owner || row.deadline) && (
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  {[row.owner && `Responsable: ${row.owner}`, row.deadline && `Fecha: ${row.deadline}`].filter(Boolean).join(' · ')}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function LimitationsSection({ sections }: { sections: { title: string; body: string }[] }) {
  if (!sections.length) return null
  return (
    <div className="space-y-4">
      {sections.map((sec, i) => (
        <div key={i} className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <HelpCircle className="h-4 w-4 text-gray-400" />
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">{sec.title}</h3>
          </div>
          <BodyText text={sec.body} />
        </div>
      ))}
    </div>
  )
}

// ── OutputKO Hero ─────────────────────────────────────────────────────────────

function OutputKOHero({ findings, runDelta }: {
  findings: Finding[]
  runDelta?: { new?: string[]; resolved?: string[]; worsened?: string[] } | null
}) {
  const topFinding = findings.find(f => f.severity === 'CRITICAL')
    || findings.find(f => f.severity === 'HIGH')
    || findings[0]

  if (!findings.length || !topFinding) return null

  const isCritical = topFinding.severity === 'CRITICAL'
  const isNew = runDelta?.new?.includes(topFinding.id)
  const resolvedCount = runDelta?.resolved?.length || 0
  const newCount = runDelta?.new?.length || 0

  return (
    <motion.div
      initial={{ opacity: 0, y: -16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className={`relative rounded-3xl overflow-hidden ${
        isCritical
          ? 'bg-gradient-to-br from-red-950 via-red-900 to-red-800 border border-red-700'
          : 'bg-gradient-to-br from-orange-950 via-orange-900 to-amber-900 border border-orange-700'
      }`}
    >
      {/* Subtle noise texture */}
      <div className="absolute inset-0 opacity-5"
        style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=\'0 0 256 256\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cfilter id=\'noise\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.9\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100%25\' height=\'100%25\' filter=\'url(%23noise)\'/%3E%3C/svg%3E")' }}
      />

      <div className="relative px-7 py-6">
        {/* Eyebrow */}
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <span className="flex items-center gap-1.5 text-xs font-mono tracking-widest uppercase text-red-300/80">
            <span className={`w-1.5 h-1.5 rounded-full ${isCritical ? 'bg-red-400 animate-pulse' : 'bg-orange-400'}`} />
            Acción prioritaria · {topFinding.id}
          </span>
          {isNew && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-red-500/30 text-red-200 border border-red-500/40">
              Nuevo este período
            </span>
          )}
        </div>

        {/* Main message */}
        <h2 className="text-2xl sm:text-3xl font-bold text-white leading-tight mb-3 max-w-3xl">
          {topFinding.title}
        </h2>

        {/* Top bullet if available */}
        {topFinding.bullets[0] && (
          <p className="text-base text-red-100/80 leading-relaxed mb-5 max-w-2xl">
            {topFinding.bullets[0]}
          </p>
        )}

        {/* Progress bar — resolved vs total */}
        {(resolvedCount > 0 || newCount > 0) && (
          <div className="flex items-center gap-4 pt-4 border-t border-white/10">
            {resolvedCount > 0 && (
              <span className="flex items-center gap-1.5 text-sm text-emerald-300 font-medium">
                <CheckCircle2 className="h-4 w-4" />
                {resolvedCount} resuelto{resolvedCount > 1 ? 's' : ''} vs período anterior
              </span>
            )}
            {newCount > 0 && (
              <span className="flex items-center gap-1.5 text-sm text-red-300 font-medium">
                <AlertOctagon className="h-4 w-4" />
                {newCount} nuevo{newCount > 1 ? 's' : ''} este período
              </span>
            )}
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ── Improvement Banner ────────────────────────────────────────────────────────

function ImprovementBanner({ runDelta, runCount }: {
  runDelta: any;
  runCount?: number
}) {
  const resolved = runDelta?.resolved?.length || 0
  const improved = runDelta?.improved?.length || 0
  const total = resolved + improved

  if (total === 0 || !runCount || runCount <= 1) return null

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      className="flex items-center gap-3 px-5 py-3.5 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-2xl"
    >
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-100 dark:bg-emerald-900/50 flex items-center justify-center">
        <TrendingUp className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
      </div>
      <div>
        <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
          El sistema aprendió — {total} issue{total > 1 ? 's' : ''} mejor{total > 1 ? 'es' : ''} que el período anterior
        </p>
        <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5">
          {resolved > 0 && `${resolved} resuelto${resolved > 1 ? 's' : ''}`}
          {resolved > 0 && improved > 0 && ' · '}
          {improved > 0 && `${improved} con severidad reducida`}
          {runCount > 1 && ` · Run #${runCount}`}
        </p>
      </div>
    </motion.div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function ResultsDisplay({ analysisId, onNewAnalysis }: ResultsDisplayProps) {
  const [reports, setReports] = useState<Report[]>([])
  const [activeTab, setActiveTab] = useState(0)
  const [loading, setLoading] = useState(true)
  const [runDelta, setRunDelta] = useState<any>(null)
  const [knownFindings, setKnownFindings] = useState<any>(null)
  const [markedFP, setMarkedFP] = useState<Set<string>>(new Set())
  const [copiedLink, setCopiedLink] = useState(false)
  const [dataQuality, setDataQuality] = useState<DataQuality | null>(null)
  const [currencyWarnings, setCurrencyWarnings] = useState<string[]>([])

  useEffect(() => {
    axios.get(`${API_URL}/api/jobs/${analysisId}/results`).then(res => {
      const raw = res.data.reports || {}
      const arr: Report[] = Array.isArray(raw)
        ? raw
        : Object.entries(raw).map(([key, content]) => ({
            type: key,
            title: key === 'executive' ? 'Resumen Ejecutivo' : key.charAt(0).toUpperCase() + key.slice(1),
            content: typeof content === 'string' ? content : JSON.stringify(content, null, 2),
          }))
      setReports(arr)
      setRunDelta(res.data.run_delta || null)
      setKnownFindings(res.data.known_findings || null)
      setDataQuality(res.data.data_quality ?? null)
      setCurrencyWarnings(res.data.currency_warnings ?? [])
    }).catch(() => {}).finally(() => setLoading(false))
  }, [analysisId])

  if (loading) return (
    <div className="flex flex-col items-center justify-center py-40 gap-4">
      <div className="relative h-14 w-14">
        <div className="absolute inset-0 rounded-full border-4 border-violet-100 dark:border-violet-900" />
        <div className="absolute inset-0 rounded-full border-4 border-t-violet-600 animate-spin" />
      </div>
      <p className="text-sm text-gray-400 animate-pulse">Cargando reporte…</p>
    </div>
  )

  if (!reports.length) return (
    <div className="flex flex-col items-center justify-center py-40 gap-4">
      <FileText className="h-12 w-12 text-gray-300" />
      <p className="text-gray-500">No se encontraron reportes.</p>
      <button onClick={onNewAnalysis} className="px-4 py-2 bg-violet-600 text-white rounded-xl text-sm font-medium">
        Nuevo análisis
      </button>
    </div>
  )

  const active = reports[activeTab]
  const parsed: ParsedReport = parseReport(active.content)

  const handleFalsePositive = async (findingId: string) => {
    if (!parsed.clientName) return
    try {
      await axios.put(`${API_URL}/api/clients/${encodeURIComponent(parsed.clientName)}/profile/false-positive?finding_id=${encodeURIComponent(findingId)}`)
      setMarkedFP(prev => { const next = new Set(prev); next.add(findingId); return next })
    } catch (e) {
      console.error('Failed to mark false positive', e)
    }
  }

  const visibleFindings = parsed.findings.filter(f => !markedFP.has(f.id))

  const criticalCount = visibleFindings.filter(f => f.severity === 'CRITICAL').length
  const highCount     = visibleFindings.filter(f => f.severity === 'HIGH').length

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-5xl mx-auto space-y-8 pb-20">

      {/* ── Data Quality Badge ── */}
      {dataQuality && (
        <DQScoreBadge
          score={dataQuality.score}
          label={dataQuality.confidence_label}
          tag={dataQuality.data_quality_tag}
          warnings={dataQuality.warnings}
          compact={false}
        />
      )}

      {/* ── DQ Warnings Banner ── */}
      {dataQuality?.decision === 'PROCEED_WITH_WARNINGS' && dataQuality.warnings && dataQuality.warnings.length > 0 && (
        <div className="flex gap-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-2xl px-5 py-4">
          <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-800 dark:text-amber-200 mb-1">
              Analysis completado con advertencias de calidad de datos
            </p>
            <ul className="space-y-0.5">
              {dataQuality.warnings.slice(0, 2).map((w, i) => (
                <li key={i} className="text-xs text-amber-700 dark:text-amber-300">{w}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* ── Currency Warnings ── */}
      {currencyWarnings.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl text-sm text-amber-700 dark:text-amber-300">
          <span>⚠</span>
          <span>
            Mezcla de monedas detectada en {currencyWarnings.length} consulta{currencyWarnings.length > 1 ? 's' : ''} — los totales usan moneda de empresa
          </span>
        </div>
      )}

      {/* ── OutputKO Hero ── */}
      <OutputKOHero findings={visibleFindings} runDelta={runDelta} />

      {/* ── Top bar ── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
              <CheckCircle2 className="h-3 w-3" />Análisis completado
            </span>
            {criticalCount > 0 && (
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300 border border-red-200 dark:border-red-800">
                <AlertOctagon className="h-3 w-3" />{criticalCount} crítico{criticalCount > 1 ? 's' : ''}
              </span>
            )}
            {highCount > 0 && (
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-orange-50 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300 border border-orange-200 dark:border-orange-800">
                <AlertTriangle className="h-3 w-3" />{highCount} alto{highCount > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">
            {parsed.clientName || 'Reporte de Inteligencia'}
          </h1>
          <p className="text-sm text-gray-400 mt-1.5 font-mono">
            {[
              parsed.analysisDate && `Análisis: ${parsed.analysisDate}`,
              parsed.dataThrough && `Datos hasta: ${parsed.dataThrough}`,
              parsed.currency && `Divisa: ${parsed.currency}`,
            ].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onNewAnalysis}
            className="flex-shrink-0 flex items-center gap-2 px-4 py-2.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-violet-400 dark:hover:border-violet-500 text-gray-700 dark:text-gray-300 rounded-xl transition-all text-sm font-medium shadow-sm"
          >
            <RefreshCw className="h-4 w-4" />Nuevo análisis
          </button>
          <button
            onClick={() => {
              const url = `${window.location.origin}?report=${analysisId}`
              navigator.clipboard.writeText(url).then(() => {
                setCopiedLink(true)
                setTimeout(() => setCopiedLink(false), 2500)
              })
            }}
            className="flex-shrink-0 flex items-center gap-2 px-4 py-2.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-violet-400 dark:hover:border-violet-500 text-gray-700 dark:text-gray-300 rounded-xl transition-all text-sm font-medium shadow-sm"
          >
            {copiedLink
              ? <><Check className="h-4 w-4 text-emerald-500" />Copiado!</>
              : <><Share2 className="h-4 w-4" />Compartir</>
            }
          </button>
          {parsed.clientName && (
            <a
              href={`/clients/${encodeURIComponent(parsed.clientName)}/history`}
              className="flex-shrink-0 flex items-center gap-2 px-4 py-2.5 bg-violet-600 hover:bg-violet-700 text-white rounded-xl transition-all text-sm font-medium shadow-sm"
            >
              <TrendingUp className="h-4 w-4" />Ver historial
            </a>
          )}
        </div>
      </div>

      {/* ── Improvement Banner ── */}
      <ImprovementBanner runDelta={runDelta} runCount={undefined} />

      {/* ── Report tabs (if multiple) ── */}
      {reports.length > 1 && (
        <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 p-1 rounded-xl w-fit">
          {reports.map((r, i) => (
            <button key={i} onClick={() => setActiveTab(i)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${activeTab === i ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-700'}`}>
              {r.title}
            </button>
          ))}
        </div>
      )}

      {/* ── Caveat banner ── */}
      {parsed.caveat && (
        <motion.div
          initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
          className="flex gap-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-2xl px-5 py-4"
        >
          <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-amber-800 dark:text-amber-200 leading-relaxed">{parsed.caveat}</p>
        </motion.div>
      )}

      {/* ── Delta panel ── */}
      {runDelta && (
        <DeltaPanel
          runDelta={runDelta}
          knownFindings={knownFindings}
        />
      )}

      {/* ── KPI grid ── */}
      {parsed.kpis.length > 0 && (
        <div>
          <SectionLabel>Las Cifras que Importan</SectionLabel>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {parsed.kpis.map((kpi, i) => <KPICard key={i} kpi={kpi} i={i} />)}
          </div>
        </div>
      )}

      {/* ── Findings ── */}
      {visibleFindings.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
            <SectionLabel>Hallazgos — Ranking por Impacto × Urgencia</SectionLabel>
            <div className="flex gap-3 text-xs mb-4">
              {criticalCount > 0 && (
                <span className="flex items-center gap-1 text-red-500 font-medium">
                  <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />{criticalCount} crítico{criticalCount > 1 ? 's' : ''}
                </span>
              )}
              {highCount > 0 && (
                <span className="flex items-center gap-1 text-orange-500 font-medium">
                  <span className="w-2 h-2 rounded-full bg-orange-500 inline-block" />{highCount} alto{highCount > 1 ? 's' : ''}
                </span>
              )}
              <span className="text-gray-400">{visibleFindings.length} total</span>
            </div>
          </div>
          <div className="space-y-3">
            {visibleFindings.map((f, i) => <FindingCard key={f.id} finding={f} i={i} onFalsePositive={handleFalsePositive} />)}
          </div>
        </div>
      )}

      {/* ── Contradictions ── */}
      {parsed.contradictions.length > 0 && (
        <ContradictionsTable rows={parsed.contradictions} />
      )}

      {/* ── Actions ── */}
      {parsed.actions.length > 0 && (
        <ActionsTable rows={parsed.actions} />
      )}

      {/* ── Other sections (limitations, etc.) ── */}
      <LimitationsSection sections={parsed.sections} />

      {/* ── Raw fallback (collapsed) ── */}
      <details className="group">
        <summary className="cursor-pointer text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 select-none py-1">
          Ver markdown original
        </summary>
        <pre className="mt-2 text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4 overflow-auto max-h-96 whitespace-pre-wrap">
          {active.content}
        </pre>
      </details>

    </motion.div>
  )
}

export default ResultsDisplay
