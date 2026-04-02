'use client'

import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle, AlertTriangle, Clock, ArrowRight } from 'lucide-react'
import { T, SEV_COLOR, SEV_LABEL } from '@/components/d4c/tokens'
import { ConfidenceBadge, MicroBadge } from '@/components/ui/ConfidenceBadge'
import { TrustScoreHeader } from '@/components/findings/TrustScoreHeader'
import { AuditTrailPanel } from '@/components/findings/AuditTrailPanel'
import { useCountUp } from '@/hooks/useCountUp'
import { KOReportV2 } from '@/components/ko-report/KOReportV2'
import type { ParsedReport } from '@/lib/reportParser'
import type { AnalysisConfidenceMetadata } from '@/lib/confidence-types'

// ── Types ────────────────────────────────────────────────────────────────────

interface KOReportRevealProps {
  report: ParsedReport
  dqScore?: number
  companyName?: string
  confidenceMetadata?: AnalysisConfidenceMetadata
}

// ── Shared styles ────────────────────────────────────────────────────────────

const s = {
  card: {
    background: T.bg.card,
    border: T.border.card,
    borderRadius: T.radius.md,
    padding: T.space.lg,
  },
  mono: { fontFamily: T.font.mono },
  display: { fontFamily: T.font.display },
} as const

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Extract the first monetary/numeric value from a string. Returns { raw, numeric } */
function extractMonetaryValue(text: string): { raw: string; numeric: number; prefix: string; suffix: string } | null {
  // Match patterns like $3.2M, $3,200,000, $3.200.000, €1.5M, etc.
  const match = text.match(/([€$USD\s]*)(\d[\d.,]*)\s*(M|MM|mil|millones|K)?/i)
  if (!match) return null

  const prefix = match[1]?.trim() || '$'
  let numStr = match[2].replace(/\./g, '').replace(/,/g, '.')
  let numeric = parseFloat(numStr)
  const suffix = match[3] || ''

  if (/^M$/i.test(suffix)) numeric *= 1_000_000
  else if (/^MM$/i.test(suffix)) numeric *= 1_000_000
  else if (/^mil$/i.test(suffix)) numeric *= 1_000
  else if (/^millones$/i.test(suffix)) numeric *= 1_000_000
  else if (/^K$/i.test(suffix)) numeric *= 1_000

  return { raw: match[0], numeric, prefix, suffix }
}

