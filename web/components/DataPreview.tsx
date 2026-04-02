'use client'

/**
 * DataPreview.tsx
 * Shows first N rows of an uploaded file in a scrollable table,
 * plus metadata panel, sheet selector (Excel), and column mapper.
 */

import { useState, useEffect, useCallback } from 'react'
import { T } from '@/components/d4c/tokens'
import { getPreview, getSchema } from '@/lib/api'
import type { PreviewData, SchemaData } from '@/lib/types'
import SheetSelector from './SheetSelector'
import ColumnMapper from './ColumnMapper'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface DataPreviewProps {
  uploadId: string
  /** Available sheets (from UploadResult.sheets). Pass [] for CSV. */
  sheets?: string[]
  onConfirm: (mapping: Record<string, string>) => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Compute null percentage for a column across visible rows. */
function nullPct(rows: Record<string, unknown>[], col: string): number {
  if (rows.length === 0) return 0
  const nullCount = rows.filter(r => r[col] == null || r[col] === '').length
  return Math.round((nullCount / rows.length) * 100)
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SkeletonRows({ cols }: { cols: number }) {
  return (
    <>
      {Array.from({ length: 5 }).map((_, ri) => (
        <tr key={ri}>
          {Array.from({ length: cols }).map((_, ci) => (
            <td key={ci} style={{ padding: '8px 12px' }}>
              <div style={{
                height: 14,
                borderRadius: 4,
                backgroundColor: T.bg.hover,
                width: `${50 + Math.random() * 40}%`,
                animation: 'pulse 1.4s ease-in-out infinite',
              }} />
            </td>
          ))}
        </tr>
      ))}
    </>
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
      fontSize: 9,
      fontFamily: T.font.mono,
      color,
      backgroundColor: `${color}18`,
      padding: '1px 5px',
      borderRadius: 4,
      display: 'block',
      marginTop: 2,
      whiteSpace: 'nowrap',
    }}>
      {dtype}
    </span>
  )
}

function NullBar({ pct }: { pct: number }) {
  if (pct === 0) return null
  const color = pct > 50 ? T.accent.red : pct > 20 ? T.accent.yellow : T.accent.orange
  return (
    <div title={`${pct}% nulos`} style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 3 }}>
      <div style={{
        width: 40,
        height: 3,
        backgroundColor: T.bg.hover,
        borderRadius: 2,
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          backgroundColor: color,
          borderRadius: 2,
        }} />
      </div>
      <span style={{ fontSize: 9, color, fontFamily: T.font.mono }}>{pct}%</span>
    </div>
  )
}

function MetaCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 2,
      padding: `${T.space.sm} ${T.space.md}`,
      backgroundColor: T.bg.elevated,
      borderRadius: T.radius.sm,
      border: T.border.card,
      minWidth: 100,
    }}>
      <span style={{
        fontSize: 10,
        fontWeight: 600,
        color: T.text.tertiary,
        fontFamily: T.font.display,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 18,
        fontWeight: 700,
        color: T.text.primary,
        fontFamily: T.font.mono,
        lineHeight: 1.2,
      }}>
        {value}
      </span>
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function DataPreview({ uploadId, sheets = [], onConfirm }: DataPreviewProps) {
  const [activeSheet, setActiveSheet] = useState<string>(sheets[0] ?? '')
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [schema, setSchema] = useState<SchemaData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [showMapper, setShowMapper] = useState(false)

  // Fetch preview + schema whenever sheet changes
  const fetchData = useCallback(async (sheet?: string) => {
    setLoading(true)
    setError(null)
    try {
      const [previewData, schemaData] = await Promise.all([
        getPreview(uploadId, 50, sheet || undefined),
        getSchema(uploadId),
      ])
      setPreview(previewData)
      setSchema(schemaData)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error al cargar vista previa')
    } finally {
      setLoading(false)
    }
  }, [uploadId])

  useEffect(() => {
    fetchData(activeSheet || undefined)
  }, [fetchData, activeSheet])

  const handleSheetChange = useCallback((sheet: string) => {
    setActiveSheet(sheet)
  }, [])

  const handleConfirm = useCallback(() => {
    onConfirm(mapping)
  }, [mapping, onConfirm])

  // ── Derived data ───────────────────────────────────────────────────────────

  const columns = preview?.columns ?? []
  const rows = preview?.rows ?? []
  const totalRows = preview?.total_rows ?? 0

  const schemaMap: Record<string, string> = {}
  if (schema) {
    for (const col of schema.columns) {
      schemaMap[col.name] = col.dtype
    }
  }

  const mapperColumns = columns.map(name => ({
    name,
    dtype: schemaMap[name] ?? 'object',
    sample: rows[0]?.[name] != null ? String(rows[0][name]) : undefined,
  }))

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: T.space.md,
      backgroundColor: T.bg.card,
      border: T.border.card,
      borderRadius: T.radius.md,
      overflow: 'hidden',
    }}>
      {/* Sheet selector */}
      {sheets.length > 1 && (
        <SheetSelector
          sheets={sheets}
          activeSheet={activeSheet}
          onChange={handleSheetChange}
        />
      )}

      {/* Loading state */}
      {loading && (
        <div style={{ padding: T.space.md }}>
          {/* Metadata skeleton */}
          <div style={{ display: 'flex', gap: T.space.sm, marginBottom: T.space.md, flexWrap: 'wrap' }}>
            {['Filas', 'Columnas'].map(l => (
              <div key={l} style={{
                padding: `${T.space.sm} ${T.space.md}`,
                backgroundColor: T.bg.elevated,
                borderRadius: T.radius.sm,
                border: T.border.card,
                minWidth: 100,
              }}>
                <div style={{ height: 10, width: 40, backgroundColor: T.bg.hover, borderRadius: 3, marginBottom: 6 }} />
                <div style={{ height: 18, width: 60, backgroundColor: T.bg.hover, borderRadius: 3 }} />
              </div>
            ))}
          </div>

          {/* Table skeleton */}
          <div style={{ overflowX: 'auto', borderRadius: T.radius.sm, border: T.border.card }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ backgroundColor: T.bg.elevated }}>
                  {Array.from({ length: 5 }).map((_, i) => (
                    <th key={i} style={{ padding: '8px 12px' }}>
                      <div style={{ height: 12, width: 70, backgroundColor: T.bg.hover, borderRadius: 3 }} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <SkeletonRows cols={5} />
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div style={{
          margin: T.space.md,
          padding: T.space.md,
          borderRadius: T.radius.sm,
          backgroundColor: `${T.accent.red}10`,
          border: `1px solid ${T.accent.red}30`,
          display: 'flex',
          alignItems: 'flex-start',
          gap: T.space.sm,
        }}>
          <span style={{ fontSize: 16, color: T.accent.red, lineHeight: 1.4 }}>⚠</span>
          <div>
            <div style={{
              fontSize: 13,
              fontWeight: 600,
              color: T.accent.red,
              fontFamily: T.font.display,
              marginBottom: 4,
            }}>
              Error al cargar vista previa
            </div>
            <div style={{
              fontSize: 12,
              color: T.text.secondary,
              fontFamily: T.font.display,
            }}>
              {error}
            </div>
            <button
              onClick={() => fetchData(activeSheet || undefined)}
              style={{
                marginTop: T.space.sm,
                padding: '4px 12px',
                borderRadius: T.radius.sm,
                border: `1px solid ${T.accent.red}40`,
                backgroundColor: `${T.accent.red}15`,
                color: T.accent.red,
                fontSize: 12,
                fontFamily: T.font.display,
                cursor: 'pointer',
              }}
            >
              Reintentar
            </button>
          </div>
        </div>
      )}

      {/* Data content */}
      {!loading && !error && preview && (
        <>
          {/* Metadata panel */}
          <div style={{
            display: 'flex',
            gap: T.space.sm,
            padding: `${T.space.md} ${T.space.md} 0`,
            flexWrap: 'wrap',
          }}>
            <MetaCard label="Total filas" value={totalRows.toLocaleString('es')} />
            <MetaCard label="Columnas" value={columns.length} />
            {activeSheet && <MetaCard label="Hoja activa" value={activeSheet} />}
            <MetaCard label="Mostrando" value={`${rows.length} filas`} />
          </div>

          {/* Scrollable data table */}
          <div style={{
            overflowX: 'auto',
            margin: `0 ${T.space.md}`,
            borderRadius: T.radius.sm,
            border: T.border.card,
          }}>
            <table style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 12,
              fontFamily: T.font.mono,
            }}>
              <thead>
                <tr style={{ backgroundColor: T.bg.elevated }}>
                  {columns.map(col => {
                    const pct = nullPct(rows, col)
                    const dtype = schemaMap[col] ?? 'object'
                    return (
                      <th
                        key={col}
                        style={{
                          padding: '8px 12px',
                          textAlign: 'left',
                          borderBottom: `1px solid ${T.bg.hover}`,
                          borderRight: `1px solid ${T.bg.hover}40`,
                          whiteSpace: 'nowrap',
                          verticalAlign: 'top',
                          minWidth: 120,
                        }}
                      >
                        <div style={{
                          fontSize: 12,
                          fontWeight: 600,
                          color: T.text.primary,
                          fontFamily: T.font.display,
                        }}>
                          {col}
                        </div>
                        <DtypeBadge dtype={dtype} />
                        <NullBar pct={pct} />
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr
                    key={ri}
                    style={{
                      backgroundColor: ri % 2 === 0 ? T.bg.card : T.bg.elevated,
                    }}
                  >
                    {columns.map(col => {
                      const val = row[col]
                      const isEmpty = val == null || val === ''
                      return (
                        <td
                          key={col}
                          style={{
                            padding: '7px 12px',
                            borderBottom: `1px solid ${T.bg.hover}30`,
                            borderRight: `1px solid ${T.bg.hover}30`,
                            color: isEmpty ? T.text.tertiary : T.text.secondary,
                            fontStyle: isEmpty ? 'italic' : 'normal',
                            maxWidth: 220,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {isEmpty ? 'null' : String(val)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Column mapper section */}
          <div style={{ padding: `0 ${T.space.md}` }}>
            <button
              onClick={() => setShowMapper(v => !v)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: T.space.xs,
                padding: `${T.space.sm} 0`,
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: T.accent.teal,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: T.font.display,
              }}
            >
              <span style={{
                display: 'inline-block',
                transition: 'transform 0.2s',
                transform: showMapper ? 'rotate(90deg)' : 'rotate(0deg)',
              }}>
                ▶
              </span>
              Mapeo de columnas
              <span style={{
                fontSize: 11,
                fontWeight: 400,
                color: T.text.tertiary,
                marginLeft: 4,
              }}>
                ({Object.keys(mapping).length} columnas activas)
              </span>
            </button>

            {showMapper && (
              <div style={{ marginBottom: T.space.md }}>
                <ColumnMapper
                  columns={mapperColumns}
                  onMappingChange={setMapping}
                />
              </div>
            )}
          </div>

          {/* Confirm button */}
          <div style={{
            padding: `${T.space.md}`,
            borderTop: `1px solid ${T.bg.hover}`,
            display: 'flex',
            justifyContent: 'flex-end',
            gap: T.space.sm,
          }}>
            <button
              onClick={handleConfirm}
              style={{
                padding: '8px 20px',
                borderRadius: T.radius.sm,
                border: `1px solid ${T.accent.teal}60`,
                backgroundColor: `${T.accent.teal}18`,
                color: T.accent.teal,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: T.font.display,
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.backgroundColor = `${T.accent.teal}30`
              }}
              onMouseLeave={e => {
                e.currentTarget.style.backgroundColor = `${T.accent.teal}18`
              }}
            >
              Confirmar datos →
            </button>
          </div>
        </>
      )}

      {/* Pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  )
}
