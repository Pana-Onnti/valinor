'use client'

import { T } from '@/components/d4c/tokens'

/* ── Shimmer keyframes (injected once) ───────────────────────────────────── */
const SHIMMER_ID = 'd4c-shimmer-keyframes'

function ensureShimmerStyle() {
  if (typeof document === 'undefined') return
  if (document.getElementById(SHIMMER_ID)) return
  const style = document.createElement('style')
  style.id = SHIMMER_ID
  style.textContent = `
    @keyframes d4c-shimmer {
      0% { background-position: -200% 0; }
      100% { background-position: 200% 0; }
    }
  `
  document.head.appendChild(style)
}

/* ── Base Skeleton ───────────────────────────────────────────────────────── */

interface SkeletonProps {
  width?: string
  height?: string
  radius?: string
}

export function Skeleton({
  width = '100%',
  height = '16px',
  radius = T.radius.sm,
}: SkeletonProps) {
  ensureShimmerStyle()

  return (
    <div
      aria-hidden="true"
      style={{
        width,
        height,
        borderRadius: radius,
        background: `linear-gradient(
          90deg,
          ${T.bg.elevated} 25%,
          ${T.bg.hover} 50%,
          ${T.bg.elevated} 75%
        )`,
        backgroundSize: '200% 100%',
        animation: 'd4c-shimmer 1.5s ease-in-out infinite',
      }}
    />
  )
}

/* ── Composed Skeletons ──────────────────────────────────────────────────── */

export function SkeletonCard() {
  return (
    <div
      style={{
        width: '100%',
        height: 120,
        borderRadius: T.radius.md,
        border: T.border.card,
        backgroundColor: T.bg.card,
        padding: T.space.md,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.sm,
      }}
    >
      <Skeleton width="40%" height="14px" />
      <Skeleton width="70%" height="12px" />
      <Skeleton width="55%" height="12px" />
    </div>
  )
}

export function SkeletonKPIRow() {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: T.space.md,
        width: '100%',
      }}
    >
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            borderRadius: T.radius.md,
            border: T.border.card,
            backgroundColor: T.bg.card,
            padding: T.space.md,
            display: 'flex',
            flexDirection: 'column',
            gap: T.space.sm,
          }}
        >
          <Skeleton width="50%" height="12px" />
          <Skeleton width="70%" height="24px" />
          <Skeleton width="40%" height="10px" />
        </div>
      ))}
    </div>
  )
}

export function SkeletonFindingList() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm, width: '100%' }}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            borderRadius: T.radius.md,
            border: T.border.card,
            backgroundColor: T.bg.card,
            padding: T.space.md,
            display: 'flex',
            flexDirection: 'column',
            gap: T.space.xs,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
            <Skeleton width="60px" height="20px" radius="9999px" />
            <Skeleton width="40%" height="14px" />
          </div>
          <Skeleton width="90%" height="12px" />
          <Skeleton width="75%" height="12px" />
        </div>
      ))}
    </div>
  )
}

export function SkeletonText({ lines }: { lines: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.xs, width: '100%' }}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i}>
          <Skeleton
            width={i === lines - 1 ? '60%' : '100%'}
            height="12px"
          />
        </div>
      ))}
    </div>
  )
}
