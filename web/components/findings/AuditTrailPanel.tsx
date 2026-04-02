'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Code, Database, Shield, Copy, Check, ChevronDown } from 'lucide-react'
import { T } from '@/components/d4c/tokens'
import type { ConfidenceLevel, FindingConfidence } from '@/lib/confidence-types'

export interface AuditTrailPanelProps {
  findingId: string
  confidence: FindingConfidence
  isOpen: boolean
  onToggle: (findingId: string) => void
}

// ── Constants ─────────────────────────────────────────────────────────────────

const CONFIDENCE_COLOR: Record<ConfidenceLevel, string> = {
  verified: T.accent.teal,
  estimated: T.accent.yellow,
  low_confidence: T.accent.red,
}

const VERIFICATION_LABEL: Record<VerificationMethod, string> = {
  direct_query: '\u2713 Consulta directa verificada',
  cross_agent: '\u2713 Verificado por m\u00faltiples agentes',
  interpolation: '~ Interpolado desde datos parciales',
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const s = {
  mono: { fontFamily: T.font.mono } as React.CSSProperties,
  display: { fontFamily: T.font.display } as React.CSSProperties,
  sectionHeader: {
    fontFamily: T.font.display,
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '1px',
    color: T.text.tertiary,
    margin: 0,
    marginBottom: T.space.sm,
    display: 'flex',
    alignItems: 'center',
    gap: T.space.sm,
  } as React.CSSProperties,
  detailRow: {
    fontFamily: T.font.display,
    fontSize: 13,
    color: T.text.secondary,
    lineHeight: 1.6,
    display: 'flex',
    gap: T.space.sm,
  } as React.CSSProperties,
  label: {
    fontFamily: T.font.mono,
    fontSize: 11,
    color: T.text.tertiary,
    minWidth: 100,
    flexShrink: 0,
  } as React.CSSProperties,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function dqScoreColor(score: number): string {
  if (score >= 8) return T.accent.teal
  if (score >= 5) return T.accent.yellow
  return T.accent.red
}

function formatNumber(n: number): string {
  return n.toLocaleString('es-AR')
}

// ── Component ─────────────────────────────────────────────────────────────────

export function AuditTrailPanel({ findingId, confidence, isOpen, onToggle }: AuditTrailPanelProps) {
  const [copied, setCopied] = useState(false)
  const accentColor = CONFIDENCE_COLOR[confidence.level]

  const handleCopy = async () => {
    await navigator.clipboard.writeText(confidence.sql_query)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onToggle(findingId)
    }
  }

  return (
    <div style={{ width: '100%' }}>
      {/* Toggle button */}
      <button
        onClick={(e) => { e.stopPropagation(); onToggle(findingId) }}
        onKeyDown={handleKeyDown}
        aria-expanded={isOpen}
        aria-controls={`audit-panel-${findingId}`}
        style={{
          ...s.mono,
          fontSize: 11,
          color: accentColor,
          background: 'transparent',
          border: `1px solid ${accentColor}40`,
          borderRadius: T.radius.sm,
          padding: `${T.space.xs} ${T.space.sm}`,
          cursor: 'pointer',
          display: 'inline-flex',
          alignItems: 'center',
          gap: T.space.xs,
          transition: 'background 0.15s',
        }}
      >
        <Shield size={12} />
        Ver evidencia
        <ChevronDown
          size={12}
          style={{
            transition: 'transform 0.3s',
            transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
          }}
        />
      </button>

      {/* Expandable panel */}
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            id={`audit-panel-${findingId}`}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: 'easeInOut' }}
            style={{ overflow: 'hidden' }}
          >
            <div
              style={{
                marginTop: T.space.md,
                paddingLeft: T.space.md,
                borderLeft: `3px solid ${accentColor}`,
                display: 'flex',
                flexDirection: 'column',
                gap: T.space.lg,
              }}
            >
              {/* ── Fuente de datos ── */}
              {(confidence.source_tables.length > 0 || confidence.source_columns.length > 0) && (
                <div>
                  <h4 style={s.sectionHeader}>
                    <Database size={12} />
                    Fuente de datos
                  </h4>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.xs }}>
                    {confidence.source_tables.length > 0 && (
                      <div style={s.detailRow}>
                        <span style={s.label}>Tablas</span>
                        <span style={{ ...s.mono, fontSize: 12, color: T.text.primary }}>
                          {confidence.source_tables.join(', ')}
                        </span>
                      </div>
                    )}

                    {confidence.source_columns.length > 0 && (
                      <div style={s.detailRow}>
                        <span style={s.label}>Columnas</span>
                        <span style={{ ...s.mono, fontSize: 12, color: T.text.primary }}>
                          {confidence.source_columns.join(', ')}
                        </span>
                      </div>
                    )}

                    <div style={s.detailRow}>
                      <span style={s.label}>Registros</span>
                      <span style={{ ...s.mono, fontSize: 12, color: T.text.primary }}>
                        {formatNumber(confidence.record_count)}
                      </span>
                    </div>

                    <div style={s.detailRow}>
                      <span style={s.label}>Tasa NULL</span>
                      <span style={{
                        ...s.mono,
                        fontSize: 12,
                        color: confidence.null_rate > 0.2 ? T.accent.yellow : T.text.primary,
                      }}>
                        {(confidence.null_rate * 100).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* ── Query SQL ── */}
              {confidence.sql_query && (
                <div>
                  <h4 style={s.sectionHeader}>
                    <Code size={12} />
                    Query SQL
                  </h4>

                  <div style={{ position: 'relative' }}>
                    <pre
                      style={{
                        fontFamily: T.font.mono,
                        fontSize: 12,
                        color: T.text.secondary,
                        background: T.bg.elevated,
                        borderRadius: T.radius.sm,
                        padding: T.space.md,
                        margin: 0,
                        overflow: 'auto',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        maxHeight: 300,
                        lineHeight: 1.5,
                      }}
                    >
                      {confidence.sql_query}
                    </pre>

                    <button
                      onClick={(e) => { e.stopPropagation(); handleCopy() }}
                      style={{
                        ...s.mono,
                        position: 'absolute',
                        top: T.space.sm,
                        right: T.space.sm,
                        fontSize: 11,
                        color: copied ? T.accent.teal : T.text.tertiary,
                        background: T.bg.card,
                        border: T.border.subtle,
                        borderRadius: T.radius.sm,
                        padding: `${T.space.xs} ${T.space.sm}`,
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: T.space.xs,
                        transition: 'color 0.15s',
                      }}
                    >
                      {copied ? <Check size={12} /> : <Copy size={12} />}
                      {copied ? 'Copiado' : 'Copiar'}
                    </button>
                  </div>
                </div>
              )}

              {/* ── Verificacion ── */}
              <div>
                <h4 style={s.sectionHeader}>
                  <Shield size={12} />
                  Verificaci&oacute;n
                </h4>

                <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.xs }}>
                  <div style={s.detailRow}>
                    <span style={s.label}>M&eacute;todo</span>
                    <span style={{
                      ...s.display,
                      fontSize: 13,
                      color: confidence.verification_method === 'interpolation'
                        ? T.accent.yellow
                        : T.accent.teal,
                    }}>
                      {VERIFICATION_LABEL[confidence.verification_method]}
                    </span>
                  </div>

                  <div style={s.detailRow}>
                    <span style={s.label}>DQ Score</span>
                    <span style={{
                      ...s.mono,
                      fontSize: 13,
                      fontWeight: 700,
                      color: dqScoreColor(confidence.dq_score),
                    }}>
                      {confidence.dq_score.toFixed(1)}/10
                    </span>
                  </div>

                  {confidence.degradation_applied && confidence.degradation_reason && (
                    <div style={{
                      marginTop: T.space.xs,
                      padding: T.space.sm,
                      background: T.accent.yellow + '15',
                      border: `1px solid ${T.accent.yellow}30`,
                      borderRadius: T.radius.sm,
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: T.space.sm,
                    }}>
                      <span style={{ fontSize: 14, flexShrink: 0 }}>&#9888;</span>
                      <span style={{ ...s.display, fontSize: 12, color: T.accent.yellow, lineHeight: 1.5 }}>
                        <strong>Degradaci&oacute;n aplicada:</strong> {confidence.degradation_reason}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
