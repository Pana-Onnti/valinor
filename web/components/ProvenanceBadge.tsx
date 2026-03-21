'use client'

import { T } from '@/components/d4c/tokens'

export interface ProvenanceBadgeProps {
  score: number
  source: string
  tag: string
}

// [94/100 · GL accounts · FINAL]
export function ProvenanceBadge({ score, source, tag }: ProvenanceBadgeProps) {
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      fontSize: 11,
      fontFamily: T.font.mono,
      color: T.text.tertiary,
      backgroundColor: T.bg.elevated,
      border: T.border.subtle,
      borderRadius: T.radius.sm,
      padding: '2px 8px',
    }}>
      <span>{score}/100</span>
      <span style={{ opacity: 0.4 }}>·</span>
      <span>{source}</span>
      <span style={{ opacity: 0.4 }}>·</span>
      <span style={{ fontWeight: 600, color: T.text.secondary }}>{tag}</span>
    </span>
  )
}
