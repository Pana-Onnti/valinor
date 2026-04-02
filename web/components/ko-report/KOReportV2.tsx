'use client'

import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts'
import { type ParsedReport } from '@/lib/reportParser'
import { T, SEV_COLOR, SEV_LABEL, CHART_THEME } from '@/components/d4c/tokens'
import { TrustScoreHeader } from '@/components/findings/TrustScoreHeader'
import type { ConfidenceMetadata } from '@/lib/confidence-types'

// ── Types ─────────────────────────────────────────────────────────────────────

interface KOReportV2Props {
  report: ParsedReport
  dqScore?: number       // 0–1
  companyName?: string
  confidenceMetadata?: ConfidenceMetadata
}

// ── Shared styles ─────────────────────────────────────────────────────────────

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

// ── Sub-components ────────────────────────────────────────────────────────────

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

function HeroNumber({ value, label, severity = 'INFO' }: { value: string; label: string; severity?: string }) {
  const color = SEV_COLOR[severity] ?? T.text.primary
  return (
    <div style={{
      ...s.card,
      borderLeft: `3px solid ${color}`,
      display: 'flex',
      flexDirection: 'column',
      gap: T.space.xs,
    }}>
      <div style={{ ...s.mono, fontSize: 28, fontWeight: 700, color, lineHeight: 1.1 }}>
        {value}
      </div>
      <div style={{ ...s.display, fontSize: 12, color: T.text.secondary, marginTop: 2 }}>
        {label}
      </div>
    </div>
  )
}

function SectionHeader({ num, title, description }: { num: string; title: string; description?: string }) {
  return (
    <div style={{ marginBottom: T.space.lg }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: T.space.md }}>
        <span style={{
          ...s.mono,
          fontSize: 32,
          fontWeight: 700,
          color: T.accent.teal + '50',
          lineHeight: 1,
        }}>
          {num}
        </span>
        <h2 style={{
          ...s.display,
          fontSize: 18,
          fontWeight: 700,
          color: T.text.primary,
          margin: 0,
        }}>
          {title}
        </h2>
      </div>
      {description && (
        <p style={{ ...s.display, fontSize: 13, color: T.text.secondary, margin: `${T.space.xs} 0 0 0` }}>
          {description}
        </p>
      )}
    </div>
  )
}

function D4CTooltip({ active, payload, label }: { active?: boolean; payload?: { color: string; name: string; value: number | string }[]; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: CHART_THEME.tooltip.bg,
      border: `1px solid ${CHART_THEME.tooltip.border}`,
      borderRadius: T.radius.sm,
      padding: '8px 12px',
      fontFamily: T.font.mono,
      fontSize: 12,
    }}>
      {label && <div style={{ color: T.text.secondary, marginBottom: 4 }}>{label}</div>}
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toLocaleString('es-AR') : p.value}
        </div>
      ))}
    </div>
  )
}

// ── FindingCard ───────────────────────────────────────────────────────────────

function FindingCard({ finding }: { finding: ParsedReport['findings'][number] }) {
  const [expanded, setExpanded] = useState(false)
  const color = SEV_COLOR[finding.severity] ?? T.accent.blue

  return (
    <div style={{
      ...s.card,
      borderLeft: `3px solid ${color}`,
      cursor: 'pointer',
      transition: 'background 0.15s',
    }}
      onClick={() => setExpanded(e => !e)}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: T.space.sm, justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: T.space.sm, flex: 1 }}>
          <StatusBadge severity={finding.severity} />
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
          {expanded ? '▴' : '▾'}
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
    </div>
  )
}

// ── Main Component ────────────────────────────────────────────────────────────

