'use client'

import { useState } from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

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

  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-4 hover:shadow-md transition-all">
      <p className="text-xs text-gray-400 mb-1 truncate">{label}</p>
      <p className="text-lg font-bold text-gray-900 dark:text-white leading-none mb-2">
        {latestPoint?.value || '—'}
      </p>

      {numeric.length >= 2 && (
        <svg width="120" height="32" className="mb-2 overflow-visible">
          <path
            d={sparklinePath(numeric)}
            fill="none"
            stroke={trend === 'up' ? '#10b981' : trend === 'down' ? '#ef4444' : '#6b7280'}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}

      <div className="flex items-center gap-1 text-xs">
        {trend === 'up' && <TrendingUp className="h-3 w-3 text-emerald-500" />}
        {trend === 'down' && <TrendingDown className="h-3 w-3 text-red-500" />}
        {trend === 'flat' && <Minus className="h-3 w-3 text-gray-400" />}
        <span className={
          trend === 'up' ? 'text-emerald-600 dark:text-emerald-400' :
          trend === 'down' ? 'text-red-600 dark:text-red-400' : 'text-gray-400'
        }>
          {dataPoints.length} períodos
        </span>
      </div>
    </div>
  )
}
