'use client'

import { T } from '@/components/d4c/tokens'

export interface DQScoreBadgeProps {
  score: number
  label: string
  tag: string
  warnings?: string[]
  compact?: boolean
}

function scoreAccent(score: number): string {
  if (score >= 90) return T.accent.teal
  if (score >= 75) return T.accent.yellow
  if (score >= 50) return T.accent.orange
  return T.accent.red
}

function scoreSymbol(score: number): string {
  if (score >= 90) return '✓'
  if (score >= 75) return '!'
  if (score >= 50) return '!'
  return '✕'
}

// Compact pill: [✓ 94 CONFIRMED · FINAL]
function CompactPill({ score, label, tag }: Pick<DQScoreBadgeProps, 'score' | 'label' | 'tag'>) {
  const color = scoreAccent(score)
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      fontSize: 11,
      fontWeight: 500,
      fontFamily: T.font.mono,
      padding: '3px 10px',
      borderRadius: 999,
      border: `1px solid ${color}40`,
      backgroundColor: color + '15',
      color,
    }}>
      <span style={{ fontWeight: 700 }}>{scoreSymbol(score)}</span>
      <span style={{ fontWeight: 700 }}>{score}</span>
      <span>{label}</span>
      <span style={{ opacity: 0.5 }}>·</span>
      <span>{tag}</span>
    </span>
  )
}

// Circular score ring using SVG
function ScoreRing({ score }: { score: number }) {
  const color = scoreAccent(score)
  const radius = 28
  const circumference = 2 * Math.PI * radius
  const filled = (score / 100) * circumference

  return (
    <div style={{ position: 'relative', width: 80, height: 80, flexShrink: 0 }}>
      <svg width="80" height="80" viewBox="0 0 72 72" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="36" cy="36" r={radius} fill="none" strokeWidth="6" stroke={T.bg.hover} />
        <circle
          cx="36" cy="36" r={radius}
          fill="none"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          stroke={color}
        />
      </svg>
      <div style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <span style={{ fontSize: 18, fontWeight: 700, color, fontFamily: T.font.mono }}>{score}</span>
        <span style={{ fontSize: 10, color: T.text.tertiary, lineHeight: 1 }}>/100</span>
      </div>
    </div>
  )
}

// Full card mode
function FullCard({ score, label, tag, warnings }: DQScoreBadgeProps) {
  const color = scoreAccent(score)
  const shownWarnings = warnings?.slice(0, 2) ?? []

  return (
    <div style={{
      borderRadius: T.radius.md,
      border: `1px solid ${color}40`,
      backgroundColor: color + '10',
      padding: T.space.lg,
      display: 'flex',
      alignItems: 'flex-start',
      gap: T.space.lg,
    }}>
      <ScoreRing score={score} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const, marginBottom: 4 }}>
          <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' as const, color }}>
            {label}
          </span>
          <span style={{ color: T.text.tertiary }}>·</span>
          <span style={{
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: '0.08em',
            textTransform: 'uppercase' as const,
            padding: '2px 8px',
            borderRadius: 999,
            border: `1px solid ${color}40`,
            backgroundColor: color + '15',
            color,
            fontFamily: T.font.mono,
          }}>
            {tag}
          </span>
        </div>
        <p style={{ fontSize: 12, color: T.text.secondary, marginBottom: T.space.sm }}>
          Calidad de datos del análisis
        </p>
        {shownWarnings.length > 0 && (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {shownWarnings.map((w, i) => (
              <li key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 6, fontSize: 12, color }}>
                <span style={{ flexShrink: 0, marginTop: 1 }}>{scoreSymbol(score)}</span>
                <span style={{ opacity: 0.8 }}>{w}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

export function DQScoreBadge({ score, label, tag, warnings, compact = false }: DQScoreBadgeProps) {
  if (compact) return <CompactPill score={score} label={label} tag={tag} />
  return <FullCard score={score} label={label} tag={tag} warnings={warnings} />
}
