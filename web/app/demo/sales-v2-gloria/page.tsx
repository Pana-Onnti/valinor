'use client'

/**
 * Dynamic demo — Gloria sales v2 pipeline with period picker + animated stages.
 *
 * Flow:
 *   idle     → period selector + "Run diagnostic" button
 *   loading  → PipelineProgress (full stage list on first run, short list when switching)
 *   ready    → SalesReportV2 with persistent period picker at the top
 *
 * Backing JSONs are pre-generated per period:
 *   scripts/generate_sales_report_v2_gloria.py --batch
 *   → web/public/demo/sales-v2-gloria-{6m,12m,24m}.json
 *
 * Refs: VAL-141, VAL-158
 */

import { useCallback, useEffect, useState } from 'react'
import SalesReportV2, {
  parseSalesReportV2,
  type SalesReportV2Data,
} from '@/components/ko-report/SalesReportV2'
import PipelineProgress, {
  FULL_STAGES,
  SHORT_STAGES,
} from '@/components/ko-report/PipelineProgress'
import { T } from '@/components/d4c/tokens'

type Period = { slug: string; label: string; months: number; hint: string }

const PERIODS: Period[] = [
  { slug: '6m',  label: 'Últimos 6 meses',  months: 6,
    hint: '474 clientes · ventana reciente' },
  { slug: '12m', label: 'Últimos 12 meses', months: 12,
    hint: '2.813 clientes · año completo' },
  { slug: '24m', label: 'Últimos 24 meses', months: 24,
    hint: '3.772 clientes · histórico 2 años' },
]

type Phase = 'idle' | 'loading' | 'ready'

