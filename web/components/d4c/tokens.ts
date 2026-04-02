/**
 * tokens.ts — D4C Design System tokens
 * Fuente única de verdad para colores, tipografía y espaciado.
 * Todo output visual D4C usa estos valores. Sin excepciones.
 *
 * Colors reference CSS custom properties defined in globals.css,
 * enabling dark/light mode via [data-theme] on <html>.
 */

export const T = {
  // ── Backgrounds ───────────────────────────────────────────────────────────
  bg: {
    primary:  'var(--color-bg-base)',
    card:     'var(--color-bg-surface)',
    elevated: 'var(--color-bg-elevated)',
    hover:    'var(--color-bg-hover)',
  },

  // ── Text ──────────────────────────────────────────────────────────────────
  text: {
    primary:   'var(--color-text-primary)',
    secondary: 'var(--color-text-secondary)',
    tertiary:  'var(--color-text-tertiary)',
    inverse:   'var(--color-text-inverse)',
  },

  // ── Accents ───────────────────────────────────────────────────────────────
  accent: {
    teal:   'var(--color-accent-teal)',
    red:    'var(--color-accent-red)',
    yellow: 'var(--color-accent-yellow)',
    orange: 'var(--color-accent-orange)',
    blue:   'var(--color-accent-blue)',
    purple: 'var(--color-accent-purple)',
  },

  // ── Borders ───────────────────────────────────────────────────────────────
  border: {
    subtle: '1px solid var(--color-border-subtle)',
    card:   '1px solid var(--color-border-card)',
  },

  // ── Radius ────────────────────────────────────────────────────────────────
  radius: {
    sm: '8px',
    md: '12px',
    lg: '16px',
  },

  // ── Spacing ───────────────────────────────────────────────────────────────
  space: {
    xs:  '4px',
    sm:  '8px',
    md:  '16px',
    lg:  '24px',
    xl:  '32px',
    xxl: '48px',
  },

  // ── Fonts ─────────────────────────────────────────────────────────────────
  font: {
    display: "'Sora', 'DM Sans', system-ui, sans-serif",
    mono:    "'DM Mono', 'Fira Code', monospace",
  },
} as const

/** Mapeo severity → color accent */
export const SEV_COLOR: Record<string, string> = {
  CRITICAL: T.accent.red,
  HIGH:     T.accent.orange,
  MEDIUM:   T.accent.yellow,
  LOW:      T.accent.blue,
  INFO:     T.accent.blue,
  OK:       T.accent.teal,
}

/** Badge label en español */
export const SEV_LABEL: Record<string, string> = {
  CRITICAL: 'Crítico',
  HIGH:     'Alto',
  MEDIUM:   'Medio',
  LOW:      'Bajo',
  INFO:     'Info',
  OK:       'OK',
}

/** Recharts theme */
export const CHART_THEME = {
  colors: [T.accent.teal, T.accent.red, T.accent.yellow, T.accent.orange, T.accent.blue],
  background: T.bg.card,
  grid: 'var(--color-chart-grid)',
  text: T.text.tertiary,
  tooltip: { bg: T.bg.elevated, border: T.bg.hover, text: T.text.primary },
}