export function KOReportV2({ report, dqScore, companyName, confidenceMetadata }: KOReportV2Props) {
  const name = companyName ?? report.clientName
  const critical = report.findings.filter(f => f.severity === 'CRITICAL')
  const high = report.findings.filter(f => f.severity === 'HIGH')
  const warnings = report.findings.filter(f => ['MEDIUM', 'LOW', 'INFO'].includes(f.severity))

  // Hero numbers: KPIs más relevantes (primeros 4)
  const heroKPIs = report.kpis.slice(0, 4)

  // Chart data desde KPIs numéricos
  const chartData = report.kpis
    .map(k => {
      const match = k.value.match(/[\d.,]+/)
      const num = match ? parseFloat(match[0].replace(',', '')) : null
      return num !== null ? { name: k.label.substring(0, 20), value: num } : null
    })
    .filter(Boolean)
    .slice(0, 6) as { name: string; value: number }[]

  const today = new Date().toLocaleDateString('es-AR', { year: 'numeric', month: 'long', day: 'numeric' })

  return (
    <div style={{
      background: T.bg.primary,
      minHeight: '100vh',
      fontFamily: T.font.display,
      color: T.text.primary,
    }}>
      {/* Print styles */}
      <style>{`
        @media print {
          body { background: white; color: #111; }
          .no-print { display: none !important; }
        }
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');
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
            Intelligence Report
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
          <div style={{ display: 'flex', gap: T.space.sm }}>
            {critical.length > 0 && (
              <span style={{ ...s.mono, fontSize: 10, color: T.accent.red }}>
                {critical.length} crítico{critical.length > 1 ? 's' : ''}
              </span>
            )}
            {high.length > 0 && (
              <span style={{ ...s.mono, fontSize: 10, color: T.accent.orange }}>
                {high.length} alto{high.length > 1 ? 's' : ''}
              </span>
            )}
            {warnings.length > 0 && (
              <span style={{ ...s.mono, fontSize: 10, color: T.accent.yellow }}>
                {warnings.length} avisos
              </span>
            )}
          </div>
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

      {/* ── Trust Score ── */}
      {confidenceMetadata?.trust_score && (
        <TrustScoreHeader trustScore={confidenceMetadata.trust_score} />
      )}

      {/* ── Body ── */}
      <main style={{ maxWidth: 960, margin: '0 auto', padding: `${T.space.xxl} ${T.space.xl}` }}>

        {/* ── 01 Executive Summary ── */}
        <section style={{ marginBottom: T.space.xxl }}>
          <SectionHeader
            num="01"
            title="Resumen Ejecutivo"
            description={`${name} · ${report.analysisDate || today}`}
          />

          {/* Headline con loss framing */}
          {critical.length > 0 && (
            <div style={{
              ...s.card,
              background: T.accent.red + '10',
              borderColor: T.accent.red + '40',
              borderLeft: `3px solid ${T.accent.red}`,
              marginBottom: T.space.lg,
            }}>
              <div style={{ ...s.display, fontSize: 20, fontWeight: 700, color: T.text.primary, lineHeight: 1.3 }}>
                {name} tiene {critical.length} problema{critical.length > 1 ? 's' : ''} crítico{critical.length > 1 ? 's' : ''} que requieren acción inmediata.
              </div>
              {report.caveat && (
                <div style={{ ...s.mono, fontSize: 11, color: T.text.tertiary, marginTop: T.space.sm }}>
                  ⚠ {report.caveat}
                </div>
              )}
            </div>
          )}

          {/* Hero KPIs grid */}
          {heroKPIs.length > 0 && (
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: T.space.md,
              marginBottom: T.space.lg,
            }}>
              {heroKPIs.map((kpi, i) => (
                <HeroNumber
                  key={i}
                  value={kpi.value}
                  label={kpi.label}
                  severity={kpi.confidence === 'MEASURED' ? 'OK' : 'INFO'}
                />
              ))}
            </div>
          )}
        </section>

        {/* ── 02 Hallazgos ── */}
        <section style={{ marginBottom: T.space.xxl }}>
          <SectionHeader
            num="02"
            title="Hallazgos"
            description={`${report.findings.length} hallazgos ordenados por severidad`}
          />
          <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
            {report.findings.map((f, i) => (
              <FindingCard key={i} finding={f} />
            ))}
            {report.findings.length === 0 && (
              <div style={{ ...s.display, fontSize: 13, color: T.text.tertiary }}>
                Sin hallazgos registrados.
              </div>
            )}
          </div>
        </section>

        {/* ── 03 Métricas ── */}
        {chartData.length > 0 && (
          <section style={{ marginBottom: T.space.xxl }}>
            <SectionHeader num="03" title="Métricas" />
            <div style={{ ...s.card }}>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} barSize={28}>
                  <XAxis
                    dataKey="name"
                    tick={{ fill: T.text.tertiary, fontSize: 11, fontFamily: T.font.mono }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: T.text.tertiary, fontSize: 11, fontFamily: T.font.mono }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={v => v.toLocaleString('es-AR')}
                  />
                  <Tooltip content={<D4CTooltip />} />
                  <Bar dataKey="value" fill={T.accent.teal} radius={[4, 4, 0, 0]} name="Valor" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        {/* ── 04 Plan de acción ── */}
        {report.actions.length > 0 && (
          <section style={{ marginBottom: T.space.xxl }}>
            <SectionHeader num="04" title="Plan de Acción" />
            <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
              {report.actions.map((a, i) => (
                <div key={i} style={{
                  ...s.card,
                  borderLeft: `3px solid ${T.accent.teal}`,
                  display: 'flex',
                  gap: T.space.md,
                  alignItems: 'flex-start',
                }}>
                  <span style={{ ...s.mono, fontSize: 16, fontWeight: 700, color: T.accent.teal + '80', flexShrink: 0 }}>
                    {a.num.padStart(2, '0')}
                  </span>
                  <div style={{ flex: 1 }}>
                    <div style={{ ...s.display, fontSize: 13, fontWeight: 500, color: T.text.primary, marginBottom: 4 }}>
                      {a.action}
                    </div>
                    {(a.owner || a.deadline) && (
                      <div style={{ ...s.mono, fontSize: 11, color: T.text.tertiary }}>
                        {a.owner && `Responsable: ${a.owner}`}
                        {a.owner && a.deadline && ' · '}
                        {a.deadline && `Fecha: ${a.deadline}`}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
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