export default function SalesV2GloriaDemoPage() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [selectedSlug, setSelectedSlug] = useState('12m')
  const [report, setReport] = useState<SalesReportV2Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isFirstRun, setIsFirstRun] = useState(true)

  const loadReportFor = useCallback(async (slug: string) => {
    setError(null)
    try {
      const res = await fetch(`/demo/sales-v2-gloria-${slug}.json`, { cache: 'no-store' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const raw = await res.text()
      const parsed = parseSalesReportV2(raw)
      if (!parsed) {
        setError('JSON inválido o schema no coincide.')
        return null
      }
      setReport(parsed)
      return parsed
    } catch (e) {
      setError(String(e))
      return null
    }
  }, [])

  const runDiagnostic = useCallback(async (slug: string) => {
    setSelectedSlug(slug)
    setPhase('loading')
    // Pre-fetch in parallel with the animation — by the time the stages finish,
    // the JSON is ready, so the transition to `ready` feels instant.
    loadReportFor(slug)
  }, [loadReportFor])

  const onProgressComplete = useCallback(() => {
    setPhase('ready')
    setIsFirstRun(false)
  }, [])

  const switchPeriod = useCallback(async (slug: string) => {
    if (slug === selectedSlug) return
    setSelectedSlug(slug)
    setPhase('loading')
    loadReportFor(slug)
  }, [selectedSlug, loadReportFor])

  return (
    <div style={{ background: T.bg.primary, minHeight: '100vh' }}>
      {phase === 'idle' && <IdleScreen periods={PERIODS} onRun={runDiagnostic}
        selectedSlug={selectedSlug} onSelect={setSelectedSlug} />}

      {phase === 'loading' && (
        <PipelineProgress
          stages={isFirstRun ? FULL_STAGES : SHORT_STAGES}
          onComplete={onProgressComplete}
        />
      )}

      {phase === 'ready' && report && (
        <div style={{ maxWidth: 1100, margin: '0 auto', fontFamily: T.font.display }}>
          <PeriodBar periods={PERIODS} selectedSlug={selectedSlug} onChange={switchPeriod} />
          <SalesReportV2 report={report} />
        </div>
      )}

      {error && (
        <div style={{
          padding: T.space.lg, margin: T.space.lg,
          background: `${T.accent.red}10`, border: `1px solid ${T.accent.red}33`,
          borderRadius: T.radius.md, color: T.accent.red, maxWidth: 1100,
          marginLeft: 'auto', marginRight: 'auto',
        }}>
          Error cargando datos: {error}
          <br />
          <span style={{ fontSize: 11, opacity: 0.8 }}>
            Ejecutar: <code>python3 scripts/generate_sales_report_v2_gloria.py --batch</code>
          </span>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Idle screen — "Run diagnostic" CTA with period picker
// ─────────────────────────────────────────────────────────────────────

function IdleScreen({
  periods, selectedSlug, onSelect, onRun,
}: {
  periods: Period[]
  selectedSlug: string
  onSelect: (s: string) => void
  onRun: (s: string) => void
}) {
  return (
    <div
      style={{
        maxWidth: 640,
        margin: '0 auto',
        padding: `${T.space.xxl} ${T.space.lg}`,
        fontFamily: T.font.display,
      }}
    >
      <div
        style={{
          fontSize: 11, color: T.text.tertiary,
          textTransform: 'uppercase', letterSpacing: 1.5,
        }}
      >
        Valinor · Demo en vivo
      </div>
      <h1
        style={{
          fontSize: 34, margin: `${T.space.sm} 0 ${T.space.md}`,
          color: T.text.primary, lineHeight: 1.15, fontWeight: 600,
        }}
      >
        Diagnóstico comercial de <span style={{ color: T.accent.teal }}>Gloria</span>
      </h1>
      <p
        style={{
          fontSize: 15, color: T.text.secondary, marginBottom: T.space.xl,
          lineHeight: 1.5,
        }}
      >
        Valinor conecta a la base Openbravo real (260.060 facturas), ejecuta 13 queries
        paramétricas, corre un swarm de agentes de análisis, y entrega un reporte
        estructurado de ventas con RFM, HHI, Magic Matrix y call list priorizada.
      </p>

      <div style={{ marginBottom: T.space.xl }}>
        <div
          style={{
            fontSize: 11, color: T.text.tertiary,
            textTransform: 'uppercase', letterSpacing: 1.2, marginBottom: T.space.sm,
          }}
        >
          Período a analizar
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
          {periods.map((p) => (
            <PeriodCard
              key={p.slug}
              period={p}
              selected={p.slug === selectedSlug}
              onClick={() => onSelect(p.slug)}
            />
          ))}
        </div>
      </div>

      <button
        onClick={() => onRun(selectedSlug)}
        style={{
          background: T.accent.teal,
          color: T.text.inverse,
          border: 'none',
          padding: `${T.space.md} ${T.space.xl}`,
          borderRadius: T.radius.md,
          fontSize: 15,
          fontWeight: 600,
          fontFamily: T.font.display,
          cursor: 'pointer',
          width: '100%',
          letterSpacing: 0.3,
          transition: 'transform 120ms ease, opacity 120ms ease',
        }}
        onMouseDown={(e) => (e.currentTarget.style.transform = 'scale(0.98)')}
        onMouseUp={(e) => (e.currentTarget.style.transform = 'scale(1)')}
        onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
      >
        Ejecutar diagnóstico →
      </button>

      <div
        style={{
          marginTop: T.space.md, fontSize: 11,
          color: T.text.tertiary, fontFamily: T.font.mono, textAlign: 'center',
        }}
      >
        Datos reales · PostgreSQL · ~14 segundos
      </div>
    </div>
  )
}

function PeriodCard({
  period, selected, onClick,
}: {
  period: Period
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      style={{
        textAlign: 'left',
        background: selected ? 'var(--color-bg-surface)' : 'transparent',
        border: selected ? `1px solid ${T.accent.teal}` : T.border.card,
        borderRadius: T.radius.md,
        padding: T.space.md,
        cursor: 'pointer',
        fontFamily: T.font.display,
        transition: 'all 160ms ease',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div
            style={{
              fontSize: 15, fontWeight: 500,
              color: T.text.primary, marginBottom: 2,
            }}
          >
            {period.label}
          </div>
          <div
            style={{
              fontSize: 12, color: T.text.tertiary, fontFamily: T.font.mono,
            }}
          >
            {period.hint}
          </div>
        </div>
        <div
          style={{
            width: 16, height: 16, borderRadius: '50%',
            border: `2px solid ${selected ? T.accent.teal : 'var(--color-border-card)'}`,
            background: selected ? T.accent.teal : 'transparent',
            flexShrink: 0,
          }}
        />
      </div>
    </button>
  )
}

// ─────────────────────────────────────────────────────────────────────
// Period bar — persistent header shown on the ready state
// ─────────────────────────────────────────────────────────────────────

function PeriodBar({
  periods, selectedSlug, onChange,
}: {
  periods: Period[]
  selectedSlug: string
  onChange: (slug: string) => void
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: `${T.space.md} ${T.space.lg}`,
        borderBottom: T.border.subtle,
        fontFamily: T.font.display,
        background: 'var(--color-bg-surface)',
      }}
    >
      <div>
        <div
          style={{
            fontSize: 10, color: T.text.tertiary,
            textTransform: 'uppercase', letterSpacing: 1.2,
          }}
        >
          Período
        </div>
        <div style={{ fontSize: 14, color: T.text.primary, marginTop: 2 }}>
          {periods.find((p) => p.slug === selectedSlug)?.label ?? ''}
        </div>
      </div>
      <div style={{ display: 'flex', gap: T.space.xs }}>
        {periods.map((p) => {
          const active = p.slug === selectedSlug
          return (
            <button
              key={p.slug}
              onClick={() => onChange(p.slug)}
              style={{
                background: active ? T.accent.teal : 'transparent',
                color: active ? T.text.inverse : T.text.secondary,
                border: active ? 'none' : T.border.card,
                borderRadius: T.radius.sm,
                padding: `${T.space.xs} ${T.space.md}`,
                fontSize: 12,
                fontFamily: T.font.mono,
                cursor: active ? 'default' : 'pointer',
                transition: 'all 120ms ease',
              }}
            >
              {p.slug}
            </button>
          )
        })}
      </div>
    </div>
  )
}
