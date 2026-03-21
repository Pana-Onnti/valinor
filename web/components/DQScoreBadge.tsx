'use client'

export interface DQScoreBadgeProps {
  score: number
  label: string
  tag: string
  warnings?: string[]
  compact?: boolean
}

function scoreColor(score: number): {
  bg: string
  border: string
  text: string
  ring: string
  icon: string
} {
  if (score >= 90) return {
    bg: 'bg-emerald-50 dark:bg-emerald-900/20',
    border: 'border-emerald-200 dark:border-emerald-800',
    text: 'text-emerald-700 dark:text-emerald-300',
    ring: 'text-emerald-500',
    icon: '✓',
  }
  if (score >= 75) return {
    bg: 'bg-amber-50 dark:bg-amber-900/20',
    border: 'border-amber-200 dark:border-amber-800',
    text: 'text-amber-700 dark:text-amber-300',
    ring: 'text-amber-500',
    icon: '⚠',
  }
  if (score >= 50) return {
    bg: 'bg-orange-50 dark:bg-orange-900/20',
    border: 'border-orange-200 dark:border-orange-800',
    text: 'text-orange-700 dark:text-orange-300',
    ring: 'text-orange-500',
    icon: '!',
  }
  return {
    bg: 'bg-red-50 dark:bg-red-900/20',
    border: 'border-red-200 dark:border-red-800',
    text: 'text-red-700 dark:text-red-300',
    ring: 'text-red-500',
    icon: '✕',
  }
}

// Compact pill: [✓ 94 CONFIRMED · FINAL]
function CompactPill({ score, label, tag }: Pick<DQScoreBadgeProps, 'score' | 'label' | 'tag'>) {
  const c = scoreColor(score)
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full border ${c.bg} ${c.border} ${c.text}`}
    >
      <span className="font-bold">{c.icon}</span>
      <span className="font-bold">{score}</span>
      <span>{label}</span>
      <span className="opacity-60">·</span>
      <span>{tag}</span>
    </span>
  )
}

// Circular score ring using SVG
function ScoreRing({ score }: { score: number }) {
  const c = scoreColor(score)
  const radius = 28
  const circumference = 2 * Math.PI * radius
  const filled = (score / 100) * circumference

  return (
    <div className="relative w-20 h-20 flex-shrink-0">
      <svg className="w-20 h-20 -rotate-90" viewBox="0 0 72 72">
        {/* Track */}
        <circle
          cx="36" cy="36" r={radius}
          fill="none"
          strokeWidth="6"
          className="stroke-gray-200 dark:stroke-gray-700"
        />
        {/* Progress */}
        <circle
          cx="36" cy="36" r={radius}
          fill="none"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          className={c.ring}
          stroke="currentColor"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className={`text-xl font-bold ${c.text}`}>{score}</span>
        <span className="text-xs text-gray-400 leading-none">/100</span>
      </div>
    </div>
  )
}

// Full card mode
function FullCard({ score, label, tag, warnings }: DQScoreBadgeProps) {
  const c = scoreColor(score)
  const shownWarnings = warnings?.slice(0, 2) ?? []

  return (
    <div className={`rounded-2xl border p-5 flex items-start gap-5 ${c.bg} ${c.border}`}>
      <ScoreRing score={score} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          <span className={`text-sm font-bold uppercase tracking-wide ${c.text}`}>{label}</span>
          <span className="text-gray-300 dark:text-gray-600">·</span>
          <span className={`text-xs font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border ${c.bg} ${c.border} ${c.text}`}>
            {tag}
          </span>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          Calidad de datos del análisis
        </p>
        {shownWarnings.length > 0 && (
          <ul className="space-y-1">
            {shownWarnings.map((w, i) => (
              <li key={i} className={`flex items-start gap-1.5 text-xs ${c.text}`}>
                <span className="flex-shrink-0 mt-0.5">{c.icon}</span>
                <span className="opacity-80">{w}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

export function DQScoreBadge({ score, label, tag, warnings, compact = false }: DQScoreBadgeProps) {
  if (compact) {
    return <CompactPill score={score} label={label} tag={tag} />
  }
  return <FullCard score={score} label={label} tag={tag} warnings={warnings} />
}