function formatCurrency(value: number, prefix: string): string {
  if (value >= 1_000_000) {
    return `${prefix}${(value / 1_000_000).toLocaleString('es-AR', { maximumFractionDigits: 1 })}M`
  }
  if (value >= 1_000) {
    return `${prefix}${Math.round(value).toLocaleString('es-AR')}`
  }
  return `${prefix}${value.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}

function formatDuration(seconds: number): string {
  const min = Math.floor(seconds / 60)
  const sec = Math.round(seconds % 60)
  if (min > 0) return `${min} min ${sec} seg`
  return `${sec} seg`
}

/** Parse a KPI value to a number, or return null */
function parseKPINumeric(value: string): number | null {
  const cleaned = value.replace(/[^0-9.,%-]/g, '')
  if (!cleaned) return null
  const num = parseFloat(cleaned.replace(/\./g, '').replace(',', '.'))
  return isNaN(num) ? null : num
}

// ── StatusBadge ──────────────────────────────────────────────────────────────

function StatusBadge({ severity }: { severity: string }) {
  const color = SEV_COLOR[severity] ?? T.accent.blue
  return (
    <span style={{
      ...s.mono,
      fontSize: 10,
      fontWeight: 600,
      letterSpacing: '0.05em',
      textTransform: 'uppercase' as const,
      color,
      background: color + '20',
      border: `1px solid ${color}40`,
      borderRadius: T.radius.sm,
      padding: '2px 8px',
    }}>
      {SEV_LABEL[severity] ?? severity}
    </span>
  )
}

// ── FindingCard (reveal variant) ─────────────────────────────────────────────

function RevealFindingCard({
  finding,
  confidenceMetadata,
  index,
  auditOpen,
  onAuditToggle,
}: {
  finding: ParsedReport['findings'][number]
  confidenceMetadata?: AnalysisConfidenceMetadata
  index: number
  auditOpen: boolean
  onAuditToggle: (findingId: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const color = SEV_COLOR[finding.severity] ?? T.accent.blue

  return (
    <div
      style={{
        ...s.card,
        borderLeft: `3px solid ${color}`,
        cursor: 'pointer',
        transition: 'background 0.15s',
      }}
      onClick={() => setExpanded(e => !e)}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: T.space.sm, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: T.space.sm, flex: 1, flexWrap: 'wrap' }}>
          <StatusBadge severity={finding.severity} />
          {(() => {
            const fc = confidenceMetadata?.findings_confidence?.[finding.id]
            return fc ? (
              <ConfidenceBadge
                level={fc.level}
                tooltip={{ record_count: fc.record_count, null_rate: fc.null_rate, source_tables: fc.source_tables }}
                delay={index * 0.1}
              />
            ) : null
          })()}
          <div>
            <div style={{ ...s.mono, fontSize: 10, color: T.text.tertiary, marginBottom: 4 }}>
              {finding.id}
            </div>
            <div style={{ ...s.display, fontSize: 14, fontWeight: 600, color: T.text.primary, lineHeight: 1.4 }}>
              {finding.title}
            </div>
          </div>
        </div>
        <span style={{ ...s.mono, fontSize: 16, color: T.text.tertiary, flexShrink: 0 }}>
          {expanded ? '\u25B4' : '\u25BE'}
        </span>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div style={{ marginTop: T.space.md, borderTop: T.border.subtle, paddingTop: T.space.md }}>
          {finding.bullets.length > 0 ? (
            <ul style={{ margin: 0, padding: `0 0 0 ${T.space.md}`, listStyle: 'none' }}>
              {finding.bullets.map((b, i) => (
                <li key={i} style={{
                  ...s.display,
                  fontSize: 13,
                  color: T.text.secondary,
                  lineHeight: 1.6,
                  marginBottom: T.space.xs,
                  paddingLeft: T.space.sm,
                  borderLeft: `2px solid ${color}40`,
                }}>
                  {b}
                </li>
              ))}
            </ul>
          ) : (
            <p style={{ ...s.display, fontSize: 13, color: T.text.secondary, margin: 0, lineHeight: 1.6 }}>
              {finding.body}
            </p>
          )}
          {finding.sql && (
            <pre style={{
              ...s.mono,
              fontSize: 11,
              color: T.text.tertiary,
              background: T.bg.elevated,
              borderRadius: T.radius.sm,
              padding: T.space.sm,
              marginTop: T.space.sm,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
            }}>
              {finding.sql}
            </pre>
          )}
        </div>
      )}

      {/* Audit trail panel */}
      {confidenceMetadata?.findings_confidence?.[finding.id] && (
        <div
          style={{ marginTop: T.space.md }}
          onClick={(e) => e.stopPropagation()}
        >
          <AuditTrailPanel
            findingId={finding.id}
            confidence={confidenceMetadata.findings_confidence[finding.id]}
            isOpen={auditOpen}
            onToggle={onAuditToggle}
          />
        </div>
      )}
    </div>
  )
}

// ── KPI Card with count-up ───────────────────────────────────────────────────

function KPICard({
  kpi,
  confidenceMetadata,
  delayMs,
  index,
}: {
  kpi: ParsedReport['kpis'][number]
  confidenceMetadata?: AnalysisConfidenceMetadata
  delayMs: number
  index: number
}) {
  const numericValue = parseKPINumeric(kpi.value)
  const animatedValue = useCountUp(numericValue ?? 0, 800, delayMs)
  const kpiConf = confidenceMetadata?.kpi_confidence?.[kpi.label]
  const color = kpi.confidence === 'MEASURED' ? T.accent.teal : T.accent.blue

  // Build display value: if numeric, show animated; else show static
  const displayValue = numericValue !== null
    ? kpi.value.replace(/[\d.,]+/, animatedValue.toLocaleString('es-AR'))
    : kpi.value

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: delayMs / 1000, ease: 'easeOut' }}
      style={{
        ...s.card,
        borderLeft: `3px solid ${color}`,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.xs,
        position: 'relative',
        willChange: 'transform, opacity',
      }}
    >
      {kpiConf && (
        <div style={{ position: 'absolute', top: T.space.sm, right: T.space.sm }}>
          <MicroBadge
            level={kpiConf.level}
            tooltip={{ record_count: kpiConf.record_count, null_rate: kpiConf.null_rate, source_tables: kpiConf.source_tables }}
            delay={index * 0.1}
          />
        </div>
      )}
      <div style={{
        ...s.mono, fontSize: 28, fontWeight: 700, color, lineHeight: 1.1,
      }}>
        {displayValue}
      </div>
      <div style={{ ...s.display, fontSize: 12, color: T.text.secondary, marginTop: 2 }}>
        {kpi.label}
      </div>
    </motion.div>
  )
}

// ── Urgency badge ────────────────────────────────────────────────────────────

function UrgencyBadge({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      ...s.mono,
      fontSize: 9,
      fontWeight: 700,
      letterSpacing: '0.08em',
      textTransform: 'uppercase' as const,
      color,
      background: color + '18',
      border: `1px solid ${color}40`,
      borderRadius: T.radius.sm,
      padding: '2px 8px',
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

function getUrgency(index: number): { label: string; color: string } {
  if (index < 2) return { label: 'ESTA SEMANA', color: T.accent.red }
  if (index < 4) return { label: 'SEMANA 2', color: T.accent.orange }
  return { label: 'ESTE MES', color: T.accent.yellow }
}

// ── Main Component ───────────────────────────────────────────────────────────

export function KOReportReveal({ report, dqScore, companyName, confidenceMetadata }: KOReportRevealProps) {
  const [openAuditId, setOpenAuditId] = useState<string | null>(null)
  const [showAllFindings, setShowAllFindings] = useState(false)
  const [checkedActions, setCheckedActions] = useState<Record<number, boolean>>({})
  const [showFullReport, setShowFullReport] = useState(false)

  const name = companyName ?? report.clientName
  const today = new Date().toLocaleDateString('es-AR', { year: 'numeric', month: 'long', day: 'numeric' })

  const handleAuditToggle = (findingId: string) => {
    setOpenAuditId(prev => prev === findingId ? null : findingId)
  }

  // Extract hero value from first CRITICAL finding
  const heroData = useMemo(() => {
    const critical = report.findings.find(f => f.severity === 'CRITICAL')
    if (!critical) return null
    const extracted = extractMonetaryValue(critical.title)
    if (!extracted) return null
    return { ...extracted, title: critical.title }
  }, [report.findings])

  const heroAnimated = useCountUp(heroData?.numeric ?? 0, 800, 400)

  // Visible findings (max 5 initially)
  const visibleFindings = showAllFindings ? report.findings : report.findings.slice(0, 5)
  const hasMoreFindings = report.findings.length > 5

  // Pipeline duration
  const pipelineDuration = confidenceMetadata?.pipeline_duration_seconds

  // ── Phase timing (ms) ──
  const PHASE_1_START = 0
  const PHASE_2_START = 1200
  const PHASE_3_START = PHASE_2_START + Math.min(visibleFindings.length, 5) * 200 + 400
  const PHASE_4_START = PHASE_3_START + report.kpis.length * 100 + 600
  const PHASE_5_START = PHASE_4_START + report.actions.length * 100 + 400

  return (
    <div style={{
      background: T.bg.primary,
      minHeight: '100vh',
      fontFamily: T.font.display,
      color: T.text.primary,
    }}>
      {/* Print styles + font import */}
      <style>{`
        @media print {
          body { background: white; color: #111; }
          .no-print { display: none !important; }
        }
        @import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&family=DM+Mono:wght@400;500&display=swap');
        @media (max-width: 640px) {
          .reveal-hero-number { font-size: 40px !important; }
          .reveal-kpi-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>

      {/* ── Nav Header ── */}
      <header style={{
        background: T.bg.card,
        borderBottom: T.border.card,
        padding: `${T.space.md} ${T.space.xl}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.md }}>
          <div style={{ ...s.mono, fontSize: 14, fontWeight: 700, color: T.accent.teal, letterSpacing: '-0.02em' }}>
            ◈ VALINOR
          </div>
          <div style={{ width: 1, height: 16, background: T.bg.hover }} />
          <div style={{ ...s.display, fontSize: 13, color: T.text.secondary }}>
            Diagnóstico Empresarial
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}>
          {dqScore !== undefined && (
            <div style={{ display: 'flex', alignItems: 'center', gap: T.space.xs }}>
              <span style={{ ...s.mono, fontSize: 11, color: T.text.tertiary }}>DQ</span>
              <span style={{
                ...s.mono,
                fontSize: 13,
                fontWeight: 700,
                color: dqScore >= 0.8 ? T.accent.teal : dqScore >= 0.6 ? T.accent.yellow : T.accent.red,
              }}>
                {Math.round(dqScore * 100)}%
              </span>
            </div>
          )}
          <button
            className="no-print"
            onClick={() => window.print()}
            style={{
              ...s.mono,
              fontSize: 11,
              color: T.text.tertiary,
              background: 'transparent',
              border: T.border.card,
              borderRadius: T.radius.sm,
              padding: `${T.space.xs} ${T.space.sm}`,
              cursor: 'pointer',
            }}
          >
            ▸ PDF
          </button>
        </div>
      </header>

      <main style={{ maxWidth: 960, margin: '0 auto', padding: `${T.space.xxl} ${T.space.xl}` }}>

        {/* ═══════════════════════════════════════════════════════════════════════
            PHASE 1: Hero Section (0-1200ms)
            ═══════════════════════════════════════════════════════════════════════ */}
        <motion.section
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          style={{
            marginBottom: T.space.xxl,
            textAlign: 'center',
            willChange: 'transform, opacity',
          }}
        >
          {/* Company + date */}
          <div style={{
            ...s.display,
            fontSize: 16,
            color: T.text.secondary,
            marginBottom: T.space.lg,
          }}>
            {name} · {report.analysisDate || today}
          </div>

          {/* Hero monetary value */}
          {heroData && (
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.5, delay: 0.3 }}
              style={{ willChange: 'transform, opacity' }}
            >
              <div
                className="reveal-hero-number"
                style={{
                  ...s.display,
                  fontSize: 64,
                  fontWeight: 700,
                  color: T.accent.red,
                  lineHeight: 1.1,
                  letterSpacing: '-0.02em',
                  marginBottom: T.space.md,
                }}
              >
                {formatCurrency(heroAnimated, heroData.prefix)}
              </div>

              {/* Loss-framing headline */}
              <div style={{
                ...s.display,
                fontSize: 20,
                fontWeight: 500,
                color: T.text.primary,
                lineHeight: 1.4,
                maxWidth: 600,
                margin: '0 auto',
                marginBottom: T.space.lg,
              }}>
                Estás dejando de cobrar {formatCurrency(heroData.numeric, heroData.prefix)} en facturas vencidas
              </div>
            </motion.div>
          )}

          {/* Trust Score */}
          {confidenceMetadata?.trust_score && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5, delay: 0.8 }}
              style={{ willChange: 'opacity' }}
            >
              <TrustScoreHeader trustScore={confidenceMetadata.trust_score} />
            </motion.div>
          )}
        </motion.section>

        {/* ═══════════════════════════════════════════════════════════════════════
            PHASE 2: Findings Staggered Reveal (1200ms+)
            ═══════════════════════════════════════════════════════════════════════ */}
        <section style={{ marginBottom: T.space.xxl }}>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: PHASE_2_START / 1000 }}
          >
            <div style={{ marginBottom: T.space.lg }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: T.space.md }}>
                <span style={{
                  ...s.mono, fontSize: 32, fontWeight: 700,
                  color: T.accent.teal + '50', lineHeight: 1,
                }}>01</span>
                <h2 style={{
                  ...s.display, fontSize: 18, fontWeight: 700,
                  color: T.text.primary, margin: 0,
                }}>Hallazgos</h2>
              </div>
              <p style={{ ...s.display, fontSize: 13, color: T.text.secondary, margin: `${T.space.xs} 0 0 0` }}>
                {report.findings.length} hallazgos ordenados por severidad
              </p>
            </div>
          </motion.div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
            {visibleFindings.map((f, i) => (
              <motion.div
                key={f.id || i}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  duration: 0.4,
                  delay: (PHASE_2_START + i * 200) / 1000,
                  ease: 'easeOut',
                }}
                style={{ willChange: 'transform, opacity' }}
              >
                <RevealFindingCard
                  finding={f}
                  confidenceMetadata={confidenceMetadata}
                  index={i}
                  auditOpen={openAuditId === f.id}
                  onAuditToggle={handleAuditToggle}
                />
              </motion.div>
            ))}
          </div>

          {/* Show more / show full report */}
          {hasMoreFindings && !showAllFindings && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: (PHASE_2_START + 5 * 200 + 200) / 1000 }}
              style={{ textAlign: 'center', marginTop: T.space.lg }}
            >
              <button
                onClick={() => setShowAllFindings(true)}
                style={{
                  ...s.display,
                  fontSize: 13,
                  fontWeight: 500,
                  color: T.accent.teal,
                  background: 'transparent',
                  border: `1px solid ${T.accent.teal}40`,
                  borderRadius: T.radius.sm,
                  padding: `${T.space.sm} ${T.space.lg}`,
                  cursor: 'pointer',
                  transition: 'background 0.15s',
                }}
              >
                Ver todos los hallazgos ({report.findings.length - 5} más)
              </button>
            </motion.div>
          )}
        </section>

        {/* ═══════════════════════════════════════════════════════════════════════
            PHASE 3: KPI Cards Row
            ═══════════════════════════════════════════════════════════════════════ */}
        {report.kpis.length > 0 && (
          <section style={{ marginBottom: T.space.xxl }}>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: PHASE_3_START / 1000 }}
            >
              <div style={{ marginBottom: T.space.lg }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: T.space.md }}>
                  <span style={{
                    ...s.mono, fontSize: 32, fontWeight: 700,
                    color: T.accent.teal + '50', lineHeight: 1,
                  }}>02</span>
                  <h2 style={{
                    ...s.display, fontSize: 18, fontWeight: 700,
                    color: T.text.primary, margin: 0,
                  }}>Cifras Clave</h2>
                </div>
              </div>
            </motion.div>

            <div
              className="reveal-kpi-grid"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                gap: T.space.md,
              }}
            >
              {report.kpis.slice(0, 4).map((kpi, i) => (
                <KPICard
                  key={i}
                  kpi={kpi}
                  confidenceMetadata={confidenceMetadata}
                  delayMs={PHASE_3_START + i * 100}
                  index={i}
                />
              ))}
            </div>
          </section>
        )}

        {/* ═══════════════════════════════════════════════════════════════════════
            PHASE 4: Action Plan
            ═══════════════════════════════════════════════════════════════════════ */}
        {report.actions.length > 0 && (
          <section style={{ marginBottom: T.space.xxl }}>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: PHASE_4_START / 1000 }}
            >
              <div style={{ marginBottom: T.space.lg }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: T.space.md }}>
                  <span style={{
                    ...s.mono, fontSize: 32, fontWeight: 700,
                    color: T.accent.teal + '50', lineHeight: 1,
                  }}>03</span>
                  <h2 style={{
                    ...s.display, fontSize: 18, fontWeight: 700,
                    color: T.text.primary, margin: 0,
                  }}>Plan de Acción</h2>
                </div>
              </div>
            </motion.div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
              {report.actions.map((a, i) => {
                const urgency = getUrgency(i)
                return (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.4,
                      delay: (PHASE_4_START + i * 100) / 1000,
                      ease: 'easeOut',
                    }}
                    style={{ willChange: 'transform, opacity' }}
                  >
                    <div style={{
                      ...s.card,
                      borderLeft: `3px solid ${urgency.color}`,
                      display: 'flex',
                      gap: T.space.md,
                      alignItems: 'flex-start',
                    }}>
                      {/* Checkbox */}
                      <label
                        style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', flexShrink: 0, marginTop: 2 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={!!checkedActions[i]}
                          onChange={() => setCheckedActions(prev => ({ ...prev, [i]: !prev[i] }))}
                          style={{
                            width: 16,
                            height: 16,
                            accentColor: urgency.color,
                            cursor: 'pointer',
                          }}
                        />
                      </label>

                      <div style={{ flex: 1 }}>
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: T.space.sm,
                          marginBottom: T.space.xs,
                          flexWrap: 'wrap',
                        }}>
                          <UrgencyBadge label={urgency.label} color={urgency.color} />
                          <span style={{ ...s.mono, fontSize: 12, fontWeight: 700, color: T.text.tertiary }}>
                            {a.num.padStart(2, '0')}
                          </span>
                        </div>
                        <div style={{
                          ...s.display,
                          fontSize: 13,
                          fontWeight: 500,
                          color: checkedActions[i] ? T.text.tertiary : T.text.primary,
                          textDecoration: checkedActions[i] ? 'line-through' : 'none',
                          transition: 'color 0.2s, text-decoration 0.2s',
                          lineHeight: 1.5,
                        }}>
                          Acción: {a.action}
                        </div>
                        {(a.owner || a.deadline) && (
                          <div style={{ ...s.mono, fontSize: 11, color: T.text.tertiary, marginTop: 4 }}>
                            {a.owner && `Responsable: ${a.owner}`}
                            {a.owner && a.deadline && ' · '}
                            {a.deadline && `Fecha: ${a.deadline}`}
                          </div>
                        )}
                      </div>
                    </div>
                  </motion.div>
                )
              })}
            </div>
          </section>
        )}

        {/* ═══════════════════════════════════════════════════════════════════════
            PHASE 5: Retention CTA
            ═══════════════════════════════════════════════════════════════════════ */}
        <motion.section
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: PHASE_5_START / 1000, ease: 'easeOut' }}
          style={{
            ...s.card,
            textAlign: 'center',
            marginBottom: T.space.xxl,
            background: T.bg.elevated,
            willChange: 'transform, opacity',
          }}
        >
          {pipelineDuration && (
            <div style={{
              ...s.mono,
              fontSize: 12,
              color: T.text.tertiary,
              marginBottom: T.space.md,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: T.space.xs,
            }}>
              <Clock size={14} style={{ opacity: 0.7 }} />
              Este diagnóstico fue generado en {formatDuration(pipelineDuration)}.
            </div>
          )}

          <div style={{
            ...s.display,
            fontSize: 16,
            fontWeight: 500,
            color: T.text.primary,
            marginBottom: T.space.lg,
            lineHeight: 1.5,
          }}>
            Valinor puede monitorear tu empresa continuamente.
          </div>

          <button
            style={{
              ...s.display,
              fontSize: 14,
              fontWeight: 600,
              color: T.text.inverse,
              background: T.accent.teal,
              border: 'none',
              borderRadius: T.radius.md,
              padding: `${T.space.md} ${T.space.xl}`,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: T.space.sm,
              transition: 'opacity 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.9')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          >
            Activar monitoreo continuo
            <ArrowRight size={16} />
          </button>
        </motion.section>

        {/* ═══════════════════════════════════════════════════════════════════════
            Full Report Expander
            ═══════════════════════════════════════════════════════════════════════ */}
        <div style={{ textAlign: 'center', marginBottom: T.space.xxl }}>
          <button
            onClick={() => setShowFullReport(prev => !prev)}
            style={{
              ...s.mono,
              fontSize: 12,
              color: T.text.tertiary,
              background: 'transparent',
              border: T.border.subtle,
              borderRadius: T.radius.sm,
              padding: `${T.space.sm} ${T.space.lg}`,
              cursor: 'pointer',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = T.text.secondary)}
            onMouseLeave={e => (e.currentTarget.style.color = T.text.tertiary)}
          >
            {showFullReport ? 'Ocultar reporte completo' : 'Ver reporte completo detallado'}
          </button>
        </div>

        {showFullReport && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
            style={{ overflow: 'hidden' }}
          >
            <KOReportV2
              report={report}
              dqScore={dqScore}
              companyName={companyName}
              confidenceMetadata={confidenceMetadata}
            />
          </motion.div>
        )}

        {/* ── Footer ── */}
        <footer style={{
          borderTop: T.border.subtle,
          paddingTop: T.space.lg,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div style={{ ...s.mono, fontSize: 11, color: T.text.tertiary }}>
            Generado por Valinor · Delta 4C · {today}
          </div>
          {report.dataThrough && (
            <div style={{ ...s.mono, fontSize: 11, color: T.text.tertiary }}>
              Datos hasta: {report.dataThrough}
            </div>
          )}
        </footer>
      </main>
    </div>
  )
}
