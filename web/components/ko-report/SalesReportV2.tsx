'use client'

/**
 * SalesReportV2 — renders the structured JSON emitted by the sales narrator v2.
 *
 * Data source: core/valinor/agents/narrators/sales.py → SalesReportV2 schema.
 * Parse with JSON.parse(reportString) and pass the object as `report`.
 *
 * Refs: VAL-141
 */

import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import { T } from '@/components/d4c/tokens'

// ── Types (mirror of core/valinor/schemas/sales_report_v2.py) ────────────────

type Confidence = 'measured' | 'estimated' | 'inferred'
type RiskLevel = 'low' | 'medium' | 'high'
type HHILevel = 'diversified' | 'moderate' | 'high_risk'
type Trend = 'sube' | 'estable' | 'baja' | 'caida'

export type RFMSegment =
  | 'champions' | 'loyal' | 'potential_loyalists' | 'new_customers'
  | 'promising' | 'need_attention' | 'about_to_sleep' | 'at_risk'
  | 'cannot_lose' | 'hibernating' | 'lost'

interface KPITile {
  label: string; value: string; sub?: string | null
  confidence: Confidence; trend_pct?: number | null
}

interface RFMSegmentSummary {
  segment: RFMSegment; count: number; revenue_share_pct: number
  avg_ltv: number; recommended_action: string; confidence: Confidence
}

interface ConcentrationReport {
  hhi: number; hhi_level: HHILevel
  cr1_pct: number; cr5_pct: number; cr10_pct: number
  total_customers: number; interpretation: string; confidence: Confidence
}

interface TopCustomerRow {
  customer_name: string; customer_id?: string | null
  ltv_eur: number; share_pct: number; last_purchase: string
  risk: RiskLevel; confidence: Confidence
}

interface MagicMatrixCell {
  segment: RFMSegment; category: string
  penetration_pct: number; gap_opportunity_eur: number; confidence: Confidence
}

interface CallListEntry {
  rank: number; customer_name: string; customer_id?: string | null
  deal_risk_score: number; last_purchase: string; ltv_eur: number
  recovery_potential_eur: number; recovery_confidence: Confidence
  reason: string; script_hint: string
}

interface CategoryPerformance {
  category: string; revenue_eur: number; share_pct: number
  mom_pct: number | null
  trend: Trend | null
  confidence: Confidence
}

interface NextAction {
  priority: number; title: string; rationale: string
  impact_eur: number; impact_confidence: Confidence; deadline: string
}

type CustomerProfile = 'cuenta_top' | 'account_grande' | 'cuenta_media' | 'outlier'

export interface SalesReportV2Data {
  client_name: string; period: string; currency: string
  generated_at: string
  hero_loss_eur: number
  hero_loss_headline: string
  kpi_bar: KPITile[]
  rfm_segments: RFMSegmentSummary[]
  concentration: ConcentrationReport
  top_customers: TopCustomerRow[]
  category_performance: CategoryPerformance[]
  magic_matrix: MagicMatrixCell[]
  call_list: (CallListEntry & { profile?: CustomerProfile; frequency?: number })[]
  next_actions: NextAction[]
  executive_summary: string
  data_caveats: string[]
}

// ── Segment + risk styling ────────────────────────────────────────────────────

const SEGMENT_LABEL: Record<RFMSegment, string> = {
  champions: 'Champions', loyal: 'Loyal',
  potential_loyalists: 'Potential Loyalists', new_customers: 'New Customers',
  promising: 'Promising', need_attention: 'Need Attention',
  about_to_sleep: 'About to Sleep', at_risk: 'At Risk',
  cannot_lose: 'Cannot Lose', hibernating: 'Hibernating', lost: 'Lost',
}

const SEGMENT_COLOR: Record<RFMSegment, string> = {
  champions: T.accent.teal, loyal: T.accent.blue,
  potential_loyalists: T.accent.purple, new_customers: T.accent.teal,
  promising: T.accent.blue, need_attention: T.accent.yellow,
  about_to_sleep: T.accent.orange, at_risk: T.accent.red,
  cannot_lose: T.accent.red, hibernating: T.accent.orange, lost: T.accent.red,
}

