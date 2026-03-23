'use client'

/**
 * ColumnMapper.tsx
 * Maps uploaded file columns to domain entities with auto-detection and manual override.
 */

import { useState, useEffect, useCallback } from 'react'
import { T } from '@/components/d4c/tokens'

// ── Types ─────────────────────────────────────────────────────────────────────

export type EntityOption =
  | 'date'
  | 'amount'
  | 'customer'
  | 'product'
  | 'invoice'
  | 'payment'
  | 'ignore'
  | 'other'

interface ColumnInfo {
  name: string
  dtype: string
  sample?: string
}

export interface ColumnMapperProps {
  columns: ColumnInfo[]
  onMappingChange: (mapping: Record<string, string>) => void
}

interface ColumnState {
  entity: EntityOption
  ignored: boolean
  confidence: 'high' | 'low' | 'none'
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ENTITY_OPTIONS: { value: EntityOption; label: string }[] = [
  { value: 'date',     label: 'Fecha' },
  { value: 'amount',   label: 'Monto' },
  { value: 'customer', label: 'Cliente' },
  { value: 'product',  label: 'Producto' },
  { value: 'invoice',  label: 'Factura' },
  { value: 'payment',  label: 'Pago' },
  { value: 'ignore',   label: 'Ignorar' },
  { value: 'other',    label: 'Otro' },
]

/** Pattern rules for auto-detection. Order matters — first match wins. */
const DETECTION_RULES: Array<{ patterns: RegExp[]; entity: EntityOption }> = [
  {
    patterns: [/fecha/i, /date/i, /invoice_date/i, /created_at/i, /updated_at/i, /\bfch\b/i],
    entity: 'date',
  },
  {
    patterns: [/\bmonto\b/i, /\bamount\b/i, /\btotal\b/i, /\bsubtotal\b/i, /\bprice\b/i, /\bimporte\b/i, /\bvalor\b/i],
    entity: 'amount',
  },
  {
    patterns: [/cliente/i, /customer/i, /\bclient\b/i, /partner/i, /\bcliente_id\b/i, /\bcust\b/i],
    entity: 'customer',
  },
  {
    patterns: [/producto/i, /product/i, /\bitem\b/i, /\bsku\b/i, /\bpart\b/i, /articulo/i],
    entity: 'product',
  },
  {
    patterns: [/factura/i, /invoice/i, /\bbill\b/i, /receipt/i, /\bfact\b/i, /\binv\b/i],
    entity: 'invoice',
  },
  {
    patterns: [/\bpago\b/i, /payment/i, /\bpaid\b/i, /cobro/i, /\bpay\b/i],
    entity: 'payment',
  },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function detectEntity(name: string): { entity: EntityOption; confidence: 'high' | 'low' | 'none' } {
  const lower = name.toLowerCase()

  for (const rule of DETECTION_RULES) {
    for (const pattern of rule.patterns) {
      if (pattern.test(lower)) {
        // Exact keyword matches get high confidence, partial/fuzzy get low
        const isExact = rule.patterns.some(p => {
          const src = p.source.replace(/\\b|[/]i$/g, '').toLowerCase()
          return lower === src || lower === src.replace(/\\/g, '')
        })
        return { entity: rule.entity, confidence: isExact ? 'high' : 'low' }
      }
    }
  }

  return { entity: 'other', confidence: 'none' }
}

function initColumnStates(columns: ColumnInfo[]): Record<string, ColumnState> {
  const states: Record<string, ColumnState> = {}
  for (const col of columns) {
    const { entity, confidence } = detectEntity(col.name)
    states[col.name] = { entity, ignored: entity === 'ignore', confidence }
  }
  return states
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ConfidenceBadge({ confidence }: { confidence: 'high' | 'low' | 'none' }) {
  const CONFIG = {
    high: { label: 'Auto', color: T.accent.teal,   bg: `${T.accent.teal}18` },
    low:  { label: 'Bajo', color: T.accent.yellow, bg: `${T.accent.yellow}18` },
    none: { label: '—',    color: T.text.tertiary,  bg: T.bg.elevated },
  }
  const { label, color, bg } = CONFIG[confidence]

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '2px 7px',
      borderRadius: '100px',
      fontSize: 10,
      fontWeight: 600,
      color,
      backgroundColor: bg,
      fontFamily: T.font.display,
      whiteSpace: 'nowrap',
      letterSpacing: '0.03em',
    }}>
      {label}
    </span>
  )
}

