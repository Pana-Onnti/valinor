/**
 * tokens.ts — D4C Design System tokens
 * Fuente única de verdad para colores, tipografía y espaciado.
 * Todo output visual D4C usa estos valores. Sin excepciones.
 */

export const T = {
  // ── Backgrounds (lightened 1 stop for better contrast ratios) ────────────
  bg: {
    primary:  '#0E0E14',   // capa base — slightly raised from pure void
    card:     '#15151C',   // superficie de card — visible separation
    elevated: '#1E1E28',   // hover, tooltips, elementos anidados
    hover:    '#282838',   // estado activo/presionado
  },

  // ── Text (secondary/tertiary raised for WCAG AA compliance) ────────────
  text: {
    primary:   '#F0F0F5',  // headings, hero numbers
    secondary: '#9A9AAA',  // body text, descripciones — WCAG AA on bg-card
    tertiary:  '#6A6A7A',  // labels, captions, metadata — improved readability
    inverse:   '#0E0E14',  // texto sobre fondos claros/accent
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

  // ── Borders (updated to match lightened bg tokens) ──────────────────────
  border: {
    subtle: '1px solid #1E1E28',
    card:   '1px solid #282838',
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
  grid: '#1E1E2840',
  text: T.text.tertiary,
  tooltip: { bg: T.bg.elevated, border: T.bg.hover, text: T.text.primary },
}