const RISK_COLOR: Record<RiskLevel, string> = {
  low: T.accent.teal, medium: T.accent.yellow, high: T.accent.red,
}

const HHI_LEVEL_LABEL: Record<HHILevel, string> = {
  diversified: 'Diversificada', moderate: 'Concentración moderada',
  high_risk: 'Alta concentración',
}

const HHI_LEVEL_COLOR: Record<HHILevel, string> = {
  diversified: T.accent.teal, moderate: T.accent.yellow, high_risk: T.accent.red,
}

const TREND_COLOR: Record<Trend, string> = {
  sube: T.accent.teal, estable: T.text.tertiary,
  baja: T.accent.yellow, caida: T.accent.red,
}

// ── Shared styles ─────────────────────────────────────────────────────────────

const s = {
  card: {
    background: T.bg.card, border: T.border.card,
    borderRadius: T.radius.md, padding: T.space.lg,
  },
  mono: { fontFamily: T.font.mono },
  display: { fontFamily: T.font.display },
} as const

// ── Confidence badge ─────────────────────────────────────────────────────────

function ConfMarker({ level }: { level: Confidence }) {
  const label = { measured: '[MEDIDO]', estimated: '[ESTIMADO]', inferred: '[INFERIDO]' }[level]
  const color = { measured: T.accent.teal, estimated: T.accent.yellow, inferred: T.accent.blue }[level]
  return (
    <span style={{
      ...s.mono, fontSize: 9, color, letterSpacing: '0.08em',
    }}>{label}</span>
  )
}

// ── Sections ──────────────────────────────────────────────────────────────────

function KPIBar({ tiles }: { tiles: KPITile[] }) {
  if (!tiles.length) return null
  return (
    <div style={{
      display: 'grid', gap: T.space.sm,
      gridTemplateColumns: `repeat(${Math.min(tiles.length, 5)}, 1fr)`,
      marginBottom: T.space.lg,
    }}>
      {tiles.map((t, i) => (
        <div key={i} style={{ ...s.card, padding: T.space.md, textAlign: 'center' as const }}>
          <div style={{ ...s.mono, fontSize: 24, color: T.text.primary, fontWeight: 300 }}>
            {t.value}
          </div>
          <div style={{ ...s.mono, fontSize: 9, color: T.text.tertiary, marginTop: 4, letterSpacing: '0.08em' }}>
            {t.label.toUpperCase()}
          </div>
          {t.sub && (
            <div style={{ fontSize: 10, color: T.text.secondary, marginTop: 4 }}>{t.sub}</div>
          )}
          <div style={{ marginTop: 6 }}><ConfMarker level={t.confidence} /></div>
        </div>
      ))}
    </div>
  )
}