function DtypeBadge({ dtype }: { dtype: string }) {
  const color = dtype.startsWith('float') || dtype.startsWith('int')
    ? T.accent.blue
    : dtype === 'datetime64[ns]' || dtype.includes('date')
      ? T.accent.purple
      : T.text.tertiary

  return (
    <span style={{
      fontSize: 10,
      fontFamily: T.font.mono,
      color,
      backgroundColor: `${color}18`,
      padding: '1px 6px',
      borderRadius: 4,
      whiteSpace: 'nowrap',
    }}>
      {dtype}
    </span>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ColumnMapper({ columns, onMappingChange }: ColumnMapperProps) {
  const [states, setStates] = useState<Record<string, ColumnState>>(() => initColumnStates(columns))

  // Re-init when columns list changes (different sheet selected)
  useEffect(() => {
    setStates(initColumnStates(columns))
  }, [columns])

  // Notify parent whenever mapping changes
  useEffect(() => {
    const mapping: Record<string, string> = {}
    for (const [colName, state] of Object.entries(states)) {
      if (!state.ignored) {
        mapping[colName] = state.entity
      }
    }
    onMappingChange(mapping)
  }, [states, onMappingChange])

  const handleEntityChange = useCallback((colName: string, entity: EntityOption) => {
    setStates(prev => ({
      ...prev,
      [colName]: {
        ...prev[colName],
        entity,
        ignored: entity === 'ignore',
        confidence: prev[colName].confidence,
      },
    }))
  }, [])

  const handleIgnoreToggle = useCallback((colName: string) => {
    setStates(prev => {
      const current = prev[colName]
      return {
        ...prev,
        [colName]: {
          ...current,
          ignored: !current.ignored,
          entity: !current.ignored ? 'ignore' : detectEntity(colName).entity,
        },
      }
    })
  }, [])

  if (columns.length === 0) return null

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 0,
      backgroundColor: T.bg.card,
      border: T.border.card,
      borderRadius: T.radius.md,
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 100px 120px 100px 48px',
        gap: T.space.sm,
        padding: `${T.space.sm} ${T.space.md}`,
        borderBottom: `1px solid ${T.bg.hover}`,
        backgroundColor: T.bg.elevated,
      }}>
        {['Columna', 'Tipo', 'Mapear como', 'Confianza', 'Ignorar'].map((h) => (
          <span key={h} style={{
            fontSize: 11,
            fontWeight: 600,
            color: T.text.tertiary,
            fontFamily: T.font.display,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}>
            {h}
          </span>
        ))}
      </div>

      {/* Rows */}
      {columns.map((col, idx) => {
        const state = states[col.name] ?? { entity: 'other', ignored: false, confidence: 'none' }
        const isIgnored = state.ignored
        const isAlternate = idx % 2 === 1

        return (
          <div
            key={col.name}
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 100px 120px 100px 48px',
              gap: T.space.sm,
              alignItems: 'center',
              padding: `${T.space.sm} ${T.space.md}`,
              backgroundColor: isAlternate ? T.bg.elevated : T.bg.card,
              borderBottom: idx < columns.length - 1 ? `1px solid ${T.bg.hover}40` : 'none',
              opacity: isIgnored ? 0.45 : 1,
              transition: 'opacity 0.15s',
            }}
          >
            {/* Column name */}
            <div>
              <div style={{
                fontSize: 13,
                fontWeight: 500,
                color: T.text.primary,
                fontFamily: T.font.mono,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}>
                {col.name}
              </div>
              {col.sample && (
                <div style={{
                  fontSize: 11,
                  color: T.text.tertiary,
                  fontFamily: T.font.mono,
                  marginTop: 2,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  ej: {col.sample}
                </div>
              )}
            </div>

            {/* Dtype badge */}
            <div><DtypeBadge dtype={col.dtype} /></div>

            {/* Entity dropdown */}
            <select
              value={state.entity}
              disabled={isIgnored}
              onChange={e => handleEntityChange(col.name, e.target.value as EntityOption)}
              style={{
                backgroundColor: T.bg.elevated,
                border: `1px solid ${T.bg.hover}`,
                borderRadius: T.radius.sm,
                color: isIgnored ? T.text.tertiary : T.text.primary,
                fontSize: 12,
                fontFamily: T.font.display,
                padding: '4px 8px',
                cursor: isIgnored ? 'not-allowed' : 'pointer',
                width: '100%',
                outline: 'none',
              }}
            >
              {ENTITY_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            {/* Confidence badge */}
            <div>
              <ConfidenceBadge confidence={isIgnored ? 'none' : state.confidence} />
            </div>

            {/* Ignore checkbox */}
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <input
                type="checkbox"
                checked={isIgnored}
                onChange={() => handleIgnoreToggle(col.name)}
                title="Ignorar esta columna"
                style={{
                  width: 16,
                  height: 16,
                  cursor: 'pointer',
                  accentColor: T.accent.teal,
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}
