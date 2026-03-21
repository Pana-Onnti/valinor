'use client'

export interface ProvenanceBadgeProps {
  score: number
  source: string
  tag: string
}

// [94/100 · GL accounts · FINAL]
export function ProvenanceBadge({ score, source, tag }: ProvenanceBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-gray-400 dark:text-gray-500 font-mono bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5">
      <span>{score}/100</span>
      <span className="opacity-50">·</span>
      <span>{source}</span>
      <span className="opacity-50">·</span>
      <span className="font-semibold">{tag}</span>
    </span>
  )
}
