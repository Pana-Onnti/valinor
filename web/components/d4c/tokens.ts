/**
 * tokens.ts — D4C Design System tokens
 * Fuente única de verdad para colores, tipografía y espaciado.
 * Todo output visual D4C usa estos valores. Sin excepciones.
 */

export const T = {
  // ── Backgrounds ─────────────────────────────────────────────────────────────
  bg: {
    primary:  '#0A0A0F',   // capa base — deep void
    card:     '#111116',   // superficie de card
    elevated: '#1A1A22',   // hover, tooltips, elementos anidados
    hover:    '#222230',   // estado activo/presionado
  },

  // ── Text ────────────────────────────────────────────────────────────────────
  text: {
    primary:   '#F0F0F5',  // headings, hero numbers
    secondary: '#8A8A9A',  // body text, descripciones
    tertiary:  '#5A5A6A',  // labels, captions, metadata
    inverse:   '#0A0A0F',  // texto sobre fondos claros/accent
  },

  // ── Accents ─────────────────────────────────────────────────────────────────
  accent: {
    teal:   '#2A9D8F',     // Valinor brand, success, CTA primario
    red:    '#E63946',     // CRITICAL, loss framing, danger
    yellow: '#E9C46A',     // WARNING, highlights secundarios
    orange: '#F4845F',     // MEDIUM severity
    blue:   '#85B7EB',     // INFO, datos neutros
    purple: '#9B5DE5',     // dev/interno, epics
  },

  // ── Borders ─────────────────────────────────────────────────────────────────
  border: {
    subtle: '1px solid #1A1A22',
    card:   '1px solid #222230',
  },

  // ── Radius ──────────────────────────────────────────────────────────────────
  radius: {
    sm: '8px',
    md: '12px',
    lg: '16px',
  },

  // ── Spacing ─────────────────────────────────────────────────────────────────
  space: {
    xs:  '4px',
    sm:  '8px',
    md:  '16px',
    lg:  '24px',
    xl:  '32px',
    xxl: '48px',
  },

  // ── Fonts ───────────────────────────────────────────────────────────────────
  font: {
    display: "'Inter', 'DM Sans', system-ui, sans-serif",
    mono:    "'JetBrains Mono', 'Fira Code', monospace",
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
  grid: '#1A1A2240',
  text: T.text.tertiary,
  tooltip: { bg: T.bg.elevated, border: T.bg.hover, text: T.text.primary },
}
