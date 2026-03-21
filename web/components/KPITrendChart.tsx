'use client'

import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

interface DataPoint {
  period: string
  value: string
  numeric_value?: number | null
  run_date: string
}

interface KPITrendChartProps {
  label: string
  dataPoints: DataPoint[]
}

function sparklinePath(values: number[], width = 120, height = 32): string {
  if (values.length < 2) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const step = width / (values.length - 1)
  const points = values.map((v, i) => {
    const x = i * step
    const y = height - ((v - min) / range) * height
    return `${x},${y}`
  })
  return `M${points.join(' L')}`
}

export function KPITrendChart({ label, dataPoints }: KPITrendChartProps) {
  const numeric = dataPoints
    .map(d => d.numeric_value)
    .filter((v): v is number => v != null)

  const last = numeric[numeric.length - 1]
  const prev = numeric[numeric.length - 2]
  const trend = prev != null && last != null
    ? last > prev ? 'up' : last < prev ? 'down' : 'flat'
    : 'flat'

  const latestPoint = dataPoints[dataPoints.length - 1]
  const trendColor = trend === 'up' ? T.accent.teal : trend === 'down' ? T.accent.red : T.text.tertiary

  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.md,
      border: T.border.card,
      padding: T.space.md,
    }}>
      <p style={{ fontSize: 11, color: T.text.tertiary, marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {label}
      </p>
      <p style={{ fontSize: 18, fontWeight: 700, color: T.text.primary, lineHeight: 1, marginBottom: 8, fontFamily: T.font.mono }}>
        {latestPoint?.value || '—'}
      </p>

      {numeric.length >= 2 && (
        <svg width="120" height="32" style={{ display: 'block', marginBottom: 8, overflow: 'visible' }}>
          <path
            d={sparklinePath(numeric)}
            fill="none"
            stroke={trendColor}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {trend === 'up'   && <TrendingUp  size={12} style={{ color: trendColor }} />}
        {trend === 'down' && <TrendingDown size={12} style={{ color: trendColor }} />}
        {trend === 'flat' && <Minus        size={12} style={{ color: trendColor }} />}
        <span style={{ fontSize: 11, color: trendColor }}>{dataPoints.length} períodos</span>
      </div>
    </div>
  )
}