function RFMGrid({ segments }: { segments: RFMSegmentSummary[] }) {
  if (!segments.length) return null
  return (
    <div style={{ ...s.card, marginBottom: T.space.lg }}>
      <SectionTitle label="Segmentación RFM" sub="Recency · Frequency · Monetary — 11 segmentos estándar B2B" />
      <div style={{
        display: 'grid', gap: T.space.sm,
        gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
      }}>
        {segments.map((seg) => {
          const color = SEGMENT_COLOR[seg.segment]
          return (
            <div key={seg.segment} style={{
              background: T.bg.elevated, border: T.border.subtle,
              borderLeft: `3px solid ${color}`, borderRadius: T.radius.sm,
              padding: T.space.md,
            }}>
              <div style={{ ...s.mono, fontSize: 11, color, fontWeight: 600 }}>
                {SEGMENT_LABEL[seg.segment]}
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 4 }}>
                <span style={{ ...s.mono, fontSize: 18, color: T.text.primary }}>{seg.count}</span>
                <span style={{ fontSize: 10, color: T.text.tertiary }}>clientes</span>
              </div>
              <div style={{ fontSize: 11, color: T.text.secondary, marginTop: 2 }}>
                {seg.revenue_share_pct.toFixed(1)}% revenue · LTV ø €{Math.round(seg.avg_ltv).toLocaleString('es-AR')}
              </div>
              <div style={{ fontSize: 11, color: T.text.secondary, marginTop: 8, lineHeight: 1.4 }}>
                {seg.recommended_action}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ConcentrationPanel({ c }: { c: ConcentrationReport }) {
  const levelColor = HHI_LEVEL_COLOR[c.hhi_level]
  const crData = [
    { k: 'CR1',  v: c.cr1_pct },
    { k: 'CR5',  v: c.cr5_pct },
    { k: 'CR10', v: c.cr10_pct },
  ]
  return (
    <div style={{
      ...s.card, display: 'grid', gap: T.space.lg,
      gridTemplateColumns: '1fr 1fr', marginBottom: T.space.lg,
    }}>
      <div>
        <SectionTitle label="Índice Herfindahl-Hirschman (HHI)" sub={c.interpretation} />
        <div style={{ display: 'flex', alignItems: 'baseline', gap: T.space.md }}>
          <span style={{ ...s.mono, fontSize: 42, fontWeight: 300, color: levelColor }}>
            {c.hhi.toFixed(0)}
          </span>
          <span style={{ ...s.mono, fontSize: 11, color: levelColor, letterSpacing: '0.08em' }}>
            {HHI_LEVEL_LABEL[c.hhi_level]}
          </span>
        </div>
        <div style={{ fontSize: 10, color: T.text.tertiary, marginTop: 4 }}>
          Escala: 0 (diversificada) — 10.000 (monopolio). Umbrales DOJ: &lt;1.500 competitiva, 1.500-2.500 moderada, &gt;2.500 alta.
        </div>
        <div style={{ marginTop: 8 }}><ConfMarker level={c.confidence} /></div>
      </div>
      <div>
        <SectionTitle label="Concentration Ratios" sub="% del revenue en Top N clientes" />
        <ResponsiveContainer width="100%" height={140}>
          <BarChart data={crData} barSize={40}>
            <XAxis dataKey="k" tick={{ fill: T.text.tertiary, fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: T.text.tertiary, fontSize: 10 }} axisLine={false} tickLine={false} />
            <Tooltip cursor={{ fill: 'transparent' }} contentStyle={{
              background: T.bg.elevated, border: T.border.subtle, borderRadius: 6, fontSize: 11,
            }} />
            <Bar dataKey="v" radius={[4, 4, 0, 0]}>
              {crData.map((_, i) => (
                <Cell key={i} fill={[T.accent.teal, T.accent.yellow, T.accent.orange][i]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function TopCustomersTable({ rows }: { rows: TopCustomerRow[] }) {
  if (!rows.length) return null
  const maxShare = Math.max(...rows.map((r) => r.share_pct), 1)
  return (
    <div style={{ ...s.card, marginBottom: T.space.lg }}>
      <SectionTitle label="Top clientes — concentración de cartera" sub="LTV acumulado en el período analizado" />
      {rows.map((r, i) => (
        <div key={i} style={{
          display: 'grid', alignItems: 'center', gap: T.space.sm,
          gridTemplateColumns: '1.6fr 3fr 90px 60px 100px 70px',
          padding: '10px 0',
          borderBottom: i < rows.length - 1 ? T.border.subtle : undefined,
        }}>
          <div style={{ ...s.mono, fontSize: 11, color: T.text.secondary }}>
            {r.customer_name}
            {r.customer_id && <span style={{ color: T.text.tertiary, marginLeft: 4 }}>({r.customer_id})</span>}
          </div>
          <div style={{ height: 5, background: T.bg.elevated, borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              width: `${(r.share_pct / maxShare) * 100}%`, height: '100%',
              background: RISK_COLOR[r.risk],
            }} />
          </div>
          <div style={{ ...s.mono, fontSize: 11, color: T.text.primary, textAlign: 'right' as const }}>
            €{Math.round(r.ltv_eur).toLocaleString('es-AR')}
          </div>
          <div style={{ ...s.mono, fontSize: 11, color: T.text.tertiary, textAlign: 'right' as const }}>
            {r.share_pct.toFixed(1)}%
          </div>
          <div style={{ ...s.mono, fontSize: 10, color: T.text.tertiary }}>{r.last_purchase}</div>
          <span style={{
            ...s.mono, fontSize: 9, letterSpacing: '0.08em',
            color: RISK_COLOR[r.risk],
            background: `${RISK_COLOR[r.risk]}1a`,
            border: `1px solid ${RISK_COLOR[r.risk]}33`,
            padding: '2px 6px', borderRadius: 3, textAlign: 'center' as const,
          }}>{r.risk.toUpperCase()}</span>
        </div>
      ))}
    </div>
  )
}

function CategoryPerformanceList({ rows }: { rows: CategoryPerformance[] }) {
  if (!rows.length) return null
  const hasMoM = rows.some((r) => r.mom_pct !== null && r.mom_pct !== undefined)
  return (
    <div style={{ ...s.card, marginBottom: T.space.lg }}>
      <SectionTitle label="Rendimiento por categoría"
        sub={hasMoM ? "Período actual vs. MoM" : "Revenue y share del período — MoM requiere 2 períodos"} />
      {rows.map((r, i) => {
        const trendColor = r.trend ? TREND_COLOR[r.trend] : T.accent.teal
        return (
          <div key={i} style={{
            display: 'grid', alignItems: 'center', gap: T.space.sm,
            gridTemplateColumns: hasMoM ? '1.2fr 2fr 110px 60px 80px' : '1.2fr 2fr 110px 60px',
            padding: '8px 0',
            borderBottom: i < rows.length - 1 ? T.border.subtle : undefined,
          }}>
            <div style={{ fontSize: 12, color: T.text.primary }}>{r.category}</div>
            <div style={{ height: 5, background: T.bg.elevated, borderRadius: 3, overflow: 'hidden' }}>
              <div style={{
                width: `${Math.min(r.share_pct * 2.5, 100)}%`, height: '100%',
                background: trendColor,
              }} />
            </div>
            <div style={{ ...s.mono, fontSize: 11, color: T.text.secondary, textAlign: 'right' as const }}>
              €{Math.round(r.revenue_eur).toLocaleString('es-AR')}
            </div>
            <div style={{ ...s.mono, fontSize: 11, color: T.text.tertiary, textAlign: 'right' as const }}>
              {r.share_pct.toFixed(1)}%
            </div>
            {hasMoM && (
              <div style={{
                ...s.mono, fontSize: 10,
                color: r.mom_pct !== null ? trendColor : T.text.tertiary,
                textAlign: 'right' as const,
              }}>
                {r.mom_pct === null || r.mom_pct === undefined
                  ? '—'
                  : `${r.mom_pct > 0 ? '+' : ''}${r.mom_pct.toFixed(0)}% MoM`}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function MagicMatrixHeatmap({ cells }: { cells: MagicMatrixCell[] }) {
  if (!cells.length) return null
  // Build segment × category pivot
  const segments = Array.from(new Set(cells.map((c) => c.segment)))
  const categories = Array.from(new Set(cells.map((c) => c.category)))
  const lookup = new Map<string, MagicMatrixCell>()
  for (const c of cells) lookup.set(`${c.segment}::${c.category}`, c)

  return (
    <div style={{ ...s.card, marginBottom: T.space.lg, overflowX: 'auto' }}>
      <SectionTitle label="Magic Matrix — cross-sell por segmento × categoría"
        sub="% de penetración. Los gaps marcan oportunidad comercial." />
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 11 }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left' as const, padding: '6px 8px', color: T.text.tertiary, ...s.mono, fontSize: 10 }}></th>
            {categories.map((cat) => (
              <th key={cat} style={{
                ...s.mono, fontSize: 10, padding: '6px 8px',
                color: T.text.tertiary, textAlign: 'center' as const,
              }}>{cat}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {segments.map((seg) => (
            <tr key={seg}>
              <td style={{
                ...s.mono, fontSize: 10, padding: '6px 8px',
                color: SEGMENT_COLOR[seg as RFMSegment], fontWeight: 600,
              }}>
                {SEGMENT_LABEL[seg as RFMSegment]}
              </td>
              {categories.map((cat) => {
                const cell = lookup.get(`${seg}::${cat}`)
                const pct = cell?.penetration_pct ?? 0
                const bg = `${SEGMENT_COLOR[seg as RFMSegment]}${Math.round(pct / 100 * 200).toString(16).padStart(2, '0')}`
                return (
                  <td key={cat} title={cell ? `${pct.toFixed(0)}% · oportunidad €${Math.round(cell.gap_opportunity_eur).toLocaleString('es-AR')}` : ''}
                    style={{
                      padding: '8px 10px', textAlign: 'center' as const,
                      background: bg, color: pct > 40 ? T.text.primary : T.text.tertiary,
                      ...s.mono, fontSize: 10,
                    }}>
                    {pct > 0 ? `${pct.toFixed(0)}%` : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const PROFILE_LABEL: Record<CustomerProfile, string> = {
  cuenta_top: 'CUENTA TOP',
  account_grande: 'CUENTA GRANDE',
  cuenta_media: 'CUENTA MEDIA',
  outlier: 'OUTLIER',
}

const PROFILE_COLOR: Record<CustomerProfile, string> = {
  cuenta_top: T.accent.red,
  account_grande: T.accent.teal,
  cuenta_media: T.accent.blue,
  outlier: T.accent.yellow,
}

function CallList({ rows }: { rows: SalesReportV2Data['call_list'] }) {
  if (!rows.length) return null
  return (
    <div style={{ ...s.card, marginBottom: T.space.lg }}>
      <SectionTitle label="Call list priorizada por Deal Risk Score"
        sub="Script adaptado al perfil (cuenta grande / media / outlier). Sample chica penaliza confianza del potencial." />
      {rows.map((r) => {
        const scoreColor =
          r.deal_risk_score > 70 ? T.accent.red :
          r.deal_risk_score > 40 ? T.accent.yellow : T.accent.teal
        const profile = r.profile ?? 'cuenta_media'
        const profileColor = PROFILE_COLOR[profile]
        return (
          <div key={r.rank} style={{
            display: 'grid', gap: T.space.sm,
            gridTemplateColumns: '36px 1.5fr 2fr 80px 90px',
            padding: `${T.space.sm} 0`,
            borderBottom: T.border.subtle, alignItems: 'flex-start',
          }}>
            <div style={{
              ...s.mono, fontSize: 12, color: scoreColor, fontWeight: 600,
              textAlign: 'center' as const,
            }}>#{r.rank}</div>
            <div>
              <div style={{ fontSize: 12, color: T.text.primary, fontWeight: 500 }}>
                {r.customer_name}
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 3 }}>
                <span style={{
                  ...s.mono, fontSize: 9, color: profileColor,
                  background: `${profileColor}1a`, border: `1px solid ${profileColor}33`,
                  padding: '1px 6px', borderRadius: 3, letterSpacing: '0.08em',
                }}>{PROFILE_LABEL[profile]}</span>
                <span style={{ ...s.mono, fontSize: 10, color: T.text.tertiary }}>
                  {r.frequency ?? 0} pedidos
                </span>
              </div>
              <div style={{ fontSize: 11, color: T.text.secondary, marginTop: 6 }}>{r.reason}</div>
              <div style={{ fontSize: 11, color: T.text.tertiary, marginTop: 4, fontStyle: 'italic' as const, lineHeight: 1.5 }}>
                "{r.script_hint}"
              </div>
            </div>
            <div style={{ fontSize: 11, color: T.text.secondary }}>
              <div>Última: <span style={{ ...s.mono }}>{r.last_purchase}</span></div>
              <div>LTV: <span style={{ ...s.mono }}>€{Math.round(r.ltv_eur).toLocaleString('es-AR')}</span></div>
              <div style={{ color: T.accent.teal }}>
                Potencial: €{Math.round(r.recovery_potential_eur).toLocaleString('es-AR')}{' '}
                <ConfMarker level={r.recovery_confidence} />
              </div>
            </div>
            <div style={{ ...s.mono, textAlign: 'right' as const }}>
              <div style={{ fontSize: 18, color: scoreColor, fontWeight: 300 }}>
                {r.deal_risk_score.toFixed(1)}
              </div>
              <div style={{ fontSize: 9, color: T.text.tertiary, letterSpacing: '0.08em' }}>RISK SCORE</div>
            </div>
            <div />
          </div>
        )
      })}
    </div>
  )
}

function NextActionsBlock({ actions, heroLossEur }: { actions: NextAction[]; heroLossEur: number }) {
  if (!actions.length) return null
  return (
    <div style={{
      ...s.card,
      background: `linear-gradient(180deg, ${T.accent.red}08 0%, ${T.bg.card} 100%)`,
      borderLeft: `4px solid ${T.accent.red}`,
      marginBottom: T.space.lg,
    }}>
      <div style={{
        ...s.mono, fontSize: 11, color: T.accent.red,
        letterSpacing: '0.18em', textTransform: 'uppercase' as const, marginBottom: T.space.sm,
      }}>Esta semana tenés que:</div>
      {actions.map((a) => (
        <div key={a.priority} style={{
          display: 'grid', gap: T.space.md, alignItems: 'flex-start',
          gridTemplateColumns: '28px 1fr 140px',
          padding: `${T.space.md} 0`,
          borderBottom: a.priority < actions.length ? T.border.subtle : undefined,
        }}>
          <div style={{
            ...s.mono, fontSize: 20, color: T.accent.red, fontWeight: 300,
            textAlign: 'center' as const, lineHeight: 1,
          }}>{a.priority}</div>
          <div>
            <div style={{ fontSize: 14, color: T.text.primary, fontWeight: 500, marginBottom: 4 }}>
              {a.title}
            </div>
            <div style={{ fontSize: 12, color: T.text.secondary, lineHeight: 1.5 }}>{a.rationale}</div>
            <div style={{
              ...s.mono, fontSize: 10, color: T.text.tertiary, marginTop: 6,
              letterSpacing: '0.08em',
            }}>
              DEADLINE: {a.deadline.toUpperCase()}
            </div>
          </div>
          <div style={{ textAlign: 'right' as const }}>
            <div style={{ ...s.mono, fontSize: 16, color: T.accent.red, fontWeight: 300 }}>
              €{Math.round(a.impact_eur).toLocaleString('es-AR')}
            </div>
            <div style={{ ...s.mono, fontSize: 9, color: T.text.tertiary, marginTop: 2 }}>
              IMPACTO €
            </div>
            <div style={{ marginTop: 4 }}><ConfMarker level={a.impact_confidence} /></div>
          </div>
        </div>
      ))}
    </div>
  )
}

function SectionTitle({ label, sub }: { label: string; sub?: string }) {
  return (
    <div style={{ marginBottom: T.space.md }}>
      <div style={{
        ...s.mono, fontSize: 10, color: T.accent.teal,
        letterSpacing: '0.18em', textTransform: 'uppercase' as const,
      }}>{label}</div>
      {sub && <div style={{ fontSize: 12, color: T.text.secondary, marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

// ── Main component ───────────────────────────────────────────────────────────

function HeroLoss({ report }: { report: SalesReportV2Data }) {
  if (!report.hero_loss_eur) return null
  return (
    <div style={{
      padding: `${T.space.xl} ${T.space.lg}`,
      borderLeft: `4px solid ${T.accent.red}`,
      background: `linear-gradient(180deg, ${T.accent.red}10 0%, ${T.bg.card} 100%)`,
      borderRadius: T.radius.md,
      marginBottom: T.space.lg,
    }}>
      <div style={{
        ...s.mono, fontSize: 10, color: T.accent.red, letterSpacing: '0.2em',
        textTransform: 'uppercase' as const, marginBottom: T.space.sm,
      }}>Hallazgo crítico</div>
      <div style={{
        ...s.display, fontSize: 44, color: T.accent.red, fontWeight: 300,
        lineHeight: 1, letterSpacing: '-0.02em',
      }}>
        €{Math.round(report.hero_loss_eur).toLocaleString('es-AR')}
      </div>
      <div style={{
        ...s.display, fontSize: 16, color: T.text.primary, lineHeight: 1.5,
        marginTop: T.space.sm, maxWidth: 720,
      }}>
        {report.hero_loss_headline}
      </div>
    </div>
  )
}

export default function SalesReportV2({ report }: { report: SalesReportV2Data }) {
  return (
    <div style={{ color: T.text.primary, padding: T.space.lg }}>
      {/* Header */}
      <div style={{ marginBottom: T.space.lg }}>
        <div style={{
          ...s.mono, fontSize: 10, color: T.text.tertiary, letterSpacing: '0.18em',
          textTransform: 'uppercase' as const,
        }}>
          Reporte de Ventas — {report.client_name}
        </div>
        <div style={{ ...s.display, fontSize: 22, color: T.text.primary, marginTop: T.space.xs }}>
          Diagnóstico comercial · <span style={{ color: T.accent.teal }}>{report.period}</span>
        </div>
        <div style={{ fontSize: 12, color: T.text.secondary, marginTop: T.space.sm, lineHeight: 1.6 }}>
          {report.executive_summary}
        </div>
      </div>

      {/* Loss-framed hero — first element the CEO sees */}
      <HeroLoss report={report} />

      {/* Decision-forcing actions near the top — provocación directa */}
      <NextActionsBlock actions={report.next_actions} heroLossEur={report.hero_loss_eur} />

      <KPIBar tiles={report.kpi_bar} />
      <ConcentrationPanel c={report.concentration} />
      <CallList rows={report.call_list} />
      <TopCustomersTable rows={report.top_customers} />
      <RFMGrid segments={report.rfm_segments} />
      <CategoryPerformanceList rows={report.category_performance} />
      <MagicMatrixHeatmap cells={report.magic_matrix} />

      {!!report.data_caveats.length && (
        <div style={{
          ...s.card, background: `${T.accent.yellow}10`, border: `1px solid ${T.accent.yellow}33`,
        }}>
          <div style={{ ...s.mono, fontSize: 10, color: T.accent.yellow, letterSpacing: '0.18em' }}>
            CAVEATS DE DATOS
          </div>
          <ul style={{ margin: 0, paddingLeft: 18, marginTop: 8 }}>
            {report.data_caveats.map((c, i) => (
              <li key={i} style={{ fontSize: 11, color: T.text.secondary, marginBottom: 4 }}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/**
 * Convenience: parse a JSON-serialized report (as returned by the Python
 * narrator) into SalesReportV2Data. Returns null on parse failure.
 */
export function parseSalesReportV2(raw: string | null | undefined): SalesReportV2Data | null {
  if (!raw) return null
  try {
    const obj = JSON.parse(raw)
    if (!obj || typeof obj !== 'object') return null
    // Minimal runtime validation — full validation happens in the backend
    if (!('concentration' in obj) || !('kpi_bar' in obj)) return null
    // Backfill new fields for older JSON payloads so the renderer stays defensive
    const result = obj as SalesReportV2Data
    if (result.hero_loss_eur === undefined) result.hero_loss_eur = 0
    if (!result.hero_loss_headline) result.hero_loss_headline = ''
    if (!Array.isArray(result.next_actions)) result.next_actions = []
    return result
  } catch {
    return null
  }
}
