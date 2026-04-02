'use client'

/**
 * SheetSelector.tsx
 * Tab-style button group for Excel sheet selection.
 */

import { T } from '@/components/d4c/tokens'

// ── Component ─────────────────────────────────────────────────────────────────

export interface SheetSelectorProps {
  sheets: string[]
  activeSheet: string
  onChange: (sheet: string) => void
}

export default function SheetSelector({ sheets, activeSheet, onChange }: SheetSelectorProps) {
  if (sheets.length === 0) return null

  return (
    <div style={{
      display: 'flex',
      flexWrap: 'wrap',
      gap: T.space.xs,
      padding: `${T.space.sm} ${T.space.md}`,
      borderBottom: `1px solid ${T.bg.hover}`,
      backgroundColor: T.bg.card,
    }}>
      <span style={{
        fontSize: 11,
        fontWeight: 600,
        color: T.text.tertiary,
        fontFamily: T.font.display,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        alignSelf: 'center',
        marginRight: T.space.xs,
        whiteSpace: 'nowrap',
      }}>
        Hoja:
      </span>

      {sheets.map((sheet) => {
        const isActive = sheet === activeSheet
        return (
          <button
            key={sheet}
            onClick={() => onChange(sheet)}
            style={{
              padding: '4px 12px',
              borderRadius: T.radius.sm,
              border: isActive
                ? `1px solid ${T.accent.teal}60`
                : `1px solid ${T.bg.hover}`,
              backgroundColor: isActive
                ? `${T.accent.teal}18`
                : T.bg.elevated,
              color: isActive ? T.accent.teal : T.text.secondary,
              fontSize: 12,
              fontWeight: isActive ? 600 : 400,
              fontFamily: T.font.display,
              cursor: 'pointer',
              transition: 'all 0.15s',
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={e => {
              if (!isActive) {
                e.currentTarget.style.backgroundColor = T.bg.hover
                e.currentTarget.style.color = T.text.primary
              }
            }}
            onMouseLeave={e => {
              if (!isActive) {
                e.currentTarget.style.backgroundColor = T.bg.elevated
                e.currentTarget.style.color = T.text.secondary
              }
            }}
          >
            {sheet}
          </button>
        )
      })}
    </div>
  )
}
