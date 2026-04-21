'use client'

import { useEffect, useRef, useState } from 'react'
import { T } from '@/components/d4c/tokens'

export type Stage = {
  id: string
  label: string
  detail?: string
  durationMs: number
}

type Props = {
  stages: Stage[]
  onComplete: () => void
}

/**
 * Animated pipeline progress timeline. Advances sequentially through `stages`,
 * calling `onComplete` after the last one. Designed for a live-feeling demo:
 * each stage has an active state with a pulsing dot, completed stages show a
 * check, and the elapsed time keeps ticking at the top so viewers feel the flow.
 *
 * The timings here are cosmetic — they don't actually gate any work — but they
 * mirror the real pipeline stages (DQ Gate, Query Builder, Analysis agents,
 * Narrator) so the demo stays honest about what Valinor does.
 *
 * Refs: VAL-158
 */
export default function PipelineProgress({ stages, onComplete }: Props) {
  const [currentIdx, setCurrentIdx] = useState(0)
  const [elapsedMs, setElapsedMs] = useState(0)
  const startRef = useRef<number>(Date.now())

  useEffect(() => {
    startRef.current = Date.now()
    const tick = setInterval(() => {
      setElapsedMs(Date.now() - startRef.current)
    }, 50)
    return () => clearInterval(tick)
  }, [])

  useEffect(() => {
    if (currentIdx >= stages.length) {
      const t = setTimeout(onComplete, 400)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setCurrentIdx((i) => i + 1), stages[currentIdx].durationMs)
    return () => clearTimeout(t)
  }, [currentIdx, stages, onComplete])

  const totalMs = stages.reduce((a, s) => a + s.durationMs, 0)
  const progressPct = Math.min(100, (elapsedMs / totalMs) * 100)

  return (
    <div
      style={{
        padding: T.space.xl,
        maxWidth: 720,
        margin: '0 auto',
        fontFamily: T.font.mono,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'baseline',
          marginBottom: T.space.md,
          fontFamily: T.font.display,
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: 1.2 }}>
            Valinor · Diagnóstico en curso
          </div>
          <div style={{ fontSize: 22, color: T.text.primary, fontWeight: 600, marginTop: 4 }}>
            Gloria · postgresql://tad@localhost:5432
          </div>
        </div>
        <div style={{ fontSize: 12, color: T.text.tertiary, fontFamily: T.font.mono }}>
          {(elapsedMs / 1000).toFixed(1)}s
        </div>
      </div>

      {/* Progress bar */}
      <div
        style={{
          height: 2,
          background: 'var(--color-border-subtle)',
          borderRadius: 1,
          overflow: 'hidden',
          marginBottom: T.space.lg,
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${progressPct}%`,
            background: T.accent.teal,
            transition: 'width 60ms linear',
          }}
        />
      </div>

      {/* Stage list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
        {stages.map((stage, i) => {
          const status = i < currentIdx ? 'done' : i === currentIdx ? 'active' : 'pending'
          return <StageRow key={stage.id} stage={stage} status={status} />
        })}
      </div>
    </div>
  )
}

function StageRow({
  stage,
  status,
}: {
  stage: Stage
  status: 'done' | 'active' | 'pending'
}) {
  const color =
    status === 'done' ? T.accent.teal : status === 'active' ? T.accent.teal : T.text.tertiary
  const opacity = status === 'pending' ? 0.4 : 1

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: T.space.md,
        padding: `${T.space.sm} ${T.space.md}`,
        background: status === 'active' ? 'var(--color-bg-surface)' : 'transparent',
        borderRadius: T.radius.sm,
        border: status === 'active' ? `1px solid ${T.accent.teal}33` : '1px solid transparent',
        opacity,
        transition: 'opacity 240ms ease, background 240ms ease, border-color 240ms ease',
      }}
    >
      <StatusDot status={status} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 14,
            color: status === 'pending' ? T.text.tertiary : T.text.primary,
            fontFamily: T.font.display,
            fontWeight: status === 'active' ? 500 : 400,
          }}
        >
          {stage.label}
        </div>
        {stage.detail && (
          <div
            style={{
              marginTop: 2,
              fontSize: 11,
              color: T.text.tertiary,
              fontFamily: T.font.mono,
            }}
          >
            {stage.detail}
          </div>
        )}
      </div>
      {status === 'done' && (
        <span style={{ color, fontSize: 11, fontFamily: T.font.mono }}>OK</span>
      )}
      {status === 'active' && (
        <span style={{ color, fontSize: 11, fontFamily: T.font.mono }}>…</span>
      )}
    </div>
  )
}

function StatusDot({ status }: { status: 'done' | 'active' | 'pending' }) {
  const size = 10
  const baseStyle: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: '50%',
    flexShrink: 0,
    marginTop: 4,
  }
  if (status === 'done') {
    return <span style={{ ...baseStyle, background: T.accent.teal }} />
  }
  if (status === 'active') {
    return (
      <span style={{ position: 'relative', display: 'inline-flex', marginTop: 4 }}>
        <span
          style={{
            ...baseStyle,
            marginTop: 0,
            background: T.accent.teal,
            animation: 'd4c-pulse 1.2s ease-in-out infinite',
          }}
        />
        <span
          aria-hidden
          style={{
            position: 'absolute',
            inset: 0,
            width: size,
            height: size,
            borderRadius: '50%',
            background: T.accent.teal,
            opacity: 0.25,
            animation: 'd4c-ring 1.2s ease-out infinite',
          }}
        />
        <style>{`
          @keyframes d4c-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.25); } }
          @keyframes d4c-ring { 0% { transform: scale(1); opacity: 0.4; } 100% { transform: scale(2.4); opacity: 0; } }
        `}</style>
      </span>
    )
  }
  return <span style={{ ...baseStyle, background: 'var(--color-border-card)' }} />
}

/**
 * Canonical stages reflecting Valinor's real pipeline. Durations are tuned so
 * the first run lands ~14s (substantial, not rushed), subsequent period switches
 * use a compressed stage list (see SHORT_STAGES) around ~5s.
 */
export const FULL_STAGES: Stage[] = [
  { id: 'connect', label: 'Conectando a la base de datos',
    detail: 'postgresql://tad@localhost:5432/gloria', durationMs: 700 },
  { id: 'discover', label: 'Descubriendo esquema',
    detail: '7 entidades · 3 relaciones · FK inference', durationMs: 1400 },
  { id: 'dq', label: 'Data Quality Gate',
    detail: '8 checks · score 100/100', durationMs: 1200 },
  { id: 'build', label: 'Construyendo queries paramétricas',
    detail: '13 queries · 5 para sales v2 (RFM, HHI, cross-sell, churn)', durationMs: 1100 },
  { id: 'exec', label: 'Ejecutando queries contra PostgreSQL',
    detail: '260.060 facturas · 2.104 clientes', durationMs: 2400 },
  { id: 'agents', label: 'Analysis agents (Analyst · Sentinel · Hunter)',
    detail: 'Swarm paralelo · 29 findings', durationMs: 3200 },
  { id: 'recon', label: 'Reconciliation',
    detail: 'Conflict detection · 0 conflicts', durationMs: 700 },
  { id: 'narrator', label: 'Sales narrator v2',
    detail: 'RFM + HHI + Magic Matrix + call list priorizada', durationMs: 2100 },
  { id: 'render', label: 'Componiendo reporte',
    detail: 'Structured JSON → React', durationMs: 500 },
]

/** Shorter list shown when the user switches period without a full "cold start". */
export const SHORT_STAGES: Stage[] = [
  { id: 'rebuild', label: 'Re-ejecutando queries para el nuevo período',
    detail: 'Rolling window recalculado', durationMs: 1400 },
  { id: 'reagents', label: 'Re-analyst + sentinel + hunter',
    detail: 'Incremental · cache entity_map', durationMs: 2000 },
  { id: 'renarrate', label: 'Regenerando narrativa de ventas',
    detail: 'Sales v2 JSON', durationMs: 1100 },
  { id: 'rerender', label: 'Actualizando reporte',
    durationMs: 400 },
]
